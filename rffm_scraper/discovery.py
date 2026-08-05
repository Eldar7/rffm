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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from rffm_scraper.config import Settings
from rffm_scraper.http_client import RffmClient
from rffm_scraper.normalize import (
    classify_age_category,
    classify_division_level,
    is_femenino_label,
    match_category_base,
    phase_label_from_competition_name,
)

logger = logging.getLogger("rffm_scraper.discovery")


# Surgical data correction agreed for 2022-2023 only: these competition ids
# are explicit "1ª PREBENJAMIN ..." stages that should be classified as
# PRIMERA. Keyed by (season_label, competition_id) to avoid touching any
# other season or competition naming pattern.
DIVISION_LEVEL_OVERRIDES: dict[tuple[str, str], str] = {
    ("2022-2023", "16948677"): "PRIMERA",
    ("2022-2023", "16907698"): "PRIMERA",
    ("2022-2023", "16969301"): "PRIMERA",
    ("2025-2026", "26687967"): "PRIMERA",
    ("2025-2026", "26700985"): "PRIMERA",
    ("2025-2026", "26701868"): "PRIMERA",
}


def _override_division_level_if_needed(season_label: str, competition_id: str, current: str) -> str:
    return DIVISION_LEVEL_OVERRIDES.get((season_label, competition_id), current)


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
    is_femenino: bool
    division_level: str
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


def run_discovery(client: RffmClient, settings: Settings, *, workers: int = 1) -> DiscoveryResult:
    api = settings.site.api

    seasons_raw = client.get_json(api.seasons, stage="discovery", entity_type="seasons") or []
    game_types_raw = client.get_json(api.game_types, stage="discovery", entity_type="game_types") or []

    season_id = _resolve_season_id(seasons_raw, settings.target.season_label)
    logger.info("Resolved season %s -> cod_temporada=%s", settings.target.season_label, season_id)

    competition_tasks: list[tuple[dict, str, str, str, str, bool, str]] = []

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
            raw_category_label = comp.get("NombreCategoria", "")
            if settings.target.crawl_all_categories:
                # No config-supplied priority list to match against - use
                # the fixed age vocabulary instead (see normalize.py), which
                # covers every age RFFM runs, not just this project's
                # BENJAMIN/PREBENJAMIN scope. Falls through to "OTHER"
                # rather than the raw label itself, so BENJAMIN/PREBENJAMIN
                # (and every other age) stay consolidated buckets here too -
                # see DATA_DICTIONARY.md's "Category taxonomy" section for
                # why a previous version of this (raw label passthrough)
                # was a regression: it silently broke acta_partido's
                # `category == scope_category` filter for BENJAMIN/
                # PREBENJAMIN by fragmenting them across a dozen raw labels.
                category_base = classify_age_category(
                    raw_category_label, fallback_label=comp.get("nombre", "")
                )
            else:
                category_base = match_category_base(
                    raw_category_label, settings.target.category_priority
                )
            division_level = classify_division_level(
                raw_category_label, fallback_label=comp.get("nombre", "")
            )
            division_level = _override_division_level_if_needed(
                settings.target.season_label,
                str(comp.get("codigo", "")),
                division_level,
            )
            is_fem = is_femenino_label(raw_category_label)
            phase_label = phase_label_from_competition_name(comp.get("nombre", ""))

            competition_tasks.append(
                (comp, game_type_id, game_type_label, category_base or "", raw_category_label, is_fem, division_level)
            )

    def fetch_competition_groups(
        index: int, task: tuple[dict, str, str, str, str, bool, str], task_client: RffmClient,
    ) -> tuple[int, list[DiscoveredGroup], list]:
        comp, game_type_id, game_type_label, category_base, raw_category_label, is_fem, division_level = task
        competition_id = comp["codigo"]
        log_start = len(task_client.crawl_log)
        group_list = task_client.get_json(
            api.groups,
            params={"competicion": competition_id},
            stage="discovery",
            entity_type="groups",
            entity_id=competition_id,
        )
        discovered = [
            DiscoveredGroup(
                season_id=season_id,
                season_label=settings.target.season_label,
                game_type_id=game_type_id,
                game_type_label=game_type_label,
                competition_id=competition_id,
                competition_label_raw=comp.get("nombre", ""),
                category_base=category_base,
                category_label_raw=raw_category_label,
                is_femenino=is_fem,
                division_level=division_level,
                phase_label=phase_label_from_competition_name(comp.get("nombre", "")),
                group_id=grp["codigo"],
                group_label_raw=grp.get("nombre", ""),
                total_jornadas=_safe_int(grp.get("total_jornadas")),
                total_equipos=_safe_int(grp.get("total_equipos")),
                clasificacion_goleadores=grp.get("clasificacion_goleadores") == "1",
                ver_clasificacion=grp.get("ver_clasificacion") == "1",
            )
            for grp in (group_list or [])
        ]
        return index, discovered, task_client.crawl_log[log_start:]

    grouped: list[list[DiscoveredGroup] | None] = [None] * len(competition_tasks)
    if workers == 1:
        for index, task in enumerate(competition_tasks):
            _, discovered, _ = fetch_competition_groups(index, task, client)
            grouped[index] = discovered
    else:
        local = threading.local()

        def fetch_in_worker(index: int, task: tuple[dict, str, str, str, str, bool, str]):
            if not hasattr(local, "client"):
                local.client = RffmClient(settings, run_id=client.run_id)
            return fetch_competition_groups(index, task, local.client)

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rffm-discovery") as executor:
            futures = [executor.submit(fetch_in_worker, index, task) for index, task in enumerate(competition_tasks)]
            for completed, future in enumerate(as_completed(futures), start=1):
                index, discovered, logs = future.result()
                grouped[index] = discovered
                client.crawl_log.extend(logs)
                if completed % 25 == 0 or completed == len(competition_tasks):
                    logger.info("discovery groups progress: %d/%d competitions", completed, len(competition_tasks))

    groups = [group for discovered in grouped if discovered for group in discovered]

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
