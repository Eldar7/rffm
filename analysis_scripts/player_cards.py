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

from site_theme import FONT_LINKS, LANG_SWITCH_JS, THEME_INIT_JS, THEME_SWITCH_JS, switch_row_html

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
    comp_meta = comps.set_index("competition_id")[["category_base", "division_level", "is_femenino", "game_type"]]
    part = part.join(comp_meta, on="competition_id")

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
        player["rows"].append({
            "team": clean(row.team), "team_id": clean(row.team_id),
            "club": clean(row.club_name_raw),
            "comp": clean(row.competition), "comp_id": clean(row.competition_id),
            "grp": clean(row.group), "group_id": clean(row.group_id),
            "cat": clean(getattr(row, "category_base", None)) or "OTHER",
            "div": clean(getattr(row, "division_level", None)) or "OTHER",
            "gt": clean(getattr(row, "game_type", None)),
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
    "back": "&larr; Ficha de equipo",
    "loading": "Cargando…",
    "not_found": "No se encontraron datos de inscripción para este jugador.",
    "h_reg": "Inscripciones por equipo/división",
    "birth": "Año de nacimiento",
    "all_seasons": "Mostrar todas las temporadas",
    "th_season": "Temporada", "th_cat": "Categoría", "th_div": "División", "th_team": "Equipo", "th_comp": "Competición",
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

.section-h{ display:flex; align-items:center; gap:0.9rem; flex-wrap:wrap; }
.section-h h2{ font-family:'Oswald',sans-serif; font-weight:700; text-transform:uppercase; font-size:1.1rem; color:var(--ink); margin:0; }
label.all-seasons{ display:inline-flex; align-items:center; gap:0.4rem; font-size:0.82rem; color:var(--ink-soft); cursor:pointer; margin-left:auto; }

.table-shell{ background:var(--surface); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); overflow:hidden; }
table{border-collapse:separate; border-spacing:0; font-size:0.85rem; width:100%;}
thead th{ background:var(--surface); border-bottom:1px solid var(--line-strong); padding:0.55rem 0.7rem;
  text-align:left; font-size:0.7rem; letter-spacing:0.05em; text-transform:uppercase; color:var(--ink-soft); }
tbody td{ border-bottom:1px solid var(--line); padding:0.5rem 0.7rem; vertical-align:middle; }
tbody tr:last-child td{border-bottom:none;}
tbody tr:hover td{background:var(--accent-soft);}
.season-cell{font-family:'JetBrains Mono',monospace; font-size:0.78rem; color:var(--ink-soft); white-space:nowrap;}
.tier-chip{ display:inline-block; font-size:0.72rem; font-weight:700; padding:0.1rem 0.5rem; border-radius:999px;
  background:var(--accent-soft); color:var(--accent); white-space:nowrap; }
.team-name{color:var(--ink); font-weight:600;}
.comp-meta{display:block; font-size:0.72rem; color:var(--ink-faint); margin-top:0.1rem;}
.empty-state{padding:2rem; text-align:center; color:var(--ink-faint);}
.birth-note{color:var(--ink-soft); font-size:0.85rem;}
footer.note{font-size:0.78rem; color:var(--ink-soft); max-width:90ch;}
</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    %SWITCH_ROW%
    <a class="back" href="club_division_map.html" data-i18n="back">&larr; Карточка команды</a>
    <span class="eyebrow" data-i18n="eyebrow">RFFM (Мадрид) &middot; карточка игрока</span>
    <h1 id="playerName">…</h1>
    <p class="club-sub" id="playerSub"></p>
  </header>

  <section>
    <div class="section-h">
      <h2 data-i18n="h_reg">Заявки по командам/дивизионам</h2>
      <label class="all-seasons"><input type="checkbox" id="allSeasonsBox"><span data-i18n="all_seasons">Показать все сезоны</span></label>
    </div>
    <div class="table-shell">
      <table id="regTable">
        <thead><tr>
          <th data-i18n="th_season">Сезон</th>
          <th data-i18n="th_cat">Категория</th>
          <th data-i18n="th_div">Дивизион</th>
          <th data-i18n="th_team">Команда</th>
          <th data-i18n="th_comp">Соревнование</th>
        </tr></thead>
        <tbody id="regBody"><tr><td class="empty-state" colspan="5" data-i18n="loading">Загрузка…</td></tr></tbody>
      </table>
    </div>
  </section>

  <footer class="note" data-i18n="footer">Построено из <code>output/processed/rffm/player_competition_participation.csv</code>. См.
    <code>analysis_scripts/player_cards.py</code>.</footer>
</div>
<script>
const SHARD_MOD = %SHARD_MOD%;
const SEASONS = %SEASONS_JSON%;
const LANG = {
  ru: { loading: 'Загрузка…', notFound: 'Нет данных о заявках этого игрока.', other: 'Прочее', birthLabel: 'Год рождения' },
  es: { loading: 'Cargando…', notFound: 'No se encontraron datos de inscripción para este jugador.', other: 'Otra', birthLabel: 'Año de nacimiento' },
};
let CURLANG = 'ru';
let CUR_PID = null, CUR_SEASON = null;
const SHARD_CACHE = {};

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

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
    document.getElementById('regBody').innerHTML =
      `<tr><td class="empty-state" colspan="5">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  document.getElementById('playerName').textContent = found.name;
  document.title = `${found.name} — RFFM`;
  document.getElementById('playerSub').textContent =
    found.birth_year ? `${LANG[CURLANG].birthLabel}: ${found.birth_year}` : '';
  if (!rows.length) {
    document.getElementById('regBody').innerHTML =
      `<tr><td class="empty-state" colspan="5">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  rows.sort((a, b) => b._season.localeCompare(a._season) || (a.comp || '').localeCompare(b.comp || ''));
  document.getElementById('regBody').innerHTML = rows.map(r => `<tr>
    <td class="season-cell">${esc(r._season)}</td>
    <td>${esc(r.cat && r.cat !== 'OTHER' ? r.cat : (LANG[CURLANG].other))}</td>
    <td><span class="tier-chip">${esc(r.div && r.div !== 'OTHER' ? r.div : '—')}</span></td>
    <td class="team-name">${esc(r.team || '—')}</td>
    <td>${esc(r.comp || '—')}<span class="comp-meta">${esc([r.grp, r.gt].filter(Boolean).join(' · '))}</span></td>
  </tr>`).join('');
}

async function main() {
  const params = new URLSearchParams(location.search);
  CUR_PID = params.get('player');
  CUR_SEASON = params.get('season') || SEASONS[SEASONS.length - 1];
  if (!CUR_PID) {
    document.getElementById('regBody').innerHTML =
      `<tr><td class="empty-state" colspan="5">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  await render();
}

document.getElementById('allSeasonsBox').addEventListener('change', render);

(function () {
  var I18N_ES = %I18N_ES_JSON%;
  %LANG_SWITCH_JS%
})();

document.querySelectorAll('.lang-opt').forEach(function (btn) {
  btn.addEventListener('click', function () { CURLANG = btn.getAttribute('data-lang-btn'); render(); });
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
            .replace("%THEME_SWITCH_JS%", THEME_SWITCH_JS))


def main():
    parser = argparse.ArgumentParser(description="RFFM player-card data + page")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    build_all(Path(__file__).parent.parent / args.output_dir)


if __name__ == "__main__":
    main()
