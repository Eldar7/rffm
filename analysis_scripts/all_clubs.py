#!/usr/bin/env python3
"""
All-clubs browser: one row per club, aggregated across every team/competition
that club fielded this season — the same idea as all_players.py/all_teams.py,
one level further up the hierarchy (player -> team -> club).

Deliberately has NO data-build pass of its own: it fetches the exact same
data/all_teams_<season>.json all_teams.py already writes (one row per team x
competition) and aggregates it into per-club rows client-side, live, from
whichever category/division chips are currently active — so "this club's
numbers, counting only its CADETE teams" is just a filter toggle, not a
second dataset. Two pages, one source of truth; see all_teams.py's own
docstring for the row shape being aggregated here.

Aggregation rules (see aggregateClubs() in the page's own JS):
  - Match totals (played/W-D-L/goals/points) sum across EVERY row for the
    club (league + cup both count — "how much did this club's teams
    achieve in total this season").
  - Per-TEAM properties (squad size, roster stability, cards) are deduped
    to one value per team_id first (a team's league-row and cup-row repeat
    the identical number), THEN averaged/summed across the club's distinct
    teams — summing them straight off every row would double-count a team
    that has both a league and a cup row.

Usage:
    python analysis_scripts/all_clubs.py
    python analysis_scripts/all_clubs.py --output-dir reports
"""

import argparse
import json
from pathlib import Path

from club_division_map import (CAT_LABEL_ES, CAT_LABEL_RU, CATEGORIES, DIV_LABEL_ES, DIV_LABEL_RU, DIV_ORDER,
                                TIER_OF)
from site_theme import DATATABLE_CSS, DATATABLE_JS, FONT_LINKS, THEME_INIT_JS, THEME_SWITCH_JS, switch_row_html
from team_cards import list_seasons

I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; todos los clubes",
    "back": "&larr; Mapa de clubes",
    "nav_clubs": "Todos los clubes", "nav_teams": "Todos los equipos", "nav_players": "Todos los jugadores",
    "h1": "Todos los clubes",
    "lede": "Una fila por club de la temporada elegida arriba, sumando todos sus equipos y competiciones "
            "activos (liga y copa incluidas). Marca las categorías/divisiones que quieras contar en el "
            "total. Haz clic en ▾ de cualquier columna para ordenar/filtrar, como en Excel.",
    "h_howto": "Cómo encontrar clubes fuertes",
    "how1": "«Ptos/partido (pond.)» y «Dif/partido (pond.)» son los números más comparables entre clubes "
            "con distinto número de equipos/partidos — la suma de puntos no lo es (un club con más "
            "equipos suma más puntos sin ser necesariamente más fuerte por equipo).",
    "how2": "«Lideran» cuenta cuántos de los equipos del club van primeros en su grupo ahora mismo — señal "
            "directa de cuántos frentes tiene un club en la cima. «Mejor división» muestra el techo real "
            "del club (su equipo en la liga más fuerte), aunque el resto juegue más abajo.",
    "how3": "«Plantilla media»/«Estabilidad media» resumen la profundidad y continuidad de los onces del "
            "club en conjunto — un club con muchos equipos pero plantillas muy cortas puede tener "
            "problemas de cantera aunque los resultados de ahora mismo sean buenos.",
    "lbl_season": "Temporada",
    "lbl_cats": "Categoría", "btn_all1": "Todas", "btn_none1": "Ninguna",
    "lbl_divs": "División", "btn_all2": "Todas", "btn_none2": "Ninguna",
    "searchPh": "Buscar club…",
    "loading": "Cargando…", "noResults": "Sin resultados.",
    "th_club": "Club", "th_cats": "Categorías", "th_teams": "Equipos", "th_bestdiv": "Mejor división",
    "th_pl": "PJ", "th_w": "G", "th_d": "E", "th_l": "P",
    "th_gf": "GF", "th_ga": "GC", "th_gd": "DG", "th_pts": "Pts",
    "th_ppg": "Ptos/partido (pond.)", "th_gdpg": "Dif/partido (pond.)", "th_leaders": "Lideran",
    "th_sq": "Plantilla media", "th_st": "Estabilidad media",
    "th_yc": "A", "th_rc": "R", "th_dyc": "2A", "th_loc": "Localidad",
    "footer": 'Agregado a partir de <code>data/all_teams_&lt;temporada&gt;.json</code> '
              '(ver <code>analysis_scripts/all_teams.py</code>). Sin build propio — ver '
              '<code>analysis_scripts/all_clubs.py</code>.',
}

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — все клубы</title>
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
.club-crest-ic{width:16px; height:16px; object-fit:contain; border-radius:3px; vertical-align:middle; margin-right:0.35rem;}
.profile-link{font-size:0.78rem; margin-left:0.4rem;}
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
      <a class="is-here" data-i18n="nav_clubs">Все клубы</a>
      <a href="all_teams.html" data-i18n="nav_teams">Все команды</a>
      <a href="all_players.html" data-i18n="nav_players">Все игроки</a>
    </nav>
    <span class="eyebrow" data-i18n="eyebrow">RFFM (Мадрид) &middot; все клубы</span>
    <h1 data-i18n="h1">Все клубы</h1>
    <p class="lede prose" data-i18n="lede">
      Одна строка — клуб выбранного вверху сезона, суммируя все его активные команды и соревнования
      (лига и кубок включены). Отметьте категории/дивизионы, которые нужно учитывать в сумме.
      Клик по ▾ в заголовке любой колонки — сортировка и фильтр, как в Excel.
    </p>
  </header>

  <details class="strategy-box">
    <summary data-i18n="h_howto">Как искать сильные клубы</summary>
    <ol class="prose">
      <li data-i18n="how1">
        «Очки/игру (взвеш.)» и «Разница/игру (взвеш.)» — самые сравнимые между клубами с разным числом
        команд/матчей цифры; сумма очков — нет (клуб с бóльшим числом команд наберёт больше очков, не
        обязательно будучи сильнее в расчёте на команду).
      </li>
      <li data-i18n="how2">
        «Лидируют» показывает, сколько команд клуба сейчас идут первыми в своей группе — прямой сигнал,
        на скольких фронтах клуб на вершине. «Лучший дивизион» — реальный потолок клуба (его команда в
        самой сильной лиге), даже если остальные играют ниже.
      </li>
      <li data-i18n="how3">
        «Состав ср.»/«Стабильность ср.» суммируют глубину и постоянство составов клуба в целом — клуб с
        большим числом команд, но очень короткими составами может иметь проблемы с резервом, даже если
        текущие результаты хорошие.
      </li>
    </ol>
  </details>

  <div class="controls-bar">
    <label class="filter-label" data-i18n="lbl_season" style="min-width:auto;">Сезон</label>
    <select id="seasonSelect"></select>
    <div class="search">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input type="text" id="searchBox" placeholder="Поиск клуба…" autocomplete="off">
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
      <table id="clubsTable" class="dtable">
        <thead><tr>
          <th data-key="club" data-type="text"><span data-i18n="th_club">Клуб</span></th>
          <th data-key="cats" data-type="number"><span data-i18n="th_cats">Категорий</span></th>
          <th data-key="teams" data-type="number"><span data-i18n="th_teams">Команд</span></th>
          <th data-key="bestdiv" data-type="text"><span data-i18n="th_bestdiv">Лучший дивизион</span></th>
          <th data-key="pl" data-type="number" title="Игр (сумма по всем командам)"><span data-i18n="th_pl">И</span></th>
          <th data-key="w" data-type="number" title="Выигрышей"><span data-i18n="th_w">В</span></th>
          <th data-key="d" data-type="number" title="Ничьих"><span data-i18n="th_d">Н</span></th>
          <th data-key="l" data-type="number" title="Поражений"><span data-i18n="th_l">П</span></th>
          <th data-key="gf" data-type="number" title="Забито мячей"><span data-i18n="th_gf">ЗМ</span></th>
          <th data-key="ga" data-type="number" title="Пропущено мячей"><span data-i18n="th_ga">ПМ</span></th>
          <th data-key="gd" data-type="number" title="Разница мячей"><span data-i18n="th_gd">РМ</span></th>
          <th data-key="pts" data-type="number" title="Очков (сумма)"><span data-i18n="th_pts">О</span></th>
          <th data-key="ppg" data-type="number" title="Суммарные очки / суммарные игры по всем командам клуба"><span data-i18n="th_ppg">Очки/игру (взвеш.)</span></th>
          <th data-key="gdpg" data-type="number" title="Суммарная разница мячей / суммарные игры"><span data-i18n="th_gdpg">Разница/игру (взвеш.)</span></th>
          <th data-key="leaders" data-type="number" title="Число команд клуба на 1 месте в своей группе"><span data-i18n="th_leaders">Лидируют</span></th>
          <th data-key="sq" data-type="number" title="Среднее число разных игроков в заявке по командам клуба"><span data-i18n="th_sq">Состав ср.</span></th>
          <th data-key="st" data-type="number" title="Средняя стабильность стартового состава по командам клуба"><span data-i18n="th_st">Стабильность ср.</span></th>
          <th data-key="yc" data-type="number" title="Жёлтые карточки"><span data-i18n="th_yc">Ж</span></th>
          <th data-key="rc" data-type="number" title="Красные карточки"><span data-i18n="th_rc">К</span></th>
          <th data-key="dyc" data-type="number" title="Вторые жёлтые"><span data-i18n="th_dyc">2Ж</span></th>
          <th data-key="loc" data-type="text"><span data-i18n="th_loc">Город</span></th>
        </tr></thead>
        <tbody id="clubsBody"><tr><td class="empty-state" colspan="21" data-i18n="loading">Загрузка…</td></tr></tbody>
      </table>
    </div>
  </div>

  <footer class="note" data-i18n="footer">Агрегировано из <code>data/all_teams_&lt;сезон&gt;.json</code>
    (см. <code>analysis_scripts/all_teams.py</code>). Своего построения данных нет — см.
    <code>analysis_scripts/all_clubs.py</code>.</footer>
</div>
<script>
const SEASONS = %SEASONS_JSON%;
const CAT_ORDER = %CAT_ORDER_JSON%;
const DIV_ORDER = %DIV_ORDER_JSON%;
const CAT_LABEL_RU = %CAT_LABEL_RU_JSON%;
const CAT_LABEL_ES = %CAT_LABEL_ES_JSON%;
const DIV_LABEL_RU = %DIV_LABEL_RU_JSON%;
const DIV_LABEL_ES = %DIV_LABEL_ES_JSON%;
const TIER_OF = %TIER_OF_JSON%;
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
const SEASON_CACHE = {}; // season -> Promise<{rows, clubs}> (same file all_teams.html fetches)
let ALL_DIVS = new Set();
let RESTORING = false;

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}
function catLabel(c) { return (CURLANG === 'ru' ? CAT_LABEL_RU : CAT_LABEL_ES)[c] || c; }
function divLabel(d) { return (CURLANG === 'ru' ? DIV_LABEL_RU : DIV_LABEL_ES)[d] || d || ''; }
function divTier(d) { const t = TIER_OF[d]; return (t === null || t === undefined) ? Infinity : t; }

%DATATABLE_JS%

function loadSeason(season) {
  if (!SEASON_CACHE[season]) {
    // v2/data/... - all_teams.py (v1) no longer builds its own copy of
    // this (see build_site.py); all_teams_v2's copy is the only one.
    SEASON_CACHE[season] = fetch(`v2/data/all_teams_${season}.json`)
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

// Group the same team x competition rows all_teams.html shows into one
// record per club — see module docstring for why match totals sum across
// every row while squad/stability/cards dedupe to one value per team_id
// first.
function aggregateClubs(rows, clubMeta) {
  const byClub = new Map();
  rows.forEach(r => {
    let c = byClub.get(r.club_id);
    if (!c) {
      c = {
        club: r.club, club_id: r.club_id, slug: r.slug,
        teams: new Set(), cats: new Set(), divs: new Set(), leaders: new Set(),
        pl: 0, w: 0, d: 0, l: 0, gf: 0, ga: 0, pts: 0, teamAgg: new Map(),
      };
      byClub.set(r.club_id, c);
    }
    c.teams.add(r.tid);
    c.cats.add(r.cat);
    c.divs.add(r.div);
    c.pl += r.pl || 0; c.w += r.w || 0; c.d += r.d || 0; c.l += r.l || 0;
    c.gf += r.gf || 0; c.ga += r.ga || 0; c.pts += r.pts || 0;
    if (String(r.pos) === '1') c.leaders.add(r.tid);
    if (!c.teamAgg.has(r.tid)) c.teamAgg.set(r.tid, { sq: r.sq, st: r.st, yc: r.yc || 0, rc: r.rc || 0, dyc: r.dyc || 0 });
  });
  return [...byClub.values()].map(c => {
    const teamStats = [...c.teamAgg.values()];
    const sqVals = teamStats.map(t => t.sq).filter(v => v !== null && v !== undefined);
    const stVals = teamStats.map(t => t.st).filter(v => v !== null && v !== undefined);
    const divsSorted = [...c.divs].sort((a, b) => divTier(a) - divTier(b));
    const bestDiv = divsSorted.length ? divsSorted[0] : null;
    const meta = clubMeta[c.club_id] || {};
    return {
      club: c.club, club_id: c.club_id, slug: c.slug, cats: c.cats.size, teams: c.teams.size, bestDiv,
      pl: c.pl, w: c.w, d: c.d, l: c.l, gf: c.gf, ga: c.ga, gd: c.gf - c.ga, pts: c.pts,
      leaders: c.leaders.size,
      sq: sqVals.length ? sqVals.reduce((a, b) => a + b, 0) / sqVals.length : null,
      st: stVals.length ? stVals.reduce((a, b) => a + b, 0) / stVals.length : null,
      yc: teamStats.reduce((a, t) => a + t.yc, 0), rc: teamStats.reduce((a, t) => a + t.rc, 0), dyc: teamStats.reduce((a, t) => a + t.dyc, 0),
      loc: meta.loc || null,
      crest: meta.crest || null,
    };
  });
}

function allTeamsUrl(c) {
  return `all_teams.html?season=${encodeURIComponent(CUR_SEASON)}&q=${encodeURIComponent(c.club)}`;
}
function clubProfileUrl(c) {
  return `club_profile.html?club=${encodeURIComponent(c.slug)}`;
}

function rowHtml(c) {
  const bestDivText = (c.bestDiv && c.bestDiv !== 'OTHER') ? divLabel(c.bestDiv) : '—';
  const bestDivSort = c.bestDiv ? -divTier(c.bestDiv) : -Infinity; // stronger division sorts higher by default
  const ppg = c.pl ? c.pts / c.pl : null;
  const gdpg = c.pl ? c.gd / c.pl : null;
  const sqDisplay = c.sq === null ? '—' : c.sq.toFixed(1);
  const stDisplay = c.st === null ? '—' : `${Math.round(c.st * 100)}%`;
  const crestHtml = c.crest ? `<img class="club-crest-ic" src="${c.crest}" alt="" onerror="this.remove()">` : '';
  return `<tr>
    <td class="name-cell" data-col="club" data-v="${esc(c.club)}">
      ${crestHtml}<a href="${allTeamsUrl(c)}">${esc(c.club)}</a>
      <a class="profile-link" href="${clubProfileUrl(c)}" title="Профиль клуба">&rarr;</a>
    </td>
    <td data-col="cats" data-v="${c.cats}">${c.cats}</td>
    <td data-col="teams" data-v="${c.teams}">${c.teams}</td>
    <td data-col="bestdiv" data-v="${bestDivSort}" data-label="${esc(bestDivText)}">${bestDivText === '—' ? '—' : `<span class="tier-chip">${esc(bestDivText)}</span>`}</td>
    <td data-col="pl" data-v="${c.pl || 0}">${c.pl || 0}</td>
    <td data-col="w" data-v="${c.w || 0}">${c.w || 0}</td>
    <td data-col="d" data-v="${c.d || 0}">${c.d || 0}</td>
    <td data-col="l" data-v="${c.l || 0}">${c.l || 0}</td>
    <td data-col="gf" data-v="${c.gf || 0}">${c.gf || 0}</td>
    <td data-col="ga" data-v="${c.ga || 0}">${c.ga || 0}</td>
    <td data-col="gd" data-v="${c.gd || 0}">${c.gd > 0 ? '+' : ''}${c.gd || 0}</td>
    <td data-col="pts" data-v="${c.pts || 0}">${c.pts || 0}</td>
    <td data-col="ppg" data-v="${ppg === null ? '' : ppg}">${ppg === null ? '—' : ppg.toFixed(2)}</td>
    <td data-col="gdpg" data-v="${gdpg === null ? '' : gdpg}">${gdpg === null ? '—' : (gdpg > 0 ? '+' : '') + gdpg.toFixed(2)}</td>
    <td data-col="leaders" data-v="${c.leaders || 0}">${c.leaders || 0}</td>
    <td data-col="sq" data-v="${c.sq === null ? '' : c.sq}">${sqDisplay}</td>
    <td data-col="st" data-v="${c.st === null ? '' : c.st}">${stDisplay}</td>
    <td data-col="yc" data-v="${c.yc || 0}">${c.yc || '—'}</td>
    <td data-col="rc" data-v="${c.rc || 0}">${c.rc || '—'}</td>
    <td data-col="dyc" data-v="${c.dyc || 0}">${c.dyc || '—'}</td>
    <td data-col="loc" data-v="${esc(c.loc || '')}">${esc(c.loc || '—')}</td>
  </tr>`;
}

let RENDER_TOKEN = 0;
async function render() {
  const myToken = ++RENDER_TOKEN;
  const tbody = document.getElementById('clubsBody');
  tbody.innerHTML = `<tr><td class="empty-state" colspan="21">${LANG[CURLANG].loading}</td></tr>`;
  const payload = await loadSeason(CUR_SEASON);
  if (myToken !== RENDER_TOKEN) return;

  const seenDivs = [...new Set(payload.rows.map(r => r.div))].sort((a, b) => divTier(a) - divTier(b) || String(a).localeCompare(String(b)));
  if (!STATE.seeded) { seenDivs.forEach(d => STATE.divs.add(d)); STATE.seeded = true; }
  ALL_DIVS = new Set(seenDivs);
  buildChipRow('chips-divs', 'divs', seenDivs, divLabel, render);

  let teamRows = payload.rows.filter(r => STATE.cats.has(r.cat) && STATE.divs.has(r.div));
  const q = document.getElementById('searchBox').value.trim().toLowerCase();
  if (q) teamRows = teamRows.filter(r => (r.club || '').toLowerCase().includes(q));

  const clubs = aggregateClubs(teamRows, payload.clubs || {});
  document.getElementById('resultCount').textContent = clubs.length.toLocaleString();
  if (!clubs.length) {
    tbody.innerHTML = `<tr><td class="empty-state" colspan="21">${LANG[CURLANG].noResults}</td></tr>`;
    return;
  }
  tbody.innerHTML = clubs.map(rowHtml).join('');
  rffmInitDataTable(document.getElementById('clubsTable'), { labels: DT_LABELS[CURLANG] });
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
            .replace("%TIER_OF_JSON%", json.dumps(TIER_OF, ensure_ascii=False))
            .replace("%I18N_ES_JSON%", json.dumps(I18N_ES, ensure_ascii=False))
            .replace("%THEME_SWITCH_JS%", THEME_SWITCH_JS)
            .replace("%DATATABLE_CSS%", DATATABLE_CSS)
            .replace("%DATATABLE_JS%", DATATABLE_JS))


def build_all(out_dir: Path) -> None:
    # No data pass here on purpose — see module docstring. all_teams.py's
    # own build_all() must have already run (or run separately after this)
    # to produce data/all_teams_<season>.json, which this page fetches
    # client-side; build_site.py calls both.
    seasons = list_seasons()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "all_clubs.html").write_text(build_html(seasons), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="RFFM all-clubs browser (aggregates all_teams.py's data)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    build_all(Path(__file__).parent.parent / args.output_dir)


if __name__ == "__main__":
    main()
