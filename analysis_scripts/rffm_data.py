"""
Compatibility layer over output/processed/rffm_parquet/ (build_parquet.py's
output) for report generators that currently do
`pd.read_csv(BASE / season / "<table>.csv", dtype=str)`.

read_table(name, season=..., category=...) returns a DataFrame with the
same columns (in the same order) and the same all-string/NaN values that
call would have produced, so a report generator can switch its data source
by changing the read call only — join keys, clean()/norm_id() helpers, and
every downstream computation stay untouched.

Intentional differences from the CSV originals:
  - `source_url` is absent from every analytical table (build_parquet.py
    drops it - 100% derivable from IDs). Grep-verified harmless: only
    analysis_scripts/retry_check.py used it, and it doesn't build the
    site. `scraped_at` IS kept (parsed to a real timestamp), but stringifies
    with a space instead of the original's "T" date/time separator
    (str(pd.Timestamp) formatting, not a data difference) - moot for the
    site today since no report generator reads it, kept for archival/
    ad hoc-query completeness (see build_parquet.py's module docstring).
    crawl_log/data_quality_report keep source_url too - there it's the
    audit record of what was fetched, not a derivable convenience.
  - read_table("players") takes no `season` and returns a table deduped to
    one row per player_id (player_id is a stable identity - DATA_
    DICTIONARY.md: "stable identity only") instead of the original's one
    row per (player_id, season). Safe for the common case - every report
    that just does a player_id -> name/birth_year lookup dict.
    player_career.py's compute_career_index() is different: it picks each
    player's *earliest* recorded birth_year by walking seasons in order,
    so it needs the original per-season shape rather than "latest value
    only" - use read_table("players_by_season", season=...) for that (and
    anything else season-order-sensitive): same one-row-per-(player_id,
    season) shape as the CSVs, not deduped. In practice this dataset has
    zero players whose birth_year genuinely changes across seasons once
    compared numerically (build_parquet.py's build_players_table checked
    directly) - the CSVs' raw text does disagree for 18,594 players
    ("1991" one season, "1991.0" another - the same upstream float-
    serialization artifact matches.py's matchday/scores carry), which is
    why compute_career_index() vs its Parquet-backed port still won't
    match byte-for-byte on birth_year: the original keeps the ".0" noise,
    the Parquet path cleans it via real int typing. players_by_season is
    still the right table for this pattern (defensive - if a genuine
    conflict ever does appear in future data, per-season history is what
    lets "earliest" be computed correctly at all), it just turned out this
    dataset's actual risk was formatting noise, not real disagreement.

Usage:
    import rffm_data as data
    matches = data.read_table("matches", season="2025-2026")
    lineups = data.read_table("match_lineups", season="2025-2026", category="CADETE")
    teams = data.read_table("teams", season="2025-2026")
    players = data.read_table("players")                              # global identity lookup
    players_2025 = data.read_table("players_by_season", season="2025-2026")  # original per-season shape
"""

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

PARQUET_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm_parquet"

# Tables with no `season` column in the original CSV (season is purely a
# directory-name artifact of build_parquet.py) - dropped after filtering
# so the returned shape matches pd.read_csv(season_dir / f"{name}.csv").
NO_SEASON_COLUMN_IN_ORIGINAL = {
    "teams", "venues", "clubs", "players_by_season", "game_types", "seasons",
    "manifest_groups", "manifest_pages", "manifest_endpoints",
}

# Category-sharded enrichment tables: build_parquet.py writes these as one
# file per season (<name>/<season>.parquet), not one combined file, so
# they need a different, season-required load path - see build_parquet.py's
# module docstring ("Category-sharded enrichment dirs") for why.
SHARDED_TABLES = {"match_lineups", "match_goals", "match_cards", "match_staff", "match_officials"}

# Everything else that carries a `season` dimension is ALSO one Parquet file
# per season now (<name>/<season>.parquet) - build_parquet.py stopped
# writing these as one combined file for the same reason as SHARDED_TABLES
# above: an unchanged season's file then stays byte-identical across
# rebuilds, instead of git seeing the whole (binary, non-delta-friendly)
# table as "changed" every time any one season's crawl adds new rows. Same
# season-required load path as SHARDED_TABLES, just without category_base.
SEASON_PARTITIONED_TABLES = {
    "matches", "standings", "scorers", "groups", "competitions",
    "team_group_membership", "player_competition_participation", "player_season_stats",
    "teams", "venues", "clubs", "game_types", "seasons",
    "manifest_groups", "manifest_pages", "manifest_endpoints",
    "players_by_season", "crawl_log", "data_quality_report",
}


@lru_cache(maxsize=None)
def _load(name: str) -> pd.DataFrame:
    # Unbounded is fine here (unlike the two caches below): this is only
    # ever called for the small, flat, cross-season table names in
    # NO_SEASON_COLUMN_IN_ORIGINAL/etc. (players, clubs_extended, ...) -
    # bounded by how many *table names* exist, not by season count, so it
    # can never accumulate the way a per-season cache does.
    path = PARQUET_DIR / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found - run `python analysis_scripts/build_parquet.py "
            f"--output-dir output/processed/rffm_parquet` first, or a season/table "
            f"that hasn't been through the Parquet ETL yet."
        )
    return pd.read_parquet(path)


@lru_cache(maxsize=96)
def _load_sharded_season(name: str, season: str) -> pd.DataFrame | None:
    # Bounded (unlike the module's original maxsize=None here) - see
    # _read_table_cached's docstring for why maxsize=None across a 10-season
    # build_site.py run is what actually OOM-killed a real CI runner (15GB
    # RAM ceiling, confirmed via df/free logging added to pages-deploy.yml).
    # This layer's raw Parquet loads are individually cheap (compact
    # category/Int16/Int32 dtypes - a whole season of match_lineups across
    # every category is ~65MB), so 96 is generous headroom over one season's
    # ~20-30 distinct (name, season) entries, not a tight bound.
    path = PARQUET_DIR / name / f"{season}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _stringify(df: pd.DataFrame) -> pd.DataFrame:
    """Match pd.read_csv(..., dtype=str): every value is either a Python
    str or real NaN - never "5373769.0"/"<NA>" as literal text.

    A plain vectorized `.astype(str)` per column (this function's original
    form) looks right printed - `print()` renders a real missing pd.NA and
    the literal 4-character string "<NA>" identically - but they are not
    the same thing: `Series([1, 2, None], dtype="Int32").astype(str)` turns
    the missing slot into the *literal string* "<NA>", which
    clean()/norm_id()'s `pd.isna(v)` check (every report generator's
    null-guard, including this file's own callers) does not catch, since
    isna("<NA>") is False. Confirmed on real data: matches.parquet's
    home_team_id has 12,383 genuine nulls (bye-match placeholder) at the
    raw Parquet level, and read_table("matches", ...) silently reported
    ZERO before this fix - every one had turned into the text "<NA>" and
    was passing every "is this missing" check as if it were a real team id.
    `.apply(lambda v: str(v))` doesn't fix this either and reintroduces the
    OTHER bug this function was written to dodge: on a nullable Int16/Int32
    column, apply()'s internal fast path silently upcasts through numpy
    float64 once the column is large enough (confirmed on this dataset - a
    3-row slice stayed int, the real ~578k-row column did not), turning
    e.g. sex_raw's "0" into "0.0".

    The actual fix: go through `.astype(object)` first (a real Python
    int/bool/str per cell, real None for any missing slot - no upcast,
    since object dtype has no numeric fast path to trigger it), THEN
    stringify only the non-None cells. Gets both properties at once.

    One more pandas-3.x gotcha layered on top of that, found the same way
    as build_parquet.py's compact_types() one (see its own comment):
    `Series.map()` infers the RESULT column's dtype too, and for an
    all-string(-or-None) object column pandas 3.x aggressively infers
    `StringDtype` right there, before the value even reaches a DataFrame -
    and under StringDtype, a missing slot silently becomes a raw Python
    `float('nan')` instead of staying `None`/`pd.NA` (confirmed: `.dtype`
    on the `.map()` result alone, with no DataFrame involved yet, already
    reads "str"). `.itertuples()` (every _v2 report generator's read
    pattern) then hands that nan back verbatim. Confirmed on real data:
    matches.parquet's home_team_id, 2,144 genuine nulls for 2025-2026 alone
    - every one came back as `float('nan')` through `.itertuples()`,
    invisible to any `v is None` check (including this file's own
    docstring example above, and team_participation_map_v2.py's `clean()`)
    and fatal to `json.dumps(..., allow_nan=False)`. Once `.map()`/
    `.astype(str)` has already inferred StringDtype, the None is gone for
    good - a later `.astype(object)` on the result just relabels the dtype
    without restoring it (tried, checked, didn't work). Skipping the
    inference entirely fixes it - the first version of this fix did that
    with a plain per-cell Python list comprehension, which is correct but
    measured ~7s to stringify one 578k-row/13-column table (every read_table
    call pays this, so every report build compounds it into minutes). The
    version below gets the same guarantee - never construct a Series/array
    that pandas could infer as StringDtype - without a Python-level loop:
    stringify through numpy's `.astype(str)` on only the *non-null* slice of
    a plain object-dtype numpy array (numpy's own C loop, not pandas
    dtype-inferring machinery), assign back in place, and hand the finished
    numpy object array to the Series constructor with an explicit
    `dtype=object`. Measured ~150x faster on the same column, byte-for-byte
    identical output.

    One more layer on top of that (found via py-spy, once the above got
    _stringify() to the top of a full site-build profile): `.astype(str)`
    on an object array doesn't stay object dtype - numpy scans for the
    longest resulting string and materializes a *fixed-width* `<U...>`
    unicode array (elements become `numpy.str_`, not `str`), even when
    every value already IS a `str` (e.g. a category column's values,
    already real Python strings straight out of `.astype(object)` above -
    confirmed by inspecting element types directly). That extra width-scan-
    and-repack is pure waste for anything already string-shaped, and it's
    most of what real report data is (names, addresses, category labels -
    numeric/ID columns are the minority). `np.frompyfunc(str, 1, 1)` calls
    the exact same `str()` per non-null element (verified byte-identical
    output across all 237 real Parquet tables/every column - including the
    float64 lat/lon columns above, where `str()` is what actually produces
    the 17-significant-digit text either way) but returns a plain object
    array - no width scan, no repack, and the elements come back as genuine
    `str` instead of `numpy.str_`. Measured ~1.5x faster in aggregate across
    every real table (up to ~12x on a single high-cardinality text column
    like a player name), zero value/null/type mismatches."""
    out = {}
    for col in df.columns:
        s = df[col]
        arr = s.astype(object).where(s.notna(), None).to_numpy(dtype=object, copy=False)
        not_none = arr != None  # noqa: E711 - elementwise identity check over an object array, not a scalar `is`
        arr = arr.copy()
        arr[not_none] = np.frompyfunc(str, 1, 1)(arr[not_none])
        out[col] = pd.Series(arr, index=df.index, dtype=object)
    return pd.DataFrame(out, index=df.index).reset_index(drop=True)


@lru_cache(maxsize=64)
def _read_table_cached(name: str, season: str | None, category: str | None) -> pd.DataFrame:
    if name in SHARDED_TABLES or name in SEASON_PARTITIONED_TABLES:
        if season is None:
            raise ValueError(f"{name} is season-sharded on disk - season= is required")
        df = _load_sharded_season(name, season)
        if df is None:
            cols = ["category_base"] if name in SHARDED_TABLES else []
            return _stringify(pd.DataFrame(columns=cols))  # empty, matches "dir missing" originals
        if category is not None and "category_base" in df.columns:
            df = df[df["category_base"] == category].drop(columns=["category_base"])
        if name in NO_SEASON_COLUMN_IN_ORIGINAL and "season" in df.columns:
            df = df.drop(columns=["season"])
        return _stringify(df)

    df = _load(name)

    if name == "players":
        return _stringify(df)

    if category is not None and "category_base" in df.columns:
        df = df[df["category_base"] == category]
        df = df.drop(columns=["category_base"])

    return _stringify(df)


def read_table(name: str, season: str | None = None, category: str | None = None) -> pd.DataFrame:
    """Returns a DataFrame shaped like the original per-season/per-category
    CSV read. `season`/`category` are ignored where the table doesn't carry
    that dimension (e.g. players is global; flat tables have no category).

    Cached (LRU, maxsize=64, keyed on the exact name/season/category triple)
    - measured motivation: _stringify() alone costs ~5.5s for a single
    (table, season, category) combination at typical match_lineups size, and
    up to 6 different _v2.py report generators independently call read_table
    with the IDENTICAL (name, season, category) during one build_site.py run
    (each doing its own join against match_lineups/match_goals/match_cards -
    see PARQUET_CLOSURE.md's sibling investigation into where site-build time
    actually goes). The raw Parquet read was already cached one layer down
    (_load/_load_sharded_season), but re-running _stringify() on every call
    was not - this closes that gap.

    Bounded, not maxsize=None: _stringify()'s output is real Python
    str/None per cell, not the compact category/Int16/Int32 dtypes the
    underlying Parquet read caches - measured one season's stringified
    match_lineups/match_goals/match_cards alone (every category) at ~1.4GB.
    An unbounded cache across a 10-season build_site.py run is exactly what
    OOM-killed a real CI runner (confirmed via df/free logging added to
    pages-deploy.yml: RAM climbed from ~1GB to the 15GB ceiling over ~20
    minutes, runner killed by "shutdown signal" rather than a clean Python
    MemoryError). 64 comfortably covers one season's ~20-30 distinct
    (name, season, category) entries - the intra-season, cross-generator
    reuse this cache exists for - while bounding steady-state memory to
    roughly 1-2 seasons' worth instead of all 10 at once. A season that
    scrolls out of the LRU window just pays the ~5.5s rebuild again, not a
    correctness cost.

    Always returns `.copy()`, never the cached object directly: audited
    (grep) and confirmed several report generators mutate a read_table()
    result's columns in place (e.g. weird_scores_report_v2.py's
    `goals["minute"] = pd.to_numeric(...)` runs directly on the DataFrame
    read_table returned, no intervening copy) - sharing the cached object
    across callers would let one report's in-place edit corrupt what every
    other report sees for the same (name, season, category). Measured the
    copy cost specifically to make sure it doesn't eat the win: ~85ms for a
    DataFrame that costs ~5.5s to rebuild from scratch, ~65x cheaper."""
    return _read_table_cached(name, season, category).copy()


def list_categories(name: str, season: str) -> list[str]:
    """Category files build_sharded_season() would have globbed for this
    season, e.g. list_categories("match_lineups", "2025-2026") mirrors
    what `(BASE / season / "match_lineups").glob("*.csv")` used to give."""
    if name in SHARDED_TABLES:
        df = _load_sharded_season(name, season)
        return sorted(df["category_base"].unique().tolist()) if df is not None else []
    if name in SEASON_PARTITIONED_TABLES:
        raise ValueError(f"{name} is season-partitioned but has no category_base column")
    df = _load(name)
    if "season" not in df.columns or "category_base" not in df.columns:
        raise ValueError(f"{name} has no per-season/category shards")
    return sorted(df.loc[df["season"] == season, "category_base"].unique().tolist())


def list_seasons(name: str) -> list[str]:
    if name in SHARDED_TABLES or name in SEASON_PARTITIONED_TABLES:
        return sorted(p.stem for p in (PARQUET_DIR / name).glob("*.parquet"))
    df = _load(name)
    if "season" not in df.columns:
        raise ValueError(f"{name} has no season column")
    return sorted(df["season"].unique().tolist())
