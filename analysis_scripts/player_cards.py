#!/usr/bin/env python3
"""
Player card: which team(s)/division(s) a player was registered to, per
season — from player_competition_participation.csv (opt-in fichajugador
enrichment; a player can have more than one concurrent row, e.g. a reserve-
team + first-team dual registration, see DATA_DICTIONARY.md). Linked from
the Team Card's roster x matches matrix (team_cards.py/team_rosters.py):
clicking a player there opens this page for the current season, with a
checkbox to expand to every season this project has fichajugador data for
(only 2023-2024 onward — see coverage_manifest.csv).

150k+ distinct players in 2025-2026 alone rules out one file per player (or
one big per-season file). Instead this shards player_competition_
participation.csv by `int(player_id) % SHARD_MOD`, one JSON per (season,
shard) under <output-dir>/data/player_participation_<season>/<shard>.json
— player_card.html computes the same shard index client-side (int(id) %
SHARD_MOD, mirrored in JS) and fetches just that one shard per season, ~100
players' worth of noise around the one it actually wants rather than the
whole season.

Usage:
    python analysis_scripts/player_cards.py
    python analysis_scripts/player_cards.py --output-dir reports
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from club_division_map import DIV_LABEL_ES, DIV_LABEL_RU
from site_theme import (DATATABLE_CSS, DATATABLE_JS, FONT_LINKS, LANG_SWITCH_JS, THEME_INIT_JS,
                         THEME_SWITCH_JS, club_slug_map, switch_row_html)
from team_cards import build_club_team_cards

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

SHARD_MOD = 100


def list_participation_seasons() -> list[str]:
    m = pd.read_csv(MANIFEST, dtype=str)
    ok = m[(m["stage"] == "fichajugador") & (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(ok["season"].unique().tolist())


def clean(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def shard_of(player_id: str) -> int:
    return int(player_id) % SHARD_MOD


def build_season_shards(season: str) -> dict[int, dict[str, dict]]:
    d = BASE / season
    part = pd.read_csv(d / "player_competition_participation.csv", dtype=str)
    players = pd.read_csv(d / "players.csv", dtype=str)
    comps = pd.read_csv(d / "competitions.csv", dtype=str)

    pid_to_name = dict(zip(players["player_id"], players["player_name"]))
    pid_to_birth = dict(zip(players["player_id"], players["birth_year"]))
    comp_meta = comps.set_index("competition_id")[
        ["category_base", "division_level", "is_femenino", "game_type", "game_type_id"]]
    part = part.join(comp_meta, on="competition_id")

    # Same club_name_raw -> slug map team_cards.py used to name its
    # data/team_cards_<season>/<slug>.json files, computed via the exact
    # same function (not just the same club_slug_map() call with a
    # different name list — collision numbering ("-2", "-3", ...) depends
    # on which OTHER names share a base slug, so this must draw from
    # team_cards.py's own club universe, not player_competition_
    # participation.csv's, or a "Команда" link here can silently resolve to
    # a different club's file whenever two names collide).
    club_teams = build_club_team_cards(season)
    slug_by_club = club_slug_map(sorted(club_teams.keys()))

    shards: dict[int, dict[str, dict]] = {}
    for row in part.itertuples(index=False):
        pid = row.player_id
        if not pid:
            continue
        shard = shards.setdefault(shard_of(pid), {})
        player = shard.setdefault(pid, {
            "name": pid_to_name.get(pid) or pid,
            "birth_year": clean(pid_to_birth.get(pid)),
            "rows": [],
        })
        club = clean(row.club_name_raw)
        player["rows"].append({
            "team": clean(row.team), "team_id": clean(row.team_id),
            "club": club, "club_slug": slug_by_club.get(club),
            "comp": clean(row.competition), "comp_id": clean(row.competition_id),
            "grp": clean(row.group), "group_id": clean(row.group_id),
            "cat": clean(getattr(row, "category_base", None)) or "OTHER",
            "div": clean(getattr(row, "division_level", None)) or "OTHER",
            "gt": clean(getattr(row, "game_type", None)), "gt_id": clean(getattr(row, "game_type_id", None)),
            "season_id": clean(row.season_id),
            "pos": clean(row.team_position), "pts": clean(row.team_points),
        })
    return shards


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    seasons = seasons or list_participation_seasons()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "player_card.html").write_text(build_html(seasons), encoding="utf-8")

    for season in seasons:
        print(f"Building player participation shards for season {season}")
        shards = build_season_shards(season)
        data_dir = out_dir / "data" / f"player_participation_{season}"
        data_dir.mkdir(parents=True, exist_ok=True)
        for shard_id, payload in shards.items():
            (data_dir / f"{shard_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                encoding="utf-8")
        print(f"  {sum(len(p) for p in shards.values())} players across {len(shards)} shards written to {data_dir}")


I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; ficha de jugador",
    "back": "&larr; Mapa de clubes",
    "backTeam": "&larr; Ficha de equipo",
    "loading": "Cargando…",
    "not_found": "No se encontraron datos de inscripción para este jugador.",
    "h_reg": "Inscripciones por equipo/división",
    "reg_p": "Por defecto las filas siguen el orden de las columnas (temporada → categoría → división → equipo). "
             "Haz clic en ▾ de cualquier columna para ordenar y filtrar, como en Excel. «Resumen» se calcula con "
             "los datos del equipo (sin minutos jugados ni asistencias, que la fuente no registra) y se carga "
             "aparte, puede tardar un momento.",
    "birth": "Año de nacimiento",
    "all_seasons": "Mostrar todas las temporadas",
    "th_season": "Temporada", "th_cat": "Categoría", "th_div": "División", "th_team": "Equipo", "th_comp": "Competición",
    "th_summary": "Resumen",
    "stSeasons": "Temporadas", "stClubs": "Clubes", "stTeams": "Equipos", "stApps": "Partidos (total)", "stGoals": "Goles (total)",
    "nowLabel": "Ahora:",
    "footer": 'Construido a partir de <code>output/processed/rffm/player_competition_participation.csv</code>. Ver '
              '<code>analysis_scripts/player_cards.py</code>.',
}

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — карточка игрока</title>
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
.page{ max-width:900px; margin:0 auto; padding:2.25rem 1.25rem 4rem; display:flex; flex-direction:column; gap:1.5rem; }
h1{ font-family:'Oswald', ui-sans-serif, "Arial Narrow", "Helvetica Neue", Arial, sans-serif; font-weight:700;
  text-transform:uppercase; letter-spacing:0.01em; text-wrap:balance; margin:0; color:var(--ink); font-size:clamp(1.3rem,2.6vw,1.8rem); line-height:1.2; }
header.masthead{display:flex; flex-direction:column; gap:0.4rem; border-bottom:3px solid var(--ink); padding-bottom:1rem; position:relative;}
.eyebrow{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:var(--accent); }
.club-sub{margin:0; color:var(--ink-soft); font-size:0.95rem;}
a.back{font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:var(--accent); text-decoration:none;}
a.back:hover{text-decoration:underline;}
.masthead .switch-row{position:absolute; top:0; right:0; display:flex; gap:0.5rem;}
.lang-switch, .theme-switch{ display:inline-flex; border:1px solid var(--line-strong); border-radius:999px; overflow:hidden; }
.lang-opt, .theme-opt{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:0.04em;
  padding:4px 12px; background:var(--surface); color:var(--ink-soft); border:none; cursor:pointer; }
.lang-opt.is-active, .theme-opt.is-active{background:var(--accent); color:#fff;}
.theme-opt{font-size:13px; padding:3px 10px;}

.season-badge{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; font-weight:700; letter-spacing:0.03em;
  background:var(--accent-soft); color:var(--accent); border-radius:999px; padding:0.12rem 0.6rem; }
.now-badge{ font-size:0.85rem; }
.now-badge a{font-weight:700;}

.stats-strip{ display:grid; grid-template-columns:repeat(auto-fit, minmax(6.5rem, 1fr));
  background:var(--surface); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); overflow:hidden; }
.stats-strip .stat-cell{ padding:0.7rem 0.8rem; border-right:1px solid var(--line); }
.stats-strip .stat-cell:last-child{border-right:none;}
.stats-strip .stat-cell .num{ font-family:'JetBrains Mono',monospace; font-weight:700; font-size:1.3rem; color:var(--ink); font-variant-numeric:tabular-nums; }
.stats-strip .stat-cell .lbl{font-size:0.68rem; color:var(--ink-soft); margin-top:0.15rem;}

.section-h{ display:flex; align-items:center; gap:0.9rem; flex-wrap:wrap; }
.section-h h2{ font-family:'Oswald',sans-serif; font-weight:700; text-transform:uppercase; font-size:1.1rem; color:var(--ink); margin:0; }
.section-p{color:var(--ink-soft); font-size:0.82rem; max-width:70ch; margin:0;}
label.all-seasons{ display:inline-flex; align-items:center; gap:0.4rem; font-size:0.82rem; color:var(--ink-soft); cursor:pointer; margin-left:auto; }

.table-shell{ background:var(--surface); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); overflow:hidden; }
.table-scroll{overflow-x:auto;}
table{border-collapse:separate; border-spacing:0; font-size:0.85rem; width:100%;}
thead th{ background:var(--surface); border-bottom:1px solid var(--line-strong); padding:0.55rem 0.7rem;
  text-align:left; font-size:0.7rem; letter-spacing:0.05em; text-transform:uppercase; color:var(--ink-soft); white-space:nowrap; }
tbody td{ border-bottom:1px solid var(--line); padding:0.5rem 0.7rem; vertical-align:middle; }
tbody tr:last-child td{border-bottom:none;}
tbody tr:hover td{background:var(--accent-soft);}
.season-cell{font-family:'JetBrains Mono',monospace; font-size:0.78rem; color:var(--ink-soft); white-space:nowrap;}
.tier-chip{ display:inline-block; font-size:0.72rem; font-weight:700; padding:0.1rem 0.5rem; border-radius:999px;
  background:var(--accent-soft); color:var(--accent); white-space:nowrap; }
.team-name{color:var(--ink); font-weight:600;}
.comp-meta{display:block; font-size:0.72rem; color:var(--ink-faint); margin-top:0.1rem;}
.summary-cell{font-family:'JetBrains Mono',monospace; font-size:0.78rem; white-space:nowrap; color:var(--ink-soft);}
.empty-state{padding:2rem; text-align:center; color:var(--ink-faint);}
.birth-note{color:var(--ink-soft); font-size:0.85rem;}
footer.note{font-size:0.78rem; color:var(--ink-soft); max-width:90ch;}
%DATATABLE_CSS%
</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    %SWITCH_ROW%
    <a class="back" id="backLink" href="club_division_map.html">&larr; Карта клубов</a>
    <span class="eyebrow" data-i18n="eyebrow">RFFM (Мадрид) &middot; карточка игрока</span>
    <h1 id="playerName">…</h1>
    <p class="club-sub">
      <span id="playerSub"></span>
      <span class="now-badge" id="nowBadge"></span>
    </p>
  </header>

  <div class="stats-strip" id="profileStrip"></div>

  <section>
    <div class="section-h">
      <h2 data-i18n="h_reg">Заявки по командам/дивизионам</h2>
      <label class="all-seasons"><input type="checkbox" id="allSeasonsBox"><span data-i18n="all_seasons">Показать все сезоны</span></label>
    </div>
    <p class="section-p" data-i18n="reg_p">
      По умолчанию строки идут в порядке колонок (сезон → категория → дивизион → команда). Клик по ▾ в
      заголовке — сортировка и фильтр, как в Excel. «Сводка» считается по данным команды (без игрового
      времени и передач — их нет в источнике) и подгружается отдельно, может занять момент.
    </p>
    <div class="table-shell">
      <div class="table-scroll">
        <table id="regTable" class="dtable">
          <thead><tr>
            <th data-key="season" data-type="text"><span data-i18n="th_season">Сезон</span></th>
            <th data-key="cat" data-type="text"><span data-i18n="th_cat">Категория</span></th>
            <th data-key="div" data-type="text"><span data-i18n="th_div">Дивизион</span></th>
            <th data-key="team" data-type="text"><span data-i18n="th_team">Команда</span></th>
            <th data-key="comp" data-type="text"><span data-i18n="th_comp">Соревнование</span></th>
            <th data-key="summary" data-type="number"><span data-i18n="th_summary">Сводка</span></th>
          </tr></thead>
          <tbody id="regBody"><tr><td class="empty-state" colspan="6" data-i18n="loading">Загрузка…</td></tr></tbody>
        </table>
      </div>
    </div>
  </section>

  <footer class="note" data-i18n="footer">Построено из <code>output/processed/rffm/player_competition_participation.csv</code>. См.
    <code>analysis_scripts/player_cards.py</code>.</footer>
</div>
<script>
const SHARD_MOD = %SHARD_MOD%;
const SEASONS = %SEASONS_JSON%;
const DIV_LABEL_RU = %DIV_LABEL_RU_JSON%;
const DIV_LABEL_ES = %DIV_LABEL_ES_JSON%;
const LANG = {
  ru: { loading: 'Загрузка…', notFound: 'Нет данных о заявках этого игрока.', other: 'Прочее', birthLabel: 'Год рождения',
        stSeasons: 'Сезонов', stClubs: 'Клубов', stTeams: 'Команд', stApps: 'Явок (всего)', stGoals: 'Голов (всего)',
        nowLabel: 'Сейчас:', backTeam: '&larr; Карточка команды', back: '&larr; Карта клубов' },
  es: { loading: 'Cargando…', notFound: 'No se encontraron datos de inscripción para este jugador.', other: 'Otra', birthLabel: 'Año de nacimiento',
        stSeasons: 'Temporadas', stClubs: 'Clubes', stTeams: 'Equipos', stApps: 'Partidos (total)', stGoals: 'Goles (total)',
        nowLabel: 'Ahora:', backTeam: '&larr; Ficha de equipo', back: '&larr; Mapa de clubes' },
};
const DT_LABELS = {
  ru: { selectAll: '(все)', search: 'Поиск…', apply: 'Применить', clear: 'Сбросить', empty: '(пусто)' },
  es: { selectAll: '(todos)', search: 'Buscar…', apply: 'Aplicar', clear: 'Restablecer', empty: '(vacío)' },
};
let CURLANG = 'ru';
let CUR_PID = null, CUR_SEASON = null;
const SHARD_CACHE = {};
const TEAM_DATA_CACHE = {};
let ROW_STATS = {};

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}
function divLabel(d) { return (CURLANG === 'ru' ? DIV_LABEL_RU : DIV_LABEL_ES)[d] || d || ''; }

%DATATABLE_JS%

async function fetchShard(season, pid) {
  const shard = parseInt(pid, 10) % SHARD_MOD;
  const key = `${season}/${shard}`;
  if (!(key in SHARD_CACHE)) {
    try {
      const res = await fetch(`data/player_participation_${season}/${shard}.json`);
      SHARD_CACHE[key] = res.ok ? await res.json() : null;
    } catch (e) {
      SHARD_CACHE[key] = null;
    }
  }
  return SHARD_CACHE[key];
}

function teamCardUrl(r) {
  if (!(r.club_slug && r.team_id)) return null;
  return `team_card.html?season=${encodeURIComponent(r._season)}&club=${encodeURIComponent(r.club_slug)}&team=${encodeURIComponent(r.team_id)}`;
}
function compCalUrl(r) {
  if (!(r.season_id && r.comp_id && r.group_id && r.gt_id)) return null;
  return `https://www.rffm.es/competicion/calendario?temporada=${r.season_id}&competicion=${r.comp_id}&grupo=${r.group_id}&jornada=1&tipojuego=${r.gt_id}`;
}

// Same shape/logic as team_cards.py's computeStats(), scoped to one
// (player, team) pair instead of a whole roster — duplicated rather than
// shared because these are separate static-HTML page templates with no
// module system between them (same convention as esc() already being
// defined identically in every *_cards.py page).
function computePlayerTeamStats(pid, matches, lineups) {
  const played = matches.filter(m => m.status === 'finished');
  let apps = 0, starts = 0, goals = 0, yellow = 0, red = 0, dy = 0, cap = 0, gkapps = 0;
  played.forEach(m => {
    const cell = (lineups[m.match_id] || {})[pid];
    if (!cell) return;
    apps++;
    if (cell.start) starts++;
    goals += cell.goals || 0;
    (cell.cards || []).forEach(c => {
      if (c === 'roja') red++; else if (c === 'doble amarilla' || c === 'doble_amarilla') dy++; else yellow++;
    });
    if (cell.cap) cap++;
    if (cell.gk) gkapps++;
  });
  return { apps, played: played.length, starts, goals, yellow, red, dy, cap, gkapps };
}

function summaryText(s) {
  if (!s || !s.played) return '—';
  const parts = [`${s.apps}/${s.played}`];
  if (s.goals) parts.push(`${s.goals}⚽`);
  const cardBits = [];
  if (s.yellow) cardBits.push(`${s.yellow}Ж`);
  if (s.red) cardBits.push(`${s.red}К`);
  if (s.dy) cardBits.push(`${s.dy}(2Ж)`);
  if (cardBits.length) parts.push(cardBits.join(' '));
  if (s.cap) parts.push(`©${s.cap}`);
  return parts.join(' · ');
}

// Roster (lineups) + match list for one team, fetched from the same JSON
// team_card.html/team_rosters.py already build — nothing new to crawl or
// pre-aggregate, just two more consumers of existing lazily-loaded data.
// Cached per (season, club, team) since a player can have more than one
// participation row for the same team (e.g. league + cup registrations).
async function fetchTeamRosterAndMatches(season, clubSlug, teamId) {
  const key = `${season}/${clubSlug}/${teamId}`;
  if (!(key in TEAM_DATA_CACHE)) {
    TEAM_DATA_CACHE[key] = (async () => {
      try {
        const [rosterRes, cardRes] = await Promise.all([
          fetch(`data/team_rosters_${season}/${teamId}.json`),
          fetch(`data/team_cards_${season}/${clubSlug}.json`),
        ]);
        const roster = rosterRes.ok ? await rosterRes.json() : { lineups: {} };
        const card = cardRes.ok ? await cardRes.json() : { teams: {} };
        const matches = (card.teams && card.teams[teamId] && card.teams[teamId].matches) || [];
        return { lineups: roster.lineups || {}, matches };
      } catch (e) {
        return { lineups: {}, matches: [] };
      }
    })();
  }
  return TEAM_DATA_CACHE[key];
}

function renderProfileStrip(rows) {
  const strip = document.getElementById('profileStrip');
  const seasons = new Set(rows.map(r => r._season));
  const clubs = new Set(rows.map(r => r.club).filter(Boolean));
  const teams = new Set(rows.map(r => r.team_id).filter(Boolean));
  const cell = (id, num, lbl) => `<div class="stat-cell"><div class="num" id="${id}">${num}</div><div class="lbl">${esc(lbl)}</div></div>`;
  strip.innerHTML =
    cell('stSeasonsNum', seasons.size, LANG[CURLANG].stSeasons) +
    cell('stClubsNum', clubs.size, LANG[CURLANG].stClubs) +
    cell('stTeamsNum', teams.size, LANG[CURLANG].stTeams) +
    cell('stAppsNum', '…', LANG[CURLANG].stApps) +
    cell('stGoalsNum', '…', LANG[CURLANG].stGoals);
}

// Totals are summed over TEAM_STATS_BY_KEY (one entry per distinct
// season+team), never over every row: a player can have several
// participation rows for the very same team (league registration + cup
// registration + playoff registration, ...) — team_card.html's own
// competitions panel is exactly why this is common — and each of those
// rows' "Сводка" cell legitimately repeats that team's identical stats, but
// summing all of them into "total appearances" would multiply the same
// real matches by however many registrations that one team happened to
// have, wildly overstating it.
let TEAM_STATS_BY_KEY = {};
function updateProfileTotals() {
  const vals = Object.values(TEAM_STATS_BY_KEY);
  const appsEl = document.getElementById('stAppsNum'), goalsEl = document.getElementById('stGoalsNum');
  if (appsEl) appsEl.textContent = vals.reduce((s, v) => s + (v.apps || 0), 0);
  if (goalsEl) goalsEl.textContent = vals.reduce((s, v) => s + (v.goals || 0), 0);
}

function renderNowBadge(rows) {
  const badge = document.getElementById('nowBadge');
  if (!rows.length) { badge.innerHTML = ''; return; }
  const latest = rows.reduce((a, b) => (b._season > a._season ? b : a));
  const url = teamCardUrl(latest);
  const teamHtml = url ? `<a href="${url}">${esc(latest.team || '—')}</a>` : esc(latest.team || '—');
  badge.innerHTML = `${esc(LANG[CURLANG].nowLabel)} ${teamHtml}`;
}

// Kicked off after the table's already rendered (so the page isn't blocked
// on N team-data fetches) — each row's placeholder cell fills in as its
// own fetch resolves, and the running profile totals + this table's active
// sort/filter (if the user already touched the "Сводка" column) refresh
// alongside it.
function loadRowSummaries(rows) {
  ROW_STATS = {};
  TEAM_STATS_BY_KEY = {};
  rows.forEach((r, i) => {
    if (!r.team_id || !r.club_slug) return;
    fetchTeamRosterAndMatches(r._season, r.club_slug, r.team_id).then(({ matches, lineups }) => {
      const s = computePlayerTeamStats(CUR_PID, matches, lineups);
      ROW_STATS[i] = s;
      TEAM_STATS_BY_KEY[`${r._season}_${r.team_id}`] = s;
      const cell = document.getElementById(`sum-${i}`);
      if (cell) {
        const text = summaryText(s);
        cell.textContent = text;
        cell.setAttribute('data-v', String(s.apps || 0));
        cell.setAttribute('data-label', text);
      }
      updateProfileTotals();
      const table = document.getElementById('regTable');
      if (table && table._rffmDt) table._rffmDt.refresh();
    });
  });
}

async function render() {
  const allSeasons = document.getElementById('allSeasonsBox').checked;
  const seasons = allSeasons ? SEASONS : [CUR_SEASON];
  let rows = [];
  let found = null;
  for (const season of seasons) {
    const shard = await fetchShard(season, CUR_PID);
    const player = shard && shard[CUR_PID];
    if (!player) continue;
    if (!found) found = player;
    player.rows.forEach(r => rows.push(Object.assign({ _season: season }, r)));
  }
  if (!found) {
    document.getElementById('playerName').textContent = '—';
    document.getElementById('profileStrip').innerHTML = '';
    document.getElementById('nowBadge').innerHTML = '';
    document.getElementById('regBody').innerHTML =
      `<tr><td class="empty-state" colspan="6">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  document.getElementById('playerName').textContent = found.name;
  document.title = `${found.name} — RFFM`;
  document.getElementById('playerSub').textContent =
    found.birth_year ? `${LANG[CURLANG].birthLabel}: ${found.birth_year}` : '';
  if (!rows.length) {
    document.getElementById('profileStrip').innerHTML = '';
    document.getElementById('nowBadge').innerHTML = '';
    document.getElementById('regBody').innerHTML =
      `<tr><td class="empty-state" colspan="6">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  // Default order follows the columns themselves (season -> category ->
  // division -> team), not "newest first" — the ▾ menus handle any other
  // order a viewer wants, and this is what "unsorted" (3rd click state)
  // restores back to.
  rows.sort((a, b) =>
    (a._season || '').localeCompare(b._season || '') ||
    (a.cat || '').localeCompare(b.cat || '') ||
    (a.div || '').localeCompare(b.div || '') ||
    (a.team || '').localeCompare(b.team || ''));

  renderProfileStrip(rows);
  renderNowBadge(rows);

  document.getElementById('regBody').innerHTML = rows.map((r, i) => {
    const teamUrl = teamCardUrl(r);
    const teamHtml = teamUrl ? `<a href="${teamUrl}">${esc(r.team || '—')}</a>` : esc(r.team || '—');
    const compUrl = compCalUrl(r);
    const compHtml = compUrl
      ? `<a href="${compUrl}" target="_blank" rel="noopener">${esc(r.comp || '—')}</a>`
      : esc(r.comp || '—');
    const meta = [r.grp, r.gt].filter(Boolean).map(esc).join(' &middot; ');
    const divText = r.div && r.div !== 'OTHER' ? divLabel(r.div) : '—';
    const catText = r.cat && r.cat !== 'OTHER' ? r.cat : LANG[CURLANG].other;
    return `<tr>
      <td class="season-cell" data-col="season" data-v="${esc(r._season)}">${esc(r._season)}</td>
      <td data-col="cat" data-v="${esc(catText)}">${esc(catText)}</td>
      <td data-col="div" data-v="${esc(divText)}"><span class="tier-chip">${esc(divText)}</span></td>
      <td class="team-name" data-col="team" data-v="${esc(r.team || '')}">${teamHtml}</td>
      <td data-col="comp" data-v="${esc(r.comp || '')}">${compHtml}${meta ? `<span class="comp-meta">${meta}</span>` : ''}</td>
      <td class="summary-cell" data-col="summary" data-v="0" data-label="…" id="sum-${i}">…</td>
    </tr>`;
  }).join('');

  rffmInitDataTable(document.getElementById('regTable'), { labels: DT_LABELS[CURLANG] });
  loadRowSummaries(rows);
}

// The label ("← Карточка команды" vs "← Карта клубов") has to match where
// the link actually goes — it used to always say "карточка команды" while
// always pointing at club_division_map.html. Real destination now depends
// on how this page was reached: team_card.html's player links pass
// fromTeam/fromClub (see team_cards.py), so Back returns to the exact team
// card that was open; without that context (direct link, future all-
// players list, ...) it falls back to the club map with a truthful label.
function setupBackLink() {
  const params = new URLSearchParams(location.search);
  const link = document.getElementById('backLink');
  const fromTeam = params.get('fromTeam'), fromClub = params.get('fromClub');
  const season = params.get('season') || SEASONS[SEASONS.length - 1];
  if (fromTeam && fromClub) {
    link.href = `team_card.html?season=${encodeURIComponent(season)}&club=${encodeURIComponent(fromClub)}&team=${encodeURIComponent(fromTeam)}`;
    link.innerHTML = LANG[CURLANG].backTeam;
  } else {
    link.href = 'club_division_map.html';
    link.innerHTML = LANG[CURLANG].back;
  }
}

async function main() {
  const params = new URLSearchParams(location.search);
  CUR_PID = params.get('player');
  CUR_SEASON = params.get('season') || SEASONS[SEASONS.length - 1];
  document.getElementById('allSeasonsBox').checked = params.get('all') === '1';
  setupBackLink();
  if (!CUR_PID) {
    document.getElementById('regBody').innerHTML =
      `<tr><td class="empty-state" colspan="6">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  await render();
}

document.getElementById('allSeasonsBox').addEventListener('change', function () {
  const params = new URLSearchParams(location.search);
  if (this.checked) params.set('all', '1'); else params.delete('all');
  history.replaceState(null, '', location.pathname + '?' + params.toString());
  render();
});

(function () {
  var I18N_ES = %I18N_ES_JSON%;
  %LANG_SWITCH_JS%
})();

document.querySelectorAll('.lang-opt').forEach(function (btn) {
  btn.addEventListener('click', function () { CURLANG = btn.getAttribute('data-lang-btn'); setupBackLink(); render(); });
});
try { if (localStorage.getItem('rffm_lang') === 'es') CURLANG = 'es'; } catch (e) {}

%THEME_SWITCH_JS%

main();
</script>
</body>
</html>
"""


def build_html(seasons: list[str]) -> str:
    return (HTML
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%THEME_INIT%", THEME_INIT_JS)
            .replace("%SWITCH_ROW%", switch_row_html())
            .replace("%SHARD_MOD%", str(SHARD_MOD))
            .replace("%SEASONS_JSON%", json.dumps(seasons))
            .replace("%I18N_ES_JSON%", json.dumps(I18N_ES, ensure_ascii=False))
            .replace("%LANG_SWITCH_JS%", LANG_SWITCH_JS)
            .replace("%THEME_SWITCH_JS%", THEME_SWITCH_JS)
            .replace("%DATATABLE_CSS%", DATATABLE_CSS)
            .replace("%DATATABLE_JS%", DATATABLE_JS)
            .replace("%DIV_LABEL_RU_JSON%", json.dumps(DIV_LABEL_RU, ensure_ascii=False))
            .replace("%DIV_LABEL_ES_JSON%", json.dumps(DIV_LABEL_ES, ensure_ascii=False)))


def main():
    parser = argparse.ArgumentParser(description="RFFM player-card data + page")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    build_all(Path(__file__).parent.parent / args.output_dir)


if __name__ == "__main__":
    main()
