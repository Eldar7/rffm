"""fichaequipo `team` JSON -> one clubs.csv row.

Separate from acta_parsers.py/fichajugador_parsers.py (which also read
fichaequipo-adjacent enrichment pages) since this reads a different page
(fichaequipo, not acta-partido/fichajugador) and produces a different
entity (club, not match/player data).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_club(team_json: dict[str, Any], representative_team_id: str, source_url: str) -> dict:
    """codigo_club is confirmed identical across every team of the same
    club (spot-checked live on multi-team clubs), so it's the real RFFM
    club identity, not a surrogate we invented.

    domicilio_correspondencia/localidad_correspondencia/etc. are a
    correspondence address (where official mail goes), not necessarily a
    stadium address - RFFM does not publish a per-club venue. For playing
    fields, join matches.csv's venue_id against venues.csv instead.

    Deliberately excludes telefonos/email_correspondencia/fax: those are a
    club delegate's personal contact info on this page, not public club
    data.
    """
    return dict(
        club_id=str(team_json.get("codigo_club") or ""),
        club_name_raw=(team_json.get("nombre_club") or "").strip(),
        portal_web=(team_json.get("portal_web") or "").strip() or None,
        crest_url=(team_json.get("escudo_club") or "").strip() or None,
        correspondence_address=(team_json.get("domicilio_correspondencia") or "").strip() or None,
        locality=(team_json.get("localidad_correspondencia") or "").strip() or None,
        province=(team_json.get("provincia_correspondencia") or "").strip() or None,
        postal_code=(team_json.get("codigo_postal_correspondencia") or "").strip() or None,
        representative_team_id=representative_team_id,
        source_url=source_url,
        scraped_at=_now_iso(),
    )
