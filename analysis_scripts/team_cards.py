#!/usr/bin/env python3
"""
Team card: every match a single team played this season, across every
competition/division it appeared in, with the date, opponent, score and
where the game sits in the pyramid — the page club_division_map.html's team
names/links now open (instead of sending the click out to rffm.es's own
fichaequipo page), and the base this project's future roster×matches
participation matrix (see the docstring note at the bottom of this file)
will build on.

Data volume forced two scoping decisions:
  - one JSON per (season, club) under <output-dir>/data/team_cards_<season>/
    <slug>.json — not one file per team_id (9000+ teams in 2025-2026 alone)
    and not one season-wide bundle (matches.csv alone runs 28-53 MB/season).
    Splitting by club keeps each fetch down to one club's own teams, loaded
    lazily only when a team card is opened. club_division_map.py computes
    the exact same slug for the same club name via site_theme.club_slug_map(),
    so a link built there always resolves to the file built here.
  - build_all() defaults to the latest season only, not every crawled season
    like club_division_map.py — 8 seasons of team-card JSON would run
    450+ MB. A team-card link for an older season degrades to "no data"
    instead of the build shipping a half-gigabyte artifact; pass --season
    explicitly to build another one.

Usage:
    python analysis_scripts/team_cards.py
    python analysis_scripts/team_cards.py --season 2025-2026 --output-dir reports
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from site_theme import (DATATABLE_CSS, DATATABLE_JS, FONT_LINKS, LANG_SWITCH_JS, THEME_INIT_JS,
                         THEME_SWITCH_JS, club_slug_map, switch_row_html)

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"


def list_seasons() -> list[str]:
    m = pd.read_csv(MANIFEST, dtype=str)
    core = m[(m["stage"] == "core") & (m["category_base"] == "ALL") &
             (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(core["season"].unique().tolist())


def norm_id(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def clean(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def build_club_team_cards(season: str) -> dict[str, dict]:
    """club_name_raw -> {team_id: {name, matches: [...]}}, one entry per
    team the club fielded, sorted chronologically within each team."""
    d = BASE / season
    teams = pd.read_csv(d / "teams.csv", dtype=str)
    matches = pd.read_csv(d / "matches.csv", dtype=str)

    tid_to_club = dict(zip(teams["team_id"].map(norm_id), teams["club_name_raw"]))
    tid_to_name = dict(zip(teams["team_id"].map(norm_id), teams["team"]))

    matches["hid"] = matches["home_team_id"].map(norm_id)
    matches["aid"] = matches["away_team_id"].map(norm_id)

    club_teams: dict[str, dict[str, dict]] = {}
    sides = (("hid", "aid", "home_team", "away_team", "home_score", "away_score", True),
             ("aid", "hid", "away_team", "home_team", "away_score", "home_score", False))
    for _, r in matches.iterrows():
        for tid_col, opp_col, _own_name_col, opp_name_col, sf_col, sa_col, is_home in sides:
            tid = r[tid_col]
            if not tid:
                continue
            club = tid_to_club.get(tid)
            if not club:
                continue
            opp_tid = r[opp_col]
            opp_name = clean(tid_to_name.get(opp_tid)) or clean(r[opp_name_col])
            sf, sa = clean(r[sf_col]), clean(r[sa_col])
            result = None
            if r["is_finished"] == "True" and sf is not None and sa is not None:
                try:
                    fsf, fsa = float(sf), float(sa)
                    result = "W" if fsf > fsa else ("L" if fsf < fsa else "D")
                except ValueError:
                    pass
            entry = {
                "match_id": clean(r["match_id"]),
                "date": clean(r["match_date"]), "time": clean(r["match_time"]),
                "home": is_home, "opp": opp_name, "opp_tid": clean(opp_tid),
                "sf": sf, "sa": sa, "result": result, "status": clean(r["status"]),
                "comp": clean(r["competition"]), "comp_id": clean(r["competition_id"]),
                "grp": clean(r["group"]), "group_id": clean(r["group_id"]),
                "gt": clean(r["game_type"]), "gt_id": clean(r["game_type_id"]),
                "phase": clean(r["phase_label"]), "matchday": clean(r["matchday_label"]),
                "season_id": clean(r["season_id"]),
            }
            team_rec = club_teams.setdefault(club, {}).setdefault(tid, {
                "name": clean(tid_to_name.get(tid)) or tid, "matches": [],
            })
            team_rec["matches"].append(entry)

    for teams_of_club in club_teams.values():
        for team_rec in teams_of_club.values():
            team_rec["matches"].sort(key=lambda x: (x["date"] or "9999-99-99", x["time"] or ""))

    return club_teams


I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; ficha de equipo",
    "back": "&larr; Mapa de clubes",
    "loading": "Cargando…",
    "not_found": "No se encontraron datos para este equipo en esta temporada.",
    "h_matches": "Partidos de la temporada",
    "n_matches": "partidos",
    "th_date": "Fecha", "th_comp": "Competición", "th_opp": "Rival", "th_score": "Resultado", "th_ha": "L/V",
    "home": "Local", "away": "Visitante",
    "scheduled": "por jugar",
    "tab_matches": "Partidos", "tab_roster": "Plantilla",
    "h_roster": "Plantilla por partido",
    "roster_p": "Filas — jugadores, columnas — partidos de la temporada. Círculo relleno — titular, círculo hueco — "
                "suplente que entró, borde dorado — capitán, número al lado — goles marcados, barra — tarjeta.",
    "h_summary": "Resumen por jugador",
    "summary_p": "Calculado a partir de las convocatorias (sin datos de minutos jugados ni asistencias, que la "
                 "fuente no registra). “Partidos” cuenta partidos ya finalizados. Haz clic en ▾ de "
                 "cualquier columna para ordenar o filtrar, como en Excel.",
    "sh_jersey": "Nº", "sh_name": "Jugador", "sh_apps": "Partidos", "sh_starts": "Titular", "sh_sub": "Suplente",
    "sh_goals": "Goles", "sh_gpa": "Goles/partido", "sh_y": "A", "sh_r": "R", "sh_dy": "2A",
    "sh_cap": "Capitán", "sh_gk": "Portero", "sh_cs": "Imbatido", "sh_ppg": "Puntos/partido",
    "footer": 'Construido a partir de <code>output/processed/rffm/matches.csv</code> y '
              '<code>match_lineups/match_goals/match_cards</code>. Ver <code>analysis_scripts/team_cards.py</code>, '
              '<code>analysis_scripts/team_rosters.py</code>.',
}

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — карточка команды</title>
%FONT_LINKS%
%THEME_INIT%
<style>
:root{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --win:#2f6b3c; --win-soft:#dce8dd; --loss:#a03327; --loss-soft:#f5ddd6; --draw:#8a6a12; --draw-soft:#f3e7c4;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
    --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
    --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
    --win:#74c47f; --win-soft:#20301f; --loss:#e2685a; --loss-soft:#33201d; --draw:#d9b64a; --draw-soft:#332a10;
  }
}
:root[data-theme="dark"]{
  --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
  --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
  --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
  --win:#74c47f; --win-soft:#20301f; --loss:#e2685a; --loss-soft:#33201d; --draw:#d9b64a; --draw-soft:#332a10;
}
:root[data-theme="light"]{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --win:#2f6b3c; --win-soft:#dce8dd; --loss:#a03327; --loss-soft:#f5ddd6; --draw:#8a6a12; --draw-soft:#f3e7c4;
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

.section-h{ display:flex; align-items:baseline; gap:0.6rem; }
.section-h h2{ font-family:'Oswald',sans-serif; font-weight:700; text-transform:uppercase; font-size:1.1rem; color:var(--ink); margin:0; }
.section-h .n{ font-family:'JetBrains Mono',monospace; color:var(--accent); font-size:0.78rem; font-weight:700; }

.table-shell{ background:var(--surface); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); overflow:hidden; }
table{border-collapse:separate; border-spacing:0; font-size:0.85rem; width:100%;}
thead th{ background:var(--surface); border-bottom:1px solid var(--line-strong); padding:0.55rem 0.7rem;
  text-align:left; font-size:0.7rem; letter-spacing:0.05em; text-transform:uppercase; color:var(--ink-soft); }
tbody td{ border-bottom:1px solid var(--line); padding:0.5rem 0.7rem; vertical-align:middle; }
tbody tr:last-child td{border-bottom:none;}
tbody tr:hover td{background:var(--accent-soft);}
td.date-cell{font-family:'JetBrains Mono',monospace; font-size:0.78rem; color:var(--ink-soft); white-space:nowrap;}
td.comp-cell{max-width:22rem;}
.comp-name{color:var(--ink); font-weight:600;}
.comp-meta{display:block; font-size:0.72rem; color:var(--ink-faint); margin-top:0.1rem;}
.ha-badge{font-family:'JetBrains Mono',monospace; font-size:0.68rem; font-weight:700; padding:0.08rem 0.4rem;
  border-radius:4px; background:var(--surface); border:1px solid var(--line-strong); color:var(--ink-soft); white-space:nowrap;}
.score-cell{font-variant-numeric:tabular-nums; font-weight:700; white-space:nowrap;}
.score-badge{display:inline-block; padding:0.1rem 0.5rem; border-radius:4px;}
.score-badge.res-W{background:var(--win-soft); color:var(--win);}
.score-badge.res-L{background:var(--loss-soft); color:var(--loss);}
.score-badge.res-D{background:var(--draw-soft); color:var(--draw);}
.score-pending{color:var(--ink-faint); font-weight:400; font-style:italic; font-size:0.8rem;}
.empty-state{padding:2rem; text-align:center; color:var(--ink-faint);}
footer.note{font-size:0.78rem; color:var(--ink-soft); max-width:90ch;}

.tabs{display:flex; gap:0.4rem;}
.tab-btn{ font-family:inherit; font-size:0.82rem; font-weight:700; color:var(--ink-soft); background:var(--surface);
  border:1.5px solid var(--line-strong); border-radius:999px; padding:0.35rem 0.9rem; cursor:pointer; }
.tab-btn:hover{color:var(--ink); border-color:var(--accent);}
.tab-btn.active{background:var(--accent); border-color:var(--accent); color:#fff;}
.tab-pane{display:none;}
.tab-pane.active{display:block;}

.matrix-scroll{overflow:auto; max-height:75vh;}
table.matrix{font-size:0.76rem;}
table.matrix th, table.matrix td{padding:0.3rem 0.4rem; white-space:nowrap;}
th.player-head{ position:sticky; left:0; z-index:3; background:var(--surface); text-align:left;
  border-right:1px solid var(--line-strong); min-width:11rem; }
td.player-cell{ position:sticky; left:0; z-index:1; background:var(--surface);
  border-right:1px solid var(--line-strong); text-align:left; }
tbody tr:hover td.player-cell{background:var(--accent-soft);}
.player-name{color:var(--ink); font-weight:600;}
.jersey-badge{ display:inline-block; min-width:1.3rem; text-align:center; font-family:'JetBrains Mono',monospace;
  font-size:0.68rem; font-weight:700; padding:0.02rem 0.25rem; border-radius:3px; margin-right:0.35rem;
  background:var(--accent-soft); color:var(--accent); }
.gk-badge{font-size:0.62rem; color:var(--ink-faint); margin-left:0.3rem;}
th.match-head{ text-align:center; font-weight:700; cursor:default; }
th.match-head .mh-date{display:block; color:var(--ink);}
th.match-head .mh-opp{display:block; font-size:0.62rem; color:var(--ink-faint); font-weight:400; max-width:5.5rem;
  overflow:hidden; text-overflow:ellipsis; margin:0 auto;}
td.cell-mark{text-align:center;}
.mark-start, .mark-sub{ display:inline-block; width:0.7rem; height:0.7rem; border-radius:50%; }
.mark-start{background:var(--accent);}
.mark-sub{background:transparent; border:1.5px solid var(--accent);}
.mark-cap{box-shadow:0 0 0 2px var(--gold);}
.mark-goals{ display:inline-block; margin-left:0.2rem; font-family:'JetBrains Mono',monospace; font-size:0.68rem;
  font-weight:700; color:var(--win); vertical-align:middle; }
.mark-card{display:inline-block; width:0.45rem; height:0.62rem; border-radius:1px; margin-left:0.15rem; vertical-align:middle;}
.mark-card.amarilla{background:var(--draw);}
.mark-card.roja{background:var(--loss);}
.mark-card.doble-amarilla{background:linear-gradient(180deg, var(--draw) 50%, var(--loss) 50%);}
.matrix-loading, .matrix-empty{padding:1.5rem; text-align:center; color:var(--ink-faint);}
.summary-scroll{overflow:auto;}
table.dtable{font-size:0.82rem;}
table.dtable td{white-space:nowrap;}
%DATATABLE_CSS%
</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    %SWITCH_ROW%
    <a class="back" href="club_division_map.html" data-i18n="back">&larr; Карта клубов</a>
    <span class="eyebrow" data-i18n="eyebrow">RFFM (Мадрид) &middot; карточка команды</span>
    <h1 id="teamName">…</h1>
    <p class="club-sub" id="clubName"></p>
  </header>

  <div class="tabs">
    <button type="button" class="tab-btn active" id="tabBtnMatches" data-i18n="tab_matches">Матчи</button>
    <button type="button" class="tab-btn" id="tabBtnRoster" data-i18n="tab_roster">Состав</button>
  </div>

  <section class="tab-pane active" id="paneMatches">
    <div class="section-h"><h2 data-i18n="h_matches">Матчи сезона</h2><span class="n dt-count" id="matchCount"></span></div>
    <div class="table-shell">
      <table id="matchTable" class="dtable">
        <thead><tr>
          <th data-key="date" data-type="text"><span data-i18n="th_date">Дата</span></th>
          <th data-key="ha" data-type="text"><span data-i18n="th_ha">Д/В</span></th>
          <th data-key="opp" data-type="text"><span data-i18n="th_opp">Соперник</span></th>
          <th data-key="score" data-type="number"><span data-i18n="th_score">Результат</span></th>
          <th data-key="comp" data-type="text"><span data-i18n="th_comp">Соревнование</span></th>
        </tr></thead>
        <tbody id="matchBody"><tr><td class="empty-state" colspan="5" data-i18n="loading">Загрузка…</td></tr></tbody>
      </table>
    </div>
  </section>

  <section class="tab-pane" id="paneRoster">
    <div class="section-h"><h2 data-i18n="h_summary">Итоги по игрокам</h2><span class="n dt-count" id="summaryCount"></span></div>
    <p style="color:var(--ink-soft); font-size:0.82rem; max-width:70ch; margin:0 0 0.8rem;" data-i18n="summary_p">
      Считается по количеству выходов на поле (без игрового времени и передач — в источнике их нет).
      «Явка» учитывает только уже сыгранные матчи. Клик по ▾ в заголовке любой колонки — сортировка и
      фильтр по значениям, как в Excel.
    </p>
    <div class="table-shell">
      <div class="summary-scroll">
        <table id="summaryTable" class="dtable">
          <thead><tr>
            <th data-key="jersey" data-type="number"><span data-i18n="sh_jersey">№</span></th>
            <th data-key="name" data-type="text"><span data-i18n="sh_name">Игрок</span></th>
            <th data-key="apps" data-type="number"><span data-i18n="sh_apps">Явка</span></th>
            <th data-key="starts" data-type="number"><span data-i18n="sh_starts">Старт</span></th>
            <th data-key="subapps" data-type="number"><span data-i18n="sh_sub">Скамейка</span></th>
            <th data-key="goals" data-type="number"><span data-i18n="sh_goals">Голы</span></th>
            <th data-key="goalsperapp" data-type="number"><span data-i18n="sh_gpa">Гол/явка</span></th>
            <th data-key="yellow" data-type="number" title="Жёлтые карточки"><span data-i18n="sh_y">Ж</span></th>
            <th data-key="red" data-type="number" title="Красные карточки"><span data-i18n="sh_r">К</span></th>
            <th data-key="dy" data-type="number" title="Вторые жёлтые"><span data-i18n="sh_dy">2Ж</span></th>
            <th data-key="cap" data-type="number"><span data-i18n="sh_cap">Капитан</span></th>
            <th data-key="gkapps" data-type="number"><span data-i18n="sh_gk">На воротах</span></th>
            <th data-key="cs" data-type="number"><span data-i18n="sh_cs">Сухие</span></th>
            <th data-key="ppg" data-type="number"><span data-i18n="sh_ppg">Очки/игру</span></th>
          </tr></thead>
          <tbody id="summaryBody"></tbody>
        </table>
      </div>
    </div>

    <div class="section-h" style="margin-top:1.6rem;"><h2 data-i18n="h_roster">Состав по матчам</h2><span class="n" id="rosterCount"></span></div>
    <p style="color:var(--ink-soft); font-size:0.82rem; max-width:70ch; margin:0 0 0.8rem;" data-i18n="roster_p">
      Строки — игроки, столбцы — матчи сезона. Закрашенный кружок — в старте, пустой — вышел на замену,
      золотая обводка — капитан, число рядом — забитые голы, полоска — карточка.
    </p>
    <div class="table-shell">
      <div class="matrix-scroll" id="matrixScroll">
        <div class="matrix-loading" id="matrixStatus" data-i18n="loading">Загрузка…</div>
      </div>
    </div>
  </section>

  <footer class="note" data-i18n="footer">Построено из <code>output/processed/rffm/matches.csv</code> и
    <code>match_lineups/match_goals/match_cards</code>. См. <code>analysis_scripts/team_cards.py</code>,
    <code>analysis_scripts/team_rosters.py</code>.</footer>
</div>
<script>
const LANG = {
  ru: { loading: 'Загрузка…', notFound: 'Нет данных об этой команде в этом сезоне.',
        home: 'Дома', away: 'В гостях', scheduled: 'ещё не сыгран',
        win: 'Победа', draw: 'Ничья', loss: 'Поражение' },
  es: { loading: 'Cargando…', notFound: 'No se encontraron datos para este equipo en esta temporada.',
        home: 'Local', away: 'Visitante', scheduled: 'por jugar',
        win: 'Victoria', draw: 'Empate', loss: 'Derrota' },
};
const DT_LABELS = {
  ru: { asc: '▲ по возрастанию', desc: '▼ по убыванию', selectAll: '(все)', search: 'Поиск…', apply: 'Применить', clear: 'Сбросить', empty: '(пусто)' },
  es: { asc: '▲ ascendente', desc: '▼ descendente', selectAll: '(todos)', search: 'Buscar…', apply: 'Aplicar', clear: 'Restablecer', empty: '(vacío)' },
};
let CURLANG = 'ru';

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

%DATATABLE_JS%

function groupCalUrl(m) {
  if (!(m.season_id && m.comp_id && m.group_id && m.gt_id)) return null;
  return `https://www.rffm.es/competicion/calendario?temporada=${m.season_id}&competicion=${m.comp_id}&grupo=${m.group_id}&jornada=1&tipojuego=${m.gt_id}`;
}

function fmtGoals(v) {
  const n = Number(v);
  return Number.isFinite(n) ? String(Math.round(n)) : v;
}
function scoreCellHtml(m) {
  if (m.status !== 'finished' || m.sf === null || m.sa === null || m.sf === undefined || m.sa === undefined) {
    return `<span class="score-pending">${LANG[CURLANG].scheduled}</span>`;
  }
  const cls = m.result ? `res-${m.result}` : '';
  return `<span class="score-badge ${cls}">${fmtGoals(m.sf)} : ${fmtGoals(m.sa)}</span>`;
}

// Numeric rank so the "Результат" column can be sorted/filtered by outcome
// (Win/Draw/Loss/pending) rather than by literal, mostly-unique score text.
function resultRank(m) {
  if (m.status !== 'finished' || !m.result) return -1;
  return m.result === 'W' ? 3 : m.result === 'D' ? 1 : 0;
}
function resultLabel(m) {
  if (m.status !== 'finished' || !m.result) return LANG[CURLANG].scheduled;
  return { W: LANG[CURLANG].win, D: LANG[CURLANG].draw, L: LANG[CURLANG].loss }[m.result];
}

function renderMatches(team) {
  if (!team.matches.length) {
    document.getElementById('matchCount').textContent = '0';
    document.getElementById('matchBody').innerHTML =
      `<tr><td class="empty-state" colspan="5">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  document.getElementById('matchBody').innerHTML = team.matches.map(m => {
    const url = groupCalUrl(m);
    const compHtml = url
      ? `<a href="${url}" target="_blank" rel="noopener" class="comp-name">${esc(m.comp || m.grp || '')}</a>`
      : `<span class="comp-name">${esc(m.comp || m.grp || '')}</span>`;
    const meta = [m.grp, m.gt].filter(Boolean).map(esc).join(' &middot; ');
    const compText = m.comp || m.grp || '';
    return `<tr>
      <td class="date-cell" data-col="date" data-v="${esc(m.date || '')}">${esc(m.date || '—')}</td>
      <td data-col="ha" data-v="${m.home ? 'H' : 'A'}"><span class="ha-badge">${m.home ? LANG[CURLANG].home : LANG[CURLANG].away}</span></td>
      <td data-col="opp" data-v="${esc(m.opp || '')}">${esc(m.opp || '—')}</td>
      <td class="score-cell" data-col="score" data-v="${resultRank(m)}" data-label="${esc(resultLabel(m))}">${scoreCellHtml(m)}</td>
      <td class="comp-cell" data-col="comp" data-v="${esc(compText)}">${compHtml}${meta ? `<span class="comp-meta">${meta}</span>` : ''}</td>
    </tr>`;
  }).join('');
  rffmInitDataTable(document.getElementById('matchTable'), {
    labels: DT_LABELS[CURLANG],
    onChange: (visible, total) => {
      document.getElementById('matchCount').textContent = visible === total ? String(total) : `${visible}/${total}`;
    },
  });
}

let CUR_SEASON = null, CUR_TEAM_ID = null, CUR_TEAM = null, ROSTER_PAYLOAD = null, ROSTER_LOADING = false;

function shortDate(d) {
  if (!d) return '—';
  const parts = d.split('-');
  return parts.length === 3 ? `${parts[2]}.${parts[1]}` : d;
}

function cardClass(label) {
  if (label === 'roja') return 'roja';
  if (label === 'doble amarilla' || label === 'doble_amarilla') return 'doble-amarilla';
  return 'amarilla';
}

// Per-player aggregates for the summary table, derived entirely from the
// already-loaded match list + roster/lineups matrix (no extra fetch). Only
// counts matches with status === 'finished' as "played" — a scheduled
// fixture can't contribute to anyone's appearance tally. Appearance and
// starter/sub numbers come straight from is_starter/is_substitute in the
// source acta (mutually exclusive & always set — verified against the
// 2025-2026 crawl), but there is no minutes-played or assist data anywhere
// in the pipeline, so "goals/явка" is deliberately per-appearance, not
// per-90 — see DATA_DICTIONARY.md's "Known gaps" section.
function computeStats(pid, matches, lineups) {
  const played = matches.filter(m => m.status === 'finished');
  let starts = 0, goals = 0, yellow = 0, red = 0, dy = 0, cap = 0, gkapps = 0, cs = 0, points = 0, resultsN = 0, apps = 0;
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
    if (cell.gk) {
      gkapps++;
      const sa = m.sa !== null && m.sa !== undefined ? Number(m.sa) : null;
      if (sa !== null && !isNaN(sa) && sa === 0) cs++;
    }
    if (m.result) { points += m.result === 'W' ? 3 : (m.result === 'D' ? 1 : 0); resultsN++; }
  });
  return {
    apps, played: played.length, starts, subapps: apps - starts,
    appsPct: played.length ? apps / played.length : null,
    goals, goalsPerApp: apps ? goals / apps : null,
    yellow, red, dy, cap, gkapps, cs,
    ppg: resultsN ? points / resultsN : null,
  };
}

function renderPlayerSummary() {
  const tbody = document.getElementById('summaryBody');
  const roster = Object.entries((ROSTER_PAYLOAD && ROSTER_PAYLOAD.roster) || {});
  const lineups = (ROSTER_PAYLOAD && ROSTER_PAYLOAD.lineups) || {};
  const matches = (CUR_TEAM && CUR_TEAM.matches) || [];
  if (!roster.length) {
    tbody.innerHTML = '';
    document.getElementById('summaryCount').textContent = '';
    return;
  }
  const fmt2 = v => v === null ? '—' : v.toFixed(2);
  tbody.innerHTML = roster.map(([pid, p]) => {
    const s = computeStats(pid, matches, lineups);
    const nameUrl = `player_card.html?season=${encodeURIComponent(CUR_SEASON)}&player=${encodeURIComponent(pid)}`;
    const appsDisplay = s.played
      ? `${s.apps}/${s.played} (${Math.round((s.appsPct || 0) * 100)}%)`
      : `${s.apps}/0`;
    return `<tr>
      <td data-col="jersey" data-v="${p.jersey ? parseInt(p.jersey, 10) : ''}">${p.jersey ? esc(p.jersey) : '—'}</td>
      <td data-col="name" data-v="${esc(p.name)}"><a href="${nameUrl}">${esc(p.name)}</a></td>
      <td data-col="apps" data-v="${s.apps}" data-label="${esc(appsDisplay)}">${appsDisplay}</td>
      <td data-col="starts" data-v="${s.starts}">${s.starts}</td>
      <td data-col="subapps" data-v="${s.subapps}">${s.subapps}</td>
      <td data-col="goals" data-v="${s.goals}">${s.goals}</td>
      <td data-col="goalsperapp" data-v="${s.goalsPerApp === null ? '' : s.goalsPerApp}">${fmt2(s.goalsPerApp)}</td>
      <td data-col="yellow" data-v="${s.yellow}">${s.yellow || '—'}</td>
      <td data-col="red" data-v="${s.red}">${s.red || '—'}</td>
      <td data-col="dy" data-v="${s.dy}">${s.dy || '—'}</td>
      <td data-col="cap" data-v="${s.cap}">${s.cap || '—'}</td>
      <td data-col="gkapps" data-v="${s.gkapps}">${s.gkapps || '—'}</td>
      <td data-col="cs" data-v="${s.gkapps ? s.cs : ''}">${s.gkapps ? s.cs : '—'}</td>
      <td data-col="ppg" data-v="${s.ppg === null ? '' : s.ppg}">${fmt2(s.ppg)}</td>
    </tr>`;
  }).join('');
  rffmInitDataTable(document.getElementById('summaryTable'), {
    labels: DT_LABELS[CURLANG],
    onChange: (visible, total) => {
      document.getElementById('summaryCount').textContent = visible === total ? String(total) : `${visible}/${total}`;
    },
  });
}

function renderMatrix() {
  const status = document.getElementById('matrixStatus');
  const scroll = document.getElementById('matrixScroll');
  if (!CUR_TEAM || !CUR_TEAM.matches.length) {
    scroll.innerHTML = `<div class="matrix-empty">${LANG[CURLANG].notFound}</div>`;
    return;
  }
  const roster = Object.entries((ROSTER_PAYLOAD && ROSTER_PAYLOAD.roster) || {});
  if (!roster.length) {
    scroll.innerHTML = `<div class="matrix-empty">${LANG[CURLANG].notFound}</div>`;
    return;
  }
  document.getElementById('rosterCount').textContent = roster.length;
  roster.sort((a, b) => {
    const ja = parseInt(a[1].jersey, 10), jb = parseInt(b[1].jersey, 10);
    if (!isNaN(ja) && !isNaN(jb)) return ja - jb;
    if (!isNaN(ja)) return -1;
    if (!isNaN(jb)) return 1;
    return String(a[1].name).localeCompare(String(b[1].name));
  });
  const lineups = ROSTER_PAYLOAD.lineups || {};
  const matches = CUR_TEAM.matches;

  let head = `<th class="player-head">&nbsp;</th>` + matches.map(m => {
    const opp = m.opp || '';
    return `<th class="match-head" title="${esc(opp)} &middot; ${esc(m.comp || '')}">` +
      `<span class="mh-date">${shortDate(m.date)}</span><span class="mh-opp">${esc(opp)}</span></th>`;
  }).join('');

  let rows = roster.map(([pid, p]) => {
    const jersey = p.jersey ? `<span class="jersey-badge">${esc(p.jersey)}</span>` : '';
    const gk = p.gk ? `<span class="gk-badge">GK</span>` : '';
    let cells = matches.map(m => {
      const cell = (lineups[m.match_id] || {})[pid];
      if (!cell) return `<td class="cell-mark">&nbsp;</td>`;
      const markCls = cell.start ? 'mark-start' : 'mark-sub';
      const capCls = cell.cap ? ' mark-cap' : '';
      const goals = cell.goals ? `<span class="mark-goals">&#9917;${cell.goals}</span>` : '';
      const cards = (cell.cards || []).map(c => `<span class="mark-card ${cardClass(c)}"></span>`).join('');
      return `<td class="cell-mark"><span class="${markCls}${capCls}"></span>${goals}${cards}</td>`;
    }).join('');
    const nameUrl = `player_card.html?season=${encodeURIComponent(CUR_SEASON)}&player=${encodeURIComponent(pid)}`;
    return `<tr><td class="player-cell"><span class="player-name">${jersey}<a href="${nameUrl}">${esc(p.name)}</a></span>${gk}</td>${cells}</tr>`;
  }).join('');

  scroll.innerHTML = `<table class="matrix"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
}

async function loadRoster() {
  if (ROSTER_PAYLOAD || ROSTER_LOADING) { renderMatrix(); renderPlayerSummary(); return; }
  ROSTER_LOADING = true;
  const status = document.getElementById('matrixStatus');
  status.textContent = LANG[CURLANG].loading;
  status.style.display = '';
  try {
    const res = await fetch(`data/team_rosters_${CUR_SEASON}/${CUR_TEAM_ID}.json`);
    if (!res.ok) throw new Error('not found');
    ROSTER_PAYLOAD = await res.json();
  } catch (e) {
    ROSTER_PAYLOAD = { roster: {}, lineups: {} };
  }
  ROSTER_LOADING = false;
  renderMatrix();
  renderPlayerSummary();
}

// Which tab is open lives in the URL (?tab=roster) via replaceState — not
// pushState, a tab flip isn't a "navigation" worth its own Back entry — so
// a shared/reloaded link lands on the same tab the sharer was looking at.
function showTab(name, opts) {
  opts = opts || {};
  const isRoster = name === 'roster';
  document.getElementById('tabBtnRoster').classList.toggle('active', isRoster);
  document.getElementById('tabBtnMatches').classList.toggle('active', !isRoster);
  document.getElementById('paneRoster').classList.toggle('active', isRoster);
  document.getElementById('paneMatches').classList.toggle('active', !isRoster);
  if (isRoster) loadRoster();
  if (!opts.silent) {
    const params = new URLSearchParams(location.search);
    if (isRoster) params.set('tab', 'roster'); else params.delete('tab');
    history.replaceState(null, '', location.pathname + '?' + params.toString());
  }
}
document.getElementById('tabBtnMatches').addEventListener('click', () => showTab('matches'));
document.getElementById('tabBtnRoster').addEventListener('click', () => showTab('roster'));

async function main() {
  const params = new URLSearchParams(location.search);
  const season = params.get('season');
  const clubSlug = params.get('club');
  const teamId = params.get('team');
  CUR_SEASON = season; CUR_TEAM_ID = teamId;
  if (!season || !clubSlug || !teamId) {
    document.getElementById('matchBody').innerHTML =
      `<tr><td class="empty-state" colspan="5">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  let payload;
  try {
    const res = await fetch(`data/team_cards_${season}/${clubSlug}.json`);
    payload = await res.json();
  } catch (e) {
    document.getElementById('matchBody').innerHTML =
      `<tr><td class="empty-state" colspan="5">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  const team = (payload.teams || {})[teamId];
  document.getElementById('clubName').textContent = payload.club || '';
  if (!team) {
    document.getElementById('teamName').textContent = payload.club || '—';
    document.getElementById('matchBody').innerHTML =
      `<tr><td class="empty-state" colspan="5">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  document.getElementById('teamName').textContent = team.name;
  document.title = `${team.name} — RFFM`;
  CUR_TEAM = team;
  renderMatches(team);
  showTab(params.get('tab') === 'roster' ? 'roster' : 'matches', { silent: true });
}

(function () {
  var I18N_ES = %I18N_ES_JSON%;
  %LANG_SWITCH_JS%
})();

document.querySelectorAll('.lang-opt').forEach(function (btn) {
  btn.addEventListener('click', function () { CURLANG = btn.getAttribute('data-lang-btn'); main(); });
});
try { if (localStorage.getItem('rffm_lang') === 'es') CURLANG = 'es'; } catch (e) {}

%THEME_SWITCH_JS%

main();
</script>
</body>
</html>
"""


def build_html() -> str:
    return (HTML
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%THEME_INIT%", THEME_INIT_JS)
            .replace("%SWITCH_ROW%", switch_row_html())
            .replace("%I18N_ES_JSON%", json.dumps(I18N_ES, ensure_ascii=False))
            .replace("%LANG_SWITCH_JS%", LANG_SWITCH_JS)
            .replace("%THEME_SWITCH_JS%", THEME_SWITCH_JS)
            .replace("%DATATABLE_CSS%", DATATABLE_CSS)
            .replace("%DATATABLE_JS%", DATATABLE_JS))


def main():
    parser = argparse.ArgumentParser(description="RFFM team-card data + page")
    parser.add_argument("--season", default=None, help="build only this season's data (default: every season with a complete core crawl)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    # Unlike club_division_map.py (which is cheap enough to bundle every
    # crawled season), a full team-card data set for all 8 seasons would run
    # ~450MB+ of JSON (matches.csv alone is 28-53 MB per season) — default to
    # just the latest season; club_division_map.py's season switcher still
    # works for older seasons, a team-card link just degrades to "no data"
    # there instead of shipping a half-gigabyte build artifact.
    seasons = seasons or [list_seasons()[-1]]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "team_card.html").write_text(build_html(), encoding="utf-8")

    for season in seasons:
        print(f"Building team cards for season {season}")
        club_teams = build_club_team_cards(season)
        slugs = club_slug_map(sorted(club_teams.keys()))
        data_dir = out_dir / "data" / f"team_cards_{season}"
        data_dir.mkdir(parents=True, exist_ok=True)
        for club, teams_of_club in club_teams.items():
            payload = {"club": club, "season": season, "teams": teams_of_club}
            (data_dir / f"{slugs[club]}.json").write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                encoding="utf-8")
        print(f"  {len(club_teams)} clubs written to {data_dir}")


if __name__ == "__main__":
    main()
