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

club_profiles:
  Different from every stage above: a club_id that returns club: null is a
  *valid* successful outcome (a stale/defunct club_id), not a failure - see
  club_profile_pipeline.py's module docstring - so it never shows up via the
  complete_with_failures manifest gate the other stages use (this stage's
  manifest row is "complete" with targets_failed=0 whenever every HTTP
  fetch succeeded, regardless of how many came back null). Retryable here
  means "was null before, but the site now has data for it" - genuinely
  useful since club identities can apparently get reactivated/reassigned.
  Candidates = club_profile_not_found rows in
  club_profiles_data_quality_report.csv (info severity, not a warning).
  Fix: delete the success=True club_profiles_crawl_log.csv row for that
  club_id (cross-season - one shared log, not per-season) so the pipeline
  re-fetches it on the next enrich_club_profiles.py run; a revived club_id
  simply gets appended as a fresh clubs_extended.csv/club_teams.csv snapshot
  the normal way, nothing needs to be cleared there.

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


def is_club_profile_live(url: str) -> bool:
    pp = _fetch_page_props(url)
    return pp is not None and bool(pp.get("club"))


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


def load_club_profiles_null() -> pd.DataFrame:
    """club_profiles: club_ids that came back club: null on their last
    fetch - info-severity club_profile_not_found rows in the quality
    report, not the manifest's complete_with_failures gate (see module
    docstring - null is a valid outcome there, not a failure)."""
    qr_path = PROCESSED / "club_profiles_data_quality_report.csv"
    if not qr_path.exists():
        return pd.DataFrame()
    qr = pd.read_csv(qr_path, dtype=str)
    nulls = qr[qr["check_name"] == "club_profile_not_found"][["entity_id"]].copy()
    if nulls.empty:
        return nulls
    nulls["source_url"] = BASE_URL + "/fichaclub/" + nulls["entity_id"]
    return nulls


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


def clear_club_profiles_done(entity_ids: set[str]) -> int:
    """Remove success=True club_profiles_crawl_log.csv rows for these
    club_ids so the pipeline re-fetches them. Cross-season - one shared
    top-level log, not per-season like clear_clubs_done above. Nothing to
    remove from clubs_extended.csv/club_teams.csv - a null result never
    wrote a row there in the first place (append-only, see
    club_profile_pipeline.py)."""
    log_path = PROCESSED / "club_profiles_crawl_log.csv"
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

def _check_candidates(candidates: pd.DataFrame, checker, workers: int) -> tuple[list[str], list[str]]:
    live_ids: list[str] = []
    dead_ids: list[str] = []

    def _check(r: pd.Series) -> tuple[str, str, bool]:
        return r["entity_id"], r["source_url"], checker(r["source_url"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_check, r): r for _, r in candidates.iterrows()}
        for i, fut in enumerate(as_completed(futures), 1):
            entity_id, url, live = fut.result()
            print(f"    [{i}/{len(candidates)}] {'LIVE' if live else 'dead'}  {entity_id}  {url}")
            (live_ids if live else dead_ids).append(entity_id)

    return live_ids, dead_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--stages", nargs="+", help="Only process these stages (e.g. acta_partido fichajugador club_profiles)")
    args = parser.parse_args()

    mf = pd.read_csv(MANIFEST, dtype=str)
    cwf = mf[mf["status"] == "complete_with_failures"]

    retryable: list[dict] = []

    if cwf.empty:
        print("No complete_with_failures entries in manifest.")
    else:
        print(f"Found {len(cwf)} complete_with_failures entries:\n")

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

        live_ids, dead_ids = _check_candidates(failures, checker, args.workers)
        print(f"  -> retryable: {len(live_ids)}  dead: {len(dead_ids)}")

        if live_ids:
            retryable.append({
                "season": season, "stage": stage, "category": category,
                "entity_ids": set(live_ids), "mode": mode,
            })

    # club_profiles: not gated by complete_with_failures (null is a valid
    # outcome there, not a failure - see module docstring) - always checked
    # unless explicitly excluded via --stages.
    if not args.stages or "club_profiles" in args.stages:
        nulls = load_club_profiles_null()
        if nulls.empty:
            print("\n[cross-season] club_profiles — no club_profile_not_found entries to check.")
        else:
            print(
                f"\n[cross-season] club_profiles — {len(nulls)} null club_ids to check "
                f"for revival ({args.workers} workers)...", flush=True,
            )
            live_ids, dead_ids = _check_candidates(nulls, is_club_profile_live, args.workers)
            print(f"  -> retryable: {len(live_ids)}  dead: {len(dead_ids)}")
            if live_ids:
                retryable.append({
                    "season": "ALL", "stage": "club_profiles", "category": "ALL",
                    "entity_ids": set(live_ids), "mode": "null-revival",
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
        elif r["stage"] == "club_profiles":
            removed = clear_club_profiles_done(r["entity_ids"])
        else:
            removed = clear_log_failures(r["season"], r["stage"], r["entity_ids"])
        clear_manifest_status(r["season"], r["stage"], r["category"])
        print(f"  Cleared {removed} log rows, manifest -> partial  [{r['season']} {r['stage']} {r['category']}]")

    print(
        "\nDone. club_profiles revivals will re-fetch on the next "
        "enrich_club_profiles.py run (adds a fresh snapshot row, doesn't "
        "touch any other club_id's history). Commit the updated CSVs and "
        "trigger the orchestrator/dispatch as appropriate."
    )


if __name__ == "__main__":
    main()
