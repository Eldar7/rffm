#!/usr/bin/env python3
"""
v2 PROOF-OF-CONCEPT: identical to weird_scores_report.py except its two
data-reading functions (compact_matches, compact_enrichment) source from
output/processed/rffm_parquet/ via rffm_data.read_table() instead of
pd.read_csv() on output/processed/rffm/<season>/*.csv. Kept as a separate
file (not a flag on the original) so the CSV-driven site is never at risk
of this change - see build_site.py for how it's wired into a separate
site/v2/ output alongside the untouched original.

One deliberate departure from that "otherwise byte-for-byte" parity:
compact_matches()'s "hc"/"ac" (home/away club) fields hold club_id (via
club_identity.py - team_club_map.csv, ground truth from RFFM's own site),
not club_name_raw text like the original - club-level aggregation
(clubAgg(), the "intra-club derby" section) needs a real identity, not a
name that can differ between two teams of the same club within one
season. compact_matches() also now writes a small "clubs" (club_id ->
display name) lookup into each season's _meta.json for the client to
resolve ids back to display text - see CLUB_NAMES in the JS below.

"Странные счета, доминаторы и аутсайдеры" — the RFFM weird-scores report.

Design and RU/ES bilingual toggle ported from a one-off Claude.ai artifact
with the same title. Filterable client-side by season / age category /
division / game type — everything (wildest score, blowouts, dominators,
curiosities, match-protocol goals/cards/referees) is recomputed in the
browser from data exported here, nothing is baked in for one fixed scope.

Data layout (all under <output-dir>/data/):
- weird_scores_<season>.json — every finished match that season across every
  age category/division/game-type this project tracks (see CATEGORIES/
  DIV_ORDER below), compact fields only. Fetched once per season switch.
- weird_scores_<season>_<CATEGORY>.json — that category's match-protocol
  data (goals/cards/officials + a player_id->appearances lookup, not the
  full per-match lineup table, which would be far too large to ship) for
  season x category combinations that have acta_partido coverage. Fetched
  lazily, only for the categories currently selected in the filter.

Usage:
    python analysis_scripts/weird_scores_report.py
    python analysis_scripts/weird_scores_report.py --season 2025-2026 --output-dir reports
"""

import argparse
import json
import re
from pathlib import Path

import pandas as pd

import club_identity as ci
import rffm_data as data
from site_theme import CSS, FONT_LINKS, THEME_INIT_JS, THEME_SWITCH_JS, switch_row_html

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

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

DIV_ORDER = [
    "DIVISION DE HONOR", "PRIMERA DIVISION AUTONOMICA", "PREFERENTE",
    "PRIMERA", "SEGUNDA", "TERCERA",
]
DIV_CODE = {
    "DIVISION DE HONOR": "DH", "PRIMERA DIVISION AUTONOMICA": "PDA", "PREFERENTE": "PREF",
    "PRIMERA": "PRIM", "SEGUNDA": "SEG", "TERCERA": "TER",
}
DIV_LABEL_ES = {
    "DH": "División de Honor", "PDA": "1ª Div. Autonómica", "PREF": "Preferente",
    "PRIM": "1ª División", "SEG": "2ª División", "TER": "3ª División",
}
DIV_LABEL_RU = DIV_LABEL_ES

GT_CODE = {"Futbol-7": "F7", "Fútbol Sala": "FS", "Futbol-11": "F11", "Fútbol-5": "F5"}
GT_SHORT = {"F7": "F-7", "FS": "Sala", "F11": "F-11", "F5": "F-5"}


def gt_code(gt: str) -> str:
    if gt in GT_CODE:
        return GT_CODE[gt]
    return re.sub(r"[^A-Za-z0-9]", "", str(gt)).upper()[:6] or "GT"


def norm_id(v):
    try:
        return str(int(float(str(v))))
    except (ValueError, TypeError):
        return None


def clean(v):
    """None for NaN/empty (pandas leaves real NaN floats in string columns
    for missing values — those serialize to the bare, non-JSON token `NaN`)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def list_seasons() -> list[str]:
    m = pd.read_csv(MANIFEST, dtype=str)
    core = m[(m["stage"] == "core") & (m["category_base"] == "ALL") &
             (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(core["season"].unique().tolist())


def latest_core_season() -> str:
    seasons = list_seasons()
    if not seasons:
        raise SystemExit("No season has a complete core crawl in coverage_manifest.csv")
    return seasons[-1]


# ---------------------------------------------------------------------------
# Data export
# ---------------------------------------------------------------------------

def compact_matches(season: str) -> list[dict]:
    """Every finished match this season, across every age category/division/
    game type this project tracks — compact fields for client-side filtering
    and recomputation (sections 01-06)."""
    matches = data.read_table("matches", season=season)
    teams = data.read_table("teams", season=season)
    comps = data.read_table("competitions", season=season)

    comps["division_level"] = comps["division_level"].fillna("OTHER")
    div_by_comp = comps.set_index("competition_id")["division_level"]

    m = matches.copy()
    m["division_level"] = m["competition_id"].map(div_by_comp)
    m = m[m["category"].isin(CATEGORIES) & m["division_level"].isin(DIV_ORDER) & m["game_type"].notna()].copy()
    m["hs"] = pd.to_numeric(m["home_score"], errors="coerce")
    m["as_"] = pd.to_numeric(m["away_score"], errors="coerce")
    played = m[m["is_finished"].str.lower() == "true"].dropna(subset=["hs", "as_"]).copy()
    played["hid"] = played["home_team_id"].map(norm_id)
    played["aid"] = played["away_team_id"].map(norm_id)

    tid_to_name = dict(zip(teams["team_id"].map(norm_id), teams["team"]))
    tid_to_club_id = {tid: ci.resolve(tid) for tid in teams["team_id"].map(norm_id).dropna().unique()}
    played["home_name"] = played["hid"].map(tid_to_name).fillna(played["home_team"])
    played["away_name"] = played["aid"].map(tid_to_name).fillna(played["away_team"])
    played["home_club"] = played["hid"].map(tid_to_club_id)
    played["away_club"] = played["aid"].map(tid_to_club_id)
    played["divc"] = played["division_level"].map(DIV_CODE)
    played["gtc"] = played["game_type"].map(gt_code)

    def club_id_or_none(v) -> int | None:
        return int(v) if pd.notna(v) else None

    out = []
    for r in played.to_dict("records"):
        out.append({
            "id": r["match_id"], "d": clean(r["match_date"]),
            "h": clean(r["home_name"]) or "?", "hid": r["hid"], "hc": club_id_or_none(r["home_club"]),
            "a": clean(r["away_name"]) or "?", "aid": r["aid"], "ac": club_id_or_none(r["away_club"]),
            "hs": int(r["hs"]), "as": int(r["as_"]),
            "comp": clean(r["competition"]), "grp": clean(r["group"]),
            "cat": r["category"], "div": r["divc"], "gt": r["gtc"],
        })
    return out


def compact_enrichment(season: str, category: str) -> dict | None:
    """goals/cards/officials + a player appearances lookup for one category —
    everything section 07 needs, minus the full per-match lineup table
    (too large to ship; only the is_goalkeeper flag it provides is kept,
    joined directly onto each goal row, and only the per-player appearance
    *count* it provides, not every row).

    Player names come from read_table("players_by_season", season=...), not
    the deduped read_table("players") - the original reads this season's own
    players.csv, and confirmed on real data that a player's recorded name
    spelling can genuinely change between seasons (RFFM's own site started
    serving some players' names without diacritics from 2024-2025 onward),
    so the deduped table's "latest name wins" pick would have broken this
    file's whole reason for existing: proving the migration is lossless."""
    goals = data.read_table("match_goals", season=season, category=category)
    if goals.empty:
        return None

    cards = data.read_table("match_cards", season=season, category=category)
    if cards.empty:
        cards = pd.DataFrame(columns=["match_id", "team_id", "player_id", "minute", "card_type_label"])
    officials = data.read_table("match_officials", season=season, category=category)
    if officials.empty:
        officials = pd.DataFrame(columns=["match_id", "official_kind", "official_id", "official_name"])
    lineups = data.read_table("match_lineups", season=season, category=category)
    if lineups.empty:
        lineups = pd.DataFrame(columns=["match_id", "team_id", "player_id", "is_goalkeeper"])
    players = data.read_table("players_by_season", season=season)
    if not players.empty:
        name_map = dict(zip(players["player_id"], players["player_name"]))
    else:
        name_map = {}

    if not lineups.empty:
        lu = lineups[["match_id", "team_id", "player_id", "is_goalkeeper"]].drop_duplicates()
        goals = goals.merge(lu, on=["match_id", "team_id", "player_id"], how="left")
        apps = lineups.groupby("player_id")["match_id"].nunique().to_dict()
    else:
        goals["is_goalkeeper"] = None
        apps = {}
    goals["is_goalkeeper"] = goals["is_goalkeeper"].fillna("False")
    goals["minute"] = pd.to_numeric(goals["minute"], errors="coerce")
    if not cards.empty:
        cards["minute"] = pd.to_numeric(cards["minute"], errors="coerce")

    pids = set(goals["player_id"].dropna())
    if not cards.empty:
        pids |= set(cards["player_id"].dropna())
    players_out = {pid: (clean(name_map.get(pid)) or pid) for pid in pids}

    goals_out = [
        {"m": r["match_id"], "t": norm_id(r["team_id"]), "p": r["player_id"],
         "min": (int(r["minute"]) if pd.notna(r.get("minute")) else None),
         "gk": r.get("is_goalkeeper") == "True"}
        for r in goals.to_dict("records")
    ]
    cards_out = [
        {"m": r["match_id"], "t": norm_id(r["team_id"]), "p": r["player_id"],
         "min": (int(r["minute"]) if pd.notna(r.get("minute")) else None),
         "type": clean(r.get("card_type_label"))}
        for r in cards.to_dict("records")
    ] if not cards.empty else []
    officials_out = [
        {"m": r["match_id"], "kind": clean(r["official_kind"]), "oid": clean(r["official_id"]), "name": clean(r["official_name"])}
        for r in officials.to_dict("records")
    ] if not officials.empty else []

    return {"goals": goals_out, "cards": cards_out, "officials": officials_out,
            "apps": apps, "players": players_out}


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    """One file per (season, category): that category's matches for the
    season plus its match-protocol enrichment (or empty enrichment where
    acta_partido hasn't been crawled for it) — fetched lazily, only for
    whichever categories are active in the filter, so switching season
    never has to ship all 11 categories' matches at once (~30MB unsplit)."""
    seasons = seasons or list_seasons()
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    for season in seasons:
        print(f"Building weird-scores data for season {season}")
        matches = compact_matches(season)
        print(f"  {len(matches)} played matches")

        by_cat: dict[str, list] = {}
        for m in matches:
            by_cat.setdefault(m["cat"], []).append(m)
        cats_present = sorted(by_cat)

        names = ci.club_display_names()
        slugs = ci.club_slugs()
        club_ids = {m["hc"] for m in matches} | {m["ac"] for m in matches}
        club_ids.discard(None)
        meta = {
            "season": season, "categories": cats_present,
            "divs": sorted(set(m["div"] for m in matches)),
            "gts": sorted(set(m["gt"] for m in matches)),
            "clubs": {cid: names.get(cid) or f"club {cid}" for cid in club_ids},
            # club_profile.html's "Соперничества" section lives at the same
            # club_id-based slug for every club (club_identity.py) - lets
            # the client link "see the full history between these two clubs"
            # straight into it (?club=<hc slug>&opp=<ac slug>#rivalrySection)
            # without a second lookup.
            "club_slugs": {cid: slugs.get(cid) for cid in club_ids if slugs.get(cid)},
        }
        (data_dir / f"weird_scores_{season}_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")

        for cat in cats_present:
            enrich = compact_enrichment(season, cat) or {
                "goals": [], "cards": [], "officials": [], "apps": {}, "players": {}}
            print(f"    {cat}: {len(by_cat[cat])} matches, {len(enrich['goals'])} goals, {len(enrich['cards'])} cards")
            payload = {"season": season, "cat": cat, "matches": by_cat[cat], **enrich}
            (data_dir / f"weird_scores_{season}_{cat}.json").write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")

    (out_dir / "weird_scores.html").write_text(build_html(seasons), encoding="utf-8")
    print(f"Report written to {out_dir / 'weird_scores.html'}")


# ---------------------------------------------------------------------------
# HTML shell — everything below is recomputed client-side from the JSON
# exported above, filtered by season / age category / division / game type.
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — странные счета, доминаторы и аутсайдеры</title>
<a class="back" href="index.html" style="display:inline-block;margin:16px 0 0 20px">&larr; RFFM data</a>
%FONT_LINKS%
%THEME_INIT%
<style>%CSS%
.filter-panel{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:0.9rem 1.1rem;
  box-shadow:var(--shadow); display:flex; flex-direction:column; gap:0.6rem; margin:18px 0 0; }
.filter-row{ display:flex; align-items:flex-start; gap:0.9rem; flex-wrap:wrap; }
.filter-label{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; font-weight:700; text-transform:uppercase;
  letter-spacing:0.05em; color:var(--ink-muted); white-space:nowrap; padding-top:0.4rem; min-width:82px; }
.filter-chips{ display:flex; flex-wrap:wrap; gap:0.35rem; flex:1; }
.chip{ display:inline-flex; align-items:center; padding:0.26rem 0.6rem; border-radius:999px; font-size:0.78rem; cursor:pointer;
  border:1.5px solid var(--line); background:var(--surface-2); color:var(--ink-muted); user-select:none;
  transition:background .12s,border-color .12s,color .12s; }
.chip.active{ background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
.chip:hover:not(.active){ border-color:var(--accent); color:var(--ink); }
.quick-btns{ display:flex; gap:0.3rem; align-items:center; padding-top:0.3rem; }
.quick-btns button{ font-size:0.7rem; padding:0.18rem 0.5rem; border:1px solid var(--line); border-radius:4px;
  background:var(--surface-2); color:var(--ink-muted); cursor:pointer; font-family:inherit; }
.quick-btns button:hover{ background:var(--accent); color:var(--accent-ink); }
select#seasonSelect{ font-family:'JetBrains Mono',monospace; font-size:0.85rem; font-weight:700; color:var(--ink);
  background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:0.35rem 0.6rem; cursor:pointer; }
.loading-state{ padding:40px; text-align:center; color:var(--ink-muted); font-family:'JetBrains Mono',monospace; }
</style>
</head>
<body>
<div class="wrap">
  <div class="masthead">
    <div>
      <div class="kicker"><span id="txt-kicker"></span></div>
      <h1><span id="txt-h1"></span></h1>
    </div>
    <div class="scope-block">
      %SWITCH_ROW%
      <div class="scope">
        <span id="txt-scope1"></span><br>
        <span id="txt-scope2"></span><br>
        <span id="txt-scope3"></span>
      </div>
    </div>
  </div>

  <div class="filter-panel">
    <div class="filter-row">
      <span class="filter-label" id="lbl-season">Сезон</span>
      <select id="seasonSelect"></select>
    </div>
    <div class="filter-row">
      <span class="filter-label" id="lbl-cats">Возраст</span>
      <div class="filter-chips" id="chips-cats"></div>
      <div class="quick-btns"><button type="button" id="catsAll">Все</button><button type="button" id="catsNone">Нет</button></div>
    </div>
    <div class="filter-row">
      <span class="filter-label" id="lbl-divs">Дивизион</span>
      <div class="filter-chips" id="chips-divs"></div>
      <div class="quick-btns"><button type="button" id="divsAll">Все</button><button type="button" id="divsNone">Нет</button></div>
    </div>
    <div class="filter-row">
      <span class="filter-label" id="lbl-gts">Тип игры</span>
      <div class="filter-chips" id="chips-gts"></div>
      <div class="quick-btns"><button type="button" id="gtsAll">Все</button><button type="button" id="gtsNone">Нет</button></div>
    </div>
  </div>

  <div id="statStrip" class="stat-strip"></div>
  <div id="content"></div>
  <footer id="footerNote"></footer>
</div>

<script id="dataMeta" type="application/json">%SEASONS_JSON%</script>
<script>
const SEASONS = JSON.parse(document.getElementById('dataMeta').textContent);
const DEFAULT_CATS = %DEFAULT_CATS_JSON%;
const CAT_ORDER = %CAT_ORDER_JSON%;
const DIV_ORDER_JS = %DIV_ORDER_JSON%;
const CAT_LABEL_RU = %CAT_LABEL_RU_JSON%;
const CAT_LABEL_ES = %CAT_LABEL_ES_JSON%;
const DIV_LABEL_RU = %DIV_LABEL_RU_JSON%;
const DIV_LABEL_ES = %DIV_LABEL_ES_JSON%;
const GT_SHORT = %GT_SHORT_JSON%;
const TEAM_MIN_GAMES = 10, CLUB_MIN_GAMES = 15, BLOWOUT_MARGIN = 15, TOP_BLOWOUTS = 12, REF_MIN_GAMES = 15;

let CURLANG = 'ru';
let CURSEASON = SEASONS[SEASONS.length - 1];
let MATCHES = [];
let META = null;
let CLUB_NAMES = {}; // club_id -> display name, set from META.clubs on each season load
let CLUB_SLUGS = {}; // club_id -> club_profile.html slug, set from META.club_slugs on each season load
const STATE = { cats: new Set(), divs: new Set(), gts: new Set(), seeded: false };
const ENRICH_CACHE = {};

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function ruPlural(n, one, few, many) {
  n = Math.abs(Math.round(n));
  if (n % 100 >= 11 && n % 100 <= 14) return many;
  const last = n % 10;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}
function catLabel(c) { return CURLANG === 'ru' ? CAT_LABEL_RU[c] : CAT_LABEL_ES[c]; }
function divLabel(d) { return CURLANG === 'ru' ? DIV_LABEL_RU[d] : DIV_LABEL_ES[d]; }
function teamLink(tid, name) { const n = esc(name); return tid ? `<a href="https://www.rffm.es/fichaequipo/${tid}" target="_blank" rel="noopener">${n}</a>` : n; }
function matchLink(mid, text) { return `<a href="https://www.rffm.es/acta-partido/${mid}" target="_blank" rel="noopener">${text}</a>`; }
function playerLink(pid, name) { const n = esc(name || pid); return pid ? `<a href="https://www.rffm.es/fichajugador/${pid}" target="_blank" rel="noopener">${n}</a>` : n; }
function scoreTxt(m) { return `${m.hs}:${m.as}`; }
// "See the full history between these two clubs" - straight into
// club_profile.html's Соперничества section (club_profile_v2.py's ?opp=
// deep link), null when either side's club_id has no club_profile.html
// page at all (e.g. an adult-only category club_identity.py resolved but
// club_profile_data_v2.py never profiled - see that module's docstring).
function rivalryUrl(hc, ac) {
  const hs = CLUB_SLUGS[hc], as_ = CLUB_SLUGS[ac];
  if (!hs || !as_ || hc === ac) return null;
  return `club_profile.html?club=${encodeURIComponent(hs)}&opp=${encodeURIComponent(as_)}#rivalrySection`;
}
function fmtN(n) { return n.toLocaleString(CURLANG === 'ru' ? 'ru-RU' : 'es-ES'); }

const T = {
  ru: {
    kicker: 'RFFM &middot; Отчёт по данным', h1: 'Странные счета,<br>доминаторы и аутсайдеры',
    scope1: s => `Сезон <b>${s}</b>`, scope2: 'Все возрастные категории и дивизионы (фильтруется ниже)',
    scope3: 'Futbol&#8209;7, Futbol&#8209;11 и F&uacute;tbol Sala',
    lblSeason: 'Сезон', lblCats: 'Возраст', lblDivs: 'Дивизион', lblGts: 'Тип игры',
    btnAll: 'Все', btnNone: 'Нет', loading: 'Загрузка…', noData: 'Нет данных для текущего фильтра.',
    s1: 'сыгранных матчей', s2: 'гола за матч в среднем', s3: n => `разгромов с разницей &ge;${n} мячей`, s4: 'матчей 0:0',
    h01: 'Самый дикий счёт сезона', l01: 'Разница результата, невероятная даже по меркам детской лиги, где счёт формируется свободно.',
    h01m2: n => `${n} мячей разницы в одном матче`,
    rivalryLabel: 'история встреч клубов &rarr;',
    h02: n => `Топ&#8209;${n} самых разгромных матчей`, l02: 'По абсолютной разнице мячей среди завершённых игр сезона в выбранных фильтрах.',
    th_date: 'Дата', th_home: 'Хозяева', th_score: 'Счёт', th_away: 'Гости', th_comp: 'Турнир', th_match: 'Матч',
    h03: 'Другая крайность: нулевые ничьи', l03: (n, avg) => `${n} ${ruPlural(n,'матч','матча','матчей')} закончились 0:0 &mdash; при среднем счёте ${avg} гола за игру это статистическая редкость. И есть матчи, где всё решалось в перестрелке с равным счётом.`,
    drawNote: (g) => `${g} ${ruPlural(g,'мяч','мяча','мячей')}, ничья в перестрелке`,
    h04: 'Доминаторы и аутсайдеры &mdash; на уровне команд',
    l04: n => `Разница забитых и пропущенных, только команды, сыгравшие ${n}+ матчей. Клуб может выставлять несколько составов на разных уровнях &mdash; здесь считаем отдельный состав («A», «B» и т.д.).`,
    dominators: 'Доминаторы', underdogs: 'Аутсайдеры',
    teamSub: (p,w,d,l,gf,ga) => `${p} ${ruPlural(p,'игра','игры','игр')} &middot; ${w}В&#8211;${d}Н&#8211;${l}П &middot; ${gf}:${ga}`,
    h05: 'Доминаторы и аутсайдеры &mdash; на уровне клубов',
    l05: n => `Один клуб часто выставляет несколько команд на разных уровнях лиги (клуб &ne; команда). Здесь суммарная разница мячей по всем составам клуба, минимум ${n} игр.`,
    gdClub: 'GD, сумма по клубу',
    clubSub: (t,p,wp) => `${t} ${ruPlural(t,'команда','команды','команд')} &middot; ${p} ${ruPlural(p,'игра','игры','игр')} &middot; ${wp}% побед`,
    h06: 'Курьёзы',
    c1h: 'Один клуб — два разных мира',
    c1p: (club,n,worstLink,worstScore,worstP,bestLink,bestScore,bestDiff) => `У «<b>${esc(club)}</b>» ${n} команд в разных группах. Команда ${worstLink} &mdash; худшая среди своих (${worstScore} за ${worstP} игр), а ${bestLink} того же клуба &mdash; доминатор (${bestScore}, GD ${bestDiff}). Одна вывеска, полярно разный футбол.`,
    c2h: 'Внутриклубное дерби с погромом',
    c2p: (club,h,a,date,score,agg) => `${esc(club)} выставляет составы ${h} и ${a} в одной группе. В матче ${esc(date)} счёт был ${score}${agg}.`,
    c2agg: (gf,ga) => ` &mdash; по сумме двух встреч сезона: ${gf}:${ga}`,
    c3h: n => `${n} внутриклубных матчей`,
    c3p: n => `${n} ${ruPlural(n,'матч','матча','матчей')} сезона &mdash; это игры клуба сам с собой (например «A» против «C»). Формально соперники, по факту &mdash; тренировочный спарринг с официальным протоколом.`,
    c4h: n => `${n} разгромов, но лига в целом плотная`,
    c4p: (n,pct,avg,margin) => `При среднем счёте ${avg} гола за матч только ${n} игр (${pct}%) завершились с разницей ${margin}+ мячей. Экстремальные результаты &mdash; редкость на фоне общей массы, где решает один-два мяча.`,
    h07: 'Из протоколов матчей: голы, карточки, судьи',
    scopeMark: 'Охват', scopeText: (cats,n) => `Построчные протоколы матчей (acta) собраны для категорий <b>${cats}</b> в выбранном сезоне: ${n} матчей с данными протокола.`,
    s07_1: 'голов в протоколах', s07_2: (y,r) => `карточки (${y} жёлт. / ${r} красн.)`, s07_3: 'матчей хоть с одной карточкой', s07_4: 'позиций в составах (учтено)',
    leadSuffix: '&mdash; лучший бомбардир', leadSub: (g,a,gpm,teams) => `${g} голов за ${a} ${ruPlural(a,'матч','матча','матчей')} (${gpm} гола за игру) за ${teams}.`,
    l07top: 'Топ&#8209;12 бомбардиров по протоколам голов.', th_player: 'Игрок', th_goals: 'Голы', th_apps: 'Матчи', th_gpm: 'Гол/матч', th_team: 'Команда',
    c07_1h: n => `${n} голов одного ребёнка за один матч`, c07_1again: n => ` &mdash; и это случилось ${n} раза`,
    c07_1p: (link,n,again) => `${link} забил ${n} мячей в одном матче${again} &mdash; рекорд в выбранных фильтрах.`,
    c07_2h: m => `Красная карточка на ${m}&#8209;й минуте`, c07_2p: (link,m) => `${link} получил прямую красную на минуте ${m} &mdash; одно из самых ранних удалений в выбранных фильтрах.`,
    c07_3h: n => `${n} голов забили «вратари»`, c07_3p: 'В протоколах составов эти голы числятся за игроками, отмеченными как голкиперы в этом матче. В детском футболе позиция вратаря часто ротируется внутри команды.',
    c07_4h: '«Трудолюбивый» и «строгий» &mdash; разные судьи',
    c07_4p: (busy,apps,strict,cpm) => `${busy} отсудил больше всех матчей (${apps}), а чаще всех показывает карточки ${strict} (${cpm} карт./матч) &mdash; нагрузка не равна строгости.`,
    l07match: 'Топ&#8209;10 матчей: сколько голов забил один игрок за игру.', th_group: 'Группа',
    l07ref: n => `Судьи: кто отсудил больше всех матчей и кто чаще всех показывает карточки (минимум ${n} матчей).`,
    capBusy: 'Самые трудолюбивые', capStrict: 'Самые строгие', th_ref: 'Судья', th_cards: 'Карточек', th_cpm: 'Карт./матч',
    footer: season => `Источник: <span>output/processed/rffm/*.csv</span> &middot; матчи со статусом is_finished=True, сезон ${season} &middot; club &ne; team: агрегаты «на уровне клубов» суммируют все команды с одинаковым club_name_raw &middot; раздел 07 построен по протоколам матчей (match_goals/match_cards/match_officials/match_lineups). Ссылки ведут на официальные страницы rffm.es.`,
    no07: 'Для выбранных фильтров пока нет построчных протоколов матчей (голы/карточки/судьи).',
  },
  es: {
    kicker: 'RFFM &middot; Informe de datos', h1: 'Marcadores extraños,<br>dominadores y colistas',
    scope1: s => `Temporada <b>${s}</b>`, scope2: 'Todas las categorías y divisiones (se filtra abajo)',
    scope3: 'Fútbol&#8209;7, Fútbol&#8209;11 y Fútbol Sala',
    lblSeason: 'Temporada', lblCats: 'Categoría', lblDivs: 'División', lblGts: 'Tipo de juego',
    btnAll: 'Todas', btnNone: 'Ninguna', loading: 'Cargando…', noData: 'No hay datos para el filtro actual.',
    s1: 'partidos disputados', s2: 'goles de media por partido', s3: n => `goleadas con diferencia &ge;${n} goles`, s4: 'partidos 0:0',
    h01: 'El marcador más disparatado de la temporada', l01: 'Una diferencia de resultado difícil de creer incluso para los estándares de la liga infantil, donde el marcador se forma libremente.',
    h01m2: n => `${n} goles de diferencia en un solo partido`,
    rivalryLabel: 'historial entre estos clubes &rarr;',
    h02: n => `Top ${n} goleadas más abultadas`, l02: 'Por diferencia absoluta de goles entre los partidos finalizados con los filtros elegidos.',
    th_date: 'Fecha', th_home: 'Local', th_score: 'Resultado', th_away: 'Visitante', th_comp: 'Competición', th_match: 'Partido',
    h03: 'El otro extremo: empates a cero', l03: (n, avg) => `${n} partidos terminaron 0:0 &mdash; con una media de ${avg} goles por partido, es una rareza estadística. Y hay partidos que se decidieron en un intercambio de goles con marcador igualado.`,
    drawNote: (g) => `${g} goles, empate a goles`,
    h04: 'Dominadores y colistas &mdash; a nivel de equipo',
    l04: n => `Diferencia de goles a favor y en contra, solo equipos con ${n}+ partidos jugados. Un club puede inscribir varios equipos en distintos niveles &mdash; aquí se cuenta cada equipo por separado.`,
    dominators: 'Dominadores', underdogs: 'Colistas',
    teamSub: (p,w,d,l,gf,ga) => `${p} partidos &middot; ${w}G-${d}E-${l}P &middot; ${gf}:${ga}`,
    h05: 'Dominadores y colistas &mdash; a nivel de club',
    l05: n => `Un mismo club suele inscribir varios equipos en distintos niveles de la liga. Aquí se suma la diferencia de goles de todos los equipos del club, mínimo ${n} partidos.`,
    gdClub: 'DG, suma del club',
    clubSub: (t,p,wp) => `${t} equipos &middot; ${p} partidos &middot; ${wp}% de victorias`,
    h06: 'Curiosidades',
    c1h: 'Un club, dos mundos distintos',
    c1p: (club,n,worstLink,worstScore,worstP,bestLink,bestScore,bestDiff) => `«<b>${esc(club)}</b>» tiene ${n} equipos en distintos grupos. El equipo ${worstLink} es el peor de los suyos (${worstScore} en ${worstP} partidos), mientras que ${bestLink} del mismo club es casi un dominador (${bestScore}, DG ${bestDiff}). Un mismo nombre, un fútbol completamente opuesto.`,
    c2h: 'Un derbi interno con paliza incluida',
    c2p: (club,h,a,date,score,agg) => `${esc(club)} inscribe a sus equipos ${h} y ${a} en el mismo grupo. El ${esc(date)} el resultado fue ${score}${agg}.`,
    c2agg: (gf,ga) => ` &mdash; en el balance de los dos partidos de la temporada: ${gf}:${ga}`,
    c3h: n => `${n} partidos de un club contra sí mismo`,
    c3p: n => `${n} partidos de la temporada son un club jugando contra sí mismo (p. ej. «A» contra «C»). Formalmente son rivales; en la práctica, un amistoso con acta oficial.`,
    c4h: n => `${n} goleadas, pero la liga en general es reñida`,
    c4p: (n,pct,avg,margin) => `Con una media de ${avg} goles por partido, solo ${n} partidos (${pct}%) terminaron con una diferencia de ${margin}+ goles. Los resultados extremos son la excepción.`,
    h07: 'De las actas de los partidos: goles, tarjetas, árbitros',
    scopeMark: 'Alcance', scopeText: (cats,n) => `Las actas de los partidos están recopiladas para las categorías <b>${cats}</b> en la temporada elegida: ${n} partidos con datos de acta.`,
    s07_1: 'goles registrados en las actas', s07_2: (y,r) => `tarjetas (${y} amarillas / ${r} rojas)`, s07_3: 'partidos con al menos una tarjeta', s07_4: 'apariciones consideradas',
    leadSuffix: '&mdash; máximo goleador', leadSub: (g,a,gpm,teams) => `${g} goles en ${a} partidos (${gpm} goles por partido) con ${teams}.`,
    l07top: 'Top 12 goleadores según las actas de goles.', th_player: 'Jugador', th_goals: 'Goles', th_apps: 'Partidos', th_gpm: 'Goles/partido', th_team: 'Equipo',
    c07_1h: n => `${n} goles de un solo niño en un partido`, c07_1again: n => ` &mdash; y ocurrió ${n} veces`,
    c07_1p: (link,n,again) => `${link} marcó ${n} goles en un solo partido${again} &mdash; récord en los filtros elegidos.`,
    c07_2h: m => `Tarjeta roja en el minuto ${m}`, c07_2p: (link,m) => `${link} vio la roja directa en el minuto ${m} &mdash; una de las expulsiones más tempranas en los filtros elegidos.`,
    c07_3h: n => `${n} goles marcados por «porteros»`, c07_3p: 'En las actas de alineaciones, estos goles están anotados a jugadores marcados como porteros en ese partido. En el fútbol infantil la posición de portero suele rotar.',
    c07_4h: '«Trabajador» y «severo» son árbitros distintos',
    c07_4p: (busy,apps,strict,cpm) => `${busy} pitó más partidos (${apps}), mientras que quien más tarjetas saca por partido es ${strict} (${cpm} tarj./partido).`,
    l07match: 'Top 10 partidos: cuántos goles marcó un solo jugador en el encuentro.', th_group: 'Grupo',
    l07ref: n => `Árbitros: quién pitó más partidos y quién saca tarjetas con más frecuencia (mínimo ${n} partidos).`,
    capBusy: 'Los más trabajadores', capStrict: 'Los más severos', th_ref: 'Árbitro', th_cards: 'Tarjetas', th_cpm: 'Tarj./partido',
    footer: season => `Fuente: <span>output/processed/rffm/*.csv</span> &middot; partidos con is_finished=True, temporada ${season} &middot; club &ne; equipo &middot; la sección 07 se construye a partir de las actas (match_goals/match_cards/match_officials/match_lineups). Los enlaces apuntan a rffm.es.`,
    no07: 'Todavía no hay actas de partido (goles/tarjetas/árbitros) para los filtros elegidos.',
  },
};

function teamAgg(matches) {
  const map = new Map(), names = new Map();
  function bump(tid, club, gf, ga) {
    if (!tid) return;
    if (!map.has(tid)) map.set(tid, { tid, club, played: 0, gf: 0, ga: 0, wins: 0, draws: 0, losses: 0 });
    const t = map.get(tid);
    t.played++; t.gf += gf; t.ga += ga;
    if (gf > ga) t.wins++; else if (gf === ga) t.draws++; else t.losses++;
  }
  matches.forEach(m => {
    bump(m.hid, m.hc, m.hs, m.as); bump(m.aid, m.ac, m.as, m.hs);
    if (m.hid) names.set(m.hid, m.h); if (m.aid) names.set(m.aid, m.a);
  });
  return [...map.values()].map(t => ({ ...t, name: names.get(t.tid), diff: t.gf - t.ga }));
}
function clubAgg(matches) {
  const map = new Map();
  function bump(club, gf, ga, tid) {
    if (!club) return;
    if (!map.has(club)) map.set(club, { club, played: 0, gf: 0, ga: 0, wins: 0, teams: new Set() });
    const c = map.get(club);
    c.played++; c.gf += gf; c.ga += ga; if (gf > ga) c.wins++; if (tid) c.teams.add(tid);
  }
  matches.forEach(m => { bump(m.hc, m.hs, m.as, m.hid); bump(m.ac, m.as, m.hs, m.aid); });
  return [...map.values()].map(c => ({
    club: CLUB_NAMES[c.club] ?? String(c.club), played: c.played, gf: c.gf, ga: c.ga, wins: c.wins,
    teams: c.teams.size, diff: c.gf - c.ga, win_pct: Math.round(c.wins / c.played * 100),
  }));
}

function renderSec01(t, matches) {
  if (!matches.length) return `<section><div class="section-head"><h2>${t.h01}</h2><span class="n">01</span></div><p class="lede">${t.noData}</p></section>`;
  const w = matches.slice().sort((a, b) => Math.abs(b.hs - b.as) - Math.abs(a.hs - a.as))[0];
  const margin = Math.abs(w.hs - w.as);
  return `<section>
    <div class="section-head"><h2>${t.h01}</h2><span class="n">01</span></div>
    <p class="lede">${t.l01}</p>
    <div class="hero-card">
      <div class="side home"><div class="club">${teamLink(w.hid, w.h)}</div></div>
      <div class="score">${matchLink(w.id, `${w.hs}<span class="colon">:</span>${w.as}`)}</div>
      <div class="side away"><div class="club">${teamLink(w.aid, w.a)}</div></div>
      <div class="hero-meta">
        <span>${esc(w.d)} &middot; ${esc(w.comp)}, ${esc(w.grp)}</span>
        <span>${t.h01m2(margin)}</span>
        ${rivalryUrl(w.hc, w.ac) ? `<span><a href="${rivalryUrl(w.hc, w.ac)}" target="_blank" rel="noopener">${t.rivalryLabel}</a></span>` : ''}
      </div>
    </div>
  </section>`;
}

function renderSec02(t, matches) {
  const top = matches.slice().sort((a, b) => Math.abs(b.hs - b.as) - Math.abs(a.hs - a.as)).slice(0, TOP_BLOWOUTS);
  const rows = top.map((m, i) => {
    const cls = m.hs >= m.as ? 'win' : 'lose';
    const rUrl = rivalryUrl(m.hc, m.ac);
    return `<tr><td class="rank">${i + 1}</td><td class="meta">${esc(m.d)}</td><td>${teamLink(m.hid, m.h)}</td>
      <td class="score ${cls}">${matchLink(m.id, scoreTxt(m))}</td><td>${teamLink(m.aid, m.a)}</td>
      <td class="meta">${esc(m.comp)}, ${esc(m.grp)}${rUrl ? ` &middot; <a href="${rUrl}" target="_blank" rel="noopener">${t.rivalryLabel}</a>` : ''}</td></tr>`;
  }).join('');
  return `<section>
    <div class="section-head"><h2>${t.h02(TOP_BLOWOUTS)}</h2><span class="n">02</span></div>
    <p class="lede">${t.l02}</p>
    <div class="table-scroll"><table><thead><tr><th></th><th>${t.th_date}</th><th>${t.th_home}</th>
      <th style="text-align:center">${t.th_score}</th><th>${t.th_away}</th><th>${t.th_comp}</th></tr></thead>
      <tbody>${rows || `<tr><td class="meta">${t.noData}</td></tr>`}</tbody></table></div>
  </section>`;
}

function renderSec03(t, matches, avgGoals) {
  const zeros = matches.filter(m => m.hs === 0 && m.as === 0).sort((a, b) => (a.d || '').localeCompare(b.d || ''));
  const draws = matches.filter(m => m.hs === m.as && m.hs > 0).sort((a, b) => (b.hs + b.as) - (a.hs + a.as)).slice(0, 2);
  const rows = zeros.slice(0, 5).map(m => `<tr><td class="meta">${esc(m.d)}</td>
      <td>${teamLink(m.hid, m.h)} &ndash; ${teamLink(m.aid, m.a)}</td>
      <td class="score">${matchLink(m.id, '0:0')}</td><td class="meta">${esc(m.comp)}, ${esc(m.grp)}</td></tr>`)
    .concat(draws.map(m => `<tr><td class="meta">${esc(m.d)}</td>
      <td>${teamLink(m.hid, m.h)} &ndash; ${teamLink(m.aid, m.a)}</td>
      <td class="score win">${matchLink(m.id, scoreTxt(m))}</td>
      <td class="meta">${esc(m.comp)}, ${esc(m.grp)} &middot; ${t.drawNote(m.hs + m.as)}</td></tr>`))
    .join('');
  return `<section>
    <div class="section-head"><h2>${t.h03}</h2><span class="n">03</span></div>
    <p class="lede">${t.l03(zeros.length, avgGoals)}</p>
    <div class="table-scroll"><table><thead><tr><th>${t.th_date}</th><th>${t.th_match}</th>
      <th style="text-align:center">${t.th_score}</th><th>${t.th_comp}</th></tr></thead>
      <tbody>${rows || `<tr><td class="meta">${t.noData}</td></tr>`}</tbody></table></div>
  </section>`;
}

function teamRowlines(t, rows) {
  return rows.map(r => {
    const diffStr = r.diff > 0 ? `+${r.diff}` : (r.diff < 0 ? `&#8722;${Math.abs(r.diff)}` : '0');
    return `<div class="rowline"><div><div class="name">${teamLink(r.tid, r.name)}</div>
      <div class="sub">${t.teamSub(r.played, r.wins, r.draws, r.losses, r.gf, r.ga)}</div></div>
      <div class="stat">${diffStr}</div></div>`;
  }).join('');
}
function renderSec04(t, teams) {
  const eligible = teams.filter(x => x.played >= TEAM_MIN_GAMES);
  const dom = eligible.slice().sort((a, b) => b.diff - a.diff).slice(0, 5);
  const out = eligible.slice().sort((a, b) => a.diff - b.diff).slice(0, 5);
  return `<section>
    <div class="section-head"><h2>${t.h04}</h2><span class="n">04</span></div>
    <p class="lede">${t.l04(TEAM_MIN_GAMES)}</p>
    <div class="split">
      <div class="panel gold"><div class="panel-head">${t.dominators}<span class="tag">GD</span></div>${teamRowlines(t, dom) || `<div class="rowline">${t.noData}</div>`}</div>
      <div class="panel red"><div class="panel-head">${t.underdogs}<span class="tag">GD</span></div>${teamRowlines(t, out) || `<div class="rowline">${t.noData}</div>`}</div>
    </div>
  </section>`;
}

function clubRowlines(t, rows) {
  return rows.map(r => {
    const diffStr = r.diff > 0 ? `+${r.diff}` : (r.diff < 0 ? `&#8722;${Math.abs(r.diff)}` : '0');
    return `<div class="rowline"><div><div class="name">${esc(r.club)}</div>
      <div class="sub">${t.clubSub(r.teams, r.played, r.win_pct)}</div></div>
      <div class="stat">${diffStr}</div></div>`;
  }).join('');
}
function renderSec05(t, clubs) {
  const eligible = clubs.filter(x => x.played >= CLUB_MIN_GAMES);
  const dom = eligible.slice().sort((a, b) => b.diff - a.diff).slice(0, 5);
  const out = eligible.slice().sort((a, b) => a.diff - b.diff).slice(0, 5);
  return `<section>
    <div class="section-head"><h2>${t.h05}</h2><span class="n">05</span></div>
    <p class="lede">${t.l05(CLUB_MIN_GAMES)}</p>
    <div class="split">
      <div class="panel gold"><div class="panel-head">${t.dominators}<span class="tag">${t.gdClub}</span></div>${clubRowlines(t, dom) || `<div class="rowline">${t.noData}</div>`}</div>
      <div class="panel red"><div class="panel-head">${t.underdogs}<span class="tag">${t.gdClub}</span></div>${clubRowlines(t, out) || `<div class="rowline">${t.noData}</div>`}</div>
    </div>
  </section>`;
}

function renderSec06(t, matches, teams) {
  const curios = [];
  // a) one club, two worlds
  const eligible = teams.filter(x => x.played >= TEAM_MIN_GAMES && x.club);
  const byClub = new Map();
  eligible.forEach(x => { if (!byClub.has(x.club)) byClub.set(x.club, []); byClub.get(x.club).push(x); });
  let bestSpread = null;
  byClub.forEach((grp, club) => {
    if (grp.length < 2) return;
    const best = grp.reduce((a, b) => a.diff > b.diff ? a : b);
    const worst = grp.reduce((a, b) => a.diff < b.diff ? a : b);
    const spread = best.diff - worst.diff;
    if (!bestSpread || spread > bestSpread.spread) bestSpread = { club, best, worst, spread, n: grp.length };
  });
  if (bestSpread) {
    const { club, best, worst, n } = bestSpread;
    curios.push([t.c1h, t.c1p(CLUB_NAMES[club] ?? String(club), n, teamLink(worst.tid, worst.name), `${worst.gf}:${worst.ga}`, worst.played,
      teamLink(best.tid, best.name), `${best.gf}:${best.ga}`, (best.diff > 0 ? '+' : '') + best.diff)]);
  }
  // b) intra-club derby blowout
  const intra = matches.filter(m => m.hc && m.hc === m.ac);
  if (intra.length) {
    const derby = intra.slice().sort((a, b) => Math.abs(b.hs - b.as) - Math.abs(a.hs - a.as))[0];
    const legs = matches.filter(m => (m.hid === derby.hid && m.aid === derby.aid) || (m.hid === derby.aid && m.aid === derby.hid));
    let agg = '';
    if (legs.length > 1) {
      let gf = 0, ga = 0;
      legs.forEach(l => { if (l.hid === derby.hid) { gf += l.hs; ga += l.as; } else { gf += l.as; ga += l.hs; } });
      agg = t.c2agg(gf, ga);
    }
    curios.push([t.c2h, t.c2p(CLUB_NAMES[derby.hc] ?? String(derby.hc), teamLink(derby.hid, derby.h), teamLink(derby.aid, derby.a), derby.d, matchLink(derby.id, scoreTxt(derby)), agg)]);
  }
  // c) intra-club match count
  curios.push([t.c3h(intra.length), t.c3p(intra.length)]);
  // d) blowout share
  const blowouts = matches.filter(m => Math.abs(m.hs - m.as) >= BLOWOUT_MARGIN);
  const avg = matches.length ? (matches.reduce((s, m) => s + m.hs + m.as, 0) / matches.length).toFixed(2) : '0';
  const pct = matches.length ? (blowouts.length / matches.length * 100).toFixed(1) : '0';
  curios.push([t.c4h(blowouts.length), t.c4p(blowouts.length, pct, avg, BLOWOUT_MARGIN)]);

  const grid = curios.map(([h, p]) => `<div class="curio"><h3>${h}</h3><p>${p}</p></div>`).join('');
  return `<section><div class="section-head"><h2>${t.h06}</h2><span class="n">06</span></div><div class="curio-grid">${grid}</div></section>`;
}

function renderSec07(t, matches, enrich) {
  const { goals, cards, officials, apps, players } = enrich;
  if (!goals.length) {
    return `<section><div class="section-head"><h2>${t.h07}</h2><span class="n">07</span></div><p class="lede">${t.no07}</p></section>`;
  }
  const matchesById = new Map(matches.map(m => [m.id, m]));
  const totalCards = cards.length;
  const yellow = cards.filter(c => c.type === 'amarilla').length;
  const red = cards.filter(c => c.type === 'roja').length;
  const cardMatchIds = new Set(cards.map(c => c.m));
  const pctCard = matches.length ? (cardMatchIds.size / matches.length * 100).toFixed(1) : '0';
  const totalApps = Object.values(apps).reduce((s, n) => s + n, 0);

  // scorer leaderboard
  const byPlayer = new Map();
  goals.forEach(g => {
    if (!byPlayer.has(g.p)) byPlayer.set(g.p, { p: g.p, goals: 0, teams: new Set() });
    const rec = byPlayer.get(g.p);
    rec.goals++; if (g.t) rec.teams.add(g.t);
  });
  const scorers = [...byPlayer.values()].map(r => {
    const a = apps[r.p] || r.goals;
    return { ...r, apps: a, gpm: (r.goals / a).toFixed(2), name: players[r.p] };
  }).sort((a, b) => b.goals - a.goals);

  const teamNamesFor = (teamSet) => [...teamSet].map(tid => teamLink(tid, matchTeamName(matches, tid))).join(' / ');
  const lead = scorers[0];
  const leadRow = lead ? `<div class="lead-card">
    <div class="big-num">${lead.goals}</div>
    <div class="desc"><div class="name">${playerLink(lead.p, lead.name)} ${t.leadSuffix}</div>
    <div class="sub">${t.leadSub(lead.goals, lead.apps, lead.gpm, teamNamesFor(lead.teams))}</div></div>
  </div>` : '';

  const scorerRows = scorers.slice(0, 12).map((r, i) => `<tr><td class="rank">${i + 1}</td><td>${playerLink(r.p, r.name)}</td>
    <td class="num">${r.goals}</td><td class="num">${r.apps}</td><td class="num">${r.gpm}</td>
    <td class="meta">${teamNamesFor(r.teams)}</td></tr>`).join('');

  // curiosities
  const curios = [];
  const perMatch = new Map();
  goals.forEach(g => { const k = g.p + '|' + g.m; perMatch.set(k, (perMatch.get(k) || 0) + 1); });
  let bestKey = null, bestN = 0;
  perMatch.forEach((n, k) => { if (n > bestN) { bestN = n; bestKey = k; } });
  const bestCount = [...perMatch.values()].filter(n => n === bestN).length;
  if (bestKey) {
    const pid = bestKey.split('|')[0];
    const again = bestCount > 1 ? t.c07_1again(bestCount) : '';
    curios.push([t.c07_1h(bestN), t.c07_1p(playerLink(pid, players[pid]), bestN, again)]);
  }
  const realReds = cards.filter(c => c.type === 'roja' && c.min !== null && c.min !== 999).sort((a, b) => a.min - b.min);
  if (realReds.length) {
    const rc = realReds[0];
    curios.push([t.c07_2h(rc.min), t.c07_2p(playerLink(rc.p, players[rc.p]), rc.min)]);
  }
  const gkGoals = goals.filter(g => g.gk).length;
  curios.push([t.c07_3h(gkGoals), t.c07_3p]);
  const refApps = new Map(), refName = new Map();
  officials.filter(o => o.kind === 'referee').forEach(o => {
    refApps.set(o.oid, (refApps.get(o.oid) || new Set())); refApps.get(o.oid).add(o.m); refName.set(o.oid, o.name);
  });
  const cardsPerMatch = new Map();
  cards.forEach(c => cardsPerMatch.set(c.m, (cardsPerMatch.get(c.m) || 0) + 1));
  const refMatches = new Map();
  officials.filter(o => o.kind === 'referee').forEach(o => {
    if (!refMatches.has(o.oid)) refMatches.set(o.oid, new Set());
    refMatches.get(o.oid).add(o.m);
  });
  const busyList = [...refApps.entries()].map(([oid, set]) => ({ oid, apps: set.size, name: refName.get(oid) })).sort((a, b) => b.apps - a.apps);
  const strictList = [...refMatches.entries()].map(([oid, set]) => {
    let c = 0; set.forEach(m => { c += cardsPerMatch.get(m) || 0; });
    return { oid, apps: set.size, cards: c, cpm: set.size ? c / set.size : 0, name: refName.get(oid) };
  }).filter(r => r.apps >= REF_MIN_GAMES).sort((a, b) => b.cpm - a.cpm);
  if (busyList.length && strictList.length && busyList[0].oid !== strictList[0].oid) {
    curios.push([t.c07_4h, t.c07_4p(esc(busyList[0].name), busyList[0].apps, esc(strictList[0].name), strictList[0].cpm.toFixed(2))]);
  }
  const curioGrid = curios.map(([h, p]) => `<div class="curio"><h3>${h}</h3><p>${p}</p></div>`).join('');

  const matchRows = [...perMatch.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10).map(([k, n]) => {
    const [pid, mid] = k.split('|');
    const m = matchesById.get(mid);
    const desc = m ? `${teamLink(m.hid, m.h)} ${matchLink(mid, scoreTxt(m))} ${teamLink(m.aid, m.a)}` : matchLink(mid, '&mdash;');
    return `<tr><td class="meta">${m ? esc(m.d) : ''}</td><td>${playerLink(pid, players[pid])}</td>
      <td class="num">${n}</td><td class="meta">${desc}</td><td class="meta">${m ? esc(m.grp) : ''}</td></tr>`;
  }).join('');

  const busyRows = busyList.slice(0, 10).map(r => `<tr><td>${esc(r.name)}</td><td class="num">${r.apps}</td></tr>`).join('');
  const strictRows = strictList.slice(0, 10).map(r => `<tr><td>${esc(r.name)}</td><td class="num">${r.apps}</td><td class="num">${r.cards}</td><td class="num">${r.cpm.toFixed(2)}</td></tr>`).join('');

  const catNames = [...STATE.cats].filter(c => ENRICH_CACHE[CURSEASON + '_' + c]).map(catLabel).join(', ');

  return `<section>
    <div class="section-head"><h2>${t.h07}</h2><span class="n">07</span></div>
    <div class="scope-note"><span class="mark">${t.scopeMark}</span><span>${t.scopeText(catNames, fmtN(cardMatchIds.size || goals.length))}</span></div>
    <div class="stat-strip">
      <div class="cell"><div class="num">${fmtN(goals.length)}</div><div class="lbl">${t.s07_1}</div></div>
      <div class="cell"><div class="num">${totalCards}</div><div class="lbl">${t.s07_2(yellow, red)}</div></div>
      <div class="cell"><div class="num">${pctCard}%</div><div class="lbl">${t.s07_3}</div></div>
      <div class="cell"><div class="num">${fmtN(totalApps)}</div><div class="lbl">${t.s07_4}</div></div>
    </div>
    ${leadRow}
    <p class="lede" style="margin-top:24px">${t.l07top}</p>
    <div class="table-scroll"><table><thead><tr><th></th><th>${t.th_player}</th><th style="text-align:right">${t.th_goals}</th>
      <th style="text-align:right">${t.th_apps}</th><th style="text-align:right">${t.th_gpm}</th><th>${t.th_team}</th></tr></thead>
      <tbody>${scorerRows}</tbody></table></div>
    <div class="curio-grid" style="margin-top:22px">${curioGrid}</div>
    <p class="lede" style="margin-top:24px">${t.l07match}</p>
    <div class="table-scroll"><table><thead><tr><th>${t.th_date}</th><th>${t.th_player}</th>
      <th style="text-align:right">${t.th_goals}</th><th>${t.th_match}</th><th>${t.th_group}</th></tr></thead>
      <tbody>${matchRows}</tbody></table></div>
    <p class="lede" style="margin-top:24px">${t.l07ref(REF_MIN_GAMES)}</p>
    <div class="split">
      <div class="table-scroll"><div class="table-cap">${t.capBusy}</div><table><thead><tr><th>${t.th_ref}</th>
        <th style="text-align:right">${t.th_apps}</th></tr></thead><tbody>${busyRows}</tbody></table></div>
      <div class="table-scroll"><div class="table-cap">${t.capStrict}</div><table><thead><tr><th>${t.th_ref}</th>
        <th style="text-align:right">${t.th_apps}</th><th style="text-align:right">${t.th_cards}</th>
        <th style="text-align:right">${t.th_cpm}</th></tr></thead><tbody>${strictRows}</tbody></table></div>
    </div>
  </section>`;
}
function matchTeamName(matches, tid) {
  for (const m of matches) { if (m.hid === tid) return m.h; if (m.aid === tid) return m.a; }
  return tid;
}

function activeMatches() {
  return MATCHES.filter(m => STATE.cats.has(m.cat) && STATE.divs.has(m.div) && STATE.gts.has(m.gt));
}

function mergedEnrichment(filtered) {
  const visible = new Set(filtered.map(m => m.id));
  const goals = [], cards = [], officials = [], apps = {}, players = {};
  STATE.cats.forEach(cat => {
    const e = ENRICH_CACHE[CURSEASON + '_' + cat];
    if (!e) return;
    Object.assign(players, e.players);
    Object.entries(e.apps).forEach(([pid, n]) => { apps[pid] = (apps[pid] || 0) + n; });
    e.goals.forEach(g => { if (visible.has(g.m)) goals.push(g); });
    e.cards.forEach(c => { if (visible.has(c.m)) cards.push(c); });
    e.officials.forEach(o => { if (visible.has(o.m)) officials.push(o); });
  });
  return { goals, cards, officials, apps, players };
}

function renderAll() {
  const t = T[CURLANG];
  document.getElementById('txt-kicker').innerHTML = t.kicker;
  document.getElementById('txt-h1').innerHTML = t.h1;
  document.getElementById('txt-scope1').innerHTML = t.scope1(CURSEASON);
  document.getElementById('txt-scope2').innerHTML = t.scope2;
  document.getElementById('txt-scope3').innerHTML = t.scope3;
  document.getElementById('lbl-season').textContent = t.lblSeason;
  document.getElementById('lbl-cats').textContent = t.lblCats;
  document.getElementById('lbl-divs').textContent = t.lblDivs;
  document.getElementById('lbl-gts').textContent = t.lblGts;
  ['catsAll', 'divsAll', 'gtsAll'].forEach(id => document.getElementById(id).textContent = t.btnAll);
  ['catsNone', 'divsNone', 'gtsNone'].forEach(id => document.getElementById(id).textContent = t.btnNone);

  const filtered = activeMatches();
  const matchesPlayed = filtered.length;
  const totalGoals = filtered.reduce((s, m) => s + m.hs + m.as, 0);
  const avgGoals = matchesPlayed ? (totalGoals / matchesPlayed).toFixed(2) : '0';
  const blowouts = filtered.filter(m => Math.abs(m.hs - m.as) >= BLOWOUT_MARGIN).length;
  const draws00 = filtered.filter(m => m.hs === 0 && m.as === 0).length;

  document.getElementById('statStrip').innerHTML = `
    <div class="cell"><div class="num">${fmtN(matchesPlayed)}</div><div class="lbl">${t.s1}</div></div>
    <div class="cell"><div class="num">${avgGoals}</div><div class="lbl">${t.s2}</div></div>
    <div class="cell"><div class="num">${blowouts}</div><div class="lbl">${t.s3(BLOWOUT_MARGIN)}</div></div>
    <div class="cell"><div class="num">${draws00}</div><div class="lbl">${t.s4}</div></div>`;

  if (!matchesPlayed) {
    document.getElementById('content').innerHTML = `<section><p class="lede">${t.noData}</p></section>`;
    document.getElementById('footerNote').innerHTML = '';
    return;
  }

  const teams = teamAgg(filtered), clubs = clubAgg(filtered);
  const enrich = mergedEnrichment(filtered);
  document.getElementById('content').innerHTML = [
    renderSec01(t, filtered), renderSec02(t, filtered), renderSec03(t, filtered, avgGoals),
    renderSec04(t, teams), renderSec05(t, clubs), renderSec06(t, filtered, teams),
    renderSec07(t, filtered, enrich),
  ].join('');
  document.getElementById('footerNote').innerHTML = t.footer(CURSEASON);
}

function buildChipRow(containerId, kind, items, labelFn) {
  const el = document.getElementById(containerId);
  el.innerHTML = '';
  items.forEach(val => {
    const chip = document.createElement('span');
    chip.className = 'chip' + (STATE[kind].has(val) ? ' active' : '');
    chip.textContent = labelFn(val);
    chip.addEventListener('click', async () => {
      if (STATE[kind].has(val)) STATE[kind].delete(val); else STATE[kind].add(val);
      chip.classList.toggle('active', STATE[kind].has(val));
      if (kind === 'cats') await ensureEnrichmentLoaded();
      renderAll();
    });
    el.appendChild(chip);
  });
}
function buildFilterChips() {
  buildChipRow('chips-cats', 'cats', META.categories.slice().sort((a, b) => CAT_ORDER.indexOf(a) - CAT_ORDER.indexOf(b)), catLabel);
  buildChipRow('chips-divs', 'divs', META.divs.slice().sort((a, b) => DIV_ORDER_JS.indexOf(a) - DIV_ORDER_JS.indexOf(b)), divLabel);
  buildChipRow('chips-gts', 'gts', META.gts.slice(), g => GT_SHORT[g] || g);
}
async function quickSelect(kind, containerId, action) {
  const items = kind === 'cats' ? META.categories : kind === 'divs' ? META.divs : META.gts;
  items.forEach(v => { if (action === 'all') STATE[kind].add(v); else STATE[kind].delete(v); });
  [...document.getElementById(containerId).children].forEach((chip, i) => chip.classList.toggle('active', STATE[kind].has(items[i])));
  if (kind === 'cats') await ensureEnrichmentLoaded();
  renderAll();
}
document.getElementById('catsAll').addEventListener('click', () => quickSelect('cats', 'chips-cats', 'all'));
document.getElementById('catsNone').addEventListener('click', () => quickSelect('cats', 'chips-cats', 'none'));
document.getElementById('divsAll').addEventListener('click', () => quickSelect('divs', 'chips-divs', 'all'));
document.getElementById('divsNone').addEventListener('click', () => quickSelect('divs', 'chips-divs', 'none'));
document.getElementById('gtsAll').addEventListener('click', () => quickSelect('gts', 'chips-gts', 'all'));
document.getElementById('gtsNone').addEventListener('click', () => quickSelect('gts', 'chips-gts', 'none'));

async function ensureEnrichmentLoaded() {
  const fetches = [...STATE.cats].map(async cat => {
    const key = CURSEASON + '_' + cat;
    if (key in ENRICH_CACHE) return;
    try {
      const res = await fetch(`data/weird_scores_${CURSEASON}_${cat}.json`);
      const payload = res.ok ? await res.json() : null;
      ENRICH_CACHE[key] = payload ? { goals: payload.goals, cards: payload.cards, officials: payload.officials, apps: payload.apps, players: payload.players } : null;
    } catch (e) { ENRICH_CACHE[key] = null; }
  });
  await Promise.all(fetches);
}

async function loadSeason(season) {
  CURSEASON = season;
  document.getElementById('content').innerHTML = `<div class="loading-state">${T[CURLANG].loading}</div>`;
  const metaRes = await fetch(`data/weird_scores_${season}_meta.json`);
  META = await metaRes.json();
  CLUB_NAMES = META.clubs || {};
  CLUB_SLUGS = META.club_slugs || {};

  const activeCats = [...STATE.cats].filter(c => META.categories.includes(c));
  if (!STATE.seeded || !activeCats.length) {
    STATE.cats = new Set(META.categories.filter(c => DEFAULT_CATS.includes(c)));
    if (!STATE.cats.size) META.categories.forEach(c => STATE.cats.add(c));
    STATE.seeded = true;
  } else {
    STATE.cats = new Set(activeCats);
  }
  STATE.divs = new Set(META.divs);
  STATE.gts = new Set(META.gts);

  MATCHES = [];
  await ensureEnrichmentLoaded();
  await Promise.all([...STATE.cats].map(async cat => {
    const res = await fetch(`data/weird_scores_${season}_${cat}.json`);
    if (!res.ok) return;
    const payload = await res.json();
    MATCHES.push(...payload.matches);
  }));

  buildFilterChips();
  renderAll();
}

document.getElementById('seasonSelect').innerHTML = SEASONS.map(s => `<option value="${s}">${s}</option>`).join('');
document.getElementById('seasonSelect').value = CURSEASON;
document.getElementById('seasonSelect').addEventListener('change', function () { loadSeason(this.value); });

document.querySelectorAll('.lang-opt').forEach(function (btn) {
  btn.addEventListener('click', function () {
    CURLANG = btn.getAttribute('data-lang-btn');
    document.querySelectorAll('.lang-opt').forEach(b => b.classList.toggle('is-active', b === btn));
    document.documentElement.lang = CURLANG;
    buildFilterChips();
    renderAll();
  });
});
%THEME_SWITCH_JS%

loadSeason(CURSEASON);
</script>
</body>
</html>
"""


def build_html(seasons: list[str]) -> str:
    return (HTML
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%THEME_INIT%", THEME_INIT_JS)
            .replace("%THEME_SWITCH_JS%", THEME_SWITCH_JS)
            .replace("%CSS%", CSS)
            .replace("%SWITCH_ROW%", switch_row_html())
            .replace("%SEASONS_JSON%", json.dumps(seasons))
            .replace("%DEFAULT_CATS_JSON%", json.dumps(sorted(DEFAULT_CATEGORIES)))
            .replace("%CAT_ORDER_JSON%", json.dumps(CATEGORIES))
            .replace("%DIV_ORDER_JSON%", json.dumps(list(DIV_CODE.values())))
            .replace("%CAT_LABEL_RU_JSON%", json.dumps(CAT_LABEL_RU, ensure_ascii=False))
            .replace("%CAT_LABEL_ES_JSON%", json.dumps(CAT_LABEL_ES, ensure_ascii=False))
            .replace("%DIV_LABEL_RU_JSON%", json.dumps(DIV_LABEL_RU, ensure_ascii=False))
            .replace("%DIV_LABEL_ES_JSON%", json.dumps(DIV_LABEL_ES, ensure_ascii=False))
            .replace("%GT_SHORT_JSON%", json.dumps(GT_SHORT, ensure_ascii=False)))


def main():
    parser = argparse.ArgumentParser(description="RFFM weird scores / dominators / outsiders report")
    parser.add_argument("--season", default=None, help="build only this season's data file (default: every season with a complete core crawl)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


if __name__ == "__main__":
    main()
