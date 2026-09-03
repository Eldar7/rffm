#!/usr/bin/env python3
"""
v2 PROOF-OF-CONCEPT: identical to club_profile_data.py except load_season_rows()
and build_players_lookup() source from output/processed/rffm_parquet/ via
rffm_data.read_table() instead of pd.read_csv(). build_players_lookup() uses
read_table("players_by_season", season=...) - not the deduped read_table
("players") - because it keeps the *first* (earliest) season's name/birth_year
per player_id, the same season-order-sensitive pattern as player_career.py's
compute_career_index(); see rffm_data.py's module docstring.

Cross-season player-career data for the Club Profile page (club_profile.py):
for a chosen club, every player who ever wore its shirt, with their FULL
RFFM history (every club/team/category/division/season, not just the rows
at this club) — donor-club and destination-club analysis needs a player's
whole timeline, not just their time here, to tell "arrived from X" and
"left for Y" apart from "always been here" / "still here".

Built from `player_competition_participation.csv` alone (opt-in fichajugador
enrichment, one row per player x competition-registration per season — a
player can have 2+ concurrent rows the same season, e.g. reserve + first
team dual registration). No materialized transfers.csv exists on purpose
(DATA_DICTIONARY.md) — this module does NOT invent one; it exposes each
player's plain season-by-season club membership and leaves "was this
season-to-season club change a real transfer" to the caller (club_profile.py
computes it per the active filter selection, since the answer depends on
which seasons are in scope), with one deliberate distinction: a club change
across two *calendar-adjacent* seasons the player has data for is a
confirmed fact (they were registered at club A, then at club B) — but a gap
year with no participation row before a new club appears is NOT resolved to
"came from nowhere"; it is surfaced as unknown/gap, never silently dropped
or misreported as a real transfer.

Usage (library — no CLI):
    import club_profile_data as cpd
    career = cpd.build_career()                  # one row per player x season x club
    clubs = cpd.club_index(career)                # club_key -> display name/slug/seasons
    payload = cpd.club_payload(career, clubs, "REAL MADRID C.F.")
"""

from pathlib import Path

import pandas as pd

import club_identity as ci
import rffm_data as data
from club_division_map import DIV_CODE, GT_CODE

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"


def list_seasons() -> list[str]:
    m = pd.read_csv(MANIFEST, dtype=str)
    ok = m[(m["stage"] == "fichajugador") & (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(ok["season"].unique().tolist())


def clean(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def norm_id(v) -> str | None:
    s = clean(v)
    if s is None:
        return None
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def load_season_rows(season: str) -> pd.DataFrame:
    """One row per player x competition-registration for `season`, tagged
    with category/division/game type from competitions.csv.

    club_id is resolved per-row from team_id via club_identity.resolve() -
    the authoritative team_club_map.csv join, not a name heuristic (see
    club_identity.py's module docstring). A row whose team_id has no known
    club_id (~1% of rows - team_club_gap_reasons.csv documents why: technical
    no-show, FASE ZONAL, a non-federated local cup, ...) gets club_id=None
    and is dropped in build_career() - an honest small coverage loss rather
    than a name-matched guess that could silently merge or split real clubs."""
    part = data.read_table("player_competition_participation", season=season)
    comps = data.read_table("competitions", season=season)
    comp_meta = comps.set_index("competition_id")[["category_base", "division_level", "game_type"]]
    part = part.join(comp_meta, on="competition_id")
    part["season"] = season
    part["team_id"] = part["team_id"].map(norm_id)
    part["club_name_raw"] = part["club_name_raw"].map(clean)
    part["club_id"] = part["team_id"].map(ci.resolve)
    return part


def build_career(seasons: list[str] | None = None) -> pd.DataFrame:
    """Every fichajugador-covered season's participation rows, concatenated
    and tagged, dropped of rows with no player_id or no resolvable club_id."""
    seasons = seasons or list_seasons()
    frames = [load_season_rows(s) for s in seasons]
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["player_id", "club_id"])
    df["club_id"] = df["club_id"].astype(int)
    return df


def club_index(career: pd.DataFrame) -> dict[int, dict]:
    """club_id -> {display, variants, slug, seasons_active, total_players}.
    `display`/`slug` come from club_identity.py (stable per club_id, not
    per raw-name spelling); `variants` lists every raw spelling seen under
    this club_id in the participation data, for the club search box to
    still match a stale sponsor-suffixed name a user might type."""
    names = ci.club_display_names()
    slugs = ci.club_slugs()
    all_variants = ci.club_name_variants()
    out: dict[int, dict] = {}
    for key, g in career.groupby("club_id"):
        # union of this table's own spellings with club_identity's fuller
        # cross-table set (teams.csv/clubs.csv carry sponsor-era names this
        # table's own club_name_raw doesn't - see club_name_variants()'s
        # docstring) - needed so a not-yet-migrated report's ?clubname=
        # cross-link (an older raw spelling) still resolves to this club.
        variants = sorted(set(g["club_name_raw"].dropna().unique().tolist()) | set(all_variants.get(key, [])))
        out[key] = {
            "display": names.get(key) or (variants[0] if variants else f"club {key}"),
            "slug": slugs.get(key) or f"club-{key}",
            "variants": variants,
            "seasons_active": sorted(g["season"].unique().tolist()),
            "total_players": int(g["player_id"].nunique()),
        }
    return out


def index_payload(clubs: dict[int, dict]) -> list[dict]:
    """Small list for the club search/selector — every club, sorted by
    display name, without the heavy per-player payload club_payload() below
    builds one club at a time.

    `variants` (every raw club_name_raw spelling seen for this club_id) is
    carried here too, small as it is, because it's not just search-box
    fuzzing: cross-links from club_division_map.py / team_cards.py /
    player_cards.py / all_clubs.py still pass `?clubname=<raw name>` off
    THEIR OWN (not yet club_id-based) grouping - and since this page's
    `display` is now the club's CURRENT canonical name (club_identity.py),
    a link carrying an older sponsor-era name would stop matching by
    `display` alone the moment a club renames. See club_profile_v2.py's
    init()."""
    return sorted(
        ({"club_id": k, "display": v["display"], "slug": v["slug"],
          "variants": v["variants"],
          "seasons_active": v["seasons_active"], "total_players": v["total_players"]}
         for k, v in clubs.items()),
        key=lambda r: r["display"],
    )


def club_payload(career: pd.DataFrame, clubs: dict[int, dict], target_club_id: int) -> dict:
    """Full global timeline (every club, every season — not just rows at
    the target club) for every player who ever had >=1 row at target_club_id,
    so the client can compute donor/destination clubs relative to whatever
    season/category/team filters are active without a second fetch.

    Rows are normalized to keep file size down (~1.9M row-copies across
    every club file, since a player who touched N clubs in their career
    appears in N files with their FULL history each — see module docstring):
    club names and team names are pulled out into small per-file lookup
    dicts (`clubs`/`teams`) instead of repeated on every row, division/game
    type collapse to the same short codes club_division_map.py already uses
    for table badges, season collapses to its start year (re-expandable as
    f"{y}-{y+1}" client-side), and competition name/id is dropped entirely —
    category+division+game-type already carry everything Blocks 1-3 need,
    and a dropped competition label was the single largest per-row field."""
    club_names_by_id = ci.club_display_names()
    target_players = career.loc[career["club_id"] == target_club_id, "player_id"].unique()
    sub = career[career["player_id"].isin(target_players)].copy()
    sub["div_code"] = sub["division_level"].map(lambda v: DIV_CODE.get(clean(v), clean(v) or "OTHER"))
    sub["gt_code"] = sub["game_type"].map(lambda v: GT_CODE.get(clean(v), clean(v) or "?"))
    sub["cat"] = sub["category_base"].map(lambda v: clean(v) or "OTHER")
    sub = sub.drop_duplicates(subset=["player_id", "season", "club_id", "team_id", "cat", "div_code", "gt_code"])
    sub = sub.sort_values(["player_id", "season"])

    club_ix: dict[int, str] = {}          # club_id -> local short index "c0", "c1", ...
    club_names: dict[str, str] = {}       # local index -> display name
    team_names: dict[str, str] = {}       # team_id -> team display name

    players: dict[str, dict] = {}
    for row in sub.itertuples(index=False):
        pid = row.player_id
        entry = players.setdefault(pid, {"name": None, "birth_year": None, "rows": []})
        ck = row.club_id
        ix = club_ix.get(ck)
        if ix is None:
            ix = f"c{len(club_ix)}"
            club_ix[ck] = ix
            # canonical name for this club_id, not whichever raw sponsor-era
            # spelling this particular row happened to carry - a player whose
            # career spans a club's rename would otherwise see the same club
            # listed twice under two different display strings.
            club_names[ix] = club_names_by_id.get(ck) or row.club_name_raw
        tid = row.team_id
        if tid and tid not in team_names:
            team_names[tid] = clean(row.team) or tid
        entry["rows"].append({
            "y": int(row.season[:4]), "ck": ix, "t": tid,
            "cat": row.cat, "div": row.div_code, "gt": row.gt_code,
        })

    return {
        "club_id": target_club_id,
        "display": clubs[target_club_id]["display"],
        "seasons_active": clubs[target_club_id]["seasons_active"],
        "self": club_ix[target_club_id],  # which "clubs" entry IS the target club itself —
        # rows with ck==self are membership at this club; every other ck value in a
        # player's row list is their history at a DIFFERENT club (donor/destination
        # inference only), not part of "this club's own teams/roster".
        "clubs": club_names,
        "teams": team_names,
        "players": players,
    }


def build_players_lookup(seasons: list[str]) -> dict[str, tuple[str, str | None]]:
    """player_id -> (name, birth_year), built ONCE from every season's
    players.csv and reused across every club's payload — attach_player_names()
    used to re-scan players.csv per club (8 reads x ~1,200 clubs), which
    dominated build time for no reason since the lookup itself doesn't
    depend on which club is being built."""
    lookup: dict[str, tuple[str, str | None]] = {}
    for season in seasons:
        players = data.read_table("players_by_season", season=season)[["player_id", "player_name", "birth_year"]]
        if players.empty:
            continue
        for r in players.itertuples(index=False):
            if r.player_id in lookup:
                continue
            lookup[r.player_id] = (clean(r.player_name) or r.player_id, clean(r.birth_year))
    return lookup


def attach_player_names(payload: dict, players_lookup: dict[str, tuple[str, str | None]]) -> None:
    for pid, entry in payload["players"].items():
        name, birth_year = players_lookup.get(pid, (pid, None))
        entry["name"] = name
        entry["birth_year"] = birth_year
