"""Data quality checks specific to the team_clubs (fichaequipo, full
coverage) enrichment stage.

Written to its own team_clubs_data_quality_report.csv - see
acta_pipeline.py's module docstring for why enrichment stages don't share
the core pipeline's data_quality_report.csv.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("rffm_scraper.team_club_quality")


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


def run_team_club_quality_checks(
    season: str, target_team_ids: list[str], resolved_team_ids: set[str],
) -> list[dict]:
    """target_team_ids: every team_id this season's run was asked to cover
    (this season's own teams.csv). resolved_team_ids: team_ids with a row in
    team_club_map.csv (seeded or freshly fetched) after this run - a team_id
    can legitimately never resolve (a real gap on RFFM's own fichaequipo
    page, not a fetch failure - same situation clubs.csv already
    documents), which is exactly what this check surfaces per season rather
    than silently dropping it.
    """
    issues: list[dict] = []

    missing = set(target_team_ids) - resolved_team_ids
    for team_id in sorted(missing):
        issues.append(
            _issue(
                "team_club_coverage_gap", "warning", "team", team_id,
                f"season={season}: team_id was a fetch target but has no resolved club_id "
                "(fetch failure, empty page, or missing codigo_club - see "
                "team_clubs_crawl_log.csv for the underlying fetch outcome)",
            )
        )

    logger.info("Team-club quality checks found %d issue(s) for season=%s", len(issues), season)
    return issues
