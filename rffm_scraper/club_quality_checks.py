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
    issues: list[dict] = []
    issues += _check_coverage(clubs_df, target_team_ids)
    issues += _check_duplicate_club_ids(clubs_df)

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


def _check_duplicate_club_ids(clubs_df: pd.DataFrame) -> list[dict]:
    """Two different club_name_raw values resolving to the same codigo_club
    would mean the site's own name string for a club isn't stable across
    teams - worth flagging since CLAUDE.md's routing table assumes
    club_name_raw is a reliable club-level filter key."""
    issues = []
    if clubs_df.empty:
        return issues
    dupes = clubs_df.groupby("club_id")["club_name_raw"].nunique()
    for club_id, n in dupes[dupes > 1].items():
        names = clubs_df.loc[clubs_df["club_id"] == club_id, "club_name_raw"].unique().tolist()
        issues.append(
            _issue(
                "club_id_name_mismatch", "warning", "club", club_id,
                f"club_id maps to {n} different club_name_raw values: {names}",
            )
        )
    return issues
