#!/usr/bin/env python3
"""
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


CARD_LABEL_ES = {"amarilla": "amarilla", "roja": "roja", "doble_amarilla": "doble amarilla"}


def build_team_rosters(season: str) -> dict[str, dict]:
    d = BASE / season
    players = pd.read_csv(d / "players.csv", dtype=str)
    pid_to_name = dict(zip(players["player_id"], players["player_name"]))

    lineups_dir = d / "match_lineups"
    categories = sorted(p.stem for p in lineups_dir.glob("*.csv")) if lineups_dir.exists() else []

    # team_id -> {"lineups": {match_id: {player_id: {...}}}, "roster": {player_id: {...}}}
    rosters: dict[str, dict] = {}

    def team_entry(tid: str) -> dict:
        return rosters.setdefault(tid, {"lineups": {}, "roster": {}})

    for cat in categories:
        lf = lineups_dir / f"{cat}.csv"
        lu = pd.read_csv(lf, dtype=str)
        for row in lu.itertuples(index=False):
            tid, mid, pid = row.team_id, row.match_id, row.player_id
            if not (tid and mid and pid):
                continue
            te = team_entry(tid)
            match_lineup = te["lineups"].setdefault(mid, {})
            match_lineup[pid] = {
                "start": row.is_starter == "True", "sub": row.is_substitute == "True",
                "cap": row.is_captain == "True", "gk": row.is_goalkeeper == "True",
                "jersey": clean(row.jersey_number), "goals": 0, "cards": [],
            }
            ros = te["roster"].setdefault(pid, {"name": pid_to_name.get(pid) or pid,
                                                 "gk": False, "jersey": None, "apps": 0})
            ros["apps"] += 1
            if row.is_goalkeeper == "True":
                ros["gk"] = True
            jersey = clean(row.jersey_number)
            if jersey:
                ros["jersey"] = jersey

        gf = d / "match_goals" / f"{cat}.csv"
        if gf.exists():
            goals = pd.read_csv(gf, dtype=str)
            for row in goals.itertuples(index=False):
                tid, mid, pid = row.team_id, row.match_id, row.player_id
                if not (tid and mid and pid) or tid not in rosters:
                    continue
                entry = rosters[tid]["lineups"].get(mid, {}).get(pid)
                if entry is not None:
                    entry["goals"] += 1

        cf = d / "match_cards" / f"{cat}.csv"
        if cf.exists():
            cards = pd.read_csv(cf, dtype=str)
            for row in cards.itertuples(index=False):
                tid, mid, pid = row.team_id, row.match_id, row.player_id
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
    parser.add_argument("--season", default=None, help="build only this season's data (default: latest complete core crawl)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    # Same latest-season-only default as team_cards.py, for the same reason
    # (this is heavier still — the raw acta_partido enrichment alone is
    # 500+ MB/season before any trimming).
    seasons = seasons or [list_seasons()[-1]]
    for season in seasons:
        if not (BASE / season / "match_lineups").exists():
            print(f"Skipping team rosters for {season}: no match_lineups/ (acta_partido not crawled)")
            continue
        print(f"Building team rosters for season {season}")
        rosters = build_team_rosters(season)
        data_dir = out_dir / "data" / f"team_rosters_{season}"
        data_dir.mkdir(parents=True, exist_ok=True)
        for tid, payload in rosters.items():
            (data_dir / f"{tid}.json").write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                encoding="utf-8")
        print(f"  {len(rosters)} teams written to {data_dir}")


if __name__ == "__main__":
    main()
