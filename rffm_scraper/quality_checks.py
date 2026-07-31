"""Data quality checks run over the assembled processed tables.

Every check appends zero or more issue dicts (-> data_quality_report.csv)
rather than raising, so a bad data point never aborts the run - it is
surfaced for a human to look at instead.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("rffm_scraper.quality")


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


def run_quality_checks(
    matches_df: pd.DataFrame,
    standings_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    manifest_groups_df: pd.DataFrame,
) -> list[dict]:
    issues: list[dict] = []

    issues += _check_duplicate_match_ids(matches_df)
    issues += _check_duplicate_team_ids(teams_df)
    issues += _check_empty_team_names(matches_df)
    issues += _check_score_consistency(matches_df)
    issues += _check_standings_missing_keys(standings_df)
    issues += _check_team_count_mismatch(matches_df, standings_df)
    issues += _check_jornada_gaps(matches_df)
    issues += _check_calendario_vs_standings_presence(manifest_groups_df)
    issues += _check_missing_match_id_for_played(matches_df)

    logger.info("Quality checks found %d issue(s)", len(issues))
    return issues


def _check_duplicate_match_ids(matches_df: pd.DataFrame) -> list[dict]:
    issues = []
    if matches_df.empty:
        return issues
    with_id = matches_df[matches_df["match_id"].notna()]
    dupes = with_id[with_id.duplicated(subset=["match_id"], keep=False)]
    for match_id, group in dupes.groupby("match_id"):
        issues.append(
            _issue(
                "duplicate_match_id", "error", "match", match_id,
                f"match_id appears {len(group)} times across parsed rows",
            )
        )
    return issues


def _check_duplicate_team_ids(teams_df: pd.DataFrame) -> list[dict]:
    issues = []
    if teams_df.empty:
        return issues
    dupes = teams_df[teams_df.duplicated(subset=["team_id"], keep=False)]
    for team_id, group in dupes.groupby("team_id"):
        names = group["team_name_raw"].unique().tolist()
        issues.append(
            _issue(
                "duplicate_team_id", "error", "team", team_id,
                f"team_id appears {len(group)} times with names {names}",
            )
        )
    return issues


def _check_empty_team_names(matches_df: pd.DataFrame) -> list[dict]:
    issues = []
    if matches_df.empty:
        return issues
    empty = matches_df[(matches_df["home_team"].fillna("") == "") | (matches_df["away_team"].fillna("") == "")]
    for _, row in empty.iterrows():
        issues.append(
            _issue(
                "empty_team_name", "error", "match", row.get("match_id") or "unknown",
                "home_team or away_team is empty",
                group_id=row.get("group_id"), competition_id=row.get("competition_id"),
            )
        )
    return issues


def _check_score_consistency(matches_df: pd.DataFrame) -> list[dict]:
    issues = []
    if matches_df.empty:
        return issues
    home_null = matches_df["home_score"].isna()
    away_null = matches_df["away_score"].isna()
    inconsistent = matches_df[home_null != away_null]
    for _, row in inconsistent.iterrows():
        issues.append(
            _issue(
                "inconsistent_score", "error", "match", row.get("match_id") or "unknown",
                f"home_score={row.get('home_score')} away_score={row.get('away_score')}: exactly one is null",
                group_id=row.get("group_id"), competition_id=row.get("competition_id"),
            )
        )
    return issues


def _check_standings_missing_keys(standings_df: pd.DataFrame) -> list[dict]:
    issues = []
    if standings_df.empty:
        return issues
    missing = standings_df[
        (standings_df["group_id"].fillna("") == "") | (standings_df["competition_id"].fillna("") == "")
    ]
    for _, row in missing.iterrows():
        issues.append(
            _issue(
                "standing_missing_keys", "error", "standing", row.get("team_id") or "unknown",
                "standings row missing group_id or competition_id",
            )
        )
    return issues


def _check_team_count_mismatch(matches_df: pd.DataFrame, standings_df: pd.DataFrame) -> list[dict]:
    issues = []
    if matches_df.empty or standings_df.empty:
        return issues
    for group_id, m_group in matches_df.groupby("group_id"):
        s_group = standings_df[standings_df["group_id"] == group_id]
        if s_group.empty:
            continue
        match_teams = set(m_group["home_team_id"].dropna()) | set(m_group["away_team_id"].dropna())
        standing_teams = set(s_group["team_id"].dropna())
        if match_teams != standing_teams:
            issues.append(
                _issue(
                    "team_count_mismatch", "warning", "group", group_id,
                    f"{len(match_teams)} distinct teams in matches vs {len(standing_teams)} in standings "
                    f"(only-in-matches={match_teams - standing_teams}, only-in-standings={standing_teams - match_teams})",
                    group_id=group_id,
                )
            )
    return issues


def _check_jornada_gaps(matches_df: pd.DataFrame) -> list[dict]:
    issues = []
    if matches_df.empty:
        return issues
    for group_id, m_group in matches_df.groupby("group_id"):
        matchdays = sorted(m_group["matchday"].dropna().unique().tolist())
        if not matchdays:
            continue
        expected = set(range(int(min(matchdays)), int(max(matchdays)) + 1))
        missing = expected - set(int(x) for x in matchdays)
        if missing:
            issues.append(
                _issue(
                    "jornada_coverage_gap", "warning", "group", group_id,
                    f"missing matchday numbers: {sorted(missing)}",
                    group_id=group_id,
                )
            )
    return issues


def _check_calendario_vs_standings_presence(manifest_groups_df: pd.DataFrame) -> list[dict]:
    issues = []
    if manifest_groups_df.empty:
        return issues
    only_calendario = manifest_groups_df[
        manifest_groups_df["has_calendario"] & ~manifest_groups_df["has_clasificaciones"]
    ]
    for _, row in only_calendario.iterrows():
        issues.append(
            _issue(
                "calendario_without_standings", "warning", "group", row["group_id"],
                "calendario page found but clasificaciones page missing/empty",
                group_id=row["group_id"], competition_id=row["competition_id"],
            )
        )
    only_standings = manifest_groups_df[
        manifest_groups_df["has_clasificaciones"] & ~manifest_groups_df["has_calendario"]
    ]
    for _, row in only_standings.iterrows():
        issues.append(
            _issue(
                "standings_without_calendario", "warning", "group", row["group_id"],
                "clasificaciones page found but calendario page missing/empty",
                group_id=row["group_id"], competition_id=row["competition_id"],
            )
        )
    return issues


def _check_missing_match_id_for_played(matches_df: pd.DataFrame) -> list[dict]:
    issues = []
    if matches_df.empty:
        return issues
    missing = matches_df[matches_df["is_finished"] & matches_df["match_id"].isna()]
    for _, row in missing.iterrows():
        issues.append(
            _issue(
                "finished_match_missing_match_id", "warning", "match",
                f"{row.get('home_team_id')}-{row.get('away_team_id')}",
                "match has a final score but no match_id (acta link) was found",
                group_id=row.get("group_id"), competition_id=row.get("competition_id"),
            )
        )
    return issues
