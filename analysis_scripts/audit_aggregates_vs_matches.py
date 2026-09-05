"""Cross-season audit: aggregate tables (standings/scorers/player_season_stats)
vs. match-level tables (matches/match_goals/match_cards/match_lineups).

Started from one confirmed case (25 groups in 2024-2025 with full
standings/scorers but zero matches.csv rows - see DATA_FINDINGS.md's first
entry). This script generalizes that anti-join into a family of checks
looking for the same "aggregate says X, matches say something else" shape.

Read-only: queries output/processed/rffm_parquet/ via DuckDB, writes one CSV
per check under analysis_scripts/audit_output/ for inspection, and prints a
summary + a couple of examples per check. Findings worth keeping get written
up by hand in DATA_FINDINGS.md - this script does not touch that file.

Run: python analysis_scripts/audit_aggregates_vs_matches.py
"""

import os

import duckdb
import pandas as pd

PARQUET = "output/processed/rffm_parquet"
OUT_DIR = "analysis_scripts/audit_output"
os.makedirs(OUT_DIR, exist_ok=True)

con = duckdb.connect()


def p(table, season="*"):
    return f"'{PARQUET}/{table}/{season}.parquet'"


def save(df, name):
    path = os.path.join(OUT_DIR, f"{name}.csv")
    df.to_csv(path, index=False)
    return path


def section(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


# ---------------------------------------------------------------------------
# Check 1: groups with standings/scorers rows but zero matches.csv rows at all
# ---------------------------------------------------------------------------
def check_missing_groups():
    section("CHECK 1 - groups with standings/scorers but zero matches.csv rows")

    q = f"""
    WITH standings_groups AS (
        SELECT DISTINCT season, group_id FROM read_parquet({p('standings')})
    ),
    scorers_groups AS (
        SELECT DISTINCT season, group_id FROM read_parquet({p('scorers')})
    ),
    membership_groups AS (
        SELECT DISTINCT season, group_id FROM read_parquet({p('team_group_membership')})
    ),
    matches_groups AS (
        SELECT DISTINCT season, group_id FROM read_parquet({p('matches')})
    ),
    total_groups AS (
        SELECT DISTINCT season, group_id FROM read_parquet({p('groups')})
    )
    SELECT
        tg.season, tg.group_id,
        (sg.group_id IS NOT NULL) AS has_standings,
        (sc.group_id IS NOT NULL) AS has_scorers,
        (mg.group_id IS NOT NULL) AS has_membership,
        (mtg.group_id IS NOT NULL) AS has_matches
    FROM total_groups tg
    LEFT JOIN standings_groups sg USING (season, group_id)
    LEFT JOIN scorers_groups sc USING (season, group_id)
    LEFT JOIN membership_groups mg USING (season, group_id)
    LEFT JOIN matches_groups mtg USING (season, group_id)
    WHERE mtg.group_id IS NULL
      AND (sg.group_id IS NOT NULL OR sc.group_id IS NOT NULL OR mg.group_id IS NOT NULL)
    ORDER BY tg.season, tg.group_id
    """
    df = con.execute(q).df()
    save(df, "check1_groups_missing_matches")

    print(f"Total groups with some aggregate presence but 0 matches.csv rows: {len(df)}")
    if len(df):
        print(df.groupby("season").size())
        print("\nCategory breakdown for affected groups:")
        groups_ids = df["group_id"].tolist()
        cat_q = f"""
        SELECT g.season, g.category, count(*) n
        FROM read_parquet({p('groups')}) g
        WHERE g.group_id IN ({','.join(map(str, groups_ids))})
        GROUP BY g.season, g.category ORDER BY g.season, n DESC
        """
        print(con.execute(cat_q).df().to_string())
    return df


# ---------------------------------------------------------------------------
# Check 2: standings.played vs actual finished-match count per team/group
# (excludes groups already flagged fully-missing in check 1)
# ---------------------------------------------------------------------------
def check_partial_match_counts(missing_groups_df):
    section("CHECK 2 - standings.played vs count of finished matches.csv rows per team/group")

    exclude = set(zip(missing_groups_df["season"], missing_groups_df["group_id"]))

    q = f"""
    WITH match_counts AS (
        SELECT season, group_id, home_team_id AS team_id, count(*) AS n
        FROM read_parquet({p('matches')})
        WHERE is_finished = true AND home_team_id IS NOT NULL
        GROUP BY season, group_id, home_team_id
        UNION ALL
        SELECT season, group_id, away_team_id AS team_id, count(*) AS n
        FROM read_parquet({p('matches')})
        WHERE is_finished = true AND away_team_id IS NOT NULL
        GROUP BY season, group_id, away_team_id
    ),
    played_counts AS (
        SELECT season, group_id, team_id, sum(n) AS matches_in_csv
        FROM match_counts
        GROUP BY season, group_id, team_id
    )
    SELECT
        s.season, s.group_id, s.team_id, s.team,
        s.played AS standings_played,
        COALESCE(pc.matches_in_csv, 0) AS matches_in_csv,
        s.played - COALESCE(pc.matches_in_csv, 0) AS diff
    FROM read_parquet({p('standings')}) s
    LEFT JOIN played_counts pc USING (season, group_id, team_id)
    WHERE s.played != COALESCE(pc.matches_in_csv, 0)
    ORDER BY abs(s.played - COALESCE(pc.matches_in_csv, 0)) DESC
    """
    df = con.execute(q).df()
    df = df[~df.apply(lambda r: (r["season"], r["group_id"]) in exclude, axis=1)]
    save(df, "check2_team_played_mismatch")

    n_teams = len(df)
    n_groups = df[["season", "group_id"]].drop_duplicates().shape[0]
    n_seasons = df["season"].nunique()
    print(f"Team/group rows with played != matches.csv count (excl. fully-missing groups): {n_teams}")
    print(f"Spans {n_groups} distinct (season, group_id) pairs across {n_seasons} seasons")
    print("\nBy season:")
    print(df.groupby("season").size())
    print("\nDiff distribution (standings_played - matches_in_csv):")
    print(df["diff"].value_counts().sort_index())
    print("\nTop 10 examples:")
    print(df.head(10).to_string())
    return df


# ---------------------------------------------------------------------------
# Check 3: standings.goals_for/goals_against vs summed matches.csv scores
# ---------------------------------------------------------------------------
def check_goals_totals(missing_groups_df):
    section("CHECK 3 - standings.goals_for/goals_against vs summed matches.csv scores")

    exclude = set(zip(missing_groups_df["season"], missing_groups_df["group_id"]))

    q = f"""
    WITH per_team AS (
        SELECT season, group_id, home_team_id AS team_id,
               sum(home_score) AS gf, sum(away_score) AS ga
        FROM read_parquet({p('matches')})
        WHERE is_finished = true AND home_team_id IS NOT NULL
        GROUP BY season, group_id, home_team_id
        UNION ALL
        SELECT season, group_id, away_team_id AS team_id,
               sum(away_score) AS gf, sum(home_score) AS ga
        FROM read_parquet({p('matches')})
        WHERE is_finished = true AND away_team_id IS NOT NULL
        GROUP BY season, group_id, away_team_id
    ),
    totals AS (
        SELECT season, group_id, team_id, sum(gf) AS goals_for_csv, sum(ga) AS goals_against_csv
        FROM per_team
        GROUP BY season, group_id, team_id
    )
    SELECT
        s.season, s.group_id, s.team_id, s.team,
        s.goals_for AS standings_gf, COALESCE(t.goals_for_csv, 0) AS matches_gf,
        s.goals_against AS standings_ga, COALESCE(t.goals_against_csv, 0) AS matches_ga,
        s.goals_for - COALESCE(t.goals_for_csv, 0) AS gf_diff,
        s.goals_against - COALESCE(t.goals_against_csv, 0) AS ga_diff
    FROM read_parquet({p('standings')}) s
    LEFT JOIN totals t USING (season, group_id, team_id)
    WHERE s.goals_for != COALESCE(t.goals_for_csv, 0)
       OR s.goals_against != COALESCE(t.goals_against_csv, 0)
    ORDER BY (abs(s.goals_for - COALESCE(t.goals_for_csv, 0)) + abs(s.goals_against - COALESCE(t.goals_against_csv, 0))) DESC
    """
    df = con.execute(q).df()
    df = df[~df.apply(lambda r: (r["season"], r["group_id"]) in exclude, axis=1)]
    save(df, "check3_goals_mismatch")

    print(f"Team/group rows with goals_for/against mismatch (excl. fully-missing groups): {len(df)}")
    print("\nBy season:")
    print(df.groupby("season").size())
    print("\nTop 10 examples:")
    print(df.head(10).to_string())
    return df


# ---------------------------------------------------------------------------
# Check 4: scorers.csv group-level goal total vs match_goals row count for
# that group (sidesteps scorers.csv having no player_id - group-level only)
# ---------------------------------------------------------------------------
def check_scorers_vs_match_goals(missing_groups_df):
    section("CHECK 4 - scorers.csv total goals per group vs match_goals row count for that group")

    exclude = set(zip(missing_groups_df["season"], missing_groups_df["group_id"]))

    q = f"""
    WITH scorer_totals AS (
        SELECT season, group_id, sum(goals) AS scorers_total_goals
        FROM read_parquet({p('scorers')})
        GROUP BY season, group_id
    ),
    goal_counts AS (
        SELECT m.season, m.group_id, count(*) AS match_goals_rows
        FROM read_parquet({p('match_goals')}) mg
        JOIN read_parquet({p('matches')}) m USING (match_id)
        GROUP BY m.season, m.group_id
    )
    SELECT
        st.season, st.group_id, st.scorers_total_goals,
        COALESCE(gc.match_goals_rows, 0) AS match_goals_rows,
        st.scorers_total_goals - COALESCE(gc.match_goals_rows, 0) AS diff
    FROM scorer_totals st
    LEFT JOIN goal_counts gc USING (season, group_id)
    WHERE st.scorers_total_goals != COALESCE(gc.match_goals_rows, 0)
    ORDER BY abs(st.scorers_total_goals - COALESCE(gc.match_goals_rows, 0)) DESC
    """
    df = con.execute(q).df()
    df = df[~df.apply(lambda r: (r["season"], r["group_id"]) in exclude, axis=1)]
    save(df, "check4_scorers_vs_match_goals")

    print(f"Groups where scorers.csv total goals != match_goals row count (excl. fully-missing groups): {len(df)}")
    print("\nNote: scorers.csv has no player_id, so this is a GROUP-LEVEL total comparison,")
    print("not a per-player one (per-player uses player_season_stats in check 6 instead).")
    print("\nOnly meaningful where acta_partido enrichment ran for that (season, category) -")
    print("groups with 0 match_goals_rows here likely just never had acta_partido enrichment,")
    print("not a genuine mismatch. Cross-check against coverage_manifest before treating as a gap.")
    print("\nBy season:")
    print(df.groupby("season").size())
    print("\nTop 10 examples:")
    print(df.head(10).to_string())
    return df


# ---------------------------------------------------------------------------
# Check 5: player_season_stats.matches_played vs count(match_lineups) per
# player_id/season, gated by coverage_manifest (acta_partido must have run
# for that player's category that season, else the gap is a known non-issue)
# ---------------------------------------------------------------------------
def check_player_appearances():
    section("CHECK 5 - player_season_stats.matches_played vs match_lineups appearance count")

    coverage = pd.read_csv("output/processed/rffm/coverage_manifest.csv")
    acta_ok = coverage[
        (coverage["stage"] == "acta_partido")
        & (coverage["status"].isin(["complete", "complete_with_failures"]))
    ][["season", "category_base"]].drop_duplicates()
    con.register("acta_ok", acta_ok)

    # NOTE: player_competition_participation can have >1 row per player/season
    # (dual registration, sometimes spanning two different category_base values
    # - see DATA_DICTIONARY.md). Joining pss straight to player_category would
    # fan a single player/season mismatch out into one row per category it
    # touched. Use a semi-join (EXISTS) so eligibility is "at least one of this
    # player's categories was acta-enriched", but the mismatch itself is still
    # counted exactly once per (player_id, season).
    q = f"""
    WITH lineup_counts AS (
        SELECT ml.player_id, m.season, count(*) AS lineup_appearances
        FROM read_parquet({p('match_lineups')}) ml
        JOIN read_parquet({p('matches')}) m USING (match_id)
        GROUP BY ml.player_id, m.season
    ),
    player_category AS (
        SELECT DISTINCT pcp.player_id, pcp.season, g.category
        FROM read_parquet({p('player_competition_participation')}) pcp
        JOIN read_parquet({p('groups')}) g
          ON g.season = pcp.season AND g.group_id = pcp.group_id
    ),
    eligible AS (
        SELECT DISTINCT pc.player_id, pc.season
        FROM player_category pc
        JOIN acta_ok ON acta_ok.season = pc.season AND acta_ok.category_base = pc.category
    )
    SELECT
        pss.player_id, pss.season,
        pss.matches_played AS season_stats_matches_played,
        COALESCE(lc.lineup_appearances, 0) AS lineup_appearances,
        pss.matches_played - COALESCE(lc.lineup_appearances, 0) AS diff,
        (SELECT string_agg(DISTINCT category, ',') FROM player_category pc2
         WHERE pc2.player_id = pss.player_id AND pc2.season = pss.season) AS categories
    FROM read_parquet({p('player_season_stats')}) pss
    JOIN eligible USING (player_id, season)
    LEFT JOIN lineup_counts lc USING (player_id, season)
    WHERE pss.matches_played != COALESCE(lc.lineup_appearances, 0)
    """
    df = con.execute(q).df()
    save(df, "check5_player_appearance_mismatch")

    print(f"Player/season rows with matches_played != match_lineups count (acta-covered categories only): {len(df)}")
    print(f"Distinct players affected: {df['player_id'].nunique()}")
    print("\nBy season:")
    print(df.groupby("season").size())
    print("\nDiff distribution:")
    print(df["diff"].describe())
    print("\nTop 10 examples (largest |diff|):")
    print(df.reindex(df["diff"].abs().sort_values(ascending=False).index).head(10).to_string())
    return df


# ---------------------------------------------------------------------------
# Check 6: player_season_stats cards vs match_cards counts (same gating)
# ---------------------------------------------------------------------------
def check_player_cards():
    section("CHECK 6 - player_season_stats cards vs match_cards counts")

    coverage = pd.read_csv("output/processed/rffm/coverage_manifest.csv")
    acta_ok = coverage[
        (coverage["stage"] == "acta_partido")
        & (coverage["status"].isin(["complete", "complete_with_failures"]))
    ][["season", "category_base"]].drop_duplicates()
    con.register("acta_ok2", acta_ok)

    q = f"""
    WITH card_counts AS (
        SELECT mc.player_id, m.season,
               sum(CASE WHEN mc.card_type_label = 'amarilla' THEN 1 ELSE 0 END) AS yellow_csv,
               sum(CASE WHEN mc.card_type_label = 'roja' THEN 1 ELSE 0 END) AS red_csv,
               sum(CASE WHEN mc.card_type_label = 'doble_amarilla' THEN 1 ELSE 0 END) AS second_yellow_csv
        FROM read_parquet({p('match_cards')}) mc
        JOIN read_parquet({p('matches')}) m USING (match_id)
        GROUP BY mc.player_id, m.season
    ),
    player_category AS (
        SELECT DISTINCT pcp.player_id, pcp.season, g.category
        FROM read_parquet({p('player_competition_participation')}) pcp
        JOIN read_parquet({p('groups')}) g
          ON g.season = pcp.season AND g.group_id = pcp.group_id
    ),
    eligible AS (
        SELECT DISTINCT pc.player_id, pc.season
        FROM player_category pc
        JOIN acta_ok2 ON acta_ok2.season = pc.season AND acta_ok2.category_base = pc.category
    )
    SELECT
        pss.player_id, pss.season,
        pss.yellow_cards, COALESCE(cc.yellow_csv, 0) AS yellow_csv,
        pss.red_cards, COALESCE(cc.red_csv, 0) AS red_csv,
        pss.second_yellow_cards, COALESCE(cc.second_yellow_csv, 0) AS second_yellow_csv,
        (SELECT string_agg(DISTINCT category, ',') FROM player_category pc2
         WHERE pc2.player_id = pss.player_id AND pc2.season = pss.season) AS categories
    FROM read_parquet({p('player_season_stats')}) pss
    JOIN eligible USING (player_id, season)
    LEFT JOIN card_counts cc USING (player_id, season)
    WHERE pss.yellow_cards != COALESCE(cc.yellow_csv, 0)
       OR pss.red_cards != COALESCE(cc.red_csv, 0)
       OR pss.second_yellow_cards != COALESCE(cc.second_yellow_csv, 0)
    """
    df = con.execute(q).df()
    save(df, "check6_player_cards_mismatch")

    print(f"Player/season rows with any card-count mismatch (acta-covered categories only): {len(df)}")
    print(f"Distinct players affected: {df['player_id'].nunique()}")
    print("\nBy season:")
    print(df.groupby("season").size())
    print("\nTop 10 examples:")
    print(df.head(10).to_string())
    return df


# ---------------------------------------------------------------------------
# Check 7: player_season_stats.goals_total vs sum(match_goals) per player/season
# (same gating; separate from check 4's group-level scorers.csv comparison)
# ---------------------------------------------------------------------------
def check_player_goals():
    section("CHECK 7 - player_season_stats.goals_total vs match_goals row count")

    coverage = pd.read_csv("output/processed/rffm/coverage_manifest.csv")
    acta_ok = coverage[
        (coverage["stage"] == "acta_partido")
        & (coverage["status"].isin(["complete", "complete_with_failures"]))
    ][["season", "category_base"]].drop_duplicates()
    con.register("acta_ok3", acta_ok)

    q = f"""
    WITH goal_counts AS (
        SELECT mg.player_id, m.season, count(*) AS goals_csv
        FROM read_parquet({p('match_goals')}) mg
        JOIN read_parquet({p('matches')}) m USING (match_id)
        GROUP BY mg.player_id, m.season
    ),
    player_category AS (
        SELECT DISTINCT pcp.player_id, pcp.season, g.category
        FROM read_parquet({p('player_competition_participation')}) pcp
        JOIN read_parquet({p('groups')}) g
          ON g.season = pcp.season AND g.group_id = pcp.group_id
    ),
    eligible AS (
        SELECT DISTINCT pc.player_id, pc.season
        FROM player_category pc
        JOIN acta_ok3 ON acta_ok3.season = pc.season AND acta_ok3.category_base = pc.category
    )
    SELECT
        pss.player_id, pss.season,
        pss.goals_total AS season_stats_goals, COALESCE(gc.goals_csv, 0) AS match_goals_csv,
        pss.goals_total - COALESCE(gc.goals_csv, 0) AS diff,
        (SELECT string_agg(DISTINCT category, ',') FROM player_category pc2
         WHERE pc2.player_id = pss.player_id AND pc2.season = pss.season) AS categories
    FROM read_parquet({p('player_season_stats')}) pss
    JOIN eligible USING (player_id, season)
    LEFT JOIN goal_counts gc USING (player_id, season)
    WHERE pss.goals_total != COALESCE(gc.goals_csv, 0)
    """
    df = con.execute(q).df()
    save(df, "check7_player_goals_mismatch")

    print(f"Player/season rows with goals_total != match_goals count (acta-covered categories only): {len(df)}")
    print(f"Distinct players affected: {df['player_id'].nunique()}")
    print("\nBy season:")
    print(df.groupby("season").size())
    print("\nDiff distribution:")
    print(df["diff"].describe())
    print("\nTop 10 examples (largest |diff|):")
    print(df.reindex(df["diff"].abs().sort_values(ascending=False).index).head(10).to_string())
    return df


if __name__ == "__main__":
    df1 = check_missing_groups()
    df2 = check_partial_match_counts(df1)
    df3 = check_goals_totals(df1)
    df4 = check_scorers_vs_match_goals(df1)
    df5 = check_player_appearances()
    df6 = check_player_cards()
    df7 = check_player_goals()

    section("SUMMARY")
    print(f"Check 1 (fully-missing groups):         {len(df1):>6} groups")
    print(f"Check 2 (team played-count mismatch):    {len(df2):>6} team/group rows")
    print(f"Check 3 (team goals_for/against mismatch): {len(df3):>6} team/group rows")
    print(f"Check 4 (scorers vs match_goals, group-level): {len(df4):>6} group rows")
    print(f"Check 5 (player appearances mismatch):   {len(df5):>6} player/season rows")
    print(f"Check 6 (player cards mismatch):         {len(df6):>6} player/season rows")
    print(f"Check 7 (player goals mismatch):         {len(df7):>6} player/season rows")
    print(f"\nDetailed CSVs written to {OUT_DIR}/")
