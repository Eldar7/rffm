#!/usr/bin/env python3
"""
Per-team "Карта участия" data, Parquet-sourced (output/processed/
rffm_parquet/ via rffm_data.read_table()) — the team-level analog of
participation_map_v2.py, for a squad slot (`team_id` — a club's "A"/"B"/
"C"/... team within one age category, which DATA_DICTIONARY.md and live
sampling both confirm keeps the *same* `team_id` season to season, only its
division moving, rather than following the players' age upward), every
season's competition(s), final standing, and match list — so a team card
can show how that one squad moved through divisions within a season and
across seasons, and which competitions it entered along the way.

Deliberately built from CORE tables only (team_group_membership,
competitions, standings, matches, via rffm_data.py) — unlike
participation_map_v2.py (the player-level equivalent), this needs no
match_lineups/acta_partido enrichment, so it covers every season with a
complete core crawl, not just the (fewer, category-scoped) seasons
acta_partido happens to have been run for.

Shape mirrors participation_map_v2.py's "stint" grouping (one entry per
(team, competition) pairing, matches nested inside) for the same reason: a
flat per-match row repeats team/competition/division fields on every row for
no benefit. Sharded by CLUB (not by team_id-modulo like participation_map's
player shards) because club is already the natural, small-cardinality
partition a viewer needs — opening one team's card only ever needs that
team's own club's squads, and the club-level "squads over the seasons"
overview (a separate view onto this same file, on club_division_map_v2.html)
needs every squad of one club at once anyway. One file per club, ALL seasons
in it (not split per season) — team counts per club are small enough (see
build_all()'s own printed totals) that splitting further would only add
fetches for no size benefit.

The "which club" grouping is itself real work, not a simple string match:
club_name_raw (teams.csv) is a per-SEASON cosmetic display name, not a
stable identity — a real case in this data, club_id 1011: teams.csv shows
"ARAVACA C.F." in 2021-2022, "ARAVACA C.F. - Bhhs Spain" in 2022-2024, then
"ARAVACA C.F. - CEIBA" in 2024-2026, all the same real club. Grouping by
that raw string (an earlier version of this file did exactly that) splits
one club's history across one file per era. Resolves the real, stable RFFM
club_id from `output/processed/rffm/team_club_map.csv` (the `team_clubs`
crawl stage — TEAM_CLUB_GAP_REASONS.md/DATA_FINDINGS.md — a direct
team_id -> club_id table, ~84% of team_ids resolved, mostly via each
club's own /fichaclub roster page, not name matching at all) — a strictly
better source than an earlier version of this fix, which derived club_id
per-season via clubs.csv's representative_team_id column and only
resolved roughly half of clubs. A team_id whose club_id still isn't in
team_club_map.csv (the unresolved ~16% — see TEAM_CLUB_GAP_REASONS.md for
why: mostly phantom/placeholder teams, not real gaps) falls back to its
own most-recent club_name_raw, same as before — a rename can still
fragment history for those, a known limitation shared with
club_profile_data.py's club_key().

club_division_map.py's TIER_OF stays the single source of truth for
division-tier vocabulary — this module imports the constant (not a CSV
read) rather than redefining it.

Usage:
    python analysis_scripts/team_participation_map_v2.py
    python analysis_scripts/team_participation_map_v2.py --season 2025-2026 --output-dir reports
"""

import argparse
import json
from pathlib import Path

import pandas as pd

import rffm_data as data
from club_division_map import TIER_OF
from site_theme import club_slug_map
from team_rosters import norm_id

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"


def list_core_seasons() -> list[str]:
    m = pd.read_csv(MANIFEST, dtype=str)
    core = m[(m["stage"] == "core") & (m["category_base"] == "ALL") &
             (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(core["season"].unique().tolist())


def clean(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def safe_map(s: pd.Series, func) -> pd.Series:
    """`Series.map(func)` where func can return None - NOT safe to use
    directly, and not obvious why: pandas 3.x infers the RESULT column's
    dtype too, and for an all-string(-or-None) result it aggressively
    infers `StringDtype`, under which a returned `None` silently becomes a
    raw Python `float('nan')` instead of staying `None`/`pd.NA` - happens
    the moment `.map()` returns, before the result is even assigned
    anywhere (confirmed: `.dtype` on a bare `.map()` result already reads
    "str"). Every `norm_id`/`clean` call in this file hit this - both the
    ones assigned straight into a DataFrame column (matches["hid"] etc.)
    and the ones fed straight into `dict(zip(...))` without ever touching a
    DataFrame column - `zip()` iterates the already-corrupted Series either
    way. Same root cause as rffm_data.py's `_stringify()` fix (see its
    docstring) - fixed the same way: never construct a Series pandas could
    dtype-infer over `func`'s output. Unlike `_stringify()`, `func` here is
    an arbitrary callable (norm_id/clean), not always-`str()`, so there's
    no numpy `.astype()` shortcut to vectorize it with - this still calls
    `func` once per element in a Python loop. Iterating a plain numpy
    object array (`.to_numpy()`) rather than the pandas Series directly at
    least skips pandas' per-element access overhead; the tables this file
    calls it on (teams/standings/matches, thousands not hundreds-of-
    thousands of rows) are small enough that this hasn't been worth
    optimizing further."""
    arr = s.to_numpy(dtype=object, copy=False)
    return pd.Series([func(v) for v in arr], index=s.index, dtype=object)


def clean_int(v) -> int | None:
    v = clean(v)
    if v is None:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def build_season_club_teams(season: str) -> dict[str, dict[str, dict]]:
    """club_name_raw -> {team_id: {team, suffix, stints: {stint_key: {...}}}}
    for one season — merged across seasons by the caller. A `stint` here is
    one (team_id, competition_id) pairing within THIS season; the cross-
    season merge in build_all() just concatenates each team's per-season
    stints, keyed additionally by season since the same competition_id is
    never reused across seasons."""
    teams = data.read_table("teams", season=season)
    matches = data.read_table("matches", season=season)
    comps = data.read_table("competitions", season=season)
    standings = data.read_table("standings", season=season)

    team_id_norm = safe_map(teams["team_id"], norm_id)
    tid_to_club = dict(zip(team_id_norm, safe_map(teams["club_name_raw"], clean)))
    tid_to_name = dict(zip(team_id_norm, safe_map(teams["team"], clean)))
    tid_to_suffix = dict(zip(team_id_norm, safe_map(teams["squad_suffix"], clean)))
    comp_by_id = {row.competition_id: row for row in comps.itertuples(index=False)}

    standings = standings.copy()
    standings["gid"] = safe_map(standings["group_id"], norm_id)
    standings["tid"] = safe_map(standings["team_id"], norm_id)
    group_size = standings.groupby("gid")["tid"].nunique().to_dict()
    standing_by_team_group: dict[tuple[str, str], dict] = {}
    for s in standings.itertuples(index=False):
        key = (s.tid, s.gid)
        if key[0] is None or key[1] is None:
            continue
        standing_by_team_group[key] = {
            "pos": clean_int(s.position), "played": clean_int(s.played),
            "w": clean_int(s.wins), "d": clean_int(s.draws), "l": clean_int(s.losses),
            "gf": clean_int(s.goals_for), "ga": clean_int(s.goals_against),
            "pts": clean_int(s.points), "size": int(group_size.get(key[1], 0)) or None,
        }

    matches = matches.copy()
    matches["hid"] = safe_map(matches["home_team_id"], norm_id)
    matches["aid"] = safe_map(matches["away_team_id"], norm_id)

    club_teams: dict[str, dict[str, dict]] = {}
    sides = (("hid", "aid", "home_team", "away_team", "home_score", "away_score", True),
             ("aid", "hid", "away_team", "home_team", "away_score", "home_score", False))
    for r in matches.itertuples(index=False):
        for tid_col, opp_col, _own_col, opp_col_name, sf_col, sa_col, is_home in sides:
            tid = getattr(r, tid_col)
            if not tid:
                continue
            club = tid_to_club.get(tid)
            if not club:
                continue
            opp_tid = getattr(r, opp_col)
            opp_name = tid_to_name.get(opp_tid) or clean(getattr(r, opp_col_name))
            gf, ga = clean_int(getattr(r, sf_col)), clean_int(getattr(r, sa_col))
            res = None
            if r.is_finished == "True" and gf is not None and ga is not None:
                res = "W" if gf > ga else ("L" if gf < ga else "D")

            comp_id = clean(r.competition_id)
            comp = comp_by_id.get(comp_id)
            cat = (clean(comp.category_base) if comp is not None else None) or clean(r.category) or "OTHER"
            div = (clean(comp.division_level) if comp is not None else None) or "OTHER"
            gt = (clean(comp.game_type) if comp is not None else None) or clean(r.game_type)
            gt_id = (clean(comp.game_type_id) if comp is not None else None) or clean(r.game_type_id)

            team_rec = club_teams.setdefault(club, {}).setdefault(tid, {
                "team": tid_to_name.get(tid) or tid,
                "suffix": tid_to_suffix.get(tid),
                "stints": {},  # stint_key -> stint dict, flattened to a list in build_all()
            })
            stint_key = comp_id  # unique within one season already
            stint = team_rec["stints"].get(stint_key)
            if stint is None:
                stint = {
                    "season": season, "comp_id": comp_id,
                    "comp": clean(comp.competition) if comp is not None else None,
                    "phase": clean(comp.phase_label) if comp is not None else None,
                    "grp": clean(r.group), "group_id": clean(r.group_id),
                    "cat": cat, "div": div, "tier": TIER_OF.get(div),
                    "gt": gt, "gt_id": gt_id,
                    "standing": None, "matches": [],
                    "_group_ids": set(),
                }
                team_rec["stints"][stint_key] = stint
            if stint["_group_ids"] and stint["grp"] and clean(r.group_id) not in stint["_group_ids"]:
                # Cup rounds run as separate group_ids under one competition_id
                # (see team_cards.py's build_club_team_cards for the same
                # case) — no single `grp` label represents the whole stint
                # once more than one shows up, so drop it.
                stint["grp"] = None
            stint["_group_ids"].add(clean(r.group_id))
            if stint["standing"] is None:
                stint["standing"] = standing_by_team_group.get((tid, clean(r.group_id)))

            stint["matches"].append({
                "mid": clean(r.match_id), "date": clean(r.match_date), "round": clean_int(r.matchday),
                "home": is_home, "opp": opp_name, "opp_tid": opp_tid,
                "gf": gf, "ga": ga, "res": res,
            })

    for teams_of_club in club_teams.values():
        for team_rec in teams_of_club.values():
            for stint in team_rec["stints"].values():
                stint.pop("_group_ids", None)
                stint["matches"].sort(key=lambda x: x["date"] or "9999-99-99")
            team_rec["stints"] = sorted(team_rec["stints"].values(),
                                         key=lambda s: (s["matches"][0]["date"] or "9999-99-99") if s["matches"] else "9999-99-99")

    return club_teams


TEAM_CLUB_MAP_CSV = BASE / "team_club_map.csv"


def load_team_club_map() -> dict[str, str]:
    """team_id -> club_id, straight from the `team_clubs` crawl stage
    (output/processed/rffm/team_club_map.csv — TEAM_CLUB_GAP_REASONS.md/
    DATA_FINDINGS.md): a direct table, resolved mostly by matching each
    team_id against its club's own /fichaclub roster page, not by any
    club_name_raw join — so it's immune to the sponsor-suffix churn this
    module's docstring describes, and needs no per-season lookup at all
    (team_id is already this whole module's stable identity; this table
    just tells you which real club each one belongs to). ~84% of team_ids
    resolved as of this writing; the rest fall back to build_all()'s
    most-recent-club_name_raw grouping (see there)."""
    if not TEAM_CLUB_MAP_CSV.exists():
        return {}
    m = pd.read_csv(TEAM_CLUB_MAP_CSV, dtype=str)
    return dict(zip(safe_map(m["team_id"], norm_id), safe_map(m["club_id"], clean)))


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    seasons = seasons or list_core_seasons()
    print(f"Building team participation map for seasons: {', '.join(seasons)}")

    # team_id -> {team, suffix, club, club_id, slugs: set[str], stints: [...]}
    # Grouped by team_id FIRST, globally across every season, NOT by
    # club_name_raw: a club's raw name can (and does) change between
    # seasons — sponsor-suffix churn, e.g. a real case in this data:
    # team_id 300394 played under "ARAVACA C.F." in 2021-2022, "ARAVACA
    # C.F. - Bhhs Spain" in 2022-2024, and "ARAVACA C.F. - CEIBA" in
    # 2024-2026 — same team_id the whole time. team_id is the stable
    # identity this whole module is built on; `club`/`club_id`/`slugs`
    # below only decide which output FILE a team's full history is written
    # under (and findable from) — never used to decide whether two seasons
    # belong to the same team, which team_id already answers on its own.
    team_to_club_id = load_team_club_map()

    merged: dict[str, dict] = {}
    for season in seasons:
        season_teams = build_season_club_teams(season)
        # Same club_slug_map() call, over the same per-season name universe,
        # that team_cards_v2.py/club_division_map_v2.py themselves use to
        # build a link INTO this data — computed fresh per season (not
        # once globally) so a slug this file gets written under is always
        # byte-identical to what a link from that specific season's page
        # actually points at, even in a rare same-season base-slug collision.
        slug_of_name = club_slug_map(sorted(season_teams.keys()))
        for club, teams_of_club in season_teams.items():
            slug = slug_of_name[club]
            for tid, team_rec in teams_of_club.items():
                out_rec = merged.setdefault(tid, {
                    "team": team_rec["team"], "suffix": team_rec["suffix"],
                    "club": club, "club_id": team_to_club_id.get(tid), "slugs": set(), "stints": [],
                })
                out_rec["team"] = team_rec["team"]  # keep the most-recent season's display name
                out_rec["suffix"] = team_rec["suffix"] or out_rec["suffix"]
                out_rec["club"] = club  # ditto — most-recent season's club name
                out_rec["slugs"].add(slug)
                out_rec["stints"].extend(team_rec["stints"])
        print(f"  {season} done")

    for team_rec in merged.values():
        team_rec["stints"].sort(
            key=lambda s: (s["matches"][0]["date"] or "9999-99-99") if s["matches"] else "9999-99-99")

    # Group team_ids into real-club buckets: by club_id (RFFM's own stable
    # identity, from team_club_map.csv) when resolved, else by the team's
    # own most-recent club_name_raw — the fallback only matters for
    # team_club_map.csv's ~16% unresolved gap (TEAM_CLUB_GAP_REASONS.md —
    # mostly phantom/placeholder teams, not real clubs missing coverage);
    # a rename can still fragment one of those, a known limitation shared
    # with club_profile_data.py's club_key().
    buckets: dict[str, dict] = {}
    for tid, rec in merged.items():
        key = f"cid:{rec['club_id']}" if rec["club_id"] else f"name:{rec['club']}"
        b = buckets.setdefault(key, {"teams": {}, "slugs": set(), "display": rec["club"], "_latest": ""})
        b["teams"][tid] = {"team": rec["team"], "suffix": rec["suffix"], "stints": rec["stints"]}
        b["slugs"] |= rec["slugs"]
        latest = max((s["season"] for s in rec["stints"]), default="")
        if latest >= b["_latest"]:
            b["_latest"] = latest
            b["display"] = rec["club"]  # the name attached to whichever team's stints reach furthest

    data_dir = out_dir / "data" / "team_participation"
    data_dir.mkdir(parents=True, exist_ok=True)
    total_teams, total_files = 0, 0
    for bucket in buckets.values():
        payload = {"club": bucket["display"], "teams": bucket["teams"]}
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        for slug in bucket["slugs"]:
            (data_dir / f"{slug}.json").write_text(text, encoding="utf-8")
            total_files += 1
        total_teams += len(bucket["teams"])
    print(f"  {len(buckets)} clubs ({total_files} name-slug files, some clubs written under >1 historical "
          f"slug), {total_teams} squads written to {data_dir}")


def main():
    parser = argparse.ArgumentParser(description="RFFM team participation-map data (Parquet-sourced)")
    parser.add_argument("--season", default=None, help="build only this season's data (default: every season with core data)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


if __name__ == "__main__":
    main()
