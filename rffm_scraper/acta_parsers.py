"""Parse /acta-partido/<match_id> embedded `pageProps.game` JSON.

Kept separate from parsers.py because one acta-partido fetch maps to five
output tables (lineups/goals/cards/staff/officials), unlike the 1:1
page->table shape of the core pipeline's parsers.

Card-type codes ("100"/"101"/"102") were cross-referenced against
/fichajugador/'s explicitly-labeled `tarjetas` breakdown (same numeric codes,
labeled "Amarillas"/"Rojas"/"Doble Amarilla" there) - CARD_TYPE_LABELS below
is that inferred mapping, not an officially documented one. `tipo_gol` on
goal events has no such cross-reference anywhere on the site and is kept
opaque on purpose.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from rffm_scraper.normalize import team_id_or_none, to_bool_or_none, to_int_or_none

logger = logging.getLogger("rffm_scraper.acta_parsers")

CARD_TYPE_LABELS = {
    "100": "amarilla",
    "101": "roja",
    "102": "doble_amarilla",
}

# RFFM uses this literal string as a "role not reported" placeholder (seen on
# a bye match's blank coach/delegate slots) - treat it, and blank names, as
# absent rather than storing a person named "No presenta".
_ABSENT_NAME_SENTINELS = {"", "NO PRESENTA"}

# NOTE: goals/cards are intentionally NOT deduplicated, even when two entries
# in game["goles_equipo_*"]/["tarjetas_equipo_*"] are identical in every
# field (same player/minute/type). A prior version of this module dropped
# such "exact duplicates" - reverted after checking match 5334992 live: its
# goles_equipo_local array lists the same player/minute goal twice, and
# len(goles_equipo_local)==8 matches both game["goles_local"]=="8" AND the
# independently-scraped calendario-page score in matches.csv (home_score=8).
# Sampling other matches with a repeated entry showed the same pattern:
# raw event count (duplicate included) matches the scored total; dropping
# the "duplicate" undercounts by exactly one. So these are real, distinct
# events RFFM's own system happens to record identically down to the
# minute - not a scrape/data artifact - and must be kept as-is.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_absent(name: str | None) -> bool:
    return name is None or name.strip().upper() in _ABSENT_NAME_SENTINELS


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def parse_acta_partido(
    game: dict[str, Any],
    *,
    match_id: str,
    home_team_id: str,
    away_team_id: str,
    source_url: str,
) -> dict[str, list]:
    """Returns {"lineups", "goals", "cards", "staff", "officials", "warnings"}.

    home_team_id/away_team_id come from matches.csv (the caller), not the
    acta page itself, so every row here is join-consistent with matches.csv
    by construction. The page's own codigo_equipo_local/_visitante are only
    used defensively, to flag (via "warnings") a mismatch worth surfacing as
    a data-quality issue - never to override the passed-in ids.
    """
    scraped_at = _now_iso()
    warnings: list[dict] = []

    page_home_id = team_id_or_none(game.get("codigo_equipo_local"))
    page_away_id = team_id_or_none(game.get("codigo_equipo_visitante"))
    if page_home_id and page_home_id != home_team_id:
        warnings.append(
            dict(
                match_id=match_id,
                message=(
                    f"acta home team_id {page_home_id!r} != matches.csv home_team_id {home_team_id!r}"
                ),
            )
        )
    if page_away_id and page_away_id != away_team_id:
        warnings.append(
            dict(
                match_id=match_id,
                message=(
                    f"acta away team_id {page_away_id!r} != matches.csv away_team_id {away_team_id!r}"
                ),
            )
        )

    common = dict(match_id=match_id, source_url=source_url, scraped_at=scraped_at)
    return dict(
        lineups=_parse_lineups(game, home_team_id=home_team_id, away_team_id=away_team_id, **common),
        goals=_parse_goals(game, home_team_id=home_team_id, away_team_id=away_team_id, **common),
        cards=_parse_cards(game, home_team_id=home_team_id, away_team_id=away_team_id, **common),
        staff=_parse_staff(game, home_team_id=home_team_id, away_team_id=away_team_id, **common),
        officials=_parse_officials(game, **common),
        warnings=warnings,
    )


def _parse_lineups(game, *, match_id, home_team_id, away_team_id, source_url, scraped_at) -> list[dict]:
    rows = []
    for team_id, key in (
        (home_team_id, "jugadores_equipo_local"),
        (away_team_id, "jugadores_equipo_visitante"),
    ):
        for entry in game.get(key) or []:
            rows.append(
                dict(
                    match_id=match_id,
                    team_id=team_id,
                    player_id=entry.get("codjugador", ""),
                    player_name_raw=entry.get("nombre_jugador", ""),
                    jersey_number=to_int_or_none(entry.get("dorsal")),
                    is_starter=to_bool_or_none(entry.get("titular")),
                    is_substitute=to_bool_or_none(entry.get("suplente")),
                    is_captain=to_bool_or_none(entry.get("capitan")),
                    is_goalkeeper=to_bool_or_none(entry.get("portero")),
                    position_raw=_str_or_none(entry.get("posicion")),
                    position_abbr_raw=_str_or_none(entry.get("posicion_jugador_abreviatura")),
                    sex_raw=_str_or_none(entry.get("sexo")),
                    source_url=source_url,
                    scraped_at=scraped_at,
                )
            )
    return rows


def _parse_goals(game, *, match_id, home_team_id, away_team_id, source_url, scraped_at) -> list[dict]:
    rows = []
    for team_id, key in (
        (home_team_id, "goles_equipo_local"),
        (away_team_id, "goles_equipo_visitante"),
    ):
        for entry in game.get(key) or []:
            minute_raw = entry.get("minuto")
            rows.append(
                dict(
                    match_id=match_id,
                    team_id=team_id,
                    player_id=_str_or_none(entry.get("codjugador")),
                    player_name_raw=entry.get("nombre_jugador", ""),
                    minute=to_int_or_none(minute_raw),
                    minute_raw=_str_or_none(minute_raw),
                    goal_type_raw=_str_or_none(entry.get("tipo_gol")),
                    source_url=source_url,
                    scraped_at=scraped_at,
                )
            )
    return rows


def _parse_cards(game, *, match_id, home_team_id, away_team_id, source_url, scraped_at) -> list[dict]:
    rows = []
    for team_id, key in (
        (home_team_id, "tarjetas_equipo_local"),
        (away_team_id, "tarjetas_equipo_visitante"),
    ):
        for entry in game.get(key) or []:
            minute_raw = entry.get("minuto")
            card_type_raw = _str_or_none(entry.get("codigo_tipo_amonestacion"))
            rows.append(
                dict(
                    match_id=match_id,
                    team_id=team_id,
                    player_id=_str_or_none(entry.get("codjugador")),
                    player_name_raw=entry.get("nombre_jugador", ""),
                    minute=to_int_or_none(minute_raw),
                    minute_raw=_str_or_none(minute_raw),
                    card_type_raw=card_type_raw,
                    card_type_label=CARD_TYPE_LABELS.get(card_type_raw or ""),
                    is_second_yellow=to_bool_or_none(entry.get("segunda_amarilla")),
                    source_url=source_url,
                    scraped_at=scraped_at,
                )
            )
    return rows


def _add_staff_row(rows, *, match_id, team_id, role_kind, name, person_id, source_url, scraped_at):
    if _is_absent(name):
        return
    rows.append(
        dict(
            match_id=match_id,
            team_id=team_id,
            role_kind=role_kind,
            role_raw=role_kind,
            person_id=_str_or_none(person_id),
            person_name=name.strip(),
            source_url=source_url,
            scraped_at=scraped_at,
        )
    )


def _parse_staff(game, *, match_id, home_team_id, away_team_id, source_url, scraped_at) -> list[dict]:
    rows: list[dict] = []
    common = dict(match_id=match_id, source_url=source_url, scraped_at=scraped_at)

    # Field naming is genuinely asymmetric between local/visitante on this
    # site (e.g. the visitante assistant coach's id field is
    # "cod_entrenador_visitante2", not "cod_entrenador2_visitante") - keys
    # are spelled out explicitly per side rather than derived from a pattern.
    sides = (
        (
            home_team_id,
            dict(
                head_coach=("entrenador_local", "cod_entrenador_local"),
                assistant_coach=("entrenador2_local", "cod_entrenador2_local"),
                team_delegate=("delegadolocal", None),
                otros_tecnicos_key="otros_tecnicos_local",
            ),
        ),
        (
            away_team_id,
            dict(
                head_coach=("entrenador_visitante", "cod_entrenador_visitante"),
                assistant_coach=("entrenador2_visitante", "cod_entrenador_visitante2"),
                team_delegate=("delegado_visitante", None),
                otros_tecnicos_key="otros_tecnicos_visitante",
            ),
        ),
    )
    for team_id, spec in sides:
        for role_kind in ("head_coach", "assistant_coach", "team_delegate"):
            name_key, id_key = spec[role_kind]
            _add_staff_row(
                rows,
                team_id=team_id,
                role_kind=role_kind,
                name=game.get(name_key),
                person_id=game.get(id_key) if id_key else None,
                **common,
            )
        for entry in game.get(spec["otros_tecnicos_key"]) or []:
            name = entry.get("nombre")
            if _is_absent(name):
                continue
            rows.append(
                dict(
                    match_id=match_id,
                    team_id=team_id,
                    role_kind="other_staff",
                    role_raw=entry.get("tipo", ""),
                    person_id=_str_or_none(entry.get("cod_tecnico")),
                    person_name=name.strip(),
                    source_url=source_url,
                    scraped_at=scraped_at,
                )
            )
    return rows


def _parse_officials(game, *, match_id, source_url, scraped_at) -> list[dict]:
    rows = []
    for entry in game.get("arbitros_partido") or []:
        name = entry.get("nombre_arbitro")
        if _is_absent(name):
            continue
        rows.append(
            dict(
                match_id=match_id,
                official_kind="referee",
                official_id=_str_or_none(entry.get("cod_arbitro")),
                official_name=name.strip(),
                role_raw=entry.get("tipo_arbitro", ""),
                source_url=source_url,
                scraped_at=scraped_at,
            )
        )
    field_delegate = game.get("delegadocampo")
    if not _is_absent(field_delegate):
        rows.append(
            dict(
                match_id=match_id,
                official_kind="field_delegate",
                official_id=None,
                official_name=field_delegate.strip(),
                role_raw="delegado_campo",
                source_url=source_url,
                scraped_at=scraped_at,
            )
        )
    return rows
