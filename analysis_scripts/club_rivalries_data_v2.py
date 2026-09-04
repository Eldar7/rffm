#!/usr/bin/env python3
"""
Cross-season club-vs-club and team-vs-team match history ("Соперничества" -
club_profile.py's rivalries section): for a chosen club, every opponent
it has ever played, with W/D/L and goals, drillable down to which specific
squads (team_id vs team_id) actually met and the full match log between
them.

Built from matches.csv (core crawl - every season, not gated behind any
enrichment stage), both sides resolved to club_id via club_identity.py
(team_club_map.csv - the authoritative team_id -> club_id join, no name
heuristics; see that module's docstring). A match where either side's
team_id has no known club_id is dropped (same ~1% honest gap as
club_profile_data_v2.py - team_club_gap_reasons.csv documents why), and a
match between two teams of the SAME club_id (a club's 'A' squad playing its
own 'B' squad) is dropped too - that is not a rivalry between two clubs.

The by-division breakdown additionally reads standings.csv and
competitions.csv (division_level, via load_division_presence()) - not just
"which tier did THESE matches happen in" but "which tiers has EACH club
ever reached at all," independent of whether they met there. Without that,
a division with 0 matches between a pair is ambiguous (never both there vs.
both there, different years/groups, just never scheduled together) - see
DIV_ORDER (imported from club_division_map_v2.py, the existing
project-wide tier ladder - not reinvented here) and _division_rows() below.

Deliberately spans every core-crawled season (2016-2017 on) - wider than
club_profile_data_v2.py's fichajugador-scoped season list (2017-2018 on),
since match results don't depend on that enrichment stage at all. The
rivalries section's own season range is therefore NOT the same as the rest
of club_profile.html's filters - see club_profile_v2.py's rivalries UI.

One row per club that ALSO has a club_profile.html page (club_profile_data_v2
.club_index()'s keys - passed in by the caller): only those clubs have
anywhere to embed this data. An opponent that itself has no club_profile
page (plays real matches but was never covered by fichajugador enrichment,
e.g. an adult-only category) still appears in the opponent list, just
without a `slug` - the client shows it as plain text, not a broken link.

Performance note: every W/D/L/goals aggregate (club totals, by-season,
by-category, per-opponent, per-opponent-by-season/category, per-team-pair)
is computed via ONE pandas .groupby() call each over the whole (doubled,
one row per side) match table - not a chain of per-club/per-opponent
.groupby() calls. An earlier version called .groupby() fresh for every one
of ~990 clubs' own opponent/team-pair breakdown (thousands of small calls)
and measured 8+ minutes without finishing - pandas' per-call overhead
dominates when there are many small groups; a handful of groupby calls
each covering the full 1.4M-row frame is >50x faster. Only the raw
per-match log (JSON needs individual match records, not just counts) is
built by hand, in one linear pass over the frame pre-sorted by date.

Usage:
    import club_rivalries_data_v2 as crd
    build_all(out_dir, profiled_club_ids=set(club_profile_clubs))
"""

import json
from collections import defaultdict
from pathlib import Path

import duckdb
import pandas as pd

import club_identity as ci
from club_division_map_v2 import DIV_ORDER

PARQUET_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm_parquet"


def load_competition_divisions() -> dict[str, str]:
    """competition_id -> division_level, every season. competition_id is
    globally unique (confirmed: never reused across seasons - see
    build_parquet.py's PER_SEASON_TABLES), so a flat dict needs no season
    key. Only DIV_ORDER's tiered ladder is meaningful for the rivalry
    section's by-division breakdown - a cup/zonal/"OTHER" competition_id
    simply won't be in this dict, and load_match_rows() below drops those
    match rows' division_level to null rather than inventing a bucket for
    them (same convention as club_division_map_v2.py's matrix)."""
    frames = [pd.read_parquet(p, columns=["competition_id", "division_level"])
              for p in sorted((PARQUET_DIR / "competitions").glob("*.parquet"))]
    df = pd.concat(frames, ignore_index=True).drop_duplicates("competition_id")
    df = df[df["division_level"].isin(DIV_ORDER)]
    return dict(zip(df["competition_id"], df["division_level"]))


def load_match_rows() -> pd.DataFrame:
    """One row per finished match, both sides already resolved to club_id -
    matches between two teams of the same club_id, or where either side's
    team_id has no club_id at all, are already dropped (see module
    docstring)."""
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT season, category, competition, competition_id, match_id, match_date,
               venue, venue_id, home_team_id, away_team_id, home_score, away_score
        FROM read_parquet('{PARQUET_DIR}/matches/*.parquet')
        WHERE is_finished = true AND home_team_id IS NOT NULL AND away_team_id IS NOT NULL
    """).df()
    con.close()

    t2c = ci.team_to_club()
    df["home_club_id"] = df["home_team_id"].astype(str).map(t2c)
    df["away_club_id"] = df["away_team_id"].astype(str).map(t2c)
    df = df.dropna(subset=["home_club_id", "away_club_id"]).copy()
    df["home_club_id"] = df["home_club_id"].astype(int)
    df["away_club_id"] = df["away_club_id"].astype(int)
    df = df[df["home_club_id"] != df["away_club_id"]]
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)
    df["division_level"] = df["competition_id"].map(load_competition_divisions())
    return df


def load_division_presence() -> dict[int, dict[str, list[str]]]:
    """club_id -> {division_level: sorted [season, ...]} - every DIV_ORDER
    tier a club_id has EVER fielded a team in, across every season,
    independent of any particular opponent. Same source/convention as
    club_division_map_v2.py's matrix (standings.csv joined to
    competitions.csv's division_level, restricted to DIV_ORDER's tiered
    ladder - a cup/zonal/"OTHER" appearance doesn't count as tier
    presence). Used by build_all() below so the by-division rivalry
    breakdown can show e.g. "0 matches in PRIMERA" as either "neither club
    ever reached it" or "both did, just never met there" instead of a bare,
    unexplained zero."""
    divs = load_competition_divisions()
    frames = [pd.read_parquet(p, columns=["season", "competition_id", "team_id"])
              for p in sorted((PARQUET_DIR / "standings").glob("*.parquet"))]
    df = pd.concat(frames, ignore_index=True)
    df["division_level"] = df["competition_id"].map(divs)
    df = df.dropna(subset=["division_level"])

    t2c = ci.team_to_club()
    df["club_id"] = df["team_id"].astype(str).map(t2c)
    df = df.dropna(subset=["club_id"])
    df["club_id"] = df["club_id"].astype(int)

    presence: dict[int, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in df[["club_id", "division_level", "season"]].drop_duplicates().itertuples(index=False):
        presence[r.club_id][r.division_level].add(r.season)
    return {cid: {div: sorted(seasons) for div, seasons in by_div.items()}
            for cid, by_div in presence.items()}


def load_team_names() -> dict[int, str]:
    """team_id -> its cleaned display name (teams.csv's `team` column - no
    site quote-wrapped suffix, unlike matches.csv's home_team/away_team -
    see DATA_DICTIONARY.md's note on that). A team_id can recur across
    seasons; last one wins, they don't meaningfully differ."""
    frames = [pd.read_parquet(p, columns=["team_id", "team"]) for p in sorted((PARQUET_DIR / "teams").glob("*.parquet"))]
    df = pd.concat(frames, ignore_index=True).drop_duplicates("team_id", keep="last")
    return {int(k): v for k, v in zip(df["team_id"], df["team"])}


def perspective_rows(matches: pd.DataFrame) -> pd.DataFrame:
    """Doubles every match into two rows - one from each side's own point of
    view (club_id/team_id = 'us', the other side = 'them') - so every
    aggregate downstream is a plain groupby("club_id"/"opp_club_id"/...)
    instead of two asymmetric cases. Also precomputes the W/D/L indicator
    columns every breakdown below sums - vectorized once, here, rather than
    per breakdown."""
    cols = ["season", "category", "competition", "match_id", "match_date", "venue", "venue_id", "division_level"]
    home = matches[cols].copy()
    home["club_id"] = matches["home_club_id"]
    home["team_id"] = matches["home_team_id"]
    home["opp_club_id"] = matches["away_club_id"]
    home["opp_team_id"] = matches["away_team_id"]
    home["for_"] = matches["home_score"]
    home["against"] = matches["away_score"]
    home["is_home"] = True

    away = matches[cols].copy()
    away["club_id"] = matches["away_club_id"]
    away["team_id"] = matches["away_team_id"]
    away["opp_club_id"] = matches["home_club_id"]
    away["opp_team_id"] = matches["home_team_id"]
    away["for_"] = matches["away_score"]
    away["against"] = matches["home_score"]
    away["is_home"] = False

    out = pd.concat([home, away], ignore_index=True)
    out["is_w"] = (out["for_"] > out["against"]).astype("int64")
    out["is_d"] = (out["for_"] == out["against"]).astype("int64")
    out["is_l"] = (out["for_"] < out["against"]).astype("int64")
    return out


_AGG = {"matches": ("for_", "size"), "wins": ("is_w", "sum"), "draws": ("is_d", "sum"),
        "losses": ("is_l", "sum"), "goals_for": ("for_", "sum"), "goals_against": ("against", "sum")}


def _wdl_groupby(persp: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """One vectorized aggregate over the whole frame - see module docstring
    for why this replaces per-club/per-opponent .groupby() calls."""
    g = persp.groupby(keys, sort=False).agg(**_AGG).reset_index()
    for c in ("matches", "wins", "draws", "losses", "goals_for", "goals_against"):
        g[c] = g[c].astype(int)
    return g


def _counter_dict(row) -> dict:
    return {
        "matches": int(row.matches), "wins": int(row.wins), "draws": int(row.draws), "losses": int(row.losses),
        "goals_for": int(row.goals_for), "goals_against": int(row.goals_against),
    }


def build_all(out_dir: Path, profiled_club_ids: set[int]) -> None:
    print("Loading match history (core crawl, every season)...")
    matches = load_match_rows()
    print(f"  {len(matches)} inter-club finished matches")
    persp = perspective_rows(matches)
    persp = persp[persp["club_id"].isin(profiled_club_ids)]

    print("Aggregating (vectorized groupby, one pass per breakdown level)...")
    club_totals = _wdl_groupby(persp, ["club_id"])
    club_by_season = _wdl_groupby(persp, ["club_id", "season"])
    club_by_category = _wdl_groupby(persp, ["club_id", "category"])
    opp_totals = _wdl_groupby(persp, ["club_id", "opp_club_id"])
    opp_by_season = _wdl_groupby(persp, ["club_id", "opp_club_id", "season"])
    opp_by_category = _wdl_groupby(persp, ["club_id", "opp_club_id", "category"])
    opp_by_division = _wdl_groupby(persp[persp["division_level"].notna()], ["club_id", "opp_club_id", "division_level"])
    tp_totals = _wdl_groupby(persp, ["club_id", "opp_club_id", "team_id", "opp_team_id"])

    print("Loading division presence (standings x competitions, every season)...")
    presence = load_division_presence()

    print("Building per-match log (single sorted pass)...")
    log_rows: dict[tuple, list] = defaultdict(list)
    # 3 of 720,648 finished matches carry no match_date at all (a genuine,
    # tiny data quirk, not a bug here) - na_position="first" keeps sort_values
    # from choking on comparing float NaN against the other rows' str dates,
    # and to_payload()'s per-team-pair sort below re-sorts with None-safe
    # `r["date"] or ""` so those 3 just land first within their pair's log.
    persp_sorted = persp.sort_values("match_date", na_position="first")
    for r in persp_sorted.itertuples(index=False):
        log_rows[(r.club_id, r.opp_club_id, r.team_id, r.opp_team_id)].append({
            "date": r.match_date if isinstance(r.match_date, str) else None,
            "season": r.season, "category": r.category,
            "division": r.division_level if isinstance(r.division_level, str) else None,
            "for": int(r.for_), "against": int(r.against), "home": bool(r.is_home),
            "venue": r.venue if isinstance(r.venue, str) else None,
            "venue_id": int(r.venue_id) if pd.notna(r.venue_id) else None,
        })

    names = ci.club_display_names()
    slugs = ci.club_slugs()
    team_names = load_team_names()

    # index everything by club_id (and, for the per-opponent tables, also by
    # opp_club_id) so assembling one club's payload below is dict lookups,
    # not filtering a dataframe per club.
    def _index(df, key_cols):
        idx = defaultdict(list)
        for row in df.itertuples(index=False):
            idx[tuple(getattr(row, k) for k in key_cols)].append(row)
        return idx

    club_by_season_ix = _index(club_by_season, ["club_id"])
    club_by_category_ix = _index(club_by_category, ["club_id"])
    opp_totals_ix = _index(opp_totals, ["club_id"])
    opp_by_season_ix = _index(opp_by_season, ["club_id", "opp_club_id"])
    opp_by_category_ix = _index(opp_by_category, ["club_id", "opp_club_id"])
    opp_by_division_ix = _index(opp_by_division, ["club_id", "opp_club_id"])
    tp_totals_ix = _index(tp_totals, ["club_id", "opp_club_id"])

    def _division_rows(club_id: int, opp_id: int) -> list[dict]:
        """DIV_ORDER-sorted rows for the by-division breakdown: every tier
        EITHER club has ever been in, W/D/L for this pair (0 if they never
        met there), plus each side's own season list so the client can show
        e.g. "never reached this tier" vs "both did, just not each other"
        instead of a bare unexplained zero (see club_rivalries_data_v2.py's
        module-level design discussion)."""
        wdl_by_div = {r.division_level: _counter_dict(r) for r in opp_by_division_ix[(club_id, opp_id)]}
        us = presence.get(club_id, {})
        them = presence.get(opp_id, {})
        divs = set(wdl_by_div) | set(us) | set(them)
        zero = {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0}
        return [
            {"division": d, **wdl_by_div.get(d, zero), "us_seasons": us.get(d, []), "them_seasons": them.get(d, [])}
            for d in DIV_ORDER if d in divs
        ]

    data_dir = out_dir / "data" / "rivalries"
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"Writing {len(club_totals)} club rivalry files...")
    total_bytes = 0
    for i, row in enumerate(club_totals.itertuples(index=False), start=1):
        club_id = int(row.club_id)

        opponents = []
        for opp_row in opp_totals_ix[(club_id,)]:
            opp_id = int(opp_row.opp_club_id)
            team_pairs = []
            for tp_row in tp_totals_ix[(club_id, opp_id)]:
                tid, opp_tid = int(tp_row.team_id), int(tp_row.opp_team_id)
                log = sorted(log_rows[(club_id, opp_id, tid, opp_tid)], key=lambda r: r["date"] or "")
                team_pairs.append({
                    "team_us_id": tid, "team_us_name": team_names.get(tid) or str(tid),
                    "team_them_id": opp_tid, "team_them_name": team_names.get(opp_tid) or str(opp_tid),
                    **_counter_dict(tp_row), "log": log,
                })
            team_pairs.sort(key=lambda p: -p["matches"])

            by_season = sorted(({"season": r.season, **_counter_dict(r)} for r in opp_by_season_ix[(club_id, opp_id)]),
                                key=lambda r: r["season"])
            by_category = sorted(({"category": r.category, **_counter_dict(r)} for r in opp_by_category_ix[(club_id, opp_id)]),
                                  key=lambda r: r["category"])
            opponents.append({
                "club_id": opp_id,
                "display": names.get(opp_id) or f"club {opp_id}",
                "slug": slugs.get(opp_id) if opp_id in profiled_club_ids else None,
                **_counter_dict(opp_row),
                "by_season": by_season, "by_category": by_category,
                "by_division": _division_rows(club_id, opp_id),
                "team_pairs": team_pairs,
            })
        opponents.sort(key=lambda o: -o["matches"])

        by_season = sorted(({"season": r.season, **_counter_dict(r)} for r in club_by_season_ix[(club_id,)]),
                            key=lambda r: r["season"])
        by_category = sorted(({"category": r.category, **_counter_dict(r)} for r in club_by_category_ix[(club_id,)]),
                              key=lambda r: r["category"])
        payload = {
            "club_id": club_id,
            "display": names.get(club_id) or f"club {club_id}",
            **_counter_dict(row),
            "by_season": by_season, "by_category": by_category,
            "opponents": opponents,
        }

        slug = slugs.get(club_id) or f"club-{club_id}"
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        total_bytes += len(text)
        (data_dir / f"{slug}.json").write_text(text, encoding="utf-8")
        if i % 200 == 0:
            print(f"  {i}/{len(club_totals)}...")
    print(f"  done, {total_bytes / 1e6:.0f} MB across {len(club_totals)} files")
