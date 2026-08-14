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

import player_career
from club_division_map import DIV_LABEL_ES, DIV_LABEL_RU, GT_CODE, GT_SHORT, TIER_OF
from site_theme import (DATATABLE_CSS, DATATABLE_JS, FONT_LINKS, LANG_SWITCH_JS, THEME_INIT_JS,
                         THEME_SWITCH_JS, club_slug_map, switch_row_html)
from team_cards import build_club_team_cards, norm_id

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

    # team_id -> (canonical club name, slug), both keyed off team_cards.py's
    # own club universe above — NOT off this row's own club_name_raw. The
    # fichajugador endpoint (this CSV) and the core team-listing endpoint
    # (teams.csv, what build_club_team_cards() reads) report a club's name
    # differently often enough to matter (sponsor suffixes like "- CEIBA"
    # added/dropped, abbreviations, "(FS)" markers — ~20% of rows in a given
    # season in practice): joining by that free-text name instead of by the
    # already-known, reliable team_id silently drops the slug (None) for
    # every row where the two sides' text doesn't match byte-for-byte,
    # which breaks both the "Команда" link and the per-row "Сводка" fetch
    # (both require club_slug) with no visible error.
    tid_to_club: dict[str, str] = {}
    tid_to_slug: dict[str, str] = {}
    for club_name, teams_of_club in club_teams.items():
        slug = slug_by_club.get(club_name)
        for tid in teams_of_club:
            tid_to_club[tid] = club_name
            tid_to_slug[tid] = slug

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
        tid = norm_id(row.team_id)
        club = tid_to_club.get(tid) or clean(row.club_name_raw)
        player["rows"].append({
            "team": clean(row.team), "team_id": clean(row.team_id),
            "club": club, "club_slug": tid_to_slug.get(tid),
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

    print("Building player career-seasons index (X/Y seasons played)...")
    build_career_shards(out_dir, seasons)


def build_career_shards(out_dir: Path, seasons: list[str]) -> None:
    """One JSON per (player_id % SHARD_MOD) under data/player_seasons/ —
    {player_id: {"x": played, "y": eligible, "u": coverage_uncertain}} —
    same sharding as player_participation_<season>/ above, shared by
    player_card.html's own "Сезонов" stat and team_card.html's roster table
    (see player_career.py; team_rosters.py computes the same numbers
    independently rather than reading this file, since its own roster JSON
    already needs the same values inline and a cross-fetch here would just
    add a second network round-trip for no benefit)."""
    career = player_career.compute_career_index(seasons)
    coverage = player_career.load_fichajugador_coverage()
    shards: dict[int, dict[str, dict]] = {}
    for pid, c in career.items():
        x, y, uncertain = player_career.seasons_ratio(c["birth_year"], c["seasons"], seasons, coverage)
        shard = shards.setdefault(shard_of(pid), {})
        shard[pid] = {"x": x, "y": y, "u": uncertain}
    data_dir = out_dir / "data" / "player_seasons"
    data_dir.mkdir(parents=True, exist_ok=True)
    for shard_id, payload in shards.items():
        (data_dir / f"{shard_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
            encoding="utf-8")
    print(f"  {len(career)} players across {len(shards)} shards written to {data_dir}")


I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; ficha de jugador",
    "back": "&larr; Mapa de clubes",
    "backTeam": "&larr; Ficha de equipo",
    "loading": "Cargando…",
    "not_found": "No se encontraron datos de inscripción para este jugador.",
    "tab_reg": "Inscripciones",
    "tab_pmap": "Mapa de participación",
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

# Deliberately its own visual language, not the site's PT Sans/Oswald/green
# theme (site_theme.py CSS) — agreed with the user: this tab follows the
# approved standalone prototype's "scoreboard" look (Barlow Condensed/IBM
# Plex Mono/Inter, dark header, chalk-orange accent), scoped entirely under
# #pmapRoot so it can't leak into or clash with the rest of the page.
PMAP_CSS = r"""
#pmapRoot{
  --pm-ink:#0d151f; --pm-ink2:#1d2a38; --pm-paper:#fff; --pm-page:#e9edf1;
  --pm-rule:#dde3ea; --pm-rule2:#eef1f5; --pm-muted:#6b7784;
  --pm-field:#eaeef3; --pm-chalk:#b26a00; --pm-chalk-soft:#fdf1dd;
  --pm-cell:13px; --pm-gap:2px; --pm-lane:0px; --pm-band:18px; --pm-label:210px;
  --pm-sgap:calc(var(--pm-cell)/2 + var(--pm-gap));
  --pm-nw:38; --pm-ns:5;
  --pm-track:calc(var(--pm-nw)*var(--pm-cell) + (var(--pm-nw) - 1)*var(--pm-gap));
  --pm-lbl:min(12px, calc(var(--pm-cell) + 1px));
  font-family:'Inter',ui-sans-serif,system-ui,sans-serif; color:var(--pm-ink);
  background:var(--pm-page); border-radius:14px; padding:18px; margin-top:4px;
}
#pmapRoot *{box-sizing:border-box}
#pmapRoot .pm-cond{font-family:'Barlow Condensed',Inter,sans-serif;text-transform:uppercase;letter-spacing:.05em}
#pmapRoot .pm-mono{font-family:'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
#pmapRoot .pm-scoreboard{ background:var(--pm-ink);color:#fff;border-radius:14px;padding:16px 20px;
  display:flex;gap:24px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap; }
#pmapRoot .pm-sb-id .pm-kicker{font:600 11px/1 'Barlow Condensed';text-transform:uppercase;letter-spacing:.16em;color:#7f93a8}
#pmapRoot .pm-sb-id h3{font:700 26px/1.05 'Barlow Condensed';text-transform:uppercase;letter-spacing:.02em;margin:6px 0 3px;color:#fff}
#pmapRoot .pm-sb-id .pm-club{color:#9fb2c4;font-size:12.5px}
#pmapRoot .pm-sb-nums{display:flex;gap:20px;flex-wrap:wrap}
#pmapRoot .pm-num{min-width:56px}
#pmapRoot .pm-num b{display:block;font:600 22px/1 'IBM Plex Mono';letter-spacing:-.02em}
#pmapRoot .pm-num span{display:block;margin-top:4px;font:600 9.5px/1.2 'Barlow Condensed';text-transform:uppercase;letter-spacing:.12em;color:#8ba0b4}
#pmapRoot .pm-num.hi b{color:#ffc766}
#pmapRoot .pm-lede{margin:14px 2px 12px;max-width:760px;color:#41505f;font-size:13px}
#pmapRoot .pm-bar{ background:var(--pm-paper);border:1px solid var(--pm-rule);border-bottom:0;
  border-radius:12px 12px 0 0;padding:10px 12px; display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap; }
#pmapRoot .pm-grp{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
#pmapRoot .pm-grp>.pm-cap{font:600 9.5px/1 'Barlow Condensed';text-transform:uppercase;letter-spacing:.13em;color:#98a4b0;margin-right:2px}
#pmapRoot .pm-btn{ border:1px solid var(--pm-rule);background:#fff;border-radius:8px;padding:5px 9px;
  font:500 12px/1 Inter;color:#3d4b59;cursor:pointer;transition:.14s; }
#pmapRoot .pm-btn:hover{border-color:#b9c4d0;background:#f7f9fb}
#pmapRoot .pm-btn[aria-pressed="true"]{background:var(--pm-ink);border-color:var(--pm-ink);color:#fff}
#pmapRoot .pm-btn:disabled{opacity:.45;cursor:not-allowed}
#pmapRoot .pm-btn:disabled:hover{border-color:var(--pm-rule);background:#fff}
#pmapRoot .pm-seg{display:flex;border:1px solid var(--pm-rule);border-radius:8px;overflow:hidden}
#pmapRoot .pm-seg .pm-btn{border:0;border-radius:0;border-left:1px solid var(--pm-rule)}
#pmapRoot .pm-seg .pm-btn:first-child{border-left:0}
#pmapRoot .pm-swatch{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:5px;vertical-align:-1px}
#pmapRoot .pm-shell{ background:var(--pm-paper);border:1px solid var(--pm-rule);border-radius:0 0 12px 12px;
  overflow:auto;box-shadow:0 12px 30px rgba(16,32,48,.07);position:relative;max-height:70vh; }
#pmapRoot .pm-grid{ display:grid; grid-template-columns:var(--pm-label) repeat(var(--pm-ns), var(--pm-track));
  column-gap:var(--pm-sgap); padding:0 14px 0 0; min-width:min-content; }
#pmapRoot .pm-head{position:sticky;top:0;z-index:6;background:var(--pm-paper);padding-top:10px;box-shadow:0 1px 0 var(--pm-rule)}
#pmapRoot .pm-body{position:relative;padding-top:10px;padding-bottom:6px}
#pmapRoot .pm-foot{padding:8px 14px 12px;border-top:1px solid var(--pm-rule2)}
#pmapRoot .pm-stick{position:sticky;left:0;z-index:4;background:var(--pm-paper);padding-left:14px}
#pmapRoot .pm-head .pm-stick{z-index:7}
#pmapRoot .pm-sh{padding-bottom:7px}
#pmapRoot .pm-sh .pm-row1{display:flex;align-items:baseline;gap:7px}
#pmapRoot .pm-sh h4{font:700 17px/1 'Barlow Condensed';text-transform:uppercase;letter-spacing:.03em;margin:0;cursor:pointer}
#pmapRoot .pm-sh h4:hover{color:var(--pm-chalk)}
#pmapRoot .pm-pill{font:600 9.5px/1 'Barlow Condensed';text-transform:uppercase;letter-spacing:.1em;
  padding:3px 6px;border-radius:5px;background:var(--pm-chalk-soft);color:var(--pm-chalk)}
#pmapRoot .pm-sh .pm-age{font:500 10.5px/1 'IBM Plex Mono';color:#93a1af}
#pmapRoot .pm-months{display:grid;gap:var(--pm-gap);margin-top:8px;height:12px}
#pmapRoot .pm-mo{font:500 9px/12px 'IBM Plex Mono';color:#93a1af;text-transform:uppercase;
  white-space:nowrap;overflow:hidden;box-shadow:-1px 0 0 var(--pm-rule);padding-left:3px}
#pmapRoot .pm-mo.pm-first{box-shadow:none;padding-left:0}
#pmapRoot .pm-load{display:grid;gap:var(--pm-gap);height:22px;align-items:end;margin-top:5px;border-bottom:1px solid var(--pm-rule)}
#pmapRoot .pm-load i{display:block;background:#c3cdd8;border-radius:1px 1px 0 0;min-height:0}
#pmapRoot .pm-load i.pm-on{background:#8f9dab}
#pmapRoot .pm-placeholder{grid-column:1/-1;display:flex;align-items:center;justify-content:center;
  font:600 10.5px/1 'Barlow Condensed';text-transform:uppercase;letter-spacing:.08em;color:#a8b3be;
  background:repeating-linear-gradient(135deg,var(--pm-field),var(--pm-field) 6px,#e2e7ed 6px,#e2e7ed 12px);
  border-radius:4px;text-align:center;padding:4px}
#pmapRoot .pm-labels{display:grid;grid-template-columns:3px 24px 1fr;column-gap:6px}
#pmapRoot .pm-rail{border-radius:2px;background:#dbe2e9}
#pmapRoot .pm-rail.pm-own{background:var(--pm-chalk)}
#pmapRoot .pm-rl{display:flex;align-items:center;min-width:0;overflow:hidden;height:var(--pm-cell)}
#pmapRoot .pm-rl .pm-dv{font-family:'Barlow Condensed';text-transform:uppercase;letter-spacing:.04em;
  font-weight:600;font-size:var(--pm-lbl);line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#2b3947}
#pmapRoot .pm-lvl{display:flex;align-items:center;justify-content:center;height:var(--pm-cell);
  border-radius:4px;font:600 9.5px/1 'IBM Plex Mono'; background:#eef2f6;color:#7b8894}
#pmapRoot .pm-lvl.pm-own{background:var(--pm-chalk-soft);color:var(--pm-chalk)}
#pmapRoot .pm-lvl.pm-up{background:#0d151f;color:#fff}
#pmapRoot .pm-bandcap{display:flex;align-items:center;gap:6px;height:var(--pm-band);
  font:600 9px/1 'Barlow Condensed';text-transform:uppercase;letter-spacing:.12em;color:#9aa6b2}
#pmapRoot .pm-bandcap.pm-own{color:var(--pm-chalk)}
#pmapRoot .pm-bandcap.pm-zone{color:#5c6a78;border-top:2px solid #c7ceD6;padding-top:3px}
#pmapRoot .pm-track{display:grid;grid-template-columns:repeat(var(--pm-nw), var(--pm-cell));gap:var(--pm-gap);position:relative}
#pmapRoot .pm-span{grid-column:1/-1;position:relative}
#pmapRoot .pm-cell{background:var(--pm-field);border-radius:2px;position:relative;height:var(--pm-cell)}
#pmapRoot .pm-cell.pm-mo{box-shadow:-1px 0 0 rgba(13,21,31,.1)}
#pmapRoot .pm-cell.pm-play{display:flex;gap:1px;overflow:hidden;cursor:pointer}
#pmapRoot .pm-cell.pm-play i{flex:1;align-self:flex-end;border-radius:1px}
#pmapRoot .pm-cell.pm-info{cursor:help}
#pmapRoot .pm-cell.pm-play:hover,#pmapRoot .pm-cell.pm-play:focus-visible,#pmapRoot .pm-cell.pm-act{
  outline:2px solid var(--pm-ink);outline-offset:0;z-index:5;border-radius:2px}
#pmapRoot .pm-cell.pm-play:focus-visible{outline-color:var(--pm-chalk)}
#pmapRoot.pm-solo .pm-cell.pm-play{opacity:.16}
#pmapRoot.pm-solo .pm-cell.pm-play.pm-keep{opacity:1}
#pmapRoot.pm-nofill .pm-cell.pm-play i{height:100% !important}
#pmapRoot .pm-rib{position:absolute;height:var(--pm-gap);border-radius:2px;opacity:.85;pointer-events:none}
#pmapRoot .pm-rib b{position:absolute;top:0;bottom:0;width:1px;background:#fff;opacity:.9}
#pmapRoot .pm-lane{height:var(--pm-lane);overflow:hidden;position:relative}
#pmapRoot .pm-cl{position:absolute;top:0;height:var(--pm-lane);display:flex;align-items:center;gap:5px;
  font:600 9.5px/1 'Barlow Condensed';text-transform:uppercase;letter-spacing:.06em;
  color:#5c6a78;white-space:nowrap;overflow:hidden;cursor:pointer}
#pmapRoot .pm-cl:hover,#pmapRoot .pm-cl.pm-hl{color:var(--pm-ink)}
#pmapRoot .pm-cl s{text-decoration:none;width:4px;height:4px;border-radius:1px;flex:none}
#pmapRoot .pm-cl em{font-style:normal;color:#9aa6b2;font-family:'IBM Plex Mono';font-size:8.5px}
#pmapRoot .pm-water{position:absolute;left:0;right:0;height:0;border-top:1px dashed rgba(178,106,0,.55);pointer-events:none;z-index:2}
#pmapRoot .pm-cross{position:absolute;top:0;bottom:0;width:var(--pm-cell);background:rgba(13,21,31,.05);
  border-radius:2px;pointer-events:none;display:none}
#pmapRoot .pm-track.pm-hl .pm-cross{display:block}
#pmapRoot .pm-fs{font:500 10.5px/1.4 'IBM Plex Mono';color:#6b7784}
#pmapRoot .pm-fs b{color:var(--pm-ink);font-weight:600}
#pmapRoot .pm-fs .pm-tm{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:3px;vertical-align:-1px}
#pmapRoot .pm-legend{display:flex;gap:18px;flex-wrap:wrap;margin:14px 2px 0;color:#5c6a78;font-size:11.5px}
#pmapRoot .pm-legend .pm-li{display:flex;align-items:center;gap:6px}
#pmapRoot .pm-gl{width:12px;height:12px;border-radius:2px;background:var(--pm-field);position:relative;flex:none}
#pmapRoot .pm-gl.pm-full{background:#2f5fd0}
#pmapRoot .pm-gl.pm-split{display:flex;gap:1px;overflow:hidden}
#pmapRoot .pm-gl.pm-split i{flex:1;background:#2f5fd0}
#pmapRoot .pm-gl.pm-split i:last-child{background:#d95f9a}
#pmapRoot .pm-gl.pm-win{background:#dae4f5}
#pmapRoot .pm-note{margin:10px 2px 0;color:#7d8996;font-size:11.5px;max-width:900px}
#pmapRoot .pm-note code{font-family:'IBM Plex Mono';font-size:10.5px;background:#eef2f6;padding:1px 4px;border-radius:4px}
#pmapRoot .pm-empty{padding:26px;text-align:center;color:#8b98a4;font-size:13px}
.pm-tip{position:fixed;z-index:60;width:320px;background:#0d151f;color:#fff;border-radius:12px;
  padding:12px 14px 13px;box-shadow:0 22px 50px rgba(9,18,28,.34);pointer-events:none;
  opacity:0;transform:translateY(4px);transition:opacity .12s,transform .12s;
  font-family:'Inter',ui-sans-serif,sans-serif;}
.pm-tip.pm-on{opacity:1;transform:none}
.pm-tip h5{font:700 13.5px/1.2 'Barlow Condensed';text-transform:uppercase;letter-spacing:.04em;margin:0;color:#fff}
.pm-tip .pm-sub{font:500 10px/1.3 'IBM Plex Mono';color:#8ba0b4;margin-top:3px}
.pm-tip .pm-m{border-top:1px solid rgba(255,255,255,.13);margin-top:9px;padding-top:8px}
.pm-tip .pm-m .pm-hd{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600}
.pm-tip .pm-m .pm-hd s{text-decoration:none;width:8px;height:8px;border-radius:2px;flex:none}
.pm-tip .pm-m .pm-cp{font:500 9.5px/1.3 'IBM Plex Mono';color:#8ba0b4;margin:3px 0 5px}
.pm-tip .pm-kv{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:11px}
.pm-tip .pm-kv dt{color:#8ba0b4;margin:0}
.pm-tip .pm-kv dd{margin:0;font-weight:600;font-family:'IBM Plex Mono';font-size:10.5px}
.pm-tip .pm-flag{display:inline-block;margin-top:8px;padding:3px 6px;border-radius:5px;
  background:rgba(255,199,102,.16);color:#ffc766;font:600 9px/1 'Barlow Condensed';
  text-transform:uppercase;letter-spacing:.1em}
@media (max-width:700px){ #pmapRoot{--pm-label:140px; padding:12px} #pmapRoot .pm-scoreboard{padding:14px} #pmapRoot .pm-sb-id h3{font-size:21px} }
"""

# Client-side rendering engine for the "Карта участия" tab. Ported from the
# approved standalone prototype (participation_map_v2.html) but rebuilt on
# real data: row model = numbered age-relative ladder (DEBUTANTE..JUVENIL)
# plus two unranked zones (AFICIONADO+SENIOR merged "adult" zone,
# category_base=OTHER "outside the age grid" zone) instead of the
# prototype's flat hardcoded ROWS/DIVS/TEAMS — see the conversation this was
# designed in for the reasoning. Server (participation_map.py) ships raw
# per-match facts only; `level`/zone placement depends on which seasons are
# shown together for THIS player, so it's computed here, not server-side.
PMAP_JS = r"""
const PM = {};
PM.CATS = ['DEBUTANTE','PREBENJAMIN','BENJAMIN','ALEVIN','INFANTIL','CADETE','JUVENIL'];
PM.CAT_AGE = [[4,5],[6,7],[8,9],[10,11],[12,13],[14,15],[16,18]];
PM.ADULT_CATS = ['AFICIONADO','SENIOR'];
PM.CAT_NAME = {DEBUTANTE:'Debutante',PREBENJAMIN:'Prebenjamín',BENJAMIN:'Benjamín',ALEVIN:'Alevín',
  INFANTIL:'Infantil',CADETE:'Cadete',JUVENIL:'Juvenil',AFICIONADO:'Aficionado',SENIOR:'Senior',OTHER:'Otra'};
PM.HUES = ['#2a78d6','#eb6834','#1baf7a','#eda100','#e87ba4','#008300','#4a3aa7','#e34948'];
PM.DAY = 864e5;

function pmCatRank(cat){ return PM.CATS.indexOf(cat); }
function pmAgeCatRank(age){
  for (let i=0;i<PM.CAT_AGE.length;i++){ if (age>=PM.CAT_AGE[i][0] && age<=PM.CAT_AGE[i][1]) return i; }
  if (age < PM.CAT_AGE[0][0]) return 0;
  return -1;
}
function pmBucket(cat, seasonYear, birthYear){
  if (PM.ADULT_CATS.includes(cat)) return {zone:'ADULT'};
  const rank = pmCatRank(cat);
  if (rank < 0 || birthYear == null) return {zone:'OTHER'};
  const expRank = pmAgeCatRank(seasonYear - birthYear);
  if (expRank < 0) return {zone:'ADULT'};
  return {zone:'NUM', level: rank - expRank};
}

function pmMonday(d){ const x=new Date(d); const k=(x.getDay()+6)%7; x.setDate(x.getDate()-k); x.setHours(0,0,0,0); return x; }
function pmAnchor(y){ return pmMonday(new Date(y,8,1)); }
function pmWIdx(date, anchor){ return Math.round((pmMonday(date)-anchor)/(7*PM.DAY)); }
function pmWDate(anchor,i){ return new Date(anchor.getTime()+i*7*PM.DAY); }
function pmIsBreak(d){ return (d.getMonth()===11 && d.getDate()>=20) || (d.getMonth()===0 && d.getDate()<=6); }
const PM_MONTHS = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
const PM_MONTHS_ES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
function pmMonthName(m){ return (CURLANG === 'es' ? PM_MONTHS_ES : PM_MONTHS)[m]; }
function pmFmt(d){ return `${d.getDate()} ${pmMonthName(d.getMonth())}`; }
function pmFmtY(d){ return `${d.getDate()} ${pmMonthName(d.getMonth())} ${d.getFullYear()}`; }
function pmEsc(s){ return String(s ?? '').replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m])); }

// club -> stable base hue (hash on club name; club_id isn't in the
// participation-map payload, only club_name_raw, which is stable enough
// within one player's own career for this purpose), squad/team -> lightness
// step within that hue, in order of first appearance for THIS player (not
// a global registry — a per-chart-local assignment is enough, see dataviz
// skill's categorical-color guidance: fixed order, hashed to a validated set).
function pmHash(s){ let h=0; for (let i=0;i<s.length;i++){ h=(h*31 + s.charCodeAt(i))|0; } return Math.abs(h); }
function pmHexToHsl(hex){
  const n = parseInt(hex.slice(1),16), r=(n>>16&255)/255, g=(n>>8&255)/255, b=(n&255)/255;
  const mx=Math.max(r,g,b), mn=Math.min(r,g,b); let h,s,l=(mx+mn)/2;
  if (mx===mn){ h=s=0; } else {
    const d=mx-mn; s = l>0.5 ? d/(2-mx-mn) : d/(mx+mn);
    switch(mx){ case r: h=(g-b)/d+(g<b?6:0); break; case g: h=(b-r)/d+2; break; default: h=(r-g)/d+4; }
    h/=6;
  }
  return [h*360, s, l];
}
function pmHslToHex(h,s,l){
  h/=360;
  const hue2rgb=(p,q,t)=>{ if(t<0)t+=1; if(t>1)t-=1; if(t<1/6)return p+(q-p)*6*t; if(t<1/2)return q; if(t<2/3)return p+(q-p)*(2/3-t)*6; return p; };
  let r,g,b;
  if (s===0){ r=g=b=l; } else {
    const q = l<0.5 ? l*(1+s) : l+s-l*s, p = 2*l-q;
    r=hue2rgb(p,q,h+1/3); g=hue2rgb(p,q,h); b=hue2rgb(p,q,h-1/3);
  }
  const to255 = x => Math.round(x*255).toString(16).padStart(2,'0');
  return `#${to255(r)}${to255(g)}${to255(b)}`;
}
const PM_CLUB_HUE_CACHE = {};
function pmClubBaseColor(club){
  const key = club || '—';
  if (!(key in PM_CLUB_HUE_CACHE)) PM_CLUB_HUE_CACHE[key] = PM.HUES[pmHash(key) % PM.HUES.length];
  return PM_CLUB_HUE_CACHE[key];
}
const PM_SQUAD_ORDER = {};
function pmTeamColor(club, teamId){
  const base = pmClubBaseColor(club);
  const squadKey = club || '—';
  if (!(squadKey in PM_SQUAD_ORDER)) PM_SQUAD_ORDER[squadKey] = [];
  let order = PM_SQUAD_ORDER[squadKey].indexOf(teamId);
  if (order < 0) { PM_SQUAD_ORDER[squadKey].push(teamId); order = PM_SQUAD_ORDER[squadKey].length - 1; }
  if (order === 0) return base;
  const [h,s,l] = pmHexToHsl(base);
  const steps = [0, 0.12, -0.12, 0.22, -0.22];
  const delta = steps[order % steps.length];
  const nl = Math.min(0.72, Math.max(0.22, l + delta));
  return pmHslToHex(h, s, nl);
}
// Phase-within-family brightness step (regular season -> playoff -> final),
// layered on top of the team color above, not a separate hue — color still
// codes team-only (spec: "цвет кодирует исключительно команду"); this is a
// secondary CSS filter, not a palette slot.
const PM_PHASE_FILTERS = ['none','brightness(0.82)','brightness(0.66) saturate(1.15)','brightness(0.55) saturate(1.3)'];

function pmShardOf(pid){ return parseInt(pid,10) % SHARD_MOD; }
async function pmFetchSeason(season, pid){
  try {
    const res = await fetch(`data/participation_map_${season}/${pmShardOf(pid)}.json`);
    if (!res.ok) return undefined;
    const data = await res.json();
    return data[pid] || null;
  } catch (e) { return undefined; }
}

let PM_STATE = null;

async function initParticipationMap(pid){
  const root = document.getElementById('pmapRoot');
  root.innerHTML = `<div class="pm-empty" data-i18n="pm_loading">Загрузка карты участия…</div>`;
  if (!pid) return;
  const perSeason = {};
  let birthYear = null, name = null;
  await Promise.all(SEASONS.map(async season => {
    const p = await pmFetchSeason(season, pid);
    if (p === undefined) { perSeason[season] = undefined; return; } // no file at all for this season/shard
    if (p === null) { perSeason[season] = null; return; } // season has pmap data but not for this player
    perSeason[season] = p.rows || [];
    if (birthYear == null && p.birth_year) birthYear = parseInt(p.birth_year, 10);
    if (!name) name = p.name;
  }));
  const anyRealRows = Object.values(perSeason).some(v => v && v.length);
  PM_STATE = { pid, birthYear, name, perSeason, filterTeam: 'all', lane: false, fillByMinutes: false };
  if (!anyRealRows) {
    root.innerHTML = `<div class="pm-empty" data-i18n="pm_no_acta">Для сезонов этого игрока нет протоколов матчей (acta_partido) — карта участия недоступна.</div>`;
    return;
  }
  pmRender();
}

function pmAllRows(){
  const out = [];
  Object.keys(PM_STATE.perSeason).forEach(season => {
    const rows = PM_STATE.perSeason[season];
    if (!rows) return;
    const y = parseInt(season.slice(0,4), 10);
    rows.forEach(r => out.push(Object.assign({_season: season, _seasonYear: y}, r)));
  });
  return out;
}

function pmBuildRows(allRows){
  const map = new Map();
  allRows.forEach(r => {
    const b = pmBucket(r.cat, r._seasonYear, PM_STATE.birthYear);
    const div = r.div || 'OTHER';
    const key = b.zone === 'NUM' ? `N${b.level}|${div}` : `${b.zone}|${div}`;
    r._bucket = b; r._rowKey = key;
    if (!map.has(key)) map.set(key, {key, zone:b.zone, level: b.zone==='NUM'?b.level:null, div,
      tier: (TIER_OF[div] ?? null)});
  });
  const rows = [...map.values()];
  const bo = z => z==='OTHER'?0 : z==='ADULT'?1 : 2;
  rows.sort((a,b) => bo(a.zone)-bo(b.zone) || ((b.level??0)-(a.level??0)) || ((a.tier??99)-(b.tier??99)) || a.div.localeCompare(b.div));
  return rows;
}

function pmBuildTPL(rows){
  const tpl = [];
  const push = k => { tpl.push(k); return tpl.length; };
  let prevBlock = null;
  rows.forEach(r => {
    const blockKey = r.zone==='NUM' ? `N${r.level}` : r.zone;
    if (blockKey !== prevBlock){ r.bandRow = push('band'); prevBlock = blockKey; }
    r.laneRow = push('lane');
    r.cellRow = push('cell');
  });
  return tpl;
}
function pmTopOf(tpl, idx){
  let band=0,lane=0,cell=0;
  for (let i=0;i<idx-1;i++){ if (tpl[i]==='band') band++; else if (tpl[i]==='lane') lane++; else cell++; }
  return `calc(var(--pm-band)*${band} + var(--pm-lane)*${lane} + var(--pm-cell)*${cell} + var(--pm-gap)*${(idx-1)})`;
}
function pmBottomOfCell(tpl, r){ return `calc(${pmTopOf(tpl, r.cellRow)} + var(--pm-cell))`; }

function pmLevelName(l){
  if (CURLANG === 'es') return l===0?'Categoría propia' : l>0?`${l} categoría(s) por encima`:`${-l} categoría(s) por debajo`;
  return l===0 ? 'Своя возрастная категория' : l>0 ? `На ${l} категори${l===1?'ю':'и'} старше` : `На ${-l} категори${-l===1?'ю':'и'} младше`;
}
function pmZoneName(zone){
  if (zone==='ADULT') return CURLANG==='es' ? 'Nivel adulto (fuera de la escalera)' : 'Взрослый уровень (вне лестницы)';
  return CURLANG==='es' ? 'Fuera de la cuadrícula de edad' : 'Вне возрастной сетки';
}
function pmDivName(div){ return (CURLANG==='ru' ? DIV_LABEL_RU : DIV_LABEL_ES)[div] || div; }

const PM_COL = i => `calc((var(--pm-cell) + var(--pm-gap)) * ${i})`;
const PM_WIDTH = n => `calc(var(--pm-cell)*${n} + var(--pm-gap)*${Math.max(1,n) - 1})`;

function pmRender(){
  const root = document.getElementById('pmapRoot');
  const allRows = pmAllRows();
  // Every season this player has a registration for (SEASONS, same list the
  // "Заявки" tab uses) stays on the axis, even ones with no participation-map
  // rows at all — whether that's because acta_partido was never crawled for
  // that season (perSeason[s] === undefined) or it was crawled but this
  // player has zero protocol matches in it (perSeason[s] === null / []) is
  // not distinguished in the placeholder — both render as "no data this
  // season" rather than silently dropping the column (see conversation:
  // the season axis must not break).
  const seasonsWithData = SEASONS;
  if (!allRows.length){
    root.innerHTML = `<div class="pm-empty" data-i18n="pm_empty">У этого игрока нет данных протоколов матчей (acta_partido) ни в одном сезоне.</div>`;
    return;
  }
  const ROWS = pmBuildRows(allRows);
  const TPL = pmBuildTPL(ROWS);
  const ROW_TPL = TPL.map(k => k==='band'?'var(--pm-band)':k==='lane'?'var(--pm-lane)':'var(--pm-cell)').join(' ');

  // per-season calendar window: own anchor (real Sept-1-of-that-year Monday),
  // shared NW (week count) across every season shown, so columns compare
  // visually — the widest season's own natural span sets NW for all.
  const seasonMeta = {};
  let NW = 20;
  seasonsWithData.forEach(season => {
    const rows = PM_STATE.perSeason[season] || [];
    const y = parseInt(season.slice(0,4),10);
    const anchor = pmAnchor(y);
    if (!rows.length){ seasonMeta[season] = {anchor, w0:0, nw:0, y}; return; }
    const dates = rows.map(r => new Date(r.date));
    const w0 = Math.max(0, pmWIdx(new Date(Math.min(...dates)), anchor) - 1);
    const w1 = pmWIdx(new Date(Math.max(...dates)), anchor) + 1;
    seasonMeta[season] = {anchor, w0, nw: w1-w0+1, y};
    NW = Math.max(NW, w1-w0+1);
  });
  root.style.setProperty('--pm-nw', NW);
  root.style.setProperty('--pm-ns', seasonsWithData.length);

  const usedTeams = [...new Set(allRows.map(r => r.tid))];
  const teamMeta = {};
  allRows.forEach(r => { if (!teamMeta[r.tid]) teamMeta[r.tid] = {name: r.team, club: r.club, color: pmTeamColor(r.club, r.tid)}; });

  // index: rowKey|season|week -> matches
  const CELLS = new Map();
  allRows.forEach(r => {
    const meta = seasonMeta[r._season]; if (!meta) return;
    const w = pmWIdx(new Date(r.date), meta.anchor);
    const k = `${r._rowKey}§${r._season}§${w}`;
    if (!CELLS.has(k)) CELLS.set(k, []);
    CELLS.get(k).push(r);
  });

  root.innerHTML = pmBuildScoreboard(allRows) + pmBuildBar(usedTeams, teamMeta) +
    `<div class="pm-shell" id="pmShell">
      <div class="pm-grid pm-head" id="pmHead"></div>
      <div class="pm-grid pm-body" id="pmBody"></div>
      <div class="pm-grid pm-foot" id="pmFoot"></div>
    </div>` + pmBuildLegend() + `<div class="pm-tip" id="pmTip" role="tooltip" aria-hidden="true"></div>`;

  PM_CTX = {CELLS, seasonMeta, teamMeta, ROWS, familiesById:{}};
  pmRenderHead(seasonsWithData, seasonMeta, NW);
  pmRenderBody(ROWS, TPL, ROW_TPL, seasonsWithData, seasonMeta, NW, CELLS, teamMeta);
  pmRenderFoot(seasonsWithData, allRows);
  pmWireControls(usedTeams, teamMeta);
  pmWireTooltip();
}
let PM_CTX = {};

function pmBuildScoreboard(allRows){
  const played = allRows.filter(r => r.start || r.sub);
  const clubs = new Set(allRows.map(r => r.club).filter(Boolean));
  const teams = new Set(allRows.map(r => r.tid));
  const goals = played.reduce((s,r) => s + (r.goals||0), 0);
  const up = played.filter(r => r._bucket && r._bucket.zone==='NUM' && r._bucket.level > 0).length;
  const seasons = new Set(allRows.map(r => r._season)).size;
  const nums = CURLANG==='es'
    ? [[seasons,'temporadas'],[clubs.size,'clubes'],[teams.size,'equipos'],[played.length,'partidos'],[goals,'goles'],[up,'con mayores',1]]
    : [[seasons,'сезонов'],[clubs.size,'клубов'],[teams.size,'команд'],[played.length,'матчей'],[goals,'голов'],[up,'за старших',1]];
  const numsHtml = nums.map(([a,b,hi]) => `<div class="pm-num${hi?' hi':''}"><b class="pm-mono">${a}</b><span>${pmEsc(b)}</span></div>`).join('');
  const latest = allRows.reduce((a,b) => (b._season > a._season ? b : a), allRows[0]);
  const clubSub = CURLANG==='es'
    ? `Ahora: <b>${pmEsc(latest.team||'—')}</b>`
    : `Сейчас: <b>${pmEsc(latest.team||'—')}</b>`;
  return `<div class="pm-scoreboard">
    <div class="pm-sb-id">
      <div class="pm-kicker pm-cond">RFFM &middot; ${pmEsc(PM_STATE.name||'')}</div>
      <h3>${CURLANG==='es'?'Mapa de participación':'Карта участия'}</h3>
      <div class="pm-club">${clubSub}${PM_STATE.birthYear ? ` &middot; ${PM_STATE.birthYear}` : ''}</div>
    </div>
    <div class="pm-sb-nums">${numsHtml}</div>
  </div>
  <p class="pm-lede">${CURLANG==='es'
    ? 'Cada casilla es una <b>semana natural</b> (lunes-domingo). Las filas se alinean por categoría de edad relativa a la propia — todo por encima de la línea naranja se jugó con mayores.'
    : 'Каждый квадрат — <b>календарная неделя</b> (понедельник-воскресенье). Строки выровнены по возрастной категории относительно собственного возраста — всё выше оранжевой линии сыграно за старших.'}</p>`;
}

function pmBuildBar(usedTeams, teamMeta){
  const teamBtns = `<button type="button" class="pm-btn" data-pm-team="all" aria-pressed="true">${CURLANG==='es'?'Todos':'Все'}</button>` +
    usedTeams.map(t => `<button type="button" class="pm-btn" data-pm-team="${pmEsc(t)}" aria-pressed="false">
      <span class="pm-swatch" style="background:${teamMeta[t].color}"></span>${pmEsc(teamMeta[t].name||t)}</button>`).join('');
  return `<div class="pm-bar">
    <div class="pm-grp"><span class="pm-cap">${CURLANG==='es'?'Equipo':'Команда'}</span>${teamBtns}</div>
    <div class="pm-grp">
      <div class="pm-seg">
        <button type="button" class="pm-btn" id="pmLanes" aria-pressed="false">${CURLANG==='es'?'Nombres de torneos':'Названия турниров'}</button>
        <button type="button" class="pm-btn" id="pmFill" aria-pressed="false" disabled title="${CURLANG==='es'?'En la fuente de datos no hay minutos jugados por partido':'В источнике нет данных о сыгранных минутах по матчу'}">${CURLANG==='es'?'Relleno por minutos':'Заливка по минутам'}</button>
      </div>
      <div class="pm-seg" id="pmZoom">
        <button type="button" class="pm-btn" data-pm-cell="10">S</button>
        <button type="button" class="pm-btn" data-pm-cell="13" aria-pressed="true">M</button>
        <button type="button" class="pm-btn" data-pm-cell="17">L</button>
      </div>
    </div>
  </div>`;
}

function pmBuildLegend(){
  // No "в заявке, не вышел"/bench-dot legend item: match_lineups only ever
  // carries rows for players who were is_starter or is_substitute, and this
  // build treats both as played (substitutions aren't modeled in the source
  // — see DATA_DICTIONARY.md), so that third state cannot occur here.
  const L = CURLANG==='es' ? {
    full:'partido jugado (titular o suplente)', split:'2 partidos o 2 equipos en la semana',
    win:'competición en curso', none:'sin partidos',
    note:'Los nombres de torneo solo se muestran si el jugador disputó <code>≥20%</code> de los partidos del equipo y <code>≥2</code> partidos. Los minutos jugados no están en la fuente de datos — el relleno de la casilla es siempre completo.'
  } : {
    full:'сыграл матч (старт или замена)', split:'2 матча или 2 команды за неделю',
    win:'соревнование идёт', none:'матчей нет',
    note:'Названия турниров подписываются, только если игрок сыграл <code>≥20%</code> матчей команды и <code>≥2</code> матча. Сыгранных минут в источнике нет — заливка ячейки всегда полная.'
  };
  return `<div class="pm-legend">
    <div class="pm-li"><span class="pm-gl pm-full"></span>${L.full}</div>
    <div class="pm-li"><span class="pm-gl pm-split"><i></i><i></i></span>${L.split}</div>
    <div class="pm-li"><span class="pm-gl pm-win"></span>${L.win}</div>
    <div class="pm-li"><span class="pm-gl"></span>${L.none}</div>
  </div>
  <p class="pm-note">${L.note}</p>`;
}

function pmRenderHead(seasons, seasonMeta, NW){
  const head = document.getElementById('pmHead');
  let h = `<div class="pm-stick pm-sh"><div class="pm-row1"><span class="pm-cond" style="font:600 9.5px/1 'Barlow Condensed';text-transform:uppercase;letter-spacing:.12em;color:#98a4b0">${CURLANG==='es'?'Nivel · división':'Уровень · дивизион'}</span></div>
    <div class="pm-months" style="grid-template-columns:1fr"><span class="pm-mo pm-first">${CURLANG==='es'?'semana lun-dom':'неделя пн-вс'}</span></div>
    <div class="pm-load" style="grid-template-columns:1fr"></div></div>`;
  seasons.forEach(season => {
    const meta = seasonMeta[season];
    if (!meta.nw){
      h += `<div class="pm-sh"><div class="pm-row1"><h4 data-pm-jump="${season}">${season}</h4><span class="pm-pill" style="background:#e2e7ed;color:#8b98a4">${CURLANG==='es'?'sin protocolos':'нет протоколов'}</span></div>
        <div class="pm-months" style="height:auto"></div><div class="pm-load"></div></div>`;
      return;
    }
    let mo = '', run = null;
    for (let i=0;i<NW;i++){
      const d = pmWDate(meta.anchor, meta.w0+i); d.setDate(d.getDate()+3);
      if (!run || run.m !== d.getMonth()){ if (run) mo += pmCellMonth(run); run = {m:d.getMonth(), a:i, n:1, first:!mo}; }
      else run.n++;
    }
    mo += pmCellMonth(run);
    function pmCellMonth(r){ return `<span class="pm-mo${r.first?' pm-first':''}" style="grid-column:${r.a+1}/span ${r.n}">${pmMonthName(r.m)}</span>`; }
    const rows = PM_STATE.perSeason[season] || [];
    const per = new Array(NW).fill(0);
    rows.forEach(r => { const w = pmWIdx(new Date(r.date), meta.anchor) - meta.w0; if (w>=0 && w<NW) per[w]++; });
    const mx = Math.max(1, ...per);
    const bars = per.map(v => `<i class="${v?'pm-on':''}" style="height:${v?Math.max(18,v/mx*100):0}%"></i>`).join('');
    const age = PM_STATE.birthYear ? `${meta.y - PM_STATE.birthYear}` : '';
    h += `<div class="pm-sh">
      <div class="pm-row1"><h4 data-pm-jump="${season}">${season}</h4>${age ? `<span class="pm-age pm-mono">${age} ${CURLANG==='es'?'años':'лет'}</span>` : ''}</div>
      <div class="pm-months" style="grid-template-columns:repeat(${NW},var(--pm-cell))">${mo}</div>
      <div class="pm-load" style="grid-template-columns:repeat(${NW},var(--pm-cell))">${bars}</div>
    </div>`;
  });
  head.innerHTML = h;
}

function pmRenderBody(ROWS, TPL, ROW_TPL, seasons, seasonMeta, NW, CELLS, teamMeta){
  const body = document.getElementById('pmBody');
  let lab = `<div class="pm-stick pm-labels" style="grid-template-rows:${ROW_TPL};row-gap:var(--pm-gap)">`;
  let prevBlock = null;
  ROWS.forEach(r => {
    const blockKey = r.zone==='NUM' ? `N${r.level}` : r.zone;
    if (blockKey !== prevBlock){
      const own = r.zone==='NUM' && r.level===0;
      const capText = r.zone==='NUM' ? pmLevelName(r.level) : pmZoneName(r.zone);
      const cls = r.zone==='NUM' ? (own?' pm-own':'') : ' pm-zone';
      lab += `<div class="pm-bandcap${cls}" style="grid-row:${r.bandRow};grid-column:1/-1">${pmEsc(capText)}</div>`;
      prevBlock = blockKey;
    }
  });
  // rail spans per contiguous NUM block only (own-level rail highlight)
  ROWS.forEach((r,i) => {
    const own = r.zone==='NUM' && r.level===0;
    const lv = r.zone!=='NUM' ? '' : (r.level===0?'pm-own':r.level>0?'pm-up':'');
    const lvText = r.zone==='NUM' ? (r.level>0?'+'+r.level:String(r.level)) : (r.zone==='ADULT'?'A':'—');
    lab += `<div class="pm-lvl ${lv}" style="grid-row:${r.cellRow};grid-column:2" title="${pmEsc(r.zone==='NUM'?pmLevelName(r.level):pmZoneName(r.zone))}">${lvText}</div>`;
    lab += `<div class="pm-rl" style="grid-row:${r.cellRow};grid-column:3" title="${pmEsc(pmDivName(r.div))}"><span class="pm-dv">${pmEsc(pmDivName(r.div))}</span></div>`;
  });
  lab += `</div>`;

  let cols = '';
  seasons.forEach(season => {
    const meta = seasonMeta[season];
    let t = `<div class="pm-track" data-pm-season="${season}" style="grid-template-rows:${ROW_TPL}">`;
    if (!meta.nw){
      t += `<div class="pm-placeholder" style="grid-row:1/-1">${CURLANG==='es'?'Temporada sin protocolos de partido (acta_partido)':'Сезон без протоколов матчей (acta_partido)'}</div>`;
      t += `</div>`; cols += t; return;
    }
    t += `<div class="pm-cross"></div>`;
    ROWS.forEach(r => {
      const cellRowsAll = [];
      for (let i=0;i<NW;i++){
        const w = meta.w0+i;
        const ms = CELLS.get(`${r.key}§${season}§${w}`) || [];
        ms.forEach(m => cellRowsAll.push(Object.assign({_w:w}, m)));
      }
      // ribbons: competitions -> families (same team, adjacent/overlapping weeks)
      const comps = pmCompWindows(cellRowsAll);
      const families = pmBuildFamilies(comps);
      families.forEach((fam,fi) => {
        fam.id = `${r.key}__${season}__${fi}`;
        fam.row = r; fam.season = season;
        fam.comps.sort((a,b) => a.w0-b.w0);
        PM_CTX.familiesById[fam.id] = fam;
        fam.comps.forEach((c,ci) => {
          const a = Math.max(0, c.w0-meta.w0), b = Math.min(NW-1, c.w1-meta.w0);
          const color = teamMeta[c.tid] ? teamMeta[c.tid].color : '#8895a1';
          const filt = PM_PHASE_FILTERS[Math.min(ci, PM_PHASE_FILTERS.length-1)];
          t += `<div class="pm-rib" data-pm-family="${fam.id}" style="background:${color};filter:${filt};top:${pmBottomOfCell(TPL,r)};left:${PM_COL(a)};width:${PM_WIDTH(b-a+1)}">${ci>0?'<b></b>':''}</div>`;
        });
      });
      // labels: one per family, shown only if any comp in it clears 20%/>=2
      t += `<div class="pm-span pm-lane" style="grid-row:${r.laneRow}">`;
      families.forEach(fam => {
        const qualifies = fam.comps.some(c => c.tm>0 && c.apps/c.tm>=0.2 && c.apps>=2);
        if (!qualifies) return;
        const dom = fam.comps.reduce((p,c)=>c.apps>p.apps?c:p, fam.comps[0]);
        const a = Math.max(0, fam.w0-meta.w0), b = Math.min(NW-1, fam.w1-meta.w0);
        const pct = dom.tm ? Math.round(dom.apps/dom.tm*100) : 0;
        const color = teamMeta[dom.tid] ? teamMeta[dom.tid].color : '#8895a1';
        t += `<div class="pm-cl" data-pm-family="${fam.id}" style="left:${PM_COL(a)};width:${PM_WIDTH(b-a+1)}">
          <s style="background:${color}"></s>${pmEsc(dom.comp||'')} <em>${dom.apps}/${dom.tm} · ${pct}%</em></div>`;
      });
      t += `</div>`;
      for (let i=0;i<NW;i++){
        const w = meta.w0+i;
        const d = pmWDate(meta.anchor, w), thu = new Date(d.getTime()+3*PM.DAY);
        const moStart = thu.getDate() <= 7;
        const ms = CELLS.get(`${r.key}§${season}§${w}`) || [];
        const famIds = [...new Set(comps.filter(c => w>=c.w0 && w<=c.w1).map(c => {
          const fam = families.find(f => f.comps.includes(c)); return fam ? fam.id : null;
        }).filter(Boolean))];
        const cls = ['pm-cell']; let st = `grid-row:${r.cellRow};`, inner = '', att = ` data-pm-i="${i}"`;
        if (moStart) cls.push('pm-mo');
        if (ms.length){
          cls.push('pm-play');
          inner = ms.slice(0,3).map(m => `<i style="background:${teamMeta[m.tid]?teamMeta[m.tid].color:'#8895a1'};height:100%"></i>`).join('');
          cls.push(...[...new Set(ms.map(m => 'f-'+m.tid))]);
          att += ` tabindex="0" role="button" aria-label="${pmEsc(pmAriaOf(ms,d))}"`;
        } else {
          const activeComp = comps.find(c => w>=c.w0 && w<=c.w1);
          if (activeComp){ cls.push('pm-info'); st += `background:${pmTint(teamMeta[activeComp.tid]?teamMeta[activeComp.tid].color:'#8895a1')};`; }
        }
        if (ms.length || cls.includes('pm-info')) att += ` data-pm-k="${r.key}§${season}§${w}"`;
        if (famIds.length) att += ` data-pm-cellfam="${famIds.join(' ')}"`;
        t += `<div class="${cls.join(' ')}" style="${st}"${att}>${inner}</div>`;
      }
    });
    t += `</div>`;
    cols += t;
  });
  body.innerHTML = lab + cols;

  // "own age" reference line
  const own0 = ROWS.find(r => r.zone==='NUM' && r.level===0);
  const hasAbove = ROWS.some(r => (r.zone==='NUM' && r.level>0) || r.zone==='ADULT' || r.zone==='OTHER');
  if (own0 && hasAbove){
    const line = document.createElement('div');
    line.className = 'pm-water';
    line.style.top = `calc(${pmTopOf(TPL, own0.bandRow)} + var(--pm-band)/2 + 10px)`;
    body.appendChild(line);
  }
}

function pmCompWindows(cellRows){
  const byComp = new Map();
  cellRows.forEach(r => {
    if (!byComp.has(r.comp_id)) byComp.set(r.comp_id, {
      comp_id:r.comp_id, comp:r.comp, tid:r.tid, apps:0, tm:r.tm||0,
      matches:[], w0:Infinity, w1:-Infinity,
    });
    const c = byComp.get(r.comp_id);
    c.apps++; c.matches.push(r);
    c.w0 = Math.min(c.w0, r._w); c.w1 = Math.max(c.w1, r._w);
  });
  return [...byComp.values()];
}
function pmBuildFamilies(comps){
  const sorted = [...comps].sort((a,b) => a.w0-b.w0);
  const families = [];
  sorted.forEach(c => {
    const last = families[families.length-1];
    if (last && last.tid === c.tid && c.w0 <= last.w1+1){
      last.w1 = Math.max(last.w1, c.w1); last.comps.push(c);
    } else {
      families.push({tid:c.tid, w0:c.w0, w1:c.w1, comps:[c]});
    }
  });
  return families;
}
function pmTint(hex){
  const n = parseInt(hex.slice(1),16), r=n>>16&255, g=n>>8&255, b=n&255, k=.12;
  const mix=(x,base)=>Math.round(x*k+base*(1-k));
  return `rgb(${mix(r,234)},${mix(g,238)},${mix(b,243)})`;
}
function pmAriaOf(ms,d){
  const g = ms.reduce((s,m)=>s+(m.goals||0),0);
  const teams = [...new Set(ms.map(m=>m.team))].join(', ');
  return CURLANG==='es'
    ? `Semana ${pmFmtY(d)}: ${ms.length} partido(s) con ${teams}${g?`, goles: ${g}`:''}`
    : `Неделя ${pmFmtY(d)}: ${ms.length} матч(а) за ${teams}${g?`, голов: ${g}`:''}`;
}

function pmRenderFoot(seasons, allRows){
  const foot = document.getElementById('pmFoot');
  let f = `<div class="pm-stick pm-fs">${CURLANG==='es'?'Итого':'Итого'}</div>`;
  seasons.forEach(season => {
    const rows = (PM_STATE.perSeason[season] || []);
    const gl = rows.reduce((s,r)=>s+(r.goals||0),0);
    const tms = [...new Set(rows.map(r=>r.tid))];
    const teamMeta = {}; allRows.forEach(r => { if(!teamMeta[r.tid]) teamMeta[r.tid]={color:pmTeamColor(r.club,r.tid), name:r.team}; });
    const up = rows.filter(r => { const b = pmBucket(r.cat, parseInt(season.slice(0,4),10), PM_STATE.birthYear); return b.zone==='NUM' && b.level>0; }).length;
    f += `<div class="pm-fs">${tms.map(t=>`<span class="pm-tm" style="background:${teamMeta[t]?teamMeta[t].color:'#8895a1'}" title="${pmEsc(teamMeta[t]?teamMeta[t].name:'')}"></span>`).join('')}
      <b>${rows.length}</b> ${CURLANG==='es'?'part.':'матч.'} · <b>${gl}</b> ${CURLANG==='es'?'gol.':'гол.'}${up?` · <b>${up}</b> ${CURLANG==='es'?'con mayores':'за старших'}`:''}</div>`;
  });
  foot.innerHTML = f;
}

function pmWireControls(usedTeams, teamMeta){
  const root = document.getElementById('pmapRoot');
  root.querySelectorAll('[data-pm-team]').forEach(btn => {
    btn.addEventListener('click', () => {
      root.querySelectorAll('[data-pm-team]').forEach(b => b.setAttribute('aria-pressed', String(b===btn)));
      const t = btn.getAttribute('data-pm-team');
      root.classList.toggle('pm-solo', t !== 'all');
      root.querySelectorAll('.pm-cell.pm-play').forEach(c => c.classList.toggle('pm-keep', t==='all' || c.classList.contains('f-'+t)));
    });
  });
  const lanesBtn = document.getElementById('pmLanes');
  lanesBtn.addEventListener('click', () => {
    const on = lanesBtn.getAttribute('aria-pressed') === 'true';
    lanesBtn.setAttribute('aria-pressed', String(!on));
    root.style.setProperty('--pm-lane', on ? '0px' : '15px');
  });
  document.getElementById('pmZoom').querySelectorAll('[data-pm-cell]').forEach(btn => {
    btn.addEventListener('click', () => {
      root.querySelectorAll('[data-pm-cell]').forEach(b => b.setAttribute('aria-pressed', String(b===btn)));
      root.style.setProperty('--pm-cell', btn.getAttribute('data-pm-cell')+'px');
    });
  });
  root.querySelectorAll('[data-pm-jump]').forEach(h => {
    h.addEventListener('click', () => {
      const season = h.getAttribute('data-pm-jump');
      const shell = document.getElementById('pmShell');
      const track = shell.querySelector(`.pm-track[data-pm-season="${season}"]`);
      if (track) shell.scrollTo({left: track.offsetLeft - parseFloat(getComputedStyle(root).getPropertyValue('--pm-label')) - 24,
        behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'auto' : 'smooth'});
    });
  });
}

function pmWeekCard(key){
  const [rk, season, w] = key.split('§');
  const meta = PM_CTX.seasonMeta[season];
  const a = pmWDate(meta.anchor, +w), b = new Date(a.getTime()+6*PM.DAY);
  const ms = (PM_CTX.CELLS.get(key) || []).sort((x,y) => new Date(x.date)-new Date(y.date));
  if (!ms.length){
    return `<h5>${CURLANG==='es'?'Semana':'Неделя'} ${pmFmt(a)} — ${pmFmtY(b)}</h5>
      <div class="pm-sub">${CURLANG==='es'?'temporada':'сезон'} ${season} &middot; ${CURLANG==='es'?'sin datos de juego':'без игрового времени'}</div>
      <div class="pm-m"><div class="pm-hd" style="font-weight:500">${CURLANG==='es'?'La competición estaba en curso, sin datos del jugador esta semana':'Соревнование шло, данных по игроку на этой неделе нет'}</div></div>`;
  }
  let html = `<h5>${CURLANG==='es'?'Semana':'Неделя'} ${pmFmt(a)} — ${pmFmtY(b)}</h5>
    <div class="pm-sub">${CURLANG==='es'?'temporada':'сезон'} ${season} &middot; ${ms.length} ${CURLANG==='es'?'partido(s)':'матч(а)'}</div>`;
  ms.forEach(m => {
    const color = PM_CTX.teamMeta[m.tid] ? PM_CTX.teamMeta[m.tid].color : '#8895a1';
    const us = m.team || '—', them = m.opp || '—';
    const line = m.home ? `${us} ${m.gf ?? '?'}:${m.ga ?? '?'} ${them}` : `${them} ${m.ga ?? '?'}:${m.gf ?? '?'} ${us}`;
    html += `<div class="pm-m">
      <div class="pm-hd"><s style="background:${color}"></s>${pmEsc(line)}</div>
      <div class="pm-cp">${pmEsc(m.comp||'')}${m.grp && m.grp!==m.comp ? ' &middot; '+pmEsc(m.grp) : ''}${m.round?` &middot; ${CURLANG==='es'?'jornada':'тур'} ${m.round}`:''}</div>
      <dl class="pm-kv">
        <dt>${CURLANG==='es'?'Fecha':'Дата'}</dt><dd>${pmFmtY(new Date(m.date))}, ${m.home?(CURLANG==='es'?'en casa':'дома'):(CURLANG==='es'?'fuera':'в гостях')}</dd>
        <dt>${CURLANG==='es'?'Rol':'Роль'}</dt><dd>${m.start ? (CURLANG==='es'?'titular':'в старте') : (CURLANG==='es'?'suplente':'вышел на замену')}</dd>
        <dt>${CURLANG==='es'?'Goles':'Голы'}</dt><dd>${m.goals||0}</dd>
        <dt>${CURLANG==='es'?'Equipo':'Команда'}</dt><dd>${pmEsc(m.team||'')}</dd>
      </dl>`;
    if (m._bucket && m._bucket.zone==='NUM' && m._bucket.level>0) html += `<span class="pm-flag">${CURLANG==='es'?'con categoría superior':'за категорию старше'}</span>`;
    else if (m._bucket && m._bucket.zone==='ADULT') html += `<span class="pm-flag">${CURLANG==='es'?'nivel adulto':'взрослый уровень'}</span>`;
    html += `</div>`;
  });
  return html;
}

function pmFamilyCard(famId){
  const fam = PM_CTX.familiesById[famId];
  if (!fam) return '';
  const dom = fam.comps.reduce((p,c)=>c.apps>p.apps?c:p, fam.comps[0]);
  const allMatches = fam.comps.flatMap(c => c.matches).sort((a,b) => new Date(a.date)-new Date(b.date));
  const from = allMatches[0], to = allMatches[allMatches.length-1];
  const color = PM_CTX.teamMeta[dom.tid] ? PM_CTX.teamMeta[dom.tid].color : '#8895a1';
  const pct = dom.tm ? Math.round(dom.apps/dom.tm*100) : 0;
  const place = (dom.matches[0] && dom.matches[0].pos && dom.matches[0].grp_size)
    ? (CURLANG==='es' ? `${dom.matches[0].pos}.º de ${dom.matches[0].grp_size}` : `${dom.matches[0].pos}-е место из ${dom.matches[0].grp_size}`) : '—';
  const phaseNote = fam.comps.length > 1
    ? `<div class="pm-cp">${CURLANG==='es'?'incluye':'включает'} ${fam.comps.length} ${CURLANG==='es'?'fases':'этапа(ов)'}: ${fam.comps.map(c=>pmEsc(c.comp||'')).join(' → ')}</div>` : '';
  return `<h5>${pmEsc(dom.comp||'')}</h5><div class="pm-sub">${pmEsc(dom.matches[0].grp||'')} &middot; ${fam.season}</div>
    <div class="pm-m"><div class="pm-hd"><s style="background:${color}"></s>${pmEsc(dom.matches[0].team||'')}</div>
    ${phaseNote}
    <dl class="pm-kv">
      <dt>${CURLANG==='es'?'Periodo':'Период'}</dt><dd>${pmFmt(new Date(from.date))} — ${pmFmtY(new Date(to.date))}</dd>
      <dt>${CURLANG==='es'?'Partidos del equipo':'Матчей у команды'}</dt><dd>${dom.tm}</dd>
      <dt>${CURLANG==='es'?'Jugó el jugador':'Сыграл игрок'}</dt><dd>${dom.apps} · ${pct}%</dd>
      <dt>${CURLANG==='es'?'Goles':'Голы'}</dt><dd>${fam.comps.reduce((s,c)=>s+c.matches.reduce((s2,m)=>s2+(m.goals||0),0),0)}</dd>
      <dt>${CURLANG==='es'?'Resultado del equipo':'Итог команды'}</dt><dd>${place}</dd>
    </dl>${(dom.matches[0]._bucket && dom.matches[0]._bucket.zone==='NUM' && dom.matches[0]._bucket.level>0) ? `<span class="pm-flag">${CURLANG==='es'?'con categoría superior':'за категорию старше'}</span>` : ''}</div>`;
}

function pmWireTooltip(){
  const root = document.getElementById('pmapRoot');
  const tip = document.getElementById('pmTip');
  function place(x,y){
    const w = 320, hgt = tip.offsetHeight || 200;
    let L = x+16, T = y+16;
    if (L+w > innerWidth-8) L = x-w-16;
    if (T+hgt > innerHeight-8) T = Math.max(8, y-hgt-10);
    tip.style.left = L+'px'; tip.style.top = T+'px';
  }
  function show(html,x,y){ tip.innerHTML = html; tip.classList.add('pm-on'); tip.setAttribute('aria-hidden','false'); place(x,y); }
  function hide(){ tip.classList.remove('pm-on'); tip.setAttribute('aria-hidden','true'); }
  let lastTrack = null, lastId = '', lastHlFam = null;
  function setHlFamily(famId){
    if (lastHlFam === famId) return;
    if (lastHlFam) root.querySelectorAll(`[data-pm-cellfam~="${lastHlFam}"], [data-pm-family="${lastHlFam}"]`).forEach(el => el.classList.remove('pm-hl'));
    lastHlFam = famId;
    if (famId) root.querySelectorAll(`[data-pm-cellfam~="${famId}"], [data-pm-family="${famId}"]`).forEach(el => el.classList.add('pm-hl'));
  }
  function point(e){
    const cellEl = e.target.closest('.pm-cell'), tr = e.target.closest('.pm-track');
    if (tr){
      tr.classList.add('pm-hl');
      if (lastTrack && lastTrack!==tr) lastTrack.classList.remove('pm-hl');
      lastTrack = tr;
      if (cellEl) tr.querySelector('.pm-cross').style.left = PM_COL(+cellEl.dataset.pmI);
    }
    const c = e.target.closest('.pm-cell[data-pm-k]'), cl = e.target.closest('.pm-cl');
    const fam = e.target.closest('[data-pm-family]');
    setHlFamily(fam ? fam.getAttribute('data-pm-family') : null);
    const id = c ? 'w'+c.dataset.pmK : cl ? 'c'+cl.dataset.pmFamily : '';
    if (!id){ lastId=''; hide(); return; }
    if (id !== lastId){ lastId = id; show(c ? pmWeekCard(c.dataset.pmK) : pmFamilyCard(cl.dataset.pmFamily), e.clientX, e.clientY); }
    else place(e.clientX, e.clientY);
  }
  const body = document.getElementById('pmBody');
  body.addEventListener('mousemove', point);
  body.addEventListener('click', point);
  body.addEventListener('mouseleave', () => { hide(); lastId=''; setHlFamily(null); if (lastTrack) lastTrack.classList.remove('pm-hl'); });
  body.addEventListener('focusin', e => {
    const p = e.target.closest('.pm-cell.pm-play'); if (!p) return;
    const r = p.getBoundingClientRect(); show(pmWeekCard(p.dataset.pmK), r.right, r.bottom);
  });
  body.addEventListener('focusout', hide);
  document.getElementById('pmShell').addEventListener('scroll', hide);
}
"""

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — карточка игрока</title>
%FONT_LINKS%
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;450;500;600;700&display=swap" rel="stylesheet">
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
.page{ max-width:900px; margin:0 auto; padding:2.25rem 1.25rem 4rem; display:flex; flex-direction:column; gap:1.5rem; transition:max-width .15s; }
/* Карта участия — тот же полноширинный формат, что и в согласованном
   прототипе (--pm-track/--pm-label там рассчитаны на широкую доску, а не
   на список из "Заявок"); .page здесь расширяется только пока открыт этот
   таб, чтобы список регистраций по-прежнему был по центру и не растягивался. */
.page.pm-wide{ max-width:1600px; }
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
.uncertain-mark{ color:var(--gold); font-family:ui-sans-serif; cursor:help; }
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
.club-profile-link{font-size:0.85em; color:var(--ink-faint); border-bottom:none;}
.club-profile-link:hover{color:var(--accent);}
.comp-meta{display:block; font-size:0.72rem; color:var(--ink-faint); margin-top:0.1rem;}
.summary-cell{font-family:'JetBrains Mono',monospace; font-size:0.78rem; white-space:nowrap; color:var(--ink-soft);}
.empty-state{padding:2rem; text-align:center; color:var(--ink-faint);}
.birth-note{color:var(--ink-soft); font-size:0.85rem;}
footer.note{font-size:0.78rem; color:var(--ink-soft); max-width:90ch;}

.tabs{display:flex; gap:0.4rem;}
.tab-btn{ font-family:inherit; font-size:0.82rem; font-weight:700; color:var(--ink-soft); background:var(--surface);
  border:1.5px solid var(--line-strong); border-radius:999px; padding:0.35rem 0.9rem; cursor:pointer; }
.tab-btn:hover{color:var(--ink); border-color:var(--accent);}
.tab-btn.active{background:var(--accent); border-color:var(--accent); color:#fff;}
.tab-pane{display:none;}
.tab-pane.active{display:block;}
%DATATABLE_CSS%
%PMAP_CSS%
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

  <div class="tabs">
    <button type="button" class="tab-btn active" id="tabBtnReg" data-i18n="tab_reg">Заявки</button>
    <button type="button" class="tab-btn" id="tabBtnPMap" data-i18n="tab_pmap">Карта участия</button>
  </div>

  <section class="tab-pane active" id="paneReg">
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

  <section class="tab-pane" id="panePMap">
    <div id="pmapRoot"></div>
  </section>

  <footer class="note" data-i18n="footer">Построено из <code>output/processed/rffm/player_competition_participation.csv</code>. См.
    <code>analysis_scripts/player_cards.py</code>.</footer>
</div>
<script>
const SHARD_MOD = %SHARD_MOD%;
const SEASONS = %SEASONS_JSON%;
const DIV_LABEL_RU = %DIV_LABEL_RU_JSON%;
const DIV_LABEL_ES = %DIV_LABEL_ES_JSON%;
const TIER_OF = %TIER_OF_JSON%;
const GT_CODE = %GT_CODE_JSON%;
const GT_SHORT = %GT_SHORT_JSON%;
const LANG = {
  ru: { loading: 'Загрузка…', notFound: 'Нет данных о заявках этого игрока.', other: 'Прочее', birthLabel: 'Год рождения',
        stSeasons: 'Сезонов', stClubs: 'Клубов', stTeams: 'Команд', stApps: 'Явок (всего)', stGoals: 'Голов (всего)',
        uncertainHint: 'Не все сезоны в этом окне полностью докачаны — реальное число может отличаться',
        nowLabel: 'Сейчас:', backTeam: '&larr; Карточка команды', back: '&larr; Карта клубов' },
  es: { loading: 'Cargando…', notFound: 'No se encontraron datos de inscripción para este jugador.', other: 'Otra', birthLabel: 'Año de nacimiento',
        stSeasons: 'Temporadas', stClubs: 'Clubes', stTeams: 'Equipos', stApps: 'Partidos (total)', stGoals: 'Goles (total)',
        uncertainHint: 'No todas las temporadas de esta ventana están completamente recopiladas — el número real puede diferir',
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

// data/player_seasons/<pid % SHARD_MOD>.json — {x, y, u} built once across
// every season (player_cards.py build_career_shards()), independent of the
// "show all seasons" checkbox: it's a career-wide stat, not a view of the
// currently-loaded rows.
async function fetchPlayerSeasons(pid) {
  const shard = parseInt(pid, 10) % SHARD_MOD;
  try {
    const res = await fetch(`data/player_seasons/${shard}.json`);
    if (!res.ok) return null;
    const data = await res.json();
    return data[pid] || null;
  } catch (e) {
    return null;
  }
}

function renderProfileStrip(rows, career) {
  const strip = document.getElementById('profileStrip');
  const seasons = new Set(rows.map(r => r._season));
  const clubs = new Set(rows.map(r => r.club).filter(Boolean));
  const teams = new Set(rows.map(r => r.team_id).filter(Boolean));
  const cell = (id, num, lbl, extra) => `<div class="stat-cell"><div class="num" id="${id}">${num}${extra || ''}</div><div class="lbl">${esc(lbl)}</div></div>`;
  let seasonsNum = String(seasons.size);
  let seasonsExtra = '';
  if (career && career.y !== null && career.y !== undefined) {
    seasonsNum = `${career.x}/${career.y}`;
    if (career.u) seasonsExtra = ` <span class="uncertain-mark" title="${esc(LANG[CURLANG].uncertainHint)}">*</span>`;
  }
  strip.innerHTML =
    cell('stSeasonsNum', seasonsNum, LANG[CURLANG].stSeasons, seasonsExtra) +
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

  renderProfileStrip(rows, await fetchPlayerSeasons(CUR_PID));
  renderNowBadge(rows);

  document.getElementById('regBody').innerHTML = rows.map((r, i) => {
    const teamUrl = teamCardUrl(r);
    const teamHtml = teamUrl ? `<a href="${teamUrl}">${esc(r.team || '—')}</a>` : esc(r.team || '—');
    const clubProfileHtml = r.club
      ? ` <a class="club-profile-link" href="club_profile.html?clubname=${encodeURIComponent(r.club)}" title="${CURLANG === 'ru' ? 'Профиль клуба' : 'Perfil de club'}">&rarr;</a>`
      : '';
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
      <td class="team-name" data-col="team" data-v="${esc(r.team || '')}">${teamHtml}${clubProfileHtml}</td>
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

let PMAP_LOADED = false;
function showTab(name) {
  const isPMap = name === 'pmap';
  document.getElementById('tabBtnPMap').classList.toggle('active', isPMap);
  document.getElementById('tabBtnReg').classList.toggle('active', !isPMap);
  document.getElementById('panePMap').classList.toggle('active', isPMap);
  document.getElementById('paneReg').classList.toggle('active', !isPMap);
  document.querySelector('.page').classList.toggle('pm-wide', isPMap);
  if (isPMap && !PMAP_LOADED) {
    PMAP_LOADED = true;
    if (typeof initParticipationMap === 'function') initParticipationMap(CUR_PID);
  }
}
document.getElementById('tabBtnReg').addEventListener('click', () => showTab('reg'));
document.getElementById('tabBtnPMap').addEventListener('click', () => showTab('pmap'));

%PMAP_JS%

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
  btn.addEventListener('click', function () {
    CURLANG = btn.getAttribute('data-lang-btn'); setupBackLink(); render();
    if (PM_STATE) pmRender();
  });
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
            .replace("%DIV_LABEL_ES_JSON%", json.dumps(DIV_LABEL_ES, ensure_ascii=False))
            .replace("%TIER_OF_JSON%", json.dumps(TIER_OF, ensure_ascii=False))
            .replace("%GT_CODE_JSON%", json.dumps(GT_CODE, ensure_ascii=False))
            .replace("%GT_SHORT_JSON%", json.dumps(GT_SHORT, ensure_ascii=False))
            .replace("%PMAP_CSS%", PMAP_CSS)
            .replace("%PMAP_JS%", PMAP_JS))


def main():
    parser = argparse.ArgumentParser(description="RFFM player-card data + page")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    build_all(Path(__file__).parent.parent / args.output_dir)


if __name__ == "__main__":
    main()
