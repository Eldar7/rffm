#!/usr/bin/env python3
"""
"Weird scores, dominators and outsiders" — biggest blowouts, highest-scoring
matches, and the teams with the best/worst goal difference this season,
across all categories. All data embedded as JSON; category filter and
sorting run in the browser, no page reload.

Stat definitions here are this project's own (a prior one-off Claude.ai
artifact with the same title didn't have its exact methodology preserved
in the repo) — labelled explicitly in the page so they're easy to compare
against expectations and adjust.

Usage:
    python analysis_scripts/weird_scores_report.py
    python analysis_scripts/weird_scores_report.py --season 2025-2026 --output reports/weird_scores.html
"""

import argparse
import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

CAT_LABELS = {
    "DEBUTANTE": "Debutante", "PREBENJAMIN": "Prebenjamín", "BENJAMIN": "Benjamín",
    "ALEVIN": "Alevín", "INFANTIL": "Infantil", "CADETE": "Cadete", "JUVENIL": "Juvenil",
    "AFICIONADO": "Aficionado", "SENIOR": "Sénior", "UNIVERSITARIO": "Universitario",
    "VETERANOS": "Veteranos", "OTHER": "Other",
}

MIN_GAMES = 5   # minimum matches played to qualify for the dominators/outsiders tables
TOP_N = 40


def latest_core_season() -> str:
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
    matches = pd.read_csv(d / "matches.csv", dtype=str)
    teams = pd.read_csv(d / "teams.csv", dtype=str)
    comps = pd.read_csv(d / "competitions.csv", dtype=str)

    comps["category_base"] = comps["category_base"].fillna("OTHER")
    comp_cat = comps.set_index("competition_id")["category_base"]

    m = matches.copy()
    m["hs"] = pd.to_numeric(m["home_score"], errors="coerce")
    m["as_"] = pd.to_numeric(m["away_score"], errors="coerce")
    played = m[(m["is_finished"].str.lower() == "true")].dropna(subset=["hs", "as_"]).copy()
    played["cat"] = played["competition_id"].map(comp_cat).fillna("OTHER")
    played["hid"] = played["home_team_id"].map(norm_id)
    played["aid"] = played["away_team_id"].map(norm_id)
    played["margin"] = (played["hs"] - played["as_"]).abs()
    played["total_goals"] = played["hs"] + played["as_"]

    tid_to_name = dict(zip(teams["team_id"].map(norm_id), teams["team"]))
    tid_to_club = dict(zip(teams["team_id"].map(norm_id), teams["club_name_raw"]))
    played["home_name"] = played["hid"].map(tid_to_name).fillna(played["home_team"])
    played["away_name"] = played["aid"].map(tid_to_name).fillna(played["away_team"])

    def match_records(df):
        out = []
        for _, r in df.iterrows():
            out.append({
                "date": r["match_date"] if pd.notna(r["match_date"]) else None,
                "cat": r["cat"],
                "comp": r["competition"], "group": r["group"],
                "home": r["home_name"], "away": r["away_name"],
                "hs": int(r["hs"]), "as": int(r["as_"]),
            })
        return out

    blowouts = match_records(played.sort_values("margin", ascending=False).head(TOP_N))
    high_scoring = match_records(played.sort_values("total_goals", ascending=False).head(TOP_N))

    # ── per-team aggregates (both home and away appearances) ──
    home_p = played[["hid", "cat", "hs", "as_"]].rename(columns={"hid": "tid", "hs": "gf", "as_": "ga"})
    away_p = played[["aid", "cat", "as_", "hs"]].rename(columns={"aid": "tid", "as_": "gf", "hs": "ga"})
    persp = pd.concat([home_p, away_p], ignore_index=True).dropna(subset=["tid"])
    persp["win"] = persp["gf"] > persp["ga"]
    persp["draw"] = persp["gf"] == persp["ga"]
    persp["loss"] = persp["gf"] < persp["ga"]

    agg = persp.groupby("tid").agg(
        played=("gf", "size"), gf=("gf", "sum"), ga=("ga", "sum"),
        wins=("win", "sum"), draws=("draw", "sum"), losses=("loss", "sum"),
        cat=("cat", lambda s: s.mode().iat[0] if not s.mode().empty else "OTHER"),
    ).reset_index()
    agg["diff"] = agg["gf"] - agg["ga"]
    agg["name"] = agg["tid"].map(tid_to_name)
    agg["club"] = agg["tid"].map(tid_to_club)
    agg = agg.dropna(subset=["name"])

    def team_records(df):
        out = []
        for _, r in df.iterrows():
            out.append({
                "team": r["name"], "club": r["club"], "cat": r["cat"],
                "played": int(r["played"]), "wins": int(r["wins"]),
                "draws": int(r["draws"]), "losses": int(r["losses"]),
                "gf": int(r["gf"]), "ga": int(r["ga"]), "diff": int(r["diff"]),
            })
        return out

    eligible = agg[agg["played"] >= MIN_GAMES]
    dominators = team_records(eligible.sort_values("diff", ascending=False).head(TOP_N))
    outsiders = team_records(eligible.sort_values("diff", ascending=True).head(TOP_N))

    cats_present = sorted(played["cat"].unique().tolist(), key=lambda c: list(CAT_LABELS).index(c) if c in CAT_LABELS else 99)

    stats = {
        "matches_played": int(len(played)),
        "total_goals": int(played["total_goals"].sum()),
        "avg_goals": round(float(played["total_goals"].mean()), 2) if len(played) else 0,
        "biggest_margin": int(played["margin"].max()) if len(played) else 0,
    }

    return {
        "season": season,
        "categories": cats_present,
        "cat_labels": {c: CAT_LABELS.get(c, c) for c in cats_present},
        "min_games": MIN_GAMES,
        "stats": stats,
        "blowouts": blowouts,
        "high_scoring": high_scoring,
        "dominators": dominators,
        "outsiders": outsiders,
    }


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM %SEASON% — Weird scores, dominators &amp; outsiders</title>
<style>
:root{
  --bg:#f5f6f8; --surface:#ffffff; --ink:#1a1d23; --ink-soft:#5a6270; --ink-faint:#8b93a3;
  --accent:#4e79a7; --accent-soft:#e2e8f4; --bad:#e15759; --bad-soft:#fbe4e4;
  --good:#59a14f; --good-soft:#e6f2e4; --line:#dde3ed; --line-strong:#c8d0de;
  --shadow: 0 1px 2px rgba(20,20,20,0.06); --row-hover:#f4f7fc;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#14171c; --surface:#1c2028; --ink:#eef0f4; --ink-soft:#a7aebb; --ink-faint:#6c7280;
    --accent:#7aa7d9; --accent-soft:#25344a; --bad:#e97a7c; --bad-soft:#3a2226;
    --good:#7fc276; --good-soft:#1f3020; --line:#2b3040; --line-strong:#3a4058;
    --shadow: 0 1px 3px rgba(0,0,0,0.4); --row-hover:#232837;
  }
}
:root[data-theme="dark"]{
  --bg:#14171c; --surface:#1c2028; --ink:#eef0f4; --ink-soft:#a7aebb; --ink-faint:#6c7280;
  --accent:#7aa7d9; --accent-soft:#25344a; --bad:#e97a7c; --bad-soft:#3a2226;
  --good:#7fc276; --good-soft:#1f3020; --line:#2b3040; --line-strong:#3a4058;
  --shadow: 0 1px 3px rgba(0,0,0,0.4); --row-hover:#232837;
}
:root[data-theme="light"]{
  --bg:#f5f6f8; --surface:#ffffff; --ink:#1a1d23; --ink-soft:#5a6270; --ink-faint:#8b93a3;
  --accent:#4e79a7; --accent-soft:#e2e8f4; --bad:#e15759; --bad-soft:#fbe4e4;
  --good:#59a14f; --good-soft:#e6f2e4; --line:#dde3ed; --line-strong:#c8d0de;
  --shadow: 0 1px 2px rgba(20,20,20,0.06); --row-hover:#f4f7fc;
}
*{box-sizing:border-box;}
html,body{margin:0;}
body{ background:var(--bg); color:var(--ink); font-family: system-ui, sans-serif; line-height:1.5; }
.page{ max-width:1100px; margin:0 auto; padding:2rem 1.25rem 4rem; display:flex; flex-direction:column; gap:1.6rem; }
a.back{font-size:0.8rem; color:var(--accent); text-decoration:none;}
a.back:hover{text-decoration:underline;}
h1{font-size:1.6rem; margin:0.3rem 0 0.2rem;}
h2{font-size:1.05rem; margin:0 0 0.6rem; color:var(--accent); border-bottom:1px solid var(--line); padding-bottom:0.3rem;}
p.lede{color:var(--ink-soft); font-size:0.92rem; max-width:75ch; margin:0;}
p.note{color:var(--ink-faint); font-size:0.8rem; max-width:75ch; margin:0;}

.stats{display:flex; flex-wrap:wrap; gap:0.75rem;}
.stat{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:0.7rem 1rem;
  box-shadow:var(--shadow); min-width:9rem; }
.stat .n{font-family: ui-monospace, monospace; font-size:1.3rem; font-weight:700; color:var(--ink);}
.stat .l{font-size:0.72rem; color:var(--ink-soft);}

.filter-row{display:flex; flex-wrap:wrap; gap:0.4rem; align-items:center;}
.chip{ display:inline-flex; align-items:center; padding:0.28rem 0.65rem; border-radius:999px;
  font-size:0.8rem; cursor:pointer; border:1.5px solid var(--line-strong); background:var(--surface);
  color:var(--ink-soft); user-select:none; }
.chip.active{background:var(--accent); border-color:var(--accent); color:#fff;}
.chip:hover:not(.active){background:var(--accent-soft);}

section{display:flex; flex-direction:column; gap:0.5rem;}
.table-wrap{overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow);}
table{border-collapse:collapse; width:100%; font-size:0.83rem;}
th, td{padding:0.4rem 0.65rem; border-bottom:1px solid var(--line); white-space:nowrap; text-align:right;}
td:nth-child(1), th:nth-child(1) { text-align: left; }
th{background:var(--accent); color:#fff; font-size:0.74rem; text-align:center;}
th:first-child{text-align:left;}
tr:last-child td{border-bottom:none;}
tr:nth-child(even) td{background:var(--row-hover);}
.score{font-family: ui-monospace, monospace; font-weight:700;}
.diff-pos{color:var(--good); font-weight:700;}
.diff-neg{color:var(--bad); font-weight:700;}
.cat-tag{font-size:0.7rem; color:var(--ink-faint);}
</style>
</head>
<body>
<div class="page">
  <a class="back" href="index.html">&larr; RFFM data</a>
  <h1>RFFM %SEASON% — Weird scores, dominators &amp; outsiders</h1>
  <p class="lede">Biggest blowouts, highest-scoring matches, and the teams with the best/worst goal difference this season, across every category with played matches.</p>
  <p class="note">Stat definitions are this project's own (see script docstring) — "dominators"/"outsiders" rank goal difference among teams with at least <span id="minGamesNote"></span> matches played; ties broken by name.</p>

  <div class="stats" id="statsRow"></div>

  <div class="filter-row" id="catFilter"></div>

  <section>
    <h2>Biggest blowouts</h2>
    <div class="table-wrap"><table id="tblBlowouts"></table></div>
  </section>

  <section>
    <h2>Highest-scoring matches</h2>
    <div class="table-wrap"><table id="tblHighScoring"></table></div>
  </section>

  <section>
    <h2>Dominators <span class="cat-tag">best goal difference</span></h2>
    <div class="table-wrap"><table id="tblDominators"></table></div>
  </section>

  <section>
    <h2>Outsiders <span class="cat-tag">worst goal difference</span></h2>
    <div class="table-wrap"><table id="tblOutsiders"></table></div>
  </section>
</div>

<script id="pageData" type="application/json">%DATA_JSON%</script>
<script>
const DATA = JSON.parse(document.getElementById('pageData').textContent);
const ACTIVE = new Set(DATA.categories);

document.getElementById('minGamesNote').textContent = DATA.min_games;
document.getElementById('statsRow').innerHTML = [
  [DATA.stats.matches_played.toLocaleString(), 'matches played'],
  [DATA.stats.total_goals.toLocaleString(), 'goals scored'],
  [DATA.stats.avg_goals, 'avg goals/match'],
  [DATA.stats.biggest_margin, 'biggest margin'],
].map(([n, l]) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');

const catFilter = document.getElementById('catFilter');
DATA.categories.forEach(c => {
  const chip = document.createElement('span');
  chip.className = 'chip active';
  chip.textContent = DATA.cat_labels[c] || c;
  chip.dataset.cat = c;
  chip.addEventListener('click', () => {
    if (ACTIVE.has(c)) ACTIVE.delete(c); else ACTIVE.add(c);
    chip.classList.toggle('active', ACTIVE.has(c));
    render();
  });
  catFilter.appendChild(chip);
});

function matchRow(m) {
  return `<tr><td>${m.home} <span class="score">${m.hs}–${m.as}</span> ${m.away}</td>
    <td>${m.date || '—'}</td><td class="cat-tag">${DATA.cat_labels[m.cat] || m.cat}</td>
    <td>${m.comp || ''}${m.group ? ' · ' + m.group : ''}</td></tr>`;
}
function teamRow(t) {
  const diffClass = t.diff > 0 ? 'diff-pos' : (t.diff < 0 ? 'diff-neg' : '');
  return `<tr><td>${t.team} <span class="cat-tag">${t.club}</span></td>
    <td class="cat-tag">${DATA.cat_labels[t.cat] || t.cat}</td>
    <td>${t.played}</td><td>${t.wins}-${t.draws}-${t.losses}</td>
    <td>${t.gf}:${t.ga}</td><td class="${diffClass}">${t.diff > 0 ? '+' : ''}${t.diff}</td></tr>`;
}

function render() {
  const bl = DATA.blowouts.filter(m => ACTIVE.has(m.cat));
  document.getElementById('tblBlowouts').innerHTML =
    '<thead><tr><th>Match</th><th>Date</th><th>Category</th><th>Competition</th></tr></thead><tbody>' +
    bl.map(matchRow).join('') + '</tbody>';

  const hs = DATA.high_scoring.filter(m => ACTIVE.has(m.cat));
  document.getElementById('tblHighScoring').innerHTML =
    '<thead><tr><th>Match</th><th>Date</th><th>Category</th><th>Competition</th></tr></thead><tbody>' +
    hs.map(matchRow).join('') + '</tbody>';

  const dom = DATA.dominators.filter(t => ACTIVE.has(t.cat));
  document.getElementById('tblDominators').innerHTML =
    '<thead><tr><th>Team</th><th>Category</th><th>Played</th><th>W-D-L</th><th>GF:GA</th><th>Diff</th></tr></thead><tbody>' +
    dom.map(teamRow).join('') + '</tbody>';

  const out = DATA.outsiders.filter(t => ACTIVE.has(t.cat));
  document.getElementById('tblOutsiders').innerHTML =
    '<thead><tr><th>Team</th><th>Category</th><th>Played</th><th>W-D-L</th><th>GF:GA</th><th>Diff</th></tr></thead><tbody>' +
    out.map(teamRow).join('') + '</tbody>';
}
render();
</script>
</body>
</html>
"""


def build_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return (HTML
            .replace("%DATA_JSON%", data_json)
            .replace("%SEASON%", data["season"]))


def main():
    parser = argparse.ArgumentParser(description="RFFM weird scores / dominators / outsiders report")
    parser.add_argument("--season", default=None, help="defaults to the latest season with a complete core crawl")
    parser.add_argument("--output", default="reports/weird_scores.html")
    args = parser.parse_args()

    season = args.season or latest_core_season()
    print(f"Building weird-scores report for season {season}")
    data = load_data(season)
    print(f"  {data['stats']['matches_played']} played matches across {len(data['categories'])} categories")

    out = Path(__file__).parent.parent / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(data), encoding="utf-8")
    print(f"Report written to {out}")


if __name__ == "__main__":
    main()
