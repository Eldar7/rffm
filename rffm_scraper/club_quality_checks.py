"""Data quality checks specific to the clubs (fichaequipo) enrichment stage.

Written to its own clubs_data_quality_report.csv - see acta_pipeline.py's
module docstring for why enrichment stages don't share the core pipeline's
data_quality_report.csv.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("rffm_scraper.club_quality")


def _issue(check_name, severity, entity_type, entity_id, details, group_id=None, competition_id=None):
    return dict(
        check_name=check_name,
        severity=severity,
        entity_type=entity_type,
        entity_id=str(entity_id),
        group_id=group_id,
        competition_id=competition_id,
        details=details,
    )


def run_club_quality_checks(clubs_df: pd.DataFrame, target_team_ids: list) -> list[dict]:
    """Inspect the pre-dedup data so redundant fetch targets remain visible."""
    issues: list[dict] = []
    issues += _check_coverage(clubs_df, target_team_ids)
    issues += _check_redundant_club_targets(clubs_df)

    logger.info("Club quality checks found %d issue(s)", len(issues))
    return issues


def _check_coverage(clubs_df: pd.DataFrame, target_team_ids: list) -> list[dict]:
    issues = []
    covered = set(clubs_df["representative_team_id"].unique()) if not clubs_df.empty else set()
    missing = set(target_team_ids) - covered
    for team_id in sorted(missing):
        issues.append(
            _issue(
                "club_coverage_gap", "warning", "team", team_id,
                "team was selected as a club's representative but no fichaequipo profile was "
                "fetched (fetch failure, empty page, or missing codigo_club)",
            )
        )
    return issues


def _check_redundant_club_targets(clubs_df: pd.DataFrame) -> list[dict]:
    """Record target-team collisions before clubs.csv is deduped by club_id."""
    issues = []
    if clubs_df.empty:
        return issues
    dupes = clubs_df.groupby("club_id").size()
    for club_id, n in dupes[dupes > 1].items():
        reps = clubs_df.loc[clubs_df["club_id"] == club_id, "representative_team_id"].tolist()
        issues.append(
            _issue(
                "redundant_club_target", "info", "club", club_id,
                f"{n} target teams resolved to the same club_id; representative_team_ids {reps}; "
                "deduped in the published clubs.csv, keeping the first-fetched row",
            )
        )
    return issues
