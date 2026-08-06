#!/usr/bin/env python3
"""
Cross-season comparison report for RFFM data.
All data is embedded as JSON; age-category and division filters run in the
browser via Chart.js — no page reload.

Usage:
    python analysis_scripts/season_comparison.py
    python analysis_scripts/season_comparison.py --output reports/season_comparison.html
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from site_theme import FONT_LINKS, lang_switch_html

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
SEASONS = sorted(
    [d.name for d in BASE.iterdir() if d.is_dir() and len(d.name) == 9 and "-" in d.name]
)

CAT_ORDER = [
  "DEBUTANTE", "PREBENJAMIN", "BENJAMIN", "ALEVIN", "INFANTIL", "CADETE",
    "JUVENIL", "AFICIONADO", "SENIOR", "UNIVERSITARIO", "VETERANOS", "OTHER",
]
CAT_LABELS = {
  "DEBUTANTE": "Debutante",
    "PREBENJAMIN": "Prebenjamín", "BENJAMIN": "Benjamín", "ALEVIN": "Alevín",
    "INFANTIL": "Infantil", "CADETE": "Cadete", "JUVENIL": "Juvenil",
    "AFICIONADO": "Aficionado", "SENIOR": "Sénior",
    "UNIVERSITARIO": "Universitario", "VETERANOS": "Veteranos", "OTHER": "Other",
}
DIV_ORDER = [
    "PRIMERA DIVISION AUTONOMICA", "DIVISION DE HONOR", "SUPERLIGA", "LIGA NACIONAL",
    "TERCERA FEDERACION", "SEGUNDA DIVISION B", "PREFERENTE",
    "PRIMERA", "SEGUNDA", "TERCERA",
    "FASE ZONAL", "CAMPEONATO UNIVERSITARIO", "LIGA UNIVERSITARIA", "OTHER",
]
DIV_LABELS = {
    "PRIMERA DIVISION AUTONOMICA": "1ª Div. Autonómica",
    "DIVISION DE HONOR": "División de Honor",
    "SUPERLIGA": "Superliga",
    "LIGA NACIONAL": "Liga Nacional",
    "TERCERA FEDERACION": "3ª Federación",
    "SEGUNDA DIVISION B": "2ª Div. B",
    "PREFERENTE": "Preferente",
    "PRIMERA": "1ª División",
    "SEGUNDA": "2ª División",
    "TERCERA": "3ª División",
    "FASE ZONAL": "Fase Zonal",
    "CAMPEONATO UNIVERSITARIO": "Camp. Universitario",
    "LIGA UNIVERSITARIA": "Liga Universitaria",
    "OTHER": "Other",
}


def norm_id(v):
    try:
        return str(int(float(str(v))))
    except (ValueError, TypeError):
        return None


def load_all_data() -> dict:
    """
    Returns a dict ready for JSON embedding:
      seasons, all_cats, all_divs, all_gts, cat_labels, div_labels,
      first_season_for_cat, season_clubs, buckets
    """
    all_cats_seen: set = set()
    all_divs_seen: set = set()
    all_gts_seen: set = set()
    first_season_for_cat: dict = {}
    season_clubs: dict = {}
    buckets: list = []

    for season in SEASONS:
        d = BASE / season
        matches   = pd.read_csv(d / "matches.csv", dtype=str)
        teams     = pd.read_csv(d / "teams.csv", dtype=str)
        comps     = pd.read_csv(d / "competitions.csv", dtype=str)

        comps["category_base"]   = comps["category_base"].fillna("OTHER")
        comps["division_level"]  = comps["division_level"].fillna("OTHER")
        comps["is_fem"]          = comps["is_femenino"].str.lower() == "true"

        # Normalize team IDs (pandas nullable-int artifact: "123.0" → "123")
        matches["hid"] = matches["home_team_id"].map(norm_id)
        matches["aid"] = matches["away_team_id"].map(norm_id)
        teams["tid"]   = teams["team_id"].map(norm_id)
        tid_to_club    = dict(zip(teams["tid"], teams["club_name_raw"]))

        # Build per-season club index (sorted, deduplicatable in JS)
        season_club_list = sorted(teams["club_name_raw"].dropna().unique().tolist())
        season_clubs[season] = season_club_list
        club_to_idx = {c: i for i, c in enumerate(season_club_list)}

        # Women competitions
        fem_comp_ids = set(comps.loc[comps["is_fem"], "competition_id"].tolist())

        # Group competitions by (category_base, division_level)
        comp_groups = (
            comps.groupby(["category_base", "division_level"])["competition_id"]
            .apply(list).to_dict()
        )

        for (cat, div), comp_ids_list in comp_groups.items():
            all_cats_seen.add(cat)
            all_divs_seen.add(div)
            if cat not in first_season_for_cat:
                first_season_for_cat[cat] = season

            comp_ids_set = set(comp_ids_list)
            mb = matches[matches["competition_id"].isin(comp_ids_set)]
            if mb.empty:
                continue

            # Split into game-type buckets so game-type filters can affect all metrics.
            for gt_raw, mb_gt in mb.groupby("game_type", dropna=False):
                gt = str(gt_raw).strip() if pd.notna(gt_raw) else "UNKNOWN"
                if not gt or gt.lower() == "nan":
                    gt = "UNKNOWN"
                all_gts_seen.add(gt)

                played_gt = mb_gt[mb_gt["is_finished"].str.lower() == "true"]
                hs_gt = pd.to_numeric(played_gt["home_score"], errors="coerce")
                as_gt = pd.to_numeric(played_gt["away_score"], errors="coerce")
                goals_gt = int((hs_gt.sum() + as_gt.sum()))
                wm_gt = int(mb_gt["competition_id"].isin(fem_comp_ids).sum())

                team_ids_gt = set(mb_gt["hid"].dropna()) | set(mb_gt["aid"].dropna())
                clubs_set_gt = {tid_to_club[t] for t in team_ids_gt if t in tid_to_club}
                ci_gt = sorted({club_to_idx[c] for c in clubs_set_gt if c in club_to_idx})
                vi_count_gt = int(mb_gt["venue_id"].dropna().nunique())
                venue_ids_gt = sorted(mb_gt["venue_id"].dropna().unique().tolist())

                buckets.append({
                    "s":  season,
                    "c":  cat,
                    "d":  div,
                    "gt": gt,
                    "mp": int(len(played_gt)),
                    "mu": int(len(mb_gt) - len(played_gt)),
                    "g":  goals_gt,
                    "wm": wm_gt,
                    "co": len(comp_ids_list),
                    "coi": sorted(comp_ids_set),
                    "t":  len(team_ids_gt),
                    "ti": sorted(team_ids_gt),
                    "ci": ci_gt,
                    "vi": vi_count_gt,
                    "vii": venue_ids_gt,
                })

    # Sort cats and divs by preferred order (unknowns appended at end)
    def order_key(lst, v):
        return lst.index(v) if v in lst else len(lst)

    all_cats = sorted(all_cats_seen, key=lambda x: order_key(CAT_ORDER, x))
    all_divs = sorted(all_divs_seen, key=lambda x: order_key(DIV_ORDER, x))
    all_gts = sorted(all_gts_seen)

    return {
        "seasons":              SEASONS,
        "all_cats":             all_cats,
        "all_divs":             all_divs,
        "all_gts":              all_gts,
        "cat_labels":           {c: CAT_LABELS.get(c, c) for c in all_cats},
        "div_labels":           {d: DIV_LABELS.get(d, d) for d in all_divs},
        "first_season_for_cat": first_season_for_cat,
        "season_clubs":         season_clubs,
        "buckets":              buckets,
    }


# ---------------------------------------------------------------------------
# HTML / JS template
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>RFFM — сравнение сезонов</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.27.0/plotly.min.js"></script>
%FONT_LINKS%
<style>
:root{
  --bg:#f5f6f8; --surface:#ffffff; --ink:#1a1d23; --ink-soft:#5a6270; --ink-faint:#8b93a3;
  --accent:#4e79a7; --accent-soft:#e2e8f4; --line:#dde3ed; --line-strong:#c8d0de;
  --shadow: 0 1px 2px rgba(20,20,20,0.06); --row-hover:#f8f9fc;
  --warn-bg:#fff8e8; --warn-line:#f28e2b; --bad-bg:#fde8e8; --bad-line:#e15759;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#14171c; --surface:#1c2028; --ink:#eef0f4; --ink-soft:#a7aebb; --ink-faint:#6c7280;
    --accent:#7aa7d9; --accent-soft:#25344a; --line:#2b3040; --line-strong:#3a4058;
    --shadow: 0 1px 3px rgba(0,0,0,0.4); --row-hover:#232837;
    --warn-bg:#332a10; --warn-line:#e3a45c; --bad-bg:#3a2226; --bad-line:#e97a7c;
  }
}
:root[data-theme="dark"]{
  --bg:#14171c; --surface:#1c2028; --ink:#eef0f4; --ink-soft:#a7aebb; --ink-faint:#6c7280;
  --accent:#7aa7d9; --accent-soft:#25344a; --line:#2b3040; --line-strong:#3a4058;
  --shadow: 0 1px 3px rgba(0,0,0,0.4); --row-hover:#232837;
  --warn-bg:#332a10; --warn-line:#e3a45c; --bad-bg:#3a2226; --bad-line:#e97a7c;
}
:root[data-theme="light"]{
  --bg:#f5f6f8; --surface:#ffffff; --ink:#1a1d23; --ink-soft:#5a6270; --ink-faint:#8b93a3;
  --accent:#4e79a7; --accent-soft:#e2e8f4; --line:#dde3ed; --line-strong:#c8d0de;
  --shadow: 0 1px 2px rgba(20,20,20,0.06); --row-hover:#f8f9fc;
  --warn-bg:#fff8e8; --warn-line:#f28e2b; --bad-bg:#fde8e8; --bad-line:#e15759;
}
*, *::before, *::after { box-sizing: border-box; }
body { font-family: 'PT Sans', system-ui, sans-serif; max-width: 1160px; margin: 0 auto; padding: 0 1rem 3rem; color: var(--ink); background: var(--bg); }
h1 { font-family: 'Oswald', system-ui, sans-serif; font-weight: 700; text-transform: uppercase; font-size: 1.7rem; margin: 1.2rem 0 .3rem; }
h2 { font-family: 'Oswald', system-ui, sans-serif; font-weight: 700; text-transform: uppercase; font-size: 1.1rem; margin: 2rem 0 .6rem; color: var(--accent); border-bottom: 1px solid var(--line); padding-bottom: .3rem; }
small { color: var(--ink-faint); font-weight: normal; }
a.back{font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:var(--accent); text-decoration:none;}
.masthead-row{display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:0.75rem;}
.lang-switch{ display:inline-flex; border:1px solid var(--line-strong); border-radius:999px; overflow:hidden; margin-top:1.1rem; }
.lang-opt{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:0.04em;
  padding:4px 12px; background:var(--surface); color:var(--ink-soft); border:none; cursor:pointer; }
.lang-opt.is-active{background:var(--accent); color:#fff;}

/* ── filter panel ── */
.filter-panel {
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: 1rem 1.2rem; margin: 1rem 0;
}
.filter-row { display: flex; align-items: flex-start; gap: 1rem; margin-bottom: .7rem; flex-wrap: wrap; }
.filter-row:last-child { margin-bottom: 0; }
.filter-label { font-size: .78rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; color: var(--ink-soft); white-space: nowrap; padding-top: .35rem; min-width: 90px; }
.filter-chips { display: flex; flex-wrap: wrap; gap: .35rem; flex: 1; }
.chip {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .28rem .65rem; border-radius: 999px; font-size: .8rem; cursor: pointer;
  border: 1.5px solid var(--line-strong); background: var(--accent-soft); color: var(--ink-soft);
  user-select: none; transition: background .12s, border-color .12s, color .12s;
}
.chip.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.chip:hover:not(.active) { background: var(--accent-soft); border-color: var(--ink-faint); }
.chip .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; opacity: .7; }
.quick-btns { display: flex; gap: .3rem; align-items: center; padding-top: .25rem; }
.quick-btns button {
  font-size: .72rem; padding: .2rem .55rem; border: 1px solid var(--line-strong); border-radius: 4px;
  background: var(--surface); color: var(--ink-soft); cursor: pointer; white-space: nowrap;
}
.quick-btns button:hover { background: var(--accent-soft); }

/* ── coverage note ── */
.coverage-note {
  font-size: .78rem; background: var(--warn-bg); border-left: 3px solid var(--warn-line);
  padding: .5rem .8rem; border-radius: 4px; margin-top: .6rem; line-height: 1.6;
  display: none; color: var(--ink);
}
.coverage-note.visible { display: block; }
.empty-note {
  font-size: .82rem; background: var(--bad-bg); border-left: 3px solid var(--bad-line);
  padding: .5rem .8rem; border-radius: 4px; margin-top: .6rem;
  display: none; color: var(--ink);
}
.empty-note.visible { display: block; }

/* ── kpi row ── */
.kpi-row { display: flex; flex-wrap: wrap; gap: .8rem; margin: .8rem 0 1.2rem; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: .7rem 1rem; min-width: 130px; box-shadow: var(--shadow); }
.kpi .val { font-family: 'JetBrains Mono', monospace; font-size: 1.5rem; font-weight: 700; color: var(--accent); line-height: 1; }
.kpi .lbl { font-size: .72rem; color: var(--ink-soft); margin-top: .25rem; }

/* ── charts ── */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(470px, 1fr)); gap: 1.2rem; }
.chart-wrap { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: .9rem 1.1rem 1.2rem; box-shadow: var(--shadow); }
.chart-wrap h3 { font-size: .88rem; color: var(--ink-soft); margin: 0 0 .5rem; font-weight: 600; }

/* ── table ── */
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .8rem; background: var(--surface); border-radius: 8px; overflow: hidden; border: 1px solid var(--line); }
th, td { border-bottom: 1px solid var(--line); padding: .38rem .65rem; text-align: right; white-space: nowrap; }
th { background: var(--accent); color: #fff; font-size: .75rem; text-align: center; border-bottom: none; }
td:first-child, th:first-child { text-align: left; }
tr:last-child td { border-bottom: none; }
tr:nth-child(even) td { background: var(--row-hover); }
</style>
</head>
<body>

<a class="back" href="index.html">&larr; RFFM data</a>
<div class="masthead-row">
  <div>
    <h1><span data-i18n="h1">RFFM — сравнение сезонов</span></h1>
    <p style="font-size:.78rem;color:var(--ink-faint);margin:.2rem 0 .8rem">
      <span data-i18n="datalede">Данные: <code>output/processed/rffm/*/</code> &nbsp;|&nbsp; Сезоны:</span> <span id="seasons-list"></span>
    </p>
  </div>
  %LANG_SWITCH%
</div>

<div class="filter-panel">
  <div class="filter-row">
    <span class="filter-label" data-i18n="lbl_cats">Возраст</span>
    <div class="filter-chips" id="chips-cats"></div>
    <div class="quick-btns">
      <button onclick="quickSelect('cats','all')" data-i18n="btn_all1">Все</button>
      <button onclick="quickSelect('cats','none')" data-i18n="btn_none1">Нет</button>
    </div>
  </div>
  <div class="filter-row">
    <span class="filter-label" data-i18n="lbl_divs">Дивизион</span>
    <div class="filter-chips" id="chips-divs"></div>
    <div class="quick-btns">
      <button onclick="quickSelect('divs','all')" data-i18n="btn_all2">Все</button>
      <button onclick="quickSelect('divs','none')" data-i18n="btn_none2">Нет</button>
    </div>
  </div>
  <div class="filter-row">
    <span class="filter-label" data-i18n="lbl_gts">Тип игры</span>
    <div class="filter-chips" id="chips-gts"></div>
    <div class="quick-btns">
      <button onclick="quickSelect('gts','all')" data-i18n="btn_all3">Все</button>
      <button onclick="quickSelect('gts','none')" data-i18n="btn_none3">Нет</button>
    </div>
  </div>
  <div class="coverage-note" id="coverage-note"></div>
  <div class="empty-note" id="empty-note" data-i18n="empty_note">Нет данных по текущему фильтру — выберите хотя бы одну возрастную категорию, дивизион и тип игры.</div>
</div>

<h2><span data-i18n="h2_kpi">Ключевые цифры — последний сезон</span> <span id="kpi-season-label" style="font-weight:normal;font-size:.9rem"></span></h2>
<div class="kpi-row" id="kpi-row"></div>

<h2 data-i18n="h2_trends">Динамика по сезонам</h2>
<div class="grid">
  <div class="chart-wrap"><h3 data-i18n="ch_matches">Матчи по сезонам (сыграно / не сыграно)</h3><canvas id="ch-matches"></canvas></div>
  <div class="chart-wrap"><h3 data-i18n="ch_clubs">Клубы и команды по сезонам</h3><canvas id="ch-clubs"></canvas></div>
  <div class="chart-wrap"><h3 data-i18n="ch_comps">Соревнования по сезонам</h3><canvas id="ch-comps"></canvas></div>
  <div class="chart-wrap"><h3 data-i18n="ch_goals">Голы по сезонам</h3><canvas id="ch-goals"></canvas></div>
  <div class="chart-wrap"><h3 data-i18n="ch_avg">Среднее число голов за сыгранный матч</h3><canvas id="ch-avg"></canvas></div>
  <div class="chart-wrap"><h3 data-i18n="ch_women">Доля женского футбола (% всех матчей)</h3><canvas id="ch-women"></canvas></div>
</div>

<h2 data-i18n="h2_breakdown">Разбивка по категориям и форматам — последний сезон</h2>
<div class="grid">
  <div class="chart-wrap"><h3 data-i18n="ch_catlatest">Матчи по возрастной категории (последний сезон)</h3><canvas id="ch-cat-latest"></canvas></div>
  <div class="chart-wrap"><h3 data-i18n="ch_gtlatest">Матчи по типу игры (последний сезон)</h3><canvas id="ch-gt-latest"></canvas></div>
  <div class="chart-wrap"><h3 data-i18n="ch_divlatest">Матчи по дивизиону (последний сезон)</h3><canvas id="ch-div-latest"></canvas></div>
  <div class="chart-wrap" style="grid-column: 1 / -1"><h3 data-i18n="ch_catstacked">Матчи по возрастной категории — все сезоны (стек)</h3><canvas id="ch-cat-stacked"></canvas></div>
</div>

<h2><span data-i18n="h2_heatmap">Возрастная категория × дивизион — все данные</span> <small style="font-weight:normal;font-size:.8rem;color:var(--ink-faint)" data-i18n="heatmap_note">(с учётом фильтра по типу игры)</small></h2>
<div class="chart-wrap" style="padding-bottom:.5rem">
  <div id="heatmap-div" style="width:100%;min-height:420px"></div>
</div>

<h2 data-i18n="h2_summary">Сводная таблица</h2>
<div class="table-wrap"><table id="summary-table"></table></div>

<script>
const DATA = %DATA_JSON%;
let CURLANG = 'ru';
const LANG = {
  ru: {
    played: 'Сыграно', unplayed: 'Не сыграно', clubs: 'Клубы', teams: 'Команды',
    competitions: 'Соревнования', goals: 'Голы', avgGoals: 'Голов/матч', womenPct: 'Матчи среди женщин, %',
    matches: 'Матчи',
    kpi: ['матчей сыграно', 'клубов', 'команд', 'соревнований', 'голов забито', 'голов/матч в среднем', 'женских матчей', 'площадок'],
    thead: ['Сезон', 'Охват', 'Сыграно', 'Не сыграно', 'Клубы', 'Команды', 'Соревнования', 'Голы', 'Голов/матч', 'Женских, %', 'Площадки'],
    coverage: n => `&#9432; Ограниченный охват: ${n}`,
    availFrom: (label, season) => `<b>${label}</b>: доступно с сезона <b>${season}</b>`,
  },
  es: {
    played: 'Disputados', unplayed: 'Sin disputar', clubs: 'Clubes', teams: 'Equipos',
    competitions: 'Competiciones', goals: 'Goles', avgGoals: 'Goles/partido', womenPct: "Partidos femeninos, %",
    matches: 'Partidos',
    kpi: ['partidos disputados', 'clubes', 'equipos', 'competiciones', 'goles marcados', 'goles/partido de media', 'partidos femeninos', 'sedes'],
    thead: ['Temporada', 'Alcance', 'Disputados', 'Sin disputar', 'Clubes', 'Equipos', 'Competiciones', 'Goles', 'Goles/partido', 'Femenino, %', 'Sedes'],
    coverage: n => `&#9432; Cobertura limitada: ${n}`,
    availFrom: (label, season) => `<b>${label}</b>: disponible desde la temporada <b>${season}</b>`,
  },
};

const COLORS = [
  "#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f",
  "#edc948","#b07aa1","#ff9da7","#9c755f","#bab0ac","#4dc9f6","#f67019",
];
const CAT_COLORS = {};
DATA.all_cats.forEach((c, i) => { CAT_COLORS[c] = COLORS[i % COLORS.length]; });
const GT_COLORS = {};
DATA.all_gts.forEach((gt, i) => { GT_COLORS[gt] = COLORS[i % COLORS.length]; });

// ── filter state ──
const STATE = {
  cats: new Set(DATA.all_cats),
  divs: new Set(DATA.all_divs),
  gts: new Set(DATA.all_gts),
};

// ── build filter chips ──
function buildChips(containerId, items, stateSet, labelMap, colorMap) {
  const el = document.getElementById(containerId);
  items.forEach(val => {
    const chip = document.createElement('span');
    chip.className = 'chip active';
    chip.dataset.val = val;
    const dot = document.createElement('span');
    dot.className = 'dot';
    if (colorMap) dot.style.background = colorMap[val] || '#999';
    chip.appendChild(dot);
    chip.appendChild(document.createTextNode(labelMap[val] || val));
    chip.addEventListener('click', () => {
      if (stateSet.has(val)) stateSet.delete(val); else stateSet.add(val);
      chip.classList.toggle('active', stateSet.has(val));
      recompute();
    });
    el.appendChild(chip);
  });
}

function quickSelect(group, action) {
  const stateSet =
    group === 'cats' ? STATE.cats :
    group === 'divs' ? STATE.divs :
    STATE.gts;
  const items =
    group === 'cats' ? DATA.all_cats :
    group === 'divs' ? DATA.all_divs :
    DATA.all_gts;
  const container = document.getElementById('chips-' + group);
  items.forEach(val => {
    if (action === 'all') stateSet.add(val); else stateSet.delete(val);
  });
  container.querySelectorAll('.chip').forEach(chip => {
    chip.classList.toggle('active', stateSet.has(chip.dataset.val));
  });
  recompute();
}

// ── chart helpers ──
const CHARTS = {};

function makeBar(id, datasets, labels, opts) {
  return new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels: labels || DATA.seasons, datasets },
    options: {
      responsive: true,
      animation: false,
      plugins: {
        legend: { display: opts?.legend ?? (datasets.length > 1), position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: { mode: 'index' },
      },
      scales: {
        x: { stacked: opts?.stacked ?? false, ticks: { font: { size: 11 } } },
        y: { stacked: opts?.stacked ?? false, beginAtZero: true, ticks: { font: { size: 11 } } },
      },
    },
  });
}

function makeLine(id, datasets) {
  return new Chart(document.getElementById(id), {
    type: 'line',
    data: { labels: DATA.seasons, datasets },
    options: {
      responsive: true,
      animation: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { font: { size: 11 } } }, x: { ticks: { font: { size: 11 } } } },
    },
  });
}

function setDs(chart, idx, data) { chart.data.datasets[idx].data = data; }
function setLabels(chart, labels) { chart.data.labels = labels; }

function initCharts() {
  const empty8 = () => DATA.seasons.map(() => 0);

  CHARTS.matches = makeBar('ch-matches', [
    { label: LANG[CURLANG].played,   data: empty8(), backgroundColor: COLORS[0] },
    { label: LANG[CURLANG].unplayed, data: empty8(), backgroundColor: COLORS[9] },
  ], null, { stacked: true });

  CHARTS.clubs = makeBar('ch-clubs', [
    { label: LANG[CURLANG].clubs, data: empty8(), backgroundColor: COLORS[1] },
    { label: LANG[CURLANG].teams, data: empty8(), backgroundColor: COLORS[2] },
  ]);

  CHARTS.comps = makeBar('ch-comps', [
    { label: LANG[CURLANG].competitions, data: empty8(), backgroundColor: COLORS[3] },
  ]);

  CHARTS.goals = makeBar('ch-goals', [
    { label: LANG[CURLANG].goals, data: empty8(), backgroundColor: COLORS[4] },
  ]);

  CHARTS.avg = makeLine('ch-avg', [{
    label: LANG[CURLANG].avgGoals, data: empty8(),
    borderColor: COLORS[0], backgroundColor: COLORS[0] + '33',
    fill: true, tension: 0.3, pointRadius: 4,
  }]);

  CHARTS.women = makeLine('ch-women', [{
    label: LANG[CURLANG].womenPct, data: empty8(),
    borderColor: COLORS[6], backgroundColor: COLORS[6] + '33',
    fill: true, tension: 0.3, pointRadius: 4,
  }]);

  CHARTS.catLatest = makeBar('ch-cat-latest',
    [{ label: LANG[CURLANG].matches, data: [], backgroundColor: [] }],
    [], { legend: false });

  CHARTS.gtLatest = makeBar('ch-gt-latest',
    [{ label: LANG[CURLANG].matches, data: [], backgroundColor: [] }],
    [], { legend: false });

  CHARTS.catStacked = makeBar('ch-cat-stacked', [], null, { stacked: true, legend: true });

  CHARTS.divLatest = makeBar('ch-div-latest',
    [{ label: LANG[CURLANG].matches, data: [], backgroundColor: [] }],
    [], { legend: false });

  // Heatmap — built once, never updated by filters
  buildHeatmap();
}

// ── heatmap (static, all data) ──
function buildHeatmap() {
  updateHeatmap();
}

function updateHeatmap() {
  const cats = DATA.all_cats;
  const divs = DATA.all_divs;

  // z[cat_idx][div_idx] = total matches
  const mat = cats.map(c =>
    divs.map(d =>
      DATA.buckets.filter(b => b.c === c && b.d === d && STATE.gts.has(b.gt))
                  .reduce((s, b) => s + b.mp + b.mu, 0)
    )
  );

  // Replace zeros with null so Plotly renders them as empty cells
  const z = mat.map(row => row.map(v => v === 0 ? null : v));
  const zText = mat.map(row => row.map(v => v === 0 ? '' : v.toLocaleString()));

  const catLabels = cats.map(c => DATA.cat_labels[c] || c);
  const divLabels = divs.map(d => DATA.div_labels[d] || d);

  Plotly.react('heatmap-div', [{
    type: 'heatmap',
    z,
    x: divLabels,
    y: catLabels,
    text: zText,
    texttemplate: '%{text}',
    textfont: { color: '#1f2937', size: 10 },
    colorscale: [
      [0.0, '#f7fcf5'],
      [0.2, '#e5f5e0'],
      [0.4, '#a1d99b'],
      [0.6, '#41ab5d'],
      [0.8, '#238b45'],
      [1.0, '#00441b'],
    ],
    showscale: true,
    colorbar: {
      title: { text: 'Matches', side: 'right' },
      thickness: 14,
      tickfont: { size: 10 },
    },
    hoverongaps: false,
    hovertemplate: '<b>%{y}</b> × <b>%{x}</b><br>Matches: %{z:,}<extra></extra>',
  }], {
    margin: { l: 110, r: 60, t: 20, b: 130 },
    xaxis: { tickangle: -40, tickfont: { size: 11 } },
    yaxis: { tickfont: { size: 11 }, autorange: 'reversed' },
    paper_bgcolor: '#fff',
    plot_bgcolor: '#fff',
    font: { family: 'system-ui, sans-serif' },
  }, { responsive: true, displayModeBar: false });
}

// ── main recompute ──
function recompute() {
  const seasons = DATA.seasons;

  // per-season aggregates
  const agg = {};
  seasons.forEach(s => {
    agg[s] = { mp: 0, mu: 0, g: 0, wm: 0, co: 0, t: 0, ci: new Set(), vi: 0, gt: {}, coi: new Set(), ti: new Set(), vii: new Set() };
  });

  let anyData = false;
  for (const b of DATA.buckets) {
    if (!STATE.cats.has(b.c) || !STATE.divs.has(b.d) || !STATE.gts.has(b.gt)) continue;
    const a = agg[b.s];
    a.mp += b.mp;
    a.mu += b.mu;
    a.g  += b.g;
    a.wm += b.wm;
    for (const cid of (b.coi || [])) a.coi.add(cid);
    for (const tid of (b.ti || [])) a.ti.add(tid);
    for (const vid of (b.vii || [])) a.vii.add(vid);
    for (const i of b.ci) a.ci.add(i);
    const gtTotal = b.mp + b.mu;
    a.gt[b.gt] = (a.gt[b.gt] || 0) + gtTotal;
    if (b.mp + b.mu > 0) anyData = true;
  }

  for (const s of seasons) {
    agg[s].co = agg[s].coi.size;
    agg[s].t = agg[s].ti.size;
    agg[s].vi = agg[s].vii.size;
  }

  // Keep heatmap synchronized with selected game types.
  updateHeatmap();

  document.getElementById('empty-note').classList.toggle('visible', !anyData);

  // ── trend charts ──
  setDs(CHARTS.matches, 0, seasons.map(s => agg[s].mp));
  setDs(CHARTS.matches, 1, seasons.map(s => agg[s].mu));
  CHARTS.matches.update('none');

  setDs(CHARTS.clubs, 0, seasons.map(s => agg[s].ci.size));
  setDs(CHARTS.clubs, 1, seasons.map(s => agg[s].t));
  CHARTS.clubs.update('none');

  setDs(CHARTS.comps, 0, seasons.map(s => agg[s].co));
  CHARTS.comps.update('none');

  setDs(CHARTS.goals, 0, seasons.map(s => agg[s].g));
  CHARTS.goals.update('none');

  setDs(CHARTS.avg, 0, seasons.map(s =>
    agg[s].mp > 0 ? +(agg[s].g / agg[s].mp).toFixed(2) : 0));
  CHARTS.avg.update('none');

  setDs(CHARTS.women, 0, seasons.map(s => {
    const total = agg[s].mp + agg[s].mu;
    return total > 0 ? +(agg[s].wm / total * 100).toFixed(1) : 0;
  }));
  CHARTS.women.update('none');

  // ── latest season breakdown charts ──
  const last = seasons[seasons.length - 1];

  // categories breakdown
  const catPairs = DATA.all_cats
    .filter(c => STATE.cats.has(c))
    .map(c => {
      const cnt = DATA.buckets
        .filter(b => b.s === last && b.c === c && STATE.divs.has(b.d) && STATE.gts.has(b.gt))
        .reduce((s, b) => s + b.mp + b.mu, 0);
      return [c, cnt];
    })
    .filter(([, v]) => v > 0);

  CHARTS.catLatest.data.labels = catPairs.map(([c]) => DATA.cat_labels[c]);
  CHARTS.catLatest.data.datasets[0].data = catPairs.map(([, v]) => v);
  CHARTS.catLatest.data.datasets[0].backgroundColor = catPairs.map(([c]) => CAT_COLORS[c]);
  CHARTS.catLatest.update('none');

  // division breakdown (latest season)
  const divPairs = DATA.all_divs
    .filter(d => STATE.divs.has(d))
    .map(d => {
      const cnt = DATA.buckets
        .filter(b => b.s === last && b.d === d && STATE.cats.has(b.c) && STATE.gts.has(b.gt))
        .reduce((s, b) => s + b.mp + b.mu, 0);
      return [d, cnt];
    })
    .filter(([, v]) => v > 0);

  CHARTS.divLatest.data.labels = divPairs.map(([d]) => DATA.div_labels[d]);
  CHARTS.divLatest.data.datasets[0].data = divPairs.map(([, v]) => v);
  CHARTS.divLatest.data.datasets[0].backgroundColor = divPairs.map((_, i) => COLORS[i % COLORS.length]);
  CHARTS.divLatest.update('none');

  // game type breakdown
  const gtAgg = agg[last].gt;
  const gtPairs = Object.entries(gtAgg).sort((a, b) => b[1] - a[1]);
  CHARTS.gtLatest.data.labels = gtPairs.map(([k]) => k);
  CHARTS.gtLatest.data.datasets[0].data = gtPairs.map(([, v]) => v);
  CHARTS.gtLatest.data.datasets[0].backgroundColor = gtPairs.map((_, i) => COLORS[i % COLORS.length]);
  CHARTS.gtLatest.update('none');

  // stacked categories across seasons
  const selectedCats = DATA.all_cats.filter(c => STATE.cats.has(c));
  CHARTS.catStacked.data.datasets = selectedCats.map(cat => ({
    label: DATA.cat_labels[cat],
    data: seasons.map(s =>
      DATA.buckets.filter(b => b.s === s && b.c === cat && STATE.divs.has(b.d) && STATE.gts.has(b.gt))
        .reduce((sum, b) => sum + b.mp + b.mu, 0)
    ),
    backgroundColor: CAT_COLORS[cat],
  }));
  CHARTS.catStacked.update('none');

  // ── KPI tiles ──
  const la = agg[last];
  const K = LANG[CURLANG].kpi;
  const kpiData = [
    { val: la.mp.toLocaleString(),                                           lbl: K[0] },
    { val: la.ci.size.toLocaleString(),                                      lbl: K[1] },
    { val: la.t.toLocaleString(),                                            lbl: K[2] },
    { val: la.co.toLocaleString(),                                           lbl: K[3] },
    { val: la.g.toLocaleString(),                                            lbl: K[4] },
    { val: la.mp > 0 ? (la.g / la.mp).toFixed(2) : '—',                    lbl: K[5] },
    { val: (la.mp + la.mu) > 0 ? (la.wm / (la.mp + la.mu) * 100).toFixed(1) + '%' : '—', lbl: K[6] },
    { val: la.vi.toLocaleString(),                                           lbl: K[7] },
  ];
  const kpiRow = document.getElementById('kpi-row');
  kpiRow.innerHTML = kpiData.map(k =>
    `<div class="kpi"><div class="val">${k.val}</div><div class="lbl">${k.lbl}</div></div>`
  ).join('');

  // ── summary table ──
  const TH = LANG[CURLANG].thead;
  const thead = `<thead><tr>
    <th>${TH[0]}</th><th>${TH[1]}</th><th>${TH[2]}</th><th>${TH[3]}</th>
    <th>${TH[4]}</th><th>${TH[5]}</th><th>${TH[6]}</th><th>${TH[7]}</th>
    <th>${TH[8]}</th><th>${TH[9]}</th><th>${TH[10]}</th>
  </tr></thead>`;
  const tbody = '<tbody>' + seasons.map(s => {
    const a = agg[s];
    const cats_in_season = [...new Set(DATA.buckets.filter(b => b.s === s && STATE.cats.has(b.c) && STATE.divs.has(b.d) && STATE.gts.has(b.gt)).map(b => b.c))];
    const scopeStr = cats_in_season.map(c => DATA.cat_labels[c]).join(', ') || '—';
    const avg = a.mp > 0 ? (a.g / a.mp).toFixed(2) : '—';
    const wpct = (a.mp + a.mu) > 0 ? (a.wm / (a.mp + a.mu) * 100).toFixed(1) + '%' : '—';
    return `<tr>
      <td>${s}</td><td style="font-size:.72rem;color:var(--ink-faint)">${scopeStr}</td>
      <td>${a.mp.toLocaleString()}</td><td>${a.mu.toLocaleString()}</td>
      <td>${a.ci.size.toLocaleString()}</td><td>${a.t.toLocaleString()}</td>
      <td>${a.co.toLocaleString()}</td><td>${a.g.toLocaleString()}</td>
      <td>${avg}</td><td>${wpct}</td><td>${a.vi.toLocaleString()}</td>
    </tr>`;
  }).join('') + '</tbody>';
  document.getElementById('summary-table').innerHTML = thead + tbody;

  // ── coverage note ──
  const late = DATA.all_cats.filter(c =>
    STATE.cats.has(c) && DATA.first_season_for_cat[c] && DATA.first_season_for_cat[c] > DATA.seasons[0]
  );
  const noteEl = document.getElementById('coverage-note');
  if (late.length) {
    const lines = late.map(c => LANG[CURLANG].availFrom(DATA.cat_labels[c], DATA.first_season_for_cat[c]));
    noteEl.innerHTML = LANG[CURLANG].coverage(lines.join(' &nbsp;·&nbsp; '));
    noteEl.classList.add('visible');
  } else {
    noteEl.classList.remove('visible');
    noteEl.innerHTML = '';
  }
}

// ── init ──
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('seasons-list').textContent =
    DATA.seasons[0] + ' – ' + DATA.seasons[DATA.seasons.length - 1];
  document.getElementById('kpi-season-label').textContent = '(' + DATA.seasons[DATA.seasons.length - 1] + ')';

  buildChips('chips-cats', DATA.all_cats, STATE.cats, DATA.cat_labels, CAT_COLORS);
  buildChips('chips-divs', DATA.all_divs, STATE.divs, DATA.div_labels, null);
  buildChips('chips-gts', DATA.all_gts, STATE.gts, {}, GT_COLORS);
  initCharts();
  recompute();

  const I18N_ES = %I18N_ES_JSON%;
  document.querySelectorAll('.lang-opt').forEach(btn => {
    btn.addEventListener('click', () => {
      CURLANG = btn.getAttribute('data-lang-btn');
      document.querySelectorAll('.lang-opt').forEach(b => b.classList.toggle('is-active', b === btn));
      document.querySelectorAll('[data-i18n]').forEach(el => {
        if (el.dataset.ru === undefined) el.dataset.ru = el.innerHTML;
        if (CURLANG === 'ru') el.innerHTML = el.dataset.ru;
        else if (Object.prototype.hasOwnProperty.call(I18N_ES, el.dataset.i18n)) el.innerHTML = I18N_ES[el.dataset.i18n];
      });
      document.documentElement.lang = CURLANG;
      CHARTS.matches.data.datasets[0].label = LANG[CURLANG].played;
      CHARTS.matches.data.datasets[1].label = LANG[CURLANG].unplayed;
      CHARTS.clubs.data.datasets[0].label = LANG[CURLANG].clubs;
      CHARTS.clubs.data.datasets[1].label = LANG[CURLANG].teams;
      CHARTS.comps.data.datasets[0].label = LANG[CURLANG].competitions;
      CHARTS.goals.data.datasets[0].label = LANG[CURLANG].goals;
      CHARTS.avg.data.datasets[0].label = LANG[CURLANG].avgGoals;
      CHARTS.women.data.datasets[0].label = LANG[CURLANG].womenPct;
      [CHARTS.matches, CHARTS.clubs, CHARTS.comps, CHARTS.goals, CHARTS.avg, CHARTS.women].forEach(c => c.update('none'));
      recompute();
      try { localStorage.setItem('rffm_lang', CURLANG); } catch (e) {}
    });
  });
  let saved = null;
  try { saved = localStorage.getItem('rffm_lang'); } catch (e) {}
  if (saved === 'es') document.querySelector('[data-lang-btn="es"]').click();
});
</script>
</body>
</html>
"""


I18N_ES = {
    "h1": "RFFM — comparación entre temporadas",
    "datalede": 'Datos: <code>output/processed/rffm/*/</code> &nbsp;|&nbsp; Temporadas:',
    "lbl_cats": "Categorías",
    "btn_all1": "Todas", "btn_none1": "Ninguna",
    "lbl_divs": "División",
    "btn_all2": "Todas", "btn_none2": "Ninguna",
    "lbl_gts": "Tipo de juego",
    "btn_all3": "Todos", "btn_none3": "Ninguno",
    "empty_note": "No hay datos para el filtro actual — selecciona al menos una categoría, una división y un tipo de juego.",
    "h2_kpi": "Cifras clave — última temporada",
    "h2_trends": "Tendencias entre temporadas",
    "ch_matches": "Partidos por temporada (disputados vs. sin disputar)",
    "ch_clubs": "Clubes y equipos por temporada",
    "ch_comps": "Competiciones por temporada",
    "ch_goals": "Goles totales por temporada",
    "ch_avg": "Goles de media por partido disputado",
    "ch_women": "Fútbol femenino (% de todos los partidos)",
    "h2_breakdown": "Desglose por categoría y formato — última temporada",
    "ch_catlatest": "Partidos por categoría de edad (última temporada)",
    "ch_gtlatest": "Partidos por tipo de juego (última temporada)",
    "ch_divlatest": "Partidos por división (última temporada)",
    "ch_catstacked": "Partidos por categoría de edad — todas las temporadas (apilado)",
    "h2_heatmap": "Categoría de edad × División — todos los datos",
    "heatmap_note": "(filtrado por tipo de juego)",
    "h2_summary": "Tabla resumen",
}


def build_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return (HTML
            .replace("%DATA_JSON%", data_json)
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%LANG_SWITCH%", lang_switch_html())
            .replace("%I18N_ES_JSON%", json.dumps(I18N_ES, ensure_ascii=False)))


def main():
    parser = argparse.ArgumentParser(description="RFFM cross-season comparison report")
    parser.add_argument("--output", default="reports/season_comparison.html")
    args = parser.parse_args()

    print(f"Loading {len(SEASONS)} seasons: {', '.join(SEASONS)}")
    data = load_all_data()
    print(f"  {len(data['buckets'])} buckets across all seasons")

    out = Path(__file__).parent.parent / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(data), encoding="utf-8")
    print(f"Report written to {out}")

    # Quick text summary (all categories, no filter)
    from collections import defaultdict
    agg = defaultdict(lambda: {"mp": 0, "g": 0, "ci": set()})
    for b in data["buckets"]:
        a = agg[b["s"]]
        a["mp"] += b["mp"]
        a["g"]  += b["g"]
        a["ci"].update(b["ci"])
    print("\n--- All categories ---")
    print(f"{'Season':<12} {'Played':>8} {'Goals':>8} {'Clubs':>7}")
    for s in SEASONS:
        a = agg[s]
        print(f"{s:<12} {a['mp']:>8,} {a['g']:>8,} {len(a['ci']):>7,}")


if __name__ == "__main__":
    main()
