#!/usr/bin/env python3
"""
Referential-integrity checker for output/processed/rffm_parquet/: for every
FK-like column documented in DATA_DICTIONARY.md, checks that every non-null
value actually resolves in the table it's supposed to reference (an
anti-join: rows on the FK side with no matching PK-side row).

Why this exists and what it does NOT replace: the crawler already has its
own data-quality checks (data_quality_report.csv - plausibility/range
checks like birth_year_out_of_range, and site-vs-computed reconciliation
like jugados_reconciliation_mismatch), but none of its 9 check types cover
cross-table referential integrity - "does this team_id actually exist in
teams?". That's a real, previously unquantified gap this project has had
since CSV days; this script closes it for the Parquet copy, at query time,
without needing a persisted database with declared FOREIGN KEY constraints
(see the discussion in this project's own history for why that heavier
option was decided against - portability, and that a real audit of every
legitimate NULL/exception case would be needed to make constraints
enforceable rather than just noisy).

A NULL in an FK column is never a violation (nullable FKs are legitimate -
e.g. matches.home_team_id is null for a bye) - only a non-null value that
fails to resolve counts.

Usage:
    python analysis_scripts/validate_parquet.py
    python analysis_scripts/validate_parquet.py --parquet-dir output/processed/rffm_parquet

Exit code is nonzero if any violation is found, so this can gate a
workflow step (e.g. parquet-build.yml) the same way a failing test would.
"""

import argparse
import sys
from pathlib import Path

import duckdb

PARQUET_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm_parquet"

# (description, fk_source_glob, fk_column, pk_target_file, pk_column)
# fk_source_glob is relative to --parquet-dir; sharded tables (one file per
# season) are globbed with *.parquet, flat tables reference the single file
# directly - both work the same way through DuckDB's glob support.
CHECKS: list[tuple[str, str, str, str, str]] = [
    ("matches.home_team_id -> teams", "matches.parquet", "home_team_id", "teams.parquet", "team_id"),
    ("matches.away_team_id -> teams", "matches.parquet", "away_team_id", "teams.parquet", "team_id"),
    ("matches.competition_id -> competitions", "matches.parquet", "competition_id", "competitions.parquet", "competition_id"),
    ("matches.group_id -> groups", "matches.parquet", "group_id", "groups.parquet", "group_id"),
    ("matches.venue_id -> venues", "matches.parquet", "venue_id", "venues.parquet", "venue_id"),
    ("groups.competition_id -> competitions", "groups.parquet", "competition_id", "competitions.parquet", "competition_id"),
    ("team_group_membership.team_id -> teams", "team_group_membership.parquet", "team_id", "teams.parquet", "team_id"),
    ("team_group_membership.competition_id -> competitions", "team_group_membership.parquet", "competition_id", "competitions.parquet", "competition_id"),
    ("team_group_membership.group_id -> groups", "team_group_membership.parquet", "group_id", "groups.parquet", "group_id"),
    ("standings.team_id -> teams", "standings.parquet", "team_id", "teams.parquet", "team_id"),
    ("standings.competition_id -> competitions", "standings.parquet", "competition_id", "competitions.parquet", "competition_id"),
    ("standings.group_id -> groups", "standings.parquet", "group_id", "groups.parquet", "group_id"),
    ("scorers.team_id -> teams", "scorers.parquet", "team_id", "teams.parquet", "team_id"),
    ("scorers.competition_id -> competitions", "scorers.parquet", "competition_id", "competitions.parquet", "competition_id"),
    ("scorers.group_id -> groups", "scorers.parquet", "group_id", "groups.parquet", "group_id"),
    ("player_competition_participation.player_id -> players", "player_competition_participation.parquet", "player_id", "players.parquet", "player_id"),
    ("player_competition_participation.team_id -> teams", "player_competition_participation.parquet", "team_id", "teams.parquet", "team_id"),
    ("player_competition_participation.competition_id -> competitions", "player_competition_participation.parquet", "competition_id", "competitions.parquet", "competition_id"),
    ("player_competition_participation.group_id -> groups", "player_competition_participation.parquet", "group_id", "groups.parquet", "group_id"),
    ("player_season_stats.player_id -> players", "player_season_stats.parquet", "player_id", "players.parquet", "player_id"),
    ("match_lineups.match_id -> matches", "match_lineups/*.parquet", "match_id", "matches.parquet", "match_id"),
    ("match_lineups.team_id -> teams", "match_lineups/*.parquet", "team_id", "teams.parquet", "team_id"),
    ("match_lineups.player_id -> players", "match_lineups/*.parquet", "player_id", "players.parquet", "player_id"),
    ("match_goals.match_id -> matches", "match_goals/*.parquet", "match_id", "matches.parquet", "match_id"),
    ("match_goals.team_id -> teams", "match_goals/*.parquet", "team_id", "teams.parquet", "team_id"),
    ("match_goals.player_id -> players", "match_goals/*.parquet", "player_id", "players.parquet", "player_id"),
    ("match_cards.match_id -> matches", "match_cards/*.parquet", "match_id", "matches.parquet", "match_id"),
    ("match_cards.team_id -> teams", "match_cards/*.parquet", "team_id", "teams.parquet", "team_id"),
    ("match_cards.player_id -> players", "match_cards/*.parquet", "player_id", "players.parquet", "player_id"),
    ("match_staff.match_id -> matches", "match_staff/*.parquet", "match_id", "matches.parquet", "match_id"),
    ("match_staff.team_id -> teams", "match_staff/*.parquet", "team_id", "teams.parquet", "team_id"),
    ("match_officials.match_id -> matches", "match_officials/*.parquet", "match_id", "matches.parquet", "match_id"),
]


def run_checks(parquet_dir: Path) -> list[tuple[str, int]]:
    con = duckdb.connect()
    violations = []
    for label, fk_glob, fk_col, pk_file, pk_col in CHECKS:
        fk_path = parquet_dir / fk_glob
        pk_path = parquet_dir / pk_file
        if not pk_path.exists():
            print(f"  skip {label}: {pk_file} not found")
            continue
        q = f"""
            SELECT COUNT(*) FROM (
                SELECT DISTINCT fk.{fk_col} AS v
                FROM '{fk_path}' fk
                WHERE fk.{fk_col} IS NOT NULL
            ) x
            LEFT JOIN '{pk_path}' pk ON x.v = pk.{pk_col}
            WHERE pk.{pk_col} IS NULL
        """
        count = con.execute(q).fetchone()[0]
        status = "OK" if count == 0 else f"VIOLATION x{count}"
        print(f"  {label:<55} {status}")
        if count:
            violations.append((label, count))
    return violations


def main():
    parser = argparse.ArgumentParser(description="Check referential integrity across output/processed/rffm_parquet/")
    parser.add_argument("--parquet-dir", default=str(PARQUET_DIR))
    args = parser.parse_args()

    parquet_dir = Path(args.parquet_dir)
    print(f"Validating {parquet_dir} ({len(CHECKS)} relationships)...")
    violations = run_checks(parquet_dir)

    if violations:
        print(f"\n{len(violations)} relationship(s) with violations - see above.")
        sys.exit(1)
    print("\nAll relationships clean.")


if __name__ == "__main__":
    main()
