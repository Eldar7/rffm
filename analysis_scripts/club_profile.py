#!/usr/bin/env python3
"""
Club Profile: pick one club, slice by season/age-category/team, and see
where its current squads' players came from (donor clubs, Sankey + ranking),
what the squad looks like (composition overview), and how individual
players' careers moved through clubs/teams/divisions over time (group
trajectory chart + a per-player detail card). See club_profile_data.py for
the data model this reads.

One HTML page (club_profile.html) + a small club index (small enough to
embed: ~1,200 clubs' name/slug/season-range) + one JSON per club, fetched
lazily only once a club is picked (data/club_profile/<slug>.json) — mirrors
team_rosters.py's "only fetch when actually opened" pattern, since a club's
full alumni-career payload can run into the megabytes (see
club_profile_data.club_payload()'s docstring) and there are ~1,200 clubs.

Usage:
    python analysis_scripts/club_profile.py
    python analysis_scripts/club_profile.py --output-dir reports
"""

import argparse
import json
from pathlib import Path

import club_profile_data as cpd
from club_division_map import CAT_LABEL_ES, CATEGORIES, DIV_CODE, DIV_LABEL_ES, GT_CODE, TIER_OF
from site_theme import FONT_LINKS, LANG_SWITCH_JS, THEME_INIT_JS, THEME_SWITCH_JS, switch_row_html

# This page's own :root token set matches club_division_map.py / team_cards.py
# / player_cards.py (NOT site_theme.CSS, which only index.html actually uses)
# on purpose — those are the pages this one cross-links with directly, so a
# visitor bouncing between "Профиль клуба" and the club/team/player cards
# should see one consistent look, not two different design systems.

CAT_ORDER = CATEGORIES + ["OTHER"]
CAT_LABEL = dict(CAT_LABEL_ES)
CAT_LABEL["OTHER"] = "Otro / Прочее"

# division_level -> short code -> {tier, label}, derived from club_division_map.py's
# own tables so this page can never drift from the tier scheme every other
# report already uses. Keyed by the SAME code club_profile_data.club_payload()
# stores on each row (DIV_CODE.get(division_level, division_level) — codes
# with no DIV_CODE entry, e.g. "OTHER"/"FASE ZONAL", fall back to their own
# raw division_level string as their own "code").
CODE_TIER: dict[str, int | None] = {}
CODE_LABEL: dict[str, str] = {}
for _div, _tier in TIER_OF.items():
    _code = DIV_CODE.get(_div, _div)
    CODE_TIER[_code] = _tier
    CODE_LABEL[_code] = DIV_LABEL_ES.get(_div, _div)
GT_LABEL = {v: k for k, v in GT_CODE.items()}


def build_all(out_dir: Path) -> None:
    print("Building club career index (all seasons, fichajugador)...")
    seasons = cpd.list_seasons()
    career = cpd.build_career(seasons)
    clubs = cpd.club_index(career)
    lookup = cpd.build_players_lookup(seasons)
    print(f"  {len(career)} participation rows, {len(clubs)} clubs, {len(lookup)} players")

    data_dir = out_dir / "data"
    club_dir = data_dir / "club_profile"
    club_dir.mkdir(parents=True, exist_ok=True)

    (data_dir / "club_profile_index.json").write_text(
        json.dumps(cpd.index_payload(clubs), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"Building {len(clubs)} per-club profile files...")
    total_bytes = 0
    for i, key in enumerate(clubs, start=1):
        payload = cpd.club_payload(career, clubs, key)
        cpd.attach_player_names(payload, lookup)
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        total_bytes += len(text)
        (club_dir / f"{clubs[key]['slug']}.json").write_text(text, encoding="utf-8")
        if i % 200 == 0:
            print(f"  {i}/{len(clubs)}...")
    print(f"  done, {total_bytes / 1e6:.0f} MB across {len(clubs)} club files")

    (out_dir / "club_profile.html").write_text(build_html(seasons), encoding="utf-8")


def build_html(seasons: list[str]) -> str:
    return (HTML
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%THEME_INIT%", THEME_INIT_JS)
            .replace("%THEME_SWITCH_JS%", THEME_SWITCH_JS)
            .replace("%SWITCH_ROW%", switch_row_html())
            .replace("%ALL_SEASONS_JSON%", json.dumps(seasons))
            .replace("%CAT_ORDER_JSON%", json.dumps(CAT_ORDER))
            .replace("%CAT_LABEL_JSON%", json.dumps(CAT_LABEL, ensure_ascii=False))
            .replace("%CODE_TIER_JSON%", json.dumps(CODE_TIER, ensure_ascii=False))
            .replace("%CODE_LABEL_JSON%", json.dumps(CODE_LABEL, ensure_ascii=False))
            .replace("%GT_LABEL_JSON%", json.dumps(GT_LABEL, ensure_ascii=False))
            .replace("%I18N_ES_JSON%", json.dumps(I18N_ES, ensure_ascii=False))
            .replace("__CSS__", PAGE_CSS)
            .replace("__JS__", PAGE_JS)
            .replace("__LANG_JS__", LANG_SWITCH_JS))


def main():
    parser = argparse.ArgumentParser(description="RFFM club profile report (donors, roster, career paths)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    build_all(Path(__file__).parent.parent / args.output_dir)


I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; perfil de club",
    "back": "&larr; Portada",
    "h1": "Perfil de club",
    "lede": "Elige un club para ver de qué clubes llegaron sus jugadores, cómo es la plantilla y qué camino "
            "siguió cada jugador por clubes, equipos y divisiones a lo largo de los años.",
    "pick_placeholder": "Buscar club (p. ej. Getafe, Aravaca, Real Madrid)…",
    "pick_hint": "Escribe para buscar entre los clubes con datos de inscripción de jugadores (2018-2019 a 2025-2026).",
    "loading": "Cargando…",
    "scope_seasons": "Temporadas", "scope_cats": "Categorías", "scope_teams": "Equipos",
    "preset_all": "Todas", "preset_last3": "Últimas 3", "preset_current": "Temporada actual",
    "preset_none": "Ninguna",
    "chips_reset": "Restablecer filtros",
    "count_players": "jugadores", "count_clubs": "clubes en la vista",
    "mode_detailed": "Detallado", "mode_compact": "Compacto",
    "h_flow": "De dónde llegaron / a dónde se fueron",
    "dir_in": "De dónde llegaron", "dir_out": "A dónde se fueron",
    "flow_view_sankey": "Diagrama", "flow_view_rank": "Ranking",
    "homegrown_lbl": "Cantera (siempre en el club)", "gap_lbl": "Llegada tras un hueco de datos (club previo desconocido)",
    "active_lbl": "Sigue en el club", "notfound_lbl": "Sin datos posteriores (no necesariamente una baja)",
    "th_club": "Club", "th_players": "Jugadores", "th_pct": "%",
    "flow_empty": "No hay movimientos de jugadores en este recorte.",
    "h_roster": "Plantilla en este recorte",
    "kpi_total": "Jugadores", "kpi_clubs_teams": "Equipos", "kpi_cats": "Categorías",
    "kpi_stability": "Estabilidad (repiten temporada)",
    "h_heatmap": "Categoría × equipo",
    "h_paths": "Camino de los jugadores",
    "paths_note": "Eje Y: categoría (bloque) y división dentro de ella — los niveles solo son comparables "
                  "dentro de la misma categoría, no entre categorías distintas.",
    "paths_search": "Buscar/resaltar jugador…",
    "status_in": "En la plantilla", "status_new": "Nuevo esta temporada", "status_left": "Se fue",
    "player_modal_close": "Cerrar",
    "player_homegrown": "Cantera del club — sin registro previo en otro club.",
    "player_from": "Llegó de {club} en la temporada {season}.",
    "player_gap": "Llegó tras un hueco sin datos; club previo desconocido.",
    "th_season": "Temporada", "th_club_row": "Club", "th_team_row": "Equipo", "th_cat_row": "Categoría", "th_div_row": "División",
    "footer": 'Construido a partir de <code>output/processed/rffm/*/player_competition_participation.csv</code> '
              '(temporadas 2018-2019 a 2025-2026). No existe un <code>transfers.csv</code> — un club anterior/posterior '
              'solo se muestra cuando el jugador tiene inscripción confirmada en dos temporadas consecutivas; un hueco '
              'sin datos se marca como desconocido, nunca como una baja o llegada inventada. Ver '
              '<code>analysis_scripts/club_profile.py</code> / <code>club_profile_data.py</code>.',
}


HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — профиль клуба</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.27.0/plotly.min.js"></script>
%FONT_LINKS%
%THEME_INIT%
<style>__CSS__</style>
</head>
<body>

<div class="page full">
  <header class="masthead">
    %SWITCH_ROW%
    <a class="back" href="index.html">&larr; RFFM data</a>
    <span class="eyebrow"><span data-i18n="eyebrow">RFFM (Мадрид) &middot; профиль клуба</span></span>
    <h1><span data-i18n="h1">Профиль клуба</span></h1>
    <p><span data-i18n="lede">Выберите клуб, чтобы увидеть, из каких клубов пришли его игроки, как устроен состав
      и какой путь по клубам/командам/дивизионам прошёл каждый игрок.</span></p>
  </header>

  <div class="pick-wrap">
    <div class="search" id="clubSearchBox">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input type="text" id="clubSearch" data-i18n-ph="pick_placeholder" placeholder="Поиск клуба (напр. Getafe, Aravaca, Real Madrid)&hellip;" autocomplete="off">
    </div>
    <div class="pick-pop" id="clubSearchPop"></div>
  </div>
  <p class="foot" id="pickHint"><span data-i18n="pick_hint">Начните вводить название — поиск по клубам с данными о заявках игроков (сезоны 2018-2019 &ndash; 2025-2026).</span></p>

  <div id="app" style="display:none">

    <div class="club-head" id="clubHead"></div>

    <div class="filter-panel">
      <div id="filterbar"></div>
      <div class="chiprow" id="chiprow"></div>
    </div>

    <section>
      <div class="section-head">
        <h2><span data-i18n="h_flow">Откуда пришли / куда уходят</span></h2>
        <div class="seg" id="dirToggle">
          <button type="button" class="seg-opt is-active" data-dir="in"><span data-i18n="dir_in">Откуда пришли</span></button>
          <button type="button" class="seg-opt" data-dir="out"><span data-i18n="dir_out">Куда уходят</span></button>
        </div>
        <div class="seg" id="flowViewToggle">
          <button type="button" class="seg-opt is-active" data-view="sankey"><span data-i18n="flow_view_sankey">Диаграмма</span></button>
          <button type="button" class="seg-opt" data-view="rank"><span data-i18n="flow_view_rank">Рейтинг</span></button>
        </div>
      </div>
      <div class="flow-stats" id="flowStats"></div>
      <div class="chart-wrap"><p class="foot" id="sankeyEmptyMsg" style="display:none;margin:0 0 1rem"></p><div id="sankeyDiv" style="width:100%;min-height:460px"></div></div>
      <div class="table-shell" id="rankWrap" style="display:none">
        <div class="table-scroll"><table><thead><tr><th><span data-i18n="th_club">Клуб</span></th><th class="num"><span data-i18n="th_players">Игроков</span></th><th class="num"><span data-i18n="th_pct">%</span></th></tr></thead>
        <tbody id="rankBody"></tbody></table></div>
      </div>
    </section>

    <section>
      <div class="section-head"><h2><span data-i18n="h_roster">Состав в этом срезе</span></h2></div>
      <div class="stats" id="statStrip"></div>
      <div class="chart-wrap"><div id="heatmapDiv" style="width:100%;min-height:360px"></div></div>
    </section>

    <section>
      <div class="section-head">
        <h2><span data-i18n="h_paths">Путь игроков</span></h2>
        <input type="text" id="pathSearch" class="path-search" data-i18n-ph="paths_search" placeholder="Найти/выделить игрока&hellip;" autocomplete="off">
      </div>
      <p class="scope-note"><span class="mark">i</span> <span data-i18n="paths_note">Ось Y: категория (блок) и дивизион внутри неё &mdash; уровни сравнимы только внутри одной категории, а не между разными категориями.</span></p>
      <p class="foot" id="pathsCapNote"></p>
      <div class="chart-wrap"><div id="pathsDiv" style="width:100%;min-height:520px"></div></div>
    </section>

  </div>

  <footer class="note"><span data-i18n="footer">Построено из <code>output/processed/rffm/*/player_competition_participation.csv</code>
    (сезоны 2018-2019 &ndash; 2025-2026). Отдельного <code>transfers.csv</code> не существует &mdash; предыдущий/следующий клуб
    показывается только когда у игрока есть подтверждённая заявка в двух подряд идущих сезонах; разрыв без данных помечается
    как неизвестный, а не выдаётся за уход или приход. См. <code>analysis_scripts/club_profile.py</code> /
    <code>club_profile_data.py</code>.</span></footer>
</div>

<div class="modal-backdrop hidden" id="playerModalBackdrop">
  <div class="modal" id="playerModalCard"></div>
</div>

<script>
const ALL_SEASONS = %ALL_SEASONS_JSON%;
const CAT_ORDER = %CAT_ORDER_JSON%;
const CAT_LABEL = %CAT_LABEL_JSON%;
const CODE_TIER = %CODE_TIER_JSON%;
const CODE_LABEL = %CODE_LABEL_JSON%;
const GT_LABEL = %GT_LABEL_JSON%;
const I18N_ES = %I18N_ES_JSON%;
__JS__
%THEME_SWITCH_JS%
</script>
<script>
(function () {
  __LANG_JS__
})();
</script>
</body>
</html>
"""

# Token set copied verbatim from club_division_map.py — see the note by this
# module's imports for why (visual parity with the pages this cross-links to,
# not site_theme.CSS which only index.html uses).
PAGE_CSS = r"""
:root{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --row-hover:#f4f7f2; --teal:#1a6b7a; --teal-soft:#d8eef1; --pos-red:#a03327; --pos-red-soft:#f5ddd6;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
    --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
    --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
    --row-hover:#1c2619; --teal:#5fc3d6; --teal-soft:#12313a; --pos-red:#e2685a; --pos-red-soft:#33201d;
  }
}
:root[data-theme="dark"]{
  --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
  --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
  --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
  --row-hover:#1c2619; --teal:#5fc3d6; --teal-soft:#12313a; --pos-red:#e2685a; --pos-red-soft:#33201d;
}
:root[data-theme="light"]{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --row-hover:#f4f7f2; --teal:#1a6b7a; --teal-soft:#d8eef1; --pos-red:#a03327; --pos-red-soft:#f5ddd6;
}
*{box-sizing:border-box;}
html,body{margin:0; height:100%;}
body{ background:var(--bg); color:var(--ink); font-family:'PT Sans', ui-sans-serif, "Helvetica Neue", Arial, sans-serif;
  line-height:1.5; -webkit-font-smoothing:antialiased; }
a{ color:var(--accent); text-decoration:none; }
a:hover{ text-decoration:underline; }
code{ font-family: ui-monospace, monospace; font-size:0.86em; background:var(--accent-soft); padding:0.05em 0.35em; border-radius:3px; }

.page{ max-width:1400px; margin:0 auto; padding:2.25rem 1.25rem 4rem; display:flex; flex-direction:column; gap:1.5rem; }
.page.full{ max-width:none; padding-left:clamp(1.25rem,3vw,3rem); padding-right:clamp(1.25rem,3vw,3rem); }
h1{ font-family:'Oswald', ui-sans-serif, "Arial Narrow", "Helvetica Neue", Arial, sans-serif; font-weight:700;
  text-transform:uppercase; letter-spacing:0.01em; text-wrap:balance; margin:0; color:var(--ink); font-size:clamp(1.4rem,2.8vw,1.9rem); line-height:1.2; }
h2{ font-family:'Oswald', ui-sans-serif, sans-serif; font-weight:700; text-transform:uppercase; font-size:1.05rem; margin:0; color:var(--ink); }
header.masthead{ display:flex; flex-direction:column; gap:0.4rem; border-bottom:3px solid var(--ink); padding-bottom:1rem; position:relative; }
.eyebrow{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:var(--accent); }
header.masthead p{ margin:0; color:var(--ink-soft); font-size:0.95rem; max-width:75ch; }
a.back{ font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:var(--accent); }
.masthead .switch-row, header.masthead > .switch-row{ position:absolute; top:0; right:0; display:flex; gap:0.5rem; }
.lang-switch, .theme-switch{ display:inline-flex; border:1px solid var(--line-strong); border-radius:999px; overflow:hidden; }
.lang-opt, .theme-opt{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:0.04em;
  padding:4px 12px; background:var(--surface); color:var(--ink-soft); border:none; cursor:pointer; }
.lang-opt.is-active, .theme-opt.is-active{ background:var(--accent); color:#fff; }
.theme-opt{ font-size:13px; padding:3px 10px; }

/* ── club picker (search-as-you-type combobox) ── */
.pick-wrap{ position:relative; }
.search{ display:flex; align-items:center; gap:0.5rem; border:1px solid var(--line-strong);
  border-radius:6px; padding:0.55rem 0.75rem; background:var(--surface); box-shadow:var(--shadow); }
.search svg{ flex:none; opacity:0.55; }
.search input{ border:none; background:transparent; outline:none; color:var(--ink); font-size:1rem; width:100%; font-family:inherit; }
.search input::placeholder{ color:var(--ink-faint); }
.pick-pop{ position:absolute; top:calc(100% + 4px); left:0; right:0; background:var(--surface);
  border:1px solid var(--line-strong); border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,0.18);
  max-height:22rem; overflow:auto; z-index:40; display:none; }
.pick-pop.open{ display:block; }
.pick-opt{ padding:0.5rem 0.8rem; cursor:pointer; display:flex; justify-content:space-between; gap:0.6rem; align-items:baseline; border-bottom:1px solid var(--line); }
.pick-opt:last-child{ border-bottom:none; }
.pick-opt:hover, .pick-opt.hi{ background:var(--accent-soft); }
.pick-opt .nm{ font-weight:700; color:var(--ink); }
.pick-opt .meta{ font-size:0.76rem; color:var(--ink-faint); white-space:nowrap; font-family:'JetBrains Mono',monospace; }
.pick-empty{ padding:0.7rem 0.8rem; color:var(--ink-faint); font-size:0.85rem; }
p.foot{ color:var(--ink-faint); font-size:0.8rem; margin:-0.9rem 0 0; }

/* ── selected-club header ── */
.club-head{ display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:0.8rem;
  background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:1rem 1.3rem; box-shadow:var(--shadow); }
.club-head .nm{ font-family:'Oswald',sans-serif; font-weight:700; text-transform:uppercase; font-size:clamp(1.1rem,2.2vw,1.5rem); }
.club-head .sub{ font-size:0.82rem; color:var(--ink-soft); margin-top:0.2rem; }
.club-head .count{ font-family:'JetBrains Mono',monospace; font-size:0.85rem; color:var(--accent); font-weight:700; white-space:nowrap; }
.club-head .mode-toggle{ display:flex; gap:0.3rem; }

/* ── filter panel (reuses club_division_map.py's filter-row/chip language) ── */
.filter-panel{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:0.9rem 1.1rem; box-shadow:var(--shadow); display:flex; flex-direction:column; gap:0.7rem; }
.filter-row{ display:flex; align-items:flex-start; gap:0.9rem; flex-wrap:wrap; }
.filter-label{ font-size:0.74rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:var(--ink-soft);
  white-space:nowrap; padding-top:0.5rem; min-width:82px; }
.msel{ position:relative; }
.msel-btn{ font-family:inherit; font-size:0.84rem; font-weight:600; color:var(--ink); background:var(--bg);
  border:1px solid var(--line-strong); border-radius:6px; padding:0.4rem 0.7rem; cursor:pointer; display:inline-flex; align-items:center; gap:0.4rem; }
.msel-btn:hover{ border-color:var(--accent); }
.msel-btn .n{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:var(--accent); background:var(--accent-soft); border-radius:999px; padding:0.05rem 0.4rem; }
.msel-pop{ position:absolute; top:calc(100% + 4px); left:0; z-index:30; background:var(--surface);
  border:1px solid var(--line-strong); border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,0.2); padding:0.6rem; width:16rem; display:none; }
.msel-pop.open{ display:block; }
.msel-presets{ display:flex; flex-wrap:wrap; gap:0.3rem; margin-bottom:0.5rem; }
.msel-presets button{ font-size:0.7rem; padding:0.18rem 0.5rem; border:1px solid var(--line-strong); border-radius:4px;
  background:var(--bg); color:var(--ink-soft); cursor:pointer; }
.msel-presets button:hover{ background:var(--accent-soft); color:var(--ink); }
.msel-list{ max-height:14rem; overflow:auto; display:flex; flex-direction:column; gap:0.15rem; }
.msel-item{ display:flex; align-items:center; gap:0.45rem; padding:0.2rem 0.15rem; cursor:pointer; font-size:0.84rem; border-radius:4px; }
.msel-item:hover{ background:var(--row-hover); }
.msel-item input{ margin:0; }
.chiprow{ display:flex; flex-wrap:wrap; gap:0.4rem; align-items:center; }
.chip{ display:inline-flex; align-items:center; gap:0.3rem; padding:0.26rem 0.6rem; border-radius:999px; font-size:0.78rem;
  border:1.5px solid var(--line-strong); background:var(--bg); color:var(--ink-soft); }
.chip.accent{ background:var(--accent-soft); border-color:var(--accent); color:var(--ink); }
.chip button{ border:none; background:none; cursor:pointer; color:inherit; font-size:0.85em; padding:0; line-height:1; opacity:0.7; }
.chip button:hover{ opacity:1; }
.chip-reset{ font-size:0.76rem; padding:0.24rem 0.6rem; border:1px solid var(--line-strong); border-radius:999px;
  background:var(--bg); color:var(--ink-soft); cursor:pointer; }
.chip-reset:hover{ color:var(--pos-red); border-color:var(--pos-red); }

/* ── sections ── */
section{ display:flex; flex-direction:column; gap:0.8rem; }
.section-head{ display:flex; align-items:center; gap:1rem; flex-wrap:wrap; border-bottom:1px solid var(--line); padding-bottom:0.6rem; }
.seg{ display:inline-flex; border:1px solid var(--line-strong); border-radius:999px; overflow:hidden; }
.seg-opt{ font-family:inherit; font-size:0.78rem; font-weight:700; padding:0.32rem 0.8rem; border:none; background:var(--surface); color:var(--ink-soft); cursor:pointer; }
.seg-opt.is-active{ background:var(--accent); color:#fff; }
.path-search{ margin-left:auto; font-family:inherit; font-size:0.85rem; border:1px solid var(--line-strong); border-radius:6px;
  padding:0.35rem 0.6rem; background:var(--bg); color:var(--ink); min-width:14rem; }
.chart-wrap{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:1rem 1.1rem 1.3rem; box-shadow:var(--shadow); }
.scope-note{ display:flex; gap:0.6rem; align-items:flex-start; background:var(--accent-soft); border-left:4px solid var(--accent);
  border-radius:4px; padding:0.6rem 0.9rem; margin:0; font-size:0.82rem; color:var(--ink-soft); }
.scope-note .mark{ font-family:'JetBrains Mono',monospace; font-weight:700; color:var(--accent); flex:none; }

.stats{ display:flex; flex-wrap:wrap; gap:0.75rem; }
.stat{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:0.7rem 1rem;
  box-shadow:var(--shadow); min-width:9rem; display:flex; flex-direction:column; gap:0.15rem; }
.stat .n{ font-family:ui-monospace,monospace; font-size:1.35rem; font-weight:700; font-variant-numeric:tabular-nums; color:var(--ink); }
.stat .l{ font-size:0.72rem; color:var(--ink-soft); letter-spacing:0.03em; }

.flow-stats{ display:flex; flex-wrap:wrap; gap:0.6rem; font-size:0.82rem; color:var(--ink-soft); }
.flow-stats .fs-item{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:0.4rem 0.8rem; display:flex; gap:0.4rem; align-items:baseline; }
.flow-stats .fs-item b{ font-family:ui-monospace,monospace; color:var(--accent); font-size:1rem; }

.table-shell{ background:var(--surface); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); overflow:hidden; }
.table-scroll{ overflow:auto; max-height:26rem; }
table{ border-collapse:separate; border-spacing:0; font-size:0.86rem; width:100%; }
thead th{ background:var(--surface); position:sticky; top:0; z-index:2; border-bottom:1px solid var(--line-strong);
  padding:0.5rem 0.7rem; text-align:left; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--ink-soft); }
th.num, td.num{ text-align:right; font-variant-numeric:tabular-nums; }
tbody td{ border-bottom:1px solid var(--line); padding:0.4rem 0.7rem; vertical-align:middle; }
tbody tr:hover td{ background:var(--row-hover); }
tbody tr{ cursor:pointer; }

/* ── player modal ── */
.modal-backdrop{ position:fixed; inset:0; background:rgba(10,15,10,0.55); display:flex; align-items:center; justify-content:center; padding:1.5rem; z-index:50; }
.modal-backdrop.hidden{ display:none; }
.modal{ background:var(--surface); border-radius:10px; max-width:700px; width:100%; max-height:85vh; overflow:auto; padding:1.5rem; position:relative; box-shadow:var(--shadow); }
.modal-close{ position:absolute; top:0.7rem; right:0.7rem; background:none; border:none; font-size:1.6rem; line-height:1; cursor:pointer; color:var(--ink-soft); padding:0.2rem 0.5rem; }
.modal-close:hover{ color:var(--ink); }
.modal h3{ font-family:'Oswald',sans-serif; text-transform:uppercase; font-weight:700; margin:0 0 0.2rem; padding-right:2rem; }
.modal .modal-sub{ color:var(--ink-soft); font-size:0.85rem; margin-bottom:0.9rem; }
.modal .badge{ display:inline-block; background:var(--accent-soft); color:var(--ink); border-radius:6px; padding:0.5rem 0.8rem; font-size:0.85rem; margin-bottom:1rem; }

.status-dot{ display:inline-block; width:0.7rem; height:0.7rem; border-radius:50%; margin-right:0.3rem; }
.status-in{ color:var(--accent); } .status-in .status-dot{ background:var(--accent); }
.status-new{ color:var(--gold); } .status-new .status-dot{ background:var(--gold); }
.status-left{ color:var(--pos-red); } .status-left .status-dot{ background:var(--pos-red); }

@media (max-width: 720px){
  header.masthead > .switch-row{ position:static; margin-bottom:0.5rem; }
  .filter-row{ flex-direction:column; }
  .path-search{ margin-left:0; width:100%; }
}
"""

PAGE_JS = r"""
(function () {
'use strict';

let CLUB_INDEX = [];
let CLUB = null;          // current club payload (see club_profile_data.club_payload())
let SELF = null;          // CLUB.self — which "clubs" entry IS the target club
let filters = { seasons: null, cats: null, teams: null };  // null = "all"
let direction = 'in';     // 'in' = donors, 'out' = destinations
let flowView = 'sankey';
let pathHighlight = '';

const YEARS = ALL_SEASONS.map(s => parseInt(s.slice(0, 4), 10));
const MIN_YEAR = Math.min.apply(null, YEARS);
const MAX_YEAR = Math.max.apply(null, YEARS);

function seasonLabel(y) { return y + '-' + (y + 1); }
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function isEs() { return document.documentElement.lang === 'es'; }
function stripTags(html) { const d = document.createElement('div'); d.innerHTML = html; return d.textContent; }
function T(key, fallbackRu) { return (isEs() && I18N_ES[key]) ? stripTags(I18N_ES[key]) : fallbackRu; }
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function plotlyBase() {
  return {
    paper_bgcolor: cssVar('--surface'), plot_bgcolor: cssVar('--surface'),
    font: { family: "'PT Sans', sans-serif", color: cssVar('--ink'), size: 12 },
    margin: { t: 24, r: 24, b: 44, l: 56 },
  };
}

/* ============================= club picker ============================= */

async function init() {
  const res = await fetch('data/club_profile_index.json');
  CLUB_INDEX = await res.json();
  wireSearch();
  wireStaticControls();
  const params = new URLSearchParams(location.search);
  const slug = params.get('club');
  const name = params.get('clubname');
  // clubname is what cross-links from club_division_map.html/team_card.html/
  // player_card.html pass — those pages compute their OWN club_slug_map()
  // over their own (per-season) club universe, which is not guaranteed to
  // assign the same collision-numbered slug as this page's (career-wide)
  // index, so a name match here is more reliable than trusting their slug.
  let entry = slug ? CLUB_INDEX.find(c => c.slug === slug) : null;
  if (!entry && name) {
    entry = CLUB_INDEX.find(c => c.display === name) ||
      CLUB_INDEX.find(c => c.display.toLowerCase() === name.toLowerCase());
  }
  if (entry) selectClub(entry);
}

function wireSearch() {
  const input = document.getElementById('clubSearch');
  const pop = document.getElementById('clubSearchPop');
  let hiIndex = -1, results = [];

  function renderResults(q) {
    const ql = q.trim().toLowerCase();
    results = ql.length < 2 ? [] : CLUB_INDEX.filter(c => c.display.toLowerCase().includes(ql)).slice(0, 25);
    hiIndex = -1;
    if (!ql) { pop.classList.remove('open'); pop.innerHTML = ''; return; }
    if (!results.length) {
      pop.innerHTML = '<div class="pick-empty">' + (isEs() ? 'Sin resultados' : 'Ничего не найдено') + '</div>';
      pop.classList.add('open');
      return;
    }
    pop.innerHTML = results.map((c, i) => (
      '<div class="pick-opt" data-i="' + i + '"><span class="nm">' + esc(c.display) + '</span>' +
      '<span class="meta">' + c.total_players + ' · ' + c.seasons_active[0] + '–' + c.seasons_active[c.seasons_active.length - 1] + '</span></div>'
    )).join('');
    pop.classList.add('open');
    pop.querySelectorAll('.pick-opt').forEach(el => {
      el.addEventListener('click', () => { selectClub(results[+el.dataset.i]); pop.classList.remove('open'); input.value = ''; });
    });
  }

  input.addEventListener('input', () => renderResults(input.value));
  input.addEventListener('focus', () => { if (input.value.trim().length >= 2) renderResults(input.value); });
  input.addEventListener('keydown', (e) => {
    const items = Array.from(pop.querySelectorAll('.pick-opt'));
    if (!items.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); hiIndex = Math.min(hiIndex + 1, items.length - 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); hiIndex = Math.max(hiIndex - 1, 0); }
    else if (e.key === 'Enter') { e.preventDefault(); if (hiIndex >= 0) items[hiIndex].click(); return; }
    else return;
    items.forEach((el, i) => el.classList.toggle('hi', i === hiIndex));
    items[hiIndex].scrollIntoView({ block: 'nearest' });
  });
  document.addEventListener('click', (e) => {
    if (!document.getElementById('clubSearchBox').contains(e.target)) pop.classList.remove('open');
  });
}

async function selectClub(entry) {
  document.getElementById('pickHint').style.display = 'none';
  document.getElementById('app').style.display = '';
  document.getElementById('clubHead').innerHTML = '<div class="sub">' + (isEs() ? 'Cargando…' : 'Загрузка…') + '</div>';

  const url = new URL(location.href);
  url.searchParams.set('club', entry.slug);
  history.replaceState(null, '', url);

  const res = await fetch('data/club_profile/' + entry.slug + '.json');
  CLUB = await res.json();
  SELF = CLUB.self;
  filters = { seasons: null, cats: null, teams: null };
  direction = 'in'; flowView = 'sankey'; pathHighlight = '';
  document.getElementById('pathSearch').value = '';
  document.querySelectorAll('#dirToggle .seg-opt').forEach(b => b.classList.toggle('is-active', b.dataset.dir === 'in'));
  document.querySelectorAll('#flowViewToggle .seg-opt').forEach(b => b.classList.toggle('is-active', b.dataset.view === 'sankey'));

  renderClubHead();
  renderFilterBar();
  renderChips();
  renderAll();
}

/* ============================= club header ============================= */

function renderClubHead() {
  const el = document.getElementById('clubHead');
  el.innerHTML =
    '<div><div class="nm">' + esc(CLUB.display) + '</div>' +
    '<div class="sub">' + CLUB.seasons_active[0] + '–' + CLUB.seasons_active[CLUB.seasons_active.length - 1] +
    ' · ' + Object.keys(CLUB.players).length + ' ' + T('count_players', 'игроков за всё время') + '</div></div>' +
    '<div class="count" id="clubHeadCount"></div>';
}

function updateHeadCount(roster) {
  const clubsTouched = new Set();
  roster.forEach(p => p.allRows.forEach(r => clubsTouched.add(r.ck)));
  document.getElementById('clubHeadCount').textContent =
    roster.length + ' ' + T('count_players', 'игроков') + ' · ' +
    clubsTouched.size + ' ' + T('count_clubs', 'клубов в этом срезе');
}

/* ============================= filter bar ============================= */

function ownRowsAll() {
  const rows = [];
  Object.values(CLUB.players).forEach(p => p.rows.forEach(r => { if (r.ck === SELF) rows.push(r); }));
  return rows;
}
function availableSeasons() {
  return CLUB.seasons_active.map(s => parseInt(s.slice(0, 4), 10)).sort((a, b) => a - b);
}
function availableCats(seasonsSet) {
  const set = new Set();
  ownRowsAll().forEach(r => { if (!seasonsSet || seasonsSet.has(r.y)) set.add(r.cat); });
  return CAT_ORDER.filter(c => set.has(c));
}
function availableTeams(seasonsSet, catsSet) {
  const map = new Map();
  ownRowsAll().forEach(r => {
    if (seasonsSet && !seasonsSet.has(r.y)) return;
    if (catsSet && !catsSet.has(r.cat)) return;
    if (!map.has(r.t)) map.set(r.t, CLUB.teams[r.t] || r.t);
  });
  return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1], 'ru'));
}
function optionsFor(key) {
  if (key === 'seasons') return availableSeasons().map(y => ({ value: y, label: seasonLabel(y) }));
  if (key === 'cats') return availableCats(filters.seasons).map(c => ({ value: c, label: CAT_LABEL[c] || c }));
  if (key === 'teams') return availableTeams(filters.seasons, filters.cats).map(([id, label]) => ({ value: id, label }));
}
function groupLabel(key) {
  if (key === 'seasons') return T('scope_seasons', 'Сезоны');
  if (key === 'cats') return T('scope_cats', 'Категории');
  return T('scope_teams', 'Команды');
}

function renderFilterBar() {
  const bar = document.getElementById('filterbar');
  bar.className = 'filter-row';
  bar.innerHTML = ['seasons', 'cats', 'teams'].map(key => (
    '<div class="msel" id="msel-' + key + '"><span class="filter-label">' + groupLabel(key) + '</span>' +
    '<button type="button" class="msel-btn" id="mselBtn-' + key + '"></button>' +
    '<div class="msel-pop" id="mselPop-' + key + '"></div></div>'
  )).join('');
  ['seasons', 'cats', 'teams'].forEach(wireFilterGroup);
}

function renderMselButton(key) {
  const btn = document.getElementById('mselBtn-' + key);
  if (!btn) return;
  const all = optionsFor(key);
  const sel = filters[key];
  if (!sel) btn.textContent = T('preset_all', 'Все') + ' (' + all.length + ')';
  else btn.textContent = all.filter(o => sel.has(o.value)).length + ' / ' + all.length;
}

function wireFilterGroup(key) {
  const btn = document.getElementById('mselBtn-' + key);
  const pop = document.getElementById('mselPop-' + key);
  renderMselButton(key);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const wasOpen = pop.classList.contains('open');
    closeAllMsel();
    if (!wasOpen) openMselPopover(key, pop);
  });
  pop.addEventListener('click', (e) => e.stopPropagation());
}
function closeAllMsel() { document.querySelectorAll('.msel-pop.open').forEach(p => p.classList.remove('open')); }
document.addEventListener('click', closeAllMsel);

function openMselPopover(key, pop) {
  const all = optionsFor(key);
  const sel = filters[key];
  const isChecked = (v) => !sel || sel.has(v);
  const presets = key === 'seasons'
    ? [['all', T('preset_all', 'Все')], ['last3', T('preset_last3', 'Последние 3')], ['current', T('preset_current', 'Текущий сезон')]]
    : [['all', T('preset_all', 'Все')], ['none', T('preset_none', 'Ни одной')]];

  pop.innerHTML =
    '<div class="msel-presets">' + presets.map(([p, l]) => '<button type="button" data-preset="' + p + '">' + esc(l) + '</button>').join('') + '</div>' +
    '<div class="msel-list">' + all.map(o => (
      '<label class="msel-item"><input type="checkbox" data-v="' + esc(String(o.value)) + '" ' + (isChecked(o.value) ? 'checked' : '') + '><span>' + esc(o.label) + '</span></label>'
    )).join('') + '</div>';
  pop.classList.add('open');

  pop.querySelectorAll('input[type=checkbox]').forEach(cb => {
    cb.addEventListener('change', () => {
      const current = new Set(filters[key] ? [...filters[key]] : all.map(o => o.value));
      const val = key === 'seasons' ? +cb.dataset.v : cb.dataset.v;
      if (cb.checked) current.add(val); else current.delete(val);
      filters[key] = (current.size === all.length) ? null : current;
      onFilterChanged();
    });
  });
  pop.querySelectorAll('button[data-preset]').forEach(b => {
    b.addEventListener('click', () => {
      const p = b.dataset.preset;
      if (p === 'all') filters[key] = null;
      else if (p === 'none') filters[key] = new Set();
      else if (p === 'last3') { const ys = availableSeasons(); filters.seasons = new Set(ys.slice(-3)); }
      else if (p === 'current') { const ys = availableSeasons(); filters.seasons = new Set([ys[ys.length - 1]]); }
      onFilterChanged();
      openMselPopover(key, pop);
    });
  });
}

function onFilterChanged() {
  const catsNow = new Set(optionsFor('cats').map(o => o.value));
  if (filters.cats) filters.cats = new Set([...filters.cats].filter(v => catsNow.has(v)));
  const teamsNow = new Set(optionsFor('teams').map(o => o.value));
  if (filters.teams) filters.teams = new Set([...filters.teams].filter(v => teamsNow.has(v)));
  renderMselButton('seasons'); renderMselButton('cats'); renderMselButton('teams');
  renderChips();
  renderAll();
}

function renderChips() {
  const row = document.getElementById('chiprow');
  const chips = [];
  ['seasons', 'cats', 'teams'].forEach(key => {
    const sel = filters[key];
    if (!sel) return;
    const all = optionsFor(key);
    const labels = all.filter(o => sel.has(o.value)).map(o => o.label);
    chips.push('<span class="chip accent">' + groupLabel(key) + ': ' + (labels.length ? esc(labels.join(', ')) : (isEs() ? 'ninguno' : 'ничего')) + '</span>');
  });
  if (!chips.length) { row.innerHTML = ''; return; }
  row.innerHTML = chips.join('') + '<button type="button" class="chip-reset" id="chipReset">' + T('chips_reset', 'Сбросить фильтры') + '</button>';
  document.getElementById('chipReset').addEventListener('click', () => {
    filters = { seasons: null, cats: null, teams: null };
    renderMselButton('seasons'); renderMselButton('cats'); renderMselButton('teams');
    renderChips(); renderAll();
  });
}

/* ============================= roster + donor/destination ============================= */

function isRowInScope(r) {
  if (r.ck !== SELF) return false;
  if (filters.seasons && !filters.seasons.has(r.y)) return false;
  if (filters.cats && !filters.cats.has(r.cat)) return false;
  if (filters.teams && !filters.teams.has(r.t)) return false;
  return true;
}

function computeRoster() {
  const roster = [];
  for (const pid in CLUB.players) {
    const p = CLUB.players[pid];
    const inScope = p.rows.filter(isRowInScope);
    if (!inScope.length) continue;
    roster.push({ pid, name: p.name, birth_year: p.birth_year, rowsInScope: inScope, allRows: p.rows });
  }
  return roster;
}

function playerSeasonMap(rows) {
  const m = new Map();
  rows.forEach(r => { if (!m.has(r.y)) m.set(r.y, new Set()); m.get(r.y).add(r.ck); });
  return m;
}

// A club change is only ever reported when the player has a confirmed
// registration row in TWO CALENDAR-ADJACENT seasons (this year at the target,
// the other year at a different club) — see club_profile_data.py's module
// docstring. A gap year with no data before a new club appears is surfaced
// as "gap" (previous club unknown), never resolved into a guess.
function findDonor(allRows, y0) {
  const m = playerSeasonMap(allRows);
  const years = [...m.keys()].sort((a, b) => a - b);
  if (years[0] === y0) return { type: 'homegrown' };
  const idx = years.indexOf(y0);
  const prevYear = years[idx - 1];
  if (prevYear === y0 - 1) {
    const prevClubs = [...m.get(prevYear)].filter(ck => ck !== SELF);
    if (prevClubs.length) return { type: 'transfer', from: prevClubs[0] };
    return { type: 'continuing' };
  }
  return { type: 'gap' };
}
function findDestination(allRows, yLast) {
  if (yLast >= MAX_YEAR) return { type: 'active' };
  const m = playerSeasonMap(allRows);
  const years = [...m.keys()].sort((a, b) => a - b);
  const idx = years.indexOf(yLast);
  const nextYear = years[idx + 1];
  if (nextYear === yLast + 1) {
    const nextClubs = [...m.get(nextYear)].filter(ck => ck !== SELF);
    if (nextClubs.length) return { type: 'left', to: nextClubs[0] };
    return { type: 'continuing' };
  }
  return { type: 'not_found' };
}

function computeFlows(roster, dir) {
  const edges = new Map();
  let homegrown = 0, gap = 0, activeCont = 0, notFound = 0;
  roster.forEach(p => {
    const ys = p.rowsInScope.map(r => r.y);
    if (dir === 'in') {
      const y0 = Math.min.apply(null, ys);
      const res = findDonor(p.allRows, y0);
      if (res.type === 'homegrown') homegrown++;
      else if (res.type === 'transfer') {
        const e = edges.get(res.from) || { count: 0, players: [] };
        e.count++; e.players.push({ pid: p.pid, name: p.name, season: seasonLabel(y0) });
        edges.set(res.from, e);
      } else if (res.type === 'gap') gap++;
      else activeCont++;
    } else {
      const yL = Math.max.apply(null, ys);
      const res = findDestination(p.allRows, yL);
      if (res.type === 'active' || res.type === 'continuing') activeCont++;
      else if (res.type === 'left') {
        const e = edges.get(res.to) || { count: 0, players: [] };
        e.count++; e.players.push({ pid: p.pid, name: p.name, season: seasonLabel(yL + 1) });
        edges.set(res.to, e);
      } else if (res.type === 'not_found') notFound++;
    }
  });
  return { edges, homegrown, gap, activeCont, notFound, total: roster.length };
}

/* ============================= Block 1: flow ============================= */

function fsItem(n, label) { return '<span class="fs-item"><b>' + n + '</b>' + esc(label) + '</span>'; }

function renderFlow(roster) {
  const flow = computeFlows(roster, direction);
  const items = direction === 'in'
    ? [fsItem(flow.homegrown, T('homegrown_lbl', 'Своя школа (в клубе с самого начала)')),
       fsItem(flow.gap, T('gap_lbl', 'Пришёл после разрыва в данных (клуб неизвестен)'))]
    : [fsItem(flow.activeCont, T('active_lbl', 'Остаётся в клубе')),
       fsItem(flow.notFound, T('notfound_lbl', 'Нет данных дальше (не обязательно уход)'))];
  document.getElementById('flowStats').innerHTML = items.join('');

  const sorted = [...flow.edges.entries()].sort((a, b) => b[1].count - a[1].count);
  document.getElementById('sankeyDiv').parentElement.style.display = flowView === 'sankey' ? '' : 'none';
  document.getElementById('rankWrap').style.display = flowView === 'rank' ? '' : 'none';
  if (flowView === 'sankey') renderSankey(sorted); else renderRank(sorted, flow.total);
}

function renderSankey(sorted) {
  const el = document.getElementById('sankeyDiv');
  const emptyMsg = document.getElementById('sankeyEmptyMsg');
  if (!sorted.length) {
    // Plotly.purge() clears the plot's own traces/SVG but leaves its
    // 'js-plotly-plot' marker class on the div permanently — so the "no
    // transfers" message lives in its OWN sibling element, never written
    // into el.innerHTML directly. Plotly.react() only ever appends/updates
    // its own nodes in el and never clears unrelated siblings, so writing
    // the message inside el would leave it stranded next to the chart on
    // the very next non-empty render.
    Plotly.purge(el);
    el.style.display = 'none';
    emptyMsg.textContent = T('flow_empty', 'Нет переходов игроков в этом срезе.');
    emptyMsg.style.display = '';
    return;
  }
  emptyMsg.style.display = 'none';
  el.style.display = '';
  const TOP_N = 12;
  const top = sorted.slice(0, TOP_N), rest = sorted.slice(TOP_N);
  const restCount = rest.reduce((s, [, v]) => s + v.count, 0);

  const labels = [CLUB.display];
  const clubIx = {};
  top.forEach(([ck]) => { clubIx[ck] = labels.length; labels.push(CLUB.clubs[ck] || ck); });
  let otherIx = -1;
  if (restCount > 0) { otherIx = labels.length; labels.push((isEs() ? 'Otros (' : 'Другие (') + rest.length + ')'); }

  const source = [], target = [], value = [], linkPlayers = [];
  top.forEach(([ck, v]) => {
    if (direction === 'in') { source.push(clubIx[ck]); target.push(0); } else { source.push(0); target.push(clubIx[ck]); }
    value.push(v.count); linkPlayers.push(v.players);
  });
  if (restCount > 0) {
    if (direction === 'in') { source.push(otherIx); target.push(0); } else { source.push(0); target.push(otherIx); }
    value.push(restCount); linkPlayers.push(rest.flatMap(([, v]) => v.players));
  }
  const nodeColors = labels.map((_, i) => i === 0 ? cssVar('--accent') : cssVar('--teal'));

  Plotly.react(el, [{
    type: 'sankey', orientation: 'h',
    node: { label: labels, pad: 14, thickness: 16, color: nodeColors, line: { color: cssVar('--line-strong'), width: 0.5 } },
    link: { source, target, value, color: cssVar('--accent-soft') },
  }], Object.assign(plotlyBase(), { height: 460, margin: { t: 24, r: 170, b: 20, l: 170 } }), { responsive: true, displayModeBar: false })
    .then(() => {
      el.removeAllListeners && el.removeAllListeners('plotly_click');
      el.on('plotly_click', (d) => {
        const pt = d.points[0];
        if (pt && pt.pointNumber !== undefined && linkPlayers[pt.pointNumber]) {
          openPlayersListModal(pt.label || (CLUB.clubs[top[pt.pointNumber] ? top[pt.pointNumber][0] : ''] || ''), linkPlayers[pt.pointNumber]);
        }
      });
    });
}

function renderRank(sorted, total) {
  const body = document.getElementById('rankBody');
  if (!sorted.length) {
    body.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--ink-faint)">' + T('flow_empty', 'Нет переходов.') + '</td></tr>';
    return;
  }
  body.innerHTML = sorted.map(([ck, v]) => (
    '<tr data-ck="' + esc(ck) + '"><td>' + esc(CLUB.clubs[ck] || ck) + '</td><td class="num">' + v.count + '</td><td class="num">' + (v.count / total * 100).toFixed(1) + '%</td></tr>'
  )).join('');
  body.querySelectorAll('tr').forEach(tr => {
    tr.addEventListener('click', () => {
      const entry = sorted.find(([c]) => c === tr.dataset.ck);
      if (entry) openPlayersListModal(CLUB.clubs[entry[0]] || entry[0], entry[1].players);
    });
  });
}

/* ============================= Block 2: roster ============================= */

function stat(n, l) { return '<div class="stat"><div class="n">' + n + '</div><div class="l">' + esc(l) + '</div></div>'; }

function renderRoster(roster) {
  const byCat = new Set(); roster.forEach(p => p.rowsInScope.forEach(r => byCat.add(r.cat)));
  const teamSet = new Set(); roster.forEach(p => p.rowsInScope.forEach(r => teamSet.add(r.t)));

  let stabilityPct = 0;
  if (roster.length) {
    const maxYear = Math.max.apply(null, roster.flatMap(p => p.rowsInScope.map(r => r.y)));
    const atMax = roster.filter(p => p.rowsInScope.some(r => r.y === maxYear));
    const returning = atMax.filter(p => p.allRows.some(r => r.ck === SELF && r.y < maxYear));
    stabilityPct = atMax.length ? Math.round(returning.length / atMax.length * 100) : 0;
  }

  document.getElementById('statStrip').innerHTML = [
    stat(roster.length, T('kpi_total', 'Игроков')),
    stat(teamSet.size, T('kpi_clubs_teams', 'Команд')),
    stat(byCat.size, T('kpi_cats', 'Категорий')),
    stat(stabilityPct + '%', T('kpi_stability', 'Стабильность состава (вернулись с прошлого сезона)')),
  ].join('');

  renderHeatmap(roster);
}

function renderHeatmap(roster) {
  const el = document.getElementById('heatmapDiv');
  const catsPresent = CAT_ORDER.filter(c => roster.some(p => p.rowsInScope.some(r => r.cat === c)));
  const teamIds = [...new Set(roster.flatMap(p => p.rowsInScope.map(r => r.t)))]
    .sort((a, b) => (CLUB.teams[a] || a).localeCompare(CLUB.teams[b] || b, 'ru'));
  if (!catsPresent.length || !teamIds.length) { Plotly.purge(el); el.innerHTML = ''; return; }

  const z = catsPresent.map(cat => teamIds.map(t => {
    const set = new Set();
    roster.forEach(p => { if (p.rowsInScope.some(r => r.cat === cat && r.t === t)) set.add(p.pid); });
    return set.size || null;
  }));
  const teamLabels = teamIds.map(t => CLUB.teams[t] || t);
  const catLabels = catsPresent.map(c => CAT_LABEL[c] || c);

  Plotly.react(el, [{
    type: 'heatmap', x: teamLabels, y: catLabels, z,
    colorscale: [[0, cssVar('--surface')], [1, cssVar('--accent')]], showscale: false, xgap: 2, ygap: 2,
    text: z.map(row => row.map(v => v || '')), texttemplate: '%{text}', textfont: { color: cssVar('--ink') },
    hovertemplate: '%{y} / %{x}: %{z}<extra></extra>',
  }], Object.assign(plotlyBase(), {
    height: Math.max(280, catsPresent.length * 46 + 90),
    xaxis: { tickangle: -35, tickfont: { size: 10 }, automargin: true }, yaxis: { autorange: 'reversed', automargin: true },
  }), { responsive: true, displayModeBar: false });
}

/* ============================= Block 3: paths ============================= */

function catIndex(cat) { const i = CAT_ORDER.indexOf(cat); return i === -1 ? CAT_ORDER.length : i; }
function yPos(cat, div) {
  const tier = CODE_TIER[div];
  const offset = (tier === null || tier === undefined) ? 4 : (8 - Math.min(tier, 8));
  return catIndex(cat) * 10 + offset;
}
function playerStatus(p, maxYearInScope) {
  const y0 = Math.min.apply(null, p.rowsInScope.map(r => r.y));
  if (y0 === maxYearInScope) return 'new';
  const yL = Math.max.apply(null, p.rowsInScope.map(r => r.y));
  const dest = findDestination(p.allRows, yL);
  return (dest.type === 'active' || dest.type === 'continuing') ? 'in' : 'left';
}

function renderPaths(roster) {
  const el = document.getElementById('pathsDiv');
  const note = document.getElementById('pathsCapNote');
  if (!roster.length) { Plotly.purge(el); el.innerHTML = ''; note.textContent = ''; return; }
  const maxYearInScope = Math.max.apply(null, roster.flatMap(p => p.rowsInScope.map(r => r.y)));

  const CAP = 60;
  let show = roster;
  if (roster.length > CAP) {
    show = [...roster].sort((a, b) => b.allRows.length - a.allRows.length).slice(0, CAP);
    note.textContent = isEs()
      ? 'Mostrando ' + CAP + ' de ' + roster.length + ' jugadores (los de trayectoria mas larga) - usa los filtros para acotar.'
      : 'Показано ' + CAP + ' из ' + roster.length + ' игроков (с самой длинной историей) — сузьте фильтры, чтобы увидеть остальных.';
  } else {
    note.textContent = '';
  }

  const statusColor = { in: cssVar('--accent'), new: cssVar('--gold'), left: cssVar('--pos-red') };
  const traces = show.map(p => {
    const rows = [...p.allRows].sort((a, b) => a.y - b.y);
    const status = playerStatus(p, maxYearInScope);
    return {
      type: 'scatter', mode: 'lines+markers',
      x: rows.map(r => r.y), y: rows.map(r => yPos(r.cat, r.div)),
      text: rows.map(r => p.name + '<br>' + seasonLabel(r.y) + ' · ' + (CLUB.clubs[r.ck] || r.ck) + ' (' + (CLUB.teams[r.t] || r.t) + ')<br>' + (CAT_LABEL[r.cat] || r.cat) + ' · ' + (CODE_LABEL[r.div] || r.div)),
      hovertemplate: '%{text}<extra></extra>',
      line: { color: statusColor[status], width: 1.6 },
      marker: {
        size: rows.map(r => r.ck === SELF ? 8 : 5), color: statusColor[status],
        line: { width: rows.map(r => r.ck === SELF ? 2 : 0), color: cssVar('--ink') },
      },
      name: p.name, pid: p.pid, opacity: 1,
    };
  });

  const tickvals = [], ticktext = [];
  CAT_ORDER.forEach((c, i) => { tickvals.push(i * 10 + 4); ticktext.push(CAT_LABEL[c] || c); });

  Plotly.react(el, traces, Object.assign(plotlyBase(), {
    height: 520, showlegend: false,
    xaxis: { title: isEs() ? 'Temporada' : 'Сезон', tickvals: YEARS, ticktext: ALL_SEASONS, gridcolor: cssVar('--line'), automargin: true },
    yaxis: { tickvals, ticktext, autorange: 'reversed', gridcolor: cssVar('--line'), automargin: true },
  }), { responsive: true, displayModeBar: false })
    .then(() => {
      el.removeAllListeners && el.removeAllListeners('plotly_click');
      el.on('plotly_click', (d) => {
        const tr = d.points[0];
        if (tr && traces[tr.curveNumber]) openPlayerModal(traces[tr.curveNumber].pid);
      });
      applyPathHighlight();
    });
}

function applyPathHighlight() {
  const el = document.getElementById('pathsDiv');
  if (!el.data || !el.data.length) return;
  const q = pathHighlight.trim().toLowerCase();
  const opacities = el.data.map(tr => (!q || (tr.name || '').toLowerCase().includes(q)) ? 1 : 0.08);
  Plotly.restyle(el, { opacity: opacities });
}

/* ============================= player modal ============================= */

function showModal() { document.getElementById('playerModalBackdrop').classList.remove('hidden'); }
function hideModal() { document.getElementById('playerModalBackdrop').classList.add('hidden'); }

function openPlayersListModal(title, players) {
  const card = document.getElementById('playerModalCard');
  card.innerHTML = '<button type="button" class="modal-close" id="modalCloseBtn">&times;</button>' +
    '<h3>' + esc(title) + '</h3>' +
    '<div class="modal-sub">' + players.length + ' ' + T('count_players', 'игроков') + '</div>' +
    '<div class="table-shell"><div class="table-scroll"><table><tbody>' +
    players.map(p => '<tr data-pid="' + esc(p.pid) + '"><td>' + esc(p.name) + '</td><td class="num">' + esc(p.season) + '</td></tr>').join('') +
    '</tbody></table></div></div>';
  card.querySelectorAll('tr[data-pid]').forEach(tr => tr.addEventListener('click', () => openPlayerModal(tr.dataset.pid)));
  document.getElementById('modalCloseBtn').addEventListener('click', hideModal);
  showModal();
}

function openPlayerModal(pid) {
  const p = CLUB.players[pid];
  if (!p) return;
  const rows = [...p.rows].sort((a, b) => a.y - b.y);
  const y0 = rows[0].y;
  const donor = findDonor(p.rows, y0);
  let badge = '';
  if (donor.type === 'homegrown') badge = T('player_homegrown', 'Своя школа клуба — нет более ранней записи в другом клубе.');
  else if (donor.type === 'transfer') {
    const fromName = CLUB.clubs[donor.from] || donor.from;
    badge = isEs() ? I18N_ES.player_from.replace('{club}', fromName).replace('{season}', seasonLabel(y0))
      : 'Пришёл из ' + fromName + ' в сезоне ' + seasonLabel(y0) + '.';
  } else if (donor.type === 'gap') {
    badge = T('player_gap', 'Пришёл после разрыва в данных; предыдущий клуб неизвестен.');
  }

  const card = document.getElementById('playerModalCard');
  card.innerHTML = '<button type="button" class="modal-close" id="modalCloseBtn">&times;</button>' +
    '<h3>' + esc(p.name) + '</h3>' +
    '<div class="modal-sub">' + (p.birth_year ? p.birth_year + ' · ' : '') + rows.length + ' ' + (isEs() ? 'registros' : 'записей') + '</div>' +
    (badge ? '<div class="badge">' + esc(badge) + '</div>' : '') +
    '<div class="table-shell"><div class="table-scroll"><table><thead><tr>' +
    '<th>' + T('th_season', 'Сезон') + '</th><th>' + T('th_club_row', 'Клуб') + '</th><th>' + T('th_team_row', 'Команда') + '</th>' +
    '<th>' + T('th_cat_row', 'Категория') + '</th><th>' + T('th_div_row', 'Дивизион') + '</th></tr></thead><tbody>' +
    rows.map(r => (
      '<tr' + (r.ck === SELF ? ' style="background:var(--accent-soft)"' : '') + '>' +
      '<td>' + seasonLabel(r.y) + '</td><td>' + esc(CLUB.clubs[r.ck] || r.ck) + '</td><td>' + esc(CLUB.teams[r.t] || r.t) + '</td>' +
      '<td>' + esc(CAT_LABEL[r.cat] || r.cat) + '</td><td>' + esc(CODE_LABEL[r.div] || r.div) + '</td></tr>'
    )).join('') + '</tbody></table></div></div>';
  document.getElementById('modalCloseBtn').addEventListener('click', hideModal);
  showModal();
}

/* ============================= wiring / render-all ============================= */

function renderAll() {
  const roster = computeRoster();
  updateHeadCount(roster);
  renderFlow(roster);
  renderRoster(roster);
  renderPaths(roster);
}

function wireStaticControls() {
  document.getElementById('dirToggle').addEventListener('click', (e) => {
    const btn = e.target.closest('.seg-opt'); if (!btn || !CLUB) return;
    direction = btn.dataset.dir;
    document.querySelectorAll('#dirToggle .seg-opt').forEach(b => b.classList.toggle('is-active', b === btn));
    renderFlow(computeRoster());
  });
  document.getElementById('flowViewToggle').addEventListener('click', (e) => {
    const btn = e.target.closest('.seg-opt'); if (!btn || !CLUB) return;
    flowView = btn.dataset.view;
    document.querySelectorAll('#flowViewToggle .seg-opt').forEach(b => b.classList.toggle('is-active', b === btn));
    renderFlow(computeRoster());
  });
  document.getElementById('pathSearch').addEventListener('input', (e) => {
    pathHighlight = e.target.value; applyPathHighlight();
  });
  document.getElementById('playerModalBackdrop').addEventListener('click', (e) => {
    if (e.target.id === 'playerModalBackdrop') hideModal();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideModal(); });
  document.querySelectorAll('.theme-opt').forEach(btn => btn.addEventListener('click', () => { if (CLUB) renderAll(); }));
  document.querySelectorAll('.lang-opt').forEach(btn => btn.addEventListener('click', () => {
    if (!CLUB) return;
    renderClubHead(); renderFilterBar(); renderChips(); renderAll();
  }));
}

init();

})();
"""


if __name__ == "__main__":
    main()
