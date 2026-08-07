#!/usr/bin/env python3
"""
Club x division matrix — one row per club, one column per (age category,
division tier, game type), cell = team count + best position reached that
season. Filterable client-side by season / age category / division / game
type; click a club to open a detail panel with its real home venues (exact
lat/lon from venues.csv, not a single collapsed guess), its crest/website/
correspondence address (clubs.csv, where crawled), and every team/division
entry for that club.

Each season's matrix is written as its own JSON file under
<output-dir>/data/club_map_<season>.json and fetched client-side when the
season selector changes — embedding every season's full (now 11-category)
matrix in one HTML page would make it too large to ship as one blob.

Usage:
    python analysis_scripts/club_division_map.py
    python analysis_scripts/club_division_map.py --season 2025-2026 --output-dir reports
"""

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from site_theme import FONT_LINKS, lang_switch_html

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

# Full age-category vocabulary (CLAUDE.md/DATA_DICTIONARY.md) — BENJAMIN/
# PREBENJAMIN was this project's initial focus, not a hard restriction, and
# core crawls now cover every category the federation runs.
CATEGORIES = [
    "DEBUTANTE", "PREBENJAMIN", "BENJAMIN", "ALEVIN", "INFANTIL", "CADETE",
    "JUVENIL", "AFICIONADO", "SENIOR", "UNIVERSITARIO", "VETERANOS",
]
DEFAULT_CATEGORIES = {"BENJAMIN", "PREBENJAMIN"}
# Category/division names are the federation's own Spanish terms (Alevín,
# Preferente, ...) — kept as-is in both RU and ES chrome. Transliterating
# them into Russian ("Алевин", "Преференте") reads as wrong, not translated.
CAT_LABEL_ES = {
    "DEBUTANTE": "Debutante", "PREBENJAMIN": "Prebenjamín", "BENJAMIN": "Benjamín",
    "ALEVIN": "Alevín", "INFANTIL": "Infantil", "CADETE": "Cadete", "JUVENIL": "Juvenil",
    "AFICIONADO": "Aficionado", "SENIOR": "Sénior", "UNIVERSITARIO": "Universitario",
    "VETERANOS": "Veteranos",
}
CAT_LABEL_RU = CAT_LABEL_ES

# Ordered strongest-to-weakest, matching CLAUDE.md/DATA_DICTIONARY.md tier ordering.
DIV_ORDER = [
    "DIVISION DE HONOR", "PRIMERA DIVISION AUTONOMICA", "PREFERENTE",
    "PRIMERA", "SEGUNDA", "TERCERA",
]
DIV_CODE = {
    "DIVISION DE HONOR": "DH", "PRIMERA DIVISION AUTONOMICA": "PDA", "PREFERENTE": "PREF",
    "PRIMERA": "PRIM", "SEGUNDA": "SEG", "TERCERA": "TER",
}
DIV_LABEL_ES = {
    "DIVISION DE HONOR": "División de Honor", "PRIMERA DIVISION AUTONOMICA": "1ª Div. Autonómica",
    "PREFERENTE": "Preferente", "PRIMERA": "1ª División", "SEGUNDA": "2ª División", "TERCERA": "3ª División",
}
DIV_LABEL_RU = DIV_LABEL_ES

GT_CODE = {"Futbol-7": "F7", "Fútbol Sala": "FS", "Futbol-11": "F11", "Fútbol-5": "F5"}
GT_SHORT = {"Futbol-7": "F-7", "Fútbol Sala": "Sala", "Futbol-11": "F-11", "Fútbol-5": "F-5"}


def gt_code(gt: str) -> str:
    if gt in GT_CODE:
        return GT_CODE[gt]
    return re.sub(r"[^A-Za-z0-9]", "", gt).upper()[:6] or "GT"


def list_seasons() -> list[str]:
    """Every season whose core crawl is complete, per coverage_manifest.csv."""
    m = pd.read_csv(MANIFEST, dtype=str)
    core = m[(m["stage"] == "core") & (m["category_base"] == "ALL") &
             (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(core["season"].unique().tolist())


def latest_core_season() -> str:
    seasons = list_seasons()
    if not seasons:
        raise SystemExit("No season has a complete core crawl in coverage_manifest.csv")
    return seasons[-1]


def norm_id(v):
    try:
        return str(int(float(str(v))))
    except (ValueError, TypeError):
        return None


def abs_crest_url(path):
    if not isinstance(path, str) or not path.strip():
        return None
    if path.startswith("http"):
        return path
    return "https://www.rffm.es" + path


def clean(v):
    """None for NaN/empty (pandas leaves real NaN floats in string columns
    for missing values — those serialize to the bare, non-JSON token `NaN`)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def load_data(season: str) -> dict:
    d = BASE / season
    teams = pd.read_csv(d / "teams.csv", dtype=str)
    comps = pd.read_csv(d / "competitions.csv", dtype=str)
    standings = pd.read_csv(d / "standings.csv", dtype=str)
    matches = pd.read_csv(d / "matches.csv", dtype=str)
    venues = pd.read_csv(d / "venues.csv", dtype=str)
    clubs_path = d / "clubs.csv"
    clubs_df = pd.read_csv(clubs_path, dtype=str) if clubs_path.exists() else None

    comps["category_base"] = comps["category_base"].fillna("OTHER")
    comps["division_level"] = comps["division_level"].fillna("OTHER")
    comp_facet = comps.set_index("competition_id")[["category_base", "division_level", "game_type", "game_type_id"]]

    standings = standings.join(comp_facet, on="competition_id")
    standings = standings[standings["category_base"].isin(CATEGORIES) &
                           standings["division_level"].isin(DIV_ORDER) &
                           standings["game_type"].notna()].copy()
    standings["position"] = pd.to_numeric(standings["position"], errors="coerce")
    standings["tid"] = standings["team_id"].map(norm_id)

    tid_to_club = dict(zip(teams["team_id"].map(norm_id), teams["club_name_raw"]))
    tid_to_name = dict(zip(teams["team_id"].map(norm_id), teams["team"]))
    standings["club"] = standings["tid"].map(tid_to_club)
    standings = standings.dropna(subset=["club", "position"])
    standings["gt_code"] = standings["game_type"].map(gt_code)

    group_size = standings.groupby("group_id").size().to_dict()

    # ── matrix cells: one row per (club, cat, div, gt) ──
    cell_rows = []
    for (club, cat, div, gtc), grp in standings.groupby(["club", "category_base", "division_level", "gt_code"]):
        best = grp.loc[grp["position"].idxmin()]
        cell_rows.append({
            "club": club, "cat": cat, "div": div, "gtc": gtc,
            "n": int(grp["tid"].nunique()),
            "pos": int(best["position"]),
            "size": int(group_size.get(best["group_id"], len(grp))),
            "grp": clean(best["group"]),
        })
    cells = pd.DataFrame(cell_rows)

    # ── per-club team list (for the detail panel) ──
    teams_by_club: dict[str, list] = {}
    for _, r in standings.iterrows():
        teams_by_club.setdefault(r["club"], []).append({
            "team": clean(tid_to_name.get(r["tid"])) or clean(r["team"]) or r["tid"],
            "tid": r["tid"],
            "cat": r["category_base"], "div": r["division_level"], "gt": r["game_type"],
            "grp": clean(r["group"]), "pos": int(r["position"]),
            "size": int(group_size.get(r["group_id"], 1)),
            "season_id": clean(r["season_id"]), "comp_id": clean(r["competition_id"]),
            "group_id": clean(r["group_id"]), "gt_id": clean(r["game_type_id"]),
        })

    # ── venues: EVERY real home ground per club (exact lat/lon from venues.csv), not one guess ──
    relevant_tids = set(standings["tid"].dropna().unique())
    matches["hid"] = matches["home_team_id"].map(norm_id)
    matches["vid"] = matches["venue_id"].map(norm_id)
    home = matches[matches["hid"].isin(relevant_tids)].copy()
    home["club"] = home["hid"].map(tid_to_club)
    venues["vid"] = venues["venue_id"].map(norm_id)
    venue_info = venues.set_index("vid")[["venue_name", "address", "locality", "google_maps_url"]].to_dict("index")

    venues_by_club: dict[str, list] = {}
    for club, grp in home.dropna(subset=["vid"]).groupby("club"):
        counts = grp["vid"].value_counts()
        total = int(counts.sum())
        out = []
        for vid, n in counts.items():
            info = venue_info.get(vid, {})
            out.append({
                "venue": clean(info.get("venue_name")) or vid, "address": clean(info.get("address")),
                "locality": clean(info.get("locality")), "maps": clean(info.get("google_maps_url")),
                "n": int(n), "total": total, "pct": round(int(n) / total * 100) if total else 0,
            })
        venues_by_club[club] = out

    # ── club identity (crest, website, correspondence address) — opt-in, may be absent ──
    club_info_by_name = {}
    if clubs_df is not None:
        for _, r in clubs_df.iterrows():
            club_info_by_name[r["club_name_raw"]] = {
                "crest": abs_crest_url(clean(r.get("crest_url"))),
                "web": clean(r.get("portal_web")),
                "address": clean(r.get("correspondence_address")),
                "locality": clean(r.get("locality")),
                "province": clean(r.get("province")),
                "reptid": clean(r.get("representative_team_id")),
            }

    # ── assemble per-club records ──
    clubs_out = []
    for club, grp in cells.groupby("club"):
        rec = {"club": club}
        cells_dict = {}
        for _, r in grp.iterrows():
            key = f"{r['cat']}_{DIV_CODE[r['div']]}_{r['gtc']}"
            cells_dict[key] = {"n": int(r["n"]), "pos": int(r["pos"]), "size": int(r["size"]), "grp": r["grp"]}
        rec["cells"] = cells_dict
        rec["teams"] = sorted(teams_by_club.get(club, []), key=lambda t: (t["cat"], t["div"], t["pos"]))
        rec["venues"] = sorted(venues_by_club.get(club, []), key=lambda v: -v["n"])
        rec["info"] = club_info_by_name.get(club)
        clubs_out.append(rec)
    clubs_out.sort(key=lambda r: r["club"])

    columns = []
    seen = set()
    for _, r in cells[["cat", "div", "gtc"]].drop_duplicates().iterrows():
        gt_label = next((g for g in standings.loc[standings["gt_code"] == r["gtc"], "game_type"].unique()), r["gtc"])
        key = f"{r['cat']}_{DIV_CODE[r['div']]}_{r['gtc']}"
        if key in seen:
            continue
        seen.add(key)
        columns.append({
            "cat": r["cat"], "div": r["div"], "gt": gt_label, "key": key,
            "cat_label_ru": CAT_LABEL_RU[r["cat"]], "cat_label_es": CAT_LABEL_ES[r["cat"]],
            "div_label_ru": DIV_LABEL_RU[r["div"]], "div_label_es": DIV_LABEL_ES[r["div"]],
            "gt_short": GT_SHORT.get(gt_label, gt_label),
        })
    columns.sort(key=lambda c: (CATEGORIES.index(c["cat"]), DIV_ORDER.index(c["div"]), c["gt"]))

    return {"season": season, "columns": columns, "clubs": clubs_out}


HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — карта клубов по дивизионам</title>
%FONT_LINKS%
<style>
:root{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --tier-1:#c3dcc7; --tier-2:#d6e6d8; --tier-3:#e6efe6; --tier-4:#f2f5f1; --row-hover:#f4f7f2;
  --teal:#1a6b7a; --teal-soft:#d8eef1; --pos-red:#a03327; --pos-red-soft:#f5ddd6;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
    --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
    --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
    --tier-1:#294a30; --tier-2:#213b27; --tier-3:#1c2f21; --tier-4:#18241b; --row-hover:#1c2619;
    --teal:#5fc3d6; --teal-soft:#12313a; --pos-red:#e2685a; --pos-red-soft:#33201d;
  }
}
:root[data-theme="dark"]{
  --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
  --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
  --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
  --tier-1:#294a30; --tier-2:#213b27; --tier-3:#1c2f21; --tier-4:#18241b; --row-hover:#1c2619;
  --teal:#5fc3d6; --teal-soft:#12313a; --pos-red:#e2685a; --pos-red-soft:#33201d;
}
:root[data-theme="light"]{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --tier-1:#c3dcc7; --tier-2:#d6e6d8; --tier-3:#e6efe6; --tier-4:#f2f5f1; --row-hover:#f4f7f2;
  --teal:#1a6b7a; --teal-soft:#d8eef1; --pos-red:#a03327; --pos-red-soft:#f5ddd6;
}
*{box-sizing:border-box;}
html,body{margin:0; height:100%;}
body{
  background:var(--bg); color:var(--ink);
  font-family: 'PT Sans', ui-sans-serif, "Helvetica Neue", Arial, sans-serif;
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
select#seasonSelect{ font-family:'JetBrains Mono',monospace; font-size:0.82rem; font-weight:700; color:var(--ink);
  background:var(--surface); border:1px solid var(--line-strong); border-radius:6px; padding:0.4rem 0.6rem; cursor:pointer; }

.lang-switch{ display:inline-flex; border:1px solid var(--line-strong); border-radius:999px; overflow:hidden; }
.lang-opt{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:0.04em;
  padding:4px 12px; background:var(--surface); color:var(--ink-soft); border:none; cursor:pointer; }
.lang-opt.is-active{background:var(--accent); color:#fff;}

/* ── filter panel ── */
.filter-panel{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:0.9rem 1.1rem; box-shadow:var(--shadow); display:flex; flex-direction:column; gap:0.6rem; }
.filter-row{ display:flex; align-items:flex-start; gap:0.9rem; flex-wrap:wrap; }
.filter-label{ font-size:0.74rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:var(--ink-soft);
  white-space:nowrap; padding-top:0.35rem; min-width:82px; }
.filter-chips{ display:flex; flex-wrap:wrap; gap:0.35rem; flex:1; }
.chip{ display:inline-flex; align-items:center; padding:0.26rem 0.6rem; border-radius:999px; font-size:0.78rem; cursor:pointer;
  border:1.5px solid var(--line-strong); background:var(--bg); color:var(--ink-soft); user-select:none;
  transition:background .12s,border-color .12s,color .12s; }
.chip.active{ background:var(--accent); border-color:var(--accent); color:#fff; }
.chip:hover:not(.active){ border-color:var(--accent); color:var(--ink); }
.quick-btns{ display:flex; gap:0.3rem; align-items:center; padding-top:0.25rem; }
.quick-btns button{ font-size:0.7rem; padding:0.18rem 0.5rem; border:1px solid var(--line-strong); border-radius:4px;
  background:var(--bg); color:var(--ink-soft); cursor:pointer; }
.quick-btns button:hover{ background:var(--accent-soft); color:var(--ink); }

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
thead tr.lvl-row th.club-head{ position:sticky; left:0; z-index:4; background:var(--surface);
  border-right:1px solid var(--line-strong); min-width:15rem; cursor:default; }
thead tr.lvl-row th.total-head{min-width:8rem;}
tbody td{ border-bottom:1px solid var(--line); padding:0.4rem 0.55rem; vertical-align:middle; white-space:nowrap; }
tbody tr:hover td{background:var(--row-hover);}
tbody td.club-cell{ position:sticky; left:0; z-index:2; background:var(--surface);
  border-right:1px solid var(--line-strong); font-weight:600; color:var(--ink); white-space:normal; max-width:16rem; }
tbody tr:hover td.club-cell{background:var(--row-hover);}
.club-cell-inner{display:flex; align-items:baseline; gap:0.4rem; flex-wrap:wrap;}
.club-name{flex:1 1 auto; min-width:0; cursor:pointer; border-bottom:1px dashed var(--line-strong);}
.club-name:hover{color:var(--accent); border-color:var(--accent);}
a.pin{ flex:none; display:inline-flex; align-items:center; gap:0.2rem; font-size:0.7rem; font-weight:600;
  color:var(--ink-faint); text-decoration:none; border:1px solid var(--line-strong); border-radius:999px;
  padding:0.08rem 0.4rem 0.08rem 0.3rem; white-space:nowrap; }
a.pin:hover{color:var(--accent); border-color:var(--accent); background:var(--accent-soft);}
td.total-cell{font-variant-numeric: tabular-nums; color:var(--ink-soft); text-align:right;}
td.total-cell strong{color:var(--ink); font-weight:700;}
td.cell{text-align:center; padding:0.3rem 0.4rem;}
td.cell .chip2{ display:inline-flex; flex-direction:column; align-items:center; justify-content:center;
  gap:0.05rem; border-radius:6px; padding:0.28rem 0.5rem; min-width:3.6rem; font-variant-numeric: tabular-nums; cursor:default; }
td.cell .chip2 .n{font-size:0.78rem; font-weight:700; color:var(--accent);}
td.cell .chip2 .p{font-size:0.68rem; color:var(--ink-soft);}
td.cell .empty{color:var(--ink-faint); font-size:0.8rem;}
td.cell.lvl-0{background:var(--tier-1);} td.cell.lvl-1{background:var(--tier-2);}
td.cell.lvl-2{background:var(--tier-3);} td.cell.lvl-3{background:var(--tier-4);}
.hidden{display:none !important;}
.empty-state{padding:2.5rem 1rem; text-align:center; color:var(--ink-soft); font-size:0.92rem;}
footer.note{font-size:0.82rem; color:var(--ink-soft); max-width:80ch;}
footer.note code{ font-family: ui-monospace, monospace; font-size:0.86em; background:var(--accent-soft);
  padding:0.05em 0.35em; border-radius:3px; color:var(--ink); }

/* ── club modal ── */
.modal-backdrop{position:fixed; inset:0; background:rgba(10,15,10,0.55); display:flex; align-items:center; justify-content:center; padding:1.5rem; z-index:50;}
.modal-backdrop.hidden{display:none;}
.modal{background:var(--surface); border-radius:10px; max-width:640px; width:100%; max-height:85vh; overflow:auto; padding:1.5rem; position:relative; box-shadow:var(--shadow);}
.modal-close{position:absolute; top:0.7rem; right:0.7rem; background:none; border:none; font-size:1.6rem; line-height:1; cursor:pointer; color:var(--ink-soft); padding:0.2rem 0.5rem;}
.modal-close:hover{color:var(--ink);}
.modal-head{display:flex; gap:0.9rem; align-items:center; margin-bottom:0.75rem; padding-right:2rem;}
.modal-crest{width:60px; height:60px; object-fit:contain; border-radius:6px; background:var(--bg); flex:none;}
.modal h2{font-family:'Oswald',sans-serif; font-weight:700; text-transform:uppercase; font-size:1.05rem; margin:0 0 0.2rem;}
.modal-note{font-size:0.8rem; color:var(--ink-soft); background:var(--accent-soft); border-radius:6px; padding:0.5rem 0.7rem; margin-top:0.4rem;}
.modal-section{margin-top:1.1rem;}
.modal-section h3{font-family:'JetBrains Mono',monospace; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.06em; color:var(--accent); margin:0 0 0.5rem;}
.modal-venue,.modal-team-row{display:flex; justify-content:space-between; align-items:center; gap:0.6rem; padding:0.35rem 0; border-bottom:1px solid var(--line); font-size:0.82rem;}
.modal-venue:last-child,.modal-team-row:last-child{border-bottom:none;}
.modal-venue .v-name{color:var(--ink);}
.modal-venue .v-stat{color:var(--ink-soft); white-space:nowrap; text-align:right;}
.modal-group-h{font-family:'JetBrains Mono',monospace; font-size:0.68rem; font-weight:700; text-transform:uppercase;
  letter-spacing:0.05em; color:var(--ink-soft); margin:0.7rem 0 0.15rem; padding-top:0.5rem; border-top:1px solid var(--line);}
.modal-group-h:first-child{border-top:none; margin-top:0; padding-top:0;}
.modal-div-h{font-size:0.72rem; font-weight:700; color:var(--ink); margin:0.3rem 0 0.1rem;}

/* ---------- position badges: gold=1st, then 4 flat, non-gradient bands by proximity to top/bottom ---------- */
.pos-badge{ display:inline-flex; align-items:baseline; gap:0.15rem; padding:0.1rem 0.45rem; border-radius:999px;
  font-family:ui-monospace,monospace; font-size:0.76rem; font-weight:700; white-space:nowrap; }
.pos-badge .of{opacity:0.7; font-weight:400;}
.pos-gold{ background:var(--gold-soft); color:var(--gold-ink,var(--gold)); box-shadow:inset 0 0 0 1.5px var(--gold); }
.pos-green{ background:var(--accent-soft); color:var(--accent); }
.pos-teal{ background:var(--teal-soft); color:var(--teal); }
.pos-grey{ background:var(--line); color:var(--ink-soft); }
.pos-red{ background:var(--pos-red-soft); color:var(--pos-red); }
td.cell .chip2.pos-gold .n{color:var(--gold);}
td.cell .chip2.pos-green .n{color:var(--accent);}
td.cell .chip2.pos-teal .n{color:var(--teal);}
td.cell .chip2.pos-grey .n{color:var(--ink-soft);}
td.cell .chip2.pos-red .n{color:var(--pos-red);}
td.cell .chip2.pos-gold{box-shadow: inset 0 0 0 1.5px var(--gold);}
</style>
</head>
<body>

<div class="page">
  <header class="masthead">
    %LANG_SWITCH%
    <a class="back" href="index.html">&larr; RFFM data</a>
    <span class="eyebrow"><span data-i18n="eyebrow">RFFM (Мадрид) &middot; клубы по дивизионам</span></span>
    <h1><span data-i18n="h1">Карта клубов по дивизионам</span></h1>
    <p><span data-i18n="lede">Каждая строка &mdash; клуб, каждый столбец &mdash; дивизион/тип игры. В ячейке &mdash; сколько команд клуба там выступает и лучшая позиция (любой из его команд) в своей группе. Кликните по названию клуба, чтобы увидеть настоящие площадки, герб и полный список команд.</span></p>
  </header>

  <div class="stats" id="stats"></div>

  <div class="filter-panel">
    <div class="filter-row">
      <span class="filter-label" data-i18n="lbl_season">Сезон</span>
      <select id="seasonSelect"></select>
    </div>
    <div class="filter-row">
      <span class="filter-label" data-i18n="lbl_cats">Возраст</span>
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
    <div class="filter-row">
      <span class="filter-label" data-i18n="lbl_gts">Тип игры</span>
      <div class="filter-chips" id="chips-gts"></div>
      <div class="quick-btns">
        <button type="button" id="gtsAll" data-i18n="btn_all3">Все</button>
        <button type="button" id="gtsNone" data-i18n="btn_none3">Нет</button>
      </div>
    </div>
  </div>

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
    <span data-i18n="legend5">&#128205; = самая частая реальная площадка клуба (клик по клубу — полный список)</span>
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
    <span data-i18n="foot1">Охват: клубы с зарегистрированной классификацией в выбранных фильтрах, сезон выбирается выше. Только позиции регулярного сезона. Источник: <code>output/processed/rffm/{teams,competitions,standings,matches,venues,clubs}.csv</code>.</span>
    <br><br>
    <span data-i18n="foot2"><strong>О площадках:</strong> клик по названию клуба открывает настоящий список площадок этого клуба из базы (точные координаты <code>venues.csv</code>), а не одну усреднённую догадку &mdash; детский футбол часто играется в формате «sede» с ротацией полей по турам, поэтому у клуба обычно несколько реальных адресов, а не один стадион.</span>
  </footer>
</div>

<div class="modal-backdrop hidden" id="modalBackdrop">
  <div class="modal">
    <button class="modal-close" id="modalClose" aria-label="Close">&times;</button>
    <div id="modalContent"></div>
  </div>
</div>

<script>
const SEASONS = %SEASONS_JSON%;
const DEFAULT_CATS = %DEFAULT_CATS_JSON%;
const CAT_ORDER = %CAT_ORDER_JSON%;
const DIV_ORDER_JS = %DIV_ORDER_JSON%;
const CAT_LABEL_RU = %CAT_LABEL_RU_JSON%;
const CAT_LABEL_ES = %CAT_LABEL_ES_JSON%;
const DIV_LABEL_RU = %DIV_LABEL_RU_JSON%;
const DIV_LABEL_ES = %DIV_LABEL_ES_JSON%;
const LANG = {
  ru: { club: 'Клуб', total: 'Всего команд', clubsWord: 'клубов', noResults: 'Нет результатов.', searchPh: 'Поиск клуба (напр. Aravaca, Getafe, Real Madrid)…', of: 'в', loading: 'Загрузка…' },
  es: { club: 'Club', total: 'Total equipos', clubsWord: 'clubes', noResults: 'Sin resultados.', searchPh: 'Buscar club (p. ej. Aravaca, Getafe, Real Madrid)…', of: 'en', loading: 'Cargando…' },
};
let CURLANG = 'ru';
let DATA = null, COLUMNS = [], CLUBS = [];
const STATE = { cats: new Set(), divs: new Set(), gts: new Set(), seeded: false };
let TIER = {};
let sortKey = '__total', sortDir = -1;

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function catLabel(c) { return CURLANG === 'ru' ? CAT_LABEL_RU[c] : CAT_LABEL_ES[c]; }
function divLabel(d) { return CURLANG === 'ru' ? DIV_LABEL_RU[d] : DIV_LABEL_ES[d]; }

function activeColumns() {
  return COLUMNS.filter(c => STATE.cats.has(c.cat) && STATE.divs.has(c.div) && STATE.gts.has(c.gt));
}

function buildChipRow(containerId, kind, items, labelFn) {
  const el = document.getElementById(containerId);
  el.innerHTML = '';
  items.forEach(val => {
    const chip = document.createElement('span');
    chip.className = 'chip' + (STATE[kind].has(val) ? ' active' : '');
    chip.textContent = labelFn(val);
    chip.addEventListener('click', () => {
      if (STATE[kind].has(val)) STATE[kind].delete(val); else STATE[kind].add(val);
      chip.classList.toggle('active', STATE[kind].has(val));
      buildHead();
      render();
    });
    el.appendChild(chip);
  });
}

function buildFilterChips() {
  const allCats = [...new Set(COLUMNS.map(c => c.cat))].sort((a, b) => CAT_ORDER.indexOf(a) - CAT_ORDER.indexOf(b));
  const allDivs = [...new Set(COLUMNS.map(c => c.div))].sort((a, b) => DIV_ORDER_JS.indexOf(a) - DIV_ORDER_JS.indexOf(b));
  const allGts = [...new Set(COLUMNS.map(c => c.gt))].sort();
  buildChipRow('chips-cats', 'cats', allCats, catLabel);
  buildChipRow('chips-divs', 'divs', allDivs, divLabel);
  buildChipRow('chips-gts', 'gts', allGts, g => g);
}

function quickSelect(kind, containerId, action) {
  const items = [...document.getElementById(containerId).children].map((el, i) => i);
  const cols = kind === 'cats' ? [...new Set(COLUMNS.map(c => c.cat))]
    : kind === 'divs' ? [...new Set(COLUMNS.map(c => c.div))]
    : [...new Set(COLUMNS.map(c => c.gt))];
  cols.forEach(v => { if (action === 'all') STATE[kind].add(v); else STATE[kind].delete(v); });
  [...document.getElementById(containerId).children].forEach((chip, i) => chip.classList.toggle('active', STATE[kind].has(cols[i])));
  buildHead();
  render();
}
document.getElementById('catsAll').addEventListener('click', () => quickSelect('cats', 'chips-cats', 'all'));
document.getElementById('catsNone').addEventListener('click', () => quickSelect('cats', 'chips-cats', 'none'));
document.getElementById('divsAll').addEventListener('click', () => quickSelect('divs', 'chips-divs', 'all'));
document.getElementById('divsNone').addEventListener('click', () => quickSelect('divs', 'chips-divs', 'none'));
document.getElementById('gtsAll').addEventListener('click', () => quickSelect('gts', 'chips-gts', 'all'));
document.getElementById('gtsNone').addEventListener('click', () => quickSelect('gts', 'chips-gts', 'none'));

function buildHead() {
  const cols = activeColumns();
  const catRow = document.getElementById('catRow');
  const headRow = document.getElementById('headRow');
  catRow.innerHTML = '<th class="corner"></th>';
  headRow.innerHTML = '';
  const corner = document.createElement('th');
  corner.className = 'club-head';
  corner.textContent = LANG[CURLANG].club;
  headRow.appendChild(corner);

  let lastCat = null, span = 0, catTh = null;
  const catThs = [];
  cols.forEach(col => {
    if (col.cat !== lastCat) {
      if (catTh) catThs.push([catTh, span]);
      catTh = document.createElement('th');
      catTh.textContent = catLabel(col.cat);
      lastCat = col.cat;
      span = 0;
    }
    span++;
    const th = document.createElement('th');
    th.textContent = divLabel(col.div) + ' · ' + col.gt_short;
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

  TIER = {};
  const byCat = {};
  cols.forEach(c => { (byCat[c.cat] = byCat[c.cat] || []).push(c.key); });
  Object.values(byCat).forEach(keys => keys.forEach((k, i) => { TIER[k] = Math.min(i, 3); }));
}

function sortBy(key) {
  sortDir = (sortKey === key) ? -sortDir : -1;
  sortKey = key;
  render();
}

// 1st place = gold; the rest split into 4 flat (non-gradient) bands by
// how close the position is to the top vs. the bottom of the group.
function posBand(pos, size) {
  if (pos === 1) return 'pos-gold';
  if (size <= 1) return 'pos-gold';
  const pct = (pos - 1) / (size - 1);
  if (pct <= 0.25) return 'pos-green';
  if (pct <= 0.5) return 'pos-teal';
  if (pct <= 0.75) return 'pos-grey';
  return 'pos-red';
}
function posBadgeHtml(pos, size) {
  return `<span class="pos-badge ${posBand(pos, size)}">${pos}<span class="of">/${size}</span></span>`;
}

function render() {
  const cols = activeColumns();
  const q = document.getElementById('searchBox').value.trim().toLowerCase();
  const onlyPresent = document.getElementById('presentToggle').classList.contains('active');

  const totalFor = club => cols.reduce((s, c) => s + (club.cells[c.key] ? club.cells[c.key].n : 0), 0);
  const divsFor = club => new Set(cols.filter(c => club.cells[c.key]).map(c => c.cat + '_' + c.div)).size;

  let rows = CLUBS.filter(c => !q || c.club.toLowerCase().includes(q));
  if (onlyPresent) rows = rows.filter(c => totalFor(c) > 0);
  const valFor = c => sortKey === '__total' ? totalFor(c) : (c.cells[sortKey] ? c.cells[sortKey].n : 0);
  rows = rows.slice().sort((a, b) => sortDir * (valFor(a) - valFor(b)) || a.club.localeCompare(b.club));

  document.getElementById('resultCount').textContent = rows.length.toLocaleString() + ' ' + LANG[CURLANG].clubsWord;

  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols.length + 2;
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
    nameSpan.addEventListener('click', () => openClubModal(club));
    inner.appendChild(nameSpan);
    if (club.venues && club.venues.length) {
      const top = club.venues[0];
      const a = document.createElement('a');
      a.className = 'pin';
      a.href = top.maps || '#';
      a.target = '_blank';
      a.rel = 'noopener';
      a.title = `${top.venue} — ${top.n}/${top.total} (${top.pct}%)`;
      a.textContent = '\u{1F4CD} ' + top.pct + '%';
      a.addEventListener('click', e => e.stopPropagation());
      inner.appendChild(a);
    }
    clubTd.appendChild(inner);
    tr.appendChild(clubTd);

    cols.forEach(col => {
      const td = document.createElement('td');
      td.className = 'cell lvl-' + TIER[col.key];
      const v = club.cells[col.key];
      if (v) {
        const chip = document.createElement('span');
        chip.className = 'chip2 ' + posBand(v.pos, v.size);
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
    totalTd.innerHTML = `<strong>${totalFor(club)}</strong> ${LANG[CURLANG].of} ${divsFor(club)}`;
    tr.appendChild(totalTd);

    frag.appendChild(tr);
  });
  tbody.appendChild(frag);
}

const STAT_LABELS = {
  ru: ['клубов', 'команд (в фильтре)', 'колонок в таблице'],
  es: ['clubes', 'equipos (en el filtro)', 'columnas en la tabla'],
};
function renderStats() {
  const cols = activeColumns();
  const totalTeams = CLUBS.reduce((s, c) => s + cols.reduce((s2, col) => s2 + (c.cells[col.key] ? c.cells[col.key].n : 0), 0), 0);
  const nums = [CLUBS.length, totalTeams, cols.length];
  document.getElementById('stats').innerHTML = STAT_LABELS[CURLANG].map((l, idx) =>
    `<div class="stat"><div class="n">${nums[idx].toLocaleString()}</div><div class="l">${l}</div></div>`
  ).join('');
}

function teamCardLink(tid, name) {
  return tid ? `<a href="https://www.rffm.es/fichaequipo/${tid}" target="_blank" rel="noopener">${name}</a>` : name;
}
function groupCalLink(t) {
  const text = esc(t.grp || '');
  if (!(t.season_id && t.comp_id && t.group_id && t.gt_id)) return text;
  const url = `https://www.rffm.es/competicion/calendario?temporada=${t.season_id}&competicion=${t.comp_id}&grupo=${t.group_id}&jornada=1&tipojuego=${t.gt_id}`;
  return `<a href="${url}" target="_blank" rel="noopener">${text}</a>`;
}

function openClubModal(club) {
  const L = CURLANG;
  const info = club.info;
  const crestHtml = info && info.crest
    ? `<img class="modal-crest" src="${info.crest}" alt="" onerror="this.style.display='none'">` : '';
  const clubNameHtml = (info && info.reptid)
    ? `<a href="https://www.rffm.es/fichaequipo/${info.reptid}" target="_blank" rel="noopener">${esc(club.club)}</a>` : esc(club.club);
  const webRaw = info && info.web;
  const webHref = webRaw ? (webRaw.startsWith('http') ? webRaw : 'https://' + webRaw) : null;
  const webHtml = webHref ? `<div><a href="${webHref}" target="_blank" rel="noopener">${esc(webRaw)}</a></div>` : '';
  const addrLabel = L === 'ru' ? 'Юридический/контактный адрес клуба (не адрес поля)' : 'Dirección de correspondencia del club (no es la dirección del campo)';
  const addrHtml = info && info.address
    ? `<div class="modal-note">${addrLabel}: ${esc(info.address)}${info.locality ? ', ' + esc(info.locality) : ''}</div>` : '';
  const venueMapLabel = L === 'ru' ? 'карта' : 'mapa';
  const venuesHtml = (club.venues && club.venues.length)
    ? club.venues.map(v => `<div class="modal-venue"><span class="v-name">${esc(v.venue)}${v.address ? ' — ' + esc(v.address) : ''}</span>` +
        `<span class="v-stat">${v.n}/${v.total} (${v.pct}%)${v.maps ? ` &middot; <a href="${v.maps}" target="_blank" rel="noopener">${venueMapLabel}</a>` : ''}</span></div>`).join('')
    : `<div class="modal-note">${L === 'ru' ? 'Нет данных о домашних площадках.' : 'Sin datos de sedes locales.'}</div>`;

  // group by age category (youngest → oldest) then division (strongest → weakest)
  const byCat = new Map();
  (club.teams || []).forEach(t => {
    if (!byCat.has(t.cat)) byCat.set(t.cat, new Map());
    const byDiv = byCat.get(t.cat);
    if (!byDiv.has(t.div)) byDiv.set(t.div, []);
    byDiv.get(t.div).push(t);
  });
  const catsSorted = [...byCat.keys()].sort((a, b) => CAT_ORDER.indexOf(a) - CAT_ORDER.indexOf(b));
  let teamsHtml = '';
  catsSorted.forEach(cat => {
    teamsHtml += `<div class="modal-group-h">${catLabel(cat)}</div>`;
    const byDiv = byCat.get(cat);
    const divsSorted = [...byDiv.keys()].sort((a, b) => DIV_ORDER_JS.indexOf(a) - DIV_ORDER_JS.indexOf(b));
    divsSorted.forEach(div => {
      teamsHtml += `<div class="modal-div-h">${divLabel(div)}</div>`;
      teamsHtml += byDiv.get(div).map(t =>
        `<div class="modal-team-row"><span>${teamCardLink(t.tid, esc(t.team))} <span style="color:var(--ink-faint)">&middot; ${groupCalLink(t)} &middot; ${t.gt}</span></span>${posBadgeHtml(t.pos, t.size)}</div>`
      ).join('');
    });
  });
  if (!teamsHtml) teamsHtml = `<div class="modal-note">${L === 'ru' ? 'Нет данных о командах.' : 'Sin datos de equipos.'}</div>`;

  const venuesTitle = L === 'ru' ? 'Реальные площадки (из БД)' : 'Sedes reales (de la BD)';
  const teamsTitle = L === 'ru' ? 'Команды и дивизионы' : 'Equipos y divisiones';
  document.getElementById('modalContent').innerHTML = `
    <div class="modal-head">${crestHtml}<div><h2>${clubNameHtml}</h2>${webHtml}</div></div>
    ${addrHtml}
    <div class="modal-section"><h3>${venuesTitle}</h3>${venuesHtml}</div>
    <div class="modal-section"><h3>${teamsTitle}</h3>${teamsHtml}</div>
  `;
  document.getElementById('modalBackdrop').classList.remove('hidden');
}
function closeModal() { document.getElementById('modalBackdrop').classList.add('hidden'); }
document.getElementById('modalClose').addEventListener('click', closeModal);
document.getElementById('modalBackdrop').addEventListener('click', e => { if (e.target.id === 'modalBackdrop') closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

async function loadSeason(season) {
  document.getElementById('tbody').innerHTML = `<tr><td class="empty-state">${LANG[CURLANG].loading}</td></tr>`;
  const res = await fetch('data/club_map_' + season + '.json');
  DATA = await res.json();
  COLUMNS = DATA.columns;
  CLUBS = DATA.clubs;

  const allCats = new Set(COLUMNS.map(c => c.cat));
  const allDivs = new Set(COLUMNS.map(c => c.div));
  const allGts = new Set(COLUMNS.map(c => c.gt));
  if (!STATE.seeded) {
    DEFAULT_CATS.forEach(c => { if (allCats.has(c)) STATE.cats.add(c); });
    allDivs.forEach(d => STATE.divs.add(d));
    allGts.forEach(g => STATE.gts.add(g));
    STATE.seeded = true;
  } else {
    STATE.cats = new Set([...STATE.cats].filter(c => allCats.has(c)));
    STATE.divs = new Set([...STATE.divs].filter(d => allDivs.has(d)));
    STATE.gts = new Set([...STATE.gts].filter(g => allGts.has(g)));
    if (!STATE.cats.size) allCats.forEach(c => STATE.cats.add(c));
    if (!STATE.divs.size) allDivs.forEach(d => STATE.divs.add(d));
    if (!STATE.gts.size) allGts.forEach(g => STATE.gts.add(g));
  }

  buildFilterChips();
  buildHead();
  renderStats();
  render();
}

document.getElementById('seasonSelect').innerHTML = SEASONS.map(s => `<option value="${s}">${s}</option>`).join('');
document.getElementById('seasonSelect').value = SEASONS[SEASONS.length - 1];
document.getElementById('seasonSelect').addEventListener('change', function () { loadSeason(this.value); });

document.getElementById('searchBox').addEventListener('input', render);
document.getElementById('presentToggle').addEventListener('click', function () {
  this.classList.toggle('active');
  render();
});

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
    document.getElementById('searchBox').placeholder = LANG[CURLANG].searchPh;
    document.documentElement.lang = CURLANG;
    buildFilterChips();
    buildHead();
    renderStats();
    render();
  });
});

loadSeason(SEASONS[SEASONS.length - 1]);
</script>
</body>
</html>
"""

I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; clubes por división",
    "h1": "Mapa de clubes por división",
    "lede": "Cada fila es un club, cada columna una división/tipo de juego. La celda muestra cuántos equipos tiene el club ahí y la mejor posición alcanzada (de cualquiera de sus equipos) en su grupo. Haz clic en el nombre del club para ver sus sedes reales, escudo y la lista completa de equipos.",
    "lbl_season": "Temporada",
    "lbl_cats": "Categoría",
    "btn_all1": "Todas", "btn_none1": "Ninguna",
    "lbl_divs": "División",
    "btn_all2": "Todas", "btn_none2": "Ninguna",
    "lbl_gts": "Tipo de juego",
    "btn_all3": "Todos", "btn_none3": "Ninguno",
    "onlyPresent": "Solo con presencia visible",
    "legend1": "División más alta disponible",
    "legend2": "División más baja disponible",
    "legend3": "Líder de su grupo",
    "legend4": "Celda: nº de equipos del club ahí &middot; mejor posición/tamaño del grupo",
    "legend5": "&#128205; = sede real más frecuente del club (clic en el club — lista completa)",
    "foot1": 'Alcance: clubes con clasificación registrada dentro de los filtros elegidos; la temporada se elige arriba. Posiciones de la fase regular únicamente. Fuente: <code>output/processed/rffm/{teams,competitions,standings,matches,venues,clubs}.csv</code>.',
    "foot2": '<strong>Sobre las sedes:</strong> al hacer clic en el nombre del club se abre la lista real de sedes de ese club tomada de la base de datos (coordenadas exactas de <code>venues.csv</code>), no una única sede promedio &mdash; el fútbol infantil suele jugarse en formato "sede" con rotación de campos por jornada, así que un club suele tener varias direcciones reales, no un solo estadio.',
}


def build_html(seasons: list[str]) -> str:
    i18n_es = I18N_ES
    return (HTML
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%LANG_SWITCH%", lang_switch_html())
            .replace("%SEASONS_JSON%", json.dumps(seasons))
            .replace("%DEFAULT_CATS_JSON%", json.dumps(sorted(DEFAULT_CATEGORIES)))
            .replace("%CAT_ORDER_JSON%", json.dumps(CATEGORIES))
            .replace("%DIV_ORDER_JSON%", json.dumps(DIV_ORDER))
            .replace("%CAT_LABEL_RU_JSON%", json.dumps(CAT_LABEL_RU, ensure_ascii=False))
            .replace("%CAT_LABEL_ES_JSON%", json.dumps(CAT_LABEL_ES, ensure_ascii=False))
            .replace("%DIV_LABEL_RU_JSON%", json.dumps(DIV_LABEL_RU, ensure_ascii=False))
            .replace("%DIV_LABEL_ES_JSON%", json.dumps(DIV_LABEL_ES, ensure_ascii=False))
            .replace("%I18N_ES_JSON%", json.dumps(i18n_es, ensure_ascii=False)))


def main():
    parser = argparse.ArgumentParser(description="RFFM club x division matrix report")
    parser.add_argument("--season", default=None, help="build only this season's data file (default: every season with a complete core crawl)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    seasons = seasons or list_seasons()
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    for season in seasons:
        print(f"Building club/division map data for season {season}")
        data = load_data(season)
        print(f"  {len(data['clubs'])} clubs, {len(data['columns'])} columns")
        (data_dir / f"club_map_{season}.json").write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")

    (out_dir / "club_division_map.html").write_text(build_html(seasons), encoding="utf-8")
    print(f"Report written to {out_dir / 'club_division_map.html'}")


if __name__ == "__main__":
    main()
