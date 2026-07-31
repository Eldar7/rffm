"""Normalization helpers: accents/case, category matching, dates, team names."""
from __future__ import annotations

import re
import unicodedata


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_label(text: str) -> str:
    """Uppercase, accent-free, single-spaced, hyphen/space unified label.

    Used purely for matching (e.g. 'BENJAMÍN F-7' vs 'benjamin f7'); the
    original raw label is always preserved separately in the output.
    """
    text = strip_accents(text or "").upper()
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def match_category_base(raw_label: str, category_priority: list[str]) -> str | None:
    """Return the configured base category matching raw_label, or None.

    category_priority must list more specific categories before the ones
    they are substrings of (e.g. PREBENJAMIN before BENJAMIN), since
    'BENJAMIN' occurs inside 'PREBENJAMIN'.
    """
    normalized = normalize_label(raw_label)
    for base in category_priority:
        if normalize_label(base) in normalized:
            return base
    return None


_DATE_RE = re.compile(r"^(\d{2})[-/](\d{2})[-/](\d{4})$")


def parse_date_to_iso(raw: str | None) -> str | None:
    """Parse dd-mm-yyyy or dd/mm/yyyy into ISO yyyy-mm-dd. None if empty/unparseable."""
    if not raw:
        return None
    raw = raw.strip()
    m = _DATE_RE.match(raw)
    if not m:
        return None
    dd, mm, yyyy = m.groups()
    return f"{yyyy}-{mm}-{dd}"


_MATCHDAY_LABEL_RE = re.compile(r"^\s*(\d+)\s*(?:\((.*)\))?\s*$")


def parse_matchday_label(raw: str | None) -> tuple[int | None, str | None]:
    """'1 (11-10-2025)' -> (1, '1 (11-10-2025)'); returns (None, raw) if unparseable."""
    if raw is None:
        return None, None
    m = _MATCHDAY_LABEL_RE.match(raw)
    if not m:
        return None, raw
    return int(m.group(1)), raw


_SUFFIX_RE = re.compile(r"""['"]\s*([A-Za-z0-9]+)\s*['"]\s*$""")


def parse_team_name(raw_name: str) -> tuple[str, str | None]:
    """Split a raw team name into (club_name_raw, squad_suffix).

    RFFM encodes the squad letter in a trailing quoted token, e.g.
    "C.F. MADRID RIO 'A'" -> ("C.F. MADRID RIO", "A"). If no quoted
    suffix is present, squad_suffix is None and club_name_raw == raw_name.
    """
    if not raw_name:
        return raw_name, None
    m = _SUFFIX_RE.search(raw_name.strip())
    if not m:
        return raw_name.strip(), None
    suffix = m.group(1)
    club_name = raw_name[: m.start()].strip()
    return club_name, suffix


def to_int_or_none(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s == "":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def to_float_or_none(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


_PLAYOFF_PHASE_RE = re.compile(
    r"\b(\d+ª?\s*FASE|FASE\s*FINAL|SEGUNDA\s*FASE|TERCERA\s*FASE)\b"
)


def phase_label_from_competition_name(competition_name: str) -> str:
    """Classify a competition's raw name into a coarse phase label.

    RFFM models each season phase (regular season, 'T. CAMPEONES' playoff
    stages, 'SEGUNDA FASE' second-phase groups, ...) as its own competition
    id under the same category. We keep the full raw name too, this is
    just a normalized bucket for filtering/analytics.
    """
    normalized = normalize_label(competition_name)
    if "T. CAMPEONES" in normalized or "TORNEO CAMPEONES" in normalized or "CAMPEONES" in normalized:
        m = _PLAYOFF_PHASE_RE.search(normalized)
        sub = m.group(1) if m else ""
        return f"playoff {sub}".strip()
    m = _PLAYOFF_PHASE_RE.search(normalized)
    if m:
        return f"phase {m.group(1)}".lower()
    return "regular_season"
