"""Live-verify every group flagged by audit_aggregates_vs_matches.py's
checks 1 and 2 (standings/scorers present, matches.csv missing or short)
against the current RFFM site, to answer one question per group: would
re-crawling this group's calendario actually add anything?

Uses the project's own unmodified fetch_calendario()/parse_matches() - the
same functions main.py's core crawl uses - so this is a read-only spot
check of the live site, not a re-implementation. Respects the project's
configured rate limit (one RffmClient, sequential requests).

Prerequisite: run analysis_scripts/audit_aggregates_vs_matches.py first,
so analysis_scripts/audit_output/check1_groups_missing_matches.csv and
check2_team_played_mismatch.csv exist.

Writes analysis_scripts/audit_output/recrawl_live_verification.csv with one
row per candidate group: our stored counts vs. the live counts just
fetched. See DATA_FINDINGS.md's "Systematic audit" entry for the result of
the last run (all 25 check-1 groups benefit, all 759 check-2 groups don't).

Run: python analysis_scripts/live_verify_recrawl_candidates.py
"""

import os
import sys
import time

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rffm_scraper.config import load_settings
from rffm_scraper.fetchers import fetch_calendario
from rffm_scraper.http_client import RffmClient
from rffm_scraper.parsers import GroupContext, parse_matches

PARQUET = "output/processed/rffm_parquet"
AUDIT_OUT = "analysis_scripts/audit_output"
OUT_PATH = os.path.join(AUDIT_OUT, "recrawl_live_verification.csv")


def build_candidate_list():
    con = duckdb.connect()
    check1 = pd.read_csv(os.path.join(AUDIT_OUT, "check1_groups_missing_matches.csv"))
    check2 = pd.read_csv(os.path.join(AUDIT_OUT, "check2_team_played_mismatch.csv"))
    candidates = pd.concat(
        [check1[["season", "group_id"]], check2[["season", "group_id"]]], ignore_index=True
    ).drop_duplicates()
    con.register("cand", candidates)
    q = f"""
    SELECT c.season, c.group_id, g.season_id, g.competition_id, comp.game_type_id,
           count(m.match_id) AS our_rows,
           sum(CASE WHEN m.is_finished THEN 1 ELSE 0 END) AS our_finished,
           max(TRY_CAST(m.matchday AS INT)) AS our_max_matchday
    FROM cand c
    JOIN read_parquet('{PARQUET}/groups/*.parquet') g
      ON g.season = c.season AND g.group_id = c.group_id
    JOIN read_parquet('{PARQUET}/competitions/*.parquet') comp
      ON comp.season = g.season AND comp.competition_id = g.competition_id
    LEFT JOIN read_parquet('{PARQUET}/matches/*.parquet') m
      ON m.season = c.season AND m.group_id = c.group_id
    GROUP BY c.season, c.group_id, g.season_id, g.competition_id, comp.game_type_id
    ORDER BY c.season, c.group_id
    """
    return con.execute(q).df()


def main():
    candidates = build_candidate_list()
    settings = load_settings("config.yaml")
    client = RffmClient(settings)

    rows = []
    start = time.time()
    for i, row in candidates.iterrows():
        season = row["season"]
        season_id = str(int(row["season_id"]))
        group_id = str(int(row["group_id"]))
        competition_id = str(int(row["competition_id"]))
        game_type_id = str(int(row["game_type_id"]))

        ctx = GroupContext(
            season=season, season_id=season_id, category="", competition="",
            competition_id=competition_id, group="", group_id=group_id,
            game_type="", game_type_id=game_type_id, phase_label="",
        )
        result = {
            "season": season, "group_id": int(group_id),
            "our_rows": row["our_rows"], "our_finished": row["our_finished"],
            "our_max_matchday": row["our_max_matchday"],
            "live_rows": None, "live_finished": None, "live_max_matchday": None,
            "ok": False, "error": "",
        }
        try:
            res = fetch_calendario(
                client, settings, season_id=season_id, competicion=competition_id,
                grupo=group_id, game_type_id=game_type_id, entity_id=group_id,
            )
            calendar_json = (res.page_props or {}).get("calendar") if res.ok else None
            live_rows = parse_matches(calendar_json, ctx, res.url) if calendar_json else []
            finished = [r for r in live_rows if r.get("is_finished")]
            result.update({
                "live_rows": len(live_rows),
                "live_finished": len(finished),
                "live_max_matchday": max((r["matchday"] for r in live_rows), default=None),
                "ok": bool(res.ok),
            })
        except Exception as e:
            result["error"] = repr(e)

        rows.append(result)
        if (i + 1) % 100 == 0:
            print(f"[{i + 1}/{len(candidates)}] elapsed={time.time() - start:.0f}s")

    out = pd.DataFrame(rows)
    out["benefit"] = out["live_finished"].fillna(0) > out["our_finished"].fillna(0)
    os.makedirs(AUDIT_OUT, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)

    print(f"\nDone in {time.time() - start:.0f}s. {len(out)} groups checked, "
          f"{out['benefit'].sum()} would benefit from re-crawling.")
    print(f"Written to {OUT_PATH}")


if __name__ == "__main__":
    main()
