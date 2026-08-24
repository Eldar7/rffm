#!/usr/bin/env python3
"""
Read-only closure detector for the open/closed Parquet-vs-CSV git policy
(see DATA_DICTIONARY.md's "Two copies of the data" section once documented
there): a (season, stage) is CLOSED once coverage_manifest.csv shows
status == "complete" for every category_base row of that (season, stage) -
strictly "complete", not "complete_with_failures", which OPERATIONS.md's
retry_check.py can and does reset back to "partial" for a later re-crawl
attempt (so it is not a safe "this data will never change again" signal).
core is category_base="ALL" only (one row per season); acta_partido/
fichajugador/clubs can have several category_base rows per season, and this
module requires ALL of them to be "complete" before calling that (season,
stage) closed - a season with 10 of 11 categories done for fichajugador
still counts as open. This is the simpler of two options discussed with the
project owner (the other: split match_lineups/etc. into one Parquet file per
(season, category) instead of per season, so a category could close
independently) - deliberately not done here since it would mean restructuring
Parquet files that are already committed; revisit if a single long-tail
category routinely holds up a whole season's closure for months.

This script only REPORTS closure status - it never writes, commits, or
deletes anything. The action that actually commits a closed (season, stage)'s
Parquet and deletes its source CSVs is a separate, explicit, human-triggered
step - see build_parquet.py's --close flag - and must never run
unattended/on a schedule (project owner's explicit instruction).

club_profiles (clubs_extended.csv/club_teams.csv) is deliberately excluded
from this whole scheme - it's not season-scoped (season="ALL" in the
manifest, a cross-season append-only log re-fetched indefinitely via
enrich_club_profiles.py --force-refetch), so "closed" doesn't apply to it.

Usage:
    python analysis_scripts/parquet_closure.py            # full report
    python analysis_scripts/parquet_closure.py --stage core
    python analysis_scripts/parquet_closure.py --table matches
"""

import argparse
from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

ALL_STAGES = ["core", "acta_partido", "fichajugador", "clubs"]

# Parquet table name -> owning coverage_manifest.csv stage. Anything not
# listed here (players - cross-season deduped, handled separately from
# season-based closure; clubs_extended/club_teams - see module docstring)
# is out of scope for this open/closed scheme entirely.
TABLE_STAGE = {
    "matches": "core", "standings": "core", "scorers": "core", "groups": "core",
    "competitions": "core", "team_group_membership": "core",
    "teams": "core", "venues": "core", "game_types": "core", "seasons": "core",
    "manifest_groups": "core", "manifest_pages": "core", "manifest_endpoints": "core",
    "clubs": "clubs",
    "player_competition_participation": "fichajugador", "player_season_stats": "fichajugador",
    "players_by_season": "fichajugador",
    "match_lineups": "acta_partido", "match_goals": "acta_partido", "match_cards": "acta_partido",
    "match_staff": "acta_partido", "match_officials": "acta_partido",
}


def load_manifest() -> pd.DataFrame:
    return pd.read_csv(MANIFEST, dtype=str)


def stage_closed_seasons(stage: str, manifest: pd.DataFrame | None = None) -> set[str]:
    """Every season where `stage` is fully closed - every category_base row
    for (season, stage) has status == 'complete'."""
    m = manifest if manifest is not None else load_manifest()
    sub = m[m["stage"] == stage]
    closed = set()
    for season, g in sub.groupby("season"):
        if len(g) > 0 and (g["status"] == "complete").all():
            closed.add(season)
    return closed


def table_closed_seasons(table: str, manifest: pd.DataFrame | None = None) -> set[str]:
    stage = TABLE_STAGE.get(table)
    if stage is None:
        raise ValueError(f"{table!r} has no known stage mapping (players/clubs_extended/"
                          f"club_teams are deliberately out of scope - see module docstring)")
    return stage_closed_seasons(stage, manifest)


def log_family_closed_seasons(manifest: pd.DataFrame | None = None) -> set[str]:
    """crawl_log/data_quality_report merge all four stages' rows per season
    into one Parquet file each (log_family column) - only closeable once
    EVERY stage for that season is closed, the strictest of any table."""
    m = manifest if manifest is not None else load_manifest()
    per_stage = [stage_closed_seasons(s, m) for s in ALL_STAGES]
    return set.intersection(*per_stage) if per_stage else set()


def report(stage_filter: str | None = None, table_filter: str | None = None) -> None:
    m = load_manifest()
    if table_filter:
        closed = sorted(table_closed_seasons(table_filter, m))
        print(f"{table_filter} (stage={TABLE_STAGE[table_filter]}): closed seasons = {closed}")
        return

    stages = [stage_filter] if stage_filter else ALL_STAGES
    for stage in stages:
        closed = sorted(stage_closed_seasons(stage, m))
        open_ = sorted(set(m.loc[m["stage"] == stage, "season"].unique()) - set(closed))
        print(f"stage={stage:<14} closed: {closed}")
        print(f"{'':<20} open:   {open_}")

    if not stage_filter and not table_filter:
        print(f"\ncrawl_log/data_quality_report (need ALL 4 stages closed): "
              f"{sorted(log_family_closed_seasons(m))}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=ALL_STAGES, help="Report just this stage")
    parser.add_argument("--table", choices=sorted(TABLE_STAGE), help="Report just this table's owning stage")
    args = parser.parse_args()
    report(args.stage, args.table)


if __name__ == "__main__":
    main()
