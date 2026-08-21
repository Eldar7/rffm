"""Pydantic row models for every processed CSV. Field order == CSV column order."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class Row(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GameType(Row):
    game_type_id: str
    game_type: str


class Competition(Row):
    season: str
    season_id: str
    category_base: str
    category_label_raw: str
    is_femenino: bool
    division_level: str
    competition: str
    competition_id: str
    phase_label: str
    game_type: str
    game_type_id: str
    source_url: str
    scraped_at: str


class Group(Row):
    season: str
    season_id: str
    category: str
    competition: str
    competition_id: str
    group: str
    group_id: str
    group_label_raw: str
    subgroup_label: Optional[str]
    source_url: str
    scraped_at: str


class Team(Row):
    team_id: str
    team: str
    team_name_raw: str
    club_name_raw: str
    squad_suffix: Optional[str]
    source_team_url: str
    scraped_at: str


class Club(Row):
    club_id: str
    club_name_raw: str
    portal_web: Optional[str]
    crest_url: Optional[str]
    correspondence_address: Optional[str]
    locality: Optional[str]
    province: Optional[str]
    postal_code: Optional[str]
    representative_team_id: str
    source_url: str
    scraped_at: str


class ClubProfile(Row):
    """One row per successful /fichaclub/<club_id> fetch - clubs_extended.csv
    is append-only (a new snapshot on every fetch, including refresh runs),
    not one row per club_id like clubs.csv. See club_profile_pipeline.py."""

    club_id: str
    club_name: Optional[str]
    crest_url: Optional[str]
    delegacion: Optional[str]
    comarca: Optional[str]
    cif: Optional[str]
    registered_address: Optional[str]
    registered_locality: Optional[str]
    registered_province: Optional[str]
    registered_postal_code: Optional[str]
    correspondence_address: Optional[str]
    correspondence_locality: Optional[str]
    correspondence_province: Optional[str]
    correspondence_postal_code: Optional[str]
    correspondence_titular: Optional[str]
    correspondence_tratamiento: Optional[str]
    correspondence_email: Optional[str]
    portal_web: Optional[str]
    twitter: Optional[str]
    facebook: Optional[str]
    linkedin: Optional[str]
    instagram: Optional[str]
    telefonos: Optional[str]
    fax: Optional[str]
    fecha_fundacion: Optional[str]
    presidente: Optional[str]
    source_url: str
    scraped_at: str


class ClubTeamRosterEntry(Row):
    """One row per (club_id, team) per successful /fichaclub/ fetch -
    club_teams.csv is append-only, same snapshot semantics as ClubProfile
    above. team_id is the same id space as teams.csv's team_id (confirmed by
    cross-reference)."""

    club_id: str
    team_id: str
    categoria: Optional[str]
    team_name_raw: Optional[str]
    en_competicion: Optional[bool]
    source_url: str
    scraped_at: str


class TeamClubMapping(Row):
    """One row per team_id -> club_id, output/processed/rffm/team_club_map.csv
    (cross-season - see team_club_pipeline.py's module docstring). Unlike
    clubs_extended.csv/club_teams.csv this is NOT an append-only snapshot
    log: a team_id's club_id is a stable, permanent fact once resolved (RFFM
    never reassigns a team_id to a different club), so there is exactly one
    row per team_id, upserted rather than accumulated.

    `source` records how this row was obtained, since most rows are seeded
    for free from data another stage already fetched rather than from a
    live /fichaequipo/ request of this stage's own:
      - "fichaequipo_direct": this stage's own live fetch of
        /fichaequipo/<team_id> -> codigo_club.
      - "fichaclub_roster": copied from club_teams.csv (the /fichaclub/
        roster already lists this team_id under its club_id).
      - "clubs_representative": copied from some season's clubs.csv, where
        this team_id was the representative_team_id for its club_name_raw
        group.
      - "exact_name_match": this team_id's own /fichaequipo/ never resolved
        (or was never fetched), but another team_id with the *exact same*
        club_name_raw string already resolved to a club_id via one of the
        sources above - propagated with no name-matching heuristics beyond
        exact string equality. Skipped (not guessed at) whenever a
        club_name_raw group has more than one distinct resolved club_id.
      - "manual_review": human-verified during analysis, not derivable by
        any of the above (club_name_raw drifted too far for exact-string
        matching - e.g. "FUTURO VELILLA F. S." vs its already-resolved
        sibling "FUTURO VELILLA"). Confirmed via independent evidence
        (shared venue_id across every season, consecutive team_id issued in
        the same registration batch, or an unambiguous crest/name match),
        documented per-row in DATA_FINDINGS.md - never added speculatively.
        Not reproducible by re-running the pipeline; a one-time,
        deliberately reviewed exception, not a recurring seeding layer.
    """

    team_id: str
    club_id: str
    source: str
    source_url: str
    scraped_at: str


class TeamGroupMembership(Row):
    season: str
    season_id: str
    competition_id: str
    group_id: str
    team_id: str
    team: str
    source_url: str
    scraped_at: str


class Match(Row):
    season: str
    season_id: str
    category: str
    competition: str
    competition_id: str
    group: str
    group_id: str
    game_type: str
    game_type_id: str
    phase_label: str
    matchday: Optional[int]
    matchday_label: Optional[str]
    match_id: Optional[str]
    home_team: str
    home_team_id: Optional[str]
    away_team: str
    away_team_id: Optional[str]
    home_score: Optional[int]
    away_score: Optional[int]
    match_date: Optional[str]
    match_time: Optional[str]
    match_datetime_raw: Optional[str]
    venue: Optional[str]
    venue_id: Optional[str]
    status: str
    is_finished: bool
    is_scheduled: bool
    result_text_raw: Optional[str]
    source_url: str
    source_type: str
    scraped_at: str


class Venue(Row):
    venue_id: str
    venue_name: str
    address: Optional[str]
    locality: Optional[str]
    province: Optional[str]
    postal_code: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    google_maps_url: Optional[str]
    field_type_raw: Optional[str]
    surface_raw: Optional[str]
    source_url: str
    scraped_at: str


class Standing(Row):
    season: str
    season_id: str
    category: str
    competition: str
    competition_id: str
    group: str
    group_id: str
    team: str
    team_id: Optional[str]
    position: Optional[int]
    played: Optional[int]
    wins: Optional[int]
    draws: Optional[int]
    losses: Optional[int]
    goals_for: Optional[int]
    goals_against: Optional[int]
    goal_diff: Optional[int]
    points: Optional[int]
    sanction_points: Optional[int]
    source_url: str
    scraped_at: str


class Scorer(Row):
    season: str
    competition_id: str
    group_id: str
    team_id: Optional[str]
    player_name: str
    goals: Optional[int]
    source_url: str
    scraped_at: str


class MatchLineupEntry(Row):
    match_id: str
    team_id: str
    player_id: str
    player_name_raw: Optional[str]
    jersey_number: Optional[int]
    is_starter: Optional[bool]
    is_substitute: Optional[bool]
    is_captain: Optional[bool]
    is_goalkeeper: Optional[bool]
    position_raw: Optional[str]
    position_abbr_raw: Optional[str]
    sex_raw: Optional[str]
    source_url: str
    scraped_at: str


class MatchGoalEvent(Row):
    match_id: str
    team_id: str
    player_id: Optional[str]
    player_name_raw: Optional[str]
    minute: Optional[int]
    minute_raw: Optional[str]
    goal_type_raw: Optional[str]
    source_url: str
    scraped_at: str


class MatchCardEvent(Row):
    match_id: str
    team_id: str
    player_id: Optional[str]
    player_name_raw: Optional[str]
    minute: Optional[int]
    minute_raw: Optional[str]
    card_type_raw: Optional[str]
    card_type_label: Optional[str]
    is_second_yellow: Optional[bool]
    source_url: str
    scraped_at: str


class MatchStaff(Row):
    match_id: str
    team_id: str
    role_kind: str
    role_raw: str
    person_id: Optional[str]
    person_name: str
    source_url: str
    scraped_at: str


class MatchOfficial(Row):
    match_id: str
    official_kind: str
    official_id: Optional[str]
    official_name: str
    role_raw: str
    source_url: str
    scraped_at: str


class Player(Row):
    player_id: str
    player_name: str
    birth_year: Optional[int]
    source_url: str
    scraped_at: str
    # Derived, not scraped from this player's own fichajugador fetch - filled
    # in by player_pipeline._backfill_is_likely_coach() after the run, by
    # cross-referencing match_staff/player_season_stats (needs data outside
    # this one fetch, so it can't be set at parse time the way
    # card_type_label is). None until that backfill has run at least once.
    is_likely_coach: Optional[bool] = None


class PlayerSeasonStats(Row):
    player_id: str
    season: str
    season_id: str
    called_up: Optional[int]
    starter_appearances: Optional[int]
    substitute_appearances: Optional[int]
    matches_played: Optional[int]
    goals_total: Optional[int]
    goals_per_match: Optional[float]
    yellow_cards: Optional[int]
    red_cards: Optional[int]
    second_yellow_cards: Optional[int]
    is_goalkeeper: Optional[bool]
    jersey_number: Optional[int]
    source_url: str
    scraped_at: str


class PlayerCompetitionParticipation(Row):
    player_id: str
    season: str
    season_id: str
    competition_id: str
    competition: str
    group_id: str
    group: str
    team_id: str
    team: str
    club_name_raw: Optional[str]
    team_position: Optional[int]
    team_points: Optional[int]
    source_url: str
    scraped_at: str


class ManifestGroup(Row):
    season_id: str
    game_type_id: str
    competition_id: str
    group_id: str
    category_base: str
    category_label_raw: str
    is_femenino: bool
    division_level: str
    competition_label_raw: str
    group_label_raw: str
    has_calendario: bool
    has_clasificaciones: bool
    has_goleadores: bool


class ManifestPage(Row):
    page_kind: str
    group_id: str
    competition_id: str
    season_id: str
    game_type_id: str
    url: str
    raw_saved_path: str


class CrawlLogEntry(Row):
    run_id: str
    timestamp: str
    stage: str
    entity_type: str
    entity_id: str
    source_url: str
    http_status: Optional[int]
    success: bool
    retry_count: int
    parser_type: str
    raw_saved_path: str
    message: str
    elapsed_seconds: Optional[float] = None


class ManifestEndpoint(Row):
    name: str
    method: str
    path: str
    required_params: str
    optional_params: str
    notes: str


class DataQualityIssue(Row):
    check_name: str
    severity: str
    entity_type: str
    entity_id: str
    group_id: Optional[str]
    competition_id: Optional[str]
    details: str
