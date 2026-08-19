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
    path = PARQUET_DIR / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found - run `python analysis_scripts/build_parquet.py "
            f"--output-dir output/processed/rffm_parquet` first, or a season/table "
            f"that hasn't been through the Parquet ETL yet."
        )
    return pd.read_parquet(path)


@lru_cache(maxsize=None)
def _load_sharded_season(name: str, season: str) -> pd.DataFrame | None:
    path = PARQUET_DIR / name / f"{season}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _stringify(df: pd.DataFrame) -> pd.DataFrame:
    """Match pd.read_csv(..., dtype=str): every value is either a Python
    str or real NaN - never "5373769.0"/"<NA>" as literal text.

    Deliberately vectorized `.astype(str)` per column, not `.apply(lambda
    v: str(v))`: apply() on a nullable Int16/Int32 column that contains any
    NA silently upcasts through numpy float64 for its internal fast path
    once the column is large enough (confirmed on this dataset - a 3-row
    slice stayed int, the real ~578k-row column did not), turning e.g.
    sex_raw's "0" into "0.0". astype(str) does not do this and correctly
    preserves real NaN (not the literal text "nan"/"<NA>") for missing
    values - verified against this dataset's actual null columns."""
    out = {col: df[col].astype(str) for col in df.columns}
    return pd.DataFrame(out, index=df.index).reset_index(drop=True)


def read_table(name: str, season: str | None = None, category: str | None = None) -> pd.DataFrame:
    """Returns a DataFrame shaped like the original per-season/per-category
    CSV read. `season`/`category` are ignored where the table doesn't carry
    that dimension (e.g. players is global; flat tables have no category)."""
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
