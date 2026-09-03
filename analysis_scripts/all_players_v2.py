#!/usr/bin/env python3
"""
v2 PROOF-OF-CONCEPT: identical to all_players.py except build_career_profiles(),
build_season_performance(), and build_season_all_players() source from
output/processed/rffm_parquet/ via rffm_data.read_table() instead of
pd.read_csv(). build_career_profiles() uses read_table("players_by_season",
season=...) - not the deduped table - since its "first non-empty birth_year
across seasons" logic is season-order-sensitive, same pattern as
player_career.py (imported here as player_career_v2). build_season_all_players()
also uses read_table("players_by_season", season=...), not the deduped
table - confirmed on real data that a player's recorded name spelling can
genuinely change between seasons (RFFM's own site started serving some
players' names without diacritics from 2024-2025 onward), so the deduped
table's "latest name wins" pick would show an old season's page under a
spelling that didn't exist yet that season. Imports build_club_team_cards/
norm_id from team_cards_v2, not team_cards.

All-players browser: every player this project has fichajugador data for,
one row each, with every per-player metric this project already computes
elsewhere (team_cards.py's roster summary, player_cards.py's career stats)
brought together in one sortable/filterable table — season selector +
age-category/division chips (same widgets as club_division_map.py) plus
free-text search, same Excel-style column sort/filter as every other table
in this project (site_theme.py's dtable).

Two very different costs are involved, so they're split into two build
passes:
  - Career-wide facts (first season played, the age category they started
    in, how many distinct clubs/teams they've ever appeared for, seasons
    played X/Y) need every fichajugador-covered season's participation
    data, but only ever the same three cheap columns per season
    (player_id, team_id, club_name_raw) plus a competitions.csv join for
    category — build_career_profiles() below, one pass over every season
    regardless of which one the page is showing.
  - Season performance (appearances/goals/cards/captain/goalkeeper counts)
    needs the much heavier match_lineups/match_goals/match_cards
    enrichment (500+ MB/season before trimming, same tables
    team_rosters.py already reads) — build_season_performance() reads
    those for exactly the one season being built, pivoted by player_id
    instead of team_id since this page has no per-team grouping.

150k+ players in 2025-2026 alone rules out one big per-season file (or,
worse, one per-player file) — sharded one JSON per (season, category_base)
under data/all_players_<season>/<category>.json instead, since category is
both a natural size-bounding partition (400 VETERANOS vs 35k CADETE) and
one of the page's own filter dimensions: toggling a category chip fetches
exactly that category's shard, nothing more.

Usage:
    python analysis_scripts/all_players.py
    python analysis_scripts/all_players.py --season 2025-2026 --output-dir reports
"""

import argparse
import json
from pathlib import Path

import pandas as pd

import club_identity as ci
import player_career_v2 as player_career
import rffm_data as data
from club_division_map import CAT_LABEL_ES, CAT_LABEL_RU, CATEGORIES, DIV_LABEL_ES, DIV_LABEL_RU, DIV_ORDER
from site_theme import DATATABLE_CSS, DATATABLE_JS, FONT_LINKS, THEME_INIT_JS, THEME_SWITCH_JS, switch_row_html
from team_cards_v2 import build_club_team_cards, norm_id

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"


def clean(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def build_career_profiles(seasons: list[str]) -> dict[str, dict]:
    """player_id -> {birth_year, seasons: set, first_season, first_cat,
    clubs: set, teams: set}, one pass across every season in `seasons`
    (must be chronologically ascending — list_fichajugador_seasons()
    already returns them that way — since "first season seen" is used
    directly as "first season played" rather than min()-ing afterward).
    Deliberately a separate read from player_career.compute_career_index()
    even though both scan the same file: that function stays cheap
    (player_id + birth_year only) for its two existing callers
    (team_rosters.py, player_cards.py's "Сезонов" stat), which don't need
    club/team/category — adding those columns to every call there would
    slow down two call sites that only ever wanted the cheap version."""
    profiles: dict[str, dict] = {}
    for season in seasons:
        part = data.read_table("player_competition_participation", season=season)[
            ["player_id", "team_id", "club_name_raw", "competition_id"]]
        players = data.read_table("players_by_season", season=season)
        comps = data.read_table("competitions", season=season)
        if part.empty or players.empty or comps.empty:
            continue
        players = players[["player_id", "birth_year"]]
        comps = comps[["competition_id", "category_base"]]
        pid_to_birth = dict(zip(players["player_id"], players["birth_year"]))
        part = part.merge(comps, on="competition_id", how="left")
        for row in part.itertuples(index=False):
            pid = row.player_id
            if not pid:
                continue
            is_new = pid not in profiles
            p = profiles.setdefault(pid, {
                "birth_year": None, "seasons": set(), "first_season": None,
                "first_cat": None, "clubs": set(), "teams": set(),
            })
            p["seasons"].add(season)
            if is_new:
                p["first_season"] = season
                p["first_cat"] = clean(row.category_base)
            if not p["birth_year"]:
                by = pid_to_birth.get(pid)
                if by and str(by).strip():
                    p["birth_year"] = str(by).strip()
            tid = norm_id(row.team_id)
            if tid:
                p["teams"].add(tid)
                club_id = ci.resolve(tid)
                if club_id is not None:
                    p["clubs"].add(club_id)
    return profiles


CARD_LABEL = {"amarilla": "yc", "roja": "rc", "doble_amarilla": "dyc", "doble amarilla": "dyc"}


def build_season_performance(season: str) -> dict[str, dict]:
    """player_id -> appearance/goal/card/captain/goalkeeper counts, summed
    across every team that player appeared for this season (this page has
    no per-team column, unlike team_card.html's roster, so there's no
    reason to key by team_id the way team_rosters.py does) — same source
    tables, one pass per category, matched to a lineup appearance via
    (match_id, player_id) rather than needing team_id at all. Also keeps
    the raw set of match_ids each player appeared in ("mids") — not
    serialized itself, but what build_season_all_players() needs to split
    a team's results into "matches with this player" vs "without" for the
    result-influence columns below."""
    categories = data.list_categories("match_lineups", season)
    perf: dict[str, dict] = {}

    def entry(pid: str) -> dict:
        return perf.setdefault(pid, {"apps": 0, "starts": 0, "goals": 0, "yc": 0, "rc": 0, "dyc": 0, "cap": 0, "gk": 0,
                                      "mids": set()})

    for cat in categories:
        lineup_keys: set[tuple[str, str]] = set()
        lu = data.read_table("match_lineups", season=season, category=cat)
        for row in lu.itertuples(index=False):
            pid, mid = row.player_id, row.match_id
            if not pid or not mid:
                continue
            e = entry(pid)
            e["apps"] += 1
            e["mids"].add(mid)
            if row.is_starter == "True":
                e["starts"] += 1
            if row.is_captain == "True":
                e["cap"] += 1
            if row.is_goalkeeper == "True":
                e["gk"] += 1
            lineup_keys.add((mid, pid))

        goals = data.read_table("match_goals", season=season, category=cat)
        if not goals.empty:
            for row in goals.itertuples(index=False):
                if (row.match_id, row.player_id) in lineup_keys:
                    perf[row.player_id]["goals"] += 1

        cards = data.read_table("match_cards", season=season, category=cat)
        if not cards.empty:
            for row in cards.itertuples(index=False):
                key = (row.match_id, row.player_id)
                if key not in lineup_keys:
                    continue
                field = CARD_LABEL.get(clean(row.card_type_label))
                if field:
                    perf[row.player_id][field] += 1
    return perf


def _pts(result: str | None) -> int | None:
    return {"W": 3, "D": 1, "L": 0}.get(result)


def _is_zero(v: str | None) -> bool:
    if v is None:
        return False
    try:
        return float(v) == 0
    except ValueError:
        return False


def compute_result_influence(team_matches: list[dict], played_mids: set[str]) -> dict:
    """Plus/minus, football-style: this team's points-per-game in the
    finished matches this player appeared in, vs. the finished matches of
    the same team he didn't — the "does the team do better with him on the
    pitch" question, using only presence + final score, so it works
    identically for a striker or a holding midfielder who never touches
    the scoresheet. `nw`/`nwo` (sample sizes) travel with the numbers on
    purpose: a player who starts every match leaves a "without him" sample
    of 1-2 games, and a delta computed off that is noise, not signal — the
    page shows N alongside the number rather than hiding it. `csw` (clean
    sheets while he played) is the same idea aimed at defensive
    contribution specifically, since goals only capture attackers."""
    finished = [m for m in team_matches if m.get("status") == "finished"]
    with_ = [m for m in finished if m.get("match_id") in played_mids]
    without = [m for m in finished if m.get("match_id") not in played_mids]

    def ppg(ms: list[dict]) -> float | None:
        vals = [p for p in (_pts(m.get("result")) for m in ms) if p is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    csw = sum(1 for m in with_ if _is_zero(m.get("sa")))
    return {"pw": ppg(with_), "pwo": ppg(without), "nw": len(with_), "nwo": len(without), "csw": csw}


def build_season_all_players(season: str, profiles: dict[str, dict], all_seasons: list[str],
                              coverage: dict[tuple[str, str], str]) -> dict[str, list[dict]]:
    part = data.read_table("player_competition_participation", season=season)
    players = data.read_table("players_by_season", season=season)
    comps = data.read_table("competitions", season=season)
    comp_meta = comps.set_index("competition_id")[["category_base", "division_level"]]
    part = part.join(comp_meta, on="competition_id")

    pid_to_name = dict(zip(players["player_id"], players["player_name"]))
    pid_to_birth = dict(zip(players["player_id"], players["birth_year"]))

    # club_teams (club_id -> {team_id: {..., "matches": [...]}}) still needed
    # below for the result-influence match list; club_id/name/slug now come
    # from club_identity.py, not from this row's free-text club_name_raw
    # (which disagrees with teams.csv's spelling often enough to matter).
    club_teams = build_club_team_cards(season)
    names = ci.club_display_names()
    slugs = ci.club_slugs()

    perf = build_season_performance(season)

    # One representative registration per player for this season's
    # club/team/category/division columns — a dual-registered player's
    # other rows aren't dropped, just not the one shown here (this page
    # already surfaces "clubs ever"/"teams ever" as their own columns;
    # per-row detail for a specific player lives on player_card.html).
    current: dict[str, dict] = {}
    for row in part.itertuples(index=False):
        pid = row.player_id
        if not pid or pid in current:
            continue
        tid = norm_id(row.team_id)
        club_id = ci.resolve(tid)
        club = names.get(club_id) if club_id is not None else None
        current[pid] = {
            "team": clean(row.team), "team_id": clean(row.team_id),
            "club": club, "club_slug": slugs.get(club_id) if club_id is not None else None,
            "cat": clean(getattr(row, "category_base", None)) or "OTHER",
            "div": clean(getattr(row, "division_level", None)) or "OTHER",
        }

    shards: dict[str, list[dict]] = {}
    for pid, cur in current.items():
        prof = profiles.get(pid, {})
        stats = perf.get(pid, {})
        sx, sy, su = player_career.seasons_ratio(
            prof.get("birth_year"), prof.get("seasons", set()), all_seasons, coverage)

        # Result influence needs the player's *current* team's full match
        # list (build_club_team_cards() already built it above for the
        # club-slug lookup) split by whether match_lineups puts this player
        # in that specific match — see compute_result_influence()'s
        # docstring for why this, not goals, is the metric that also works
        # for a defender/midfielder who never scores.
        cur_tid = norm_id(cur["team_id"])
        team_matches = club_teams.get(ci.resolve(cur_tid), {}).get(cur_tid, {}).get("matches", [])
        infl = compute_result_influence(team_matches, stats.get("mids", set()))

        rec = {
            "id": pid, "n": pid_to_name.get(pid) or pid, "by": clean(pid_to_birth.get(pid)),
            "cat": cur["cat"], "div": cur["div"],
            "club": cur["club"], "cs": cur["club_slug"], "team": cur["team"], "tid": cur["team_id"],
            "fs": prof.get("first_season"), "fc": prof.get("first_cat"),
            "ncl": len(prof.get("clubs", ())), "nte": len(prof.get("teams", ())),
            "sx": sx, "sy": sy, "su": su,
            "apps": stats.get("apps", 0), "starts": stats.get("starts", 0), "goals": stats.get("goals", 0),
            "yc": stats.get("yc", 0), "rc": stats.get("rc", 0), "dyc": stats.get("dyc", 0),
            "cap": stats.get("cap", 0), "gk": stats.get("gk", 0),
            "pw": infl["pw"], "pwo": infl["pwo"], "nw": infl["nw"], "nwo": infl["nwo"], "csw": infl["csw"],
        }
        shards.setdefault(cur["cat"], []).append(rec)
    return shards


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    all_seasons = player_career.list_fichajugador_seasons()
    build_seasons = seasons or all_seasons
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "all_players.html").write_text(build_html(all_seasons), encoding="utf-8")

    print(f"Computing career profiles across {len(all_seasons)} season(s)...")
    profiles = build_career_profiles(all_seasons)
    coverage = player_career.load_fichajugador_coverage()
    print(f"  {len(profiles)} distinct players")

    for season in build_seasons:
        if season not in data.list_seasons("player_competition_participation"):
            print(f"Skipping all-players for {season}: no participation data")
            continue
        print(f"Building all-players data for season {season}")
        shards = build_season_all_players(season, profiles, all_seasons, coverage)
        data_dir = out_dir / "data" / f"all_players_{season}"
        data_dir.mkdir(parents=True, exist_ok=True)
        for cat, records in shards.items():
            (data_dir / f"{cat}.json").write_text(
                json.dumps(records, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                encoding="utf-8")
        total = sum(len(r) for r in shards.values())
        print(f"  {total} players across {len(shards)} categories written to {data_dir}")


I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; todos los jugadores",
    "back": "&larr; Mapa de clubes",
    "nav_clubs": "Todos los clubes", "nav_teams": "Todos los equipos", "nav_players": "Todos los jugadores",
    "h1": "Todos los jugadores",
    "lede": "Una fila por jugador de la temporada elegida arriba. Marca las categorías/divisiones que "
            "quieras ver — cada categoría se carga por separado, así que activar más tarda un poco más. "
            "Haz clic en ▾ de cualquier columna para ordenar/filtrar, como en Excel.",
    "h_howto": "Cómo encontrar buenos jugadores",
    "how1": "La categoría es obligatoria — sin ella la tabla queda vacía (las categorías grandes tienen "
            "decenas de miles de jugadores, así que nada se carga por defecto). La división se puede "
            "acotar de entrada a las ligas más altas.",
    "how2": "<b>¿Buscas un goleador?</b> Acota primero «División» a las ligas más altas — los goles no "
            "son comparables entre divisiones, el máximo goleador de una división floja no es "
            "necesariamente bueno. Después ordena «Goles» o «Goles/partido» de mayor a menor — la "
            "columna «Partidos» al lado muestra sobre qué muestra se calcula.",
    "how3": "<b>¿El jugador no marca (defensa/centrocampista)?</b> Mira «Influencia (Δ)» — la diferencia "
            "de puntos del equipo por partido con él en el campo y sin él — y «% imbatido» — con qué "
            "frecuencia el equipo no encaja cuando juega él. Ambas cifras muestran entre paréntesis N "
            "— partidos sin/con él; con N=1&ndash;2 la cifra es ruido, no una señal fiable.",
    "how4": "«Capitán» es una señal adicional, no estricta: los entrenadores suelen dar el brazalete al "
            "jugador de más confianza. «Clubes»/«Equipos» no habla de nivel directamente — mejor mirarlo "
            "junto con la división: pasar a una división más fuerte suele decir más que el número de "
            "cambios en sí.",
    "lbl_season": "Temporada",
    "lbl_cats": "Categoría", "btn_all1": "Todas", "btn_none1": "Ninguna",
    "lbl_divs": "División", "btn_all2": "Todas", "btn_none2": "Ninguna",
    "searchPh": "Buscar jugador…",
    "loading": "Cargando…", "noResults": "Sin resultados.", "pickCat": "Elige al menos una categoría arriba.",
    "th_name": "Jugador", "th_by": "Año nac.", "th_cat": "Categoría", "th_div": "División",
    "th_club": "Club", "th_team": "Equipo", "th_fs": "Año inicio", "th_fc": "Categoría inicio",
    "th_ncl": "Clubes", "th_nte": "Equipos", "th_seasons": "Temporadas",
    "th_apps": "Partidos", "th_starts": "Titular", "th_goals": "Goles", "th_gpa": "Goles/partido",
    "th_yc": "A", "th_rc": "R", "th_dyc": "2A", "th_cap": "Capitán", "th_gk": "Portero",
    "th_infl": "Influencia (Δ)", "th_csr": "% imbatido",
    "footer": 'Construido a partir de <code>output/processed/rffm/{player_competition_participation,'
              'match_lineups,match_goals,match_cards}.csv</code>. Ver <code>analysis_scripts/all_players.py</code>.',
}

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — все игроки</title>
%FONT_LINKS%
%THEME_INIT%
<style>
:root{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
    --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
    --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
  }
}
:root[data-theme="dark"]{
  --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
  --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
  --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
}
:root[data-theme="light"]{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
}
*{box-sizing:border-box;}
html,body{margin:0;}
body{ background:var(--bg); color:var(--ink); font-family:'PT Sans', ui-sans-serif, "Helvetica Neue", Arial, sans-serif;
  line-height:1.5; -webkit-font-smoothing:antialiased; }
a{ color:var(--accent); text-decoration:none; } a:hover{ text-decoration:underline; }
/* Full-width, not the ~900-1400px boxed shell the other pages use — those
   are read-first (a report, a career table with a handful of columns);
   this one is a dense 20+ column grid where a centered narrow column just
   forces more horizontal scrolling for no benefit. Prose blocks (lede,
   strategy) opt back into a readable measure via .prose. */
.page{ max-width:none; margin:0; padding:2.25rem 1.5rem 4rem; display:flex; flex-direction:column; gap:1.25rem; }
.prose{max-width:80ch;}
h1{ font-family:'Oswald', ui-sans-serif, "Arial Narrow", "Helvetica Neue", Arial, sans-serif; font-weight:700;
  text-transform:uppercase; letter-spacing:0.01em; text-wrap:balance; margin:0; color:var(--ink); font-size:clamp(1.3rem,2.6vw,1.8rem); line-height:1.2; }
header.masthead{display:flex; flex-direction:column; gap:0.5rem; border-bottom:3px solid var(--ink); padding-bottom:1rem; position:relative;}
.eyebrow{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:var(--accent); }
a.back{font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:var(--accent); text-decoration:none;}
a.back:hover{text-decoration:underline;}
.nav-row{display:flex; gap:1rem; flex-wrap:wrap; font-family:'JetBrains Mono',monospace; font-size:0.76rem;}
.nav-row a{color:var(--ink-soft);} .nav-row a.is-here{color:var(--accent); font-weight:700;}
.lede{color:var(--ink-soft); font-size:0.85rem; max-width:80ch; margin:0;}
.masthead .switch-row{position:absolute; top:0; right:0; display:flex; gap:0.5rem;}
.lang-switch, .theme-switch{ display:inline-flex; border:1px solid var(--line-strong); border-radius:999px; overflow:hidden; }
.lang-opt, .theme-opt{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:0.04em;
  padding:4px 12px; background:var(--surface); color:var(--ink-soft); border:none; cursor:pointer; }
.lang-opt.is-active, .theme-opt.is-active{background:var(--accent); color:#fff;}
.theme-opt{font-size:13px; padding:3px 10px;}

.controls-bar{ display:flex; align-items:center; gap:0.8rem; flex-wrap:wrap; }
.controls-bar select{ font-family:inherit; font-size:0.85rem; padding:0.35rem 0.6rem; border-radius:6px;
  border:1px solid var(--line-strong); background:var(--surface); color:var(--ink); }
.search{ position:relative; flex:1 1 16rem; max-width:22rem; }
.search input{ width:100%; box-sizing:border-box; font-family:inherit; font-size:0.85rem; padding:0.4rem 0.7rem 0.4rem 2.1rem;
  border-radius:999px; border:1px solid var(--line-strong); background:var(--surface); color:var(--ink); }
.search svg{position:absolute; left:0.7rem; top:50%; transform:translateY(-50%); color:var(--ink-faint); pointer-events:none;}
.result-count{ font-family:'JetBrains Mono',monospace; font-size:0.78rem; color:var(--accent); font-weight:700; margin-left:auto; }

.strategy-box{ background:var(--gold-soft); border:1px solid var(--gold); border-left:4px solid var(--gold);
  border-radius:8px; padding:0.7rem 1rem; }
.strategy-box summary{ cursor:pointer; font-family:'Oswald',sans-serif; font-weight:700; text-transform:uppercase;
  font-size:1rem; color:var(--ink); }
.strategy-box[open] summary{margin-bottom:0.5rem;}
.strategy-box ol{margin:0; padding-left:1.3rem; color:var(--ink-soft); font-size:0.85rem; display:flex; flex-direction:column; gap:0.4rem;}
.strategy-box li b{color:var(--ink);}

.filters{ display:flex; flex-direction:column; gap:0.5rem; background:var(--surface); border:1px solid var(--line);
  border-radius:8px; padding:0.7rem 0.9rem; }
.filter-row{ display:flex; align-items:center; gap:0.6rem; flex-wrap:wrap; }
.filter-label{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; font-weight:700; letter-spacing:0.06em;
  text-transform:uppercase; color:var(--ink-soft); min-width:6rem; }
.filter-chips{ display:flex; flex-wrap:wrap; gap:0.35rem; }
.chip{ display:inline-flex; align-items:center; padding:0.24rem 0.6rem; border-radius:999px; font-size:0.78rem; cursor:pointer;
  border:1px solid var(--line-strong); background:var(--bg); color:var(--ink-soft); user-select:none; }
.chip.active{background:var(--accent); border-color:var(--accent); color:#fff;}
.quick-btns{display:flex; gap:0.3rem; margin-left:auto;}
.quick-btns button{ font-family:'JetBrains Mono',monospace; font-size:0.68rem; font-weight:700; padding:0.2rem 0.5rem;
  border-radius:5px; border:1px solid var(--line-strong); background:var(--surface); color:var(--ink-soft); cursor:pointer; }
.quick-btns button:hover{color:var(--accent); border-color:var(--accent);}

.table-shell{ background:var(--surface); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); overflow:hidden; }
.table-scroll{overflow:auto; max-height:75vh;}
table{border-collapse:separate; border-spacing:0; font-size:0.82rem; width:100%;}
thead th{ position:sticky; top:0; z-index:2; background:var(--surface); border-bottom:1px solid var(--line-strong); padding:0.5rem 0.65rem;
  text-align:left; font-size:0.68rem; letter-spacing:0.04em; text-transform:uppercase; color:var(--ink-soft); white-space:nowrap; }
tbody td{ border-bottom:1px solid var(--line); padding:0.42rem 0.65rem; vertical-align:middle; white-space:nowrap; }
tbody tr:last-child td{border-bottom:none;}
tbody tr:hover td{background:var(--accent-soft);}
td.name-cell{font-weight:600; color:var(--ink);}
.tier-chip{ display:inline-block; font-size:0.7rem; font-weight:700; padding:0.08rem 0.45rem; border-radius:999px;
  background:var(--accent-soft); color:var(--accent); white-space:nowrap; }
.uncertain-mark{color:var(--gold); cursor:help;}
.n-note{color:var(--ink-faint); font-size:0.85em;}
.empty-state{padding:2.5rem; text-align:center; color:var(--ink-faint);}
footer.note{font-size:0.78rem; color:var(--ink-soft); max-width:90ch;}
%DATATABLE_CSS%
</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    %SWITCH_ROW%
    <a class="back" href="club_division_map.html" data-i18n="back">&larr; Карта клубов</a>
    <nav class="nav-row">
      <a href="../all_clubs.html" data-i18n="nav_clubs">Все клубы</a>
      <a href="all_teams.html" data-i18n="nav_teams">Все команды</a>
      <a class="is-here" data-i18n="nav_players">Все игроки</a>
    </nav>
    <span class="eyebrow" data-i18n="eyebrow">RFFM (Мадрид) &middot; все игроки</span>
    <h1 data-i18n="h1">Все игроки</h1>
    <p class="lede prose" data-i18n="lede">
      Одна строка — один игрок выбранного вверху сезона. Отметьте нужные категории/дивизионы — каждая
      категория грузится отдельно, поэтому включение новой займёт момент. Клик по ▾ в заголовке любой
      колонки — сортировка и фильтр, как в Excel.
    </p>
  </header>

  <details class="strategy-box" open>
    <summary data-i18n="h_howto">Как искать сильных игроков</summary>
    <ol class="prose">
      <li data-i18n="how1">
        Категория обязательна — без неё таблица пуста (крупные категории — десятки тысяч игроков, поэтому
        ничего не подгружается по умолчанию). Дивизион сразу можно сузить до топовых.
      </li>
      <li data-i18n="how2">
        <b>Ищете бомбардира?</b> Сначала сузьте «Дивизион» до топовых лиг — голы не сравнимы между дивизионами,
        лучший снайпер слабого дивизиона не обязательно силён. Затем сортируйте «Голы» или «Гол/явка» по убыванию —
        колонка «Явок» рядом показывает, на какой выборке матчей построен результат.
      </li>
      <li data-i18n="how3">
        <b>Игрок не забивает (защита/полузащита)?</b> Смотрите «Влияние (Δ)» — разница очков команды за
        игру, когда он на поле, и когда его нет — и «% на ноль» — как часто команда не пропускает при
        нём. У обеих цифр в скобках указано N — число матчей без него/с ним; при N=1&ndash;2 цифре
        доверять не стоит, это шум, а не сигнал.
      </li>
      <li data-i18n="how4">
        «Капитан» — дополнительный, не строгий сигнал: тренеры обычно доверяют повязку самому надёжному
        игроку команды. «Клубов»/«Команд» — это не про силу напрямую, а про траекторию: смотрите вместе с
        дивизионом — переход в более сильный дивизион чаще говорит о таланте, чем само число переходов.
      </li>
    </ol>
  </details>

  <div class="controls-bar">
    <label class="filter-label" data-i18n="lbl_season" style="min-width:auto;">Сезон</label>
    <select id="seasonSelect"></select>
    <div class="search">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input type="text" id="searchBox" placeholder="Поиск игрока…" autocomplete="off">
    </div>
    <span class="result-count" id="resultCount"></span>
  </div>

  <div class="filters">
    <div class="filter-row">
      <span class="filter-label" data-i18n="lbl_cats">Категория</span>
      <div class="filter-chips" id="chips-cats"></div>
      <div class="quick-btns">
        <button type="button" id="catsAll" data-i18n="btn_all1">Все</button>
        <button type="button" id="catsNone" data-i18n="btn_none1">Нет</button>
      </div>
    </div>
    <div class="filter-row">
      <span class="filter-label" data-i18n="lbl_divs">Дивизион</span>
      <div class="filter-chips" id="chips-divs"></div>
      <div class="quick-btns">
        <button type="button" id="divsAll" data-i18n="btn_all2">Все</button>
        <button type="button" id="divsNone" data-i18n="btn_none2">Нет</button>
      </div>
    </div>
  </div>

  <div class="table-shell">
    <div class="table-scroll">
      <table id="playersTable" class="dtable">
        <thead><tr>
          <th data-key="n" data-type="text"><span data-i18n="th_name">Игрок</span></th>
          <th data-key="by" data-type="number"><span data-i18n="th_by">Год рожд.</span></th>
          <th data-key="cat" data-type="text"><span data-i18n="th_cat">Категория</span></th>
          <th data-key="div" data-type="text"><span data-i18n="th_div">Дивизион</span></th>
          <th data-key="club" data-type="text"><span data-i18n="th_club">Клуб</span></th>
          <th data-key="team" data-type="text"><span data-i18n="th_team">Команда</span></th>
          <th data-key="fs" data-type="number"><span data-i18n="th_fs">Год старта</span></th>
          <th data-key="fc" data-type="text"><span data-i18n="th_fc">Категория старта</span></th>
          <th data-key="ncl" data-type="number"><span data-i18n="th_ncl">Клубов</span></th>
          <th data-key="nte" data-type="number"><span data-i18n="th_nte">Команд</span></th>
          <th data-key="seasons" data-type="number" title="Сыграно сезонов из тех, на которые игрок проходит по возрасту"><span data-i18n="th_seasons">Сезонов</span></th>
          <th data-key="apps" data-type="number"><span data-i18n="th_apps">Явок</span></th>
          <th data-key="starts" data-type="number"><span data-i18n="th_starts">Старт</span></th>
          <th data-key="goals" data-type="number"><span data-i18n="th_goals">Голы</span></th>
          <th data-key="gpa" data-type="number" title="Голы, делённые на явки"><span data-i18n="th_gpa">Гол/явка</span></th>
          <th data-key="yc" data-type="number" title="Жёлтые карточки"><span data-i18n="th_yc">Ж</span></th>
          <th data-key="rc" data-type="number" title="Красные карточки"><span data-i18n="th_rc">К</span></th>
          <th data-key="dyc" data-type="number" title="Вторые жёлтые"><span data-i18n="th_dyc">2Ж</span></th>
          <th data-key="cap" data-type="number"><span data-i18n="th_cap">Капитан</span></th>
          <th data-key="gk" data-type="number"><span data-i18n="th_gk">Вратарь</span></th>
          <th data-key="infl" data-type="number" title="Очков/игру команды с игроком минус очков/игру без него (только по сыгранным матчам его текущей команды)"><span data-i18n="th_infl">Влияние (Δ)</span></th>
          <th data-key="csr" data-type="number" title="Доля матчей без пропущенных мячей, когда этот игрок был на поле"><span data-i18n="th_csr">% на ноль</span></th>
        </tr></thead>
        <tbody id="playersBody"><tr><td class="empty-state" colspan="22" data-i18n="pickCat">Отметьте хотя бы одну категорию выше.</td></tr></tbody>
      </table>
    </div>
  </div>

  <footer class="note" data-i18n="footer">Построено из <code>output/processed/rffm/{player_competition_participation,
    match_lineups,match_goals,match_cards}.csv</code>. См. <code>analysis_scripts/all_players.py</code>.</footer>
</div>
<script>
const SEASONS = %SEASONS_JSON%;
const CAT_ORDER = %CAT_ORDER_JSON%;
const DIV_ORDER = %DIV_ORDER_JSON%;
const CAT_LABEL_RU = %CAT_LABEL_RU_JSON%;
const CAT_LABEL_ES = %CAT_LABEL_ES_JSON%;
const DIV_LABEL_RU = %DIV_LABEL_RU_JSON%;
const DIV_LABEL_ES = %DIV_LABEL_ES_JSON%;
const LANG = {
  ru: { loading: 'Загрузка…', noResults: 'Нет результатов.', pickCat: 'Отметьте хотя бы одну категорию выше.',
        uncertain: 'В окне сезонов есть недокрученные категории — пропуск может быть не реальным, а просто ещё не собранными данными.',
        lowSample: 'Матчей без этого игрока меньше трёх — разница на такой выборке это шум, не сигнал.' },
  es: { loading: 'Cargando…', noResults: 'Sin resultados.', pickCat: 'Elige al menos una categoría arriba.',
        uncertain: 'Alguna temporada de la ventana no está completamente recolectada — un hueco puede ser solo datos pendientes, no real.',
        lowSample: 'Menos de tres partidos sin este jugador — la diferencia con esa muestra es ruido, no una señal fiable.' },
};
const DT_LABELS = {
  ru: { selectAll: '(все)', search: 'Поиск…', apply: 'Применить', clear: 'Сбросить', empty: '(пусто)' },
  es: { selectAll: '(todos)', search: 'Buscar…', apply: 'Aplicar', clear: 'Restablecer', empty: '(vacío)' },
};
let CURLANG = 'ru';
const STATE = { cats: new Set(), divs: new Set(), seeded: false };
let CUR_SEASON = null;
const SHARD_CACHE = {}; // `${season}/${cat}` -> array of records (or a pending Promise)
let ALL_DIVS = new Set();

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}
function catLabel(c) { return (CURLANG === 'ru' ? CAT_LABEL_RU : CAT_LABEL_ES)[c] || c; }
function divLabel(d) { return (CURLANG === 'ru' ? DIV_LABEL_RU : DIV_LABEL_ES)[d] || d || ''; }

%DATATABLE_JS%

function teamCardUrl(r) {
  if (!(r.cs && r.tid)) return null;
  return `team_card.html?season=${encodeURIComponent(CUR_SEASON)}&club=${encodeURIComponent(r.cs)}&team=${encodeURIComponent(r.tid)}`;
}
function playerCardUrl(r) {
  return `player_card.html?season=${encodeURIComponent(CUR_SEASON)}&player=${encodeURIComponent(r.id)}`;
}
function firstYear(fs) {
  if (!fs) return null;
  const m = /^(\d{4})/.exec(fs);
  return m ? parseInt(m[1], 10) : null;
}

async function fetchCategoryShard(season, cat) {
  const key = `${season}/${cat}`;
  if (!(key in SHARD_CACHE)) {
    SHARD_CACHE[key] = fetch(`data/all_players_${season}/${cat}.json`)
      .then(res => res.ok ? res.json() : [])
      .catch(() => []);
  }
  return SHARD_CACHE[key];
}

function buildChipRow(containerId, kind, items, labelFn, onToggle) {
  const el = document.getElementById(containerId);
  el.innerHTML = '';
  items.forEach(val => {
    const chip = document.createElement('span');
    chip.className = 'chip' + (STATE[kind].has(val) ? ' active' : '');
    chip.textContent = labelFn(val);
    chip.addEventListener('click', () => {
      if (STATE[kind].has(val)) STATE[kind].delete(val); else STATE[kind].add(val);
      chip.classList.toggle('active', STATE[kind].has(val));
      onToggle();
    });
    el.appendChild(chip);
  });
}

function quickSelect(kind, containerId, allItems, action, onToggle) {
  allItems.forEach(v => { if (action === 'all') STATE[kind].add(v); else STATE[kind].delete(v); });
  [...document.getElementById(containerId).children].forEach((chip, i) => chip.classList.toggle('active', STATE[kind].has(allItems[i])));
  onToggle();
}

function rowHtml(r) {
  const teamUrl = teamCardUrl(r);
  const teamHtml = teamUrl ? `<a href="${teamUrl}">${esc(r.team || '—')}</a>` : esc(r.team || '—');
  const nameUrl = playerCardUrl(r);
  const catText = r.cat && r.cat !== 'OTHER' ? catLabel(r.cat) : '—';
  const divText = r.div && r.div !== 'OTHER' ? divLabel(r.div) : '—';
  const fcText = r.fc && r.fc !== 'OTHER' ? catLabel(r.fc) : '—';
  const fy = firstYear(r.fs);
  let seasonsDisplay = '—', seasonsSort = 0;
  if (r.sy !== null && r.sy !== undefined) {
    seasonsDisplay = `${r.sx}/${r.sy}` + (r.su ? ` <span class="uncertain-mark" title="${esc(LANG[CURLANG].uncertain)}">*</span>` : '');
    seasonsSort = r.sy ? r.sx / r.sy : r.sx;
  } else {
    seasonsDisplay = String(r.sx || 0);
    seasonsSort = r.sx || 0;
  }

  // Goals/appearance — a straight ratio of two columns already on the row,
  // nothing new to fetch.
  const gpa = r.apps ? r.goals / r.apps : null;
  const gpaDisplay = gpa === null ? '—' : gpa.toFixed(2);

  // Result influence: team's points/game with this player on the pitch
  // minus points/game without him (see compute_result_influence() in
  // all_players.py) — works for a defender/midfielder who never scores,
  // unlike goals. nwo (matches without him) rides along as a visible
  // reliability flag rather than being hidden: a player who starts every
  // match leaves a 1-2 game "without him" sample, and the delta off that
  // is noise, not signal.
  let inflDisplay = '—', inflSort = '';
  if (r.pw !== null && r.pw !== undefined && r.pwo !== null && r.pwo !== undefined) {
    const delta = r.pw - r.pwo;
    inflSort = delta;
    const lowN = r.nwo < 3;
    inflDisplay = `${delta >= 0 ? '+' : ''}${delta.toFixed(2)} <span class="n-note">(N=${r.nwo})</span>` +
      (lowN ? ` <span class="uncertain-mark" title="${esc(LANG[CURLANG].lowSample)}">*</span>` : '');
  }

  // Same with/without idea aimed specifically at defensive contribution —
  // clean-sheet rate in the matches he played.
  const csr = r.nw ? (r.csw / r.nw * 100) : null;
  const csrDisplay = csr === null ? '—' : `${Math.round(csr)}%`;

  return `<tr>
    <td class="name-cell" data-col="n" data-v="${esc(r.n)}"><a href="${nameUrl}">${esc(r.n)}</a></td>
    <td data-col="by" data-v="${r.by || ''}">${esc(r.by || '—')}</td>
    <td data-col="cat" data-v="${esc(catText)}">${esc(catText)}</td>
    <td data-col="div" data-v="${esc(divText)}"><span class="tier-chip">${esc(divText)}</span></td>
    <td data-col="club" data-v="${esc(r.club || '')}">${esc(r.club || '—')}</td>
    <td data-col="team" data-v="${esc(r.team || '')}">${teamHtml}</td>
    <td data-col="fs" data-v="${fy || ''}">${fy || '—'}</td>
    <td data-col="fc" data-v="${esc(fcText)}">${esc(fcText)}</td>
    <td data-col="ncl" data-v="${r.ncl || 0}">${r.ncl || 0}</td>
    <td data-col="nte" data-v="${r.nte || 0}">${r.nte || 0}</td>
    <td data-col="seasons" data-v="${seasonsSort}" data-label="${esc(seasonsDisplay.replace(/<[^>]+>/g, ''))}">${seasonsDisplay}</td>
    <td data-col="apps" data-v="${r.apps || 0}">${r.apps || 0}</td>
    <td data-col="starts" data-v="${r.starts || 0}">${r.starts || 0}</td>
    <td data-col="goals" data-v="${r.goals || 0}">${r.goals || 0}</td>
    <td data-col="gpa" data-v="${gpa === null ? '' : gpa}">${gpaDisplay}</td>
    <td data-col="yc" data-v="${r.yc || 0}">${r.yc || '—'}</td>
    <td data-col="rc" data-v="${r.rc || 0}">${r.rc || '—'}</td>
    <td data-col="dyc" data-v="${r.dyc || 0}">${r.dyc || '—'}</td>
    <td data-col="cap" data-v="${r.cap || 0}">${r.cap || '—'}</td>
    <td data-col="gk" data-v="${r.gk || 0}">${r.gk || '—'}</td>
    <td data-col="infl" data-v="${inflSort}" data-label="${esc(inflDisplay.replace(/<[^>]+>/g, ''))}">${inflDisplay}</td>
    <td data-col="csr" data-v="${csr === null ? '' : csr}">${csrDisplay}</td>
  </tr>`;
}

let RENDER_TOKEN = 0;
async function render() {
  const myToken = ++RENDER_TOKEN;
  const tbody = document.getElementById('playersBody');
  const cats = [...STATE.cats];
  if (!cats.length) {
    tbody.innerHTML = `<tr><td class="empty-state" colspan="22">${LANG[CURLANG].pickCat}</td></tr>`;
    document.getElementById('resultCount').textContent = '';
    return;
  }
  tbody.innerHTML = `<tr><td class="empty-state" colspan="22">${LANG[CURLANG].loading}</td></tr>`;
  const shardArrays = await Promise.all(cats.map(cat => fetchCategoryShard(CUR_SEASON, cat)));
  if (myToken !== RENDER_TOKEN) return; // a newer render() started (season/cat changed) while this fetch was in flight

  let rows = [].concat(...shardArrays);
  // Divisions are only known once the shards are in (not fixed like
  // categories), so the division chip row is (re)built here, preserving
  // any divisions still checked from before.
  const seenDivs = [...new Set(rows.map(r => r.div))].sort((a, b) => {
    const ra = DIV_ORDER.indexOf(a), rb = DIV_ORDER.indexOf(b);
    return (ra === -1 ? 999 : ra) - (rb === -1 ? 999 : rb) || String(a).localeCompare(String(b));
  });
  if (!STATE.seeded) { seenDivs.forEach(d => STATE.divs.add(d)); STATE.seeded = true; }
  ALL_DIVS = new Set(seenDivs);
  buildChipRow('chips-divs', 'divs', seenDivs, divLabel, render);

  rows = rows.filter(r => STATE.divs.has(r.div));
  const q = document.getElementById('searchBox').value.trim().toLowerCase();
  if (q) rows = rows.filter(r => (r.n || '').toLowerCase().includes(q));

  document.getElementById('resultCount').textContent = rows.length.toLocaleString();
  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="empty-state" colspan="22">${LANG[CURLANG].noResults}</td></tr>`;
    return;
  }
  rffmInitDataTable(document.getElementById('playersTable'), { labels: DT_LABELS[CURLANG], rows, rowHtml });
}

function initCategoryChips() {
  buildChipRow('chips-cats', 'cats', CAT_ORDER, catLabel, render);
}
document.getElementById('catsAll').addEventListener('click', () => quickSelect('cats', 'chips-cats', CAT_ORDER, 'all', render));
document.getElementById('catsNone').addEventListener('click', () => quickSelect('cats', 'chips-cats', CAT_ORDER, 'none', render));
document.getElementById('divsAll').addEventListener('click', () => quickSelect('divs', 'chips-divs', [...ALL_DIVS], 'all', render));
document.getElementById('divsNone').addEventListener('click', () => quickSelect('divs', 'chips-divs', [...ALL_DIVS], 'none', render));
document.getElementById('searchBox').addEventListener('input', render);
document.getElementById('seasonSelect').addEventListener('change', function () {
  CUR_SEASON = this.value;
  STATE.divs = new Set(); STATE.seeded = false;
  render();
});

document.getElementById('seasonSelect').innerHTML = SEASONS.map(s => `<option value="${s}">${s}</option>`).join('');
document.getElementById('seasonSelect').value = SEASONS[SEASONS.length - 1];
CUR_SEASON = SEASONS[SEASONS.length - 1];
// Deliberately starts with no category checked, not DEFAULT_CATEGORIES
// like club_division_map.py — the biggest categories here run 30k+ rows
// of an 18-column table (unlike that page's compact division matrix), so
// a "just show something" default risks a multi-second first paint for
// everyone; better to make the visitor's own filter pick the one thing
// that decides how much the browser has to render.
initCategoryChips();
render();

const I18N_ES = %I18N_ES_JSON%;
document.querySelectorAll('.lang-opt').forEach(function (btn) {
  btn.addEventListener('click', function () {
    CURLANG = btn.getAttribute('data-lang-btn');
    document.querySelectorAll('.lang-opt').forEach(function (b) { b.classList.toggle('is-active', b === btn); });
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      if (el.dataset.ru === undefined) el.dataset.ru = el.innerHTML;
      if (CURLANG === 'ru') el.innerHTML = el.dataset.ru;
      else if (Object.prototype.hasOwnProperty.call(I18N_ES, el.dataset.i18n)) el.innerHTML = I18N_ES[el.dataset.i18n];
    });
    const searchBox = document.getElementById('searchBox');
    if (searchBox.dataset.ru === undefined) searchBox.dataset.ru = searchBox.placeholder;
    searchBox.placeholder = CURLANG === 'ru' ? searchBox.dataset.ru : (I18N_ES.searchPh || searchBox.placeholder);
    document.documentElement.lang = CURLANG;
    initCategoryChips();
    render();
  });
});
try { if (localStorage.getItem('rffm_lang') === 'es') document.querySelector('.lang-opt[data-lang-btn="es"]').click(); } catch (e) {}

%THEME_SWITCH_JS%
</script>
</body>
</html>
"""


def build_html(seasons: list[str]) -> str:
    return (HTML
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%THEME_INIT%", THEME_INIT_JS)
            .replace("%SWITCH_ROW%", switch_row_html())
            .replace("%SEASONS_JSON%", json.dumps(seasons))
            .replace("%CAT_ORDER_JSON%", json.dumps(CATEGORIES))
            .replace("%DIV_ORDER_JSON%", json.dumps(DIV_ORDER))
            .replace("%CAT_LABEL_RU_JSON%", json.dumps(CAT_LABEL_RU, ensure_ascii=False))
            .replace("%CAT_LABEL_ES_JSON%", json.dumps(CAT_LABEL_ES, ensure_ascii=False))
            .replace("%DIV_LABEL_RU_JSON%", json.dumps(DIV_LABEL_RU, ensure_ascii=False))
            .replace("%DIV_LABEL_ES_JSON%", json.dumps(DIV_LABEL_ES, ensure_ascii=False))
            .replace("%I18N_ES_JSON%", json.dumps(I18N_ES, ensure_ascii=False))
            .replace("%THEME_SWITCH_JS%", THEME_SWITCH_JS)
            .replace("%DATATABLE_CSS%", DATATABLE_CSS)
            .replace("%DATATABLE_JS%", DATATABLE_JS))


def main():
    parser = argparse.ArgumentParser(description="RFFM all-players browser")
    parser.add_argument("--season", default=None, help="build only this season's data (default: every fichajugador-covered season)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


if __name__ == "__main__":
    main()
