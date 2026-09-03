#!/usr/bin/env python3
"""
Canonical club identity, shared by every report generator that needs to
group teams/rows into "the same club" across seasons.

The ONLY real club identifier in this project is `club_id`, from
`team_club_map.csv` (built by `enrich_team_clubs.py` /
`rffm_scraper/team_club_pipeline.py`): it is `codigo_club`, a field RFFM's
own `/fichaequipo/<team_id>` page returns for that team - ground truth from
the site's own data model, not text matched against anything. That
pipeline's docstring is explicit: "no fuzzy name-matching involved
anywhere" - its one seeding shortcut (exact byte-for-byte `club_name_raw`
match to an already-resolved team_id) only ever skips a redundant fetch
when two rows are already guaranteed to share a club_id, never used to
decide identity under ambiguity.

This replaces the ad hoc "group teams.csv rows by club_name_raw" heuristic
that club_profile_data_v2.py (`club_key()`), club_division_map.py /
club_division_map_v2.py, team_cards.py / team_cards_v2.py, and
player_cards.py each reimplemented independently. That heuristic is real
technical debt, not a style choice: club_name_raw drifts between teams of
the same club and across a club's own sponsor/name changes over time (see
team_club_pipeline.py's module docstring for a confirmed live example), so
grouping by it silently splits one real club into several, or - much
rarer but confirmed in this data (5 pairs, see club_slugs() below) -
silently merges two different real clubs that happen to share identical
registered name text.

A team_id absent from team_club_map.csv is NOT an unresolved-but-real club
waiting to be guessed at - team_club_gap_reasons.csv documents why each one
is missing (technical no-show, FASE ZONAL, a non-federated local cup, ...),
and the honest answer for those rows is "this team isn't tied to a stable
club", not a name-matched substitute. `resolve()` returns None for them;
callers must show that plainly (e.g. "неизвестный клуб (team <id>)") and
must never merge two such rows just because their raw names match.

Usage:
    import club_identity as ci
    club_id = ci.resolve(team_id)                  # None if genuinely unresolved
    name = ci.club_display_names().get(club_id)
    slug = ci.club_slugs().get(club_id)
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd

from site_theme import club_slug_map

PARQUET_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm_parquet"


@lru_cache(maxsize=1)
def team_to_club() -> dict[str, int]:
    """team_id -> club_id, the complete team_club_map.csv. team_id kept as
    str (matches every other table's join-key convention in this project -
    see rffm_data.py's _stringify / norm_id() callers)."""
    df = pd.read_parquet(PARQUET_DIR / "team_club_map.parquet")
    return dict(zip(df["team_id"].astype(str), df["club_id"].astype(int)))


def resolve(team_id: str | int | None) -> int | None:
    """team_id -> club_id, or None if this team_id has no real club_id
    (see module docstring - a genuine gap, not a matching failure)."""
    if team_id is None:
        return None
    return team_to_club().get(str(team_id))


@lru_cache(maxsize=1)
def club_display_names() -> dict[int, str]:
    """club_id -> its most recently scraped club_name_raw (clubs.csv is a
    per-season table, not a snapshot log, but a club can still be re-scraped
    across seasons with an updated name - take the latest season, then the
    latest scraped_at within it, same "current state" recipe DATA_DICTIONARY.md
    documents for clubs_extended.csv).

    clubs.csv (enrich_clubs.py, one-representative-team sampling per
    club_name_raw) has a smaller club_id universe than team_club_map.csv
    (enrich_team_clubs.py's whole reason to exist - see that pipeline's
    module docstring) - confirmed live, 7 of 1,061 team_club_map club_ids
    have no clubs.csv row at all. Fall back to teams.csv's club_name_raw
    (the most common raw spelling among that club_id's own team_ids, via
    team_to_club()) for those - still real text tied to this exact club_id
    through the same authoritative team_id join, not a name-matching guess
    across different club_ids."""
    frames = [pd.read_parquet(p) for p in sorted((PARQUET_DIR / "clubs").glob("*.parquet"))]
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["season", "scraped_at"]).drop_duplicates("club_id", keep="last")
    names = dict(zip(df["club_id"].astype(int), df["club_name_raw"]))

    missing = set(team_to_club().values()) - set(names)
    if missing:
        t2c = team_to_club()
        team_frames = [pd.read_parquet(p) for p in sorted((PARQUET_DIR / "teams").glob("*.parquet"))]
        teams = pd.concat(team_frames, ignore_index=True)[["team_id", "club_name_raw"]].drop_duplicates()
        teams["club_id"] = teams["team_id"].astype(str).map(t2c)
        teams = teams[teams["club_id"].isin(missing)]
        fallback = teams.groupby("club_id")["club_name_raw"].agg(lambda s: s.value_counts().idxmax())
        names.update(fallback.to_dict())
    return names


@lru_cache(maxsize=1)
def club_slugs() -> dict[int, str]:
    """club_id -> URL-safe slug, via site_theme.club_slug_map() - but keyed
    by club_id, not by name text. club_slug_map() disambiguates COLLIDING
    base slugs by suffixing the colliding NAME strings - if two different
    club_ids happen to share byte-identical club_name_raw (confirmed live:
    5 such pairs, e.g. two distinct clubs both registered as "GREDOS SAN
    DIEGO"), feeding it the raw name list would silently fold both club_ids
    onto the exact same slug/page. Disambiguate by club_id BEFORE calling
    club_slug_map() for exactly those collisions, so every club_id still
    gets its own distinct, still-readable slug."""
    names = club_display_names()
    by_name: dict[str, list[int]] = {}
    for cid, name in names.items():
        by_name.setdefault(name, []).append(cid)

    slug_input: dict[int, str] = {
        cid: name if len(by_name[name]) == 1 else f"{name} {cid}"
        for cid, name in names.items()
    }
    slug_of_text = club_slug_map(list(slug_input.values()))
    return {cid: slug_of_text[text] for cid, text in slug_input.items()}


@lru_cache(maxsize=1)
def club_name_variants() -> dict[int, list[str]]:
    """club_id -> every distinct raw club_name_raw spelling seen for it,
    across every source table that carries one (teams.csv - one row per
    team_id, so this is where a sponsor-suffixed spelling like "ARAVACA
    C.F. - CEIBA" actually lives - plus clubs.csv and
    player_competition_participation.csv for completeness). Not for
    display (use club_display_names() - one stable current name per
    club_id) - this is for matching an *incoming* raw name string against
    the right club_id, e.g. a cross-link from a report that hasn't been
    migrated off its own name-based grouping yet and passes whatever
    sponsor-era name ITS data happened to carry."""
    t2c = team_to_club()
    variants: dict[int, set[str]] = {}

    def _add(club_id: int, name) -> None:
        if club_id is None or not isinstance(name, str) or not name:
            return
        variants.setdefault(club_id, set()).add(name)

    teams = pd.concat(
        [pd.read_parquet(p, columns=["team_id", "club_name_raw"]) for p in sorted((PARQUET_DIR / "teams").glob("*.parquet"))],
        ignore_index=True,
    ).drop_duplicates()
    for r in teams.itertuples(index=False):
        _add(t2c.get(str(r.team_id)), r.club_name_raw)

    clubs = pd.concat(
        [pd.read_parquet(p, columns=["club_id", "club_name_raw"]) for p in sorted((PARQUET_DIR / "clubs").glob("*.parquet"))],
        ignore_index=True,
    ).drop_duplicates()
    for r in clubs.itertuples(index=False):
        _add(int(r.club_id), r.club_name_raw)

    return {cid: sorted(names) for cid, names in variants.items()}


def clear_caches() -> None:
    """For tests / re-running build steps in-process against fresh Parquet
    without restarting the interpreter."""
    team_to_club.cache_clear()
    club_display_names.cache_clear()
    club_slugs.cache_clear()
    club_name_variants.cache_clear()
