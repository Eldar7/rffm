"""Migration 001: split flat acta CSVs into per-category subdirectories
and drop redundant columns.

Run once, then commit the result. Safe to re-run (idempotent: skips seasons
that already have the new layout).

What changed (see feature/acta-files-per-category branch for context):
  - match_lineups.csv  -> match_lineups/<category>.csv
  - match_goals.csv    -> match_goals/<category>.csv
  - match_cards.csv    -> match_cards/<category>.csv
  - match_staff.csv    -> match_staff/<category>.csv
  - match_officials.csv -> match_officials/<category>.csv

Dropped columns (all recoverable):
  - source_url   (all 5 files): reconstruct as
                   f"https://www.rffm.es/acta-partido/{match_id}"
  - scraped_at   (all 5 files): join acta_crawl_log.csv on
                   entity_id=match_id where success=True, take timestamp
  - player_name_raw (match_lineups, match_goals, match_cards): join
                   players.csv on player_id -> player_name_raw

Category is derived by joining match_id -> matches.csv (category column).
"""
import pathlib
import sys
import pandas as pd

REPO_ROOT = pathlib.Path(__file__).parent.parent
SEASONS_DIR = REPO_ROOT / "output" / "processed" / "rffm"

FLAT_FILES = ["match_lineups", "match_goals", "match_cards", "match_staff", "match_officials"]
DROP_ALWAYS = ["source_url", "scraped_at"]
DROP_FROM = {"match_lineups", "match_goals", "match_cards"}  # also drop player_name_raw


def migrate_season(season_dir: pathlib.Path) -> None:
    matches_path = season_dir / "matches.csv"
    if not matches_path.exists():
        print(f"  skip {season_dir.name}: no matches.csv")
        return

    match_to_category = (
        pd.read_csv(matches_path, usecols=["match_id", "category"], dtype=str)
        .dropna(subset=["match_id"])
        .set_index("match_id")["category"]
    )

    for name in FLAT_FILES:
        flat_path = season_dir / f"{name}.csv"
        subdir = season_dir / name

        # Already migrated?
        if subdir.exists() and not flat_path.exists():
            print(f"  {name}: already migrated, skipping")
            continue

        if not flat_path.exists():
            print(f"  {name}: flat file missing, skipping")
            continue

        df = pd.read_csv(flat_path, dtype=str)

        # Add category via match_id join
        df["_category"] = df["match_id"].map(match_to_category).fillna("OTHER")

        # Drop redundant columns
        cols_to_drop = [c for c in DROP_ALWAYS if c in df.columns]
        if name in DROP_FROM and "player_name_raw" in df.columns:
            cols_to_drop.append("player_name_raw")
        df = df.drop(columns=cols_to_drop)

        # Write per-category files
        subdir.mkdir(exist_ok=True)
        for category, group in df.groupby("_category"):
            out = subdir / f"{category}.csv"
            group.drop(columns=["_category"]).to_csv(out, index=False)
            print(f"  {name}/{category}.csv: {len(group)} rows")

        flat_path.unlink()
        print(f"  removed {flat_path.name}")


def main() -> None:
    season_dirs = sorted(
        d for d in SEASONS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
    if not season_dirs:
        print("No season directories found.")
        sys.exit(1)

    for season_dir in season_dirs:
        print(f"\n=== {season_dir.name} ===")
        migrate_season(season_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
