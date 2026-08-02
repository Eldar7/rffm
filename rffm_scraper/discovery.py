"""Stage A: discovery of competitions/groups for the target season+categories.

Uses the hidden JSON endpoints reverse-engineered from the site's Next.js
client bundle (see README) rather than any hardcoded list of competition or
group ids:

    /api/seasons                                -> season list
    /api/game-types                             -> game type list
    /api/competitions?temporada=&tipojuego=      -> competitions per season+game type
    /api/groups?competicion=                     -> groups per competition

Every game type is probed (not just Futbol-7) so that the category filter,
not an assumption about game type, decides what is in scope. Empirically
for 2025-2026 this surfaces both Futbol-7 and Futbol Sala competitions for
BENJAMIN/PREBENJAMIN.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone

from rffm_scraper.config import Settings
from rffm_scraper.http_client import RffmClient
from rffm_scraper.normalize import match_category_base, phase_label_from_competition_name

logger = logging.getLogger("rffm_scraper.discovery")


@dataclasses.dataclass
class DiscoveredGroup:
    season_id: str
    season_label: str
    game_type_id: str
    game_type_label: str
    competition_id: str
    competition_label_raw: str
    category_base: str
    category_label_raw: str
    phase_label: str
    group_id: str
    group_label_raw: str
    total_jornadas: int | None
    total_equipos: int | None
    clasificacion_goleadores: bool
    ver_clasificacion: bool


@dataclasses.dataclass
class DiscoveryResult:
    season_id: str
    season_label: str
    seasons_raw: list[dict]
    game_types_raw: list[dict]
    groups: list[DiscoveredGroup]


def _resolve_season_id(seasons_raw: list[dict], season_label: str) -> str:
    for s in seasons_raw:
        if s.get("nombre") == season_label:
            return s["cod_temporada"]
    raise ValueError(
        f"Season label {season_label!r} not found in /api/seasons response: "
        f"{[s.get('nombre') for s in seasons_raw]}"
    )


def run_discovery(client: RffmClient, settings: Settings) -> DiscoveryResult:
    api = settings.site.api

    seasons_raw = client.get_json(api.seasons, stage="discovery", entity_type="seasons") or []
    game_types_raw = client.get_json(api.game_types, stage="discovery", entity_type="game_types") or []

    season_id = _resolve_season_id(seasons_raw, settings.target.season_label)
    logger.info("Resolved season %s -> cod_temporada=%s", settings.target.season_label, season_id)

    groups: list[DiscoveredGroup] = []

    for gt in game_types_raw:
        game_type_id = gt["codigo_tipo_juego"]
        game_type_label = gt["nombre"]

        competitions = client.get_json(
            api.competitions,
            params={"temporada": season_id, "tipojuego": game_type_id},
            stage="discovery",
            entity_type="competitions",
            entity_id=f"temporada={season_id}&tipojuego={game_type_id}",
        )
        if not competitions:
            continue

        if settings.target.crawl_all_categories:
            matching = competitions
        else:
            matching = [
                c for c in competitions
                if match_category_base(c.get("NombreCategoria", ""), settings.target.category_priority)
            ]
        logger.info(
            "game_type=%s (%s): %d competitions total, %d match target categories",
            game_type_id, game_type_label, len(competitions), len(matching),
        )

        for comp in matching:
            competition_id = comp["codigo"]
            if settings.target.crawl_all_categories:
                # No priority list to match against - every competition's
                # own raw label is its category_base as-is.
                category_base = comp.get("NombreCategoria", "").strip() or None
            else:
                category_base = match_category_base(
                    comp.get("NombreCategoria", ""), settings.target.category_priority
                )
            phase_label = phase_label_from_competition_name(comp.get("nombre", ""))

            group_list = client.get_json(
                api.groups,
                params={"competicion": competition_id},
                stage="discovery",
                entity_type="groups",
                entity_id=competition_id,
            )
            for grp in group_list or []:
                groups.append(
                    DiscoveredGroup(
                        season_id=season_id,
                        season_label=settings.target.season_label,
                        game_type_id=game_type_id,
                        game_type_label=game_type_label,
                        competition_id=competition_id,
                        competition_label_raw=comp.get("nombre", ""),
                        category_base=category_base or "",
                        category_label_raw=comp.get("NombreCategoria", ""),
                        phase_label=phase_label,
                        group_id=grp["codigo"],
                        group_label_raw=grp.get("nombre", ""),
                        total_jornadas=_safe_int(grp.get("total_jornadas")),
                        total_equipos=_safe_int(grp.get("total_equipos")),
                        clasificacion_goleadores=grp.get("clasificacion_goleadores") == "1",
                        ver_clasificacion=grp.get("ver_clasificacion") == "1",
                    )
                )

    result = DiscoveryResult(
        season_id=season_id,
        season_label=settings.target.season_label,
        seasons_raw=seasons_raw,
        game_types_raw=game_types_raw,
        groups=groups,
    )
    _save_manifest(settings, result)
    return result


def _safe_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _save_manifest(settings: Settings, result: DiscoveryResult) -> None:
    settings.discovery_dir.mkdir(parents=True, exist_ok=True)
    path = settings.discovery_dir / f"manifest_{result.season_id}_{_now_slug()}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season_id": result.season_id,
        "season_label": result.season_label,
        "seasons_raw": result.seasons_raw,
        "game_types_raw": result.game_types_raw,
        "groups": [dataclasses.asdict(g) for g in result.groups],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("Saved discovery manifest: %s (%d groups)", path, len(result.groups))


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
