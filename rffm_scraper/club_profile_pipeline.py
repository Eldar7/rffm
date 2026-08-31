"""Enrichment pipeline: /fichaclub/<club_id> -> clubs_extended.csv + club_teams.csv.

Separate from club_pipeline.py (fichaequipo, one representative team per
club, one row per club_id in clubs.csv) - this reads a different, richer
page keyed by the real club_id itself (not a team_id - passing a team_id
here returns club: null, confirmed live) and returns every team the club has
ever fielded, not just the one team club_pipeline.py happened to sample.

Targets are the UNION of club_id across every season's already-committed
output/processed/rffm/<season>/clubs.csv PLUS output/processed/rffm/
team_club_map.csv (cross-season, not season-scoped - a club identity isn't
a per-season concept any more than it's an age-bracket one, see
club_pipeline.py). team_club_map.csv (rffm_scraper/team_club_pipeline.py)
routinely knows club_ids clubs.csv never found, since it resolves every
team_id instead of one representative per club_name_raw group - see that
module's docstring. This project already has 10 seasons of clubs.csv
committed, so this pipeline never needs to run core/clubs itself - it just
reads whatever club_ids those already produced. Outputs
live at the processed root (output/processed/rffm/clubs_extended.csv etc.),
alongside coverage_manifest.csv, not inside any one season's directory - see
CLAUDE.md's "Why one file"/README's storage-layout rationale for why
cross-season tables live one level up.

Append-only, not upserted - this is the key difference from every other
enrichment pipeline in this codebase. A club's profile page is the site's
CURRENT state (delegacion, teams currently fielded, contact info) and can
genuinely drift over time (new/deactivated teams, name changes) - unlike
match results or a player's per-season stats, which are a fixed historical
record once written. So clubs_extended.csv/club_teams.csv never overwrite a
previous snapshot; every successful fetch appends a new row stamped with
that fetch's scraped_at. The "current" state of a club is whichever row has
the latest scraped_at - see DATA_DICTIONARY.md for the read-side recipe.
Full history (what changed, when) is just the table itself - nothing extra
to maintain.

This changes what force_refetch means here vs the other stages: elsewhere
it only bypasses the local raw-HTML cache (already-fetched targets are never
revisited regardless). Here, force_refetch=True means "take a fresh
snapshot of every target club_id now" (a deliberate refresh run) - it
bypasses the done_ids skip entirely, not just the raw-HTML cache. Default
(force_refetch=False) is a normal resumable backfill: only club_ids with no
prior successful fetch are targeted, safe to resume after an interruption
without re-fetching or duplicating anything.

A club: null response (stale/defunct club_id) is a valid, successful fetch
- HTTP 200, __NEXT_DATA__ parsed fine, the site just has nothing for that
id - not a crawl failure. See club_profile_quality_checks.py.

Cross-season and manually dispatched only (rffm-crawl.yml's club_profiles
stage) - deliberately NOT part of the crawl-all.yml self-chaining per-season
backfill plan, since this isn't a "run once per season until complete"
step the way acta_partido/fichajugador/clubs are.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from rffm_scraper.club_profile_parsers import parse_club_profile, parse_club_teams
from rffm_scraper.club_profile_quality_checks import run_club_profile_quality_checks
from rffm_scraper.config import Settings
from rffm_scraper.fetchers import extract_next_data, fetch_fichaclub
from rffm_scraper.http_client import RffmClient
from rffm_scraper.models import ClubProfile, ClubTeamRosterEntry, CrawlLogEntry
from rffm_scraper.row_io import (
    Progress,
    already_done_ids,
    append_or_write_csv,
    atomic_write_text,
    upsert_coverage_manifest,
    validate_rows,
    write_csv,
)

logger = logging.getLogger("rffm_scraper.club_profile_pipeline")

# Synthetic season/category_base key for coverage_manifest.csv - this stage
# is cross-season (see module docstring), so there's no real season_label to
# key it by. Mirrors how category_base="ALL" already denotes "not
# category-scoped" for core/clubs.
_MANIFEST_SEASON = "ALL"
_MANIFEST_CATEGORY = "ALL"
_STAGE = "club_profiles"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_target_club_ids(settings: Settings) -> list[str]:
    all_ids: set[str] = set()
    clubs_files = sorted(settings.processed_root.glob("*/clubs.csv"))
    for path in clubs_files:
        df = pd.read_csv(path, usecols=["club_id"], dtype=str, keep_default_na=True)
        all_ids.update(df["club_id"].dropna())
    # team_club_map.csv (rffm_scraper/team_club_pipeline.py) resolves every
    # team_id, not just one representative per club_name_raw group like
    # clubs.csv - so it routinely finds club_ids clubs.csv never did (a team
    # whose club_name_raw was never picked as a representative). Union it in
    # so those clubs get a /fichaclub/ profile too, not just a bare club_id.
    team_club_map_path = settings.processed_root / "team_club_map.csv"
    if team_club_map_path.exists():
        df = pd.read_csv(team_club_map_path, usecols=["club_id"], dtype=str, keep_default_na=True)
        all_ids.update(df["club_id"].dropna())
    if not all_ids:
        raise RuntimeError(
            "No output/processed/rffm/*/clubs.csv or team_club_map.csv found - run main.py + "
            "enrich_clubs.py (or enrich_team_clubs.py) for at least one season before club "
            "profile enrichment."
        )
    return sorted(all_ids)


def _raw_path(settings: Settings, club_id: str):
    return settings.raw_dir / "fichaclub" / f"{club_id}.html"


def _progress_path(settings: Settings):
    return settings.discovery_dir / "club_profiles_progress.json"


def _reread_table(processed_root, filename: str) -> pd.DataFrame:
    path = processed_root / filename
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"club_id": str, "team_id": str})


def _flush_batch(
    processed_root, profile_rows: list[dict], roster_rows: list[dict], crawl_log_rows: list[dict],
) -> None:
    if profile_rows:
        df = pd.DataFrame(validate_rows(ClubProfile, profile_rows, "club_profile"))
        append_or_write_csv(df, processed_root / "clubs_extended.csv")
        profile_rows.clear()
    if roster_rows:
        df = pd.DataFrame(validate_rows(ClubTeamRosterEntry, roster_rows, "club_team_roster"))
        append_or_write_csv(df, processed_root / "club_teams.csv")
        roster_rows.clear()
    if crawl_log_rows:
        log_df = pd.DataFrame(validate_rows(CrawlLogEntry, crawl_log_rows, "club_profiles_crawl_log"))
        append_or_write_csv(log_df, processed_root / "club_profiles_crawl_log.csv")
        crawl_log_rows.clear()


def _fetch_one_club_profile(
    club_id: str,
    settings: Settings,
    club_profile_settings: Settings,
    local: threading.local,
    run_id: str,
    force_refetch: bool,
) -> tuple[str, dict, dict | None, list[dict], float]:
    """Fetch and parse one club profile. Runs in a worker thread.

    Returns (club_id, log_entry_dict, profile_row_or_None, roster_rows, fetch_seconds).
    profile_row is None both on a real fetch failure (log_entry["success"] is
    False) and on a valid club: null response (log_entry["success"] is True)
    - callers must check log_entry["success"] to tell the two apart.
    """
    if not hasattr(local, "client"):
        local.client = RffmClient(club_profile_settings, run_id=run_id)
    client = local.client

    raw_path = _raw_path(settings, club_id)
    source_url = f"{settings.site.base_url}{settings.site.pages.fichaclub}/{club_id}"

    club_json = None
    cache_hit = False
    fetch_seconds = 0.0

    if raw_path.exists() and not force_refetch:
        cached_html = raw_path.read_text(encoding="utf-8")
        page_props = extract_next_data(cached_html)
        club_json = (page_props or {}).get("club")
        if club_json is not None:
            cache_hit = True
        else:
            logger.debug("Cached fichaclub file has no usable club object, will refetch: %s", raw_path)

    if club_json is None:
        fetch_started = time.monotonic()
        result = fetch_fichaclub(client, club_profile_settings, club_id)
        if result.ok and result.raw_html:
            atomic_write_text(raw_path, result.raw_html)
            club_json = (result.page_props or {}).get("club")
            fetch_seconds = time.monotonic() - fetch_started
        log_entry = dataclasses.asdict(client.crawl_log[-1])
    elif cache_hit:
        log_entry = dict(
            run_id=run_id, timestamp=_now_iso(), stage=_STAGE,
            entity_type="club_ficha", entity_id=club_id, source_url=source_url,
            http_status=None, success=True, retry_count=0,
            parser_type="html_next_data_cached", raw_saved_path=str(raw_path),
            message="served_from_raw_cache",
        )

    scraped_at = _now_iso()
    profile_row = None
    roster_rows: list[dict] = []
    if club_json is not None:
        profile_row = parse_club_profile(club_json, source_url=source_url, scraped_at=scraped_at)
        roster_rows = parse_club_teams(club_json, club_id=club_id, source_url=source_url, scraped_at=scraped_at)

    return club_id, log_entry, profile_row, roster_rows, fetch_seconds


def run_club_profile_enrichment(
    settings: Settings,
    force_refetch: bool | None = None,
    workers: int | None = None,
) -> dict:
    if not settings.enrichment.fetch_fichaclub:
        raise RuntimeError(
            "enrichment.fetch_fichaclub is false in config - refusing to crawl "
            "/fichaclub/ without an explicit opt-in (not robots.txt-disallowed, but "
            "gated for consistency with the other enrichment stages)."
        )

    cfg = settings.enrichment.club_profiles
    force_refetch = cfg.force_refetch if force_refetch is None else force_refetch
    workers = cfg.workers if workers is None else workers

    club_profile_settings = dataclasses.replace(
        settings,
        network=dataclasses.replace(settings.network, rate_limit_seconds=cfg.rate_limit_seconds),
    )
    client = RffmClient(club_profile_settings)

    target_club_ids = _load_target_club_ids(settings)
    processed_root = settings.processed_root
    processed_root.mkdir(parents=True, exist_ok=True)

    # Resumability source of truth (default/backfill mode only - see module
    # docstring): union of crawl-log successes and club_ids already present
    # in clubs_extended.csv, same union rationale as every other pipeline in
    # this codebase (acta_pipeline.py/club_pipeline.py) - crawl-log alone
    # misses a legitimate club: null outcome only if reread from an old log
    # predating this design; table-presence alone misses club: null
    # successes entirely (no row is ever written for those). Ignored
    # entirely when force_refetch=True - see module docstring.
    done_ids: set[str] = already_done_ids(processed_root / "club_profiles_crawl_log.csv", entity_type="club_ficha")
    clubs_extended_path = processed_root / "clubs_extended.csv"
    if clubs_extended_path.exists():
        done_ids |= set(pd.read_csv(clubs_extended_path, usecols=["club_id"], dtype=str)["club_id"].dropna())

    if force_refetch:
        already_done = set()
        remaining = target_club_ids
    else:
        already_done = done_ids & set(target_club_ids)
        remaining = [cid for cid in target_club_ids if cid not in done_ids]

    logger.info(
        "club_profiles enrichment: %d targets total, %d already done, %d remaining "
        "(force_refetch=%s workers=%d)",
        len(target_club_ids), len(already_done), len(remaining), force_refetch, workers,
    )

    progress = Progress(_progress_path(settings), "club_profiles", len(target_club_ids))
    progress.completed = len(already_done)
    progress.write()

    started_at = _now_iso()
    pending_profile_rows: list[dict] = []
    pending_roster_rows: list[dict] = []
    pending_crawl_log_rows: list[dict] = []
    null_club_ids: list[str] = []
    items_since_flush = 0

    local = threading.local()
    if workers == 1:
        local.client = client

    def _process_result(
        club_id: str, log_entry: dict, profile_row: dict | None, roster_rows: list[dict], fetch_seconds: float,
    ) -> None:
        nonlocal items_since_flush
        pending_crawl_log_rows.append(log_entry)
        progress.completed += 1
        progress.last_item_processed = club_id
        if not log_entry["success"]:
            progress.failed += 1
        else:
            if fetch_seconds > 0:
                progress.record_fetch(fetch_seconds)
            else:
                progress.skipped_cached += 1
            done_ids.add(club_id)
            if profile_row is None:
                null_club_ids.append(club_id)
            else:
                pending_profile_rows.append(profile_row)
                pending_roster_rows.extend(roster_rows)
        items_since_flush += 1
        if progress.completed % cfg.progress_report_every == 0:
            progress.write()
            logger.info(
                "club_profiles progress: %d/%d (cached=%d fresh=%d failed=%d null=%d)",
                progress.completed, progress.total_targets, progress.skipped_cached,
                progress.freshly_fetched_ok, progress.failed, len(null_club_ids),
            )
        if items_since_flush >= cfg.csv_flush_every:
            _flush_batch(processed_root, pending_profile_rows, pending_roster_rows, pending_crawl_log_rows)
            progress.write()
            upsert_coverage_manifest(
                processed_root, season=_MANIFEST_SEASON, season_id="", category_base=_MANIFEST_CATEGORY,
                stage=_STAGE, status="partial", targets_total=len(target_club_ids),
                targets_completed=progress.completed, targets_failed=progress.failed, started_at=started_at,
            )
            items_since_flush = 0

    if workers == 1:
        for club_id in remaining:
            result = _fetch_one_club_profile(
                club_id, settings, club_profile_settings, local, client.run_id, force_refetch,
            )
            _process_result(*result)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rffm-club-profile") as executor:
            futures = {
                executor.submit(
                    _fetch_one_club_profile, cid, settings, club_profile_settings,
                    local, client.run_id, force_refetch,
                ): cid
                for cid in remaining
            }
            for future in as_completed(futures):
                _process_result(*future.result())

    _flush_batch(processed_root, pending_profile_rows, pending_roster_rows, pending_crawl_log_rows)
    progress.write()

    missing = set(target_club_ids) - done_ids
    final_status = "complete" if not missing else "complete_with_failures"
    upsert_coverage_manifest(
        processed_root, season=_MANIFEST_SEASON, season_id="", category_base=_MANIFEST_CATEGORY,
        stage=_STAGE, status=final_status, targets_total=len(target_club_ids),
        targets_completed=progress.completed, targets_failed=len(missing),
        started_at=started_at, completed_at=_now_iso(),
    )

    clubs_extended_df = _reread_table(processed_root, "clubs_extended.csv")
    club_teams_df = _reread_table(processed_root, "club_teams.csv")

    quality_issues = run_club_profile_quality_checks(target_club_ids, done_ids, null_club_ids)
    write_csv(pd.DataFrame(quality_issues), processed_root / "club_profiles_data_quality_report.csv")

    summary = dict(
        targets=len(target_club_ids),
        already_done_before_this_run=len(already_done),
        processed_this_run=len(remaining),
        completed=progress.completed,
        freshly_fetched_ok=progress.freshly_fetched_ok,
        skipped_cached=progress.skipped_cached,
        failed=progress.failed,
        null_club_responses=len(null_club_ids),
        missing_after_this_run=len(missing),
        status=final_status,
        clubs_extended_rows=len(clubs_extended_df),
        club_teams_rows=len(club_teams_df),
        quality_issues=len(quality_issues),
    )
    logger.info("club_profiles enrichment summary: %s", summary)
    return summary
