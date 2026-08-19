"""Club scorecard: the metrics catalog worked out in the Aravaca/Union
investigation, computed for an arbitrary club or for every club at once.

Design notes (why it's built this way):

- Club identity is `club_id` (site's real `codigo_club`), resolved via
  `club_teams.parquet` (every team_id a club has ever fielded, from
  /fichaclub/<club_id> - see DATA_DICTIONARY.md). This replaces the old
  club_name_raw string-matching approach entirely - no more chasing sponsor
  renames by hand. Universe of clubs = every club_id present in
  clubs_extended.parquet (currently 685) - clubs whose codigo_club was
  never resolved are out of scope for this framework by construction.

- Everything is computed for ALL clubs in one vectorized pass (groupby on
  team_id -> club_id joins), not a Python loop that re-scans the Parquet
  files per club. Use `--club-id` to filter the *display* to one club after
  computing; the computation itself is always full-batch.

- Founding-cohort seasons (see the conversation this was designed in):
  PREBENJAMIN/ALEVIN start data-complete lineup coverage differ by category
  (PREBENJAMIN was futsal-only with ~100 matches/season region-wide before
  2021-2022, when it widened to Futbol-7 and jumped to ~8000+; every other
  category already had thousands of matches back to 2017-2018, the first
  season with any match_lineups files at all). ALEVIN also grew ~2.5x in
  2021-2022, but by user decision it's grouped with the "8-season" cohort
  (2017-2018) rather than the "4-season" one (2021-2022).

- No minimum-sample-size gate: every metric is reported with its `n`
  alongside it, exactly as computed - it's on the reader to weigh a 3-child
  cohort's 33% differently than a 40-child cohort's 33%. This was a
  deliberate choice (option "as-is, trust the reader"), not an oversight.

- The "max level ever reached" metric is deliberately split into two
  numbers: reached while still registered at this club, vs. reached at
  another club in a season *after* the player's last season at this club.
  Rows at other clubs that are not chronologically after the last
  in-club season (e.g. dual registration, or a club visited before joining)
  are excluded from the "after leaving" side on purpose - see
  `_split_elite_reach` for exactly how "after leaving" is defined.

Run:
    python3 analysis_scripts/club_scorecard.py --club-id 1011
    python3 analysis_scripts/club_scorecard.py --all --out /tmp/scorecards
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PARQUET_ROOT = Path(__file__).resolve().parent.parent / "output" / "processed" / "rffm_parquet"

# --- Division tier map (DIVISIONS.md) - lower number = higher level. ---
TIER_MAP = {
    "SUPERLIGA": 1,
    "LIGA NACIONAL": 1,
    "DIVISION DE HONOR": 2,
    "PRIMERA DIVISION AUTONOMICA": 3,
    "PREFERENTE": 4,
    "SEGUNDA DIVISION B": 5,
    "TERCERA FEDERACION": 5,
    "PRIMERA": 6,
    "SEGUNDA": 7,
    "TERCERA": 8,
}
ELITE_TIER_MAX = 2  # tier <= this counts as "elite" (SUPERLIGA/LIGA NACIONAL/DIVISION DE HONOR)

# --- Youth age ladder + each category's founding-cohort season (see module
# docstring for why these differ) and the full season list available. ---
ALL_SEASONS = [
    "2016-2017", "2017-2018", "2018-2019", "2019-2020", "2020-2021",
    "2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026",
]
LATEST_SEASON = ALL_SEASONS[-1]
AGE_LADDER = ["DEBUTANTE", "PREBENJAMIN", "BENJAMIN", "ALEVIN", "INFANTIL", "CADETE", "JUVENIL"]
ENTRY_CATEGORIES = {"DEBUTANTE", "PREBENJAMIN"}  # "grew up here" = first seen at this club at this age
FOUNDING_COHORT_SEASON = {
    "PREBENJAMIN": "2021-2022",
    "ALEVIN": "2017-2018",
    "BENJAMIN": "2017-2018",
    "INFANTIL": "2017-2018",
    "CADETE": "2017-2018",
    "JUVENIL": "2017-2018",
}
LINEUP_CATEGORIES = list(FOUNDING_COHORT_SEASON.keys())  # categories with match_lineups files


def _season_idx(season: str) -> int:
    return ALL_SEASONS.index(season)


# ---------------------------------------------------------------------------
# Data loading (once, shared across every metric / every club)
# ---------------------------------------------------------------------------

class Data:
    """Everything loaded once. Attributes are plain DataFrames."""

    def __init__(self, root: Path = PARQUET_ROOT):
        self.root = root
        print("Loading base tables...", file=sys.stderr)
        self.club_teams = pd.read_parquet(root / "club_teams.parquet")
        self.clubs_extended = pd.read_parquet(root / "clubs_extended.parquet")
        self.competitions = pd.read_parquet(root / "competitions.parquet")
        self.team_group_membership = pd.read_parquet(root / "team_group_membership.parquet")
        self.standings = pd.read_parquet(root / "standings.parquet")
        self.teams = pd.read_parquet(root / "teams.parquet")

        # team_id -> club_id, deduped (see DATA_DICTIONARY.md's "current
        # state" recipe - club_teams is an append-only snapshot log; today
        # there's exactly one snapshot so this is a no-op, but stays correct
        # once more snapshots accumulate).
        current_club_teams = (
            self.club_teams.sort_values("scraped_at").groupby(["club_id", "team_id"]).tail(1)
        )
        # A team_id should belong to one club; if the site ever reassigns one
        # (shouldn't happen - team_id is club-scoped on the site), keep the
        # most-recently-seen mapping.
        self.team_to_club = (
            current_club_teams.sort_values("scraped_at")
            .drop_duplicates(subset="team_id", keep="last")
            .set_index("team_id")["club_id"]
        )
        self._supplement_team_to_club_from_teams_csv()

        # competition_id -> tier, category_base, phase_label (regular season only).
        # Deliberately excludes competitions.season - team_group_membership
        # already carries its own season column, and joining a second one in
        # would silently suffix both to season_x/season_y.
        comps = self.competitions.copy()
        comps["tier"] = comps["division_level"].map(TIER_MAP)
        self.comp_meta = comps.set_index("competition_id")[
            ["category_base", "division_level", "tier", "phase_label"]
        ]

        print("Loading match_lineups (all categories x seasons)...", file=sys.stderr)
        self.lineups = self._load_lineups()
        print(f"  -> {len(self.lineups):,} lineup rows", file=sys.stderr)

        print("Loading standings-linked team_group_membership (regular season)...", file=sys.stderr)
        self.tgm_reg = self.team_group_membership.merge(
            self.comp_meta, left_on="competition_id", right_index=True, how="left"
        )
        self.tgm_reg = self.tgm_reg[self.tgm_reg["phase_label"] == "regular_season"].copy()
        self.tgm_reg["club_id"] = self.tgm_reg["team_id"].map(self.team_to_club)

        print("Loading match_cards...", file=sys.stderr)
        self.cards = self._load_glob("match_cards")
        print("Loading matches (for cards-per-match denominator)...", file=sys.stderr)
        self.matches = pd.read_parquet(root / "matches.parquet")

    def _supplement_team_to_club_from_teams_csv(self) -> None:
        """`club_teams.parquet`'s `equipos_club` roster is not always complete
        (confirmed live: Union de Aravaca's own team_id 4937443, a real
        PREBENJAMIN 'B' squad that played real matches, is simply absent from
        its club's /fichaclub/ team list - understating its 2021-2022 cohort
        by more than half, 14 vs the real 29). Fix: within each season's
        teams.csv, every team_id sharing one `club_name_raw` is the same club
        (verified repeatedly for Aravaca/Union across 10 seasons of sponsor
        renames) - so if ANY team in that group already resolved to a
        club_id via club_teams, propagate it to the rest of the group too.
        """
        teams = self.teams.copy()
        teams["club_id"] = teams["team_id"].map(self.team_to_club)
        known = teams.dropna(subset=["club_id"])
        # club_name_raw -> the (should-be-singular) club_id its known members resolved to
        name_to_club = known.groupby("club_name_raw")["club_id"].agg(lambda s: s.mode().iat[0])
        unresolved = teams[teams["club_id"].isna()].copy()
        unresolved["inferred_club_id"] = unresolved["club_name_raw"].map(name_to_club)
        filled = unresolved.dropna(subset=["inferred_club_id"])
        if len(filled):
            addition = filled.drop_duplicates("team_id").set_index("team_id")["inferred_club_id"]
            self.team_to_club = pd.concat([self.team_to_club, addition])
            print(
                f"  -> supplemented {len(addition)} team_id -> club_id mappings "
                f"missing from club_teams.parquet, via club_name_raw fallback",
                file=sys.stderr,
            )

    def _load_glob(self, subdir: str) -> pd.DataFrame:
        paths = sorted(glob.glob(str(self.root / subdir / "*.parquet")))
        frames = []
        for p in paths:
            season = Path(p).stem
            df = pd.read_parquet(p)
            df["season"] = season
            frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _load_lineups(self) -> pd.DataFrame:
        # One Parquet file per season (all categories combined in one file,
        # discriminated by `category_base`) - not one file per category like
        # the CSV copy's match_lineups/<category>.csv layout.
        frames = []
        for season in ALL_SEASONS:
            p = self.root / "match_lineups" / f"{season}.parquet"
            if not p.exists():
                continue
            df = pd.read_parquet(p, columns=["category_base", "match_id", "team_id", "player_id"])
            df = df[df["category_base"].isin(LINEUP_CATEGORIES)].copy()
            df["season"] = season
            df.rename(columns={"category_base": "category"}, inplace=True)
            frames.append(df)
        out = pd.concat(frames, ignore_index=True)
        out["club_id"] = out["team_id"].map(self.team_to_club)
        out["season_idx"] = out["season"].map(_season_idx)
        return out


# ---------------------------------------------------------------------------
# Metric 1-3: size/structure, current-season level, ceiling
# ---------------------------------------------------------------------------

def metric_size_and_ceiling(data: Data) -> pd.DataFrame:
    """One row per club_id: team count trend, current-season snapshot, all-time ceiling."""
    tgm = data.tgm_reg.dropna(subset=["club_id"])

    teams_per_season = (
        tgm.groupby(["club_id", "season"])["team_id"].nunique().unstack(fill_value=0)
    )
    teams_per_season = teams_per_season.reindex(columns=ALL_SEASONS, fill_value=0)

    players_per_season = (
        data.lineups.dropna(subset=["club_id"])
        .groupby(["club_id", "season"])["player_id"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(columns=ALL_SEASONS, fill_value=0)
    )

    def _slope(row: pd.Series) -> float:
        y = row.values.astype(float)
        x = np.arange(len(y))
        mask = y > 0
        if mask.sum() < 2:
            return np.nan
        return float(np.polyfit(x[mask], y[mask], 1)[0])

    headcount_trend = players_per_season.apply(_slope, axis=1).rename("headcount_trend_slope")

    ceiling = (
        tgm.dropna(subset=["tier"])
        .groupby("club_id")
        .apply(lambda g: g.loc[g["tier"].idxmin(), ["tier", "division_level", "category_base", "season"]])
        .rename(columns={
            "tier": "ceiling_tier", "division_level": "ceiling_division",
            "category_base": "ceiling_category", "season": "ceiling_season",
        })
    )

    latest = tgm[tgm["season"] == LATEST_SEASON]
    current_teams = latest.groupby("club_id")["team_id"].nunique().rename("teams_current_season")
    current_best_tier = (
        latest.dropna(subset=["tier"]).groupby("club_id")["tier"].min().rename("best_tier_current_season")
    )

    out = pd.DataFrame(index=sorted(set(teams_per_season.index) | set(players_per_season.index)))
    out["teams_latest_season"] = teams_per_season.get(LATEST_SEASON)
    out["players_latest_season"] = players_per_season.get(LATEST_SEASON)
    out = out.join(headcount_trend).join(ceiling).join(current_teams).join(current_best_tier)
    out.index.name = "club_id"
    return out.reset_index()


# ---------------------------------------------------------------------------
# Metric 4-5: retention curves (in-club, in-football)
# ---------------------------------------------------------------------------

def _cohort_players(data: Data, category: str) -> pd.DataFrame:
    season = FOUNDING_COHORT_SEASON[category]
    sub = data.lineups[(data.lineups["category"] == category) & (data.lineups["season"] == season)]
    return sub.dropna(subset=["club_id"])[["club_id", "player_id"]].drop_duplicates()


def metric_retention_curves(data: Data) -> pd.DataFrame:
    """One row per (club_id, category): retention_in_club_yN / retention_in_football_yN
    for every N-season horizon available from that category's founding cohort to 2025-2026.
    """
    rows = []
    for category, cohort_season in FOUNDING_COHORT_SEASON.items():
        cohort = _cohort_players(data, category)
        if cohort.empty:
            continue
        max_horizon = len(ALL_SEASONS) - 1 - _season_idx(cohort_season)
        club_sizes = cohort.groupby("club_id")["player_id"].nunique()

        by_club_players = {cid: set(g["player_id"]) for cid, g in cohort.groupby("club_id")}

        for horizon in range(1, max_horizon + 1):
            target_season = ALL_SEASONS[_season_idx(cohort_season) + horizon]
            present_any = set(data.lineups.loc[data.lineups["season"] == target_season, "player_id"])
            present_by_club = (
                data.lineups.loc[data.lineups["season"] == target_season]
                .groupby("club_id")["player_id"]
                .apply(set)
            )
            for cid, players in by_club_players.items():
                n = len(players)
                still_football = len(players & present_any)
                still_club = len(players & present_by_club.get(cid, set()))
                rows.append({
                    "club_id": cid, "category": category, "cohort_season": cohort_season,
                    "n": n, "horizon_years": horizon,
                    "retained_in_club": still_club, "retained_in_club_pct": still_club / n * 100,
                    "retained_in_football": still_football, "retained_in_football_pct": still_football / n * 100,
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Metric 6-8: elite pathway (first-appearance homegrown-ness, level split, current-squad homegrown %)
# ---------------------------------------------------------------------------

def _first_appearance(data: Data) -> pd.DataFrame:
    """Per player_id: earliest (season, category, club_id) row on record."""
    df = data.lineups.dropna(subset=["club_id"]).sort_values("season_idx")
    first = df.groupby("player_id").first()[["season", "category", "club_id"]]
    first.columns = ["first_season", "first_category", "first_club_id"]
    return first


def _best_tier_per_player_club(data: Data) -> pd.DataFrame:
    """Per (player_id, club_id, season): best tier the player's team competed at
    that season (join lineups -> team's regular-season tier that season)."""
    team_season_tier = (
        data.tgm_reg.dropna(subset=["tier"])
        .groupby(["team_id", "season"])["tier"]
        .min()
        .rename("tier")
        .reset_index()
    )
    merged = data.lineups.merge(team_season_tier, on=["team_id", "season"], how="inner")
    return merged.dropna(subset=["club_id"])


def metric_elite_pathway(data: Data) -> pd.DataFrame:
    """One row per club_id: alumni pool size, % ever elite (in-club / after-leaving
    split), and of the elite ones, how many were first seen at this club at
    entry age (DEBUTANTE/PREBENJAMIN)."""
    pt = _best_tier_per_player_club(data)
    first = _first_appearance(data)

    alumni = pt[["player_id", "club_id"]].drop_duplicates()
    alumni_by_club = alumni.groupby("club_id")["player_id"].apply(set)

    # last season a player was at each club (for the "after leaving" chronology test)
    last_season_at_club = (
        pt.groupby(["player_id", "club_id"])["season_idx"].max().rename("last_idx").reset_index()
    )

    rows = []
    for cid, players in alumni_by_club.items():
        sub = pt[pt["player_id"].isin(players)]
        in_club = sub[sub["club_id"] == cid]
        elite_in_club = set(in_club.loc[in_club["tier"] <= ELITE_TIER_MAX, "player_id"])

        last_idx = dict(
            zip(
                last_season_at_club.loc[last_season_at_club["club_id"] == cid, "player_id"],
                last_season_at_club.loc[last_season_at_club["club_id"] == cid, "last_idx"],
            )
        )
        other = sub[sub["club_id"] != cid].copy()
        other["cutoff"] = other["player_id"].map(last_idx)
        after_leaving = other[other["season_idx"] > other["cutoff"]]
        elite_after_leaving = set(after_leaving.loc[after_leaving["tier"] <= ELITE_TIER_MAX, "player_id"])

        elite_any = elite_in_club | elite_after_leaving
        homegrown_elite = 0
        homegrown_unknown = 0  # first tracked row predates PREBENJAMIN/DEBUTANTE
        # going wide (2021-2022) - can't tell if they had an earlier entry-age
        # stint that simply isn't in the data (see PREBENJAMIN futsal-only
        # era note in the module docstring) - NOT the same as "recruited".
        entry_floor_idx = _season_idx(FOUNDING_COHORT_SEASON["PREBENJAMIN"])
        for pid in elite_any:
            if pid not in first.index:
                continue
            f = first.loc[pid]
            if f["first_club_id"] == cid and f["first_category"] in ENTRY_CATEGORIES:
                homegrown_elite += 1
            elif _season_idx(f["first_season"]) < entry_floor_idx:
                homegrown_unknown += 1

        n = len(players)
        elite_known_n = len(elite_any) - homegrown_unknown
        rows.append({
            "club_id": cid,
            "alumni_pool_n": n,
            "elite_in_club_n": len(elite_in_club),
            "elite_in_club_pct": len(elite_in_club) / n * 100,
            "elite_after_leaving_n": len(elite_after_leaving - elite_in_club),
            "elite_after_leaving_pct": len(elite_after_leaving - elite_in_club) / n * 100,
            "elite_any_n": len(elite_any),
            "elite_any_pct": len(elite_any) / n * 100,
            "elite_homegrown_n": homegrown_elite,
            "elite_homegrown_data_unknown_n": homegrown_unknown,
            "elite_homegrown_pct_of_known": (homegrown_elite / elite_known_n * 100) if elite_known_n else np.nan,
        })
    return pd.DataFrame(rows)


def metric_current_squad_homegrown(data: Data) -> pd.DataFrame:
    """One row per club_id: of players in the CURRENT top team (best tier this
    season), % first seen at this club at entry age - i.e. "will my kid still
    be a starter here, or displaced by recruits, if the team goes far"."""
    # Youth categories only - this metric is about the child-development
    # pathway ("will my kid still be a starter on the top team"), so an
    # adult AFICIONADO/SENIOR squad reaching a higher tier than any youth
    # team (common for smaller clubs) shouldn't hijack the "top team" pick.
    latest = data.tgm_reg[
        (data.tgm_reg["season"] == LATEST_SEASON) & (data.tgm_reg["category_base"].isin(LINEUP_CATEGORIES))
    ].dropna(subset=["tier", "club_id"])
    top_team = latest.loc[latest.groupby("club_id")["tier"].idxmin()][["club_id", "team_id", "tier", "category_base"]]

    lu_latest = data.lineups[data.lineups["season"] == LATEST_SEASON]
    first = _first_appearance(data)

    rows = []
    for _, r in top_team.iterrows():
        cid, tid = r["club_id"], r["team_id"]
        players = set(lu_latest.loc[lu_latest["team_id"] == tid, "player_id"])
        if not players:
            continue
        homegrown = 0
        unknown = 0
        entry_floor_idx = _season_idx(FOUNDING_COHORT_SEASON["PREBENJAMIN"])
        for pid in players:
            if pid not in first.index:
                continue
            f = first.loc[pid]
            if f["first_club_id"] == cid and f["first_category"] in ENTRY_CATEGORIES:
                homegrown += 1
            elif _season_idx(f["first_season"]) < entry_floor_idx:
                unknown += 1
        known_n = len(players) - unknown
        rows.append({
            "club_id": cid, "top_team_id": tid, "top_team_tier": r["tier"],
            "top_team_category": r["category_base"], "top_team_n": len(players),
            "top_team_homegrown_n": homegrown, "top_team_data_unknown_n": unknown,
            "top_team_homegrown_pct_of_known": (homegrown / known_n * 100) if known_n else np.nan,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Metric 10: transfer balance with other clubs (net flow)
# ---------------------------------------------------------------------------

def metric_transfer_balance(data: Data) -> pd.DataFrame:
    """One row per (club_id, direction-aggregated): net flow of players who
    played for club A one season and a DIFFERENT club_id the very next season
    (not both - dual registration is excluded), summed across all seasons."""
    lu = data.lineups.dropna(subset=["club_id"])[["player_id", "season", "season_idx", "club_id"]].drop_duplicates()
    lu = lu.sort_values(["player_id", "season_idx"])

    lu["next_idx"] = lu.groupby("player_id")["season_idx"].shift(-1)
    lu["next_club"] = lu.groupby("player_id")["club_id"].shift(-1)
    moves = lu[(lu["next_idx"] == lu["season_idx"] + 1) & (lu["next_club"] != lu["club_id"])]
    moves = moves.dropna(subset=["next_club"])

    out_flow = moves.groupby("club_id")["player_id"].nunique().rename("players_left")
    in_flow = moves.groupby("next_club")["player_id"].nunique().rename("players_joined")
    out_flow.index.name = "club_id"
    in_flow.index.name = "club_id"

    result = pd.concat([out_flow, in_flow], axis=1).fillna(0).astype(int)
    result["net_flow"] = result["players_joined"] - result["players_left"]
    return result.reset_index()


# ---------------------------------------------------------------------------
# Metric 11: squad continuity (does the club keep fielding a team every year)
# ---------------------------------------------------------------------------

def metric_squad_continuity(data: Data) -> pd.DataFrame:
    """One row per club_id: of the seasons between this club's first and last
    seen season (across any category), what fraction had at least one team
    fielded - i.e. did the club ever go dark and come back."""
    tgm = data.tgm_reg.dropna(subset=["club_id"])
    seasons_present = tgm.groupby("club_id")["season"].apply(lambda s: sorted(set(s), key=_season_idx))

    rows = []
    for cid, seasons in seasons_present.items():
        first_idx, last_idx = _season_idx(seasons[0]), _season_idx(seasons[-1])
        span = last_idx - first_idx + 1
        rows.append({
            "club_id": cid,
            "first_season_seen": seasons[0],
            "last_season_seen": seasons[-1],
            "seasons_span": span,
            "seasons_present": len(seasons),
            "continuity_pct": len(seasons) / span * 100 if span else np.nan,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Metric 12-13: sanction points, cards per match
# ---------------------------------------------------------------------------

def metric_discipline(data: Data) -> pd.DataFrame:
    st = data.standings.copy()
    st["club_id"] = st["team_id"].map(data.team_to_club)
    st = st.dropna(subset=["club_id"])
    sanctions = (
        st.groupby(["club_id", "season"])["sanction_points"].sum().groupby("club_id").mean()
        .rename("avg_sanction_points_per_season")
    )

    cards = data.cards.copy()
    cards["club_id"] = cards["team_id"].map(data.team_to_club)
    cards_per_club = cards.dropna(subset=["club_id"]).groupby("club_id").size().rename("total_cards")

    m = data.matches.dropna(subset=["home_team_id"]).copy()
    m["home_club"] = m["home_team_id"].map(data.team_to_club)
    m["away_club"] = m["away_team_id"].map(data.team_to_club)
    home_matches = m.groupby("home_club").size()
    away_matches = m.groupby("away_club").size()
    matches_played = home_matches.add(away_matches, fill_value=0).rename("matches_played_alltime")

    out = pd.concat([sanctions, cards_per_club, matches_played], axis=1)
    out["cards_per_match"] = out["total_cards"] / out["matches_played_alltime"]
    out.index.name = "club_id"
    return out.reset_index()


# ---------------------------------------------------------------------------
# Metric 14: playing-time equity (Gini of appearance counts within a team-season)
# ---------------------------------------------------------------------------

def _gini(x: np.ndarray) -> float:
    x = np.sort(x.astype(float))
    n = len(x)
    if n < 2 or x.sum() == 0:
        return np.nan
    cum = np.cumsum(x)
    return float((n + 1 - 2 * (cum.sum() / cum[-1])) / n)


def metric_playing_time_equity(data: Data) -> pd.DataFrame:
    appearances = data.lineups.groupby(["team_id", "season", "player_id"]).size().rename("apps").reset_index()
    gini_per_team_season = (
        appearances.groupby(["team_id", "season"])["apps"].apply(lambda s: _gini(s.values)).rename("gini")
    )
    gini_per_team_season = gini_per_team_season.reset_index()
    gini_per_team_season["club_id"] = gini_per_team_season["team_id"].map(data.team_to_club)
    out = (
        gini_per_team_season.dropna(subset=["club_id"])
        .groupby("club_id")["gini"].mean()
        .rename("avg_playing_time_gini")
    )
    return out.reset_index()


# ---------------------------------------------------------------------------
# Metric 15: result volatility (std dev of tier reached by the club's best team, by season)
# ---------------------------------------------------------------------------

def metric_result_volatility(data: Data) -> pd.DataFrame:
    tgm = data.tgm_reg.dropna(subset=["tier", "club_id"])
    best_tier_per_season = tgm.groupby(["club_id", "season"])["tier"].min()
    vol = best_tier_per_season.groupby("club_id").std().rename("best_tier_std_dev")
    n_seasons = best_tier_per_season.groupby("club_id").size().rename("seasons_with_data")
    return pd.concat([vol, n_seasons], axis=1).reset_index()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def compute_all(data: Data) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (club_level_df, club_cohort_df)."""
    print("Computing metric 1-3 (size/ceiling)...", file=sys.stderr)
    m123 = metric_size_and_ceiling(data)
    print("Computing metric 10 (transfer balance)...", file=sys.stderr)
    m10 = metric_transfer_balance(data)
    print("Computing metric 11 (squad continuity)...", file=sys.stderr)
    m11 = metric_squad_continuity(data)
    print("Computing metric 12-13 (discipline)...", file=sys.stderr)
    m1213 = metric_discipline(data)
    print("Computing metric 14 (playing-time equity)...", file=sys.stderr)
    m14 = metric_playing_time_equity(data)
    print("Computing metric 15 (result volatility)...", file=sys.stderr)
    m15 = metric_result_volatility(data)
    print("Computing metric 6-7 (elite pathway)...", file=sys.stderr)
    m67 = metric_elite_pathway(data)
    print("Computing metric 8 (current-squad homegrown %)...", file=sys.stderr)
    m8 = metric_current_squad_homegrown(data)

    club_level = data.clubs_extended[["club_id", "club_name"]].drop_duplicates()
    for m in [m123, m10, m11, m1213, m14, m15, m67, m8]:
        club_level = club_level.merge(m, on="club_id", how="left")

    print("Computing metric 4-5 (retention curves)...", file=sys.stderr)
    club_cohort = metric_retention_curves(data)
    club_cohort = club_cohort.merge(data.clubs_extended[["club_id", "club_name"]].drop_duplicates(), on="club_id", how="left")

    return club_level, club_cohort


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--club-id", type=int, help="Show results for one club_id only")
    ap.add_argument("--club-name", type=str, help="Show results for club(s) matching this name substring")
    ap.add_argument("--out", type=str, help="Directory to write club_level.csv / club_cohort.csv into")
    ap.add_argument("--all", action="store_true", help="Compute for every club (default if --out given)")
    args = ap.parse_args()

    data = Data()
    club_level, club_cohort = compute_all(data)

    if args.out:
        outdir = Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
        club_level.to_csv(outdir / "club_level.csv", index=False)
        club_cohort.to_csv(outdir / "club_cohort.csv", index=False)
        print(f"Wrote {len(club_level)} club_level rows and {len(club_cohort)} club_cohort rows to {outdir}")

    target_ids = None
    if args.club_id:
        target_ids = [args.club_id]
    elif args.club_name:
        target_ids = data.clubs_extended.loc[
            data.clubs_extended["club_name"].str.contains(args.club_name, case=False, na=False), "club_id"
        ].tolist()

    if target_ids:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 200)
        print("\n=== club_level ===")
        print(club_level[club_level["club_id"].isin(target_ids)].T)
        print("\n=== club_cohort ===")
        print(club_cohort[club_cohort["club_id"].isin(target_ids)].to_string(index=False))


if __name__ == "__main__":
    main()
