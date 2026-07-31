"""Data quality checks specific to acta-partido enrichment output.

Written to a separate acta_data_quality_report.csv - see acta_pipeline.py
module docstring for why this isn't merged into the core pipeline's report.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("rffm_scraper.acta_quality")

# Generous upper bound on a plausible in-match event minute for youth
# football (short halves, no extended extra time) - the site's own "999"
# sentinel (seen on a card issued when not literally in play) is far above
# this, so both get caught by the same check.
_MAX_SANE_MINUTE = 130


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


def run_acta_quality_checks(
    lineups_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    cards_df: pd.DataFrame,
    matches_df: pd.DataFrame,
    target_match_ids: set,
    team_id_mismatch_warnings: list[dict],
) -> list[dict]:
    issues: list[dict] = []
    issues += _check_duplicate_lineup_rows(lineups_df)
    issues += _check_duplicate_player_names(lineups_df)
    issues += _check_lineup_team_id_matches_match(lineups_df, matches_df)
    issues += _check_lineup_coverage(lineups_df, target_match_ids)
    issues += _check_anomalous_minute(goals_df, "goal")
    issues += _check_anomalous_minute(cards_df, "card")
    issues += _check_empty_player_name(lineups_df)
    issues += [
        _issue("acta_team_id_mismatch", "warning", "match", w["match_id"], w["message"])
        for w in team_id_mismatch_warnings
    ]

    logger.info("Acta quality checks found %d issue(s)", len(issues))
    return issues


def _check_duplicate_lineup_rows(lineups_df: pd.DataFrame) -> list[dict]:
    issues = []
    if lineups_df.empty:
        return issues
    dupes = lineups_df[lineups_df.duplicated(subset=["match_id", "player_id"], keep=False)]
    for (match_id, player_id), group in dupes.groupby(["match_id", "player_id"]):
        issues.append(
            _issue(
                "duplicate_lineup_entry", "error", "match_lineup", f"{match_id}:{player_id}",
                f"player_id appears {len(group)} times in the same match's lineup",
            )
        )
    return issues


def _check_duplicate_player_names(lineups_df: pd.DataFrame) -> list[dict]:
    """Checked against the pre-dedup match_lineups_df, not players.csv - a
    check against an already-deduped-by-player_id table would structurally
    never fire (same trap the core pipeline's duplicate_team_id check falls
    into against the already-deduped teams_df)."""
    issues = []
    if lineups_df.empty:
        return issues
    names_per_player = lineups_df.groupby("player_id")["player_name_raw"].nunique()
    conflicted = names_per_player[names_per_player > 1]
    for player_id in conflicted.index:
        names = lineups_df.loc[lineups_df["player_id"] == player_id, "player_name_raw"].unique().tolist()
        issues.append(
            _issue(
                "player_id_multiple_names", "error", "player", player_id,
                f"player_id appears with {len(names)} distinct names: {names}",
            )
        )
    return issues


def _check_lineup_team_id_matches_match(lineups_df: pd.DataFrame, matches_df: pd.DataFrame) -> list[dict]:
    issues = []
    if lineups_df.empty or matches_df.empty:
        return issues
    joined = lineups_df.merge(
        matches_df[["match_id", "home_team_id", "away_team_id"]], on="match_id", how="left"
    )
    mismatched = joined[
        (joined["team_id"] != joined["home_team_id"]) & (joined["team_id"] != joined["away_team_id"])
    ]
    for _, row in mismatched.iterrows():
        issues.append(
            _issue(
                "lineup_team_id_mismatch", "error", "match_lineup", f"{row['match_id']}:{row['player_id']}",
                f"lineup team_id {row['team_id']} is neither home_team_id {row['home_team_id']} "
                f"nor away_team_id {row['away_team_id']} for this match",
            )
        )
    return issues


def _check_lineup_coverage(lineups_df: pd.DataFrame, target_match_ids: set) -> list[dict]:
    issues = []
    covered = set(lineups_df["match_id"].unique()) if not lineups_df.empty else set()
    missing = target_match_ids - covered
    for match_id in sorted(missing):
        issues.append(
            _issue(
                "acta_lineup_coverage_gap", "warning", "match", match_id,
                "match was in scope but yielded zero lineup rows (fetch failure or empty page)",
            )
        )
    return issues


def _check_anomalous_minute(events_df: pd.DataFrame, event_kind: str) -> list[dict]:
    issues = []
    if events_df.empty:
        return issues
    anomalous = events_df[events_df["minute"].notna() & (events_df["minute"] > _MAX_SANE_MINUTE)]
    for _, row in anomalous.iterrows():
        issues.append(
            _issue(
                "anomalous_event_minute", "warning", f"match_{event_kind}", f"{row['match_id']}:{row.get('player_id')}",
                f"minute={row['minute']} (minute_raw={row.get('minute_raw')!r}) exceeds sane bound "
                f"of {_MAX_SANE_MINUTE} - likely a site sentinel, not a literal match minute",
            )
        )
    return issues


def _check_empty_player_name(lineups_df: pd.DataFrame) -> list[dict]:
    issues = []
    if lineups_df.empty:
        return issues
    empty = lineups_df[lineups_df["player_name_raw"].fillna("") == ""]
    for _, row in empty.iterrows():
        issues.append(
            _issue(
                "empty_player_name", "error", "match_lineup", f"{row['match_id']}:{row.get('player_id')}",
                "player_name_raw is empty",
            )
        )
    return issues
