#!/usr/bin/env python3
"""
Converts every CSV under output/processed/rffm/<season>/ into a small set of
compact, lossless Parquet tables — one file per table, concatenated across
all seasons — for the planned duckdb-wasm frontend (SQL queries over static
files in the browser instead of the current hand-sharded JSON per report).

Not wired into any report yet: this only produces the Parquet files. Run it
independently to inspect output size; analysis_scripts/build_site.py does
not read from here (yet).

Column handling, same rules validated by hand on this dataset before writing
this script:
  - Drop `source_url` (100% derivable from IDs, e.g. an acta-partido URL is
    just https://www.rffm.es/acta-partido/{match_id} — see README.md) and
    `scraped_at` (crawl provenance, not analytical; per-stage freshness
    already lives in coverage_manifest.csv, not needed per-row here).
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
    `player_name`/`birth_year` is kept; `birth_year` genuinely disagrees
    across seasons for 18,616 players (6% — the site itself edits birth
    years sometimes, not a crawl bug), so a `birth_year_conflict` column
    flags those instead of silently picking a value.
  - Category-sharded enrichment dirs (match_lineups/<CATEGORY>.csv etc.)
    get both `season` and `category_base` injected from the path, since
    neither is a column inside those CSVs.
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

DROP_COLS = ["source_url", "scraped_at"]

# One CSV per season, season/season_id columns already inside.
FLAT_TABLES = [
    "matches.csv", "standings.csv", "scorers.csv", "groups.csv",
    "competitions.csv", "team_group_membership.csv",
    "player_competition_participation.csv",
]

# One CSV per season, no season column inside -> inject from dir name.
# players.csv is handled separately (build_players_table) — deduped by
# player_id instead, see module docstring.
PER_SEASON_TABLES = ["teams.csv", "venues.csv", "clubs.csv"]

# One CSV per (season, category) under a subdirectory -> inject both.
SHARDED_DIRS = ["match_lineups", "match_goals", "match_cards", "match_staff", "match_officials"]


def list_seasons() -> list[str]:
    return sorted(d.name for d in BASE.iterdir() if d.is_dir() and SEASON_RE.match(d.name))


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
                df[col] = numeric.astype("float32")
        elif df[col].nunique(dropna=True) < max(n * 0.5, 1):
            df[col] = df[col].astype("category")
    return df


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", low_memory=False)
    return df.drop(columns=[c for c in DROP_COLS if c in df.columns])


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
    season's player_name/birth_year for each player_id; flags player_ids
    where birth_year disagreed across seasons instead of silently
    resolving the conflict."""
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
    conflict = all_rows.groupby("player_id")["birth_year"].transform("nunique") > 1
    all_rows["birth_year_conflict"] = conflict
    all_rows = all_rows.sort_values("season")
    deduped = all_rows.drop_duplicates("player_id", keep="last").drop(columns=["season"])
    return compact_types(deduped.reset_index(drop=True))


def build_sharded_table(dirname: str, seasons: list[str]) -> pd.DataFrame | None:
    frames = []
    for season in seasons:
        d = BASE / season / dirname
        if not d.exists():
            continue
        for f in sorted(d.glob("*.csv")):
            df = read_csv(f)
            df.insert(0, "category_base", f.stem)
            df.insert(0, "season", season)
            frames.append(df)
    if not frames:
        return None
    return compact_types(pd.concat(frames, ignore_index=True))


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

    print("Category-sharded enrichment tables (season + category_base injected):")
    for dirname in SHARDED_DIRS:
        write(dirname, build_sharded_table(dirname, seasons))

    for pattern in ["*/matches.csv", "*/standings.csv", "*/scorers.csv", "*/groups.csv",
                     "*/competitions.csv", "*/team_group_membership.csv",
                     "*/player_competition_participation.csv", "*/teams.csv", "*/venues.csv",
                     "*/players.csv", "*/clubs.csv", "*/match_lineups/*.csv", "*/match_goals/*.csv",
                     "*/match_cards/*.csv", "*/match_staff/*.csv", "*/match_officials/*.csv"]:
        total_csv_bytes += sum(f.stat().st_size for f in BASE.glob(pattern))

    print(f"\nTotal: {total_csv_bytes / 1e6:.0f} MB CSV -> {total_parquet_bytes / 1e6:.0f} MB Parquet "
          f"({total_csv_bytes / max(total_parquet_bytes, 1):.1f}x)")


if __name__ == "__main__":
    main()
