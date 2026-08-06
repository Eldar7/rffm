#!/usr/bin/env python3
"""
Builds the whole GitHub Pages site into a single output directory: the
three interactive reports plus a landing page (index.html) that links to
them and summarizes season/category coverage from coverage_manifest.csv.

Every report is regenerated from the CSVs already committed under
output/processed/rffm/ — nothing here re-scrapes the RFFM site.

Usage:
    python analysis_scripts/build_site.py --output-dir site
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import season_comparison
import club_division_map
import weird_scores_report

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"


def coverage_rows() -> list[dict]:
    """One summary row per season: core status + how many categories have
    acta_partido/fichajugador enrichment complete, for the landing page."""
    m = pd.read_csv(MANIFEST, dtype=str)
    rows = []
    for season, g in m.groupby("season"):
        core = g[(g["stage"] == "core") & (g["category_base"] == "ALL")]
        clubs = g[(g["stage"] == "clubs") & (g["category_base"] == "ALL")]
        acta = g[(g["stage"] == "acta_partido") & (g["status"] == "complete")]
        ficha = g[(g["stage"] == "fichajugador") & (g["status"] == "complete")]
        rows.append({
            "season": season,
            "core_status": core["status"].iloc[0] if not core.empty else "—",
            "clubs_status": clubs["status"].iloc[0] if not clubs.empty else "—",
            "acta_categories": sorted(acta["category_base"].unique().tolist()),
            "ficha_categories": sorted(ficha["category_base"].unique().tolist()),
        })
    rows.sort(key=lambda r: r["season"])
    return rows


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM data — Madrid youth &amp; adult football, {SEASON_RANGE}</title>
<style>
:root{
  --bg:#f5f6f8; --surface:#ffffff; --ink:#1a1d23; --ink-soft:#5a6270; --ink-faint:#8b93a3;
  --accent:#4e79a7; --accent-soft:#e2e8f4; --line:#dde3ed; --line-strong:#c8d0de;
  --shadow: 0 1px 2px rgba(20,20,20,0.06); --row-hover:#f4f7fc; --ok:#59a14f; --warn:#f28e2b;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#14171c; --surface:#1c2028; --ink:#eef0f4; --ink-soft:#a7aebb; --ink-faint:#6c7280;
    --accent:#7aa7d9; --accent-soft:#25344a; --line:#2b3040; --line-strong:#3a4058;
    --shadow: 0 1px 3px rgba(0,0,0,0.4); --row-hover:#232837; --ok:#7fc276; --warn:#e3a45c;
  }
}
:root[data-theme="dark"]{
  --bg:#14171c; --surface:#1c2028; --ink:#eef0f4; --ink-soft:#a7aebb; --ink-faint:#6c7280;
  --accent:#7aa7d9; --accent-soft:#25344a; --line:#2b3040; --line-strong:#3a4058;
  --shadow: 0 1px 3px rgba(0,0,0,0.4); --row-hover:#232837; --ok:#7fc276; --warn:#e3a45c;
}
:root[data-theme="light"]{
  --bg:#f5f6f8; --surface:#ffffff; --ink:#1a1d23; --ink-soft:#5a6270; --ink-faint:#8b93a3;
  --accent:#4e79a7; --accent-soft:#e2e8f4; --line:#dde3ed; --line-strong:#c8d0de;
  --shadow: 0 1px 2px rgba(20,20,20,0.06); --row-hover:#f4f7fc; --ok:#59a14f; --warn:#f28e2b;
}
*{box-sizing:border-box;}
html,body{margin:0;}
body{ background:var(--bg); color:var(--ink); font-family: system-ui, sans-serif; line-height:1.5; }
.page{ max-width:1000px; margin:0 auto; padding:2.5rem 1.25rem 4rem; display:flex; flex-direction:column; gap:2rem; }
h1{font-size:1.7rem; margin:0 0 0.3rem;}
h2{font-size:1.05rem; margin:0 0 0.8rem; color:var(--accent);}
p.lede{color:var(--ink-soft); font-size:0.95rem; max-width:75ch; margin:0;}
p.foot{color:var(--ink-faint); font-size:0.8rem; max-width:75ch;}
code{ font-family: ui-monospace, monospace; font-size:0.86em; background:var(--accent-soft);
  padding:0.05em 0.35em; border-radius:3px; }

.cards{ display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:1rem; }
.card{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:1.1rem 1.2rem;
  box-shadow:var(--shadow); text-decoration:none; color:var(--ink); display:flex; flex-direction:column; gap:0.4rem; }
.card:hover{border-color:var(--accent);}
.card .title{font-weight:700; font-size:1rem;}
.card .desc{font-size:0.85rem; color:var(--ink-soft);}

.table-wrap{overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow);}
table{border-collapse:collapse; width:100%; font-size:0.83rem;}
th, td{padding:0.45rem 0.7rem; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap;}
th{background:var(--accent); color:#fff; font-size:0.74rem;}
tr:last-child td{border-bottom:none;}
tr:nth-child(even) td{background:var(--row-hover);}
.status-ok{color:var(--ok); font-weight:600;}
.status-warn{color:var(--warn); font-weight:600;}
.cats{font-size:0.76rem; color:var(--ink-soft); white-space:normal;}
</style>
</head>
<body>
<div class="page">
  <header>
    <h1>RFFM data — Real Federación de Fútbol de Madrid</h1>
    <p class="lede">Competitions, fixtures/results, standings, venues and enrichment data crawled from
      <a href="https://www.rffm.es" target="_blank" rel="noopener">rffm.es</a>, rebuilt into this page
      straight from the CSVs committed in <code>output/processed/rffm/</code> — no manual step in between.</p>
  </header>

  <section>
    <h2>Reports</h2>
    <div class="cards">
      {CARDS}
    </div>
  </section>

  <section>
    <h2>Season / category coverage</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Season</th><th>Core crawl</th><th>Clubs enrichment</th>
          <th>acta_partido complete for</th><th>fichajugador complete for</th></tr></thead>
        <tbody>
          {COVERAGE_ROWS}
        </tbody>
      </table>
    </div>
    <p class="foot">Full column-level detail: <code>output/processed/rffm/coverage_manifest.csv</code>.</p>
  </section>

  <p class="foot">Rebuilt automatically by <code>.github/workflows/pages-deploy.yml</code> — see
    <code>analysis_scripts/build_site.py</code> for how each report is generated.</p>
</div>
</body>
</html>
"""


def status_span(status: str) -> str:
    if status == "complete":
        return f'<span class="status-ok">{status}</span>'
    if status == "—":
        return status
    return f'<span class="status-warn">{status}</span>'


def build_index(seasons: list[str], coverage: list[dict]) -> str:
    cards = [
        {
            "href": "season_comparison.html",
            "title": "Cross-season comparison",
            "desc": "Matches, clubs, goals and competitions per season, filterable by age category / division / game type.",
        },
        {
            "href": "club_division_map.html",
            "title": "Club × division map",
            "desc": "Benjamín/Prebenjamín club standings matrix, with each club's most-frequent home venue.",
        },
        {
            "href": "weird_scores.html",
            "title": "Weird scores, dominators & outsiders",
            "desc": "Biggest blowouts, highest-scoring matches, and the best/worst goal-difference teams.",
        },
    ]
    cards_html = "\n      ".join(
        f'<a class="card" href="{c["href"]}"><span class="title">{c["title"]}</span>'
        f'<span class="desc">{c["desc"]}</span></a>'
        for c in cards
    )

    rows_html = "\n          ".join(
        "<tr><td>{season}</td><td>{core}</td><td>{clubs}</td>"
        "<td class=\"cats\">{acta}</td><td class=\"cats\">{ficha}</td></tr>".format(
            season=r["season"],
            core=status_span(r["core_status"]),
            clubs=status_span(r["clubs_status"]),
            acta=", ".join(r["acta_categories"]) or "—",
            ficha=", ".join(r["ficha_categories"]) or "—",
        )
        for r in coverage
    )

    season_range = f"{seasons[0]}–{seasons[-1]}" if seasons else ""
    return (INDEX_HTML
            .replace("{SEASON_RANGE}", season_range)
            .replace("{CARDS}", cards_html)
            .replace("{COVERAGE_ROWS}", rows_html))


def main():
    parser = argparse.ArgumentParser(description="Build the full RFFM GitHub Pages site")
    parser.add_argument("--output-dir", default="site")
    args = parser.parse_args()

    out_dir = Path(__file__).parent.parent / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building season_comparison.html ({len(season_comparison.SEASONS)} seasons)...")
    sc_data = season_comparison.load_all_data()
    (out_dir / "season_comparison.html").write_text(season_comparison.build_html(sc_data), encoding="utf-8")

    print("Building club_division_map.html...")
    cm_season = club_division_map.latest_core_season()
    cm_data = club_division_map.load_data(cm_season)
    (out_dir / "club_division_map.html").write_text(club_division_map.build_html(cm_data), encoding="utf-8")

    print("Building weird_scores.html...")
    ws_season = weird_scores_report.latest_core_season()
    ws_data = weird_scores_report.load_data(ws_season)
    (out_dir / "weird_scores.html").write_text(weird_scores_report.build_html(ws_data), encoding="utf-8")

    print("Building index.html...")
    coverage = coverage_rows()
    (out_dir / "index.html").write_text(
        build_index(season_comparison.SEASONS, coverage), encoding="utf-8")

    total_bytes = sum(f.stat().st_size for f in out_dir.glob("*.html"))
    print(f"\nSite written to {out_dir} ({total_bytes / 1024:.0f} KB total)")


if __name__ == "__main__":
    main()
