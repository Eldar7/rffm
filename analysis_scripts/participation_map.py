#!/usr/bin/env python3
"""
Per-player, per-match participation facts for the "Карта участия" tab on
player_card.html: for every match a player actually appears in
match_lineups (acta_partido enrichment, opt-in/category-scoped — see
DATA_DICTIONARY.md), the match date, team, competition/division/category,
goals/cards, opponent/score, and the team's final placement in that group.

Deliberately raw, not interpreted: this module does not compute the map's
vertical axis (age-relative `level`, division tier, or the two unranked
zones for AFICIONADO/SENIOR and category_base=OTHER) — that depends on
which seasons are shown together for a given player, so it's computed
client-side in player_card.html from birth_year + season_id + category_base,
the same "server ships facts, client interprets" split player_cards.py and
team_rosters.py already use for their own data.

Sharded by player_id % SHARD_MOD (same modulus as player_cards.py, so the
same client-side shard_of() works for both), one file per (season, shard):
data/participation_map_<season>/<shard>.json.

Grouped into "stints" — one entry per (team, competition) pairing, with
team/competition/division/etc. stored once and a compact per-match list
nested inside — rather than one flat row per match repeating those fields.
A flat-row shape here pushed a single season past 1GB and the whole site
past GitHub Pages' 10GB artifact limit; player_cards.py's pmExpandStints()
unpacks this back into flat per-match rows client-side before rendering.

Usage:
    python analysis_scripts/participation_map.py
    python analysis_scripts/participation_map.py --season 2024-2025 --output-dir reports
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from team_rosters import norm_id

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

SHARD_MOD = 100


def list_core_seasons() -> list[str]:
    """Every season with core data, regardless of acta_partido coverage —
    a season the player was active in but with no protocols still needs to
    appear on the map's season axis (as a placeholder), not vanish."""
    m = pd.read_csv(MANIFEST, dtype=object)
    core = m[(m["stage"] == "core") & (m["category_base"] == "ALL") &
             (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(core["season"].unique().tolist())


def list_acta_seasons() -> list[str]:
    """Seasons that actually have match_lineups/ to read (a season can be
    in list_core_seasons() without this — see 2016-2017)."""
    return sorted(s.name for s in BASE.iterdir()
                  if s.is_dir() and (s / "match_lineups").exists())


def shard_of(player_id: str) -> int:
    return int(player_id) % SHARD_MOD


def clean(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def clean_int(v) -> int | None:
    """matchday/home_score/away_score/position carry a trailing '.0' quirk
    when the column has any null in it (see DATA_DICTIONARY.md) — bare
    int(x) raises on that, so go through float() first."""
    v = clean(v)
    if v is None:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def build_season_shards(season: str) -> dict[int, dict[str, dict]]:
    d = BASE / season
    lineups_dir = d / "match_lineups"
    if not lineups_dir.exists():
        return {}

    players = pd.read_csv(d / "players.csv", dtype=object)
    pid_to_birth = dict(zip(players["player_id"], players["birth_year"]))
    pid_to_name = dict(zip(players["player_id"], players["player_name"]))

    teams = pd.read_csv(d / "teams.csv", dtype=object)
    tid_to_team = {norm_id(row.team_id): {"team": clean(row.team), "club": clean(row.club_name_raw)}
                   for row in teams.itertuples(index=False)}

    standings = pd.read_csv(d / "standings.csv", dtype=object)
    group_sizes = standings.groupby("group_id")["team_id"].count().to_dict()
    pos_by_group_team = {(clean(row.group_id), norm_id(row.team_id)): clean_int(row.position)
                          for row in standings.itertuples(index=False)}

    competitions = pd.read_csv(d / "competitions.csv", dtype=object)
    comp_by_id = {row.competition_id: row for row in competitions.itertuples(index=False)}

    matches = pd.read_csv(d / "matches.csv", dtype=object)
    match_by_id: dict[str, dict] = {}
    for row in matches.itertuples(index=False):
        match_by_id[row.match_id] = {
            "date": clean(row.match_date),
            "round": clean_int(row.matchday),
            "home_tid": norm_id(row.home_team_id),
            "away_tid": norm_id(row.away_team_id),
            "home_team": clean(row.home_team),
            "away_team": clean(row.away_team),
            "home_score": clean_int(row.home_score),
            "away_score": clean_int(row.away_score),
            "group": clean(row.group),
            "group_id": clean(row.group_id),
            "competition_id": clean(row.competition_id),
            "category": clean(row.category),
            "game_type": clean(row.game_type),
            "game_type_id": clean(row.game_type_id),
        }

    # (competition_id, team_id) -> count of that team's *finished* matches in
    # that competition — the denominator the map's tooltip needs to show
    # "апps out of team's total matches" (participation_map's per-player rows
    # only ever cover matches this one player appears in, so the team's full
    # count has to come from matches.csv directly, not be derived from them).
    team_matches_total: dict[tuple[str, str], int] = {}
    for row in matches.itertuples(index=False):
        if row.is_finished != "True":
            continue
        cid = clean(row.competition_id)
        for tid in (norm_id(row.home_team_id), norm_id(row.away_team_id)):
            if tid:
                key = (cid, tid)
                team_matches_total[key] = team_matches_total.get(key, 0) + 1

    categories = sorted(p.stem for p in lineups_dir.glob("*.csv"))
    shards: dict[int, dict[str, dict]] = {}

    for cat in categories:
        lu = pd.read_csv(lineups_dir / f"{cat}.csv", dtype=object)

        goals_count: dict[tuple[str, str], int] = {}
        gf = d / "match_goals" / f"{cat}.csv"
        if gf.exists():
            for row in pd.read_csv(gf, dtype=object).itertuples(index=False):
                key = (row.match_id, row.player_id)
                goals_count[key] = goals_count.get(key, 0) + 1

        cards_map: dict[tuple[str, str], list[str]] = {}
        cf = d / "match_cards" / f"{cat}.csv"
        if cf.exists():
            for row in pd.read_csv(cf, dtype=object).itertuples(index=False):
                label = clean(getattr(row, "card_type_label", None))
                if label:
                    key = (row.match_id, row.player_id)
                    cards_map.setdefault(key, []).append(label)

        for row in lu.itertuples(index=False):
            pid, mid = row.player_id, row.match_id
            if not (pid and mid):
                continue
            m = match_by_id.get(mid)
            if m is None:
                continue
            tid = norm_id(row.team_id)
            is_home = tid == m["home_tid"]
            comp = comp_by_id.get(m["competition_id"])
            team_info = tid_to_team.get(tid, {})
            pos = pos_by_group_team.get((m["group_id"], tid))
            grp_size = group_sizes.get(m["group_id"])

            shard = shards.setdefault(shard_of(pid), {})
            player = shard.setdefault(pid, {
                "name": pid_to_name.get(pid) or pid,
                "birth_year": clean_int(pid_to_birth.get(pid)),
                "stints": {},  # (tid, comp_id) -> stint dict, flattened to a list before writing
            })
            # A "stint" = one (team, competition) pairing for this player —
            # team/competition/division/etc. only ever change between
            # stints, never match-to-match within one, so they're stored
            # once per stint instead of once per match (participation_map's
            # payload was ~30 fields/match with most of them byte-identical
            # across every match of a stint, which alone pushed a single
            # season's shards past several GB — see the conversation this
            # was diagnosed in). Only genuinely per-match facts go in
            # "matches".
            stint_key = f"{tid}|{m['competition_id']}"
            stint = player["stints"].get(stint_key)
            if stint is None:
                stint = {
                    "tid": tid,
                    "team": team_info.get("team"),
                    "club": team_info.get("club"),
                    "comp_id": m["competition_id"],
                    "comp": clean(comp.competition) if comp is not None else None,
                    "phase": clean(comp.phase_label) if comp is not None else None,
                    "grp": m["group"],
                    "group_id": m["group_id"],
                    "cat": (clean(comp.category_base) if comp is not None else None) or m["category"] or "OTHER",
                    "div": (clean(comp.division_level) if comp is not None else None) or "OTHER",
                    "gt": (clean(comp.game_type) if comp is not None else None) or m["game_type"],
                    "gt_id": (clean(comp.game_type_id) if comp is not None else None) or m["game_type_id"],
                    "pos": pos,
                    "grp_size": grp_size,
                    "tm": team_matches_total.get((m["competition_id"], tid), 0),
                    "matches": [],
                }
                player["stints"][stint_key] = stint
            stint["matches"].append({
                "mid": mid,
                "date": m["date"],
                "round": m["round"],
                "start": row.is_starter == "True",
                "sub": row.is_substitute == "True",
                "cap": row.is_captain == "True",
                "gk": row.is_goalkeeper == "True",
                "goals": goals_count.get((mid, pid), 0),
                "cards": cards_map.get((mid, pid), []),
                "home": is_home,
                "opp": m["away_team"] if is_home else m["home_team"],
                "gf": m["home_score"] if is_home else m["away_score"],
                "ga": m["away_score"] if is_home else m["home_score"],
            })

    for shard in shards.values():
        for player in shard.values():
            player["stints"] = list(player["stints"].values())

    return shards


def main():
    parser = argparse.ArgumentParser(description="RFFM player participation-map data")
    parser.add_argument("--season", default=None, help="build only this season's data (default: every season with match_lineups)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    seasons = seasons or list_acta_seasons()
    for season in seasons:
        if not (BASE / season / "match_lineups").exists():
            print(f"Skipping participation map for {season}: no match_lineups/ (acta_partido not crawled)")
            continue
        print(f"Building participation map for season {season}")
        shards = build_season_shards(season)
        data_dir = out_dir / "data" / f"participation_map_{season}"
        data_dir.mkdir(parents=True, exist_ok=True)
        for shard_id, payload in shards.items():
            (data_dir / f"{shard_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                encoding="utf-8")
        print(f"  {sum(len(p) for p in shards.values())} players across {len(shards)} shards written to {data_dir}")


if __name__ == "__main__":
    main()
