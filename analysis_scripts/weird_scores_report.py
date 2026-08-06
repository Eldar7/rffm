#!/usr/bin/env python3
"""
"Странные счета, доминаторы и аутсайдеры" — the RFFM weird-scores report.

Design and RU/ES bilingual toggle ported from a one-off Claude.ai artifact
with the same title; this version computes every number live from the
CSVs already committed under output/processed/rffm/ (nothing here
re-scrapes rffm.es), scoped to this project's core categories per
CLAUDE.md (BENJAMÍN + PREBENJAMÍN, every game type).

Usage:
    python analysis_scripts/weird_scores_report.py
    python analysis_scripts/weird_scores_report.py --season 2025-2026 --output reports/weird_scores.html
"""

import argparse
import html as html_lib
from pathlib import Path

import pandas as pd

from site_theme import CSS, FONT_LINKS, LANG_SWITCH_JS, lang_switch_html

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

CATEGORIES = ["BENJAMIN", "PREBENJAMIN"]
CAT_DISPLAY = {"BENJAMIN": "BENJAMÍN", "PREBENJAMIN": "PREBENJAMÍN"}

BLOWOUT_MARGIN = 15
TEAM_MIN_GAMES = 10
CLUB_MIN_GAMES = 15
TOP_BLOWOUTS = 12
REF_MIN_GAMES = 15


def esc(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return html_lib.escape(str(v))


def ru_plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 100 in (11, 12, 13, 14):
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def norm_id(v):
    try:
        return str(int(float(str(v))))
    except (ValueError, TypeError):
        return None


def latest_core_season() -> str:
    m = pd.read_csv(MANIFEST, dtype=str)
    core = m[(m["stage"] == "core") & (m["category_base"] == "ALL") &
             (m["status"].isin(["complete", "complete_with_failures"]))]
    if core.empty:
        raise SystemExit("No season has a complete core crawl in coverage_manifest.csv")
    return sorted(core["season"].unique().tolist())[-1]


def team_link(tid, name) -> str:
    name = esc(name)
    if tid:
        return f'<a href="https://www.rffm.es/fichaequipo/{tid}" target="_blank" rel="noopener">{name}</a>'
    return name


def match_link(match_id, text) -> str:
    return f'<a href="https://www.rffm.es/acta-partido/{match_id}" target="_blank" rel="noopener">{text}</a>'


def score_txt(r) -> str:
    return f"{int(r['hs'])}:{int(r['as_'])}"


def score_html_colon(r) -> str:
    return f'{int(r["hs"])}<span class="colon">:</span>{int(r["as_"])}'


def player_link(pid, name) -> str:
    name = esc(name)
    if pid:
        return f'<a href="https://www.rffm.es/fichajugador/{pid}" target="_blank" rel="noopener">{name}</a>'
    return name


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(season: str) -> dict:
    d = BASE / season
    matches = pd.read_csv(d / "matches.csv", dtype=str)
    teams = pd.read_csv(d / "teams.csv", dtype=str)
    comps = pd.read_csv(d / "competitions.csv", dtype=str)

    comps["category_base"] = comps["category_base"].fillna("OTHER")
    comp_cat = comps.set_index("competition_id")["category_base"]

    m = matches.copy()
    m["hs"] = pd.to_numeric(m["home_score"], errors="coerce")
    m["as_"] = pd.to_numeric(m["away_score"], errors="coerce")
    played = m[m["is_finished"].str.lower() == "true"].dropna(subset=["hs", "as_"]).copy()
    played["cat"] = played["competition_id"].map(comp_cat)
    played = played[played["cat"].isin(CATEGORIES)].copy()
    played["hid"] = played["home_team_id"].map(norm_id)
    played["aid"] = played["away_team_id"].map(norm_id)
    played["margin"] = (played["hs"] - played["as_"]).abs()
    played["total_goals"] = played["hs"] + played["as_"]

    tid_to_name = dict(zip(teams["team_id"].map(norm_id), teams["team"]))
    tid_to_club = dict(zip(teams["team_id"].map(norm_id), teams["club_name_raw"]))
    played["home_name"] = played["hid"].map(tid_to_name).fillna(played["home_team"])
    played["away_name"] = played["aid"].map(tid_to_name).fillna(played["away_team"])
    played["home_club"] = played["hid"].map(tid_to_club)
    played["away_club"] = played["aid"].map(tid_to_club)

    # ── per-team perspective (both home and away appearances) ──
    home_p = played[["hid", "home_club", "hs", "as_"]].rename(
        columns={"hid": "tid", "home_club": "club", "hs": "gf", "as_": "ga"})
    away_p = played[["aid", "away_club", "as_", "hs"]].rename(
        columns={"aid": "tid", "away_club": "club", "as_": "gf", "hs": "ga"})
    persp = pd.concat([home_p, away_p], ignore_index=True).dropna(subset=["tid"])
    persp["win"] = persp["gf"] > persp["ga"]
    persp["draw"] = persp["gf"] == persp["ga"]
    persp["loss"] = persp["gf"] < persp["ga"]

    team_agg = persp.groupby("tid").agg(
        played=("gf", "size"), gf=("gf", "sum"), ga=("ga", "sum"),
        wins=("win", "sum"), draws=("draw", "sum"), losses=("loss", "sum"),
        club=("club", "first"),
    ).reset_index()
    team_agg["diff"] = team_agg["gf"] - team_agg["ga"]
    team_agg["name"] = team_agg["tid"].map(tid_to_name)
    team_agg = team_agg.dropna(subset=["name"])

    club_agg = persp.dropna(subset=["club"]).groupby("club").agg(
        played=("gf", "size"), gf=("gf", "sum"), ga=("ga", "sum"),
        wins=("win", "sum"), teams=("tid", "nunique"),
    ).reset_index()
    club_agg["diff"] = club_agg["gf"] - club_agg["ga"]
    club_agg["win_pct"] = (club_agg["wins"] / club_agg["played"] * 100).round(0)

    # ── enrichment tables (per-category files; both categories fully covered) ──
    goals = pd.concat(
        [pd.read_csv(d / "match_goals" / f"{c}.csv", dtype=str) for c in CATEGORIES
         if (d / "match_goals" / f"{c}.csv").exists()], ignore_index=True)
    cards = pd.concat(
        [pd.read_csv(d / "match_cards" / f"{c}.csv", dtype=str) for c in CATEGORIES
         if (d / "match_cards" / f"{c}.csv").exists()], ignore_index=True)
    officials = pd.concat(
        [pd.read_csv(d / "match_officials" / f"{c}.csv", dtype=str) for c in CATEGORIES
         if (d / "match_officials" / f"{c}.csv").exists()], ignore_index=True)
    lineups = pd.concat(
        [pd.read_csv(d / "match_lineups" / f"{c}.csv", dtype=str) for c in CATEGORIES
         if (d / "match_lineups" / f"{c}.csv").exists()], ignore_index=True)
    players = pd.read_csv(d / "players.csv", dtype=str)
    cards["minute"] = pd.to_numeric(cards["minute"], errors="coerce")

    return {
        "season": season,
        "played": played,
        "team_agg": team_agg,
        "club_agg": club_agg,
        "tid_to_name": tid_to_name,
        "tid_to_club": tid_to_club,
        "goals": goals, "cards": cards, "officials": officials,
        "lineups": lineups, "players": players,
    }


# ---------------------------------------------------------------------------
# HTML section builders
# ---------------------------------------------------------------------------

class I18n:
    """Collects RU (DOM-native) / ES pairs for the [data-i18n] toggle."""

    def __init__(self):
        self.es = {}
        self._n = 0

    def t(self, ru_html: str, es_html: str, key: str | None = None) -> str:
        if key is None:
            self._n += 1
            key = f"k{self._n}"
        self.es[key] = es_html
        return f'<span data-i18n="{key}">{ru_html}</span>'


def build_html(data: dict) -> str:
    i = I18n()
    season = data["season"]
    played = data["played"]
    team_agg = data["team_agg"]
    club_agg = data["club_agg"]
    tid_to_name = data["tid_to_name"]

    matches_played = len(played)
    total_goals = int(played["total_goals"].sum())
    avg_goals = round(played["total_goals"].mean(), 2) if matches_played else 0
    blowout_count = int((played["margin"] >= BLOWOUT_MARGIN).sum())
    blowout_pct = round(blowout_count / matches_played * 100, 1) if matches_played else 0
    draws_00 = played[(played["hs"] == 0) & (played["as_"] == 0)]
    draws_00_count = len(draws_00)

    # ---- section 01: wildest score ----
    wildest = played.sort_values("margin", ascending=False).iloc[0]
    w_home_win = wildest["hs"] >= wildest["as_"]

    sec01 = f'''
  <section>
    <div class="section-head">
      <h2>{i.t("Самый дикий счёт сезона", "El marcador más disparatado de la temporada", "h01")}</h2>
      <span class="n">01</span>
    </div>
    <p class="lede">{i.t(
        "Разница результата, невероятная даже по меркам детской лиги, где счёт формируется свободно.",
        "Una diferencia de resultado difícil de creer incluso para los estándares de la liga infantil, donde el marcador se forma libremente.",
        "l01")}</p>
    <div class="hero-card">
      <div class="side home"><div class="club">{team_link(wildest['hid'], wildest['home_name'])}</div></div>
      <div class="score">{match_link(wildest['match_id'], score_html_colon(wildest))}</div>
      <div class="side away"><div class="club">{team_link(wildest['aid'], wildest['away_name'])}</div></div>
      <div class="hero-meta">
        <span>{esc(wildest['match_date'])} &middot; {esc(wildest['competition'])}, {esc(wildest['group'])}</span>
        <span>{i.t(
            f"{int(wildest['margin'])} мячей разницы в одном матче",
            f"{int(wildest['margin'])} goles de diferencia en un solo partido",
            "h01m2")}</span>
      </div>
    </div>
  </section>'''

    # ---- section 02: top blowouts ----
    top_bl = played.sort_values("margin", ascending=False).head(TOP_BLOWOUTS)
    rows02 = []
    for rank, (_, r) in enumerate(top_bl.iterrows(), start=1):
        win_cls = "win" if r["hs"] >= r["as_"] else "lose"
        rows02.append(
            f'<tr><td class="rank">{rank}</td><td class="meta">{esc(r["match_date"])}</td>'
            f'<td>{team_link(r["hid"], r["home_name"])}</td>'
            f'<td class="score {win_cls}">{match_link(r["match_id"], score_txt(r))}</td>'
            f'<td>{team_link(r["aid"], r["away_name"])}</td>'
            f'<td class="meta">{esc(r["competition"])}, {esc(r["group"])}</td></tr>'
        )
    sec02 = f'''
  <section>
    <div class="section-head">
      <h2>{i.t(f"Топ&#8209;{TOP_BLOWOUTS} самых разгромных матчей", f"Top {TOP_BLOWOUTS} goleadas más abultadas", "h02")}</h2>
      <span class="n">02</span>
    </div>
    <p class="lede">{i.t(
        "По абсолютной разнице мячей среди завершённых игр сезона.",
        "Por diferencia absoluta de goles entre los partidos finalizados de la temporada.",
        "l02")}</p>
    <div class="table-scroll">
      <table>
        <thead><tr><th></th><th>{i.t("Дата","Fecha","th_date")}</th><th>{i.t("Хозяева","Local","th_home")}</th>
        <th style="text-align:center">{i.t("Счёт","Resultado","th_score")}</th><th>{i.t("Гости","Visitante","th_away")}</th>
        <th>{i.t("Турнир","Competición","th_comp")}</th></tr></thead>
        <tbody>{"".join(rows02)}</tbody>
      </table>
    </div>
  </section>'''

    # ---- section 03: 0:0 draws + narrow high-scoring draws ----
    zero_sample = draws_00.sort_values("match_date").head(5)
    draws_nonzero = played[(played["hs"] == played["as_"]) & (played["hs"] > 0)]
    narrow_top = draws_nonzero.sort_values("total_goals", ascending=False).head(2)
    rows03 = []
    for _, r in zero_sample.iterrows():
        rows03.append(
            f'<tr><td class="meta">{esc(r["match_date"])}</td>'
            f'<td>{team_link(r["hid"], r["home_name"])} &ndash; {team_link(r["aid"], r["away_name"])}</td>'
            f'<td class="score">{match_link(r["match_id"], "0:0")}</td>'
            f'<td class="meta">{esc(r["competition"])}, {esc(r["group"])}</td></tr>'
        )
    for _, r in narrow_top.iterrows():
        goal_word = ru_plural(int(r["total_goals"]), "мяч", "мяча", "мячей")
        note = i.t(
            f"{esc(r['competition'])}, {esc(r['group'])} &middot; {int(r['total_goals'])} {goal_word}, ничья в перестрелке",
            f"{esc(r['competition'])}, {esc(r['group'])} &middot; {int(r['total_goals'])} goles, empate a goles",
        )
        rows03.append(
            f'<tr><td class="meta">{esc(r["match_date"])}</td>'
            f'<td>{team_link(r["hid"], r["home_name"])} &ndash; {team_link(r["aid"], r["away_name"])}</td>'
            f'<td class="score win">{match_link(r["match_id"], score_txt(r))}</td>'
            f'<td class="meta">{note}</td></tr>'
        )
    match_word = ru_plural(draws_00_count, "матч", "матча", "матчей")
    sec03 = f'''
  <section>
    <div class="section-head">
      <h2>{i.t("Другая крайность: нулевые ничьи", "El otro extremo: empates a cero", "h03")}</h2>
      <span class="n">03</span>
    </div>
    <p class="lede">{i.t(
        f"{draws_00_count} {match_word} сезона закончились 0:0 &mdash; при среднем счёте {avg_goals} гола за игру это статистическая редкость. И есть матчи, где всё решалось в перестрелке с равным счётом.",
        f"{draws_00_count} partidos de la temporada terminaron 0:0 &mdash; con una media de {avg_goals} goles por partido, es una rareza estadística. Y hay partidos que se decidieron en un intercambio de goles con marcador igualado.",
        "l03")}</p>
    <div class="table-scroll">
      <table>
        <thead><tr><th>{i.t("Дата","Fecha","th_date_2")}</th><th>{i.t("Матч","Partido","th_match")}</th>
        <th style="text-align:center">{i.t("Счёт","Resultado","th_score_2")}</th><th>{i.t("Турнир","Competición","th_comp_2")}</th></tr></thead>
        <tbody>{"".join(rows03)}</tbody>
      </table>
    </div>
  </section>'''

    # ---- section 04: team-level dominators/outsiders ----
    eligible_t = team_agg[team_agg["played"] >= TEAM_MIN_GAMES]
    dom_t = eligible_t.sort_values("diff", ascending=False).head(5)
    out_t = eligible_t.sort_values("diff", ascending=True).head(5)

    def team_rowlines(df, sign):
        lines = []
        for _, r in df.iterrows():
            played_w = ru_plural(int(r["played"]), "игра", "игры", "игр")
            sub_key = f"t04_{sign}_{r['tid']}"
            sub_ru = f"{int(r['played'])} {played_w} &middot; {int(r['wins'])}В&#8211;{int(r['draws'])}Н&#8211;{int(r['losses'])}П &middot; {int(r['gf'])}:{int(r['ga'])}"
            sub_es = f"{int(r['played'])} partidos &middot; {int(r['wins'])}G-{int(r['draws'])}E-{int(r['losses'])}P &middot; {int(r['gf'])}:{int(r['ga'])}"
            diff_str = f"+{int(r['diff'])}" if r["diff"] > 0 else f"&#8722;{abs(int(r['diff']))}"
            lines.append(
                f'<div class="rowline"><div><div class="name">{team_link(r["tid"], r["name"])}</div>'
                f'<div class="sub">{i.t(sub_ru, sub_es, sub_key)}</div></div><div class="stat">{diff_str}</div></div>'
            )
        return "".join(lines)

    sec04 = f'''
  <section>
    <div class="section-head">
      <h2>{i.t("Доминаторы и аутсайдеры &mdash; на уровне команд", "Dominadores y colistas &mdash; a nivel de equipo", "h04")}</h2>
      <span class="n">04</span>
    </div>
    <p class="lede">{i.t(
        f"Разница забитых и пропущенных, только команды, сыгравшие {TEAM_MIN_GAMES}+ матчей. Клуб может выставлять несколько составов на разных уровнях &mdash; здесь считаем отдельный состав («A», «B» и т.д.).",
        f"Diferencia de goles a favor y en contra, solo equipos con {TEAM_MIN_GAMES}+ partidos jugados. Un club puede inscribir varios equipos en distintos niveles &mdash; aquí se cuenta cada equipo por separado («A», «B», etc.).",
        "l04")}</p>
    <div class="split">
      <div class="panel gold">
        <div class="panel-head">{i.t("Доминаторы","Dominadores","dominators")}<span class="tag">GD</span></div>
        {team_rowlines(dom_t, "d")}
      </div>
      <div class="panel red">
        <div class="panel-head">{i.t("Аутсайдеры","Colistas","underdogs")}<span class="tag">GD</span></div>
        {team_rowlines(out_t, "l")}
      </div>
    </div>
  </section>'''

    # ---- section 05: club-level dominators/outsiders ----
    eligible_c = club_agg[club_agg["played"] >= CLUB_MIN_GAMES]
    dom_c = eligible_c.sort_values("diff", ascending=False).head(5)
    out_c = eligible_c.sort_values("diff", ascending=True).head(5)

    def club_rowlines(df, sign):
        lines = []
        for idx, r in df.iterrows():
            team_word = ru_plural(int(r["teams"]), "команда", "команды", "команд")
            game_word = ru_plural(int(r["played"]), "игра", "игры", "игр")
            sub_key = f"c05_{sign}_{idx}"
            sub_ru = f"{int(r['teams'])} {team_word} &middot; {int(r['played'])} {game_word} &middot; {int(r['win_pct'])}% побед"
            sub_es = f"{int(r['teams'])} equipos &middot; {int(r['played'])} partidos &middot; {int(r['win_pct'])}% de victorias"
            diff_str = f"+{int(r['diff'])}" if r["diff"] > 0 else f"&#8722;{abs(int(r['diff']))}"
            lines.append(
                f'<div class="rowline"><div><div class="name">{esc(r["club"])}</div>'
                f'<div class="sub">{i.t(sub_ru, sub_es, sub_key)}</div></div><div class="stat">{diff_str}</div></div>'
            )
        return "".join(lines)

    sec05 = f'''
  <section>
    <div class="section-head">
      <h2>{i.t("Доминаторы и аутсайдеры &mdash; на уровне клубов", "Dominadores y colistas &mdash; a nivel de club", "h05")}</h2>
      <span class="n">05</span>
    </div>
    <p class="lede">{i.t(
        f"Один клуб часто выставляет несколько команд на разных уровнях лиги (клуб &ne; команда). Здесь суммарная разница мячей по всем составам клуба, минимум {CLUB_MIN_GAMES} игр.",
        f"Un mismo club suele inscribir varios equipos en distintos niveles de la liga (club &ne; equipo). Aquí se suma la diferencia de goles de todos los equipos del club, mínimo {CLUB_MIN_GAMES} partidos.",
        "l05")}</p>
    <div class="split">
      <div class="panel gold">
        <div class="panel-head">{i.t("Доминаторы","Dominadores","dominators2")}<span class="tag">{i.t("GD, сумма по клубу","DG, suma del club","t05tag")}</span></div>
        {club_rowlines(dom_c, "d")}
      </div>
      <div class="panel red">
        <div class="panel-head">{i.t("Аутсайдеры","Colistas","underdogs2")}<span class="tag">{i.t("GD, сумма по клубу","DG, suma del club","t05tag2")}</span></div>
        {club_rowlines(out_c, "l")}
      </div>
    </div>
  </section>'''

    # ---- section 06: curiosities (computed, not hardcoded) ----
    curios = []

    # a) one club, two different worlds — widest spread between its own teams' GD
    te = team_agg[team_agg["played"] >= TEAM_MIN_GAMES].dropna(subset=["club"])
    per_club = te.groupby("club")
    spread_rows = []
    for club, grp in per_club:
        if len(grp) < 2:
            continue
        best = grp.loc[grp["diff"].idxmax()]
        worst = grp.loc[grp["diff"].idxmin()]
        spread_rows.append((club, best, worst, best["diff"] - worst["diff"]))
    if spread_rows:
        club, best, worst, spread = max(spread_rows, key=lambda x: x[3])
        p1_ru = (
            f'У «<b>{esc(club)}</b>» {len(per_club.get_group(club))} команд в разных группах. '
            f'Команда {team_link(worst["tid"], worst["name"])} &mdash; худшая среди своих ({int(worst["gf"])}:{int(worst["ga"])} за {int(worst["played"])} игр), '
            f'а {team_link(best["tid"], best["name"])} того же клуба &mdash; доминатор ({int(best["gf"])}:{int(best["ga"])}, GD {"+" if best["diff"]>0 else ""}{int(best["diff"])}). '
            f'Одна вывеска, полярно разный футбол.'
        )
        p1_es = (
            f'«<b>{esc(club)}</b>» tiene {len(per_club.get_group(club))} equipos en distintos grupos. '
            f'El equipo {team_link(worst["tid"], worst["name"])} es el peor de los suyos ({int(worst["gf"])}:{int(worst["ga"])} en {int(worst["played"])} partidos), '
            f'mientras que {team_link(best["tid"], best["name"])} del mismo club es casi un dominador ({int(best["gf"])}:{int(best["ga"])}, DG {"+" if best["diff"]>0 else ""}{int(best["diff"])}). '
            f'Un mismo nombre, un fútbol completamente opuesto.'
        )
        curios.append((
            i.t("Один клуб — два разных мира", "Un club, dos mundos distintos", "c06_1_h"),
            i.t(p1_ru, p1_es, "c06_1_p"),
        ))

    # b) intra-club derby blowout
    intra = played[(played["home_club"].notna()) & (played["home_club"] == played["away_club"])].copy()
    if not intra.empty:
        derby = intra.sort_values("margin", ascending=False).iloc[0]
        pair = {derby["hid"], derby["aid"]}
        both_legs = played[
            (played["hid"].isin(pair)) & (played["aid"].isin(pair)) & (played["hid"] != played["aid"])
        ]
        total_gf = int(both_legs["hs"].where(both_legs["hid"] == derby["hid"], both_legs["as_"]).sum()) if len(both_legs) > 1 else int(derby["hs"])
        total_ga = int(both_legs["as_"].where(both_legs["hid"] == derby["hid"], both_legs["hs"]).sum()) if len(both_legs) > 1 else int(derby["as_"])
        derby_score = match_link(derby["match_id"], score_txt(derby))
        agg_ru = f" &mdash; по сумме двух встреч сезона: {total_gf}:{total_ga}" if len(both_legs) > 1 else ""
        agg_es = f" &mdash; en el balance de los dos partidos de la temporada: {total_gf}:{total_ga}" if len(both_legs) > 1 else ""
        p2_ru = (
            f'{esc(derby["home_club"])} выставляет составы {team_link(derby["hid"], derby["home_name"])} и {team_link(derby["aid"], derby["away_name"])} в одной группе. '
            f'В матче {esc(derby["match_date"])} счёт был {derby_score}{agg_ru}.'
        )
        p2_es = (
            f'{esc(derby["home_club"])} inscribe a sus equipos {team_link(derby["hid"], derby["home_name"])} y {team_link(derby["aid"], derby["away_name"])} en el mismo grupo. '
            f'El {esc(derby["match_date"])} el resultado fue {derby_score}{agg_es}.'
        )
        curios.append((
            i.t("Внутриклубное дерби с погромом", "Un derbi interno con paliza incluida", "c06_2_h"),
            i.t(p2_ru, p2_es, "c06_2_p"),
        ))

    # c) intra-club match count
    intra_count = len(intra)
    match_word_intra = ru_plural(intra_count, "матч", "матча", "матчей")
    p3_ru = (
        f'{intra_count} {match_word_intra} сезона &mdash; это игры клуба сам с собой (например «A» против «C»). '
        f'Формально соперники, по факту &mdash; тренировочный спарринг с официальным протоколом.'
    )
    p3_es = (
        f'{intra_count} partidos de la temporada son un club jugando contra sí mismo (por ejemplo «A» contra «C»). '
        f'Formalmente son rivales; en la práctica, un amistoso con acta oficial.'
    )
    curios.append((
        i.t(f"{intra_count} внутриклубных матчей", f"{intra_count} partidos de un club contra sí mismo", "c06_3_h"),
        i.t(p3_ru, p3_es, "c06_3_p"),
    ))

    # d) blowout share
    p4_ru = (
        f'При среднем счёте {avg_goals} гола за матч только {blowout_count} игр ({blowout_pct}%) завершились с разницей {BLOWOUT_MARGIN}+ мячей. '
        f'Экстремальные результаты &mdash; редкость на фоне общей массы, где решает один-два мяча.'
    )
    p4_es = (
        f'Con una media de {avg_goals} goles por partido, solo {blowout_count} partidos ({blowout_pct}%) terminaron con una diferencia de {BLOWOUT_MARGIN}+ goles. '
        f'Los resultados extremos son la excepción frente a la masa de partidos donde todo lo deciden uno o dos goles.'
    )
    curios.append((
        i.t(f"{blowout_count} разгромов, но лига в целом плотная", f"{blowout_count} goleadas, pero la liga en general es reñida", "c06_4_h"),
        i.t(p4_ru, p4_es, "c06_4_p"),
    ))

    sec06 = f'''
  <section>
    <div class="section-head">
      <h2>{i.t("Курьёзы", "Curiosidades", "h06")}</h2>
      <span class="n">06</span>
    </div>
    <div class="curio-grid">
      {"".join(f'<div class="curio"><h3>{h}</h3><p>{p}</p></div>' for h, p in curios)}
    </div>
  </section>'''

    # ---- section 07: match protocols (goals/cards/officials) ----
    goals, cards, officials, lineups, players = (
        data["goals"], data["cards"], data["officials"], data["lineups"], data["players"])
    sec07 = ""
    if not goals.empty:
        name_map = dict(zip(players["player_id"], players["player_name"]))
        goals["minute"] = pd.to_numeric(goals["minute"], errors="coerce")

        matches_covered = lineups["match_id"].nunique() if not lineups.empty else 0
        cards_with_match = cards["match_id"].nunique() if not cards.empty else 0
        pct_with_card = round(cards_with_match / matches_covered * 100, 1) if matches_covered else 0
        yellow = int((cards["card_type_label"] == "amarilla").sum()) if not cards.empty else 0
        red = int((cards["card_type_label"] == "roja").sum()) if not cards.empty else 0
        second_yellow = int((cards["card_type_label"] == "doble_amarilla").sum()) if not cards.empty else 0
        total_cards = len(cards)
        lineup_positions = len(lineups)

        cat_label_ru = " и ".join(CAT_DISPLAY[c] for c in CATEGORIES)
        cat_label_es = " y ".join(CAT_DISPLAY[c] for c in CATEGORIES)

        # top scorer (lead-card)
        gp = goals.groupby("player_id").agg(goals=("match_id", "size")).reset_index()
        lin_apps = lineups.groupby("player_id")["match_id"].nunique().rename("apps") if not lineups.empty else pd.Series(dtype=int)
        gp = gp.join(lin_apps, on="player_id")
        gp["apps"] = gp["apps"].fillna(gp["goals"])
        gp["gpm"] = gp["goals"] / gp["apps"]
        gp["name"] = gp["player_id"].map(name_map)
        gp = gp.dropna(subset=["name"]).sort_values("goals", ascending=False)

        top_teams_by_player = goals.groupby("player_id")["team_id"].unique()

        def team_names_for(pid):
            tids = top_teams_by_player.get(pid, [])
            links = [team_link(norm_id(t), tid_to_name.get(norm_id(t), "?")) for t in tids if norm_id(t)]
            return " / ".join(links)

        lead = gp.iloc[0]
        lead_ru = f"{player_link(lead['player_id'], lead['name'])} &mdash; лучший бомбардир сезона"
        lead_es = f"{player_link(lead['player_id'], lead['name'])} &mdash; máximo goleador de la temporada"
        lead_sub_ru = f"{int(lead['goals'])} голов за {int(lead['apps'])} матчей ({lead['gpm']:.2f} гола за игру) за {team_names_for(lead['player_id'])}."
        lead_sub_es = f"{int(lead['goals'])} goles en {int(lead['apps'])} partidos ({lead['gpm']:.2f} goles por partido) con {team_names_for(lead['player_id'])}."

        rows_scorers = []
        for rank, (_, r) in enumerate(gp.head(12).iterrows(), start=1):
            rows_scorers.append(
                f'<tr><td class="rank">{rank}</td><td>{player_link(r["player_id"], r["name"])}</td>'
                f'<td class="num">{int(r["goals"])}</td><td class="num">{int(r["apps"])}</td>'
                f'<td class="num">{r["gpm"]:.2f}</td><td class="meta">{team_names_for(r["player_id"])}</td></tr>'
            )

        # curiosity: most goals by one player in a single match
        smg = goals.groupby(["player_id", "match_id"]).size().rename("g").reset_index()
        smg_top = smg.sort_values("g", ascending=False)
        best_row = smg_top.iloc[0]
        best_n = int(best_row["g"])
        best_count = int((smg_top["g"] == best_n).sum())
        best_name = name_map.get(best_row["player_id"], "?")
        again_ru = f" &mdash; и это случилось {best_count} раза" if best_count > 1 else ""
        again_es = f" &mdash; y ocurrió {best_count} veces" if best_count > 1 else ""
        c07_1_h_ru = f"{best_n} голов одного ребёнка за один матч"
        c07_1_h_es = f"{best_n} goles de un solo niño en un partido"
        c07_1_p_ru = f"{player_link(best_row['player_id'], best_name)} забил {best_n} мячей в одном матче{again_ru} &mdash; рекорд сезона в этих категориях."
        c07_1_p_es = f"{player_link(best_row['player_id'], best_name)} marcó {best_n} goles en un solo partido{again_es} &mdash; el récord de la temporada en estas categorías."

        # curiosity: earliest-minute red card
        red_cards = cards[(cards["card_type_label"] == "roja") & (cards["minute"] != 999)] if not cards.empty else cards
        c07_2_h_ru = c07_2_h_es = c07_2_p_ru = c07_2_p_es = None
        if not red_cards.empty:
            earliest = red_cards.sort_values("minute").iloc[0]
            minute = int(earliest["minute"]) if pd.notna(earliest["minute"]) else None
            p_name = name_map.get(earliest["player_id"], "?")
            if minute is not None:
                c07_2_h_ru = f"Красная карточка на {minute}&#8209;й минуте"
                c07_2_h_es = f"Tarjeta roja en el minuto {minute}"
                c07_2_p_ru = f"{player_link(earliest['player_id'], p_name)} получил прямую красную на минуте {minute} &mdash; одно из самых ранних удалений сезона."
                c07_2_p_es = f"{player_link(earliest['player_id'], p_name)} vio la roja directa en el minuto {minute} &mdash; una de las expulsiones más tempranas de la temporada."

        # curiosity: goals scored by keeper-flagged players
        c07_3_h_ru = c07_3_h_es = c07_3_p_ru = c07_3_p_es = None
        if not lineups.empty:
            lu = lineups[["match_id", "team_id", "player_id", "is_goalkeeper"]].drop_duplicates()
            gk_goals = goals.merge(lu, on=["match_id", "team_id", "player_id"], how="inner")
            gk_goal_count = int((gk_goals["is_goalkeeper"] == "True").sum())
            c07_3_h_ru = f"{gk_goal_count} голов забили «вратари»"
            c07_3_h_es = f"{gk_goal_count} goles marcados por «porteros»"
            c07_3_p_ru = "В протоколах составов эти голы числятся за игроками, отмеченными как голкиперы в этом матче. В детском футболе позиция вратаря часто ротируется внутри команды &mdash; вратарь одной игры может забивать в следующей."
            c07_3_p_es = "En las actas de alineaciones, estos goles están anotados a jugadores marcados como porteros en ese partido. En el fútbol infantil la posición de portero suele rotar dentro del equipo &mdash; el portero de un partido puede marcar en el siguiente."

        # referees
        ref = officials[officials["official_kind"] == "referee"] if not officials.empty else officials
        busy = ref.groupby(["official_id", "official_name"])["match_id"].nunique().rename("apps").reset_index().sort_values("apps", ascending=False)
        cards_per_match = cards.groupby("match_id").size().rename("cnt") if not cards.empty else pd.Series(dtype=int)
        ref_matches = ref[["match_id", "official_id", "official_name"]].drop_duplicates()
        ref_matches = ref_matches.join(cards_per_match, on="match_id")
        ref_matches["cnt"] = ref_matches["cnt"].fillna(0)
        strict = ref_matches.groupby(["official_id", "official_name"]).agg(
            apps=("match_id", "nunique"), cards=("cnt", "sum")).reset_index()
        strict = strict[strict["apps"] >= REF_MIN_GAMES].copy()
        strict["cpm"] = strict["cards"] / strict["apps"]

        c07_4_h_ru = c07_4_h_es = c07_4_p_ru = c07_4_p_es = None
        if not busy.empty and not strict.empty:
            busiest = busy.iloc[0]
            strictest = strict.sort_values("cpm", ascending=False).iloc[0]
            if busiest["official_id"] != strictest["official_id"]:
                c07_4_h_ru = '«Трудолюбивый» и «строгий» &mdash; разные судьи'
                c07_4_h_es = '«Trabajador» y «severo» son árbitros distintos'
                c07_4_p_ru = f"{esc(busiest['official_name'])} отсудил больше всех матчей ({int(busiest['apps'])}), а чаще всех показывает карточки {esc(strictest['official_name'])} ({strictest['cpm']:.2f} карт./матч) &mdash; нагрузка не равна строгости."
                c07_4_p_es = f"{esc(busiest['official_name'])} pitó más partidos ({int(busiest['apps'])}), mientras que quien más tarjetas saca por partido es {esc(strictest['official_name'])} ({strictest['cpm']:.2f} tarj./partido) &mdash; la carga de trabajo no es lo mismo que la severidad."

        rows_matches07 = []
        matches07 = data["played"]
        match_info = matches07.set_index("match_id")
        for _, r in smg_top.head(10).iterrows():
            mid = r["match_id"]
            pname = name_map.get(r["player_id"], "?")
            if mid in match_info.index:
                mm = match_info.loc[mid]
                mm = mm if mm.ndim == 1 else mm.iloc[0]
                mm_score = match_link(mid, score_txt(mm))
                match_desc = f'{team_link(mm["hid"], mm["home_name"])} {mm_score} {team_link(mm["aid"], mm["away_name"])}'
                date = esc(mm["match_date"])
                group = esc(mm["group"])
            else:
                match_desc, date, group = match_link(mid, "&mdash;"), "&mdash;", "&mdash;"
            rows_matches07.append(
                f'<tr><td class="meta">{date}</td><td>{player_link(r["player_id"], pname)}</td>'
                f'<td class="num">{int(r["g"])}</td><td class="meta">{match_desc}</td><td class="meta">{group}</td></tr>'
            )

        rows_busy = "".join(
            f'<tr><td>{esc(r["official_name"])}</td><td class="num">{int(r["apps"])}</td></tr>'
            for _, r in busy.head(10).iterrows()
        )
        rows_strict = "".join(
            f'<tr><td>{esc(r["official_name"])}</td><td class="num">{int(r["apps"])}</td>'
            f'<td class="num">{int(r["cards"])}</td><td class="num">{r["cpm"]:.2f}</td></tr>'
            for _, r in strict.sort_values("cpm", ascending=False).head(10).iterrows()
        )

        curio07 = []
        for h_ru, h_es, p_ru, p_es, key in [
            (c07_1_h_ru, c07_1_h_es, c07_1_p_ru, c07_1_p_es, "c07_1"),
            (c07_2_h_ru, c07_2_h_es, c07_2_p_ru, c07_2_p_es, "c07_2"),
            (c07_3_h_ru, c07_3_h_es, c07_3_p_ru, c07_3_p_es, "c07_3"),
            (c07_4_h_ru, c07_4_h_es, c07_4_p_ru, c07_4_p_es, "c07_4"),
        ]:
            if h_ru is None:
                continue
            curio07.append((i.t(h_ru, h_es, f"{key}_h"), i.t(p_ru, p_es, f"{key}_p")))

        yellow_word = ru_plural(yellow, "жёлтая", "жёлтых", "жёлтых")
        red_word = ru_plural(red, "красная", "красных", "красных")

        sec07 = f'''
  <section>
    <div class="section-head">
      <h2>{i.t("Из протоколов матчей: голы, карточки, судьи", "De las actas de los partidos: goles, tarjetas, árbitros", "h07")}</h2>
      <span class="n">07</span>
    </div>
    <div class="scope-note">
      <span class="mark">{i.t("Охват","Alcance","scope_mark")}</span>
      <span>{i.t(
          f"Построчные протоколы матчей (acta) с составами, голами и карточками собраны для категорий <b>{cat_label_ru}</b>: {matches_covered:,} матчей с зафиксированными составами.".replace(",", "&nbsp;"),
          f"Las actas de los partidos con alineaciones, goles y tarjetas están recopiladas para las categorías <b>{cat_label_es}</b>: {matches_covered:,} partidos con alineación registrada.".replace(",", "&nbsp;"),
          "scope_text")}</span>
    </div>
    <div class="stat-strip">
      <div class="cell"><div class="num">{len(goals):,}</div><div class="lbl">{i.t("голов в протоколах","goles registrados en las actas","s07_1")}</div></div>
      <div class="cell"><div class="num">{total_cards}</div><div class="lbl">{i.t(f"карточки ({yellow} {yellow_word} / {red} {red_word})", f"tarjetas ({yellow} amarillas / {red} rojas)","s07_2")}</div></div>
      <div class="cell"><div class="num">{pct_with_card}%</div><div class="lbl">{i.t("матчей хоть с одной карточкой","partidos con al menos una tarjeta","s07_3")}</div></div>
      <div class="cell"><div class="num">{lineup_positions:,}</div><div class="lbl">{i.t("позиций в составах","líneas de alineación","s07_4")}</div></div>
    </div>
    <div class="lead-card">
      <div class="big-num">{int(lead['goals'])}</div>
      <div class="desc">
        <div class="name">{i.t(lead_ru, lead_es, "lead_name")}</div>
        <div class="sub">{i.t(lead_sub_ru, lead_sub_es, "lead_sub")}</div>
      </div>
    </div>
    <p class="lede" style="margin-top:24px">{i.t("Топ&#8209;12 бомбардиров сезона по протоколам голов.", "Top 12 goleadores de la temporada según las actas de goles.", "l07top")}</p>
    <div class="table-scroll">
      <table>
        <thead><tr><th></th><th>{i.t("Игрок","Jugador","th_player")}</th><th style="text-align:right">{i.t("Голы","Goles","th_goals")}</th>
        <th style="text-align:right">{i.t("Матчи","Partidos","th_apps")}</th><th style="text-align:right">{i.t("Гол/матч","Goles/partido","th_gpm")}</th>
        <th>{i.t("Команда","Equipo","th_team")}</th></tr></thead>
        <tbody>{"".join(rows_scorers)}</tbody>
      </table>
    </div>
    <div class="curio-grid" style="margin-top:22px">
      {"".join(f'<div class="curio"><h3>{h}</h3><p>{p}</p></div>' for h, p in curio07)}
    </div>
    <p class="lede" style="margin-top:24px">{i.t("Топ&#8209;10 матчей: сколько голов забил один игрок за игру.", "Top 10 partidos: cuántos goles marcó un solo jugador en el encuentro.", "l07match")}</p>
    <div class="table-scroll">
      <table>
        <thead><tr><th>{i.t("Дата","Fecha","th_date_3")}</th><th>{i.t("Игрок","Jugador","th_player_2")}</th>
        <th style="text-align:right">{i.t("Голы","Goles","th_goals_2")}</th><th>{i.t("Матч","Partido","th_match_2")}</th>
        <th>{i.t("Группа","Grupo","th_group")}</th></tr></thead>
        <tbody>{"".join(rows_matches07)}</tbody>
      </table>
    </div>
    <p class="lede" style="margin-top:24px">{i.t(f"Судьи: кто отсудил больше всех матчей и кто чаще всех показывает карточки (минимум {REF_MIN_GAMES} матчей).", f"Árbitros: quién pitó más partidos y quién saca tarjetas con más frecuencia (mínimo {REF_MIN_GAMES} partidos).", "l07ref")}</p>
    <div class="split">
      <div class="table-scroll">
        <div class="table-cap">{i.t("Самые трудолюбивые","Los más trabajadores","cap_busy")}</div>
        <table>
          <thead><tr><th>{i.t("Судья","Árbitro","th_ref")}</th><th style="text-align:right">{i.t("Матчи","Partidos","th_apps_2")}</th></tr></thead>
          <tbody>{rows_busy}</tbody>
        </table>
      </div>
      <div class="table-scroll">
        <div class="table-cap">{i.t("Самые строгие","Los más severos","cap_strict")}</div>
        <table>
          <thead><tr><th>{i.t("Судья","Árbitro","th_ref_2")}</th><th style="text-align:right">{i.t("Матчи","Partidos","th_apps_3")}</th>
          <th style="text-align:right">{i.t("Карточек","Tarjetas","th_cards")}</th><th style="text-align:right">{i.t("Карт./матч","Tarj./partido","th_cpm")}</th></tr></thead>
          <tbody>{rows_strict}</tbody>
        </table>
      </div>
    </div>
  </section>'''

    footer = i.t(
        "Источник: <span>output/processed/rffm/*.csv</span> &middot; матчи со статусом is_finished=True, "
        f"сезон {esc(season)}, категории BENJAMÍN и PREBENJAMÍN &middot; club &ne; team: агрегаты «на уровне клубов» "
        "суммируют все команды с одинаковым club_name_raw &middot; раздел 07 построен по протоколам матчей "
        "(match_goals/match_cards/match_officials/match_lineups). Ссылки ведут на официальные страницы rffm.es.",
        "Fuente: <span>output/processed/rffm/*.csv</span> &middot; partidos con estado is_finished=True, "
        f"temporada {esc(season)}, categorías BENJAMÍN y PREBENJAMÍN &middot; club &ne; equipo: los agregados «a "
        "nivel de club» suman todos los equipos con el mismo club_name_raw &middot; la sección 07 se construye a "
        "partir de las actas de los partidos (match_goals/match_cards/match_officials/match_lineups). Los enlaces "
        "apuntan a las páginas oficiales de rffm.es.",
        "footer",
    )

    stat_word_matches = ru_plural(matches_played, "сыгранный матч", "сыгранных матча", "сыгранных матчей")

    body = f'''<div class="wrap">
  <div class="masthead">
    <div>
      <div class="kicker">{i.t("RFFM &middot; Отчёт по данным", "RFFM &middot; Informe de datos", "kicker")}</div>
      <h1>{i.t("Странные счета,<br>доминаторы и аутсайдеры", "Marcadores extraños,<br>dominadores y colistas", "h1")}</h1>
    </div>
    <div class="scope-block">
      {lang_switch_html()}
      <div class="scope">
        {i.t(f"Сезон <b>{esc(season)}</b>", f"Temporada <b>{esc(season)}</b>", "scope1")}<br>
        {i.t("Категории <b>BENJAM&Iacute;N</b> и <b>PREBENJAM&Iacute;N</b>", "Categor&iacute;as <b>BENJAM&Iacute;N</b> y <b>PREBENJAM&Iacute;N</b>", "scope2")}<br>
        {i.t("Futbol&#8209;7 и F&uacute;tbol Sala", "F&uacute;tbol&#8209;7 y F&uacute;tbol Sala", "scope3")}
      </div>
    </div>
  </div>
  <div class="stat-strip">
    <div class="cell"><div class="num">{matches_played:,}</div><div class="lbl">{i.t(stat_word_matches, "partidos disputados", "s1")}</div></div>
    <div class="cell"><div class="num">{avg_goals}</div><div class="lbl">{i.t("гола за матч в среднем","goles de media por partido","s2")}</div></div>
    <div class="cell"><div class="num">{blowout_count}</div><div class="lbl">{i.t(f"разгромов с разницей &ge;{BLOWOUT_MARGIN} мячей", f"goleadas con diferencia &ge;{BLOWOUT_MARGIN} goles","s3")}</div></div>
    <div class="cell"><div class="num">{draws_00_count}</div><div class="lbl">{i.t("матчей 0:0","partidos 0:0","s4")}</div></div>
  </div>
  {sec01}
  {sec02}
  {sec03}
  {sec04}
  {sec05}
  {sec06}
  {sec07}
  <footer>{footer}</footer>
</div>'''

    import json
    i18n_json = json.dumps(i.es, ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM {esc(season)}: странные счета, доминаторы и аутсайдеры</title>
<a class="back" href="index.html" style="display:inline-block;margin:16px 0 0 20px">&larr; RFFM data</a>
{FONT_LINKS}
<style>{CSS}</style>
</head>
<body>
{body}
<script>
(function () {{
  var I18N_ES = {i18n_json};
  {LANG_SWITCH_JS}
}})();
</script>
</body>
</html>
'''


def main():
    parser = argparse.ArgumentParser(description="RFFM weird scores / dominators / outsiders report")
    parser.add_argument("--season", default=None, help="defaults to the latest season with a complete core crawl")
    parser.add_argument("--output", default="reports/weird_scores.html")
    args = parser.parse_args()

    season = args.season or latest_core_season()
    print(f"Building weird-scores report for season {season}")
    data = load_data(season)
    print(f"  {len(data['played'])} played matches (BENJAMÍN+PREBENJAMÍN)")

    out = Path(__file__).parent.parent / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(data), encoding="utf-8")
    print(f"Report written to {out}")


if __name__ == "__main__":
    main()
