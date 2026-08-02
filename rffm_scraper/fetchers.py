"""Stage B: page fetchers for calendario / clasificaciones / goleadores.

Each of these server-rendered pages embeds a `<script id="__NEXT_DATA__">`
tag containing the full page state as JSON. We locate that tag by id (a
stable selector, not brittle text/CSS scraping) and parse the JSON directly
- this is effectively a hidden structured-data source riding inside HTML,
and is used in preference to scraping visible markup.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup

from rffm_scraper.config import Settings
from rffm_scraper.http_client import RffmClient

logger = logging.getLogger("rffm_scraper.fetchers")


@dataclass
class PageFetchResult:
    ok: bool
    raw_html: str | None
    page_props: dict[str, Any] | None
    url: str


def extract_next_data(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        return None
    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to decode __NEXT_DATA__: %s", exc)
        return None
    return data.get("props", {}).get("pageProps")


def fetch_page(
    client: RffmClient,
    settings: Settings,
    page_path: str,
    params: dict[str, str],
    *,
    entity_type: str,
    entity_id: str,
) -> PageFetchResult:
    result = client.get_html(
        page_path,
        params=params,
        stage="fetch_page",
        entity_type=entity_type,
        entity_id=entity_id,
    )
    url = settings.site.base_url.rstrip("/") + page_path
    if result is None:
        return PageFetchResult(ok=False, raw_html=None, page_props=None, url=url)
    html, resp = result
    page_props = extract_next_data(html)
    if page_props is None:
        logger.warning("No __NEXT_DATA__ found on %s (%s)", url, params)
        return PageFetchResult(ok=False, raw_html=html, page_props=None, url=resp.url)
    return PageFetchResult(ok=True, raw_html=html, page_props=page_props, url=resp.url)


def fetch_calendario(
    client: RffmClient, settings: Settings, *, season_id: str, competicion: str,
    grupo: str, game_type_id: str, entity_id: str,
) -> PageFetchResult:
    params = {
        "temporada": season_id,
        "competicion": competicion,
        "grupo": grupo,
        # jornada is required by the route but the page returns every
        # jornada regardless of its value - "1" is always a valid choice.
        "jornada": "1",
        "tipojuego": game_type_id,
    }
    return fetch_page(
        client, settings, settings.site.pages.calendario, params,
        entity_type="group_calendario", entity_id=entity_id,
    )


def fetch_clasificaciones(
    client: RffmClient, settings: Settings, *, season_id: str, competicion: str,
    grupo: str, game_type_id: str, entity_id: str,
) -> PageFetchResult:
    params = {
        "temporada": season_id,
        "competicion": competicion,
        "grupo": grupo,
        "tipojuego": game_type_id,
    }
    return fetch_page(
        client, settings, settings.site.pages.clasificaciones, params,
        entity_type="group_clasificaciones", entity_id=entity_id,
    )


def fetch_goleadores(
    client: RffmClient, settings: Settings, *, season_id: str, competicion: str,
    grupo: str, game_type_id: str, entity_id: str,
) -> PageFetchResult:
    params = {
        "temporada": season_id,
        "competicion": competicion,
        "grupo": grupo,
        "tipojuego": game_type_id,
    }
    return fetch_page(
        client, settings, settings.site.pages.goleadores, params,
        entity_type="group_goleadores", entity_id=entity_id,
    )


def fetch_campo(client: RffmClient, settings: Settings, venue_id: str) -> PageFetchResult:
    """Venue/field profile page. NOT robots.txt-disallowed (unlike the three
    fetchers below) - part of the core crawl, no enrichment opt-in needed.
    """
    return fetch_page(
        client, settings, f"{settings.site.pages.campo}/{venue_id}", {},
        entity_type="venue_campo", entity_id=venue_id,
    )


def fetch_acta_partido(
    client: RffmClient, settings: Settings, *, season_id: str, competicion: str,
    grupo: str, match_id: str,
) -> PageFetchResult:
    """Enrichment only. robots.txt disallows /acta-partido/ - only call this
    when settings.enrichment.fetch_acta_partido is explicitly enabled.

    URL confirmed by live sampling: /acta-partido/<match_id>?temporada=&competicion=&grupo=
    (no tipojuego, unlike the three group-level page fetchers above).
    """
    params = {"temporada": season_id, "competicion": competicion, "grupo": grupo}
    return fetch_page(
        client, settings, f"{settings.site.pages.acta_partido}/{match_id}", params,
        entity_type="match_acta", entity_id=match_id,
    )


def fetch_fichaequipo(client: RffmClient, settings: Settings, team_id: str) -> PageFetchResult:
    """Enrichment only. robots.txt disallows /fichaequipo/ - only call this
    when settings.enrichment.fetch_fichaequipo is explicitly enabled."""
    return fetch_page(
        client, settings, f"{settings.site.pages.fichaequipo}/{team_id}", {},
        entity_type="team_ficha", entity_id=team_id,
    )


def fetch_fichajugador(
    client: RffmClient, settings: Settings, *, season_id: str, player_id: str,
) -> PageFetchResult:
    """Enrichment only. robots.txt disallows /fichajugador/ - only call this
    when settings.enrichment.fetch_fichajugador is explicitly enabled.

    URL confirmed by live sampling: /fichajugador/<player_id>?temporada=<season_id>.
    The bare URL (no query param) silently defaults to the *current* season,
    so temporada is always passed explicitly.
    """
    params = {"temporada": season_id}
    return fetch_page(
        client, settings, f"{settings.site.pages.fichajugador}/{player_id}", params,
        entity_type="player_ficha", entity_id=player_id,
    )
