"""Data quality checks specific to the club-profiles (fichaclub) enrichment
stage. Written to its own club_profiles_data_quality_report.csv - see
acta_pipeline.py's module docstring for why enrichment stages don't share
the core pipeline's data_quality_report.csv.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("rffm_scraper.club_profile_quality")


def _issue(check_name, severity, entity_type, entity_id, details):
    return dict(
        check_name=check_name,
        severity=severity,
        entity_type=entity_type,
        entity_id=str(entity_id),
        group_id=None,
        competition_id=None,
        details=details,
    )


def run_club_profile_quality_checks(
    target_club_ids: list[str], done_club_ids: set[str], null_club_ids: list[str],
) -> list[dict]:
    """target_club_ids: every club_id this run was asked to cover.
    done_club_ids: club_ids with at least one successful fetch (found or
    null) after this run. null_club_ids: the subset that fetched
    successfully but got club: null back (expected for a stale/defunct
    club_id - a valid negative result, not an error).
    """
    issues: list[dict] = []

    missing = set(target_club_ids) - done_club_ids
    for club_id in sorted(missing):
        issues.append(
            _issue(
                "club_profile_coverage_gap", "warning", "club", club_id,
                "club_id was a fetch target but no successful /fichaclub/ fetch was recorded "
                "(fetch failure or unparseable page)",
            )
        )

    for club_id in sorted(set(null_club_ids) & set(target_club_ids)):
        issues.append(
            _issue(
                "club_profile_not_found", "info", "club", club_id,
                "fetched successfully but the site returned club: null - a stale/defunct "
                "club_id, not a fetch error",
            )
        )

    logger.info("Club profile quality checks found %d issue(s)", len(issues))
    return issues
