"""
Compatibility layer over output/processed/rffm_parquet/ (build_parquet.py's
output) for report generators that currently do
`pd.read_csv(BASE / season / "<table>.csv", dtype=str)`.

read_table(name, season=..., category=...) returns a DataFrame with the
same columns (in the same order) and the same all-string/NaN values that
call would have produced, so a report generator can switch its data source
by changing the read call only — join keys, clean()/norm_id() helpers, and
every downstream computation stay untouched.

Two intentional differences from the CSV originals, both grep-verified
harmless (no report generator in analysis_scripts/*.py touches either):
  - `source_url`/`scraped_at` are absent — build_parquet.py drops them
    (source_url is 100% derivable from IDs; scraped_at is crawl
    provenance). Only analysis_scripts/retry_check.py used them, and it
    doesn't build the site.
  - players() takes no `season`: player_id is a stable, season-independent
    identity (DATA_DICTIONARY.md: "stable identity only"), so
    output/processed/rffm_parquet/players.parquet is deduped to one row
    per player_id instead of repeated per season (see build_parquet.py's
    build_players_table). Every report generator only ever uses this
    table as a player_id -> name/birth_year lookup dict, never counts or
    filters it by season, so returning the global table for every season
    is behavior-preserving.

Usage:
    import rffm_data as data
    matches = data.read_table("matches", season="2025-2026")
    lineups = data.read_table("match_lineups", season="2025-2026", category="CADETE")
    teams = data.read_table("teams", season="2025-2026")
    players = data.read_table("players")
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd

PARQUET_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm_parquet"

# Tables with no `season` column in the original CSV (season is purely a
# directory-name artifact of build_parquet.py) - dropped after filtering
# so the returned shape matches pd.read_csv(season_dir / f"{name}.csv").
NO_SEASON_COLUMN_IN_ORIGINAL = {"teams", "venues", "clubs"}


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
    df = _load(name)

    if name == "players":
        return _stringify(df)

    if season is not None and "season" in df.columns:
        df = df[df["season"] == season]
        if name in NO_SEASON_COLUMN_IN_ORIGINAL:
            df = df.drop(columns=["season"])

    if category is not None and "category_base" in df.columns:
        df = df[df["category_base"] == category]
        df = df.drop(columns=["category_base"])

    return _stringify(df)


def list_categories(name: str, season: str) -> list[str]:
    """Category files build_sharded_table() would have globbed for this
    season, e.g. list_categories("match_lineups", "2025-2026") mirrors
    what `(BASE / season / "match_lineups").glob("*.csv")` used to give."""
    df = _load(name)
    if "season" not in df.columns or "category_base" not in df.columns:
        raise ValueError(f"{name} has no per-season/category shards")
    return sorted(df.loc[df["season"] == season, "category_base"].unique().tolist())


def list_seasons(name: str) -> list[str]:
    df = _load(name)
    if "season" not in df.columns:
        raise ValueError(f"{name} has no season column")
    return sorted(df["season"].unique().tolist())
