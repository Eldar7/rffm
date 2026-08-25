#!/usr/bin/env python3
"""
v2 PROOF-OF-CONCEPT: identical to team_rosters.py except build_team_rosters()
sources match_lineups/match_goals/match_cards/players from output/processed/
rffm_parquet/ via rffm_data.read_table() instead of pd.read_csv(). Reads
read_table("players_by_season", season=...), not the deduped
read_table("players") - v1 read this season's own players.csv, and
confirmed on real data that a player's recorded name spelling can genuinely
change between seasons (RFFM's own site started serving some players'
names without diacritics from 2024-2025 onward), so the deduped table's
"latest name wins" pick would show an old season's roster under a spelling
that didn't exist yet that season - this module is the sole source for
team_card.html's roster tab now (team_rosters.py's build is no longer
called from build_site.py), so there's no v1 fallback to mask this.
Imports player_career_v2 (not player_career) so the career-index
computation stays on the Parquet path too. list_seasons() is unchanged -
reads coverage_manifest.csv, which isn't part of the Parquet ETL.

Roster x matches participation matrix for the Team Card: for every match a
team played (already listed by team_cards.py), who dressed, who started vs.
came off the bench, who scored, who got carded — the acta_partido enrichment
(match_lineups/match_goals/match_cards, opt-in, category-scoped; see
DATA_DICTIONARY.md) joined down to one team at a time.

Deliberately a SEPARATE fetch from team_cards.py's per-club match-list JSON,
not merged into it, and split one-file-per-TEAM rather than one-file-per-
CLUB like team_cards.py:
  - a club's other teams' rosters are never needed when one team's matrix is
    open, so there's no reason to bundle them and force a bigger download;
  - the raw enrichment this is built from (match_lineups + match_goals +
    match_cards) runs 500+ MB for a single season even before any trimming
    — folding it into the already-shipped match-list file would multiply
    that file's size for every viewer, even ones who never open the matrix.
team_card.html fetches data/team_rosters_<season>/<team_id>.json lazily,
only when a team card's "Состав" tab is actually opened.

Usage:
    python analysis_scripts/team_rosters.py
    python analysis_scripts/team_rosters.py --season 2025-2026 --output-dir reports
"""

import argparse
import json
from pathlib import Path

import pandas as pd

import player_career_v2 as player_career
import rffm_data as data

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"


def list_seasons() -> list[str]:
    m = pd.read_csv(MANIFEST, dtype=str)
    core = m[(m["stage"] == "core") & (m["category_base"] == "ALL") &
             (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(core["season"].unique().tolist())


def clean(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def norm_id(v) -> str | None:
    """team_id in match_lineups/match_goals/match_cards carries a trailing
    ".0" for some category files and not others (ALEVIN/CADETE/INFANTIL/
    JUVENIL/AFICIONADO/SENIOR: always ".0"; BENJAMIN/PREBENJAMIN: never) —
    an upstream CSV-export quirk, not a real difference in the ID. Every
    other part of this project (team_cards.py, club_division_map.py) already
    strips it, so this must too or roster lookups by team_id silently miss
    for ~3 out of 4 teams."""
    s = clean(v)
    if s is None:
        return None
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


CARD_LABEL_ES = {"amarilla": "amarilla", "roja": "roja", "doble_amarilla": "doble amarilla"}


def build_team_rosters(season: str, career_lookup: dict[str, dict] | None = None) -> dict[str, dict]:
    players = data.read_table("players_by_season", season=season)
    pid_to_name = dict(zip(players["player_id"], players["player_name"]))
    career_lookup = career_lookup or {}

    categories = data.list_categories("match_lineups", season) if (BASE / season / "match_lineups").exists() else []

    # team_id -> {"lineups": {match_id: {player_id: {...}}}, "roster": {player_id: {...}}}
    rosters: dict[str, dict] = {}

    def team_entry(tid: str) -> dict:
        return rosters.setdefault(tid, {"lineups": {}, "roster": {}})

    for cat in categories:
        lu = data.read_table("match_lineups", season=season, category=cat)
        for row in lu.itertuples(index=False):
            tid, mid, pid = norm_id(row.team_id), row.match_id, row.player_id
            if not (tid and mid and pid):
                continue
            te = team_entry(tid)
            match_lineup = te["lineups"].setdefault(mid, {})
            match_lineup[pid] = {
                "start": row.is_starter == "True", "sub": row.is_substitute == "True",
                "cap": row.is_captain == "True", "gk": row.is_goalkeeper == "True",
                "jersey": clean(row.jersey_number), "goals": 0, "cards": [],
            }
            # "seasons": {x, y, u} — career-wide seasons-played/eligible from
            # player_career.py, embedded here (not fetched separately by
            # team_card.html) since this roster JSON is already the one
            # network round-trip the "Итоги по игрокам" tab needs.
            ros = te["roster"].setdefault(pid, {"name": pid_to_name.get(pid) or pid,
                                                 "gk": False, "jersey": None, "apps": 0,
                                                 "seasons": career_lookup.get(pid)})
            ros["apps"] += 1
            if row.is_goalkeeper == "True":
                ros["gk"] = True
            jersey = clean(row.jersey_number)
            if jersey:
                ros["jersey"] = jersey

        goals = data.read_table("match_goals", season=season, category=cat)
        if not goals.empty:
            for row in goals.itertuples(index=False):
                tid, mid, pid = norm_id(row.team_id), row.match_id, row.player_id
                if not (tid and mid and pid) or tid not in rosters:
                    continue
                entry = rosters[tid]["lineups"].get(mid, {}).get(pid)
                if entry is not None:
                    entry["goals"] += 1

        cards = data.read_table("match_cards", season=season, category=cat)
        if not cards.empty:
            for row in cards.itertuples(index=False):
                tid, mid, pid = norm_id(row.team_id), row.match_id, row.player_id
                if not (tid and mid and pid) or tid not in rosters:
                    continue
                entry = rosters[tid]["lineups"].get(mid, {}).get(pid)
                if entry is not None:
                    label = CARD_LABEL_ES.get(clean(row.card_type_label), clean(row.card_type_label))
                    if label:
                        entry["cards"].append(label)

    return rosters


def main():
    parser = argparse.ArgumentParser(description="RFFM team roster x matches participation matrix")
    parser.add_argument("--season", default=None, help="build only this season's data (default: every season with match_lineups data)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    # Every crawled season, by default — see team_cards.py's build_all() for
    # why (player_card.html's "show all seasons" view needs this for every
    # season a player was registered in, not just the latest). Heavier still
    # than team_cards.py's data (the raw acta_partido enrichment alone is
    # 500+ MB/season before any trimming); the per-season skip below already
    # limits this to seasons that actually have match_lineups/ crawled.
    seasons = seasons or list_seasons()

    # Career-wide seasons-played/eligible per player (player_career.py),
    # computed once up front from every fichajugador-covered season —
    # independent of `seasons` above, which may be a --season subset of just
    # one roster build — and reused for every season's roster JSON below,
    # since a player's X/Y doesn't depend on which season's team you're
    # viewing them from.
    print("Computing career seasons-played index...")
    career_all_seasons = player_career.list_fichajugador_seasons()
    career_index = player_career.compute_career_index(career_all_seasons)
    coverage = player_career.load_fichajugador_coverage()
    career_lookup = {
        pid: dict(zip(("x", "y", "u"), player_career.seasons_ratio(c["birth_year"], c["seasons"], career_all_seasons, coverage)))
        for pid, c in career_index.items()
    }

    for season in seasons:
        if not (BASE / season / "match_lineups").exists():
            print(f"Skipping team rosters for {season}: no match_lineups/ (acta_partido not crawled)")
            continue
        print(f"Building team rosters for season {season}")
        rosters = build_team_rosters(season, career_lookup)
        data_dir = out_dir / "data" / f"team_rosters_{season}"
        data_dir.mkdir(parents=True, exist_ok=True)
        for tid, payload in rosters.items():
            (data_dir / f"{tid}.json").write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                encoding="utf-8")
        print(f"  {len(rosters)} teams written to {data_dir}")


if __name__ == "__main__":
    main()
