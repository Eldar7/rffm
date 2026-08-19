#!/usr/bin/env python3
"""
v2 PROOF-OF-CONCEPT: identical to team_cards.py except build_club_team_cards()
sources teams/matches/competitions/standings from output/processed/
rffm_parquet/ via rffm_data.read_table() instead of pd.read_csv(). This is a
shared dependency other ported v2 reports import (player_cards_v2, all_players_v2,
all_teams_v2, all_clubs_v2 will import build_club_team_cards/norm_id/list_seasons
from here, not from the original team_cards.py) - port it once, every dependent
report gets the Parquet path for free. club_division_map's DIV_LABEL_ES/RU/
DIV_ORDER imports are unchanged (pure constants, no CSV reads - see that
module's own docstring note if/when it's ported).

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

import rffm_data as data
from club_division_map import DIV_LABEL_ES, DIV_LABEL_RU, DIV_ORDER
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
    """club_name_raw -> {team_id: {name, matches: [...], competitions: {...}}},
    one entry per team the club fielded, sorted chronologically within each
    team. `competitions` is keyed by f"{comp_id}_{group_id}" — a team can be
    registered in more than one competition/group the same season (regular
    league + cup + playoff group, ...) — see team_group_membership.csv;
    each entry carries the static per-competition facts matches.csv repeats
    on every row (division, phase, game type) plus a standings.csv snapshot
    (position/played/W-D-L/goals/points), for the Team Card's per-competition
    summary panel."""
    teams = data.read_table("teams", season=season)
    matches = data.read_table("matches", season=season)
    comps = data.read_table("competitions", season=season)
    standings = data.read_table("standings", season=season)

    tid_to_club = dict(zip(teams["team_id"].map(norm_id), teams["club_name_raw"]))
    tid_to_name = dict(zip(teams["team_id"].map(norm_id), teams["team"]))
    comp_id_to_division = dict(zip(comps["competition_id"], comps["division_level"]))

    group_size = standings.groupby(standings["group_id"].map(norm_id))["team_id"].nunique().to_dict()

    standing_by_team_group: dict[tuple[str, str], dict] = {}
    for s in standings.itertuples(index=False):
        key = (norm_id(s.team_id), norm_id(s.group_id))
        if key[0] is None or key[1] is None:
            continue
        standing_by_team_group[key] = {
            "position": clean(s.position), "played": clean(s.played),
            "wins": clean(s.wins), "draws": clean(s.draws), "losses": clean(s.losses),
            "gf": clean(s.goals_for), "ga": clean(s.goals_against),
            "gd": clean(s.goal_diff), "points": clean(s.points),
            "size": int(group_size.get(key[1], 0)) or None,
        }

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
                "name": clean(tid_to_name.get(tid)) or tid, "matches": [], "competitions": {},
            })
            team_rec["matches"].append(entry)

            # Keyed by competition_id alone, not competition_id+group_id: a
            # knockout cup runs its rounds (1/16, cuartos, ...) as *separate
            # group_ids under the same competition_id* (a real example in
            # 2025-2026: one AFICIONADO team has 6 different group_ids all
            # under competition_id 26067232, "COPA DE AFICIONADOS") — to a
            # user that's one competition, not six, so this rolls every
            # round up into a single card with a combined record. `grp` is
            # only kept when the team stayed in one single group all season
            # (the common league case) — multiple distinct groups (the cup
            # case) means no one `grp` label is representative, so it's
            # nulled out; group-level detail (incl. the calendar link) still
            # lives on each individual match entry in `matches`.
            comp_id = entry["comp_id"]
            comp_rec = team_rec["competitions"].setdefault(comp_id, {
                "comp": entry["comp"], "comp_id": comp_id,
                "grp": entry["grp"], "gt": entry["gt"], "gt_id": entry["gt_id"],
                "phase": entry["phase"], "season_id": entry["season_id"],
                "division_level": clean(comp_id_to_division.get(comp_id)),
                "standing": standing_by_team_group.get((tid, entry["group_id"])),
                "_group_ids": set(),
            })
            if comp_rec["_group_ids"] and entry["group_id"] not in comp_rec["_group_ids"]:
                comp_rec["grp"] = None
            comp_rec["_group_ids"].add(entry["group_id"])
            if comp_rec["standing"] is None:
                comp_rec["standing"] = standing_by_team_group.get((tid, entry["group_id"]))

    for teams_of_club in club_teams.values():
        for team_rec in teams_of_club.values():
            team_rec["matches"].sort(key=lambda x: (x["date"] or "9999-99-99", x["time"] or ""))
            for comp_rec in team_rec["competitions"].values():
                comp_rec.pop("_group_ids", None)

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
    "h_comps": "Competiciones",
    "comps_p": "Haz clic en una tarjeta de competición para activarla/desactivarla — los partidos, el resumen "
               "por jugador y el once inicial de abajo se recalculan solo con las competiciones activas.",
    "tab_matches": "Partidos", "tab_roster": "Plantilla",
    "h_roster": "Plantilla por partido",
    "roster_p": "Filas — jugadores, columnas — partidos de la temporada. Círculo relleno — titular, círculo hueco — "
                "suplente que entró, borde dorado — capitán, borde azul — jugó de portero ese partido, número al "
                "lado — goles marcados, barra — tarjeta.",
    "h_summary": "Resumen por jugador",
    "summary_p": "Calculado a partir de las convocatorias (sin datos de minutos jugados ni asistencias, que la "
                 "fuente no registra). “Partidos” cuenta partidos ya finalizados. Haz clic en ▾ de "
                 "cualquier columna para ordenar o filtrar, como en Excel.",
    "sh_jersey": "Nº", "sh_name": "Jugador", "sh_seasons": "Temporadas", "sh_apps": "Partidos", "sh_starts": "Titular", "sh_sub": "Suplente",
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
  --gk:#3068a8;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
    --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
    --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
    --win:#74c47f; --win-soft:#20301f; --loss:#e2685a; --loss-soft:#33201d; --draw:#d9b64a; --draw-soft:#332a10;
    --gk:#6ca6e0;
  }
}
:root[data-theme="dark"]{
  --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
  --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
  --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
  --win:#74c47f; --win-soft:#20301f; --loss:#e2685a; --loss-soft:#33201d; --draw:#d9b64a; --draw-soft:#332a10;
  --gk:#6ca6e0;
}
:root[data-theme="light"]{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --win:#2f6b3c; --win-soft:#dce8dd; --loss:#a03327; --loss-soft:#f5ddd6; --draw:#8a6a12; --draw-soft:#f3e7c4;
  --gk:#3068a8;
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
.club-sub{margin:0; color:var(--ink-soft); font-size:0.95rem; display:flex; align-items:center; gap:0.6rem; flex-wrap:wrap;}
.season-badge{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; font-weight:700; letter-spacing:0.03em;
  background:var(--accent-soft); color:var(--accent); border-radius:999px; padding:0.12rem 0.6rem; }
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

.comps-grid{ display:grid; grid-template-columns:repeat(auto-fill, minmax(15.5rem, 1fr)); gap:0.6rem; }
.comp-card{ text-align:left; font-family:inherit; cursor:pointer; background:var(--surface); border:1.5px solid var(--line-strong);
  border-radius:8px; padding:0.6rem 0.75rem; display:flex; flex-direction:column; gap:0.3rem; opacity:0.5; transition:opacity 0.1s, border-color 0.1s; }
.comp-card:hover{border-color:var(--accent);}
.comp-card.active{opacity:1; border-color:var(--accent); box-shadow:0 0 0 1px var(--accent);}
.comp-card .cc-top{display:flex; align-items:center; gap:0.4rem; flex-wrap:wrap;}
.comp-div-badge{ font-family:'JetBrains Mono',monospace; font-size:0.62rem; font-weight:700; letter-spacing:0.03em;
  background:var(--accent-soft); color:var(--accent); border-radius:4px; padding:0.08rem 0.4rem; white-space:nowrap; }
.comp-phase-badge{ font-family:'JetBrains Mono',monospace; font-size:0.62rem; font-weight:700;
  background:var(--gold-soft); color:var(--gold); border-radius:4px; padding:0.08rem 0.4rem; white-space:nowrap; }
.comp-card .cc-name{font-weight:700; font-size:0.85rem; color:var(--ink); line-height:1.25;}
.comp-card .cc-record{font-family:'JetBrains Mono',monospace; font-size:0.76rem; color:var(--ink-soft);}
.comp-card .cc-standing{font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:var(--ink-faint);}
.stats-strip{ display:grid; grid-template-columns:repeat(auto-fit, minmax(6.5rem, 1fr)); }
.stats-strip .stat-cell{ padding:0.7rem 0.8rem; border-right:1px solid var(--line); }
.stats-strip .stat-cell:last-child{border-right:none;}
.stats-strip .stat-cell .num{ font-family:'JetBrains Mono',monospace; font-weight:700; font-size:1.3rem; color:var(--ink); font-variant-numeric:tabular-nums; }
.uncertain-mark{ color:var(--gold); font-family:ui-sans-serif; cursor:help; }
.stats-strip .stat-cell .lbl{font-size:0.68rem; color:var(--ink-soft); margin-top:0.15rem;}
.stats-strip .stat-cell.win .num{color:var(--win);}
.stats-strip .stat-cell.loss .num{color:var(--loss);}

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
.mark-gk{box-shadow:0 0 0 2px var(--gk);}
.mark-cap.mark-gk{box-shadow:0 0 0 2px var(--gold), 0 0 0 4px var(--gk);}
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
    <p class="club-sub">
      <span id="clubName"></span>
      <span class="season-badge" id="seasonBadge"></span>
    </p>
  </header>

  <section id="compsSection">
    <div class="section-h"><h2 data-i18n="h_comps">Соревнования</h2><span class="n" id="compsCount"></span></div>
    <p style="color:var(--ink-soft); font-size:0.82rem; max-width:70ch; margin:0 0 0.8rem;" data-i18n="comps_p">
      Нажмите на карточку соревнования, чтобы включить/выключить его — матчи, сводка по игрокам и состав
      ниже пересчитываются только по выбранным.
    </p>
    <div class="comps-grid" id="compsGrid"></div>
  </section>

  <div class="table-shell stats-strip" id="teamStatsStrip"></div>

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
            <th data-key="seasons" data-type="number" title="Сыграно сезонов из тех, на которые игрок проходит по возрасту"><span data-i18n="sh_seasons">Сезонов</span></th>
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
      золотая обводка — капитан, синяя обводка — играл вратарём в этом матче, число рядом — забитые голы, полоска — карточка.
    </p>
    <div class="table-shell stats-strip" id="rosterStatsStrip" style="margin-bottom:0.8rem;"></div>
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
        win: 'Победа', draw: 'Ничья', loss: 'Поражение',
        stPlayed: 'Матчи', stWins: 'Победы', stDraws: 'Ничьи', stLosses: 'Поражения',
        stWinPct: '% побед', stGoals: 'Голы (з:п)', stGd: 'Разница', stPpg: 'Очков/игру',
        stStability: 'Стабильность состава', stStabilityHint: 'Среднее пересечение стартового состава с предыдущим сыгранным матчем',
        seasonsUncertain: 'Не все сезоны в этом окне полностью докачаны — реальное число может отличаться',
        noComps: 'Нет данных о соревнованиях.', standingPos: 'место', of: 'из' },
  es: { loading: 'Cargando…', notFound: 'No se encontraron datos para este equipo en esta temporada.',
        home: 'Local', away: 'Visitante', scheduled: 'por jugar',
        win: 'Victoria', draw: 'Empate', loss: 'Derrota',
        stPlayed: 'Partidos', stWins: 'Victorias', stDraws: 'Empates', stLosses: 'Derrotas',
        stWinPct: '% victorias', stGoals: 'Goles (f:c)', stGd: 'Diferencia', stPpg: 'Puntos/partido',
        stStability: 'Estabilidad del once', stStabilityHint: 'Solapamiento medio del once inicial respecto al partido anterior jugado',
        seasonsUncertain: 'No todas las temporadas de esta ventana están completamente recopiladas — el número real puede diferir',
        noComps: 'Sin datos de competiciones.', standingPos: 'puesto', of: 'de' },
};
const PHASE_LABEL = {
  ru: { regular_season: 'Регулярный чемпионат', 'phase fase final': 'Финал', playoff: 'Плей-офф',
        'phase segunda fase': '2-й этап', 'playoff FASE FINAL': 'Финал плей-офф',
        'phase 7 fase': 'Доп. этап', 'playoff 7 FASE': 'Плей-офф (доп.)' },
  es: { regular_season: 'Liga regular', 'phase fase final': 'Final', playoff: 'Playoff',
        'phase segunda fase': '2ª fase', 'playoff FASE FINAL': 'Final de playoff',
        'phase 7 fase': 'Fase adicional', 'playoff 7 FASE': 'Playoff (adicional)' },
};
const DIV_LABEL_RU = %DIV_LABEL_RU_JSON%;
const DIV_LABEL_ES = %DIV_LABEL_ES_JSON%;
const DIV_ORDER = %DIV_ORDER_JSON%;
function divLabel(d) { return (CURLANG === 'ru' ? DIV_LABEL_RU : DIV_LABEL_ES)[d] || d || ''; }
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

function divRank(div) {
  const i = DIV_ORDER.indexOf(div);
  return i === -1 ? 999 : i;
}
function phaseLabel(phase) {
  const label = (PHASE_LABEL[CURLANG] || {})[phase];
  if (!label || phase === 'regular_season') return '';
  return label;
}
function compDateMin(compId) {
  let min = null;
  ((CUR_TEAM && CUR_TEAM.matches) || []).forEach(m => {
    if (m.comp_id !== compId) return;
    if (m.date && (!min || m.date < min)) min = m.date;
  });
  return min || '9999-99-99';
}
function compRecord(compId) {
  const ms = ((CUR_TEAM && CUR_TEAM.matches) || []).filter(m => m.comp_id === compId && m.status === 'finished');
  let w = 0, d = 0, l = 0, gf = 0, ga = 0;
  ms.forEach(m => {
    if (m.result === 'W') w++; else if (m.result === 'D') d++; else if (m.result === 'L') l++;
    const sf = Number(m.sf), sa = Number(m.sa);
    if (!isNaN(sf)) gf += sf;
    if (!isNaN(sa)) ga += sa;
  });
  return { played: ms.length, w, d, l, gf, ga };
}

// One card per competition_id (see build_club_team_cards()'s docstring for
// why a cup's rounds collapse into a single card here) — click toggles it
// in/out of ACTIVE_COMP_KEYS and re-renders everything downstream through
// refreshAll(). Rebuilt wholesale on every toggle rather than patched in
// place — cheap at the scale of "how many competitions can one team be in"
// (single digits, even for a cup-running side) and much simpler than
// tracking partial DOM updates.
function renderCompetitionsPanel() {
  const grid = document.getElementById('compsGrid');
  const entries = Object.entries((CUR_TEAM && CUR_TEAM.competitions) || {});
  document.getElementById('compsCount').textContent = entries.length || '';
  if (!entries.length) {
    grid.innerHTML = `<div class="empty-state">${LANG[CURLANG].noComps}</div>`;
    return;
  }
  entries.sort((a, b) => divRank(a[1].division_level) - divRank(b[1].division_level) || compDateMin(a[0]).localeCompare(compDateMin(b[0])));
  grid.innerHTML = entries.map(([compId, c]) => {
    const rec = compRecord(compId);
    const active = ACTIVE_COMP_KEYS.has(compId);
    const divBadge = c.division_level ? `<span class="comp-div-badge">${esc(divLabel(c.division_level))}</span>` : '';
    const pl = phaseLabel(c.phase);
    const phaseBadge = pl ? `<span class="comp-phase-badge">${esc(pl)}</span>` : '';
    const recordText = rec.played ? `${rec.w}-${rec.d}-${rec.l} &middot; ${rec.gf}:${rec.ga}` : '';
    let standingText = '';
    if (c.standing && c.standing.position) {
      standingText = c.standing.size
        ? `${esc(c.standing.position)} ${esc(LANG[CURLANG].of)} ${esc(c.standing.size)} &middot; ${esc(c.standing.points)} pts`
        : `${esc(c.standing.position)}. &middot; ${esc(c.standing.points)} pts`;
    }
    return `<button type="button" class="comp-card${active ? ' active' : ''}" data-comp="${esc(compId)}">
      <div class="cc-top">${divBadge}${phaseBadge}</div>
      <div class="cc-name">${esc(c.comp || '')}${c.grp ? ` <span style="font-weight:400; color:var(--ink-faint);">&middot; ${esc(c.grp)}</span>` : ''}</div>
      <div class="cc-record">${recordText}</div>
      ${standingText ? `<div class="cc-standing">${standingText}</div>` : ''}
    </button>`;
  }).join('');
  grid.querySelectorAll('.comp-card').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.getAttribute('data-comp');
      if (ACTIVE_COMP_KEYS.has(key)) ACTIVE_COMP_KEYS.delete(key); else ACTIVE_COMP_KEYS.add(key);
      refreshAll();
    });
  });
}

// Fixture-based record (W-D-L, goals, points/game) over whichever
// competitions are currently active — cheap, since `matches` is already
// loaded for every team card regardless of tab. Deliberately does NOT
// include lineup-stability here: that needs match_lineups data, which is
// lazily fetched only once the Состав tab opens (see team_rosters.py's
// docstring) — see renderRosterStats() instead, inside that tab.
function renderTeamStats(matches) {
  const strip = document.getElementById('teamStatsStrip');
  const played = matches.filter(m => m.status === 'finished');
  if (!played.length) { strip.innerHTML = ''; return; }
  let w = 0, d = 0, l = 0, gf = 0, ga = 0, pts = 0;
  played.forEach(m => {
    if (m.result === 'W') { w++; pts += 3; } else if (m.result === 'D') { d++; pts += 1; } else if (m.result === 'L') l++;
    const sf = Number(m.sf), sa = Number(m.sa);
    if (!isNaN(sf)) gf += sf;
    if (!isNaN(sa)) ga += sa;
  });
  const winPct = Math.round((w / played.length) * 100);
  const gd = gf - ga;
  const ppg = (pts / played.length).toFixed(2);
  const cell = (cls, num, lbl) => `<div class="stat-cell ${cls}"><div class="num">${num}</div><div class="lbl">${esc(lbl)}</div></div>`;
  strip.innerHTML =
    cell('', played.length, LANG[CURLANG].stPlayed) +
    cell('win', w, LANG[CURLANG].stWins) +
    cell('', d, LANG[CURLANG].stDraws) +
    cell('loss', l, LANG[CURLANG].stLosses) +
    cell('', `${winPct}%`, LANG[CURLANG].stWinPct) +
    cell('', `${gf}:${ga}`, LANG[CURLANG].stGoals) +
    cell('', (gd > 0 ? '+' : '') + gd, LANG[CURLANG].stGd) +
    cell('', ppg, LANG[CURLANG].stPpg);
}

function renderMatches(matches) {
  if (!matches.length) {
    document.getElementById('matchCount').textContent = '0';
    document.getElementById('matchBody').innerHTML =
      `<tr><td class="empty-state" colspan="5">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  document.getElementById('matchBody').innerHTML = matches.map(m => {
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

let CUR_SEASON = null, CUR_TEAM_ID = null, CUR_CLUB_SLUG = null, CUR_TEAM = null, ROSTER_PAYLOAD = null, ROSTER_LOADING = false;

// Which competitions (competition_id) are "on" — toggled via the cards in
// #compsGrid, defaults to every competition the team has. Everything below
// (match list, player-summary table, roster matrix, stability/win-rate
// stats) reads through visibleMatches() instead of CUR_TEAM.matches
// directly, so one flip re-scopes the whole page.
let ACTIVE_COMP_KEYS = new Set();
function compKey(m) { return m.comp_id; }
function visibleMatches() {
  return ((CUR_TEAM && CUR_TEAM.matches) || []).filter(m => ACTIVE_COMP_KEYS.has(compKey(m)));
}

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
  const matches = visibleMatches();
  if (!roster.length) {
    tbody.innerHTML = '';
    document.getElementById('summaryCount').textContent = '';
    return;
  }
  const fmt2 = v => v === null ? '—' : v.toFixed(2);
  tbody.innerHTML = roster.map(([pid, p]) => {
    const s = computeStats(pid, matches, lineups);
    const nameUrl = `player_card.html?season=${encodeURIComponent(CUR_SEASON)}&player=${encodeURIComponent(pid)}` +
      `&fromTeam=${encodeURIComponent(CUR_TEAM_ID)}&fromClub=${encodeURIComponent(CUR_CLUB_SLUG)}`;
    const appsDisplay = s.played
      ? `${s.apps}/${s.played} (${Math.round((s.appsPct || 0) * 100)}%)`
      : `${s.apps}/0`;
    const seasons = p.seasons;
    let seasonsDisplay = '—', seasonsSort = -1;
    if (seasons && seasons.y !== null && seasons.y !== undefined) {
      seasonsDisplay = `${seasons.x}/${seasons.y}` + (seasons.u ? ` <span class="uncertain-mark" title="${esc(LANG[CURLANG].seasonsUncertain)}">*</span>` : '');
      seasonsSort = seasons.y ? seasons.x / seasons.y : seasons.x;
    } else if (seasons) {
      seasonsSort = seasons.x;
      seasonsDisplay = String(seasons.x);
    }
    return `<tr>
      <td data-col="jersey" data-v="${p.jersey ? parseInt(p.jersey, 10) : ''}">${p.jersey ? esc(p.jersey) : '—'}</td>
      <td data-col="name" data-v="${esc(p.name)}"><a href="${nameUrl}">${esc(p.name)}</a></td>
      <td data-col="seasons" data-v="${seasonsSort}" data-label="${esc(seasonsDisplay.replace(/<[^>]+>/g, ''))}">${seasonsDisplay}</td>
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

// Continuity index: average Jaccard overlap (|A∩B|/|A∪B|) of the starting
// XI between each pair of consecutive *played* matches, in chronological
// order — the most intuitive of the stability formulas that fit what this
// data can actually support (no minutes/subs-timing data, only who started
// each match; see the roster_p/summary_p caveats above). 0 = a completely
// different XI every time, 1 = the exact same eleven start every match.
function computeStability(matches, lineups) {
  const played = matches.filter(m => m.status === 'finished' && lineups[m.match_id]);
  if (played.length < 2) return null;
  let sum = 0, n = 0;
  for (let i = 1; i < played.length; i++) {
    const startersOf = m => new Set(Object.entries(lineups[m.match_id] || {}).filter(([, c]) => c.start).map(([pid]) => pid));
    const prev = startersOf(played[i - 1]), cur = startersOf(played[i]);
    if (!prev.size || !cur.size) continue;
    let inter = 0;
    prev.forEach(p => { if (cur.has(p)) inter++; });
    sum += inter / (prev.size + cur.size - inter);
    n++;
  }
  return n ? sum / n : null;
}

function renderRosterStats(matches, lineups) {
  const strip = document.getElementById('rosterStatsStrip');
  const stability = computeStability(matches, lineups);
  const pct = stability === null ? '—' : `${Math.round(stability * 100)}%`;
  strip.innerHTML = `<div class="stat-cell" title="${esc(LANG[CURLANG].stStabilityHint)}">
    <div class="num">${pct}</div><div class="lbl">${esc(LANG[CURLANG].stStability)}</div>
  </div>`;
}

function renderMatrix() {
  const status = document.getElementById('matrixStatus');
  const scroll = document.getElementById('matrixScroll');
  const matches = visibleMatches();
  if (!matches.length) {
    scroll.innerHTML = `<div class="matrix-empty">${LANG[CURLANG].notFound}</div>`;
    document.getElementById('rosterStatsStrip').innerHTML = '';
    return;
  }
  const roster = Object.entries((ROSTER_PAYLOAD && ROSTER_PAYLOAD.roster) || {});
  if (!roster.length) {
    scroll.innerHTML = `<div class="matrix-empty">${LANG[CURLANG].notFound}</div>`;
    document.getElementById('rosterStatsStrip').innerHTML = '';
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
  renderRosterStats(matches, lineups);

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
      const gkCls = cell.gk ? ' mark-gk' : '';
      const goals = cell.goals ? `<span class="mark-goals">&#9917;${cell.goals}</span>` : '';
      const cards = (cell.cards || []).map(c => `<span class="mark-card ${cardClass(c)}"></span>`).join('');
      return `<td class="cell-mark"><span class="${markCls}${capCls}${gkCls}"></span>${goals}${cards}</td>`;
    }).join('');
    const nameUrl = `player_card.html?season=${encodeURIComponent(CUR_SEASON)}&player=${encodeURIComponent(pid)}` +
      `&fromTeam=${encodeURIComponent(CUR_TEAM_ID)}&fromClub=${encodeURIComponent(CUR_CLUB_SLUG)}`;
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

// Single re-render entry point for anything that changes which
// competitions are active (or, via main(), first load) — recomputes the
// competitions panel + top stats strip + matches table always, and the
// roster tab's own views only if that tab is the one currently open (no
// point re-rendering a hidden matrix, and it'd force-fetch the lineup
// data early if the tab was never opened).
function refreshAll() {
  const matches = visibleMatches();
  renderCompetitionsPanel();
  renderTeamStats(matches);
  renderMatches(matches);
  if (document.getElementById('paneRoster').classList.contains('active')) {
    renderMatrix();
    renderPlayerSummary();
  }
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
  CUR_SEASON = season; CUR_TEAM_ID = teamId; CUR_CLUB_SLUG = clubSlug;
  document.getElementById('seasonBadge').textContent = season || '';
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
  document.getElementById('clubName').innerHTML = payload.club
    ? `${esc(payload.club)} &middot; <a href="club_profile.html?clubname=${encodeURIComponent(payload.club)}">${CURLANG === 'ru' ? 'профиль клуба' : 'perfil de club'} &rarr;</a>`
    : '';
  if (!team) {
    document.getElementById('teamName').textContent = payload.club || '—';
    document.getElementById('matchBody').innerHTML =
      `<tr><td class="empty-state" colspan="5">${LANG[CURLANG].notFound}</td></tr>`;
    return;
  }
  document.getElementById('teamName').textContent = team.name;
  document.title = `${team.name} — RFFM`;
  CUR_TEAM = team;
  ACTIVE_COMP_KEYS = new Set(Object.keys(team.competitions || {}));
  refreshAll();
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
            .replace("%DATATABLE_JS%", DATATABLE_JS)
            .replace("%DIV_ORDER_JSON%", json.dumps(DIV_ORDER))
            .replace("%DIV_LABEL_RU_JSON%", json.dumps(DIV_LABEL_RU, ensure_ascii=False))
            .replace("%DIV_LABEL_ES_JSON%", json.dumps(DIV_LABEL_ES, ensure_ascii=False)))


def main():
    parser = argparse.ArgumentParser(description="RFFM team-card data + page")
    parser.add_argument("--season", default=None, help="build only this season's data (default: every season with a complete core crawl)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    seasons = [args.season] if args.season else None
    build_all(Path(__file__).parent.parent / args.output_dir, seasons)


def build_all(out_dir: Path, seasons: list[str] | None = None) -> None:
    # Every crawled season, by default — player_card.html's "show all
    # seasons" view links into this per-season JSON for any season a player
    # was registered in, not just the latest, so a latest-season-only build
    # left every older-season row pointing at data that was never published
    # (silently blank "Сводка", dead team-card links). ~450MB+ of JSON across
    # 8 seasons (matches.csv alone is 28-53 MB per season) is the accepted
    # cost; pass --season explicitly for a cheaper single-season build.
    seasons = seasons or list_seasons()
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
