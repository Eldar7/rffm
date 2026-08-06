#!/usr/bin/env python3
"""
Club x division matrix for Benjamin/Prebenjamin — one row per club, one
column per (age category, division tier), cell = team count + best
position reached that season, plus each club's most-frequent home venue
(Google Maps link). All data embedded as JSON; search/filter run in the
browser, no page reload.

Usage:
    python analysis_scripts/club_division_map.py
    python analysis_scripts/club_division_map.py --season 2025-2026 --output reports/club_division_map.html
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from site_theme import FONT_LINKS, lang_switch_html

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

CATEGORIES = ["BENJAMIN", "PREBENJAMIN"]
CAT_LABELS = {"BENJAMIN": "Benjamín", "PREBENJAMIN": "Prebenjamín"}

# Ordered strongest-to-weakest, matching CLAUDE.md/DATA_DICTIONARY.md tier ordering.
DIV_ORDER = [
    "DIVISION DE HONOR", "PRIMERA DIVISION AUTONOMICA", "PREFERENTE",
    "PRIMERA", "SEGUNDA", "TERCERA",
]
DIV_CODE = {
    "DIVISION DE HONOR": "DH",
    "PRIMERA DIVISION AUTONOMICA": "PDA",
    "PREFERENTE": "PREF",
    "PRIMERA": "PRIM",
    "SEGUNDA": "SEG",
    "TERCERA": "TER",
}
DIV_LABEL = {
    "DIVISION DE HONOR": "División de Honor",
    "PRIMERA DIVISION AUTONOMICA": "1ª Div. Autonómica",
    "PREFERENTE": "Preferente",
    "PRIMERA": "1ª División",
    "SEGUNDA": "2ª División",
    "TERCERA": "3ª División",
}


def latest_core_season() -> str:
    """Most recent season whose core crawl is complete, per coverage_manifest.csv."""
    m = pd.read_csv(MANIFEST, dtype=str)
    core = m[(m["stage"] == "core") & (m["category_base"] == "ALL") &
             (m["status"].isin(["complete", "complete_with_failures"]))]
    if core.empty:
        raise SystemExit("No season has a complete core crawl in coverage_manifest.csv")
    return sorted(core["season"].unique().tolist())[-1]


def norm_id(v):
    try:
        return str(int(float(str(v))))
    except (ValueError, TypeError):
        return None


def load_data(season: str) -> dict:
    d = BASE / season
    teams = pd.read_csv(d / "teams.csv", dtype=str)
    comps = pd.read_csv(d / "competitions.csv", dtype=str)
    standings = pd.read_csv(d / "standings.csv", dtype=str)
    matches = pd.read_csv(d / "matches.csv", dtype=str)
    venues = pd.read_csv(d / "venues.csv", dtype=str)

    comps["category_base"] = comps["category_base"].fillna("OTHER")
    comps["division_level"] = comps["division_level"].fillna("OTHER")
    comp_facet = comps.set_index("competition_id")[["category_base", "division_level"]]

    standings = standings.join(comp_facet, on="competition_id")
    standings = standings[standings["category_base"].isin(CATEGORIES) &
                           standings["division_level"].isin(DIV_ORDER)].copy()
    standings["position"] = pd.to_numeric(standings["position"], errors="coerce")
    standings["tid"] = standings["team_id"].map(norm_id)

    tid_to_club = dict(zip(teams["team_id"].map(norm_id), teams["club_name_raw"]))
    standings["club"] = standings["tid"].map(tid_to_club)
    standings = standings.dropna(subset=["club", "position"])

    group_size = standings.groupby("group_id").size().to_dict()

    # ── matrix cells: one row per (club, cat, div) ──
    cell_rows = []
    for (club, cat, div), grp in standings.groupby(["club", "category_base", "division_level"]):
        best = grp.loc[grp["position"].idxmin()]
        cell_rows.append({
            "club": club, "cat": cat, "div": div,
            "n": int(grp["tid"].nunique()),
            "pos": int(best["position"]),
            "size": int(group_size.get(best["group_id"], len(grp))),
            "grp": best["group"],
        })
    cells = pd.DataFrame(cell_rows)

    # ── venues: most-frequent home ground per club, scoped to the teams in this matrix ──
    relevant_tids = set(standings["tid"].dropna().unique())
    matches["hid"] = matches["home_team_id"].map(norm_id)
    matches["vid"] = matches["venue_id"].map(norm_id)
    home = matches[matches["hid"].isin(relevant_tids)].copy()
    home["club"] = home["hid"].map(tid_to_club)
    venues["vid"] = venues["venue_id"].map(norm_id)
    venue_name = dict(zip(venues["vid"], venues["venue_name"]))
    venue_maps = dict(zip(venues["vid"], venues["google_maps_url"]))

    venue_by_club = {}
    for club, grp in home.dropna(subset=["vid"]).groupby("club"):
        counts = grp["vid"].value_counts()
        if counts.empty:
            continue
        top_vid = counts.index[0]
        total = int(counts.sum())
        n = int(counts.iloc[0])
        venue_by_club[club] = {
            "venue": venue_name.get(top_vid, top_vid),
            "n": n, "total": total,
            "pct": round(n / total * 100) if total else 0,
            "maps": venue_maps.get(top_vid),
        }

    # ── assemble per-club records ──
    clubs_out = []
    for club, grp in cells.groupby("club"):
        rec = {"club": club}
        for cat in CATEGORIES:
            for div in DIV_ORDER:
                key = f"{cat}_{DIV_CODE[div]}"
                match = grp[(grp["cat"] == cat) & (grp["div"] == div)]
                rec[key] = None if match.empty else {
                    "n": int(match.iloc[0]["n"]), "pos": int(match.iloc[0]["pos"]),
                    "size": int(match.iloc[0]["size"]), "grp": match.iloc[0]["grp"],
                }
        rec["total_teams"] = int(grp["n"].sum())
        rec["total_divs"] = int(grp[["cat", "div"]].drop_duplicates().shape[0])
        rec["venue"] = venue_by_club.get(club)
        clubs_out.append(rec)
    clubs_out.sort(key=lambda r: r["club"])

    columns = [
        {"cat": cat, "div": div, "key": f"{cat}_{DIV_CODE[div]}",
         "cat_label": CAT_LABELS[cat], "div_label": DIV_LABEL[div]}
        for cat in CATEGORIES for div in DIV_ORDER
        if not cells[(cells["cat"] == cat) & (cells["div"] == div)].empty
    ]

    return {"season": season, "columns": columns, "clubs": clubs_out}


HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM %SEASON% — карта клубов по дивизионам</title>
%FONT_LINKS%
<style>
:root{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --tier-1:#c3dcc7; --tier-2:#d6e6d8; --tier-3:#e6efe6; --tier-4:#f2f5f1; --row-hover:#f4f7f2;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
    --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
    --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
    --tier-1:#294a30; --tier-2:#213b27; --tier-3:#1c2f21; --tier-4:#18241b; --row-hover:#1c2619;
  }
}
:root[data-theme="dark"]{
  --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
  --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
  --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
  --tier-1:#294a30; --tier-2:#213b27; --tier-3:#1c2f21; --tier-4:#18241b; --row-hover:#1c2619;
}
:root[data-theme="light"]{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --tier-1:#c3dcc7; --tier-2:#d6e6d8; --tier-3:#e6efe6; --tier-4:#f2f5f1; --row-hover:#f4f7f2;
}
*{box-sizing:border-box;}
html,body{margin:0; height:100%;}
body{
  background:var(--bg); color:var(--ink);
  font-family: ui-sans-serif, "Helvetica Neue", Arial, sans-serif;
  line-height:1.5; -webkit-font-smoothing:antialiased;
}
.page{ max-width:1400px; margin:0 auto; padding:2.25rem 1.25rem 4rem; display:flex; flex-direction:column; gap:1.5rem; }
h1{ font-family: 'Oswald', ui-sans-serif, "Arial Narrow", "Helvetica Neue", Arial, sans-serif; font-weight:700;
  text-transform:uppercase; letter-spacing:0.01em; text-wrap:balance; margin:0; color:var(--ink); font-size:clamp(1.4rem,2.8vw,1.9rem); line-height:1.2; }
header.masthead{display:flex; flex-direction:column; gap:0.4rem; border-bottom:3px solid var(--ink); padding-bottom:1rem; position:relative;}
.eyebrow{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:var(--accent); }
.masthead p{margin:0; color:var(--ink-soft); font-size:0.95rem; max-width:70ch;}
a.back{font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:var(--accent); text-decoration:none;}
a.back:hover{text-decoration:underline;}
.masthead .lang-switch{position:absolute; top:0; right:0;}

.stats{display:flex; flex-wrap:wrap; gap:0.75rem;}
.stat{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:0.7rem 1rem;
  box-shadow:var(--shadow); min-width:9rem; display:flex; flex-direction:column; gap:0.15rem; }
.stat .n{font-family: ui-monospace, monospace; font-size:1.35rem; font-weight:700; font-variant-numeric: tabular-nums; color:var(--ink);}
.stat .l{font-size:0.72rem; color:var(--ink-soft); letter-spacing:0.03em;}

.controls{ display:flex; flex-wrap:wrap; gap:0.75rem; align-items:center; background:var(--surface);
  border:1px solid var(--line); border-radius:8px; padding:0.75rem 0.9rem; box-shadow:var(--shadow); }
.search{ flex:1 1 16rem; display:flex; align-items:center; gap:0.5rem; border:1px solid var(--line-strong);
  border-radius:6px; padding:0.4rem 0.65rem; background:var(--bg); }
.search svg{flex:none; opacity:0.55;}
.search input{ border:none; background:transparent; outline:none; color:var(--ink); font-size:0.92rem; width:100%; font-family:inherit; }
.search input::placeholder{color:var(--ink-faint);}
button.toggle{ font-family:inherit; font-size:0.82rem; font-weight:600; color:var(--ink-soft); background:var(--bg);
  border:1px solid var(--line-strong); border-radius:999px; padding:0.4rem 0.85rem; cursor:pointer; }
button.toggle:hover{color:var(--ink); border-color:var(--accent);}
button.toggle.active{background:var(--accent-soft); color:var(--accent); border-color:var(--accent);}
.result-count{font-size:0.8rem; color:var(--ink-soft); white-space:nowrap;}

.lang-switch{ display:inline-flex; border:1px solid var(--line-strong); border-radius:999px; overflow:hidden; }
.lang-opt{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:0.04em;
  padding:4px 12px; background:var(--surface); color:var(--ink-soft); border:none; cursor:pointer; }
.lang-opt.is-active{background:var(--accent); color:#fff;}

.legend{ display:flex; flex-wrap:wrap; gap:1.1rem; font-size:0.8rem; color:var(--ink-soft); align-items:center; }
.legend .chip-sample{ display:inline-flex; align-items:center; gap:0.35rem; }
.tier-dot{width:0.8rem; height:0.8rem; border-radius:3px; display:inline-block; border:1px solid var(--line-strong);}

.table-shell{ background:var(--surface); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); overflow:hidden; }
.table-scroll{overflow:auto; max-height:75vh;}
table{border-collapse:separate; border-spacing:0; font-size:0.83rem; width:100%;}
thead th{ background:var(--surface); position:sticky; top:0; z-index:3; border-bottom:1px solid var(--line); padding:0; text-align:left; }
thead tr.cat-row th{ font-size:0.68rem; letter-spacing:0.1em; text-transform:uppercase; color:var(--ink-soft);
  padding:0.5rem 0.7rem; border-bottom:1px solid var(--line-strong); text-align:center; }
thead tr.cat-row th.corner{background:var(--surface); position:sticky; left:0; z-index:4;}
thead tr.lvl-row th{ padding:0.5rem 0.6rem; font-size:0.72rem; font-weight:700; color:var(--ink);
  border-right:1px solid var(--line); cursor:pointer; user-select:none; white-space:nowrap; }
thead tr.lvl-row th:hover{color:var(--accent);}
thead tr.lvl-row th .arrow{opacity:0.4; font-size:0.65em; margin-left:0.2em;}
thead tr.lvl-row th.active .arrow{opacity:1; color:var(--accent);}
thead tr.lvl-row th.club-head{ position:sticky; left:0; z-index:4; background:var(--surface);
  border-right:1px solid var(--line-strong); min-width:15rem; }
thead tr.lvl-row th.total-head{min-width:8rem;}
tbody td{ border-bottom:1px solid var(--line); padding:0.4rem 0.55rem; vertical-align:middle; white-space:nowrap; }
tbody tr:hover td{background:var(--row-hover);}
tbody td.club-cell{ position:sticky; left:0; z-index:2; background:var(--surface);
  border-right:1px solid var(--line-strong); font-weight:600; color:var(--ink); white-space:normal; max-width:16rem; }
tbody tr:hover td.club-cell{background:var(--row-hover);}
.club-cell-inner{display:flex; align-items:baseline; gap:0.4rem; flex-wrap:wrap;}
.club-name{flex:1 1 auto; min-width:0;}
a.pin{ flex:none; display:inline-flex; align-items:center; gap:0.2rem; font-size:0.7rem; font-weight:600;
  color:var(--ink-faint); text-decoration:none; border:1px solid var(--line-strong); border-radius:999px;
  padding:0.08rem 0.4rem 0.08rem 0.3rem; white-space:nowrap; }
a.pin:hover{color:var(--accent); border-color:var(--accent); background:var(--accent-soft);}
td.total-cell{font-variant-numeric: tabular-nums; color:var(--ink-soft); text-align:right;}
td.total-cell strong{color:var(--ink); font-weight:700;}
td.cell{text-align:center; padding:0.3rem 0.4rem;}
td.cell .chip{ display:inline-flex; flex-direction:column; align-items:center; justify-content:center;
  gap:0.05rem; border-radius:6px; padding:0.28rem 0.5rem; min-width:3.6rem; font-variant-numeric: tabular-nums; }
td.cell .chip .n{font-size:0.78rem; font-weight:700; color:var(--accent);}
td.cell .chip .p{font-size:0.68rem; color:var(--ink-soft);}
td.cell .chip.leader{box-shadow: inset 0 0 0 1.5px var(--gold);}
td.cell .chip.leader .n{color:var(--gold);}
td.cell .empty{color:var(--ink-faint); font-size:0.8rem;}
.hidden{display:none !important;}
.empty-state{padding:2.5rem 1rem; text-align:center; color:var(--ink-soft); font-size:0.92rem;}
footer.note{font-size:0.82rem; color:var(--ink-soft); max-width:80ch;}
footer.note code{ font-family: ui-monospace, monospace; font-size:0.86em; background:var(--accent-soft);
  padding:0.05em 0.35em; border-radius:3px; color:var(--ink); }
</style>
</head>
<body>

<div class="page">
  <header class="masthead">
    %LANG_SWITCH%
    <a class="back" href="index.html">&larr; RFFM data</a>
    <span class="eyebrow"><span data-i18n="eyebrow">RFFM (Мадрид) &middot; Сезон %SEASON% &middot; Футбол-7</span></span>
    <h1><span data-i18n="h1">Карта клубов по дивизионам — Бенхамин &amp; Пребенхамин</span></h1>
    <p><span data-i18n="lede">Каждая строка &mdash; клуб, каждый столбец &mdash; дивизион. В ячейке &mdash; сколько команд клуба там выступает и лучшая позиция (любой из его команд) в своей группе. Фон темнее для более высоких дивизионов.</span></p>
  </header>

  <div class="stats" id="stats"></div>

  <div class="controls">
    <div class="search">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input type="text" id="searchBox" placeholder="Поиск клуба (напр. Aravaca, Getafe, Real Madrid)&hellip;" autocomplete="off">
    </div>
    <button class="toggle" id="presentToggle" type="button"><span data-i18n="onlyPresent">Только с присутствием</span></button>
    <span class="result-count" id="resultCount"></span>
  </div>

  <div class="legend">
    <span class="chip-sample"><span class="tier-dot" style="background:var(--tier-1)"></span><span data-i18n="legend1">Высшая доступная лига</span></span>
    <span class="chip-sample"><span class="tier-dot" style="background:var(--tier-4)"></span><span data-i18n="legend2">Низшая доступная лига</span></span>
    <span class="chip-sample"><span style="display:inline-block;width:0.9rem;height:0.9rem;border-radius:4px;box-shadow:inset 0 0 0 1.5px var(--gold);"></span><span data-i18n="legend3">Лидер своей группы</span></span>
    <span data-i18n="legend4">Ячейка: число команд клуба там &middot; лучшая позиция/размер группы</span>
    <span data-i18n="legend5">&#128205; = самая частая площадка в Google Maps (формат «sede», ротация по турам — не обязательно постоянное поле, см. сноску)</span>
  </div>

  <div class="table-shell">
    <div class="table-scroll">
      <table id="matrixTable">
        <thead>
          <tr class="cat-row" id="catRow"><th class="corner"></th></tr>
          <tr class="lvl-row" id="headRow"></tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </div>

  <footer class="note">
    <span data-i18n="foot1">Охват: клубы минимум с одной командой Бенхамин или Пребенхамин в футболе-7 с зарегистрированной классификацией, сезон %SEASON%. Только позиции регулярного сезона. Источник: <code>output/processed/rffm/{teams,competitions,standings,matches,venues}.csv</code>.</span>
    <br><br>
    <span data-i18n="foot2"><strong>О значке &#128205;:</strong> Бенхамин/Пребенхамин обычно играют в формате <em>«sede»</em> — «домашние» матчи проходят на разных полях, назначаемых по турам, а не на одном постоянном стадионе клуба. Значок открывает в Google Maps поле, где команда(ы) клуба чаще всего играли дома в этих категориях в этом сезоне, с указанием % домашних матчей там &mdash; ориентировочно, не официальный адрес.</span>
  </footer>
</div>

<script id="pageData" type="application/json">%DATA_JSON%</script>
<script>
const LANG = {
  ru: { club: 'Клуб', total: 'Всего команд', clubsWord: 'клубов', noResults: 'Нет результатов.', searchPh: 'Поиск клуба (напр. Aravaca, Getafe, Real Madrid)…', of: 'в' },
  es: { club: 'Club', total: 'Total equipos', clubsWord: 'clubes', noResults: 'Sin resultados.', searchPh: 'Buscar club (p. ej. Aravaca, Getafe, Real Madrid)…', of: 'en' },
};
let CURLANG = 'ru';
const DATA = JSON.parse(document.getElementById('pageData').textContent);
const COLUMNS = DATA.columns;
const CLUBS = DATA.clubs;

// tier shading: darkest = first column of each category (highest division present)
function tierClassFor(catKey) {
  const catCols = COLUMNS.filter(c => c.cat === catKey);
  const idx = {};
  catCols.forEach((c, i) => idx[c.key] = Math.min(i, 3));
  return idx;
}
const TIER = {};
[...new Set(COLUMNS.map(c => c.cat))].forEach(cat => Object.assign(TIER, tierClassFor(cat)));

function buildHead() {
  const catRow = document.getElementById('catRow');
  const headRow = document.getElementById('headRow');
  const corner = document.createElement('th');
  corner.className = 'club-head';
  corner.textContent = LANG[CURLANG].club;
  headRow.appendChild(corner);

  let lastCat = null, span = 0, catTh = null;
  const catThs = [];
  COLUMNS.forEach(col => {
    if (col.cat !== lastCat) {
      if (catTh) catThs.push([catTh, span]);
      catTh = document.createElement('th');
      catTh.textContent = col.cat_label;
      lastCat = col.cat;
      span = 0;
    }
    span++;
    const th = document.createElement('th');
    th.textContent = col.div_label;
    th.dataset.key = col.key;
    th.addEventListener('click', () => sortBy(col.key));
    headRow.appendChild(th);
  });
  if (catTh) catThs.push([catTh, span]);
  catThs.forEach(([th, span]) => { th.colSpan = span; catRow.appendChild(th); });

  const totalTh = document.createElement('th');
  totalTh.className = 'total-head';
  totalTh.textContent = LANG[CURLANG].total;
  totalTh.dataset.key = '__total';
  totalTh.addEventListener('click', () => sortBy('__total'));
  headRow.appendChild(totalTh);
}

let sortKey = '__total', sortDir = -1;
function sortBy(key) {
  sortDir = (sortKey === key) ? -sortDir : -1;
  sortKey = key;
  render();
}

function cellValue(club, key) {
  if (key === '__total') return club.total_teams;
  const c = club[key];
  return c ? c.n : 0;
}

function render() {
  const q = document.getElementById('searchBox').value.trim().toLowerCase();
  const onlyPresent = document.getElementById('presentToggle').classList.contains('active');

  let rows = CLUBS.filter(c => !q || c.club.toLowerCase().includes(q));
  if (onlyPresent) rows = rows.filter(c => c.total_teams > 0);
  rows = rows.slice().sort((a, b) => sortDir * (cellValue(a, sortKey) - cellValue(b, sortKey)) || a.club.localeCompare(b.club));

  document.getElementById('resultCount').textContent = rows.length.toLocaleString() + ' ' + LANG[CURLANG].clubsWord;

  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = COLUMNS.length + 2;
    td.className = 'empty-state';
    td.textContent = LANG[CURLANG].noResults;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  const frag = document.createDocumentFragment();
  rows.forEach(club => {
    const tr = document.createElement('tr');

    const clubTd = document.createElement('td');
    clubTd.className = 'club-cell';
    const inner = document.createElement('div');
    inner.className = 'club-cell-inner';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'club-name';
    nameSpan.textContent = club.club;
    inner.appendChild(nameSpan);
    if (club.venue && club.venue.maps) {
      const a = document.createElement('a');
      a.className = 'pin';
      a.href = club.venue.maps;
      a.target = '_blank';
      a.rel = 'noopener';
      a.title = `${club.venue.venue} — ${club.venue.n}/${club.venue.total} partidos (${club.venue.pct}%)`;
      a.textContent = '\u{1F4CD} ' + club.venue.pct + '%';
      inner.appendChild(a);
    }
    clubTd.appendChild(inner);
    tr.appendChild(clubTd);

    COLUMNS.forEach(col => {
      const td = document.createElement('td');
      td.className = 'cell lvl-' + TIER[col.key];
      const v = club[col.key];
      if (v) {
        const chip = document.createElement('span');
        chip.className = 'chip' + (v.pos === 1 ? ' leader' : '');
        chip.title = v.grp || '';
        chip.innerHTML = `<span class="n">${v.n}&times;</span><span class="p">${v.pos}/${v.size}</span>`;
        td.appendChild(chip);
      } else {
        const span = document.createElement('span');
        span.className = 'empty';
        span.textContent = '—';
        td.appendChild(span);
      }
      tr.appendChild(td);
    });

    const totalTd = document.createElement('td');
    totalTd.className = 'total-cell';
    totalTd.innerHTML = `<strong>${club.total_teams}</strong> ${LANG[CURLANG].of} ${club.total_divs}`;
    tr.appendChild(totalTd);

    frag.appendChild(tr);
  });
  tbody.appendChild(frag);
}

const STAT_LABELS = {
  ru: ['клубов', 'команд (Бенхамин+Пребенхамин)', 'дивизионов охвачено'],
  es: ['clubes', 'equipos (Benjamín+Prebenjamín)', 'divisiones cubiertas'],
};
function renderStats() {
  const nums = [CLUBS.length, CLUBS.reduce((s, c) => s + c.total_teams, 0), COLUMNS.length];
  document.getElementById('stats').innerHTML = STAT_LABELS[CURLANG].map((l, idx) =>
    `<div class="stat"><div class="n">${nums[idx].toLocaleString()}</div><div class="l">${l}</div></div>`
  ).join('');
}

document.getElementById('searchBox').addEventListener('input', render);
document.getElementById('presentToggle').addEventListener('click', function () {
  this.classList.toggle('active');
  render();
});

buildHead();
renderStats();
render();

const I18N_ES = %I18N_ES_JSON%;
document.querySelectorAll('.lang-opt').forEach(function (btn) {
  btn.addEventListener('click', function () {
    CURLANG = btn.getAttribute('data-lang-btn');
    document.querySelectorAll('.lang-opt').forEach(function (b) {
      b.classList.toggle('is-active', b === btn);
    });
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      if (el.dataset.ru === undefined) el.dataset.ru = el.innerHTML;
      if (CURLANG === 'ru') {
        el.innerHTML = el.dataset.ru;
      } else if (Object.prototype.hasOwnProperty.call(I18N_ES, el.dataset.i18n)) {
        el.innerHTML = I18N_ES[el.dataset.i18n];
      }
    });
    document.getElementById('searchBox').placeholder = LANG[CURLANG].searchPh;
    document.getElementById('headRow').innerHTML = '';
    document.getElementById('catRow').innerHTML = '<th class="corner"></th>';
    buildHead();
    renderStats();
    render();
  });
});
</script>
</body>
</html>
"""


I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; Temporada %SEASON% &middot; Fútbol-7",
    "h1": "Mapa de clubes por división — Benjamín &amp; Prebenjamín",
    "lede": "Cada fila es un club, cada columna una división. La celda muestra cuántos equipos tiene el club ahí y la mejor posición alcanzada (de cualquiera de sus equipos) en su grupo. El tono de fondo se oscurece hacia las divisiones más altas.",
    "onlyPresent": "Solo con presencia visible",
    "legend1": "División más alta disponible",
    "legend2": "División más baja disponible",
    "legend3": "Líder de su grupo",
    "legend4": "Celda: nº de equipos del club ahí &middot; mejor posición/tamaño del grupo",
    "legend5": '&#128205; = sede más frecuente en Google Maps (formato "sede" rotativo — no necesariamente su campo fijo, ver nota al pie)',
    "foot1": 'Alcance: clubes con al menos un equipo Benjamín o Prebenjamín en fútbol-7 con clasificación registrada, temporada %SEASON%. Posiciones de la fase regular únicamente. Fuente: <code>output/processed/rffm/{teams,competitions,standings,matches,venues}.csv</code>.',
    "foot2": '<strong>Sobre el &#128205;:</strong> Benjamín/Prebenjamín suele jugarse en formato <em>"sede"</em> — los partidos "de casa" rotan entre varios campos asignados por jornada, no un estadio fijo del club. El pin abre en Google Maps el campo donde <em>más veces</em> jugó de local el equipo/los equipos de ese club en estas categorías esta temporada, con el % de sus partidos como local que se disputaron ahí — tómalo como orientativo, no como dirección oficial.',
}


def build_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    i18n_es = {k: v.replace("%SEASON%", data["season"]) for k, v in I18N_ES.items()}
    return (HTML
            .replace("%DATA_JSON%", data_json)
            .replace("%SEASON%", data["season"])
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%LANG_SWITCH%", lang_switch_html())
            .replace("%I18N_ES_JSON%", json.dumps(i18n_es, ensure_ascii=False)))


def main():
    parser = argparse.ArgumentParser(description="RFFM club x division matrix report")
    parser.add_argument("--season", default=None, help="defaults to the latest season with a complete core crawl")
    parser.add_argument("--output", default="reports/club_division_map.html")
    args = parser.parse_args()

    season = args.season or latest_core_season()
    print(f"Building club/division map for season {season}")
    data = load_data(season)
    print(f"  {len(data['clubs'])} clubs, {len(data['columns'])} columns")

    out = Path(__file__).parent.parent / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(data), encoding="utf-8")
    print(f"Report written to {out}")


if __name__ == "__main__":
    main()
