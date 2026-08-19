"""fichaclub `club` JSON -> clubs_extended.csv / club_teams.csv rows.

Separate from club_parsers.py on purpose - that module reads a different
page (fichaequipo, one representative team per club) and produces a
different, one-row-per-club-id table (clubs.csv). This module reads the
club's own richer profile page (fichaclub) and produces two append-only
snapshot tables - see club_profile_pipeline.py's module docstring for why
"append-only" instead of upserted.

Deliberately includes telefonos/fax/email_correspondencia/
titular_correspondencia/presidente (personal contact info of club officers)
- unlike clubs.csv, which excludes these - a deliberate, explicit choice for
this table, not an oversight.
"""
from __future__ import annotations

from typing import Any


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_club_profile(club_json: dict[str, Any], *, source_url: str, scraped_at: str) -> dict:
    return dict(
        club_id=str(club_json.get("codigo") or ""),
        club_name=_clean(club_json.get("nombre_club")),
        crest_url=_clean(club_json.get("escudo")),
        delegacion=_clean(club_json.get("delegacion")),
        comarca=_clean(club_json.get("comarca")),
        cif=_clean(club_json.get("CIF")),
        registered_address=_clean(club_json.get("domicilio")),
        registered_locality=_clean(club_json.get("localidad")),
        registered_province=_clean(club_json.get("provincia")),
        registered_postal_code=_clean(club_json.get("codigo_postal")),
        correspondence_address=_clean(club_json.get("domicilio_correspondencia")),
        correspondence_locality=_clean(club_json.get("localidad_correspondencia")),
        correspondence_province=_clean(club_json.get("provincia_correspondencia")),
        correspondence_postal_code=_clean(club_json.get("codigo_postal_correspondencia")),
        correspondence_titular=_clean(club_json.get("titular_correspondencia")),
        correspondence_tratamiento=_clean(club_json.get("tratamiento_correspondencia")),
        correspondence_email=_clean(club_json.get("email_correspondencia")),
        portal_web=_clean(club_json.get("portal_web")),
        twitter=_clean(club_json.get("twitter")),
        facebook=_clean(club_json.get("facebook")),
        linkedin=_clean(club_json.get("linkedin")),
        instagram=_clean(club_json.get("instagram")),
        telefonos=_clean(club_json.get("telefonos")),
        fax=_clean(club_json.get("fax")),
        fecha_fundacion=_clean(club_json.get("fecha_fundacion")),
        presidente=_clean(club_json.get("presidente")),
        source_url=source_url,
        scraped_at=scraped_at,
    )


def parse_club_teams(club_json: dict[str, Any], *, club_id: str, source_url: str, scraped_at: str) -> list[dict]:
    """en_competicion: site's own flag, "1" for a team currently registered
    in a live competition, "0" for a historical/inactive team the club has
    fielded in the past."""
    rows = []
    for team in club_json.get("equipos_club") or []:
        en_comp_raw = team.get("en_competicion")
        en_competicion = {"1": True, "0": False}.get(str(en_comp_raw)) if en_comp_raw is not None else None
        rows.append(
            dict(
                club_id=club_id,
                team_id=str(team.get("codigo_equipo") or ""),
                categoria=_clean(team.get("categoria")),
                team_name_raw=_clean(team.get("nombre_equipo")),
                en_competicion=en_competicion,
                source_url=source_url,
                scraped_at=scraped_at,
            )
        )
    return rows
