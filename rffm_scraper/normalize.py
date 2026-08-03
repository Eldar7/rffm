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


# Age-group vocabulary for crawl_all_categories mode, where there's no
# config-driven category_priority to match against (see match_category_base
# above, used instead in the normal 2-category scope). Ordered most-specific
# first, same substring-containment reasoning: PREBENJAMIN before BENJAMIN,
# etc. (token, canonical category_base value) - the token is what's searched
# for in the normalized label; the canonical value is what gets stored, which
# only differs from the token for the two Spanish grammatical-gender stems
# (UNIVERSITARI matches both UNIVERSITARIO/UNIVERSITARIA). Derived from the
# 93 categories observed in the RFFM's 2025-2026 season - see
# DATA_DICTIONARY.md's "Category taxonomy" section for the full derivation
# and known edge cases (e.g. adult federation leagues with no explicit age
# word, which correctly fall through to OTHER below rather than being
# guessed at).
AGE_CATEGORY_VOCABULARY: list[tuple[str, str]] = [
    ("PREBENJAMIN", "PREBENJAMIN"),
    ("BENJAMIN", "BENJAMIN"),
    ("ALEV", "ALEVIN"),  # stem, not "ALEVIN" - RFFM abbreviates as "ALEV-F7"/"ALEV.F-7" in some labels
    ("INFANTIL", "INFANTIL"),
    ("CADETE", "CADETE"),
    ("JUVENIL", "JUVENIL"),
    ("VETERANOS", "VETERANOS"),
    ("UNIVERSITARI", "UNIVERSITARIO"),
    ("AFICIONADO", "AFICIONADO"),
    ("SENIOR", "SENIOR"),
]

# Same idea, for the division/level facet - also ordered most-specific
# first (e.g. "PRIMERA DIVISION AUTONOMICA" before plain "PRIMERA", which it
# would otherwise match as a substring). See DATA_DICTIONARY.md - this facet
# is the messiest of the four (age/format/gender/division) since RFFM's
# naming isn't fully orthogonal; unmatched labels fall through to OTHER
# rather than being force-fit into the nearest-looking bucket.
DIVISION_LEVEL_VOCABULARY: list[tuple[str, str]] = [
    ("PRIMERA DIVISION AUTONOMICA", "PRIMERA DIVISION AUTONOMICA"),
    ("DIVISION DE HONOR", "DIVISION DE HONOR"),
    ("PREFERENTE", "PREFERENTE"),
    ("SEGUNDA DIVISION B", "SEGUNDA DIVISION B"),
    ("TERCERA FEDERACION", "TERCERA FEDERACION"),
    ("PRIMERA", "PRIMERA"),
    ("SEGUNDA", "SEGUNDA"),
    ("TERCERA", "TERCERA"),
    ("SUPERLIGA", "SUPERLIGA"),
    ("LIGA NACIONAL", "LIGA NACIONAL"),
    ("FASE ZONAL", "FASE ZONAL"),
    ("CAMPEONATO UNIVERSITARI", "CAMPEONATO UNIVERSITARIO"),
    ("LIGA UNIVERSITARI", "LIGA UNIVERSITARIA"),
]


def classify_age_category(raw_label: str, fallback_label: str = "") -> str:
    """crawl_all_categories counterpart to match_category_base: classify
    against the fixed AGE_CATEGORY_VOCABULARY above instead of a
    config-supplied list. Returns 'OTHER' rather than None for no match,
    since there's no caller-side "not in scope, skip it" filtering step to
    feed None into here (every competition is kept in all-categories mode).

    fallback_label is tried only when raw_label produces no match — pass the
    competition nombre here, since FASE ZONAL labels embed the age group in
    the competition name ("FASE ZONAL 3 benjamin VALDEMORO FS") but not in
    NombreCategoria ("FASE ZONAL SALA")."""
    normalized = normalize_label(raw_label)
    for token, canonical in AGE_CATEGORY_VOCABULARY:
        if token in normalized:
            return canonical
    if fallback_label:
        normalized_fallback = normalize_label(fallback_label)
        for token, canonical in AGE_CATEGORY_VOCABULARY:
            if token in normalized_fallback:
                return canonical
    return "OTHER"


def classify_division_level(raw_label: str, fallback_label: str = "") -> str:
    """Best-effort division/level facet - see DIVISION_LEVEL_VOCABULARY.

    fallback_label is tried only when raw_label produces no match — pass the
    competition nombre here (same pattern as classify_age_category)."""
    normalized = normalize_label(raw_label)
    for token, canonical in DIVISION_LEVEL_VOCABULARY:
        if token in normalized:
            return canonical
    if fallback_label:
        normalized_fallback = normalize_label(fallback_label)
        for token, canonical in DIVISION_LEVEL_VOCABULARY:
            if token in normalized_fallback:
                return canonical
    return "OTHER"


def is_femenino_label(raw_label: str) -> bool:
    """Whether raw_label carries an explicit women's-category marker.

    RFFM does not consistently mark the converse (see DATA_DICTIONARY.md) -
    a False here means "no explicit marker found", not "confirmed men's/
    mixed competition".
    """
    return "FEMENIN" in normalize_label(raw_label)


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


def to_bool_or_none(value) -> bool | None:
    """Coerce RFFM's '1'/'0' (occasionally 'true'/'false') string flags to bool."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    if s in ("1", "true", "True", "TRUE"):
        return True
    if s in ("0", "false", "False", "FALSE"):
        return False
    return None


def team_id_or_none(raw_id: str | None) -> str | None:
    """RFFM uses '' or '-1' as sentinels for a bye/unassigned/unknown team."""
    if raw_id in (None, "", "-1"):
        return None
    return raw_id


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
