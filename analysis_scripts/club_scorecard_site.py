#!/usr/bin/env python3
"""RFFM site report: "Кантера" / "La Cantera" — youth-development scorecard
for all 685 clubs (size, ceiling, elite pathway, homegrown vs recruited,
retention curves, transfer balance). The metrics themselves are computed by
club_scorecard.py (Data/compute_all/to_compact_json/load_all_data) — this
module only turns that compact JSON payload into the site page, following
this project's report-module convention (load_all_data() + build_html(data),
wired into build_site.py) and its shared RU-default/ES-toggle, light/dark-
toggle chrome (site_theme.py).

Unlike most other reports here, this page's own render logic (the club
table, stat tiles, highlight cards, retention sparklines) is entirely
client-side JS driven off the embedded JSON, not server-templated rows -
so RU/ES switching for those sections is done by a small in-page LANG flag
the render functions consult directly (an ES string table, STRINGS_ES),
rather than the [data-i18n] DOM-swap trick site_theme.LANG_SWITCH_JS uses
for static markup elsewhere. Both mechanisms are wired to the same
.lang-opt buttons so a click updates both the static shell and the dynamic
sections together. See club_scorecard.py's module docstring for the
metrics methodology (founding-cohort seasons, the elite in-club/after-
leaving split, why there's no minimum-sample-size gate, etc).

Run standalone:
    python3 analysis_scripts/club_scorecard_site.py --output reports/club_scorecard.html
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from club_scorecard import load_all_data  # noqa: E402
from site_theme import FONT_LINKS, THEME_INIT_JS, THEME_SWITCH_JS, switch_row_html  # noqa: E402


HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Кантера — RFFM</title>
%FONT_LINKS%
%THEME_INIT%
<style>
:root{
  --bg:#f6f7f1; --surface:#ffffff; --surface-2:#ecefe3; --ink:#16231c; --ink-soft:#435248; --ink-faint:#77857a;
  --accent:#0e8f58; --accent-strong:#0b6e44; --accent-soft:#e4f2ea;
  --gold:#b8730f; --gold-strong:#93590c; --gold-soft:#fbf0dd;
  --line:#dbdfd0; --line-strong:#c3c9b6;
  --shadow: 0 1px 2px rgba(22,35,28,0.06), 0 8px 24px -12px rgba(22,35,28,0.18);
  --chart-club:#0e8f58; --chart-football:#9aa598; --chart-gold:#d9861c;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0e1712; --surface:#16221b; --surface-2:#1d2a22; --ink:#eaf0e7; --ink-soft:#b9c4b8; --ink-faint:#7e8c80;
    --accent:#1fa362; --accent-strong:#3fc17f; --accent-soft:#16311f;
    --gold:#d08a2a; --gold-strong:#e6a245; --gold-soft:#2e230f;
    --line:#2a3a2f; --line-strong:#3a4c3f;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5);
    --chart-club:#1fa362; --chart-football:#6e7c71; --chart-gold:#c77a18;
  }
}
:root[data-theme="dark"]{
  --bg:#0e1712; --surface:#16221b; --surface-2:#1d2a22; --ink:#eaf0e7; --ink-soft:#b9c4b8; --ink-faint:#7e8c80;
  --accent:#1fa362; --accent-strong:#3fc17f; --accent-soft:#16311f;
  --gold:#d08a2a; --gold-strong:#e6a245; --gold-soft:#2e230f;
  --line:#2a3a2f; --line-strong:#3a4c3f;
  --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5);
  --chart-club:#1fa362; --chart-football:#6e7c71; --chart-gold:#c77a18;
}
:root[data-theme="light"]{
  --bg:#f6f7f1; --surface:#ffffff; --surface-2:#ecefe3; --ink:#16231c; --ink-soft:#435248; --ink-faint:#77857a;
  --accent:#0e8f58; --accent-strong:#0b6e44; --accent-soft:#e4f2ea;
  --gold:#b8730f; --gold-strong:#93590c; --gold-soft:#fbf0dd;
  --line:#dbdfd0; --line-strong:#c3c9b6;
  --chart-club:#0e8f58; --chart-football:#9aa598; --chart-gold:#d9861c;
}
*,*::before,*::after{ box-sizing:border-box; }
body{ font-family:'PT Sans', system-ui, sans-serif; max-width:1180px; margin:0 auto; padding:0 20px 70px;
  color:var(--ink); background:var(--bg); font-size:15px; line-height:1.55; }
h1{ font-family:'Oswald', system-ui, sans-serif; font-weight:700; text-transform:uppercase; font-size:1.6rem; margin:0; letter-spacing:.02em; }
h2{ font-family:'Oswald', system-ui, sans-serif; font-weight:600; font-size:1.25rem; margin:0 0 12px; letter-spacing:.01em; }
a{ color:var(--accent-strong); }
.mono{ font-family:'JetBrains Mono', ui-monospace, monospace; font-variant-numeric:tabular-nums; }
.eyebrow{ font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--ink-faint); }

header.top{ position:sticky; top:0; z-index:20; background:color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter:blur(10px); border-bottom:1px solid var(--line); margin:0 -20px; padding:0 20px; }
.top-inner{ padding:14px 0; display:flex; align-items:center; gap:18px; flex-wrap:wrap; }
.brandmark{ display:flex; align-items:baseline; gap:10px; }
.brandmark .ball{ font-size:19px; }
.brandmark .sub{ font-size:12px; color:var(--ink-faint); font-family:'JetBrains Mono',monospace; }
.top-right{ margin-left:auto; display:flex; align-items:center; gap:14px; flex-wrap:wrap; }

.lang-switch,.theme-switch{ display:inline-flex; border:1px solid var(--line-strong); border-radius:999px; overflow:hidden; }
.lang-opt,.theme-opt{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:.04em;
  padding:5px 12px; background:var(--surface); color:var(--ink-soft); border:none; cursor:pointer; }
.lang-opt.is-active,.theme-opt.is-active{ background:var(--accent); color:#fff; }
.theme-opt{ font-size:13px; padding:4px 10px; }
.switch-row{ display:flex; gap:8px; }

.search-box{ position:relative; }
.search-box svg{ position:absolute; left:9px; top:50%; transform:translateY(-50%); opacity:.5; pointer-events:none; }
input[type="search"]{ font:inherit; font-size:13.5px; background:var(--surface); border:1px solid var(--line-strong);
  border-radius:4px; color:var(--ink); padding:7px 10px 7px 30px; width:220px; }

main{ padding-top:32px; }
.intro{ max-width:720px; margin-bottom:36px; }
.intro h1.page-title{ font-size:1.9rem; margin-bottom:12px; }
.intro p{ color:var(--ink-soft); font-size:15px; }
.intro p+p{ margin-top:8px; }

.stat-strip{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px; background:var(--line);
  border:1px solid var(--line); border-radius:8px; overflow:hidden; margin-bottom:44px; }
.stat-tile{ background:var(--surface); padding:16px 18px; }
.stat-tile .num{ font-family:'Oswald',sans-serif; font-size:28px; font-weight:600; color:var(--accent-strong); }
.stat-tile .lbl{ font-size:11.5px; color:var(--ink-faint); margin-top:4px; }

.section-head{ display:flex; align-items:baseline; justify-content:space-between; gap:16px; margin-bottom:14px; }
.section-head .note{ font-size:12px; color:var(--ink-faint); }
.highlights{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:13px; margin-bottom:48px; }
.hi-card{ background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--gold); border-radius:6px;
  padding:14px 16px; box-shadow:var(--shadow); }
.hi-card .hi-num{ font-family:'Oswald',sans-serif; font-size:24px; font-weight:600; }
.hi-card .hi-num small{ font-family:'PT Sans',sans-serif; font-size:12.5px; color:var(--ink-faint); font-weight:400; }
.hi-card .hi-club{ font-size:12.5px; font-weight:700; margin-top:2px; color:var(--accent-strong); }
.hi-card .hi-body{ font-size:12.5px; color:var(--ink-soft); margin-top:7px; }

.table-controls{ display:flex; align-items:center; gap:16px; margin-bottom:10px; flex-wrap:wrap; }
.toggle{ display:flex; align-items:center; gap:6px; font-size:12.5px; color:var(--ink-soft); }
.toggle input{ accent-color:var(--accent); }
.result-count{ font-size:12px; color:var(--ink-faint); margin-left:auto; font-family:'JetBrains Mono',monospace; }

.table-scroll{ overflow:auto; max-height:72vh; border:1px solid var(--line); border-radius:8px; background:var(--surface); }
table{ width:100%; border-collapse:collapse; min-width:900px; }
thead th{ position:sticky; top:0; z-index:5; background:var(--surface-2); text-align:left;
  font-family:'JetBrains Mono',monospace; font-size:10px; text-transform:uppercase; letter-spacing:.05em;
  color:var(--ink-faint); padding:9px 11px; border-bottom:1px solid var(--line); white-space:nowrap; cursor:pointer; user-select:none; }
thead th:hover{ color:var(--ink); }
thead th.num{ text-align:right; }
thead th .arrow{ opacity:0; margin-left:3px; }
thead th .help{ display:inline-flex; align-items:center; justify-content:center; width:13px; height:13px;
  margin-left:5px; border-radius:50%; border:1px solid var(--line-strong); color:var(--ink-faint);
  font-family:'PT Sans',sans-serif; font-size:9.5px; font-weight:700; text-transform:none; cursor:help; }
thead th .help:hover{ color:var(--accent-strong); border-color:var(--accent-strong); }
thead th.sorted .arrow{ opacity:1; color:var(--accent); }
tbody td{ padding:8px 11px; border-bottom:1px solid var(--line); font-size:13px; vertical-align:middle; }
tbody td.num{ text-align:right; }
tbody tr.club-row{ cursor:pointer; }
tbody tr.club-row:hover{ background:var(--surface-2); }
tbody tr.club-row.open{ background:var(--accent-soft); }
tbody td.mono{ font-family:'JetBrains Mono',monospace; font-variant-numeric:tabular-nums; }
.club-name-cell{ display:flex; align-items:center; gap:8px; max-width:250px; }
.club-name-cell .caret{ color:var(--ink-faint); font-size:9px; width:9px; flex:none; transition:transform .15s ease; }
tr.open .caret{ transform:rotate(90deg); color:var(--accent); }
.club-name-cell .name{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

.badge{ display:inline-block; font-family:'JetBrains Mono',monospace; font-size:10.5px; padding:2px 7px;
  border-radius:999px; white-space:nowrap; background:var(--surface-2); color:var(--ink-soft); border:1px solid var(--line-strong); }
.badge.tier1{ background:var(--gold-soft); color:var(--gold-strong); border-color:var(--gold); }
.badge.tier2{ background:var(--accent-soft); color:var(--accent-strong); border-color:var(--accent); }

.bar-cell{ display:flex; align-items:center; gap:8px; }
.bar-track{ width:52px; height:6px; border-radius:3px; background:var(--surface-2); overflow:hidden; flex:none; }
.bar-fill{ height:100%; background:var(--accent); border-radius:3px; }
.bar-val{ font-family:'JetBrains Mono',monospace; font-size:12px; width:38px; text-align:right; }
.net-pos{ color:var(--accent-strong); }
.net-neg{ color:var(--gold-strong); }
.muted-cell{ color:var(--ink-faint); }

tr.detail-row td{ padding:0; border-bottom:1px solid var(--line); }
.detail{ background:var(--surface-2); padding:18px 22px 24px; display:grid;
  grid-template-columns:minmax(210px,290px) 1fr; gap:26px; }
.detail h3{ font-family:'JetBrains Mono',monospace; font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--ink-faint); font-weight:500; margin:0 0 9px; }
.detail-stats{ display:flex; flex-direction:column; gap:9px; }
.dstat{ display:flex; justify-content:space-between; align-items:baseline; gap:10px; padding:6px 9px;
  background:var(--surface); border-radius:4px; border:1px solid var(--line); }
.dstat .k{ font-size:12px; color:var(--ink-soft); }
.dstat .v{ font-family:'JetBrains Mono',monospace; font-weight:600; font-size:13.5px; }
.elite-bar-wrap{ margin-top:5px; }
.elite-bar{ display:flex; height:18px; border-radius:4px; overflow:hidden; background:var(--surface); border:1px solid var(--line); }
.elite-legend{ display:flex; gap:12px; margin-top:7px; flex-wrap:wrap; }
.elite-legend span{ font-size:11px; color:var(--ink-soft); display:flex; align-items:center; gap:5px; }
.swatch{ width:8px; height:8px; border-radius:2px; flex:none; }
.curves-grid{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:14px; }
.curve-card{ background:var(--surface); border:1px solid var(--line); border-radius:4px; padding:9px 11px 7px; }
.curve-card .cc-head{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:2px; }
.curve-card .cc-cat{ font-size:12px; font-weight:700; }
.curve-card .cc-n{ font-size:10.5px; color:var(--ink-faint); font-family:'JetBrains Mono',monospace; }
.no-cohort{ color:var(--ink-faint); font-size:12.5px; font-style:italic; }

footer{ margin-top:56px; padding-top:18px; border-top:1px solid var(--line); color:var(--ink-faint); font-size:11.5px; }
a.back{ font-family:'JetBrains Mono',monospace; font-size:.8rem; color:var(--accent-strong); text-decoration:none; }

@media (max-width:720px){ .detail{ grid-template-columns:1fr; } input[type="search"]{ width:150px; } }
@media (prefers-reduced-motion: reduce){ *{ transition:none !important; } }
</style>
</head>
<body>

<header class="top">
  <div class="top-inner">
    <div class="brandmark">
      <span class="ball">&#9917;</span>
      <h1 data-i18n="brand">Кантера</h1>
      <span class="sub">RFFM&nbsp;&middot;&nbsp;Мадрид&nbsp;&middot;&nbsp;2016&ndash;2026</span>
    </div>
    <div class="top-right">
      <div class="search-box">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.4"/><path d="M11.5 11.5L15 15" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
        <input type="search" id="search" data-i18n-ph="search_ph" placeholder="Поиск клуба&hellip;" autocomplete="off">
      </div>
      %SWITCH_ROW%
    </div>
  </div>
</header>

<main>
  <a class="back" href="../index.html" data-i18n="back">&larr; на главную</a>

  <div class="intro">
    <h1 class="page-title" data-i18n="h_title">Какие клубы правда растят своих?</h1>
    <p data-i18n="h_p1">685 клубов Мадридского сообщества, у каждого — до 10 сезонов истории (2016&ndash;2026) команд, игроков и результатов. По каждому: сколько детей через него прошло, до какого уровня они доросли, сколько осталось — и сколько из тех, кто дошёл до элиты, реально выросли в этом клубе, а не пришли уже готовыми из другого.</p>
    <p data-i18n="h_p2">Родилась из одного конкретного вопроса — куда отдать сына 2021 года рождения — и заканчивается тем же вопросом сразу для всех 685.</p>
  </div>

  <div class="stat-strip" id="statStrip"></div>

  <section>
    <div class="section-head">
      <h2 data-i18n="hi_title">Что видно в данных</h2>
      <span class="note" data-i18n="hi_note">подборка, не рейтинг</span>
    </div>
    <div class="highlights" id="highlights"></div>
  </section>

  <section>
    <div class="section-head"><h2 data-i18n="tbl_title">685 клубов</h2></div>
    <div class="table-controls">
      <label class="toggle"><input type="checkbox" id="minAlumni"> <span data-i18n="tbl_hide">Скрыть клубов с alumni меньше 50 (маленький n — шумный %)</span></label>
      <span class="result-count" id="resultCount"></span>
    </div>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th data-key="n" data-i18n="col_club">Клуб<span class="help">?</span><span class="arrow">&#9662;</span></th>
            <th class="num" data-key="teams" data-i18n="col_teams">Команд сейчас<span class="help">?</span><span class="arrow">&#9662;</span></th>
            <th class="num" data-key="alumni" data-i18n="col_alumni">Alumni (n)<span class="help">?</span><span class="arrow">&#9662;</span></th>
            <th data-key="ctier" data-i18n="col_ceiling">Потолок<span class="help">?</span><span class="arrow">&#9662;</span></th>
            <th class="num" data-key="eliteAnyPct" data-i18n="col_elite">% дошёл до элиты<span class="help">?</span><span class="arrow">&#9662;</span></th>
            <th class="num" data-key="homegrownPct" data-i18n="col_home">% элиты — своя школа<span class="help">?</span><span class="arrow">&#9662;</span></th>
            <th class="num" data-key="cont" data-i18n="col_cont">Стабильность<span class="help">?</span><span class="arrow">&#9662;</span></th>
            <th class="num" data-key="net" data-i18n="col_net">Баланс трансферов<span class="help">?</span><span class="arrow">&#9662;</span></th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </section>

  <footer data-i18n="footer">
    Данные: Real Federación de Fútbol de Madrid (rffm.es), собраны собственным скрапером — 10 сезонов, 2016&ndash;2017&nbsp;&mdash;&nbsp;2025&ndash;2026. &laquo;Элита&raquo; = tier&nbsp;1&ndash;2 (Суперлига / Лига Насьональ / Дивизион де Онор). &laquo;Своя школа&raquo; = первое появление в данных зафиксировано в этом клубе, в возрасте Дебютанте/Пребенхамин &mdash; в пределах покрытия данных той эпохи (см. методологию в репозитории, club_scorecard.py).
  </footer>
</main>

<script>
const DATA = %DATA_JSON%;

const CAT_RU = {PREBENJAMIN:"Пребенхамин", BENJAMIN:"Бенхамин", ALEVIN:"Алевин", INFANTIL:"Инфантил", CADETE:"Кадете", JUVENIL:"Хувениль"};
const CAT_ES = {PREBENJAMIN:"Prebenjamín", BENJAMIN:"Benjamín", ALEVIN:"Alevín", INFANTIL:"Infantil", CADETE:"Cadete", JUVENIL:"Juvenil"};
const TIER_RU = {1:"Суперлига / Лига Насьональ", 2:"Дивизион де Онор", 3:"1-й Автоном. дивизион", 4:"Преференте", 5:"2-й Дивизион Б / 3-я Федерасьон", 6:"Примера", 7:"Сегунда", 8:"Терсера"};
const TIER_ES = {1:"Superliga / Liga Nacional", 2:"División de Honor", 3:"1ª Div. Autonómica", 4:"Preferente", 5:"2ª Div. B / 3ª Federación", 6:"Primera", 7:"Segunda", 8:"Tercera"};

const STRINGS = {
  ru: {
    statTiles: n => [
      [n.clubs, "клубов проанализировано"],
      [n.alumni, "игроков в базе (за всю историю)"],
      [n.teamsNow, "команд играет в этом сезоне"],
      [n.medElite, "медиана: % alumni, дошедших до элиты"],
      [n.medCont, "медиана: стабильность состава по сезонам"],
    ],
    hi: {
      eliteOf: n => `из ${n} экс-игроков дошли до элиты`,
      homeOfElite: "из них элита — своя школа",
      cont: "стабильность сезон за сезоном",
      corrLabel: n => `корреляция размер ↔ % элиты (n=${n} клубов, alumni≥50)`,
      corrPos: "Чем крупнее клуб, тем выше шанс, что кто-то из его алюмни дойдёт до элиты — ожидаемо, больше попыток.",
      corrNeg: "Размер клуба почти не предсказывает, дойдут ли его игроки до элиты.",
      rayoBody: pct => `Но лишь <b>${pct}</b> этой элиты начинала здесь с Пребенхамина — почти все пришли уже сформированными из другого клуба.`,
      madridBody: (elitePct, alumni) => `При ${elitePct} из ${alumni} alumni, дошедших до элиты — лучший баланс уровня и настоящей своей школы среди топ-клубов.`,
      aravacaBody: span => `${span} из ${span} сезонов с командой на поле — ни разу не пропустил кампанию.`,
      allData: "Весь датасет",
    },
    hideSmall: "Скрыть клубов с alumni меньше 50 (маленький n — шумный %)",
    resultCount: (a,b) => `${a} / ${b} клубов`,
    searchPh: "Поиск клуба…",
    detail: {
      eliteTrack: "Траектория элиты",
      inClub: "Дошёл до элиты в этом клубе",
      afterLeaving: "Дошёл до элиты уже после ухода",
      homegrown: "Из элиты — своя школа (Дебютанте/Пребенхамин здесь)",
      ofKnown: "из известных",
      ceiling: "Потолок клуба",
      netTransfers: "Баланс трансферов (за всю историю)",
      cardsPerMatch: "Карточек за матч",
      legendIn: "в клубе",
      legendAfter: "после ухода",
      legendNever: "не дошёл",
      noCohort: "Недостаточно данных по поколению-основателю для кривых удержания.",
      curvesTitle: "Удержание по поколению-основателю",
    },
    club_name_col: "n",
  },
  es: {
    statTiles: n => [
      [n.clubs, "clubes analizados"],
      [n.alumni, "jugadores en la base (histórico)"],
      [n.teamsNow, "equipos activos esta temporada"],
      [n.medElite, "mediana: % de alumni que llegó a élite"],
      [n.medCont, "mediana: continuidad de temporada en temporada"],
    ],
    hi: {
      eliteOf: n => `de ${n} ex-jugadores llegó a élite`,
      homeOfElite: "de esa élite es cantera propia",
      cont: "continuidad de temporada en temporada",
      corrLabel: n => `correlación tamaño ↔ % élite (n=${n} clubes, alumni≥50)`,
      corrPos: "Cuanto más grande el club, más probabilidad de que algún alumni llegue a élite — esperable, más intentos.",
      corrNeg: "El tamaño del club apenas predice si sus jugadores llegan a élite.",
      rayoBody: pct => `Pero solo <b>${pct}</b> de esa élite empezó ahí de Prebenjamín — casi todos llegaron ya formados de otro club.`,
      madridBody: (elitePct, alumni) => `Con ${elitePct} de ${alumni} alumni llegando a élite — el mejor equilibrio entre nivel y cantera real entre los grandes.`,
      aravacaBody: span => `${span} de ${span} temporadas con equipo en el terreno de juego — nunca ha faltado a una campaña.`,
      allData: "Todo el dataset",
    },
    hideSmall: "Ocultar clubes con menos de 50 alumni (n bajo, % ruidoso)",
    resultCount: (a,b) => `${a} / ${b} clubes`,
    searchPh: "Buscar club…",
    detail: {
      eliteTrack: "Trayectoria de élite",
      inClub: "Llegó a élite en este club",
      afterLeaving: "Llegó a élite tras marcharse",
      homegrown: "De la élite, cantera propia (Debutante/Prebenjamín aquí)",
      ofKnown: "de conocidos",
      ceiling: "Techo del club",
      netTransfers: "Saldo de fichajes (histórico)",
      cardsPerMatch: "Tarjetas por partido",
      legendIn: "en el club",
      legendAfter: "tras marcharse",
      legendNever: "nunca llegó",
      noCohort: "Sin datos suficientes de la generación fundadora para curvas de retención.",
      curvesTitle: "Retención por generación fundadora",
    },
    club_name_col: "n",
  },
};

let LANG = "ru";
function T(){ return STRINGS[LANG]; }
function CAT(){ return LANG === "ru" ? CAT_RU : CAT_ES; }
function TIER(){ return LANG === "ru" ? TIER_RU : TIER_ES; }

const COL_HELP = {
  ru: {
    n: "Клик по строке — раскрыть детали клуба: динамика по сезонам, переходы, разбивка по возрастам.",
    teams: "Сколько команд клуба играет в текущем сезоне (2025/26).",
    alumni: "Все игроки, хоть раз попавшие в протокол матча за этот клуб — за всю историю данных (2016–2026).",
    ctier: "Самый высокий дивизион, которого клуб когда-либо достигал — любая команда, любой сезон, не обязательно сейчас.",
    eliteAnyPct: "Доля alumni, кто хоть раз играл в топ-2 дивизиона (элита) — в этом клубе или уже в другом после ухода.",
    homegrownPct: "Из тех, кто дошёл до элиты: доля, чьё первое появление в данных — именно в этом клубе, в возрасте Дебютанте/Пребенхамин.",
    cont: "Доля сезонов между первым и последним появлением клуба в данных, когда у него была хотя бы одна команда — насколько непрерывно он существовал.",
    net: "Игроков пришло минус ушло между сезонами, по всей истории. Плюс — клуб чаще принимает, чем отдаёт.",
  },
  es: {
    n: "Clic en la fila — detalle del club: evolución por temporada, fichajes, desglose por categorías.",
    teams: "Cuántos equipos del club juegan en la temporada actual (2025/26).",
    alumni: "Todos los jugadores que aparecieron alguna vez en un acta del club, en toda la historia de datos (2016–2026).",
    ctier: "La división más alta que el club alcanzó alguna vez — cualquier equipo, cualquier temporada, no necesariamente ahora.",
    eliteAnyPct: "Porcentaje de alumni que jugó alguna vez en el top-2 de divisiones (élite) — en este club o ya en otro tras salir.",
    homegrownPct: "De los que llegaron a la élite: porcentaje cuya primera aparición registrada fue en este club, en edad Debutante/Prebenjamín.",
    cont: "Porcentaje de temporadas, entre la primera y la última aparición del club en los datos, en las que tuvo al menos un equipo — continuidad.",
    net: "Jugadores que llegaron menos los que se fueron, entre temporadas, en toda la historia. Positivo = el club recibe más de lo que cede.",
  },
};
function applyColHelp(){
  document.querySelectorAll("thead th[data-key]").forEach(th=>{
    const help = COL_HELP[LANG][th.dataset.key];
    if(!help) return;
    const span = th.querySelector(".help");
    if(span) span.title = help;
  });
}
function fmtPct(v){ return (v===null||v===undefined) ? "—" : v.toFixed(1)+"%"; }
function fmtN(v){ return (v===null||v===undefined) ? "—" : v.toLocaleString(LANG==="ru"?"ru-RU":"es-ES"); }

function renderStats(){
  const clubs = DATA.clubs;
  const totalAlumni = clubs.reduce((s,c)=>s+(c.alumni||0),0);
  const contVals = clubs.map(c=>c.cont).filter(v=>v!=null).sort((a,b)=>a-b);
  const medCont = contVals[Math.floor(contVals.length/2)];
  const eliteVals = clubs.map(c=>c.eliteAnyPct).filter(v=>v!=null).sort((a,b)=>a-b);
  const medElite = eliteVals[Math.floor(eliteVals.length/2)];
  const totalTeamsNow = clubs.reduce((s,c)=>s+(c.teams||0),0);
  const tiles = T().statTiles({
    clubs: clubs.length.toLocaleString(LANG==="ru"?"ru-RU":"es-ES"),
    alumni: totalAlumni.toLocaleString(LANG==="ru"?"ru-RU":"es-ES"),
    teamsNow: totalTeamsNow.toLocaleString(LANG==="ru"?"ru-RU":"es-ES"),
    medElite: fmtPct(medElite), medCont: fmtPct(medCont),
  });
  document.getElementById("statStrip").innerHTML = tiles.map(([n,l])=>
    `<div class="stat-tile"><div class="num mono">${n}</div><div class="lbl">${l}</div></div>`).join("");
}

function byId(id){ return DATA.clubs.find(c=>c.id===id); }
function pearson(xs, ys){
  const n = xs.length; const mx = xs.reduce((a,b)=>a+b,0)/n; const my = ys.reduce((a,b)=>a+b,0)/n;
  let num=0, dx=0, dy=0;
  for(let i=0;i<n;i++){ num += (xs[i]-mx)*(ys[i]-my); dx += (xs[i]-mx)**2; dy += (ys[i]-my)**2; }
  return num/Math.sqrt(dx*dy);
}
function renderHighlights(){
  const s = T().hi;
  const cards = [];
  const rayo = byId(30433), madrid = byId(40017), aravaca = byId(1011);
  if(rayo) cards.push({ num: fmtPct(rayo.eliteAnyPct), sub: s.eliteOf(rayo.alumni), club: rayo.n, body: s.rayoBody(fmtPct(rayo.homegrownPct)) });
  if(madrid) cards.push({ num: fmtPct(madrid.homegrownPct), sub: s.homeOfElite, club: madrid.n, body: s.madridBody(fmtPct(madrid.eliteAnyPct), madrid.alumni) });
  if(aravaca) cards.push({ num: fmtPct(aravaca.cont), sub: s.cont, club: aravaca.n, body: s.aravacaBody(aravaca.span) });
  const big = DATA.clubs.filter(c=>c.alumni>=50 && c.eliteAnyPct!=null && c.cont!=null);
  const r = pearson(big.map(c=>c.alumni), big.map(c=>c.eliteAnyPct));
  cards.push({ num: r.toFixed(2), sub: s.corrLabel(big.length), club: s.allData, body: r>0.3 ? s.corrPos : s.corrNeg });
  document.getElementById("highlights").innerHTML = cards.map(c=>`
    <div class="hi-card"><div class="hi-num">${c.num} <small>${c.sub}</small></div>
    <div class="hi-club">${c.club}</div><div class="hi-body">${c.body}</div></div>`).join("");
}

let sortKey = "alumni", sortDir = -1, hideSmall = false, filterText = "", openId = null;
function tierBadgeClass(t){ if(t===1) return "tier1"; if(t===2) return "tier2"; return ""; }
function filteredSorted(){
  let rows = DATA.clubs.filter(c => c.n.toLowerCase().includes(filterText));
  if(hideSmall) rows = rows.filter(c => (c.alumni||0) >= 50);
  rows = rows.slice().sort((a,b)=>{
    let av=a[sortKey], bv=b[sortKey];
    if(av==null && bv==null) return 0;
    if(av==null) return 1; if(bv==null) return -1;
    if(typeof av === "string") return av.localeCompare(bv) * sortDir * -1;
    return (av-bv) * sortDir;
  });
  return rows;
}
function ceilingCell(c){
  if(c.ctier==null) return `<span class="muted-cell">—</span>`;
  const label = TIER()[c.ctier] || c.cdiv || "";
  return `<span class="badge ${tierBadgeClass(c.ctier)}" title="${c.cdiv||''} · ${(CAT()[c.ccat]||c.ccat||'')} · ${c.cseason||''}">${label}</span>`;
}
function barCell(pct){
  if(pct==null) return `<span class="muted-cell">—</span>`;
  const w = Math.max(2, Math.min(100, pct));
  return `<div class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:${w}%"></div></div><div class="bar-val mono">${fmtPct(pct)}</div></div>`;
}
function netCell(c){
  if(c.net==null) return `<span class="muted-cell">—</span>`;
  const cls = c.net > 0 ? "net-pos" : (c.net < 0 ? "net-neg" : "");
  const sign = c.net > 0 ? "+" : "";
  return `<span class="mono ${cls}">${sign}${c.net}</span>`;
}
function renderTable(){
  const rows = filteredSorted();
  document.getElementById("resultCount").textContent = T().resultCount(rows.length, DATA.clubs.length);
  document.querySelectorAll("thead th[data-key]").forEach(th=>{
    th.classList.toggle("sorted", th.dataset.key===sortKey);
    const arrow = th.querySelector(".arrow");
    if(arrow) arrow.textContent = (th.dataset.key===sortKey) ? (sortDir===1 ? "▴" : "▾") : "▾";
  });
  const html = [];
  for(const c of rows){
    const isOpen = c.id === openId;
    html.push(`<tr class="club-row ${isOpen?'open':''}" data-id="${c.id}">
      <td><div class="club-name-cell"><span class="caret">▸</span><span class="name" title="${c.n}">${c.n}</span></div></td>
      <td class="num mono">${fmtN(c.teams)}</td>
      <td class="num mono">${fmtN(c.alumni)}</td>
      <td>${ceilingCell(c)}</td>
      <td>${barCell(c.eliteAnyPct)}</td>
      <td>${barCell(c.homegrownPct)}</td>
      <td class="num mono">${fmtPct(c.cont)}</td>
      <td class="num">${netCell(c)}</td>
    </tr>`);
    if(isOpen) html.push(`<tr class="detail-row"><td colspan="8">${renderDetail(c)}</td></tr>`);
  }
  document.getElementById("tbody").innerHTML = html.join("");
  document.querySelectorAll("tr.club-row").forEach(tr=>{
    tr.addEventListener("click", ()=>{
      const id = Number(tr.dataset.id);
      openId = (openId === id) ? null : id;
      renderTable();
    });
  });
}
function renderDetail(c){
  const d = T().detail;
  const eliteTotal = c.alumni || 0;
  const inClub = c.eliteInN || 0, after = c.eliteAfterN || 0;
  const notElite = Math.max(0, eliteTotal - inClub - after);
  const pct = x => eliteTotal ? (x/eliteTotal*100) : 0;
  const stats = `<div class="detail-stats"><h3>${d.eliteTrack}</h3>
      <div class="dstat"><span class="k">${d.inClub}</span><span class="v">${fmtN(inClub)}</span></div>
      <div class="dstat"><span class="k">${d.afterLeaving}</span><span class="v">${fmtN(after)}</span></div>
      <div class="dstat"><span class="k">${d.homegrown}</span><span class="v">${fmtN(c.homegrownN)} ${c.homegrownPct!=null ? '('+fmtPct(c.homegrownPct)+' '+d.ofKnown+')' : ''}</span></div>
      <div class="dstat"><span class="k">${d.ceiling}</span><span class="v">${c.cdiv||'—'}</span></div>
      <div class="dstat"><span class="k">${d.netTransfers}</span><span class="v">${netCell(c)}</span></div>
      <div class="dstat"><span class="k">${d.cardsPerMatch}</span><span class="v">${c.cardsPm!=null?c.cardsPm:'—'}</span></div>
      <div class="elite-bar-wrap"><div class="elite-bar">
        <div class="seg" style="width:${pct(inClub)}%; background:var(--chart-club)"></div>
        <div class="seg" style="width:${pct(after)}%; background:var(--chart-gold)"></div>
        <div class="seg" style="width:${pct(notElite)}%; background:var(--line-strong)"></div>
      </div><div class="elite-legend">
        <span><span class="swatch" style="background:var(--chart-club)"></span>${d.legendIn}</span>
        <span><span class="swatch" style="background:var(--chart-gold)"></span>${d.legendAfter}</span>
        <span><span class="swatch" style="background:var(--line-strong)"></span>${d.legendNever}</span>
      </div></div></div>`;
  const cohort = DATA.cohort[String(c.id)] || [];
  let curvesHtml;
  if(cohort.length === 0){
    curvesHtml = `<div class="no-cohort">${d.noCohort}</div>`;
  } else {
    const byCat = {};
    cohort.forEach(row => { (byCat[row.cat] = byCat[row.cat]||[]).push(row); });
    curvesHtml = `<div class="curves-grid">` + Object.entries(byCat).map(([cat, rows])=>{
      rows.sort((a,b)=>a.h-b.h);
      return `<div class="curve-card"><div class="cc-head"><span class="cc-cat">${CAT()[cat]||cat}</span><span class="cc-n">n=${rows[0].n} · ${rows[0].cs}</span></div>${sparkline(rows)}</div>`;
    }).join("") + `</div>`;
  }
  return `<div class="detail">${stats}<div><h3>${d.curvesTitle}</h3>${curvesHtml}</div></div>`;
}
function sparkline(rows){
  const W=200,H=90,PAD_L=26,PAD_B=16,PAD_T=8,PAD_R=8;
  const plotW=W-PAD_L-PAD_R, plotH=H-PAD_T-PAD_B;
  const maxH=Math.max(...rows.map(r=>r.h));
  const x=h=>PAD_L+(h-1)/(Math.max(1,maxH-1))*plotW;
  const y=pct=>PAD_T+(1-pct/100)*plotH;
  const pathFor=key=>rows.map((r,i)=>(i===0?"M":"L")+x(r.h).toFixed(1)+","+y(r[key]).toFixed(1)).join(" ");
  const clubPath=pathFor("rcPct"), footPath=pathFor("rfPct");
  const last=rows[rows.length-1];
  const gridLines=[0,50,100].map(v=>`<line x1="${PAD_L}" y1="${y(v)}" x2="${W-PAD_R}" y2="${y(v)}" stroke="var(--line)" stroke-width="1"/>
    <text x="${PAD_L-5}" y="${y(v)+3}" text-anchor="end" font-size="8" fill="var(--ink-faint)" font-family="JetBrains Mono, monospace">${v}</text>`).join("");
  const yr = LANG==="ru" ? ["год 1","год "+maxH] : ["año 1","año "+maxH];
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" role="img">
    ${gridLines}
    <path d="${footPath}" fill="none" stroke="var(--chart-football)" stroke-width="2" stroke-dasharray="3,3" stroke-linecap="round"/>
    <path d="${clubPath}" fill="none" stroke="var(--chart-club)" stroke-width="2" stroke-linecap="round"/>
    <circle cx="${x(last.h)}" cy="${y(last.rfPct)}" r="2.5" fill="var(--chart-football)"/>
    <circle cx="${x(last.h)}" cy="${y(last.rcPct)}" r="2.5" fill="var(--chart-club)"/>
    <text x="${x(last.h)+4}" y="${y(last.rfPct)+3}" font-size="8.5" fill="var(--chart-football)" font-family="JetBrains Mono, monospace">${last.rfPct.toFixed(0)}%</text>
    <text x="${x(last.h)+4}" y="${y(last.rcPct)-3}" font-size="8.5" font-weight="600" fill="var(--chart-club)" font-family="JetBrains Mono, monospace">${last.rcPct.toFixed(0)}%</text>
    <text x="${PAD_L}" y="${H-3}" font-size="8" fill="var(--ink-faint)" font-family="JetBrains Mono, monospace">${yr[0]}</text>
    <text x="${W-PAD_R}" y="${H-3}" text-anchor="end" font-size="8" fill="var(--ink-faint)" font-family="JetBrains Mono, monospace">${yr[1]}</text>
  </svg>`;
}

function renderAll(){ renderStats(); renderHighlights(); renderTable(); }

document.querySelectorAll("thead th[data-key]").forEach(th=>{
  th.addEventListener("click", (e)=>{
    if(e.target.classList.contains("help")) return;
    const key = th.dataset.key;
    if(sortKey === key) sortDir *= -1; else { sortKey = key; sortDir = -1; }
    renderTable();
  });
});
document.getElementById("search").addEventListener("input", e=>{
  filterText = e.target.value.trim().toLowerCase();
  openId = null;
  renderTable();
});
document.getElementById("minAlumni").addEventListener("change", e=>{
  hideSmall = e.target.checked;
  openId = null;
  renderTable();
});
document.querySelectorAll(".lang-opt").forEach(btn=>{
  btn.addEventListener("click", ()=>{
    LANG = btn.getAttribute("data-lang-btn") === "es" ? "es" : "ru";
    document.getElementById("search").placeholder = T().searchPh;
    openId = null;
    renderAll();
    applyColHelp();
  });
});

renderAll();
applyColHelp();
</script>
%THEME_SWITCH_INLINE%
</body>
</html>
"""


def build_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    theme_switch_inline = f"<script>{THEME_SWITCH_JS}</script>"
    return (HTML
            .replace("%DATA_JSON%", data_json)
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%THEME_INIT%", THEME_INIT_JS)
            .replace("%SWITCH_ROW%", switch_row_html())
            .replace("%THEME_SWITCH_INLINE%", theme_switch_inline))


def main():
    parser = argparse.ArgumentParser(description="RFFM club youth-development scorecard (\"Кантера\")")
    parser.add_argument("--output", default="reports/club_scorecard.html")
    args = parser.parse_args()

    print("Computing scorecard for all clubs (this recomputes everything from Parquet)...")
    data = load_all_data()
    print(f"  {len(data['clubs'])} clubs, {len(data['cohort'])} with cohort data")

    out = Path(__file__).parent.parent / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(data), encoding="utf-8")
    print(f"Report written to {out} ({out.stat().st_size/1024/1024:.2f} MB)")


if __name__ == "__main__":
    main()
