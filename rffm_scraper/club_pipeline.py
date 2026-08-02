"""Enrichment pipeline: /fichaequipo/<team_id> -> clubs.csv.

One representative team_id per unique club_name_raw is fetched, not every
team - codigo_club (and the correspondence-address fields) are confirmed
identical across every team of the same club by live sampling, so fetching
a second/third team of an already-covered club would just re-fetch the same
club data for no new information. Targets are restricted to teams playing
in scope_category this season (team_group_membership.csv joined to
groups.csv for the category), read from output the core crawl (main.py)
already produced - run that first.

Same resumability/progress/batched-flush/coverage-manifest design as
acta_pipeline.py/player_pipeline.py - see acta_pipeline.py's module
docstring for the full rationale (crawl-log-based "already done" as the
cross-environment resumability source of truth, batched atomic flush so a
killed run loses at most one partial batch, coverage_manifest.csv upserted
after every flush).
"""
from __future__ import annotations

import dataclasses
import logging
import time
from datetime import datetime, timezone

import pandas as pd

from rffm_scraper.club_parsers import parse_club
from rffm_scraper.club_quality_checks import run_club_quality_checks
from rffm_scraper.config import Settings
from rffm_scraper.fetchers import extract_next_data, fetch_fichaequipo
from rffm_scraper.http_client import RffmClient
from rffm_scraper.models import Club, CrawlLogEntry
from rffm_scraper.row_io import (
    Progress,
    already_done_ids,
    append_or_write_csv,
    atomic_write_text,
    upsert_coverage_manifest,
    validate_rows,
    write_csv,
)

logger = logging.getLogger("rffm_scraper.club_pipeline")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_target_teams(settings: Settings, scope_category: str) -> pd.DataFrame:
    processed = settings.processed_dir
    teams_df = pd.read_csv(processed / "teams.csv", dtype=str, keep_default_na=True)
    membership_df = pd.read_csv(processed / "team_group_membership.csv", dtype=str, keep_default_na=True)
    groups_df = pd.read_csv(processed / "groups.csv", dtype=str, keep_default_na=True)

    group_category = groups_df.set_index("group_id")["category"]
    in_scope_team_ids = set(
        membership_df.loc[membership_df["group_id"].map(group_category) == scope_category, "team_id"]
    )

    scoped = teams_df[teams_df["team_id"].isin(in_scope_team_ids)]
    representatives = scoped.drop_duplicates(subset="club_name_raw", keep="first")
    return representatives[["team_id", "club_name_raw"]].reset_index(drop=True)


def _raw_path(settings: Settings, category: str, season_label: str, team_id: str):
    return settings.raw_dir / category.lower() / season_label / "fichaequipo" / f"{team_id}.html"


def _progress_path(settings: Settings, season_label: str, scope_category: str):
    return settings.discovery_dir / f"clubs_progress_{season_label}_{scope_category.lower()}.json"


def _reread_table(processed, filename: str) -> pd.DataFrame:
    path = processed / filename
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"club_id": str, "representative_team_id": str})


def _flush_batch(processed, rows: list[dict], crawl_log_rows: list[dict]) -> None:
    if rows:
        df = pd.DataFrame(validate_rows(Club, rows, "club"))
        append_or_write_csv(df, processed / "clubs.csv")
        rows.clear()
    if crawl_log_rows:
        log_df = pd.DataFrame(validate_rows(CrawlLogEntry, crawl_log_rows, "clubs_crawl_log"))
        append_or_write_csv(log_df, processed / "clubs_crawl_log.csv")
        crawl_log_rows.clear()


def run_club_enrichment(settings: Settings, scope_category: str | None = None, force_refetch: bool | None = None) -> dict:
    if not settings.enrichment.fetch_fichaequipo:
        raise RuntimeError(
            "enrichment.fetch_fichaequipo is false in config - refusing to crawl "
            "/fichaequipo/ (robots.txt-disallowed) without an explicit opt-in."
        )

    cfg = settings.enrichment.clubs
    scope_category = scope_category or cfg.scope_category
    force_refetch = cfg.force_refetch if force_refetch is None else force_refetch
    season_label = settings.target.season_label

    club_settings = dataclasses.replace(
        settings,
        network=dataclasses.replace(settings.network, rate_limit_seconds=cfg.rate_limit_seconds),
    )
    client = RffmClient(club_settings)

    targets = _load_target_teams(settings, scope_category)
    target_team_ids: list[str] = targets["team_id"].tolist()

    processed = settings.processed_dir
    processed.mkdir(parents=True, exist_ok=True)

    matches_df = pd.read_csv(processed / "matches.csv", dtype=str, keep_default_na=True)
    season_id = matches_df.loc[matches_df["season"] == season_label, "season_id"].iloc[0]

    # Resumability source of truth: union of crawl-log successes and
    # representative_team_ids already present in clubs.csv - see
    # acta_pipeline.run_acta_enrichment for why both are needed.
    done_ids: set[str] = already_done_ids(processed / "clubs_crawl_log.csv", entity_type="team_ficha")
    clubs_path = processed / "clubs.csv"
    if clubs_path.exists():
        done_ids |= set(
            pd.read_csv(clubs_path, usecols=["representative_team_id"], dtype=str)["representative_team_id"].dropna()
        )
    already_done_this_scope = done_ids & set(target_team_ids)
    remaining = [tid for tid in target_team_ids if tid not in done_ids]

    logger.info(
        "clubs enrichment: %d targets total, %d already done, %d remaining (scope=%s)",
        len(target_team_ids), len(already_done_this_scope), len(remaining), scope_category,
    )

    progress = Progress(_progress_path(settings, season_label, scope_category), scope_category, len(target_team_ids))
    progress.completed = len(already_done_this_scope)
    progress.write()

    started_at = _now_iso()
    pending_rows: list[dict] = []
    pending_crawl_log_rows: list[dict] = []

    for i, team_id in enumerate(remaining, start=1):
        raw_path = _raw_path(settings, scope_category, season_label, team_id)
        source_url = f"{settings.site.base_url}{settings.site.pages.fichaequipo}/{team_id}"

        team_json = None
        cache_hit = False
        if raw_path.exists() and not force_refetch:
            cached_html = raw_path.read_text(encoding="utf-8")
            page_props = extract_next_data(cached_html)
            team_json = (page_props or {}).get("team")
            if team_json is not None:
                progress.skipped_cached += 1
                cache_hit = True
            else:
                logger.warning("Cached fichaequipo file unparseable, will refetch: %s", raw_path)

        if team_json is None:
            fetch_started = time.monotonic()
            result = fetch_fichaequipo(client, club_settings, team_id)
            if result.ok and result.raw_html:
                atomic_write_text(raw_path, result.raw_html)
                team_json = (result.page_props or {}).get("team")
                progress.record_fetch(time.monotonic() - fetch_started)
            pending_crawl_log_rows.append(dataclasses.asdict(client.crawl_log[-1]))
        elif cache_hit:
            pending_crawl_log_rows.append(dict(
                run_id=client.run_id, timestamp=_now_iso(), stage="clubs",
                entity_type="team_ficha", entity_id=team_id, source_url=source_url,
                http_status=None, success=True, retry_count=0,
                parser_type="html_next_data_cached", raw_saved_path=str(raw_path),
                message="served_from_raw_cache",
            ))

        progress.completed += 1
        progress.last_item_processed = team_id

        if team_json is None or not team_json.get("codigo_club"):
            progress.failed += 1
        else:
            done_ids.add(team_id)
            pending_rows.append(parse_club(team_json, representative_team_id=team_id, source_url=source_url))

        if progress.completed % cfg.progress_report_every == 0:
            progress.write()
            logger.info(
                "clubs progress: %d/%d (cached=%d fresh=%d failed=%d)",
                progress.completed, progress.total_targets, progress.skipped_cached,
                progress.freshly_fetched_ok, progress.failed,
            )

        if i % cfg.csv_flush_every == 0:
            _flush_batch(processed, pending_rows, pending_crawl_log_rows)
            progress.write()
            upsert_coverage_manifest(
                settings.processed_root, season=season_label, season_id=season_id,
                category_base=scope_category, stage="clubs", status="partial",
                targets_total=len(target_team_ids), targets_completed=progress.completed,
                targets_failed=progress.failed, started_at=started_at,
            )

    _flush_batch(processed, pending_rows, pending_crawl_log_rows)
    progress.write()

    missing = set(target_team_ids) - done_ids
    final_status = "complete" if not missing else "complete_with_failures"
    upsert_coverage_manifest(
        settings.processed_root, season=season_label, season_id=season_id,
        category_base=scope_category, stage="clubs", status=final_status,
        targets_total=len(target_team_ids), targets_completed=progress.completed,
        targets_failed=len(missing), started_at=started_at, completed_at=_now_iso(),
    )

    clubs_df = _reread_table(processed, "clubs.csv")
    quality_issues = run_club_quality_checks(clubs_df, target_team_ids)
    write_csv(pd.DataFrame(quality_issues), processed / "clubs_data_quality_report.csv")

    # `club_name_raw` is derived from team names and can be more granular than
    # RFFM's own club identity (for example, campus suffixes). `club_id` is the
    # documented primary key of clubs.csv, so publish one canonical row per ID
    # while preserving the pre-dedup collisions in the quality report above.
    if not clubs_df.empty and clubs_df["club_id"].duplicated().any():
        clubs_df = clubs_df.drop_duplicates(subset="club_id", keep="first").reset_index(drop=True)
        write_csv(clubs_df, processed / "clubs.csv")

    summary = dict(
        scope_category=scope_category,
        targets=len(target_team_ids),
        already_done_before_this_run=len(already_done_this_scope),
        processed_this_run=len(remaining),
        completed=progress.completed,
        freshly_fetched_ok=progress.freshly_fetched_ok,
        skipped_cached=progress.skipped_cached,
        failed=progress.failed,
        missing_after_this_run=len(missing),
        status=final_status,
        clubs=len(clubs_df),
        quality_issues=len(quality_issues),
    )
    logger.info("clubs enrichment summary: %s", summary)
    return summary
