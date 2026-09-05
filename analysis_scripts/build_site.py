#!/usr/bin/env python3
"""
Builds the whole GitHub Pages site into a single output directory: the
interactive reports plus a landing page (index.html) that links to them
and summarizes season/category coverage from coverage_manifest.csv.

weird_scores.html, club_division_map.html, team_card.html, player_card.html,
club_profile.html, all_players.html, all_teams.html and season_comparison.html
are built exclusively from their _v2 generators now (Parquet-sourced, via
rffm_data.py, reading output/processed/rffm_parquet/) — each strictly
supersedes the CSV-driven v1 report it replaced (see DATA_FINDINGS.md /
OPERATIONS.md for the club_id migration this depended on) and several fix
real v1 bugs on top: v1's birth_year read carried the CSVs' ".0" float-
serialization artifact, which silently dropped team_card.html's roster
"seasons eligible" (Y) stat to None for ~18.6k players; v1's all_players.html
inflated a player's "number of clubs" count on a club that only ever
renamed/changed sponsor; club_profile.html/v2 additionally ships a whole
"Соперничества" (rivalries) section v1 never had. The v1 generators
(club_division_map.py, team_cards.py, player_cards.py, club_profile.py +
club_profile_data.py, all_players.py, all_teams.py, weird_scores_report.py,
season_comparison.py) are kept in the repo — club_division_map.py and
team_cards.py in particular are still imported everywhere as shared
constant/helper modules (CATEGORIES, DIV_CODE, TIER_OF, build_club_team_cards,
norm_id, ...) — but this script no longer calls their build_all()/
build_html(), so they no longer render into the site.

output/processed/rffm_parquet/ is therefore required for a full site build,
not optional: pages-deploy.yml always rebuilds it before calling this
script, so this only bites a local/dev build run without first running
analysis_scripts/build_parquet.py. main() fails fast with a clear message
in that case rather than silently emitting an index.html whose cards link
to pages that were never built.

<output-dir>/v2/club_scorecard.html ("Кантера") is the one page that stays
under v2/ — a v2-exclusive report with no v1 equivalent ever built.

Usage:
    python analysis_scripts/build_site.py --output-dir site
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import weird_scores_report_v2
import team_cards_v2
import club_division_map_v2
import team_participation_map_v2
import club_metro_v2
import club_profile_v2
import team_rosters_v2
import participation_map_v2
import player_cards_v2
import all_players_v2
import all_teams_v2
import season_comparison_v2
import club_scorecard_site
import competition_structure
import all_clubs
from site_theme import CSS, FONT_LINKS, LANG_SWITCH_JS, THEME_INIT_JS, THEME_SWITCH_JS, switch_row_html

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
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM data — футбол Мадрида, {SEASON_RANGE}</title>
%FONT_LINKS%
%THEME_INIT%
<style>%CSS%
.page{ max-width:1000px; }
h2{ font-size:clamp(20px, 3vw, 26px); border-bottom:1px solid var(--line); padding-bottom:10px; margin-bottom:18px; }
p.foot{color:var(--ink-muted); font-size:0.8rem; max-width:75ch; font-family:'JetBrains Mono',monospace;}
code{ font-family: 'JetBrains Mono', monospace; font-size:0.86em; background:var(--surface-2);
  padding:0.05em 0.35em; border-radius:3px; }
.status-ok{color:var(--accent); font-weight:700;}
.status-warn{color:var(--gold); font-weight:700;}
</style>
</head>
<body>
<div class="wrap">
  <div class="masthead">
    <div>
      <div class="kicker"><span data-i18n="kicker">RFFM &middot; Данные федерации</span></div>
      <h1><span data-i18n="h1">Футбол Мадрида —<br>данные RFFM</span></h1>
    </div>
    <div class="scope-block">
      %SWITCH_ROW%
      <div class="scope">
        <span data-i18n="scope1">Сезоны <b>{SEASON_RANGE}</b></span>
      </div>
    </div>
  </div>
  <p class="lede" style="margin:22px 0 0"><span data-i18n="lede">Соревнования, матчи/результаты, турнирные таблицы, площадки и обогащённые данные, собранные с
    <a href="https://www.rffm.es" target="_blank" rel="noopener">rffm.es</a> и пересобранные в эту страницу
    прямо из CSV в <code>output/processed/rffm/</code> &mdash; без ручных шагов между ними.</span></p>

  <section>
    <div class="section-head">
      <h2><span data-i18n="h_reports">Отчёты</span></h2>
    </div>
    <div class="cards">
      {CARDS}
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2><span data-i18n="h_coverage">Охват по сезонам и категориям</span></h2>
    </div>
    <div class="table-scroll">
      <table>
        <thead><tr><th><span data-i18n="th_season">Сезон</span></th><th><span data-i18n="th_core">Core-краулинг</span></th><th><span data-i18n="th_clubs">Обогащение клубов</span></th>
          <th><span data-i18n="th_acta">acta_partido готово для</span></th><th><span data-i18n="th_ficha">fichajugador готово для</span></th></tr></thead>
        <tbody>
          {COVERAGE_ROWS}
        </tbody>
      </table>
    </div>
    <p class="foot"><span data-i18n="foot_detail">Полная детализация: <code>output/processed/rffm/coverage_manifest.csv</code>.</span></p>
  </section>

  <footer><span data-i18n="footer">Пересобирается автоматически <code>.github/workflows/pages-deploy.yml</code> &middot; см.
    <code>analysis_scripts/build_site.py</code>, как строится каждый отчёт.</span></footer>
</div>
<script>
(function () {
  var I18N_ES = %I18N_ES_JSON%;
  %LANG_JS%
})();
%THEME_SWITCH_JS%
</script>
</body>
</html>
"""

I18N_ES = {
    "kicker": "RFFM &middot; Datos de la federación",
    "h1": "Fútbol de Madrid —<br>datos de la RFFM",
    "scope1": "Temporadas <b>{SEASON_RANGE}</b>",
    "lede": 'Competiciones, partidos/resultados, clasificaciones, campos y datos enriquecidos recopilados de '
            '<a href="https://www.rffm.es" target="_blank" rel="noopener">rffm.es</a>, reconstruidos en esta página '
            'directamente desde los CSV de <code>output/processed/rffm/</code> &mdash; sin pasos manuales de por medio.',
    "h_reports": "Informes",
    "h_coverage": "Cobertura por temporada y categoría",
    "th_season": "Temporada", "th_core": "Rastreo core", "th_clubs": "Enriquecimiento de clubes",
    "th_acta": "acta_partido completo para", "th_ficha": "fichajugador completo para",
    "foot_detail": 'Detalle completo: <code>output/processed/rffm/coverage_manifest.csv</code>.',
    "footer": 'Reconstruido automáticamente por <code>.github/workflows/pages-deploy.yml</code> &middot; ver '
              '<code>analysis_scripts/build_site.py</code> para saber cómo se genera cada informe.',
}

CARDS_RU = [
    {
        "href": "weird_scores.html",
        "title": "Странные счета, доминаторы и аутсайдеры",
        "desc": "Самые крупные разгромы, нулевые ничьи и лучшая/худшая разница мячей у команд и клубов.",
    },
    {
        "href": "club_division_map.html",
        "title": "Карта клубов по дивизионам",
        "desc": "Матрица турнирных позиций клубов по всем возрастам и дивизионам, с реальными площадками и гербами клубов.",
    },
    {
        "href": "club_profile.html",
        "title": "Профиль клуба",
        "desc": "Выберите клуб — откуда пришли и куда уходят игроки, состав по категориям/командам, путь каждого игрока по клубам и дивизионам, и с кем и как клуб играл за всю историю — вплоть до конкретных матчей между двумя составами.",
    },
    {
        "href": "competition_structure.html",
        "title": "Пирамида лиг RFFM",
        "desc": "Для каждого возраста/пола/типа игры — полная лестница дивизионов, переходы вверх/вниз, выход в RFEF и календарь фаз сезона.",
    },
    {
        "href": "season_comparison.html",
        "title": "Сравнение сезонов",
        "desc": "Матчи, клубы, голы и соревнования по сезонам с фильтрами по возрасту / дивизиону / типу игры.",
    },
    {
        "href": "all_players.html",
        "title": "Все игроки",
        "desc": "Явки, голы, карточки и карьерные метрики (год старта, число клубов/команд) по каждому игроку — с фильтрами по сезону/возрасту/дивизиону и сортировкой по любой колонке.",
    },
    {
        "href": "all_teams.html",
        "title": "Все команды",
        "desc": "Игры, В-Н-П, очки/игру, разница мячей, место в группе, состав и стабильность по каждой команде и соревнованию — с фильтрами по сезону/возрасту/дивизиону и сортировкой по любой колонке.",
    },
    {
        "href": "all_clubs.html",
        "title": "Все клубы",
        "desc": "То же самое, но по клубам: сумма очков/игр всех команд клуба, взвешенные очки/игру и разница мячей, лучший дивизион, число лидирующих команд.",
    },
    {
        "href": "v2/club_scorecard.html",
        "title": "Кантера",
        "desc": "Кто реально растит своих: размер, потолок, доля алюмни, дошедших до элиты — своя школа или пришли готовыми — удержание по поколениям и баланс трансферов, по всем 685 клубам.",
    },
]
CARDS_ES = [
    "Marcadores extraños, dominadores y colistas",
    "Las goleadas más grandes, empates a cero y la mejor/peor diferencia de goles de equipos y clubes.",
    "Mapa de clubes por división",
    "Matriz de posiciones de clubes en todas las edades y divisiones, con sedes reales y escudos de los clubes.",
    "Perfil de club",
    "Elige un club: de dónde llegaron y a dónde se fueron sus jugadores, la plantilla por categoría/equipo, el camino de cada jugador por clubes y divisiones, y contra quién y cómo ha jugado el club en toda su historia — hasta los partidos concretos entre dos plantillas.",
    "Pirámide de ligas de la RFFM",
    "Para cada edad/sexo/tipo de juego: la escalera completa de divisiones, ascensos/descensos, la salida a la RFEF y el calendario de fases de la temporada.",
    "Comparación entre temporadas",
    "Partidos, clubes, goles y competiciones por temporada, filtrables por edad / división / tipo de juego.",
    "Todos los jugadores",
    "Partidos, goles, tarjetas y métricas de carrera (año de inicio, nº de clubes/equipos) de cada jugador — con filtros por temporada/edad/división y orden por cualquier columna.",
    "Todos los equipos",
    "Partidos, G-E-P, puntos/partido, diferencia de goles, posición en el grupo, plantilla y estabilidad de cada equipo y competición — con filtros por temporada/edad/división y orden por cualquier columna.",
    "Todos los clubes",
    "Lo mismo, pero por club: suma de puntos/partidos de todos sus equipos, puntos/partido y diferencia de goles ponderados, mejor división, número de equipos líderes.",
    "La Cantera",
    "Quién realmente forma a los suyos: tamaño, techo, qué parte de los alumni llega a élite — cantera propia o ya formados — retención por generación y saldo de fichajes, en los 685 clubes.",
]


def status_span(status: str) -> str:
    if status == "complete":
        return f'<span class="status-ok">{status}</span>'
    if status == "—":
        return status
    return f'<span class="status-warn">{status}</span>'


def build_index(seasons: list[str], coverage: list[dict]) -> str:
    cards_html = "\n      ".join(
        f'<a class="card" href="{c["href"]}"><span class="title" data-i18n="card_t{n}">{c["title"]}</span>'
        f'<span class="desc" data-i18n="card_d{n}">{c["desc"]}</span></a>'
        for n, c in enumerate(CARDS_RU)
    )
    i18n_es = dict(I18N_ES)
    for n, (title, desc) in enumerate(zip(CARDS_ES[0::2], CARDS_ES[1::2])):
        i18n_es[f"card_t{n}"] = title
        i18n_es[f"card_d{n}"] = desc

    rows_html = "\n          ".join(
        "<tr><td>{season}</td><td>{core}</td><td>{clubs}</td>"
        "<td class=\"meta\">{acta}</td><td class=\"meta\">{ficha}</td></tr>".format(
            season=r["season"],
            core=status_span(r["core_status"]),
            clubs=status_span(r["clubs_status"]),
            acta=", ".join(r["acta_categories"]) or "—",
            ficha=", ".join(r["ficha_categories"]) or "—",
        )
        for r in coverage
    )

    season_range = f"{seasons[0]}–{seasons[-1]}" if seasons else ""
    i18n_es = {k: (v.replace("{SEASON_RANGE}", season_range) if isinstance(v, str) else v)
               for k, v in i18n_es.items()}
    return (INDEX_HTML
            .replace("{SEASON_RANGE}", season_range)
            .replace("{CARDS}", cards_html)
            .replace("{COVERAGE_ROWS}", rows_html)
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%THEME_INIT%", THEME_INIT_JS)
            .replace("%THEME_SWITCH_JS%", THEME_SWITCH_JS)
            .replace("%CSS%", CSS)
            .replace("%SWITCH_ROW%", switch_row_html())
            .replace("%LANG_JS%", LANG_SWITCH_JS)
            .replace("%I18N_ES_JSON%", json.dumps(i18n_es, ensure_ascii=False)))


def main():
    parser = argparse.ArgumentParser(description="Build the full RFFM GitHub Pages site")
    parser.add_argument("--output-dir", default="site")
    args = parser.parse_args()

    out_dir = Path(__file__).parent.parent / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet_dir = Path(__file__).parent.parent / "output" / "processed" / "rffm_parquet"
    if not any((parquet_dir / "matches").glob("*.parquet")):
        sys.exit(
            "output/processed/rffm_parquet/ is not built yet — weird_scores.html, "
            "club_division_map.html, team_card.html, player_card.html, club_profile.html, "
            "all_players.html, all_teams.html, season_comparison.html and club_scorecard.html "
            "are all Parquet-sourced now and have no CSV-driven fallback. Run "
            "analysis_scripts/build_parquet.py first (pages-deploy.yml always does this "
            "before calling build_site.py)."
        )

    print("Building all_clubs.html...")
    all_clubs.build_all(out_dir)

    print("Building competition_structure.html...")
    competition_structure.build_all(out_dir)

    print("Building weird_scores.html...")
    weird_scores_report_v2.build_all(out_dir)

    print("Building team_card.html + team-participation-map data...")
    team_cards_v2.build_all(out_dir)
    team_participation_map_v2.build_all(out_dir)

    print("Building metro.html + per-club metro-diagram data (club_metro_v2)...")
    (out_dir / "metro.html").write_text(
        (Path(__file__).parent / "metro_template.html").read_text(encoding="utf-8"), encoding="utf-8")
    club_metro_v2.build_all(out_dir)

    print("Building club_division_map.html (squads-over-seasons grid)...")
    club_division_map_v2.build_all(out_dir)

    print("Building club_profile.html (linked from team_card.html / club_division_map.html)...")
    club_profile_v2.build_all(out_dir)

    # team_rosters.py's (v1) build is no longer called - confirmed on real
    # data that its output wasn't actually identical to team_rosters_v2's
    # (not just reordering): v1's birth_year read carries the CSVs' ".0"
    # float-serialization artifact, which silently drops the roster's
    # "seasons eligible" (Y) stat to None for ~18.6k players; team_rosters_v2's
    # Parquet read cleans that via real int typing.
    print("Building team_card.html's Состав tab data (team_rosters_v2)...")
    team_rosters_v2.build_all(out_dir)

    print("Building player_card.html (linked from team_card.html's roster)...")
    player_cards_v2.build_all(out_dir)

    print("Building player_card.html's Карта участия tab data (participation_map_v2)...")
    participation_map_v2.build_all(out_dir)

    print("Building all_players.html...")
    all_players_v2.build_all(out_dir)

    print("Building all_teams.html...")
    all_teams_v2.build_all(out_dir)

    print(f"Building season_comparison.html ({len(season_comparison_v2.SEASONS)} seasons)...")
    sc_data_v2 = season_comparison_v2.load_all_data()
    (out_dir / "season_comparison.html").write_text(season_comparison_v2.build_html(sc_data_v2), encoding="utf-8")

    print("Building v2/club_scorecard.html (\"Кантера\" - youth-development scorecard, all clubs)...")
    v2_dir = out_dir / "v2"
    v2_dir.mkdir(parents=True, exist_ok=True)
    cs_data = club_scorecard_site.load_all_data()
    (v2_dir / "club_scorecard.html").write_text(club_scorecard_site.build_html(cs_data), encoding="utf-8")

    print("Building index.html...")
    coverage = coverage_rows()
    (out_dir / "index.html").write_text(
        build_index(season_comparison_v2.SEASONS, coverage), encoding="utf-8")

    total_bytes = sum(f.stat().st_size for f in out_dir.glob("*.html"))
    print(f"\nSite written to {out_dir} ({total_bytes / 1024:.0f} KB total)")


if __name__ == "__main__":
    main()
