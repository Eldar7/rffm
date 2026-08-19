"""fichaequipo `team` JSON -> one team_club_map.csv row.

Separate from club_parsers.py (which reads the same page) since this
produces a different row shape - one row per team_id (team_club_map.csv),
not one row per club_id (clubs.csv) - see team_club_pipeline.py's module
docstring for why the two stages are separate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_team_club_mapping(team_json: dict[str, Any], team_id: str, source_url: str) -> dict | None:
    """Returns None if the page has no codigo_club (a genuine RFFM-side gap,
    not a parse error - see team_club_quality_checks.py)."""
    club_id = team_json.get("codigo_club")
    if not club_id:
        return None
    return dict(
        team_id=team_id,
        club_id=str(club_id),
        source="fichaequipo_direct",
        source_url=source_url,
        scraped_at=_now_iso(),
    )
