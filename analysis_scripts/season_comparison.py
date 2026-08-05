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

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
SEASONS = sorted(
    [d.name for d in BASE.iterdir() if d.is_dir() and len(d.name) == 9 and "-" in d.name]
)

CAT_ORDER = [
    "PREBENJAMIN", "BENJAMIN", "ALEVIN", "INFANTIL", "CADETE",
    "JUVENIL", "AFICIONADO", "SENIOR", "UNIVERSITARIO", "VETERANOS", "OTHER",
]
CAT_LABELS = {
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
      seasons, all_cats, all_divs, cat_labels, div_labels,
      first_season_for_cat, season_clubs, buckets
    """
    all_cats_seen: set = set()
    all_divs_seen: set = set()
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

            played    = mb[mb["is_finished"].str.lower() == "true"]
            hs        = pd.to_numeric(played["home_score"], errors="coerce")
            as_       = pd.to_numeric(played["away_score"], errors="coerce")
            goals     = int((hs.sum() + as_.sum()))
            wm        = int(mb["competition_id"].isin(fem_comp_ids).sum())

            # Distinct teams
            team_ids  = set(mb["hid"].dropna()) | set(mb["aid"].dropna())

            # Club indices (for JS-side deduplication across buckets)
            clubs_set = {tid_to_club[t] for t in team_ids if t in tid_to_club}
            ci        = sorted({club_to_idx[c] for c in clubs_set if c in club_to_idx})

            # Venues
            vi_count  = int(mb["venue_id"].dropna().nunique())

            # Game types
            gt = {str(k): int(v) for k, v in mb["game_type"].value_counts().items()}

            buckets.append({
                "s":  season,
                "c":  cat,
                "d":  div,
                "mp": int(len(played)),
                "mu": int(len(mb) - len(played)),
                "g":  goals,
                "wm": wm,
                "co": len(comp_ids_list),
                "t":  len(team_ids),
                "ci": ci,
                "vi": vi_count,
                "gt": gt,
            })

    # Sort cats and divs by preferred order (unknowns appended at end)
    def order_key(lst, v):
        return lst.index(v) if v in lst else len(lst)

    all_cats = sorted(all_cats_seen, key=lambda x: order_key(CAT_ORDER, x))
    all_divs = sorted(all_divs_seen, key=lambda x: order_key(DIV_ORDER, x))

    return {
        "seasons":              SEASONS,
        "all_cats":             all_cats,
        "all_divs":             all_divs,
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
<html lang="en">
<head>
<meta charset="utf-8">
<title>RFFM — Season comparison</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*, *::before, *::after { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; max-width: 1160px; margin: 0 auto; padding: 0 1rem 3rem; color: #222; background: #f5f6f8; }
h1 { font-size: 1.5rem; margin: 1.2rem 0 .3rem; }
h2 { font-size: 1.1rem; margin: 2rem 0 .6rem; color: #4e79a7; border-bottom: 1px solid #dde3ed; padding-bottom: .3rem; }
small { color: #888; font-weight: normal; }

/* ── filter panel ── */
.filter-panel {
  background: #fff; border: 1px solid #dde3ed; border-radius: 10px;
  padding: 1rem 1.2rem; margin: 1rem 0;
}
.filter-row { display: flex; align-items: flex-start; gap: 1rem; margin-bottom: .7rem; flex-wrap: wrap; }
.filter-row:last-child { margin-bottom: 0; }
.filter-label { font-size: .78rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; color: #666; white-space: nowrap; padding-top: .35rem; min-width: 90px; }
.filter-chips { display: flex; flex-wrap: wrap; gap: .35rem; flex: 1; }
.chip {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .28rem .65rem; border-radius: 999px; font-size: .8rem; cursor: pointer;
  border: 1.5px solid #c8d0de; background: #f0f3f8; color: #555;
  user-select: none; transition: background .12s, border-color .12s, color .12s;
}
.chip.active { background: #4e79a7; border-color: #4e79a7; color: #fff; }
.chip:hover:not(.active) { background: #e2e8f4; border-color: #a0afcc; }
.chip .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; opacity: .7; }
.quick-btns { display: flex; gap: .3rem; align-items: center; padding-top: .25rem; }
.quick-btns button {
  font-size: .72rem; padding: .2rem .55rem; border: 1px solid #c8d0de; border-radius: 4px;
  background: #fff; color: #555; cursor: pointer; white-space: nowrap;
}
.quick-btns button:hover { background: #eef2f9; }

/* ── coverage note ── */
.coverage-note {
  font-size: .78rem; background: #fff8e8; border-left: 3px solid #f28e2b;
  padding: .5rem .8rem; border-radius: 4px; margin-top: .6rem; line-height: 1.6;
  display: none;
}
.coverage-note.visible { display: block; }
.empty-note {
  font-size: .82rem; background: #fde8e8; border-left: 3px solid #e15759;
  padding: .5rem .8rem; border-radius: 4px; margin-top: .6rem;
  display: none;
}
.empty-note.visible { display: block; }

/* ── kpi row ── */
.kpi-row { display: flex; flex-wrap: wrap; gap: .8rem; margin: .8rem 0 1.2rem; }
.kpi { background: #fff; border: 1px solid #dde3ed; border-radius: 8px; padding: .7rem 1rem; min-width: 130px; }
.kpi .val { font-size: 1.5rem; font-weight: 700; color: #4e79a7; line-height: 1; }
.kpi .lbl { font-size: .72rem; color: #777; margin-top: .25rem; }

/* ── charts ── */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(470px, 1fr)); gap: 1.2rem; }
.chart-wrap { background: #fff; border: 1px solid #dde3ed; border-radius: 8px; padding: .9rem 1.1rem 1.2rem; }
.chart-wrap h3 { font-size: .88rem; color: #444; margin: 0 0 .5rem; }

/* ── table ── */
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .8rem; background: #fff; border-radius: 8px; overflow: hidden; border: 1px solid #dde3ed; }
th, td { border-bottom: 1px solid #e5e9f0; padding: .38rem .65rem; text-align: right; white-space: nowrap; }
th { background: #4e79a7; color: #fff; font-size: .75rem; text-align: center; border-bottom: none; }
td:first-child, th:first-child { text-align: left; }
tr:last-child td { border-bottom: none; }
tr:nth-child(even) td { background: #f8f9fc; }
</style>
</head>
<body>

<h1>RFFM — Cross-season comparison</h1>
<p style="font-size:.78rem;color:#888;margin:.2rem 0 .8rem">
  Data: <code>output/processed/rffm/*/</code> &nbsp;|&nbsp; Seasons: <span id="seasons-list"></span>
</p>

<div class="filter-panel">
  <div class="filter-row">
    <span class="filter-label">Age groups</span>
    <div class="filter-chips" id="chips-cats"></div>
    <div class="quick-btns">
      <button onclick="quickSelect('cats','all')">All</button>
      <button onclick="quickSelect('cats','none')">None</button>
    </div>
  </div>
  <div class="filter-row">
    <span class="filter-label">Division</span>
    <div class="filter-chips" id="chips-divs"></div>
    <div class="quick-btns">
      <button onclick="quickSelect('divs','all')">All</button>
      <button onclick="quickSelect('divs','none')">None</button>
    </div>
  </div>
  <div class="coverage-note" id="coverage-note"></div>
  <div class="empty-note" id="empty-note">No data matches the current filter — select at least one age group and one division.</div>
</div>

<h2>Key numbers — latest season <span id="kpi-season-label" style="font-weight:normal;font-size:.9rem"></span></h2>
<div class="kpi-row" id="kpi-row"></div>

<h2>Season-over-season trends</h2>
<div class="grid">
  <div class="chart-wrap"><h3>Matches per season (played vs. unplayed)</h3><canvas id="ch-matches"></canvas></div>
  <div class="chart-wrap"><h3>Clubs and teams per season</h3><canvas id="ch-clubs"></canvas></div>
  <div class="chart-wrap"><h3>Competitions per season</h3><canvas id="ch-comps"></canvas></div>
  <div class="chart-wrap"><h3>Total goals per season</h3><canvas id="ch-goals"></canvas></div>
  <div class="chart-wrap"><h3>Average goals per played match</h3><canvas id="ch-avg"></canvas></div>
  <div class="chart-wrap"><h3>Women's football share (% of all matches)</h3><canvas id="ch-women"></canvas></div>
</div>

<h2>Category &amp; format breakdown — latest season</h2>
<div class="grid">
  <div class="chart-wrap"><h3>Matches by age category (latest season)</h3><canvas id="ch-cat-latest"></canvas></div>
  <div class="chart-wrap"><h3>Matches by game type (latest season)</h3><canvas id="ch-gt-latest"></canvas></div>
  <div class="chart-wrap" style="grid-column: 1 / -1"><h3>Matches by age category — all seasons (stacked)</h3><canvas id="ch-cat-stacked"></canvas></div>
</div>

<h2>Summary table</h2>
<div class="table-wrap"><table id="summary-table"></table></div>

<script>
const DATA = %DATA_JSON%;

const COLORS = [
  "#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f",
  "#edc948","#b07aa1","#ff9da7","#9c755f","#bab0ac","#4dc9f6","#f67019",
];
const CAT_COLORS = {};
DATA.all_cats.forEach((c, i) => { CAT_COLORS[c] = COLORS[i % COLORS.length]; });

// ── filter state ──
const STATE = {
  cats: new Set(DATA.all_cats),
  divs: new Set(DATA.all_divs),
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
  const stateSet = group === 'cats' ? STATE.cats : STATE.divs;
  const items    = group === 'cats' ? DATA.all_cats : DATA.all_divs;
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
    { label: 'Played',   data: empty8(), backgroundColor: COLORS[0] },
    { label: 'Unplayed', data: empty8(), backgroundColor: COLORS[9] },
  ], null, { stacked: true });

  CHARTS.clubs = makeBar('ch-clubs', [
    { label: 'Clubs', data: empty8(), backgroundColor: COLORS[1] },
    { label: 'Teams', data: empty8(), backgroundColor: COLORS[2] },
  ]);

  CHARTS.comps = makeBar('ch-comps', [
    { label: 'Competitions', data: empty8(), backgroundColor: COLORS[3] },
  ]);

  CHARTS.goals = makeBar('ch-goals', [
    { label: 'Goals', data: empty8(), backgroundColor: COLORS[4] },
  ]);

  CHARTS.avg = makeLine('ch-avg', [{
    label: 'Avg goals/match', data: empty8(),
    borderColor: COLORS[0], backgroundColor: COLORS[0] + '33',
    fill: true, tension: 0.3, pointRadius: 4,
  }]);

  CHARTS.women = makeLine('ch-women', [{
    label: "Women's matches %", data: empty8(),
    borderColor: COLORS[6], backgroundColor: COLORS[6] + '33',
    fill: true, tension: 0.3, pointRadius: 4,
  }]);

  CHARTS.catLatest = makeBar('ch-cat-latest',
    [{ label: 'Matches', data: [], backgroundColor: [] }],
    [], { legend: false });

  CHARTS.gtLatest = makeBar('ch-gt-latest',
    [{ label: 'Matches', data: [], backgroundColor: [] }],
    [], { legend: false });

  CHARTS.catStacked = makeBar('ch-cat-stacked', [], null, { stacked: true, legend: true });
}

// ── main recompute ──
function recompute() {
  // per-season aggregates
  const agg = {};
  DATA.seasons.forEach(s => {
    agg[s] = { mp: 0, mu: 0, g: 0, wm: 0, co: 0, t: 0, ci: new Set(), vi: 0, gt: {} };
  });

  let anyData = false;
  for (const b of DATA.buckets) {
    if (!STATE.cats.has(b.c) || !STATE.divs.has(b.d)) continue;
    const a = agg[b.s];
    a.mp += b.mp;
    a.mu += b.mu;
    a.g  += b.g;
    a.wm += b.wm;
    a.co += b.co;
    a.t  += b.t;
    a.vi += b.vi;
    for (const i of b.ci) a.ci.add(i);
    for (const [gt, cnt] of Object.entries(b.gt || {})) {
      a.gt[gt] = (a.gt[gt] || 0) + cnt;
    }
    if (b.mp + b.mu > 0) anyData = true;
  }

  document.getElementById('empty-note').classList.toggle('visible', !anyData);

  // ── trend charts ──
  const seasons = DATA.seasons;
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
        .filter(b => b.s === last && b.c === c && STATE.divs.has(b.d))
        .reduce((s, b) => s + b.mp + b.mu, 0);
      return [c, cnt];
    })
    .filter(([, v]) => v > 0);

  CHARTS.catLatest.data.labels = catPairs.map(([c]) => DATA.cat_labels[c]);
  CHARTS.catLatest.data.datasets[0].data = catPairs.map(([, v]) => v);
  CHARTS.catLatest.data.datasets[0].backgroundColor = catPairs.map(([c]) => CAT_COLORS[c]);
  CHARTS.catLatest.update('none');

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
      DATA.buckets.filter(b => b.s === s && b.c === cat && STATE.divs.has(b.d))
        .reduce((sum, b) => sum + b.mp + b.mu, 0)
    ),
    backgroundColor: CAT_COLORS[cat],
  }));
  CHARTS.catStacked.update('none');

  // ── KPI tiles ──
  const la = agg[last];
  const kpiData = [
    { val: la.mp.toLocaleString(),                                           lbl: 'matches played' },
    { val: la.ci.size.toLocaleString(),                                      lbl: 'clubs' },
    { val: la.t.toLocaleString(),                                            lbl: 'teams' },
    { val: la.co.toLocaleString(),                                           lbl: 'competitions' },
    { val: la.g.toLocaleString(),                                            lbl: 'goals scored' },
    { val: la.mp > 0 ? (la.g / la.mp).toFixed(2) : '—',                    lbl: 'avg goals/match' },
    { val: (la.mp + la.mu) > 0 ? (la.wm / (la.mp + la.mu) * 100).toFixed(1) + '%' : '—', lbl: "women's matches" },
    { val: la.vi.toLocaleString(),                                           lbl: 'venues' },
  ];
  const kpiRow = document.getElementById('kpi-row');
  kpiRow.innerHTML = kpiData.map(k =>
    `<div class="kpi"><div class="val">${k.val}</div><div class="lbl">${k.lbl}</div></div>`
  ).join('');

  // ── summary table ──
  const thead = `<thead><tr>
    <th>Season</th><th>Scope</th><th>Played</th><th>Unplayed</th>
    <th>Clubs</th><th>Teams</th><th>Competitions</th><th>Goals</th>
    <th>Avg goals/match</th><th>Women's %</th><th>Venues</th>
  </tr></thead>`;
  const tbody = '<tbody>' + seasons.map(s => {
    const a = agg[s];
    const cats_in_season = [...new Set(DATA.buckets.filter(b => b.s === s && STATE.cats.has(b.c) && STATE.divs.has(b.d)).map(b => b.c))];
    const scopeStr = cats_in_season.map(c => DATA.cat_labels[c]).join(', ') || '—';
    const avg = a.mp > 0 ? (a.g / a.mp).toFixed(2) : '—';
    const wpct = (a.mp + a.mu) > 0 ? (a.wm / (a.mp + a.mu) * 100).toFixed(1) + '%' : '—';
    return `<tr>
      <td>${s}</td><td style="font-size:.72rem;color:#666">${scopeStr}</td>
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
    const lines = late.map(c =>
      `<b>${DATA.cat_labels[c]}</b>: available from <b>${DATA.first_season_for_cat[c]}</b> onward`
    );
    noteEl.innerHTML = '&#9432; Limited coverage: ' + lines.join(' &nbsp;·&nbsp; ');
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
  initCharts();
  recompute();
});
</script>
</body>
</html>
"""


def build_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return HTML.replace("%DATA_JSON%", data_json)


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
