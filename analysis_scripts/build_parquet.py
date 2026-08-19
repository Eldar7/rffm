#!/usr/bin/env python3
"""
Converts every CSV under output/processed/rffm/<season>/ into a small set of
compact, lossless Parquet tables — one file per table, concatenated across
all seasons, EXCEPT the category-sharded enrichment tables (match_lineups
etc.), which are one file per season (see "Category-sharded enrichment
dirs" below for why) — for the planned duckdb-wasm frontend (SQL queries
over static files in the browser instead of the current hand-sharded JSON
per report).

Not wired into any report yet: this only produces the Parquet files. Run it
independently to inspect output size; analysis_scripts/build_site.py does
not read from here (yet).

Column handling, same rules validated by hand on this dataset before writing
this script:
  - Drop `source_url` on the analytical tables only (100% derivable from
    IDs, e.g. an acta-partido URL is just
    https://www.rffm.es/acta-partido/{match_id} — see README.md).
    `scraped_at` is kept and parsed to a real timestamp (measured cost:
    +42MB/+20% over the whole dataset - accepted, since per-row scrape
    time isn't reconstructible any other way once the CSVs are gone).
    crawl_log/data_quality_report/manifest_* (see below) keep their own
    `source_url`/`url` columns too - there it's the actual audit record of
    what was fetched, not a derivable join convenience.
  - Season-sharded tables (one CSV per season, e.g. matches.csv) already
    carry `season`/`season_id` — kept as-is.
  - Per-season tables with no season column (teams.csv, venues.csv,
    clubs.csv) get `season` injected from the directory name, since a
    team/club row means "as seen in that season's crawl" (see CLAUDE.md:
    clubs/venues aren't category-scoped but ARE season-scoped — a new
    season's crawl writes its own copy) and metadata genuinely varies by
    season (e.g. team_cards.py/player_cards.py note club_name_raw sponsor
    suffixes changing ~20% of the time for the same team_id) — deduping
    these across seasons would silently lose real history.
  - players.csv is different: player_id is a *stable, timeless* identity
    (see DATA_DICTIONARY.md: "stable identity only"), so unlike
    teams/clubs/venues it IS deduped to one row per player_id instead of
    kept per-season — concatenating it the same way as teams.csv would
    otherwise produce ~3.2 rows/player on average (983,407 rows for
    303,968 distinct players, checked on the real dataset) and silently
    fan out every join through player_id. The most-recent season's
    `player_name`/`birth_year` is kept (see build_players_table for why
    there's no conflict-flagging column here despite an earlier version
    having one).
  - Category-sharded enrichment dirs (match_lineups/<CATEGORY>.csv etc.)
    get `category_base` injected from the path, and are written out one
    Parquet file per season (output/processed/rffm_parquet/match_lineups/
    <season>.parquet) rather than one file for all 10 seasons combined -
    combined, match_lineups alone crossed 100MB (GitHub's hard per-file
    push limit, hit for real committing this) with room to spare for
    nothing but 2-3 more seasons of growth. Per-season files mirror how
    output/processed/rffm/<season>/ itself is already partitioned, so a
    new season's crawl only ever adds one new small file instead of
    requiring the combined file to be rewritten (and re-approaching the
    limit) every time.
  - crawl_log.csv/acta_crawl_log.csv/fichajugador_crawl_log.csv/
    clubs_crawl_log.csv (identical schema, four separate files per season -
    DATA_DICTIONARY.md's "Three intentionally separate crawl_log/quality-
    report families": core's crawl_log.csv is rebuilt from scratch every
    main.py run, the other three grow incrementally and double as the
    crawler's resumability marker, so they must stay separate ON DISK as
    CSVs - that constraint doesn't apply to this read-only derived Parquet
    copy) are concatenated into one `crawl_log` table with `season` +
    `log_family` ("core"/"acta"/"fichajugador"/"clubs") injected - the
    docstring's own suggestion ("want a unified view? pd.concat() at
    analysis time") is exactly what this does, just once instead of
    per-query. Same treatment for the four data_quality_report.csv
    variants -> one `data_quality_report` table.
  - manifest_groups.csv/manifest_pages.csv/manifest_endpoints.csv have no
    source_url/scraped_at columns to worry about and no season column
    inside (crawl discovery output, one file per season) - handled exactly
    like teams.csv/venues.csv/clubs.csv (PER_SEASON_TABLES).
  - Numeric-looking columns are downcast to the smallest int type that
    fits (checked against the real min/max in this dataset, not assumed).
  - Object columns with fewer distinct values than half the row count
    become pandas `category` dtype before writing, so Parquet's own
    dictionary encoding doesn't have to discover that on its own (mostly a
    memory-during-conversion optimization; Parquet would dictionary-encode
    repeated strings either way).

Usage:
    python analysis_scripts/build_parquet.py --output-dir site/data/parquet
"""

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
SEASON_RE = re.compile(r"^\d{4}-\d{4}$")

DROP_COLS = ["source_url"]

# One CSV per season, season/season_id columns already inside.
FLAT_TABLES = [
    "matches.csv", "standings.csv", "scorers.csv", "groups.csv",
    "competitions.csv", "team_group_membership.csv",
    "player_competition_participation.csv",
    # site-reported season aggregates per player (DATA_DICTIONARY.md) - not
    # read by any current report generator (grep-verified), but real
    # analytical data, not crawl provenance, so it belongs in the compact
    # copy on the same "don't silently drop site data" grounds as
    # everything else here.
    "player_season_stats.csv",
]

# One CSV per season, no season column inside -> inject from dir name.
# players.csv is handled separately (build_players_table) — deduped by
# player_id instead, see module docstring.
PER_SEASON_TABLES = [
    "teams.csv", "venues.csv", "clubs.csv",
    # RFFM's own small reference lists (game type id -> name, season id ->
    # name + date range) - re-fetched by every crawl, not read by any
    # report generator today (grep-verified; matches.csv/competitions.csv
    # already carry game_type/season as denormalized text, no join needed
    # for current use), kept per-season rather than deduped like teams/
    # venues/clubs since there's no reason to assume the site's own list
    # is perfectly stable across years (a new season_id gets added every
    # year, by definition).
    "game_types.csv", "seasons.csv",
    # Crawl discovery manifests - what the crawler found on the site before
    # deciding what to fetch. No source_url/scraped_at columns, so DROP_COLS
    # is a no-op for these; listed here purely as documentation of that.
    "manifest_groups.csv", "manifest_pages.csv", "manifest_endpoints.csv",
]

# Same schema in all five, one file per season each - see module docstring
# ("Three intentionally separate crawl_log/quality-report families") -
# except "club_profiles", which lives once at output/processed/rffm/ (not
# per-season), same reasoning as CROSS_SEASON_TABLES below.
# (log_family, filename) pairs.
CRAWL_LOG_FAMILIES = [
    ("core", "crawl_log.csv"), ("acta", "acta_crawl_log.csv"),
    ("fichajugador", "fichajugador_crawl_log.csv"), ("clubs", "clubs_crawl_log.csv"),
]
DATA_QUALITY_REPORT_FAMILIES = [
    ("core", "data_quality_report.csv"), ("acta", "acta_data_quality_report.csv"),
    ("fichajugador", "fichajugador_data_quality_report.csv"), ("clubs", "clubs_data_quality_report.csv"),
]
CROSS_SEASON_CRAWL_LOG_FAMILY = ("club_profiles", "club_profiles_crawl_log.csv")
CROSS_SEASON_DATA_QUALITY_REPORT_FAMILY = ("club_profiles", "club_profiles_data_quality_report.csv")

# One CSV per (season, category) under a subdirectory -> inject both.
SHARDED_DIRS = ["match_lineups", "match_goals", "match_cards", "match_staff", "match_officials"]

# Cross-season append-only snapshot logs living once at output/processed/
# rffm/ (like coverage_manifest.csv), not inside any season directory -
# enrich_club_profiles.py's targets are the union of club_id across every
# season's clubs.csv, not one season's crawl, and every fetch (initial or a
# later --force-refetch) appends a new scraped_at-stamped row rather than
# overwriting, so there's no "season" to inject and no per-season file to
# glob - just read the one file as-is.
CROSS_SEASON_TABLES = ["clubs_extended.csv", "club_teams.csv"]


def list_seasons() -> list[str]:
    return sorted(d.name for d in BASE.iterdir() if d.is_dir() and SEASON_RE.match(d.name))


TIMESTAMP_COLS = {"scraped_at", "timestamp"}


def compact_types(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    for col in df.columns:
        # pandas >=2.something / 3.x: dtype=str on read_csv gives the
        # `string`/StringDtype extension type, not numpy `object` - a bare
        # `dtype != object` check (what earlier pandas needed) silently
        # skips every column under this pandas version, so nothing here
        # actually got downcast. is_string_dtype catches both.
        if not pd.api.types.is_string_dtype(df[col]):
            continue
        if col in TIMESTAMP_COLS:
            df[col] = pd.to_datetime(df[col], format="ISO8601", utc=True)
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        non_null = df[col].notna()
        if (numeric.notna() == non_null).all() and non_null.any():
            if (numeric.dropna() % 1 == 0).all():
                lo, hi = numeric.min(), numeric.max()
                for dtype in ("int16", "int32", "int64"):
                    limits = np.iinfo(dtype)
                    if lo >= limits.min and hi <= limits.max:
                        df[col] = numeric.astype(f"Int{dtype[3:]}")
                        break
            else:
                # float64/"double", not float32: venues.latitude/longitude
                # carry up to 17 significant digits in the source CSV (e.g.
                # "-3.818636699999999") - float32's ~7 significant digits
                # would silently truncate real precision on exactly the
                # field DATA_DICTIONARY.md calls out as "exact... not
                # geocoded". Confirmed on the real data: float32 changed
                # every single venue's coordinates measurably; float64
                # round-trips them exactly.
                df[col] = numeric.astype("float64")
        elif df[col].nunique(dropna=True) < max(n * 0.5, 1):
            df[col] = df[col].astype("category")
    return df


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", low_memory=False)
    return df.drop(columns=[c for c in DROP_COLS if c in df.columns])


def read_csv_raw(path: Path) -> pd.DataFrame:
    """Like read_csv() but keeps every column, including source_url/url -
    for crawl_log/data_quality_report, where that's the audit record of
    what was actually fetched, not a derivable analytical convenience."""
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig", low_memory=False)


def build_flat_table(name: str, seasons: list[str]) -> pd.DataFrame | None:
    frames = []
    for season in seasons:
        f = BASE / season / name
        if f.exists():
            frames.append(read_csv(f))
    if not frames:
        return None
    return compact_types(pd.concat(frames, ignore_index=True))


def build_per_season_table(name: str, seasons: list[str]) -> pd.DataFrame | None:
    frames = []
    for season in seasons:
        f = BASE / season / name
        if not f.exists():
            continue
        df = read_csv(f)
        df.insert(0, "season", season)
        frames.append(df)
    if not frames:
        return None
    return compact_types(pd.concat(frames, ignore_index=True))


def build_players_table(seasons: list[str]) -> pd.DataFrame | None:
    """players.csv, deduped to one row per player_id (see module docstring
    for why this table alone gets this treatment). Takes the most recent
    season's player_name/birth_year for each player_id.

    No conflict-flagging here: an earlier version added a
    `birth_year_conflict` column for player_ids where birth_year disagreed
    across seasons, but checked-and-confirmed on this dataset that's 0
    players once compared numerically (a naive raw-string comparison
    flagged 18,594 - every one of them the same ".0" float-serialization
    artifact matches.py's matchday/scores carry, not a real disagreement -
    see module docstring). Nothing read the column either. If a genuine
    conflict ever does show up in future data, players_by_season already
    has the full per-season history to find it with a plain
    `GROUP BY player_id HAVING COUNT(DISTINCT birth_year) > 1` - a
    dedicated flag column for a problem that provably doesn't exist here,
    checked by nothing, was solving a hypothetical twice over."""
    frames = []
    for season in seasons:
        f = BASE / season / "players.csv"
        if not f.exists():
            continue
        df = read_csv(f)
        df["season"] = season
        frames.append(df)
    if not frames:
        return None

    all_rows = pd.concat(frames, ignore_index=True)
    all_rows = all_rows.sort_values("season")
    deduped = all_rows.drop_duplicates("player_id", keep="last").drop(columns=["season"])
    return compact_types(deduped.reset_index(drop=True))


def build_sharded_season(dirname: str, season: str) -> pd.DataFrame | None:
    """One season's worth of a category-sharded enrichment dir, all
    categories concatenated with `category_base` injected - the unit
    build_sharded_table() below writes one Parquet file per (see module
    docstring for why per-season rather than one combined file)."""
    d = BASE / season / dirname
    if not d.exists():
        return None
    frames = []
    for f in sorted(d.glob("*.csv")):
        df = read_csv(f)
        df.insert(0, "category_base", f.stem)
        frames.append(df)
    if not frames:
        return None
    return compact_types(pd.concat(frames, ignore_index=True))


def build_family_log_table(
    families: list[tuple[str, str]], seasons: list[str],
    cross_season_family: tuple[str, str] | None = None,
) -> pd.DataFrame | None:
    """crawl_log/data_quality_report: same schema across 4 per-season files
    (core/acta/fichajugador/clubs - see module docstring), concatenated
    with `season` + `log_family` injected. Uses read_csv_raw() - not
    read_csv() - so source_url survives (it's the audit trail here, not a
    redundant join key).

    cross_season_family (e.g. club_profiles) is a 5th, optional family
    whose log lives once at output/processed/rffm/ instead of per-season -
    same file, same schema, just read once with `season` left null rather
    than glob a season directory that doesn't apply to it."""
    frames = []
    for family, filename in families:
        for season in seasons:
            f = BASE / season / filename
            if not f.exists():
                continue
            try:
                df = read_csv_raw(f)
            except pd.errors.EmptyDataError:
                # A handful of these are a stray byte or two (not exactly
                # 0-length) with no header at all - e.g.
                # 2020-2021/acta_data_quality_report.csv is 1 byte - rather
                # than guess a size cutoff, just skip whatever pandas
                # itself can't find a header row in.
                continue
            df.insert(0, "log_family", family)
            df.insert(0, "season", season)
            frames.append(df)
    if cross_season_family:
        family, filename = cross_season_family
        f = BASE / filename
        if f.exists():
            try:
                df = read_csv_raw(f)
                df.insert(0, "log_family", family)
                df.insert(0, "season", None)
                frames.append(df)
            except pd.errors.EmptyDataError:
                pass
    if not frames:
        return None
    return compact_types(pd.concat(frames, ignore_index=True))


def build_cross_season_table(name: str) -> pd.DataFrame | None:
    """clubs_extended.csv/club_teams.csv - a single append-only file at
    output/processed/rffm/ (see CROSS_SEASON_TABLES), not per-season."""
    f = BASE / name
    if not f.exists():
        return None
    return compact_types(read_csv(f))


def main():
    parser = argparse.ArgumentParser(description="Convert RFFM CSVs to compact Parquet tables")
    parser.add_argument("--output-dir", default="site/data/parquet")
    parser.add_argument("--compression-level", type=int, default=15)
    args = parser.parse_args()

    out_dir = Path(__file__).parent.parent / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    seasons = list_seasons()
    print(f"{len(seasons)} seasons: {seasons[0]}..{seasons[-1]}")

    total_csv_bytes = 0
    total_parquet_bytes = 0

    def write(table_name: str, df: pd.DataFrame | None):
        nonlocal total_parquet_bytes
        if df is None or df.empty:
            print(f"  skip {table_name}: no data")
            return
        out = out_dir / f"{table_name}.parquet"
        df.to_parquet(out, compression="zstd", compression_level=args.compression_level, index=False)
        size = out.stat().st_size
        total_parquet_bytes += size
        print(f"  {table_name:<32} {len(df):>9,} rows -> {size / 1e6:8.2f} MB")

    print("Flat tables (one CSV/season, season column already present):")
    for name in FLAT_TABLES:
        write(name.removesuffix(".csv"), build_flat_table(name, seasons))

    print("Per-season tables (season injected from directory):")
    for name in PER_SEASON_TABLES:
        write(name.removesuffix(".csv"), build_per_season_table(name, seasons))

    print("Players (deduped to one row per player_id, see module docstring):")
    write("players", build_players_table(seasons))

    print("Players by season (NOT deduped - mirrors the original per-season"
          " players.csv exactly, for season-order-sensitive call sites like"
          " player_career.py's earliest-known-birth_year logic - defensive:"
          " this dataset has zero players whose birth_year genuinely changes"
          " across seasons, but per-season history is what would let"
          " 'earliest' stay correct if that's ever not true):")
    write("players_by_season", build_per_season_table("players.csv", seasons))

    print("Category-sharded enrichment tables (one Parquet file per season, category_base injected):")
    for dirname in SHARDED_DIRS:
        total_rows = 0
        total_bytes_this_table = 0
        for season in seasons:
            df = build_sharded_season(dirname, season)
            if df is None or df.empty:
                continue
            season_dir = out_dir / dirname
            season_dir.mkdir(parents=True, exist_ok=True)
            out = season_dir / f"{season}.parquet"
            df.to_parquet(out, compression="zstd", compression_level=args.compression_level, index=False)
            size = out.stat().st_size
            total_parquet_bytes += size
            total_bytes_this_table += size
            total_rows += len(df)
        print(f"  {dirname:<32} {total_rows:>9,} rows -> {total_bytes_this_table / 1e6:8.2f} MB "
              f"across {len(seasons)} files")

    print("Cross-season tables (single append-only file at output/processed/rffm/,"
          " not per-season - see module docstring):")
    for name in CROSS_SEASON_TABLES:
        write(name.removesuffix(".csv"), build_cross_season_table(name))

    print("Crawl audit tables (4 per-season families + 1 cross-season family concatenated,"
          " log_family injected, source_url kept - see module docstring):")
    write("crawl_log", build_family_log_table(CRAWL_LOG_FAMILIES, seasons, CROSS_SEASON_CRAWL_LOG_FAMILY))
    write("data_quality_report", build_family_log_table(
        DATA_QUALITY_REPORT_FAMILIES, seasons, CROSS_SEASON_DATA_QUALITY_REPORT_FAMILY
    ))

    for pattern in ["*/matches.csv", "*/standings.csv", "*/scorers.csv", "*/groups.csv",
                     "*/competitions.csv", "*/team_group_membership.csv",
                     "*/player_competition_participation.csv", "*/player_season_stats.csv",
                     "*/teams.csv", "*/venues.csv", "*/game_types.csv", "*/seasons.csv",
                     "*/manifest_groups.csv", "*/manifest_pages.csv", "*/manifest_endpoints.csv",
                     "*/players.csv", "*/clubs.csv", "*/match_lineups/*.csv", "*/match_goals/*.csv",
                     "*/match_cards/*.csv", "*/match_staff/*.csv", "*/match_officials/*.csv",
                     "*/crawl_log.csv", "*/acta_crawl_log.csv", "*/fichajugador_crawl_log.csv",
                     "*/clubs_crawl_log.csv", "*/data_quality_report.csv",
                     "*/acta_data_quality_report.csv", "*/fichajugador_data_quality_report.csv",
                     "*/clubs_data_quality_report.csv"]:
        total_csv_bytes += sum(f.stat().st_size for f in BASE.glob(pattern))
    for name in [*CROSS_SEASON_TABLES, "club_profiles_crawl_log.csv", "club_profiles_data_quality_report.csv"]:
        f = BASE / name
        if f.exists():
            total_csv_bytes += f.stat().st_size

    print(f"\nTotal: {total_csv_bytes / 1e6:.0f} MB CSV -> {total_parquet_bytes / 1e6:.0f} MB Parquet "
          f"({total_csv_bytes / max(total_parquet_bytes, 1):.1f}x)")


if __name__ == "__main__":
    main()
