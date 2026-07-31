"""Parse /fichajugador/<player_id> embedded `pageProps.player` JSON.

One fetch maps to three tables: a stable player identity row, a per-season
stats snapshot, and zero-or-more per-competition participation rows (a
player can be registered to more than one team/competition in the same
season - e.g. reserve-team + first-team dual registration, confirmed on a
real player during research).

`partidos` and `tarjetas` on the raw JSON are `[{"nombre": ..., "valor":
...}]`-shaped arrays, not fixed keys - parsed here by matching on `nombre`
(the site's own Spanish label), not by position, so a reordering upstream
can't silently swap two stats.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from rffm_scraper.normalize import to_bool_or_none, to_float_or_none, to_int_or_none

logger = logging.getLogger("rffm_scraper.fichajugador_parsers")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _name_value_map(entries: list[dict] | None) -> dict[str, str]:
    return {e.get("nombre"): e.get("valor") for e in (entries or []) if e.get("nombre")}


def parse_player_profile(player: dict[str, Any], *, source_url: str) -> dict[str, Any]:
    """Returns {"player": {...}, "season_stats": {...}, "competitions": [...]}."""
    scraped_at = _now_iso()
    player_id = player.get("codigo_jugador", "")

    player_row = dict(
        player_id=player_id,
        player_name=player.get("nombre_jugador", ""),
        birth_year=to_int_or_none(player.get("anio_nacimiento")),
        source_url=source_url,
        scraped_at=scraped_at,
    )

    partidos = _name_value_map(player.get("partidos"))
    tarjetas = _name_value_map(player.get("tarjetas"))

    season_stats_row = dict(
        player_id=player_id,
        season=player.get("nombre_temporada", ""),
        season_id=player.get("codigo_temporada", ""),
        called_up=to_int_or_none(partidos.get("Convocados")),
        starter_appearances=to_int_or_none(partidos.get("Titular")),
        substitute_appearances=to_int_or_none(partidos.get("Suplente")),
        matches_played=to_int_or_none(partidos.get("Jugados")),
        goals_total=to_int_or_none(partidos.get("Total Goles")),
        goals_per_match=to_float_or_none(partidos.get("Media Goles por partido")),
        yellow_cards=to_int_or_none(tarjetas.get("Amarillas")),
        red_cards=to_int_or_none(tarjetas.get("Rojas")),
        second_yellow_cards=to_int_or_none(tarjetas.get("Doble Amarilla")),
        is_goalkeeper=to_bool_or_none(player.get("es_portero")),
        jersey_number=to_int_or_none(player.get("dorsal_jugador")),
        source_url=source_url,
        scraped_at=scraped_at,
    )

    competition_rows = []
    for entry in player.get("competiciones_participa") or []:
        competition_rows.append(
            dict(
                player_id=player_id,
                season=player.get("nombre_temporada", ""),
                season_id=player.get("codigo_temporada", ""),
                competition_id=entry.get("codigo_competicion", ""),
                competition=entry.get("nombre_competicion", ""),
                group_id=entry.get("codgrupo", ""),
                group=entry.get("nombre_grupo", ""),
                team_id=entry.get("codequipo", ""),
                team=entry.get("nombre_equipo", ""),
                club_name_raw=entry.get("nombre_club") or None,
                team_position=to_int_or_none(entry.get("posicion_equipo")),
                team_points=to_int_or_none(entry.get("puntos_equipo")),
                source_url=source_url,
                scraped_at=scraped_at,
            )
        )

    return dict(player=player_row, season_stats=season_stats_row, competitions=competition_rows)
