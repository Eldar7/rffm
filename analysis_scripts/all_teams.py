#!/usr/bin/env python3
"""
All-teams browser: every team-in-competition entry this project has data
for, one row per (team, competition) this season, with the same kind of
standings/quality/discipline metrics team_card.html already computes for
one team at a time, brought together into one sortable/filterable table —
this project's all_players.py, but for teams instead of players.

Row unit is (season, team_id, competition_id) rather than (season, team_id):
a team registered in both its league and a cup gets one row per competition
(mirrors team_card.html's own "one card per competition_id" collapse of a
cup's several knockout-round group_ids — see team_cards.build_club_team_cards()'s
docstring for why competition_id, not group_id, is the right granularity).
Standings-table numbers (played/W-D-L/goals/points) are NOT read from
standings.csv directly — they're recomputed from each competition's own
match list (build_club_team_cards() already has it) via the same W/D/L/points
logic team_card.html's own compRecord() uses client-side, because knockout
rounds routinely have no standings.csv row at all while still having real
match results; this way every competition_id gets a consistent record
regardless of whether the federation published a table for it.

Squad size / roster stability / discipline (cards) are the one thing that
needs a second, heavier pass over match_lineups/match_cards (same tables
all_players.py and team_rosters.py already read) — computed once per team
for the WHOLE season (not scoped to one competition, since a team fields
essentially the same squad across its league + cup fixtures) and reused
across however many competition-rows that team has.

Unlike all_players.py, there's no need to shard by category: team/club
counts run in the low thousands per season (vs. 150k+ players), small
enough to ship as one JSON per season — data/all_teams_<season>.json,
{"rows": [...], "clubs": {club_name: {web, loc, prov}}}. all_clubs.py
reads this SAME file client-side and aggregates it by club instead of
shipping a second, redundant dataset — see that module's docstring.

Usage:
    python analysis_scripts/all_teams.py
    python analysis_scripts/all_teams.py --season 2025-2026 --output-dir reports
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from club_division_map import (CAT_LABEL_ES, CAT_LABEL_RU, CATEGORIES, DIV_LABEL_ES, DIV_LABEL_RU, DIV_ORDER,
                                GT_SHORT, TIER_OF)
from site_theme import DATATABLE_CSS, DATATABLE_JS, FONT_LINKS, THEME_INIT_JS, THEME_SWITCH_JS, club_slug_map, switch_row_html
from team_cards import build_club_team_cards, list_seasons, norm_id

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"


def clean(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


CARD_LABEL = {"amarilla": "yc", "roja": "rc", "doble_amarilla": "dyc", "doble amarilla": "dyc"}


def build_team_lineup_stats(season: str) -> dict[str, dict]:
    """team_id -> {"sq": unique players fielded, "st": roster-stability
    0..1 or None, "yc"/"rc"/"dyc": card counts}, aggregated across every
    category's match_lineups/match_cards for the whole season (not scoped
    to a single competition — see module docstring). "st" is the same
    average-Jaccard-overlap-of-consecutive-starting-XIs formula
    team_card.html's computeStability() uses client-side for one team;
    computed here once per team instead so a season-wide table doesn't
    need to fetch and recompute it 1000+ times in the browser."""
    d = BASE / season
    lineups_dir = d / "match_lineups"
    matches_path = d / "matches.csv"
    if not lineups_dir.exists() or not matches_path.exists():
        return {}
    m = pd.read_csv(matches_path, dtype=str, usecols=["match_id", "match_date", "status"])
    # A missing match_date reads back as float NaN even under dtype=str (pandas'
    # universal missing-value marker) — NaN is truthy in Python, so the `or`
    # fallback below wouldn't catch it and a NaN sort key would collide with
    # the str ones from every other match. Coerce to None here so it does.
    mid_to_date = {mid: (date if isinstance(date, str) else None)
                   for mid, date in zip(m["match_id"], m["match_date"])}
    mid_to_status = dict(zip(m["match_id"], m["status"]))

    categories = sorted(p.stem for p in lineups_dir.glob("*.csv"))
    players_by_team: dict[str, set[str]] = {}
    starters_by_team_match: dict[str, dict[str, set[str]]] = {}
    cards_by_team: dict[str, dict[str, int]] = {}

    for cat in categories:
        lu = pd.read_csv(lineups_dir / f"{cat}.csv", dtype=str,
                          usecols=["match_id", "team_id", "player_id", "is_starter"])
        for row in lu.itertuples(index=False):
            tid, pid = norm_id(row.team_id), clean(row.player_id)
            if not tid or not pid:
                continue
            players_by_team.setdefault(tid, set()).add(pid)
            if row.is_starter == "True":
                starters_by_team_match.setdefault(tid, {}).setdefault(row.match_id, set()).add(pid)

        cp = d / "match_cards" / f"{cat}.csv"
        if cp.exists():
            cc = pd.read_csv(cp, dtype=str, usecols=["team_id", "card_type_label"])
            for row in cc.itertuples(index=False):
                tid = norm_id(row.team_id)
                if not tid:
                    continue
                field = CARD_LABEL.get(clean(row.card_type_label))
                if not field:
                    continue
                c = cards_by_team.setdefault(tid, {"yc": 0, "rc": 0, "dyc": 0})
                c[field] += 1

    out: dict[str, dict] = {}
    for tid, players in players_by_team.items():
        by_match = starters_by_team_match.get(tid, {})
        ordered = sorted(by_match.items(), key=lambda kv: mid_to_date.get(kv[0]) or "9999-99-99")
        starter_sets = [s for mid, s in ordered if mid_to_status.get(mid) == "finished" and s]
        stability = None
        if len(starter_sets) >= 2:
            total, n = 0.0, 0
            for i in range(1, len(starter_sets)):
                inter = len(starter_sets[i - 1] & starter_sets[i])
                union = len(starter_sets[i - 1] | starter_sets[i])
                if union:
                    total += inter / union
                    n += 1
            stability = round(total / n, 3) if n else None
        cards = cards_by_team.get(tid, {"yc": 0, "rc": 0, "dyc": 0})
        out[tid] = {"sq": len(players), "st": stability, **cards}
    return out


def build_club_meta(season: str) -> dict[str, dict]:
    """club_name_raw -> {web, loc, prov}, from the opt-in clubs.csv
    enrichment (correspondence address, not a stadium — see
    DATA_DICTIONARY.md). Missing entirely for a season that hasn't had
    enrich_clubs.py run, or for a club that crawl never resolved — both
    just mean the caller gets {} for that name and shows a blank."""
    p = BASE / season / "clubs.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p, dtype=str, usecols=["club_name_raw", "portal_web", "locality", "province"])
    out: dict[str, dict] = {}
    for row in df.itertuples(index=False):
        name = clean(row.club_name_raw)
        if not name:
            continue
        out[name] = {"web": clean(row.portal_web), "loc": clean(row.locality), "prov": clean(row.province)}
    return out


def _result_tally(matches: list[dict]) -> dict:
    finished = [m for m in matches if m.get("status") == "finished"]
    w = sum(1 for m in finished if m.get("result") == "W")
    d = sum(1 for m in finished if m.get("result") == "D")
    l = sum(1 for m in finished if m.get("result") == "L")
    gf = sum(int(float(m["sf"])) for m in finished if m.get("sf") is not None)
    ga = sum(int(float(m["sa"])) for m in finished if m.get("sa") is not None)
    return {"pl": len(finished), "w": w, "d": d, "l": l, "gf": gf, "ga": ga, "gd": gf - ga, "pts": w * 3 + d}


def build_team_rows(season: str) -> list[dict]:
    d = BASE / season
    comps = pd.read_csv(d / "competitions.csv", dtype=str, usecols=["competition_id", "category_base"])
    comp_id_to_cat = dict(zip(comps["competition_id"], comps["category_base"]))

    club_teams = build_club_team_cards(season)
    slugs = club_slug_map(sorted(club_teams.keys()))
    lineup_stats = build_team_lineup_stats(season)

    rows: list[dict] = []
    for club, teams_of_club in club_teams.items():
        slug = slugs[club]
        for tid, team_rec in teams_of_club.items():
            ls = lineup_stats.get(tid, {})
            for comp_id, comp in team_rec["competitions"].items():
                comp_matches = [m for m in team_rec["matches"] if m["comp_id"] == comp_id]
                tally = _result_tally(comp_matches)
                if not tally["pl"]:
                    continue  # nothing finished in this competition yet — nothing to rank
                standing = comp.get("standing") or {}
                rows.append({
                    "club": club, "slug": slug,
                    "tid": tid, "team": team_rec["name"],
                    "cat": clean(comp_id_to_cat.get(comp_id)) or "OTHER",
                    "div": clean(comp.get("division_level")) or "OTHER",
                    "gt": clean(comp.get("gt")),
                    "comp": clean(comp.get("comp")), "grp": clean(comp.get("grp")),
                    "pos": clean(standing.get("position")), "size": standing.get("size"),
                    "sq": ls.get("sq"), "st": ls.get("st"),
                    "yc": ls.get("yc", 0), "rc": ls.get("rc", 0), "dyc": ls.get("dyc", 0),
                    **tally,
                })
    return rows


I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; todos los equipos",
    "back": "&larr; Mapa de clubes",
    "nav_clubs": "Todos los clubes", "nav_teams": "Todos los equipos", "nav_players": "Todos los jugadores",
    "h1": "Todos los equipos",
    "lede": "Una fila por equipo y competición de la temporada elegida arriba (liga y copa cuentan por "
            "separado). Marca las categorías/divisiones que quieras ver. Haz clic en ▾ de cualquier columna "
            "para ordenar/filtrar, como en Excel.",
    "h_howto": "Cómo encontrar buenos equipos",
    "how1": "Los puntos/goles NO son comparables entre divisiones — el líder de una división floja no es "
            "necesariamente fuerte. Acota primero «División» a las ligas más altas antes de comparar números.",
    "how2": "Dentro de la misma división, ordena «Puntos/partido» o «Diferencia/partido» de mayor a menor — "
            "más estable frente a rachas cortas que los puntos totales, que dependen de cuántos partidos ya "
            "se jugaron. «Lugar» muestra la posición real dentro de su grupo.",
    "how3": "«Plantilla»/«Estabilidad» son señales secundarias sobre el equipo en sí (no sobre lo difícil "
            "que es su competición): una plantilla muy corta o un once que cambia partido a partido pueden "
            "anticipar una caída de rendimiento aunque los números de ahora mismo se vean bien.",
    "lbl_season": "Temporada",
    "lbl_cats": "Categoría", "btn_all1": "Todas", "btn_none1": "Ninguna",
    "lbl_divs": "División", "btn_all2": "Todas", "btn_none2": "Ninguna",
    "searchPh": "Buscar club o equipo…",
    "loading": "Cargando…", "noResults": "Sin resultados.",
    "th_club": "Club", "th_team": "Equipo", "th_cat": "Categoría", "th_div": "División", "th_gt": "Tipo",
    "th_comp": "Competición",
    "th_pl": "PJ", "th_w": "G", "th_d": "E", "th_l": "P",
    "th_gf": "GF", "th_ga": "GC", "th_gd": "DG", "th_pts": "Pts",
    "th_ppg": "Ptos/partido", "th_gdpg": "Dif/partido", "th_pos": "Lugar",
    "th_sq": "Plantilla", "th_st": "Estabilidad",
    "th_yc": "A", "th_rc": "R", "th_dyc": "2A",
    "footer": 'Construido a partir de <code>output/processed/rffm/{matches,standings,competitions,clubs}.csv</code> '
              'y <code>match_lineups/match_cards</code>. Ver <code>analysis_scripts/all_teams.py</code>.',
}

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — все команды</title>
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
td.comp-cell{max-width:16rem; overflow:hidden; text-overflow:ellipsis;}
.tier-chip{ display:inline-block; font-size:0.7rem; font-weight:700; padding:0.08rem 0.45rem; border-radius:999px;
  background:var(--accent-soft); color:var(--accent); white-space:nowrap; }
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
      <a href="all_clubs.html" data-i18n="nav_clubs">Все клубы</a>
      <a class="is-here" data-i18n="nav_teams">Все команды</a>
      <a href="all_players.html" data-i18n="nav_players">Все игроки</a>
    </nav>
    <span class="eyebrow" data-i18n="eyebrow">RFFM (Мадрид) &middot; все команды</span>
    <h1 data-i18n="h1">Все команды</h1>
    <p class="lede prose" data-i18n="lede">
      Одна строка — команда и соревнование выбранного вверху сезона (лига и кубок считаются отдельно).
      Отметьте нужные категории/дивизионы. Клик по ▾ в заголовке любой колонки — сортировка и фильтр, как в Excel.
    </p>
  </header>

  <details class="strategy-box">
    <summary data-i18n="h_howto">Как искать сильные команды</summary>
    <ol class="prose">
      <li data-i18n="how1">
        Очки/голы НЕ сравнимы между дивизионами — лидер слабого дивизиона не обязательно силён. Сначала
        сузьте «Дивизион» до топовых лиг, прежде чем сравнивать цифры.
      </li>
      <li data-i18n="how2">
        Внутри одного дивизиона сортируйте «Очки/игру» или «Разница/игру» по убыванию — это устойчивее к
        короткой полосе игр, чем сумма очков, которая зависит от того, сколько матчей уже сыграно.
        «Место» показывает реальную позицию в своей группе.
      </li>
      <li data-i18n="how3">
        «Состав»/«Стабильность» — сигналы о самой команде (а не о силе её турнира): очень короткая
        скамейка или стартовый состав, меняющийся от матча к матчу, могут предвещать спад формы даже
        если текущие цифры выглядят хорошо.
      </li>
    </ol>
  </details>

  <div class="controls-bar">
    <label class="filter-label" data-i18n="lbl_season" style="min-width:auto;">Сезон</label>
    <select id="seasonSelect"></select>
    <div class="search">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input type="text" id="searchBox" placeholder="Поиск клуба или команды…" autocomplete="off">
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
      <table id="teamsTable" class="dtable">
        <thead><tr>
          <th data-key="club" data-type="text"><span data-i18n="th_club">Клуб</span></th>
          <th data-key="team" data-type="text"><span data-i18n="th_team">Команда</span></th>
          <th data-key="cat" data-type="text"><span data-i18n="th_cat">Категория</span></th>
          <th data-key="div" data-type="text"><span data-i18n="th_div">Дивизион</span></th>
          <th data-key="gt" data-type="text"><span data-i18n="th_gt">Тип</span></th>
          <th data-key="comp" data-type="text"><span data-i18n="th_comp">Соревнование</span></th>
          <th data-key="pl" data-type="number" title="Игр"><span data-i18n="th_pl">И</span></th>
          <th data-key="w" data-type="number" title="Выигрышей"><span data-i18n="th_w">В</span></th>
          <th data-key="d" data-type="number" title="Ничьих"><span data-i18n="th_d">Н</span></th>
          <th data-key="l" data-type="number" title="Поражений"><span data-i18n="th_l">П</span></th>
          <th data-key="gf" data-type="number" title="Забито мячей"><span data-i18n="th_gf">ЗМ</span></th>
          <th data-key="ga" data-type="number" title="Пропущено мячей"><span data-i18n="th_ga">ПМ</span></th>
          <th data-key="gd" data-type="number" title="Разница мячей"><span data-i18n="th_gd">РМ</span></th>
          <th data-key="pts" data-type="number" title="Очков"><span data-i18n="th_pts">О</span></th>
          <th data-key="ppg" data-type="number"><span data-i18n="th_ppg">Очки/игру</span></th>
          <th data-key="gdpg" data-type="number"><span data-i18n="th_gdpg">Разница/игру</span></th>
          <th data-key="pos" data-type="number" title="Место в группе"><span data-i18n="th_pos">Место</span></th>
          <th data-key="sq" data-type="number" title="Число разных игроков в заявках за сезон"><span data-i18n="th_sq">Состав</span></th>
          <th data-key="st" data-type="number" title="Среднее сохранение стартового состава между сыгранными матчами подряд"><span data-i18n="th_st">Стабильность</span></th>
          <th data-key="yc" data-type="number" title="Жёлтые карточки"><span data-i18n="th_yc">Ж</span></th>
          <th data-key="rc" data-type="number" title="Красные карточки"><span data-i18n="th_rc">К</span></th>
          <th data-key="dyc" data-type="number" title="Вторые жёлтые"><span data-i18n="th_dyc">2Ж</span></th>
        </tr></thead>
        <tbody id="teamsBody"><tr><td class="empty-state" colspan="22" data-i18n="loading">Загрузка…</td></tr></tbody>
      </table>
    </div>
  </div>

  <footer class="note" data-i18n="footer">Построено из <code>output/processed/rffm/{matches,standings,competitions,clubs}.csv</code>
    и <code>match_lineups/match_cards</code>. См. <code>analysis_scripts/all_teams.py</code>.</footer>
</div>
<script>
const SEASONS = %SEASONS_JSON%;
const CAT_ORDER = %CAT_ORDER_JSON%;
const DIV_ORDER = %DIV_ORDER_JSON%;
const CAT_LABEL_RU = %CAT_LABEL_RU_JSON%;
const CAT_LABEL_ES = %CAT_LABEL_ES_JSON%;
const DIV_LABEL_RU = %DIV_LABEL_RU_JSON%;
const DIV_LABEL_ES = %DIV_LABEL_ES_JSON%;
const GT_SHORT = %GT_SHORT_JSON%;
const LANG = {
  ru: { loading: 'Загрузка…', noResults: 'Нет результатов.' },
  es: { loading: 'Cargando…', noResults: 'Sin resultados.' },
};
const DT_LABELS = {
  ru: { selectAll: '(все)', search: 'Поиск…', apply: 'Применить', clear: 'Сбросить', empty: '(пусто)' },
  es: { selectAll: '(todos)', search: 'Buscar…', apply: 'Aplicar', clear: 'Restablecer', empty: '(vacío)' },
};
let CURLANG = 'ru';
const STATE = { cats: new Set(CAT_ORDER), divs: new Set(), seeded: false };
let CUR_SEASON = null;
const SEASON_CACHE = {}; // season -> Promise<{rows, clubs}>
let ALL_DIVS = new Set();
let RESTORING = false;

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}
function catLabel(c) { return (CURLANG === 'ru' ? CAT_LABEL_RU : CAT_LABEL_ES)[c] || c; }
function divLabel(d) { return (CURLANG === 'ru' ? DIV_LABEL_RU : DIV_LABEL_ES)[d] || d || ''; }
function gtLabel(g) { return GT_SHORT[g] || g || '—'; }

%DATATABLE_JS%

function teamCardUrl(r) {
  return `team_card.html?season=${encodeURIComponent(CUR_SEASON)}&club=${encodeURIComponent(r.slug)}&team=${encodeURIComponent(r.tid)}`;
}
function allClubsUrl(r) {
  return `all_clubs.html?season=${encodeURIComponent(CUR_SEASON)}&q=${encodeURIComponent(r.club)}`;
}

function loadSeason(season) {
  if (!SEASON_CACHE[season]) {
    SEASON_CACHE[season] = fetch(`data/all_teams_${season}.json`)
      .then(res => res.ok ? res.json() : { rows: [], clubs: {} })
      .catch(() => ({ rows: [], clubs: {} }));
  }
  return SEASON_CACHE[season];
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
      syncUrl();
    });
    el.appendChild(chip);
  });
}
function quickSelect(kind, containerId, allItems, action, onToggle) {
  allItems.forEach(v => { if (action === 'all') STATE[kind].add(v); else STATE[kind].delete(v); });
  [...document.getElementById(containerId).children].forEach((chip, i) => chip.classList.toggle('active', STATE[kind].has(allItems[i])));
  onToggle();
  syncUrl();
}

function rowHtml(r) {
  const catText = r.cat && r.cat !== 'OTHER' ? catLabel(r.cat) : '—';
  const divText = r.div && r.div !== 'OTHER' ? divLabel(r.div) : '—';
  const ppg = r.pl ? r.pts / r.pl : null;
  const gdpg = r.pl ? r.gd / r.pl : null;
  const posDisplay = r.pos ? (r.size ? `${r.pos}/${r.size}` : r.pos) : '—';
  const posSort = (r.pos && r.size) ? (Number(r.size) - Number(r.pos) + 1) / Number(r.size) : '';
  const stDisplay = (r.st === null || r.st === undefined) ? '—' : `${Math.round(r.st * 100)}%`;
  return `<tr>
    <td class="name-cell" data-col="club" data-v="${esc(r.club)}"><a href="${allClubsUrl(r)}">${esc(r.club)}</a></td>
    <td data-col="team" data-v="${esc(r.team)}"><a href="${teamCardUrl(r)}">${esc(r.team)}</a></td>
    <td data-col="cat" data-v="${esc(catText)}">${esc(catText)}</td>
    <td data-col="div" data-v="${esc(divText)}"><span class="tier-chip">${esc(divText)}</span></td>
    <td data-col="gt" data-v="${esc(gtLabel(r.gt))}">${esc(gtLabel(r.gt))}</td>
    <td class="comp-cell" data-col="comp" data-v="${esc(r.comp || '')}" title="${esc(r.comp || '')}${r.grp ? ' · ' + esc(r.grp) : ''}">${esc(r.comp || '—')}${r.grp ? `<span class="n-note"> · ${esc(r.grp)}</span>` : ''}</td>
    <td data-col="pl" data-v="${r.pl || 0}">${r.pl || 0}</td>
    <td data-col="w" data-v="${r.w || 0}">${r.w || 0}</td>
    <td data-col="d" data-v="${r.d || 0}">${r.d || 0}</td>
    <td data-col="l" data-v="${r.l || 0}">${r.l || 0}</td>
    <td data-col="gf" data-v="${r.gf || 0}">${r.gf || 0}</td>
    <td data-col="ga" data-v="${r.ga || 0}">${r.ga || 0}</td>
    <td data-col="gd" data-v="${r.gd || 0}">${r.gd > 0 ? '+' : ''}${r.gd || 0}</td>
    <td data-col="pts" data-v="${r.pts || 0}">${r.pts || 0}</td>
    <td data-col="ppg" data-v="${ppg === null ? '' : ppg}">${ppg === null ? '—' : ppg.toFixed(2)}</td>
    <td data-col="gdpg" data-v="${gdpg === null ? '' : gdpg}">${gdpg === null ? '—' : (gdpg > 0 ? '+' : '') + gdpg.toFixed(2)}</td>
    <td data-col="pos" data-v="${posSort}" data-label="${esc(posDisplay)}">${esc(posDisplay)}</td>
    <td data-col="sq" data-v="${r.sq === null || r.sq === undefined ? '' : r.sq}">${r.sq === null || r.sq === undefined ? '—' : r.sq}</td>
    <td data-col="st" data-v="${r.st === null || r.st === undefined ? '' : r.st}">${stDisplay}</td>
    <td data-col="yc" data-v="${r.yc || 0}">${r.yc || '—'}</td>
    <td data-col="rc" data-v="${r.rc || 0}">${r.rc || '—'}</td>
    <td data-col="dyc" data-v="${r.dyc || 0}">${r.dyc || '—'}</td>
  </tr>`;
}

let RENDER_TOKEN = 0;
async function render() {
  const myToken = ++RENDER_TOKEN;
  const tbody = document.getElementById('teamsBody');
  tbody.innerHTML = `<tr><td class="empty-state" colspan="22">${LANG[CURLANG].loading}</td></tr>`;
  const payload = await loadSeason(CUR_SEASON);
  if (myToken !== RENDER_TOKEN) return;

  const seenDivs = [...new Set(payload.rows.map(r => r.div))].sort((a, b) => {
    const ra = DIV_ORDER.indexOf(a), rb = DIV_ORDER.indexOf(b);
    return (ra === -1 ? 999 : ra) - (rb === -1 ? 999 : rb) || String(a).localeCompare(String(b));
  });
  if (!STATE.seeded) { seenDivs.forEach(d => STATE.divs.add(d)); STATE.seeded = true; }
  ALL_DIVS = new Set(seenDivs);
  buildChipRow('chips-divs', 'divs', seenDivs, divLabel, render);

  let rows = payload.rows.filter(r => STATE.cats.has(r.cat) && STATE.divs.has(r.div));
  const q = document.getElementById('searchBox').value.trim().toLowerCase();
  if (q) rows = rows.filter(r => (r.club || '').toLowerCase().includes(q) || (r.team || '').toLowerCase().includes(q));

  document.getElementById('resultCount').textContent = rows.length.toLocaleString();
  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="empty-state" colspan="22">${LANG[CURLANG].noResults}</td></tr>`;
    return;
  }
  rffmInitDataTable(document.getElementById('teamsTable'), { labels: DT_LABELS[CURLANG], rows, rowHtml });
}

function initCategoryChips() {
  buildChipRow('chips-cats', 'cats', CAT_ORDER, catLabel, render);
}

document.getElementById('catsAll').addEventListener('click', () => quickSelect('cats', 'chips-cats', CAT_ORDER, 'all', render));
document.getElementById('catsNone').addEventListener('click', () => quickSelect('cats', 'chips-cats', CAT_ORDER, 'none', render));
document.getElementById('divsAll').addEventListener('click', () => quickSelect('divs', 'chips-divs', [...ALL_DIVS], 'all', render));
document.getElementById('divsNone').addEventListener('click', () => quickSelect('divs', 'chips-divs', [...ALL_DIVS], 'none', render));
document.getElementById('searchBox').addEventListener('input', () => { render(); syncUrl(); });
document.getElementById('seasonSelect').addEventListener('change', function () {
  CUR_SEASON = this.value;
  STATE.divs = new Set(); STATE.seeded = false;
  render();
  syncUrl();
});

// Season/categories/divisions/search reflected in the URL so a filtered
// view is shareable — same convention as club_division_map.html, kept
// deliberately simpler here (no sort/modal state, this page has neither).
function currentStateParams() {
  const params = new URLSearchParams();
  if (CUR_SEASON && CUR_SEASON !== SEASONS[SEASONS.length - 1]) params.set('season', CUR_SEASON);
  if (STATE.cats.size !== CAT_ORDER.length) params.set('cats', [...STATE.cats].join(','));
  if (ALL_DIVS.size && STATE.divs.size !== ALL_DIVS.size) params.set('divs', [...STATE.divs].join(','));
  const q = document.getElementById('searchBox').value.trim();
  if (q) params.set('q', q);
  return params;
}
function syncUrl() {
  if (RESTORING) return;
  const qs = currentStateParams().toString();
  history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
}

function init() {
  RESTORING = true;
  const params = new URLSearchParams(location.search);
  const wantSeason = (params.get('season') && SEASONS.includes(params.get('season'))) ? params.get('season') : SEASONS[SEASONS.length - 1];
  document.getElementById('seasonSelect').innerHTML = SEASONS.map(s => `<option value="${s}">${s}</option>`).join('');
  document.getElementById('seasonSelect').value = wantSeason;
  CUR_SEASON = wantSeason;
  STATE.cats = params.has('cats') ? new Set(params.get('cats').split(',').filter(Boolean)) : new Set(CAT_ORDER);
  document.getElementById('searchBox').value = params.get('q') || '';
  if (params.has('divs')) { STATE.divs = new Set(params.get('divs').split(',').filter(Boolean)); STATE.seeded = true; }
  initCategoryChips();
  RESTORING = false;
  render();
}
init();

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
            .replace("%GT_SHORT_JSON%", json.dumps(GT_SHORT, ensure_ascii=False))
            .replace("%I18N_ES_JSON%", json.dumps(I18N_ES, ensure_ascii=False))
            .replace("%THEME_SWITCH_JS%", THEME_SWITCH_JS)
            .replace("%DATATABLE_CSS%", DATATABLE_CSS)
            .replace("%DATATABLE_JS%", DATATABLE_JS))


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    all_seasons = list_seasons()
    build_seasons = seasons or all_seasons
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "all_teams.html").write_text(build_html(all_seasons), encoding="utf-8")

    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for season in build_seasons:
        print(f"Building all-teams data for season {season}")
        rows = build_team_rows(season)
        clubs = build_club_meta(season)
        text = json.dumps({"rows": rows, "clubs": clubs}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        (data_dir / f"all_teams_{season}.json").write_text(text, encoding="utf-8")
        print(f"  {len(rows)} team-competition rows, {len(clubs)} clubs with metadata ({len(text) / 1024:.0f} KB)")


def main():
    parser = argparse.ArgumentParser(description="RFFM all-teams browser")
    parser.add_argument("--season", default=None, help="build only this season's data (default: every season with a complete core crawl)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


if __name__ == "__main__":
    main()
