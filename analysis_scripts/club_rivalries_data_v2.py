#!/usr/bin/env python3
"""
Cross-season club-vs-club match history ("Соперничества" - club_profile.py's
rivalries section): for a chosen club, every opponent it has ever played,
drillable down to which specific squads (team_id vs team_id) actually met.

Built from matches.csv (core crawl - every season, not gated behind any
enrichment stage), both sides resolved to club_id via club_identity.py
(team_club_map.csv - the authoritative team_id -> club_id join, no name
heuristics; see that module's docstring). A match where either side's
team_id has no known club_id is dropped (same ~1% honest gap as
club_profile_data_v2.py - team_club_gap_reasons.csv documents why), and a
match between two teams of the SAME club_id (a club's 'A' squad playing its
own 'B' squad) is dropped too - that is not a rivalry between two clubs.

DESIGN: ships raw match rows, not precomputed aggregates. An earlier version
of this module computed by_season/by_category/by_division/team_pairs W/D/L
breakdowns in Python and shipped only those - fine when the UI only ever
showed one fixed set of breakdowns, but club_profile_v2.py's rivalries tab
now has free-form multi-select cross-filtering (season x category x division
x our-team x their-team, PowerBI-slicer style) - precomputing every possible
filter *combination* server-side isn't tractable (combinatorial), so instead
each club's file carries every one of its own matches as a plain row, and
club_profile_v2.py's JS filters/aggregates client-side on demand. This is
also less data than the old precomputed shape (no more repeating the same
match under every team-pair's own nested log) and less code (no groupby-per-
breakdown-level machinery below).

Each match row is a positional array, not a keyed object - see MATCH_COLS
for column order - to avoid repeating 10 field names per row across
hundreds of thousands of rows; club_profile_v2.py's JS mirrors this order
via its own M_* index constants.

division_level (standings.csv/competitions.csv, restricted to DIV_ORDER -
imported from club_division_map_v2.py, the existing project-wide tier
ladder, not reinvented here) is attached to each match row - as DIV_CODE's
short code (e.g. "PREF"), not the full division_level string, matching the
exact convention club_profile_data.club_payload() already uses, since
club_profile_v2.py's JS already has CODE_TIER/CODE_LABEL injected for
sorting/labeling those codes - no new client-side constant needed. Also
shipped separately and more completely via load_division_presence(): every
tier a club_id has EVER fielded a team in, independent of whether a given
opponent met them there. The client needs both - a division filter needs to
know which matches match it (per-row division_level), and the "did this
club ever reach this tier at all" presence indicator needs data no match
row alone carries (a club can be in PRIMERA some season without that
season's matches touching the opponent currently open). Written once as a
single shared data/rivalries/_presence.json (not duplicated into every
club's own file) since many different clubs' pages need the same
opponent's presence data as they get opened.

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
from club_division_map_v2 import DIV_CODE, DIV_ORDER

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
    view (club_id/team_id = 'us', the other side = 'them') - so building
    each club's own file below is a plain filter on club_id, not two
    asymmetric cases."""
    cols = ["season", "category", "match_date", "venue", "division_level"]
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

    return pd.concat([home, away], ignore_index=True)


# Column order for each row in a club's "matches" array - positional, not
# keyed, to avoid repeating field names per row across hundreds of
# thousands of rows (see module docstring). club_profile_v2.py's JS mirrors
# this exact order via its own M_* index constants - keep both in sync.
MATCH_COLS = [
    "date", "season", "category", "division", "venue",
    "opp_club_id", "team_us_id", "opp_team_id", "home", "for", "against",
]


def build_all(out_dir: Path, profiled_club_ids: set[int]) -> None:
    print("Loading match history (core crawl, every season)...")
    matches = load_match_rows()
    print(f"  {len(matches)} inter-club finished matches")
    persp = perspective_rows(matches)
    persp = persp[persp["club_id"].isin(profiled_club_ids)]
    # 3 of 720,648 finished matches carry no match_date at all (a genuine,
    # tiny data quirk) - na_position="first" keeps sort_values from choking
    # on comparing float NaN against the other rows' str dates. groupby()
    # below preserves this order within each club's own rows (sort=False),
    # so each club's "matches" array comes out already date-sorted for free.
    persp = persp.sort_values("match_date", na_position="first")

    print("Loading division presence (standings x competitions, every season)...")
    presence = load_division_presence()

    names = ci.club_display_names()
    slugs = ci.club_slugs()
    team_names = load_team_names()

    data_dir = out_dir / "data" / "rivalries"
    data_dir.mkdir(parents=True, exist_ok=True)

    # _presence.json: shared across every club's page, not duplicated into
    # each one - covers every club_id that appears as either side of any
    # profiled club's match (an opponent's own presence is shown too, once
    # its matchup is opened - see module docstring).
    relevant_club_ids = set(persp["club_id"].unique()) | set(persp["opp_club_id"].unique())
    presence_out = {
        str(cid): {DIV_CODE.get(div, div): seasons for div, seasons in presence[cid].items()}
        for cid in relevant_club_ids if cid in presence
    }
    presence_text = json.dumps(presence_out, ensure_ascii=False, separators=(",", ":"))
    (data_dir / "_presence.json").write_text(presence_text, encoding="utf-8")
    print(f"  _presence.json: {len(presence_out)} clubs, {len(presence_text) / 1e6:.1f} MB")

    n_clubs = persp["club_id"].nunique()
    print(f"Writing per-club match files ({n_clubs} clubs)...")
    total_bytes = 0
    for i, (club_id, g) in enumerate(persp.groupby("club_id", sort=False), start=1):
        club_id = int(club_id)
        opponents_meta = {
            str(oid): {"display": names.get(oid) or f"club {oid}",
                       "slug": slugs.get(oid) if oid in profiled_club_ids else None}
            for oid in {int(x) for x in g["opp_club_id"].unique()}
        }
        tids = {int(x) for x in g["team_id"].unique()} | {int(x) for x in g["opp_team_id"].unique()}
        team_names_out = {str(t): team_names.get(t) or str(t) for t in tids}

        match_rows = [
            [
                r.match_date if isinstance(r.match_date, str) else None,
                r.season, r.category,
                DIV_CODE.get(r.division_level, r.division_level) if isinstance(r.division_level, str) else None,
                r.venue if isinstance(r.venue, str) else None,
                int(r.opp_club_id), int(r.team_id), int(r.opp_team_id),
                bool(r.is_home), int(r.for_), int(r.against),
            ]
            for r in g.itertuples(index=False)
        ]

        payload = {
            "club_id": club_id,
            "display": names.get(club_id) or f"club {club_id}",
            "cols": MATCH_COLS,
            "opponents_meta": opponents_meta,
            "team_names": team_names_out,
            "matches": match_rows,
        }

        slug = slugs.get(club_id) or f"club-{club_id}"
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        total_bytes += len(text)
        (data_dir / f"{slug}.json").write_text(text, encoding="utf-8")
        if i % 200 == 0:
            print(f"  {i}/{n_clubs}...")
    print(f"  done, {total_bytes / 1e6:.0f} MB across {n_clubs} per-club files")
