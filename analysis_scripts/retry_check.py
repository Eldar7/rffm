"""Find crawl failures that are retryable and optionally clear them so the
next orchestrator run re-fetches.

Two failure modes handled differently:

acta_partido / fichajugador:
  Failures are rows with success=False in the stage-specific crawl log.
  Retryable = the URL now returns a page with a usable content object.
  Fix: delete those failed rows from the log; pipeline will re-attempt them.

clubs:
  Failures are team_ids that were attempted but produced no row in clubs.csv
  (team_json existed but had no codigo_club, or fetch failed silently).
  There are NO failed rows in clubs_crawl_log — successful fetches write
  success=True; teams that returned no club data write nothing.
  Retryable = the URL now returns pageProps.team.codigo_club.
  Fix: delete the success=True log row for that team_id so the pipeline
  re-fetches (it won't touch done_ids anymore) and also drops clubs.csv row
  if one exists without a real club_id, then resets manifest to partial.

Usage:
    python analysis_scripts/retry_check.py          # show only
    python analysis_scripts/retry_check.py --fix    # prompt then clear
"""
from __future__ import annotations

import argparse
import urllib.request
import json
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

PROCESSED = Path("output/processed/rffm")
MANIFEST = PROCESSED / "coverage_manifest.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

BASE_URL = "https://www.rffm.es"


# ---------------------------------------------------------------------------
# URL checkers — return True if the page now has retryable data
# ---------------------------------------------------------------------------

def _fetch_page_props(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(1))
        return data.get("props", {}).get("pageProps") or None
    except Exception:
        return None


def is_acta_live(url: str) -> bool:
    pp = _fetch_page_props(url)
    return pp is not None and bool(pp.get("game"))


def is_ficha_live(url: str) -> bool:
    pp = _fetch_page_props(url)
    return pp is not None and bool(pp.get("player"))


def is_club_live(url: str) -> bool:
    pp = _fetch_page_props(url)
    return pp is not None and bool((pp.get("team") or {}).get("codigo_club"))


STAGE_CHECKER = {
    "acta_partido": is_acta_live,
    "fichajugador": is_ficha_live,
    "clubs":        is_club_live,
}


# ---------------------------------------------------------------------------
# Loading failures
# ---------------------------------------------------------------------------

STAGE_LOG = {
    "acta_partido": ("acta_crawl_log.csv",        "match_acta"),
    "fichajugador": ("fichajugador_crawl_log.csv", "player_ficha"),
}


def load_log_failures(season: str, stage: str) -> pd.DataFrame:
    """acta/ficha: find success=False rows in the stage crawl log."""
    log_name, entity_type = STAGE_LOG[stage]
    log_path = PROCESSED / season / log_name
    if not log_path.exists():
        return pd.DataFrame()
    log = pd.read_csv(log_path, dtype=str)
    return log[
        (log["success"].str.lower() == "false") &
        (log["entity_type"] == entity_type)
    ].copy()


def load_clubs_missing(season: str) -> pd.DataFrame:
    """clubs: find team_ids that were attempted but have no clubs.csv row.

    target_team_ids = one representative team_id per club_name_raw (same logic
    as club_pipeline._load_target_teams).  done_ids = union of crawl_log
    success=True and clubs.csv representative_team_id.  missing = target - done.
    """
    teams_path = PROCESSED / season / "teams.csv"
    if not teams_path.exists():
        return pd.DataFrame()
    teams = pd.read_csv(teams_path, dtype=str)
    # replicate _load_target_teams
    targets = teams.drop_duplicates(subset="club_name_raw", keep="first")[["team_id", "club_name_raw"]].copy()

    log_path = PROCESSED / season / "clubs_crawl_log.csv"
    done_ids: set[str] = set()
    if log_path.exists():
        log = pd.read_csv(log_path, dtype=str)
        done_ids |= set(log[log["success"].str.lower() == "true"]["entity_id"].dropna())
    clubs_path = PROCESSED / season / "clubs.csv"
    if clubs_path.exists():
        done_ids |= set(pd.read_csv(clubs_path, dtype=str)["representative_team_id"].dropna())

    missing = targets[~targets["team_id"].isin(done_ids)].copy()
    missing["source_url"] = BASE_URL + "/fichaequipo/" + missing["team_id"]
    missing = missing.rename(columns={"team_id": "entity_id"})
    return missing


# ---------------------------------------------------------------------------
# Clearing / fixing
# ---------------------------------------------------------------------------

def clear_log_failures(season: str, stage: str, entity_ids: set[str]) -> int:
    log_name, _ = STAGE_LOG[stage]
    log_path = PROCESSED / season / log_name
    log = pd.read_csv(log_path, dtype=str)
    before = len(log)
    log = log[~(
        (log["success"].str.lower() == "false") &
        (log["entity_id"].isin(entity_ids))
    )]
    log.to_csv(log_path, index=False)
    return before - len(log)


def clear_clubs_done(season: str, entity_ids: set[str]) -> int:
    """Remove success=True log entries for these team_ids so the pipeline
    re-fetches them on the next run."""
    log_path = PROCESSED / season / "clubs_crawl_log.csv"
    if not log_path.exists():
        return 0
    log = pd.read_csv(log_path, dtype=str)
    before = len(log)
    log = log[~(
        (log["success"].str.lower() == "true") &
        (log["entity_id"].isin(entity_ids))
    )]
    log.to_csv(log_path, index=False)
    return before - len(log)


def clear_manifest_status(season: str, stage: str, category: str) -> None:
    mf = pd.read_csv(MANIFEST, dtype=str)
    cat_key = category if category and category != "ALL" else "ALL"
    mask = (mf["season"] == season) & (mf["stage"] == stage) & (mf["category_base"] == cat_key)
    mf.loc[mask, "status"] = "partial"
    mf.loc[mask, "targets_failed"] = "0"
    mf.to_csv(MANIFEST, index=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--stages", nargs="+", help="Only process these stages (e.g. acta_partido fichajugador)")
    args = parser.parse_args()

    mf = pd.read_csv(MANIFEST, dtype=str)
    cwf = mf[mf["status"] == "complete_with_failures"]

    if cwf.empty:
        print("No complete_with_failures entries in manifest.")
        return

    print(f"Found {len(cwf)} complete_with_failures entries:\n")

    retryable: list[dict] = []

    for _, row in cwf.iterrows():
        season = row["season"]
        stage = row["stage"]
        category = row.get("category_base", "ALL") or "ALL"

        if stage not in STAGE_CHECKER:
            print(f"  [{season} {stage} {category}] — unknown stage, skipping")
            continue
        if args.stages and stage not in args.stages:
            continue

        checker = STAGE_CHECKER[stage]

        if stage == "clubs":
            failures = load_clubs_missing(season)
            mode = "clubs-missing"
        else:
            failures = load_log_failures(season, stage)
            mode = "log-failures"

        if failures.empty:
            print(f"  [{season} {stage} {category}] — {row['targets_failed']} failed per manifest but nothing to check ({mode})")
            continue

        print(f"\n[{season}] {stage} / {category}  — {len(failures)} to check ({mode}, {args.workers} workers)...", flush=True)

        live_ids: list[str] = []
        dead_ids: list[str] = []

        def _check(r: pd.Series) -> tuple[str, str, bool]:
            return r["entity_id"], r["source_url"], checker(r["source_url"])

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_check, r): r for _, r in failures.iterrows()}
            for i, fut in enumerate(as_completed(futures), 1):
                entity_id, url, live = fut.result()
                print(f"    [{i}/{len(failures)}] {'LIVE' if live else 'dead'}  {entity_id}  {url}")
                (live_ids if live else dead_ids).append(entity_id)

        print(f"  -> retryable: {len(live_ids)}  dead: {len(dead_ids)}")

        if live_ids:
            retryable.append({
                "season": season, "stage": stage, "category": category,
                "entity_ids": set(live_ids), "mode": mode,
            })

    if not retryable:
        print("\nNothing retryable found.")
        return

    print(f"\n{'='*60}")
    print(f"Summary: {sum(len(r['entity_ids']) for r in retryable)} retryable across {len(retryable)} stage(s):")
    for r in retryable:
        print(f"  {r['season']} {r['stage']} / {r['category']}: {len(r['entity_ids'])} IDs")

    if not args.fix:
        print("\nRun with --fix to clear these entries and reset manifest to 'partial'.")
        return

    print("\nThis will reset the affected stages to 'partial' so the orchestrator re-fetches them.")
    answer = input("Proceed? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    for r in retryable:
        if r["stage"] == "clubs":
            removed = clear_clubs_done(r["season"], r["entity_ids"])
        else:
            removed = clear_log_failures(r["season"], r["stage"], r["entity_ids"])
        clear_manifest_status(r["season"], r["stage"], r["category"])
        print(f"  Cleared {removed} log rows, manifest -> partial  [{r['season']} {r['stage']} {r['category']}]")

    print("\nDone. Commit the updated CSVs and trigger the orchestrator.")


if __name__ == "__main__":
    main()
