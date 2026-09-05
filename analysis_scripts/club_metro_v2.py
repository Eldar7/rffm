#!/usr/bin/env python3
"""
Per-club "Metro de la Cantera" data: an alluvial/Sankey-style map of how a
club's youth players move between its own lettered teams and divisions
across every season with match_lineups (acta_partido) enrichment, pivoted
on birth year rather than nominal category.

Ported from the pilot built for Aravaca C.F. in notebooks/aravaca_metro/
(build_metro_v3.py -> build_links_v3.py -> finalize_metro_v3.py) — see that
directory's README.md for the full rationale behind the birth-year pivot:
an earlier category-per-season design needed a recursive "does this player
still belong to the club under some other category" lookup to catch kids
aging at a different pace than the season's nominal category, and that
recursion is what caused station-id collisions, misleading "bridge
stations" (a discovered other-category team with a tiny or unrelated-
looking roster), and — worst — a "snowball" that converged after ~9 rounds
to ~130 stations spanning the entire club. Pivoting on birth year needs no
recursion at all: "every appearance for this club, any team, any category,
for players born in year X" is a direct query, so there is nothing to
snowball and every player shown belongs to the cohort by definition.

Generalized here to every club (not just Aravaca), three ways:
  - club_id (club_identity.py / team_club_map.csv) instead of a hardcoded
    club_name_raw tuple. build_metro_v3.py matched Aravaca's own three
    raw-name spellings by hand (ARAVACA C.F. / "- Bhhs Spain" / "- CEIBA")
    — exactly the club_name_raw drift team_participation_map_v2.py's module
    docstring already documents (same club_id 1011, three eras of raw
    name) and already has a real fix for. Using ci.resolve(team_id) instead
    means a club's next sponsor-name change doesn't silently drop it.
  - Every season's match_lineups/match_goals/team metadata is scanned ONCE
    (all clubs, all categories) and grouped by club_id in memory, rather
    than one DuckDB scan per club — 685 clubs x a handful of full-Parquet
    reads per season each would otherwise dominate the build.
  - No hardcoded pivot birth-year pair: every birth year with >=MIN_APPS
    appearances for a club in some season becomes one entry of the output's
    `pivot_birth_years`. metro.html already builds its pivot buttons from
    that array at render time, so an arbitrary-length list needs no
    front-end change — it just stops being truncated to a fixed pair here.

Also drops the old team_slug_map_v3.json indirection (a slow one-time
replay of team_cards_v2's own internals to resolve each (season, team_id)'s
club slug): every station in one output file belongs to the SAME club by
construction, so its club_slug is just this club's own slug.

Skips clubs with too little cross-season signal to make a readable diagram
(MIN_SEASONS_PRESENT / MIN_STATIONS below) — most clubs only ever get a
season or two of acta_partido coverage, or too few pivot-birth-year
players, and would render as a near-empty page.

Usage:
    python analysis_scripts/club_metro_v2.py
    python analysis_scripts/club_metro_v2.py --output-dir reports --limit-clubs 5
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd

import club_identity as ci

PARQUET = Path(__file__).parent.parent / "output" / "processed" / "rffm_parquet"

CATEGORY_ORDER = ["PREBENJAMIN", "BENJAMIN", "ALEVIN", "INFANTIL", "CADETE", "JUVENIL"]
CAT_ORDINAL = {c: i for i, c in enumerate(CATEGORY_ORDER)}

# Unlike the Aravaca pilot (which pinned two specific birth years and let
# AFICIONADO show up as an occasional "graduated to the first team" rung for
# THOSE exact players), this generalizes to every birth year present for a
# club with no restriction of its own — so nothing here bounds a birth year
# to its expected age. Without a category filter that combination pulls in
# a club's ENTIRE adult squad (AFICIONADO/SENIOR spans literally any adult
# age), for every club, which is a different and much bigger population
# than "one youth cohort's journey" and drowns it out (confirmed on real
# data: Aravaca alone went from the pilot's 32 stations/251 links to 252/2800
# once AFICIONADO was in scope). Scoping to youth categories only keeps every
# club's page to what it's actually for; "did this cohort make the first
# team" is a real, different question already covered by club_scorecard.html
# ("Кантера" - alumni reaching elite, retention by generation).
YOUTH_CATEGORIES = tuple(CATEGORY_ORDER)

# Same tier vocabulary as notebooks/aravaca_metro/build_metro_v3.py, kept as
# its own dict rather than reusing club_division_map.TIER_OF: that one maps
# an unranked/zonal division to None (fine for its own table-cell use), not
# a fallback rank usable to sort stations into rows here.
TIER = {
    "SUPERLIGA": 1, "LIGA NACIONAL": 1, "DIVISION DE HONOR": 2, "PRIMERA DIVISION AUTONOMICA": 3,
    "PREFERENTE": 4, "SEGUNDA DIVISION B": 5, "TERCERA FEDERACION": 5, "PRIMERA": 6, "SEGUNDA": 7,
    "TERCERA": 8, "FASE ZONAL": 9, "OTHER": 9,
}

MIN_APPS = 4              # apps/birth-year threshold before a player "counts" for a team-season
MIN_SEASONS_PRESENT = 2   # a club needs at least this many seasons of stations to get a page
MIN_STATIONS = 4          # ...and at least this many stations total

# Entry points: one full metro diagram per plausible starting season, not
# one diagram covering a club's entire history. build_metro_v3.py's own
# design pinned exactly one cohort (Aravaca's 2014/2015 birth years,
# PREBENJAMÍN in 2021-2022) across a fixed 5-season window - generalizing
# "no restriction" to every club (no fixed cohort, all 9 available seasons)
# was tried first and confirmed unusable on real data: Aravaca alone went
# from 32 stations/2 birth years to 230 stations/22 birth years, because a
# club with a long history fields a different cohort in every category,
# every season, and nothing bounded which of them belong "in the same
# story" together. Each entry point instead auto-derives its own cohort
# exactly the way the pilot's was chosen by hand: the birth year(s) of
# whichever category is YOUNGEST among this club's stations in that
# starting season (usually PREBENJAMIN, but not assumed - some clubs never
# field it), then follows only those birth years for WINDOW_LEN seasons.
WINDOW_LEN = 5


def list_lineup_seasons() -> list[str]:
    return sorted(p.stem for p in (PARQUET / "match_lineups").glob("*.parquet"))


def pd_isna(x) -> bool:
    return bool(pd.isna(x))


def letter_of(team_name: str) -> str:
    parts = (team_name or "").strip().split()
    return parts[-1] if parts else "?"


def best_split(seq: list, min_apps: int = MIN_APPS) -> dict | None:
    """Detects a genuine intra-season transfer: an early run of one team_id
    followed by a late run of another, allowing a bounded error rate for
    stray call-ups. Ported verbatim from build_metro_v3.py."""
    n = len(seq)
    if len(set(seq)) < 2:
        return None
    early_team = seq[0]
    c = Counter(seq)
    late_candidates = [t for t in c if t != early_team]
    late_team = max(late_candidates, key=lambda t: c[t])
    best = None
    for k in range(1, n):
        left, right = seq[:k], seq[k:]
        if len(left) < min_apps or len(right) < min_apps:
            continue
        errors = sum(1 for x in left if x != early_team) + sum(1 for x in right if x != late_team)
        rate = errors / n
        if best is None or rate < best[0]:
            best = (rate, k)
    if best is None:
        return None
    rate, k = best
    return {"early": int(early_team), "late": int(late_team), "rate": rate, "split_idx": k,
            "n_early": c[early_team], "n_late": c[late_team]}


def load_season(con: duckdb.DuckDBPyConnection, season: str):
    """One season, every club at once: lineup rows, goal rows (both with a
    resolved club_id column), and per-(club_id, team_id) team metadata
    (best/lowest tier if a team shows up under more than one competition -
    e.g. league + cup - same as build_metro_v3.py's get_team_meta_bulk)."""
    lineups = con.execute(f'''
        SELECT ml.player_id, ml.team_id, m.match_date, ml.is_captain, ml.is_goalkeeper,
               p.player_name, p.birth_year
        FROM read_parquet('{PARQUET}/match_lineups/{season}.parquet') ml
        JOIN read_parquet('{PARQUET}/matches/{season}.parquet') m ON ml.match_id = m.match_id
        LEFT JOIN read_parquet('{PARQUET}/players.parquet') p ON ml.player_id = p.player_id
    ''').df()
    lineups["player_id"] = lineups["player_id"].astype(int)
    lineups["team_id"] = lineups["team_id"].astype(int)
    lineups["match_date"] = lineups["match_date"].astype(str)
    lineups["is_captain"] = lineups["is_captain"].astype(str) == "True"
    lineups["is_goalkeeper"] = lineups["is_goalkeeper"].astype(str) == "True"
    lineups["club_id"] = lineups["team_id"].map(lambda t: ci.resolve(t))
    lineups = lineups[lineups["club_id"].notna()].copy()
    lineups["club_id"] = lineups["club_id"].astype(int)

    goals = con.execute(f'''
        SELECT mg.player_id, mg.team_id, m.match_date
        FROM read_parquet('{PARQUET}/match_goals/{season}.parquet') mg
        JOIN read_parquet('{PARQUET}/matches/{season}.parquet') m ON mg.match_id = m.match_id
    ''').df()
    goals["player_id"] = goals["player_id"].astype(int)
    goals["team_id"] = goals["team_id"].astype(int)
    goals["match_date"] = goals["match_date"].astype(str)
    goals["club_id"] = goals["team_id"].map(lambda t: ci.resolve(t))
    goals = goals[goals["club_id"].notna()].copy()
    goals["club_id"] = goals["club_id"].astype(int)

    teams_df = con.execute(f'''
        SELECT DISTINCT t.team_id, t.team, c.division_level, c.game_type, c.category_base
        FROM read_parquet('{PARQUET}/teams/{season}.parquet') t
        JOIN read_parquet('{PARQUET}/team_group_membership/{season}.parquet') m ON t.team_id = m.team_id
        JOIN read_parquet('{PARQUET}/groups/{season}.parquet') g ON m.group_id = g.group_id
        JOIN read_parquet('{PARQUET}/competitions/{season}.parquet') c ON g.competition_id = c.competition_id
        WHERE c.phase_label = 'regular_season' AND c.category_base IN {YOUTH_CATEGORIES}
    ''').df()
    team_meta: dict[int, dict] = {}
    for r in teams_df.itertuples(index=False):
        tid = int(r.team_id)
        tier = TIER.get(r.division_level, 9)
        if tid not in team_meta or tier < team_meta[tid]["tier"]:
            team_meta[tid] = {"team_id": tid, "team": r.team, "division_level": r.division_level,
                               "tier": tier, "game_type": r.game_type, "category_base": r.category_base}

    return lineups, goals, team_meta


def stats_for(lineups, goals, pid, team_id, date_lo=None, date_hi=None):
    sub = lineups[(lineups["player_id"] == pid) & (lineups["team_id"] == team_id)]
    if date_lo is not None:
        sub = sub[sub["match_date"] >= date_lo]
    if date_hi is not None:
        sub = sub[sub["match_date"] < date_hi]
    apps = len(sub)
    cap = bool(sub["is_captain"].any())
    gk = bool(sub["is_goalkeeper"].any())
    gsub = goals[(goals["player_id"] == pid) & (goals["team_id"] == team_id)]
    if date_lo is not None:
        gsub = gsub[gsub["match_date"] >= date_lo]
    if date_hi is not None:
        gsub = gsub[gsub["match_date"] < date_hi]
    return apps, len(gsub), cap, gk


def classify_club_season(lineups_club, team_meta) -> tuple[dict, dict]:
    """Same classification as build_metro_v3.py's main loop, scoped to one
    club's rows for one season: majority team, or a genuine intra-season
    transfer via best_split(). Returns (result, meta) keyed by player_id."""
    result, meta = {}, {}
    for pid, g in lineups_club.groupby("player_id"):
        meta[pid] = {
            "name": g["player_name"].iloc[0],
            "birth_year": None if pd_isna(g["birth_year"].iloc[0]) else int(g["birth_year"].iloc[0]),
        }
        teams_seq = list(g["team_id"])
        counts = Counter(teams_seq)
        qualifying = {t: n for t, n in counts.items() if n >= MIN_APPS and t in team_meta}
        if not qualifying:
            majority = counts.most_common(1)[0][0]
            if majority in team_meta:
                result[pid] = {"start_team": int(majority), "end_team": int(majority), "transfer": None}
            continue
        if len(qualifying) == 1:
            t = next(iter(qualifying))
            result[pid] = {"start_team": int(t), "end_team": int(t), "transfer": None}
            continue
        split = best_split(teams_seq)
        if split and split["rate"] <= 0.15 and split["n_early"] >= MIN_APPS and split["n_late"] >= MIN_APPS \
                and split["early"] in qualifying and split["late"] in qualifying:
            split_date = list(g["match_date"])[split["split_idx"]]
            result[pid] = {"start_team": split["early"], "end_team": split["late"],
                            "transfer": {"from": split["early"], "to": split["late"], "date": split_date}}
        else:
            majority = max(qualifying, key=lambda t: qualifying[t])
            result[pid] = {"start_team": int(majority), "end_team": int(majority), "transfer": None}
    return result, meta


def build_club_stations(season, lineups_club, goals_club, team_meta, cls, meta) -> tuple[list[dict], list[dict]]:
    roster_by_team: dict[int, list] = {}
    intra_transfers: list[dict] = []
    for pid, c in cls.items():
        m = meta[pid]
        if c["transfer"]:
            tr = c["transfer"]
            intra = {"player_id": int(pid), "season": season, "from": str(tr["from"]),
                     "to": str(tr["to"]), "date": tr["date"]}
            intra_transfers.append(intra)
            apps, goals, cap, gk = stats_for(lineups_club, goals_club, pid, tr["from"], date_hi=tr["date"])
            roster_by_team.setdefault(tr["from"], []).append({
                "player_id": int(pid), "name": m["name"], "birth_year": m["birth_year"],
                "is_gk": gk, "is_cap": cap, "apps": apps, "goals": goals, "transfer_role": "before",
                "intra_transfer": intra,
            })
            apps, goals, cap, gk = stats_for(lineups_club, goals_club, pid, tr["to"], date_lo=tr["date"])
            roster_by_team.setdefault(tr["to"], []).append({
                "player_id": int(pid), "name": m["name"], "birth_year": m["birth_year"],
                "is_gk": gk, "is_cap": cap, "apps": apps, "goals": goals, "transfer_role": "after",
                "intra_transfer": intra,
            })
        else:
            t = c["start_team"]
            apps, goals, cap, gk = stats_for(lineups_club, goals_club, pid, t)
            roster_by_team.setdefault(t, []).append({
                "player_id": int(pid), "name": m["name"], "birth_year": m["birth_year"],
                "is_gk": gk, "is_cap": cap, "apps": apps, "goals": goals, "transfer_role": None,
                "intra_transfer": None,
            })

    stations = []
    for team_id, roster in roster_by_team.items():
        tm = team_meta[team_id]
        stations.append({
            "season": season, "team_id": team_id, "team": tm["team"], "letter": letter_of(tm["team"]),
            "division_level": tm["division_level"], "category_base": tm["category_base"],
            "game_type": tm["game_type"], "tier": tm["tier"],
            "roster": sorted(roster, key=lambda r: -r["goals"]),
        })
    return stations, intra_transfers


def build_club_links(seasons, stations_by_season, player_club_ids_by_season, club_id):
    """Cross-season continuity for one club — same shape as
    build_links_v3.py, but "did this player show up elsewhere" is a lookup
    into a per-season {player_id: {club_id, ...}} index built once per
    season (player_club_ids_by_season) instead of a DuckDB query per exiting
    /entering player, which doesn't scale past one club."""
    per_season = []
    for season in seasons:
        d = {}
        for t in stations_by_season.get(season, []):
            for r in t["roster"]:
                pid = r["player_id"]
                role = r.get("transfer_role")
                entry = d.setdefault(pid, {"start": None, "end": None})
                if role == "before":
                    entry["start"] = t["team_id"]
                elif role == "after":
                    entry["end"] = t["team_id"]
                else:
                    entry["start"] = t["team_id"]
                    entry["end"] = t["team_id"]
        per_season.append(d)

    def elsewhere_club(season, player_id):
        clubs = player_club_ids_by_season.get(season, {}).get(player_id)
        if not clubs:
            return None
        others = clubs - {club_id}
        return next(iter(others)) if others else None

    links, exits, entries = [], [], []
    for i, season in enumerate(seasons):
        cur = per_season[i]
        prev = per_season[i - 1] if i > 0 else None
        nxt = per_season[i + 1] if i < len(seasons) - 1 else None
        for pid, cs in cur.items():
            if nxt is not None:
                if pid in nxt:
                    links.append({"player_id": pid, "from_season": season, "from_team": cs["end"],
                                  "to_season": seasons[i + 1], "to_team": nxt[pid]["start"]})
                else:
                    dest = elsewhere_club(seasons[i + 1], pid)
                    exits.append({"player_id": pid, "season": season, "team_id": cs["end"],
                                  "kind": "left_to_club" if dest else "vanished",
                                  "dest_club": ci.club_display_names().get(dest) if dest else None})
            if prev is not None and pid not in prev:
                origin = elsewhere_club(seasons[i - 1], pid)
                entries.append({"player_id": pid, "season": season, "team_id": cs["start"],
                                "kind": "arrived_from_club" if origin else "new",
                                "origin_club": ci.club_display_names().get(origin) if origin else None})
    return links, exits, entries


def finalize_club(club_id, club_slug, seasons, stations_by_season, links, exits, intra_transfers) -> dict:
    season_idx_of = {s: i for i, s in enumerate(seasons)}

    tiers_seen = sorted({t["tier"] for ss in stations_by_season.values() for t in ss})
    tier_band = {tier: i for i, tier in enumerate(tiers_seen)}

    prev_order = None
    stations_out = []
    for si, season in enumerate(seasons):
        teams = stations_by_season.get(season, [])
        teams = sorted(teams, key=lambda t: (CAT_ORDINAL.get(t["category_base"], 9),
                                              tier_band.get(t["tier"], 9), t["team"]))
        team_rank = {t["team_id"]: i for i, t in enumerate(teams)}

        this_order = {}
        for t in teams:
            roster = t["roster"]
            if prev_order is None:
                ordered = sorted(roster, key=lambda r: -r["goals"])
            else:
                def sort_key(r):
                    po = prev_order.get(r["player_id"])
                    if po is not None:
                        return (0, po[0], po[1])
                    return (1, 0, -r["goals"])
                ordered = sorted(roster, key=sort_key)
            for j, r in enumerate(ordered):
                this_order[r["player_id"]] = (team_rank[t["team_id"]], j)

            roster_out = [{
                "player_id": r["player_id"], "name": r["name"], "birth_year": r["birth_year"],
                "is_gk": r["is_gk"], "is_cap": r["is_cap"], "apps": r["apps"], "goals": r["goals"],
                "transfer_role": r.get("transfer_role"),
                "entry_kind": r.get("entry_kind"), "origin_club": r.get("origin_club"),
                "intra_transfer": ({
                    "player_id": r["intra_transfer"]["player_id"], "season": r["intra_transfer"]["season"],
                    "from": f"{si}:{r['intra_transfer']['from']}", "to": f"{si}:{r['intra_transfer']['to']}",
                    "date": r["intra_transfer"]["date"],
                } if r.get("intra_transfer") else None),
            } for r in ordered]
            stations_out.append({
                "id": f"{si}:{t['team_id']}", "season_idx": si, "season": season,
                "team_id": t["team_id"], "letter": letter_of(t["team"]),
                "division_level": t["division_level"], "category_base": t["category_base"],
                "category_ordinal": CAT_ORDINAL.get(t["category_base"], 9),
                "game_type": t["game_type"], "tier_band": tier_band.get(t["tier"], 9),
                "club_slug": club_slug,
                "roster": roster_out,
            })
        prev_order = this_order

    links_out = [{
        "player_id": l["player_id"],
        "from": f"{season_idx_of[l['from_season']]}:{l['from_team']}",
        "to": f"{season_idx_of[l['to_season']]}:{l['to_team']}",
        "from_season": l["from_season"], "to_season": l["to_season"],
    } for l in links]
    exits_out = [{"player_id": e["player_id"], "season": e["season"],
                  "team": f"{season_idx_of[e['season']]}:{e['team_id']}",
                  "kind": e["kind"], "dest_club": e["dest_club"]} for e in exits]
    intra_out = [{"player_id": t["player_id"], "season": t["season"],
                  "from": f"{season_idx_of[t['season']]}:{t['from']}",
                  "to": f"{season_idx_of[t['season']]}:{t['to']}", "date": t["date"]}
                 for t in intra_transfers]

    all_birth_years = sorted({
        r["birth_year"] for ss in stations_out for r in ss["roster"] if r["birth_year"] is not None
    })

    return {
        "club_id": club_id, "club": ci.club_display_names().get(club_id) or f"club {club_id}",
        "season_names": seasons, "pivot_birth_years": all_birth_years,
        "category_order": CATEGORY_ORDER,
        "stations": stations_out, "links": links_out, "exits": exits_out, "intra_transfers": intra_out,
    }


def compute_entry_points(club_id, slug, present_seasons, stations_by_season,
                          player_club_ids_by_season, intra_transfers) -> dict[str, dict]:
    """One finalized diagram per plausible starting season - see WINDOW_LEN's
    comment for why a club's whole history can't be one diagram. Reuses
    build_club_links/finalize_club unchanged: both already only look at
    the (seasons, stations_by_season) they're handed, so a shorter window
    behaves exactly like build_metro_v3.py's original fixed 5-season list -
    a player continuing past the window's last season simply gets no
    link/exit recorded for it (nxt/prev is None at a window edge), not a
    dangling reference or a false "exit"."""
    player_birth_year: dict[int, int] = {}
    for stations in stations_by_season.values():
        for t in stations:
            for r in t["roster"]:
                if r["birth_year"] is not None:
                    player_birth_year.setdefault(r["player_id"], r["birth_year"])

    entry_points: dict[str, dict] = {}
    for i, start_season in enumerate(present_seasons):
        window = present_seasons[i:i + WINDOW_LEN]
        first_season_stations = stations_by_season.get(start_season, [])
        if not first_season_stations:
            continue
        youngest_ordinal = min(CAT_ORDINAL.get(t["category_base"], 9) for t in first_season_stations)
        cohort_years = {
            r["birth_year"]
            for t in first_season_stations if CAT_ORDINAL.get(t["category_base"], 9) == youngest_ordinal
            for r in t["roster"] if r["birth_year"] is not None
        }
        if not cohort_years:
            continue

        windowed: dict[str, list] = {}
        for season in window:
            out_stations = []
            for t in stations_by_season.get(season, []):
                roster = [dict(r) for r in t["roster"] if r["birth_year"] in cohort_years]
                if roster:
                    out_stations.append({**t, "roster": roster})
            if out_stations:
                windowed[season] = out_stations
        n_stations = sum(len(v) for v in windowed.values())
        if n_stations < MIN_STATIONS:
            continue

        links, exits, entries = build_club_links(window, windowed, player_club_ids_by_season, club_id)
        entry_by_key = {(e["season"], e["player_id"]): e for e in entries}
        for season, stations in windowed.items():
            for t in stations:
                for r in t["roster"]:
                    if r.get("transfer_role") == "after":
                        continue
                    e = entry_by_key.get((season, r["player_id"]))
                    if e:
                        r["entry_kind"] = e["kind"]
                        r["origin_club"] = e["origin_club"]

        window_intra = [t for t in intra_transfers
                        if t["season"] in window and player_birth_year.get(t["player_id"]) in cohort_years]
        entry_points[start_season] = finalize_club(club_id, slug, window, windowed, links, exits, window_intra)

    return entry_points


def build_all(out_dir: Path, seasons: list[str] | None = None, limit_clubs: int | None = None) -> None:
    seasons = seasons or list_lineup_seasons()
    print(f"Building club metro maps for seasons: {', '.join(seasons)}")

    con = duckdb.connect()
    stations_by_club: dict[int, dict[str, list]] = {}
    intra_by_club: dict[int, list] = {}
    player_club_ids_by_season: dict[str, dict[int, set]] = {}

    for season in seasons:
        lineups, goals, team_meta = load_season(con, season)
        player_club_ids_by_season[season] = lineups.groupby("player_id")["club_id"].apply(set).to_dict()

        # Split once per season (groupby), not once per club (a per-club
        # boolean mask over the whole season frame is O(clubs x rows) and
        # was the actual bottleneck here — 571 clubs x a season's full
        # match_lineups frame each, measured unusably slow).
        lineups_by_club = {cid: g for cid, g in lineups.groupby("club_id")}
        goals_by_club = {cid: g for cid, g in goals.groupby("club_id")}
        empty_goals = goals.iloc[0:0]

        club_ids = sorted(lineups_by_club.keys())
        if limit_clubs is not None:
            club_ids = club_ids[:limit_clubs]
        for club_id in club_ids:
            lineups_club = lineups_by_club[club_id]
            goals_club = goals_by_club.get(club_id, empty_goals)
            cls, meta = classify_club_season(lineups_club, team_meta)
            if not cls:
                continue
            stations, intra = build_club_stations(season, lineups_club, goals_club, team_meta, cls, meta)
            if not stations:
                continue
            stations_by_club.setdefault(club_id, {})[season] = stations
            intra_by_club.setdefault(club_id, []).extend(intra)
        print(f"  {season}: {len(club_ids)} clubs with lineup rows", flush=True)

    slugs = ci.club_slugs()
    data_dir = out_dir / "data" / "metro"
    data_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for club_id, stations_by_season in stations_by_club.items():
        present_seasons = [s for s in seasons if s in stations_by_season]
        n_stations = sum(len(v) for v in stations_by_season.values())
        if len(present_seasons) < MIN_SEASONS_PRESENT or n_stations < MIN_STATIONS:
            continue
        slug = slugs.get(club_id)
        if not slug:
            continue

        entry_points = compute_entry_points(club_id, slug, present_seasons, stations_by_season,
                                             player_club_ids_by_season, intra_by_club.get(club_id, []))
        if not entry_points:
            continue

        payload = {
            "club_id": club_id, "club": ci.club_display_names().get(club_id) or f"club {club_id}",
            "start_seasons": list(entry_points.keys()),
            "entry_points": entry_points,
        }
        (data_dir / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        written += 1

    print(f"  {written} clubs written to {data_dir} (of {len(stations_by_club)} with any lineup data)")


def main():
    parser = argparse.ArgumentParser(description="RFFM per-club metro-diagram data (Parquet-sourced)")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--limit-clubs", type=int, default=None,
                         help="only process the first N clubs per season (debugging)")
    args = parser.parse_args()
    build_all(Path(__file__).parent.parent / args.output_dir, limit_clubs=args.limit_clubs)


if __name__ == "__main__":
    main()
