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

import re
import unicodedata
from pathlib import Path

import pandas as pd

import rffm_data as data
from club_division_map import DIV_CODE, GT_CODE
from site_theme import club_slug_map

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


def club_key(name: str) -> str:
    """Normalize a club_name_raw into a cross-season identity key — same
    diacritic/punctuation/case folding as site_theme.club_slug_map()'s
    base_slug so the two stay conceptually aligned, uppercased instead of
    hyphenated since this is an internal grouping key, not a URL segment.
    Only folds cosmetic variation (accents, case, punctuation/whitespace) —
    a club renamed between seasons (sponsor change, legal-name change)
    still splits into two keys here, a known limitation shared with every
    other cross-season club join in this project (see player_cards.py's
    tid_to_club comment for the same ~20%-mismatch caveat)."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", " ", s).strip().upper()
    return s or "CLUB"


def load_season_rows(season: str) -> pd.DataFrame:
    """One row per player x competition-registration for `season`, tagged
    with category/division/game type from competitions.csv."""
    part = data.read_table("player_competition_participation", season=season)
    comps = data.read_table("competitions", season=season)
    comp_meta = comps.set_index("competition_id")[["category_base", "division_level", "game_type"]]
    part = part.join(comp_meta, on="competition_id")
    part["season"] = season
    part["team_id"] = part["team_id"].map(norm_id)
    part["club_name_raw"] = part["club_name_raw"].map(clean)
    part["club_key"] = part["club_name_raw"].map(lambda v: club_key(v) if v else None)
    return part


def build_career(seasons: list[str] | None = None) -> pd.DataFrame:
    """Every fichajugador-covered season's participation rows, concatenated
    and tagged, dropped of rows with no player_id or no resolvable club."""
    seasons = seasons or list_seasons()
    frames = [load_season_rows(s) for s in seasons]
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["player_id", "club_key"])
    return df


def club_index(career: pd.DataFrame) -> dict[str, dict]:
    """club_key -> {display, variants, slug, seasons_active, total_players}.
    `display` is the most common raw name for that key (mode) — usually the
    only one; `variants` lists every raw spelling seen, for the club search
    box to match against so a stale sponsor-suffixed name still finds it."""
    out: dict[str, dict] = {}
    for key, g in career.groupby("club_key"):
        variants = sorted(g["club_name_raw"].dropna().unique().tolist())
        display = g["club_name_raw"].value_counts().idxmax()
        out[key] = {
            "display": display,
            "variants": variants,
            "seasons_active": sorted(g["season"].unique().tolist()),
            "total_players": int(g["player_id"].nunique()),
        }
    slugs = club_slug_map([v["display"] for v in out.values()])
    for key, v in out.items():
        v["slug"] = slugs[v["display"]]
    return out


def index_payload(clubs: dict[str, dict]) -> list[dict]:
    """Small list for the club search/selector — every club, sorted by
    display name, without the heavy per-player payload club_payload() below
    builds one club at a time."""
    return sorted(
        ({"key": k, "display": v["display"], "slug": v["slug"],
          "seasons_active": v["seasons_active"], "total_players": v["total_players"]}
         for k, v in clubs.items()),
        key=lambda r: r["display"],
    )


def club_payload(career: pd.DataFrame, clubs: dict[str, dict], target_key: str) -> dict:
    """Full global timeline (every club, every season — not just rows at
    the target club) for every player who ever had >=1 row at target_key,
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
    target_players = career.loc[career["club_key"] == target_key, "player_id"].unique()
    sub = career[career["player_id"].isin(target_players)].copy()
    sub["div_code"] = sub["division_level"].map(lambda v: DIV_CODE.get(clean(v), clean(v) or "OTHER"))
    sub["gt_code"] = sub["game_type"].map(lambda v: GT_CODE.get(clean(v), clean(v) or "?"))
    sub["cat"] = sub["category_base"].map(lambda v: clean(v) or "OTHER")
    sub = sub.drop_duplicates(subset=["player_id", "season", "club_key", "team_id", "cat", "div_code", "gt_code"])
    sub = sub.sort_values(["player_id", "season"])

    club_ix: dict[str, str] = {}          # club_key -> local short index "c0", "c1", ...
    club_names: dict[str, str] = {}       # local index -> display name
    team_names: dict[str, str] = {}       # team_id -> team display name

    players: dict[str, dict] = {}
    for row in sub.itertuples(index=False):
        pid = row.player_id
        entry = players.setdefault(pid, {"name": None, "birth_year": None, "rows": []})
        ck = row.club_key
        ix = club_ix.get(ck)
        if ix is None:
            ix = f"c{len(club_ix)}"
            club_ix[ck] = ix
            club_names[ix] = row.club_name_raw
        tid = row.team_id
        if tid and tid not in team_names:
            team_names[tid] = clean(row.team) or tid
        entry["rows"].append({
            "y": int(row.season[:4]), "ck": ix, "t": tid,
            "cat": row.cat, "div": row.div_code, "gt": row.gt_code,
        })

    return {
        "club_key": target_key,
        "display": clubs[target_key]["display"],
        "seasons_active": clubs[target_key]["seasons_active"],
        "self": club_ix[target_key],  # which "clubs" entry IS the target club itself —
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
