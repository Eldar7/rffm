#!/usr/bin/env python3
"""DEBUTANTE analysis utilities.

Computes reusable DEBUTANTE summaries from processed CSV data.
Outputs are written under reports/.

Usage:
  c:/git/personal/rffm/.venv/Scripts/python.exe analysis_scripts/debutante_analysis.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
REPORTS = Path(__file__).parent.parent / "reports"


def norm_id(v) -> str | None:
    if pd.isna(v):
        return None
    s = str(v).strip()
    if not s or s in {"-1", "nan", "None"}:
        return None
    try:
        return str(int(float(s)))
    except Exception:
        return s


def season_dirs() -> list[Path]:
    return sorted([p for p in BASE.iterdir() if p.is_dir()])


def has_result_mask(df: pd.DataFrame) -> pd.Series:
    hs = df["home_score"].fillna("").astype(str).str.strip()
    aw = df["away_score"].fillna("").astype(str).str.strip()
    return (hs != "") & (aw != "")


def has_non_zero_score_mask(df: pd.DataFrame) -> pd.Series:
    hs = pd.to_numeric(df["home_score"], errors="coerce")
    aw = pd.to_numeric(df["away_score"], errors="coerce")
    return hs.notna() & aw.notna() & ((hs != 0) | (aw != 0))


def load_lineup_match_ids(season_dir: Path) -> set[str]:
    path = season_dir / "match_lineups" / "DEBUTANTE.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype=str, usecols=["match_id"])
    return set(df["match_id"].dropna().astype(str).tolist())


def club_appearances_from_matches(d: pd.DataFrame, teams: pd.DataFrame, season: str) -> pd.DataFrame:
    teams = teams.copy()
    teams["tid"] = teams["team_id"].map(norm_id)
    teams = teams[["tid", "club_name_raw"]].dropna(subset=["tid"]).drop_duplicates()
    id2club = dict(zip(teams["tid"], teams["club_name_raw"]))

    d = d.copy()
    d["home_tid"] = d["home_team_id"].map(norm_id)
    d["away_tid"] = d["away_team_id"].map(norm_id)

    home = d[["match_id", "home_tid"]].rename(columns={"home_tid": "tid"})
    away = d[["match_id", "away_tid"]].rename(columns={"away_tid": "tid"})
    app = pd.concat([home, away], ignore_index=True)
    app = app.dropna(subset=["tid"])
    app["club_name_raw"] = app["tid"].map(id2club)
    app = app.dropna(subset=["club_name_raw"])
    app["season"] = season
    return app[["season", "match_id", "tid", "club_name_raw"]]


def summarize_clubs(apps: pd.DataFrame, matches_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_season = (
        apps.groupby(["season", "club_name_raw"])["match_id"]
        .nunique()
        .reset_index(name=matches_col)
        .sort_values(["season", "club_name_raw"])
    )

    overall = (
        apps.groupby("club_name_raw")
        .agg(
            **{
                matches_col: ("match_id", "nunique"),
                "seasons_count": ("season", "nunique"),
            }
        )
        .reset_index()
    )
    season_list = (
        apps.groupby("club_name_raw")["season"]
        .apply(lambda s: ", ".join(sorted(set(s))))
        .reset_index(name="seasons")
    )
    overall = overall.merge(season_list, on="club_name_raw", how="left")
    overall = overall.sort_values([matches_col, "club_name_raw"], ascending=[False, True]).reset_index(drop=True)

    return overall, by_season


def build_matches_by_season() -> pd.DataFrame:
    rows = []
    for sdir in season_dirs():
        mp = sdir / "matches.csv"
        if not mp.exists():
            continue
        m = pd.read_csv(mp, dtype=str)
        d = m[m["category"].fillna("").str.upper() == "DEBUTANTE"].copy()
        if d.empty:
            continue
        dt = pd.to_datetime(d["match_date"], errors="coerce")
        vc = dt.dt.dayofweek.value_counts().to_dict()
        rows.append(
            {
                "season": sdir.name,
                "matches_total": len(d),
                "with_date": int(dt.notna().sum()),
                "without_date": int(dt.isna().sum()),
                "mon": int(vc.get(0, 0)),
                "tue": int(vc.get(1, 0)),
                "wed": int(vc.get(2, 0)),
                "thu": int(vc.get(3, 0)),
                "fri": int(vc.get(4, 0)),
                "sat": int(vc.get(5, 0)),
                "sun": int(vc.get(6, 0)),
            }
        )
    return pd.DataFrame(rows).sort_values("season")


def build_debutante_quality_by_season() -> pd.DataFrame:
    rows = []
    for sdir in season_dirs():
        mp = sdir / "matches.csv"
        if not mp.exists():
            continue
        m = pd.read_csv(mp, dtype=str)
        d = m[m["category"].fillna("").str.upper() == "DEBUTANTE"].copy()
        if d.empty:
            continue

        d["match_id"] = d["match_id"].astype(str)
        has_result = has_result_mask(d)
        has_non_zero = has_non_zero_score_mask(d)
        lineup_ids = load_lineup_match_ids(sdir)
        has_lineup = d["match_id"].isin(lineup_ids)
        has_both = has_result & has_lineup
        true_play = has_result & has_lineup & has_non_zero

        rows.append(
            {
                "season": sdir.name,
                "matches_total": len(d),
                "with_result_count": int(has_result.sum()),
                "with_result_pct": float(has_result.mean() * 100),
                "with_lineup_count": int(has_lineup.sum()),
                "with_lineup_pct": float(has_lineup.mean() * 100),
                "with_result_and_lineup_count": int(has_both.sum()),
                "with_result_and_lineup_pct": float(has_both.mean() * 100),
                "with_non_zero_score_count": int(has_non_zero.sum()),
                "with_non_zero_score_pct": float(has_non_zero.mean() * 100),
                "true_play_count": int(true_play.sum()),
                "true_play_pct": float(true_play.mean() * 100),
            }
        )

    return pd.DataFrame(rows).sort_values("season")


def build_clubs_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    all_rows = []
    for sdir in season_dirs():
        season = sdir.name
        mp = sdir / "matches.csv"
        tp = sdir / "teams.csv"
        if not mp.exists() or not tp.exists():
            continue

        m = pd.read_csv(mp, dtype=str)
        t = pd.read_csv(tp, dtype=str)
        d = m[m["category"].fillna("").str.upper() == "DEBUTANTE"].copy()
        if d.empty:
            continue

        all_rows.append(club_appearances_from_matches(d, t, season))

    apps = pd.concat(all_rows, ignore_index=True)
    overall, by_season = summarize_clubs(apps, "matches_total")
    return overall, by_season


def build_clubs_real_played() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clubs with strict true-play matches: result+lineup and non-zero score."""
    all_rows = []
    for sdir in season_dirs():
        season = sdir.name
        mp = sdir / "matches.csv"
        tp = sdir / "teams.csv"
        if not mp.exists() or not tp.exists():
            continue

        m = pd.read_csv(mp, dtype=str)
        t = pd.read_csv(tp, dtype=str)
        d = m[m["category"].fillna("").str.upper() == "DEBUTANTE"].copy()
        if d.empty:
            continue

        d["match_id"] = d["match_id"].astype(str)
        has_result = has_result_mask(d)
        has_non_zero = has_non_zero_score_mask(d)
        lineup_ids = load_lineup_match_ids(sdir)
        has_lineup = d["match_id"].isin(lineup_ids)
        d = d[has_result & has_lineup & has_non_zero].copy()
        if d.empty:
            continue

        all_rows.append(club_appearances_from_matches(d, t, season))

    if not all_rows:
        empty_overall = pd.DataFrame(columns=["club_name_raw", "matches_real_total", "seasons_count", "seasons"])
        empty_season = pd.DataFrame(columns=["season", "club_name_raw", "matches_real"])
        return empty_overall, empty_season

    apps = pd.concat(all_rows, ignore_index=True)
    overall, by_season = summarize_clubs(apps, "matches_real_total")
    by_season = by_season.rename(columns={"matches_real_total": "matches_real"})
    return overall, by_season


def team_rank_from_matches(matches: pd.DataFrame, teams: pd.DataFrame, metric_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    teams = teams.copy()
    teams["team_id_norm"] = teams["team_id"].map(norm_id)
    team_meta = teams[["team_id_norm", "club_name_raw", "team_name_raw"]].dropna(subset=["team_id_norm"]).drop_duplicates()

    m = matches.copy()
    m["home_team_id_norm"] = m["home_team_id"].map(norm_id)
    m["away_team_id_norm"] = m["away_team_id"].map(norm_id)

    home = m[["match_id", "home_team_id_norm"]].rename(columns={"home_team_id_norm": "team_id_norm"})
    away = m[["match_id", "away_team_id_norm"]].rename(columns={"away_team_id_norm": "team_id_norm"})
    apps = pd.concat([home, away], ignore_index=True).dropna(subset=["team_id_norm"])
    apps = apps.drop_duplicates()

    team_counts = apps.groupby("team_id_norm")["match_id"].nunique().reset_index(name=metric_col)
    team_counts = team_counts.merge(team_meta, on="team_id_norm", how="left")
    team_counts = team_counts.dropna(subset=["club_name_raw"])

    team_counts = team_counts.sort_values(["club_name_raw", metric_col, "team_name_raw"], ascending=[True, False, True])
    club_best = team_counts.groupby("club_name_raw", as_index=False).first()
    club_best = club_best[["club_name_raw", "team_name_raw", "team_id_norm", metric_col]]
    club_best = club_best.rename(columns={"team_name_raw": "best_team_name", "team_id_norm": "best_team_id"})
    club_best = club_best.sort_values([metric_col, "club_name_raw"], ascending=[False, True]).reset_index(drop=True)

    team_counts = team_counts.sort_values([metric_col, "club_name_raw", "team_name_raw"], ascending=[False, True, True])
    return club_best, team_counts


def build_2025_2026_best_team_by_club() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = BASE / "2025-2026"
    matches = pd.read_csv(base / "matches.csv", dtype=str)
    teams = pd.read_csv(base / "teams.csv", dtype=str)
    m = matches[matches["category"].fillna("").str.upper() == "DEBUTANTE"].copy()
    return team_rank_from_matches(m, teams, "team_matches")


def build_2025_2026_best_real_team_by_club() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = BASE / "2025-2026"
    matches = pd.read_csv(base / "matches.csv", dtype=str)
    teams = pd.read_csv(base / "teams.csv", dtype=str)

    m = matches[matches["category"].fillna("").str.upper() == "DEBUTANTE"].copy()
    m["match_id"] = m["match_id"].astype(str)
    has_result = has_result_mask(m)
    has_non_zero = has_non_zero_score_mask(m)
    lineup_ids = load_lineup_match_ids(base)
    has_lineup = m["match_id"].isin(lineup_ids)
    m = m[has_result & has_lineup & has_non_zero].copy()

    return team_rank_from_matches(m, teams, "team_matches_real")


def main() -> None:
    REPORTS.mkdir(exist_ok=True)

    by_season = build_matches_by_season()
    by_season.to_csv(REPORTS / "debutante_matches_by_season.csv", index=False, encoding="utf-8-sig")

    quality = build_debutante_quality_by_season()
    quality.to_csv(REPORTS / "debutante_quality_by_season.csv", index=False, encoding="utf-8-sig")

    clubs_all, clubs_by_season = build_clubs_all()
    clubs_all.to_csv(REPORTS / "debutante_clubs_all.csv", index=False, encoding="utf-8-sig")
    clubs_by_season.to_csv(REPORTS / "debutante_clubs_by_season.csv", index=False, encoding="utf-8-sig")

    clubs_real, clubs_real_by_season = build_clubs_real_played()
    clubs_real.to_csv(REPORTS / "debutante_clubs_real_played.csv", index=False, encoding="utf-8-sig")
    clubs_real_by_season.to_csv(REPORTS / "debutante_clubs_real_played_by_season.csv", index=False, encoding="utf-8-sig")

    club_best, team_counts = build_2025_2026_best_team_by_club()
    club_best.to_csv(REPORTS / "debutante_2025-2026_clubs_by_best_team_matches.csv", index=False, encoding="utf-8-sig")
    team_counts.to_csv(REPORTS / "debutante_2025-2026_teams_by_matches.csv", index=False, encoding="utf-8-sig")

    club_best_real, team_counts_real = build_2025_2026_best_real_team_by_club()
    club_best_real.to_csv(REPORTS / "debutante_2025-2026_clubs_by_best_team_real_matches.csv", index=False, encoding="utf-8-sig")
    team_counts_real.to_csv(REPORTS / "debutante_2025-2026_teams_by_real_matches.csv", index=False, encoding="utf-8-sig")

    print("Saved:")
    print(REPORTS / "debutante_matches_by_season.csv")
    print(REPORTS / "debutante_quality_by_season.csv")
    print(REPORTS / "debutante_clubs_all.csv")
    print(REPORTS / "debutante_clubs_by_season.csv")
    print(REPORTS / "debutante_clubs_real_played.csv")
    print(REPORTS / "debutante_clubs_real_played_by_season.csv")
    print(REPORTS / "debutante_2025-2026_clubs_by_best_team_matches.csv")
    print(REPORTS / "debutante_2025-2026_teams_by_matches.csv")
    print(REPORTS / "debutante_2025-2026_clubs_by_best_team_real_matches.csv")
    print(REPORTS / "debutante_2025-2026_teams_by_real_matches.csv")


if __name__ == "__main__":
    main()
