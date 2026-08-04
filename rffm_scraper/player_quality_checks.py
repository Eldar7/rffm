"""Data quality checks specific to fichajugador (player profile) enrichment.

Written to its own player_data_quality_report.csv - see player_pipeline.py
module docstring for why this isn't merged into other pipelines' reports.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("rffm_scraper.player_quality")

# Loose sanity bound, not a category-cutoff rule: BENJAMIN/PREBENJAMIN
# players are roughly 6-9 years old, but exact federation cutoff years
# aren't independently confirmed - this only catches clearly wrong values
# (e.g. a typo'd century), not borderline-but-plausible ones.
_MIN_SANE_BIRTH_YEAR = 2012
_MAX_SANE_BIRTH_YEAR = 2022


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


def run_player_quality_checks(
    players_df: pd.DataFrame,
    season_stats_df: pd.DataFrame,
    lineups_df: pd.DataFrame,
    target_player_ids: set,
) -> list[dict]:
    issues: list[dict] = []
    issues += _check_coverage(players_df, target_player_ids)
    issues += _check_jugados_reconciliation(season_stats_df, lineups_df)
    issues += _check_birth_year_sanity(players_df)

    logger.info("Player quality checks found %d issue(s)", len(issues))
    return issues


def _check_coverage(players_df: pd.DataFrame, target_player_ids: set) -> list[dict]:
    issues = []
    covered = set(players_df["player_id"].unique()) if not players_df.empty else set()
    missing = target_player_ids - covered
    for player_id in sorted(missing):
        issues.append(
            _issue(
                "player_profile_coverage_gap", "warning", "player", player_id,
                "player appears in match_lineups/ but no fichajugador profile was fetched (fetch failure or empty page)",
            )
        )
    return issues


def _check_jugados_reconciliation(season_stats_df: pd.DataFrame, lineups_df: pd.DataFrame) -> list[dict]:
    """Cross-validates the whole acta-partido pipeline: the site's own
    'Jugados' (matches_played) season stat should match how many
    match_lineups/ rows we actually collected for that player. A
    mismatch means our acta crawl missed some of that player's matches."""
    issues = []
    if season_stats_df.empty or lineups_df.empty:
        return issues
    lineup_counts = lineups_df.groupby("player_id").size()
    for _, row in season_stats_df.iterrows():
        player_id = row["player_id"]
        site_count = row.get("matches_played")
        if pd.isna(site_count):
            continue
        our_count = int(lineup_counts.get(player_id, 0))
        if int(site_count) != our_count:
            issues.append(
                _issue(
                    "jugados_reconciliation_mismatch", "warning", "player", player_id,
                    f"site-reported matches_played={int(site_count)} vs "
                    f"{our_count} rows collected in match_lineups/ - "
                    "likely a gap in acta-partido coverage for this player",
                )
            )
    return issues


def _check_birth_year_sanity(players_df: pd.DataFrame) -> list[dict]:
    issues = []
    if players_df.empty:
        return issues
    out_of_range = players_df[
        players_df["birth_year"].notna()
        & ((players_df["birth_year"] < _MIN_SANE_BIRTH_YEAR) | (players_df["birth_year"] > _MAX_SANE_BIRTH_YEAR))
    ]
    for _, row in out_of_range.iterrows():
        issues.append(
            _issue(
                "birth_year_out_of_range", "warning", "player", row["player_id"],
                f"birth_year={row['birth_year']} is outside the sane bound "
                f"[{_MIN_SANE_BIRTH_YEAR}, {_MAX_SANE_BIRTH_YEAR}] for BENJAMIN/PREBENJAMIN",
            )
        )
    return issues
