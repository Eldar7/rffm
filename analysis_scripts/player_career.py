#!/usr/bin/env python3
"""
Shared building block for one derived stat: how many seasons has a player
actually played, out of how many they've been age-eligible for since their
first PREBENJAMIN season — "4/5" on a player who, per their birth year,
should have started in 2021-2022 but has a participation row only from
2022-2023 onward.

Used by two different pages that otherwise share nothing: player_card.html
(one player's own stat) and team_card.html's roster table (one column per
player on the team). Lives in its own module rather than inside
player_cards.py because team_rosters.py needs the exact same numbers without
importing a module whose own build_all() does unrelated, much heavier work
(building every season's player_participation_<season>/*.json shards) —
same one-file-per-concern convention as site_theme.py.
"""

from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

# RFEF ages are calendar-year based, not exact birthdate cutoffs, so mapping
# a season + birth year to a category is an approximation (mirrors
# DATA_DICTIONARY.md's "Category taxonomy" -> "Typical ages" table) good to
# within a season around a birthday-adjacent edge case — same caveat that
# source table already carries.
AGE_CATEGORY_BRACKETS: list[tuple[int, int, tuple[str, ...]]] = [
    (6, 7, ("PREBENJAMIN",)),
    (8, 9, ("BENJAMIN",)),
    (10, 11, ("ALEVIN",)),
    (12, 13, ("INFANTIL",)),
    (14, 15, ("CADETE",)),
    (16, 18, ("JUVENIL",)),
]
ADULT_CATEGORIES = ("AFICIONADO", "SENIOR")  # 19+, split unknown without more than a birth year
FIRST_ELIGIBLE_AGE = 6  # PREBENJAMIN's youngest bracket - where the denominator starts counting


def categories_for_age(age: int) -> tuple[str, ...]:
    for lo, hi, cats in AGE_CATEGORY_BRACKETS:
        if lo <= age <= hi:
            return cats
    if age >= 19:
        return ADULT_CATEGORIES
    return ()


def list_fichajugador_seasons() -> list[str]:
    m = pd.read_csv(MANIFEST, dtype=object)
    ok = m[(m["stage"] == "fichajugador") & (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(ok["season"].unique().tolist())


def load_fichajugador_coverage() -> dict[tuple[str, str], str]:
    m = pd.read_csv(MANIFEST, dtype=object)
    fj = m[m["stage"] == "fichajugador"]
    return {(row.season, row.category_base): row.status for row in fj.itertuples(index=False)}


def compute_career_index(seasons: list[str] | None = None) -> dict[str, dict]:
    """player_id -> {"birth_year": str|None, "seasons": set[str]} across
    every season with fichajugador coverage. Reads just player_id +
    birth_year (not the full participation row that player_cards.py needs
    for its own per-row team/competition columns), so this stays cheap
    enough to call independently from more than one build script rather than
    threading a shared result through build_site.py's separately-invoked
    build_all()s."""
    seasons = seasons or list_fichajugador_seasons()
    career: dict[str, dict] = {}
    for season in seasons:
        d = BASE / season
        part_path = d / "player_competition_participation.csv"
        players_path = d / "players.csv"
        if not (part_path.exists() and players_path.exists()):
            continue
        part = pd.read_csv(part_path, dtype=object, usecols=["player_id"])
        players = pd.read_csv(players_path, dtype=object, usecols=["player_id", "birth_year"])
        pid_to_birth = dict(zip(players["player_id"], players["birth_year"]))
        for pid in part["player_id"].dropna().unique():
            c = career.setdefault(pid, {"birth_year": None, "seasons": set()})
            c["seasons"].add(season)
            if not c["birth_year"]:
                by = pid_to_birth.get(pid)
                if by and str(by).strip():
                    c["birth_year"] = str(by).strip()
    return career


def seasons_ratio(birth_year: str | None, seasons_played: set[str], all_seasons: list[str],
                   coverage: dict[tuple[str, str], str]) -> tuple[int, int | None, bool]:
    """(x, y, uncertain): y = seasons the player has been age-eligible for
    since their first PREBENJAMIN season, capped to this project's data
    window (None if birth_year is missing/unusable, since y can't be
    computed at all then); x = of those, how many they actually have a
    participation row for (a stray pre-PREBENJAMIN/DEBUTANTE-age row before
    the window doesn't inflate x past y — "4/4", never a nonsensical "5/4");
    uncertain = True if any season in that window wasn't fully crawled for
    fichajugador in the player's age-appropriate category, so a "missed"
    season there may just be missing data, not an actual gap."""
    x_all = len(seasons_played)
    if not birth_year or not str(birth_year).isdigit():
        return x_all, None, False
    by = int(birth_year)
    all_years = sorted(int(s.split("-")[0]) for s in all_seasons)
    if not all_years:
        return x_all, None, False
    floor_year, latest_year = all_years[0], all_years[-1]
    start_year = max(by + FIRST_ELIGIBLE_AGE, floor_year)
    if start_year > latest_year:
        return 0, 0, False
    y = latest_year - start_year + 1
    x = sum(1 for s in seasons_played if int(s.split("-")[0]) >= start_year)
    uncertain = False
    for yr in range(start_year, latest_year + 1):
        season_label = f"{yr}-{yr + 1}"
        cats = categories_for_age(yr - by)
        if not cats:
            continue
        if not any(coverage.get((season_label, cat)) == "complete" for cat in cats):
            uncertain = True
            break
    return x, y, uncertain
