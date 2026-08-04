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
