"""Stage C: turn embedded page-state JSON into row dicts for the data model.

Deliberately dict-in/dict-out (not the pydantic Row models) - validation
into the strict Row models happens once, centrally, in pipeline.py, so a
single malformed record can be logged and dropped without derailing an
entire group's worth of otherwise-good rows.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from rffm_scraper.normalize import (
    parse_date_to_iso,
    parse_matchday_label,
    parse_team_name,
    team_id_or_none,
    to_float_or_none,
    to_int_or_none,
)

logger = logging.getLogger("rffm_scraper.parsers")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GroupContext:
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


def parse_matches(
    calendar_json: dict[str, Any], ctx: GroupContext, source_url: str
) -> list[dict]:
    rows: list[dict] = []
    scraped_at = _now_iso()
    for round_ in calendar_json.get("rounds", []):
        matchday, matchday_label = parse_matchday_label(round_.get("jornada"))
        for game in round_.get("equipos", []):
            home_id = team_id_or_none(game.get("codigo_equipo_local"))
            away_id = team_id_or_none(game.get("codigo_equipo_visitante"))
            home_score = to_int_or_none(game.get("goles_casa"))
            away_score = to_int_or_none(game.get("goles_visitante"))
            fecha = (game.get("fecha") or "").strip()
            hora = (game.get("hora") or "").strip()
            is_finished = home_score is not None and away_score is not None
            is_scheduled = bool(fecha)
            if is_finished:
                status = "finished"
            elif is_scheduled:
                status = "scheduled"
            else:
                status = "unscheduled"

            raw_home_score = (game.get("goles_casa") or "").strip()
            raw_away_score = (game.get("goles_visitante") or "").strip()
            result_text_raw = (
                f"{raw_home_score}-{raw_away_score}"
                if raw_home_score and raw_away_score
                else None
            )

            match_id = game.get("codacta") or None
            match_datetime_raw = f"{fecha} {hora}".strip() if fecha else None

            rows.append(
                dict(
                    season=ctx.season,
                    season_id=ctx.season_id,
                    category=ctx.category,
                    competition=ctx.competition,
                    competition_id=ctx.competition_id,
                    group=ctx.group,
                    group_id=ctx.group_id,
                    game_type=ctx.game_type,
                    game_type_id=ctx.game_type_id,
                    phase_label=ctx.phase_label,
                    matchday=matchday,
                    matchday_label=matchday_label,
                    match_id=match_id,
                    home_team=game.get("equipo_local", ""),
                    home_team_id=home_id,
                    away_team=game.get("equipo_visitante", ""),
                    away_team_id=away_id,
                    home_score=home_score,
                    away_score=away_score,
                    match_date=parse_date_to_iso(fecha),
                    match_time=hora or None,
                    match_datetime_raw=match_datetime_raw,
                    venue=(game.get("campo") or "").strip() or None,
                    venue_id=team_id_or_none(game.get("codigo_campo")),
                    status=status,
                    is_finished=is_finished,
                    is_scheduled=is_scheduled,
                    result_text_raw=result_text_raw,
                    source_url=source_url,
                    source_type="calendario_page",
                    scraped_at=scraped_at,
                )
            )
    return rows


def parse_standings(
    standings_json: dict[str, Any], ctx: GroupContext, source_url: str
) -> list[dict]:
    rows: list[dict] = []
    scraped_at = _now_iso()
    for entry in standings_json.get("clasificacion", []):
        goals_for = to_int_or_none(entry.get("goles_a_favor"))
        goals_against = to_int_or_none(entry.get("goles_en_contra"))
        goal_diff = (
            goals_for - goals_against if goals_for is not None and goals_against is not None else None
        )
        rows.append(
            dict(
                season=ctx.season,
                season_id=ctx.season_id,
                category=ctx.category,
                competition=ctx.competition,
                competition_id=ctx.competition_id,
                group=ctx.group,
                group_id=ctx.group_id,
                team=entry.get("nombre", ""),
                team_id=team_id_or_none(entry.get("codequipo")),
                position=to_int_or_none(entry.get("posicion")),
                played=to_int_or_none(entry.get("jugados")),
                wins=to_int_or_none(entry.get("ganados")),
                draws=to_int_or_none(entry.get("empatados")),
                losses=to_int_or_none(entry.get("perdidos")),
                goals_for=goals_for,
                goals_against=goals_against,
                goal_diff=goal_diff,
                points=to_int_or_none(entry.get("puntos")),
                sanction_points=to_int_or_none(entry.get("puntos_sancion")),
                source_url=source_url,
                scraped_at=scraped_at,
            )
        )
    return rows


def parse_scorers(
    scorers_json: dict[str, Any], ctx: GroupContext, source_url: str
) -> list[dict]:
    rows: list[dict] = []
    scraped_at = _now_iso()
    for entry in scorers_json.get("goles", []):
        rows.append(
            dict(
                season=ctx.season,
                competition_id=ctx.competition_id,
                group_id=ctx.group_id,
                team_id=team_id_or_none(entry.get("codigo_equipo")),
                player_name=entry.get("jugador", ""),
                goals=to_int_or_none(entry.get("goles")),
                source_url=source_url,
                scraped_at=scraped_at,
            )
        )
    return rows


def teams_from_matches_and_standings(
    match_rows: list[dict], standing_rows: list[dict]
) -> dict[str, dict]:
    """Collect a team_id -> team row dict from parsed matches + standings.

    Rows without a resolvable team_id (byes / 'No asignado' placeholders)
    are intentionally excluded - teams.csv is keyed by canonical team_id.
    """
    scraped_at = _now_iso()
    teams: dict[str, dict] = {}

    def _add(team_id: str | None, raw_name: str, source_team_url: str):
        if not team_id or not raw_name:
            return
        if team_id in teams:
            return
        club_name_raw, squad_suffix = parse_team_name(raw_name)
        team_display = club_name_raw + (f" {squad_suffix}" if squad_suffix else "")
        teams[team_id] = dict(
            team_id=team_id,
            team=team_display,
            team_name_raw=raw_name,
            club_name_raw=club_name_raw,
            squad_suffix=squad_suffix,
            source_team_url=source_team_url,
            scraped_at=scraped_at,
        )

    for m in match_rows:
        if m["home_team_id"]:
            _add(m["home_team_id"], m["home_team"], f"/fichaequipo/{m['home_team_id']}")
        if m["away_team_id"]:
            _add(m["away_team_id"], m["away_team"], f"/fichaequipo/{m['away_team_id']}")
    for s in standing_rows:
        if s["team_id"]:
            _add(s["team_id"], s["team"], f"/fichaequipo/{s['team_id']}")
    return teams


def team_group_memberships(
    match_rows: list[dict],
    standing_rows: list[dict],
    ctx: GroupContext,
    source_url: str,
) -> dict[str, dict]:
    scraped_at = _now_iso()
    members: dict[str, dict] = {}

    def _add(team_id: str | None, team_name: str):
        if not team_id or team_id in members:
            return
        members[team_id] = dict(
            season=ctx.season,
            season_id=ctx.season_id,
            competition_id=ctx.competition_id,
            group_id=ctx.group_id,
            team_id=team_id,
            team=team_name,
            source_url=source_url,
            scraped_at=scraped_at,
        )

    for m in match_rows:
        _add(m["home_team_id"], m["home_team"])
        _add(m["away_team_id"], m["away_team"])
    for s in standing_rows:
        _add(s["team_id"], s["team"])
    return members


def parse_venue(field_json: dict[str, Any], venue_id: str, source_url: str) -> dict:
    """/campo/<id> page's `field` object -> one venues.csv row.

    latitude/longitude come straight from the source (not geocoded), so
    google_maps_url is exact when both are present.
    """
    lat = to_float_or_none(field_json.get("latitud"))
    lon = to_float_or_none(field_json.get("longitud"))
    return dict(
        venue_id=venue_id,
        venue_name=field_json.get("nombre_campo", ""),
        address=(field_json.get("direccion") or "").strip() or None,
        locality=(field_json.get("localidad") or "").strip() or None,
        province=(field_json.get("provincia") or "").strip() or None,
        postal_code=(field_json.get("codigo_postal") or "").strip() or None,
        latitude=lat,
        longitude=lon,
        google_maps_url=f"https://www.google.com/maps?q={lat},{lon}" if lat is not None and lon is not None else None,
        field_type_raw=(field_json.get("tipo_campo") or "").strip() or None,
        surface_raw=(field_json.get("superficie_juego") or "").strip() or None,
        source_url=source_url,
        scraped_at=_now_iso(),
    )
