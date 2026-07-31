"""Enrichment pipeline: /acta-partido/<match_id> -> lineups/goals/cards/staff/officials.

Separate from pipeline.py on purpose - this stage is optional (robots.txt
disallows the path; only runs when explicitly opted into), can cover tens of
thousands of matches (order-of-magnitude more requests than the core crawl),
and must be independently resumable across a run that may be interrupted.

Resumability: raw acta HTML is cached at a deterministic per-match path
(output/raw/rffm/{category}/{season}/acta/{match_id}.html), written
atomically (row_io.atomic_write_text) so a process killed mid-write never
leaves a half-written file that a naive "does this path exist" check would
mistake for a complete, cached page. On rerun, an existing cached file is
parsed directly (no network call) unless force_refetch=True.

Progress: a small JSON checkpoint is written atomically every
`progress_report_every` matches to
output/raw/rffm/discovery/acta_progress_<scope>.json, so a separate read (by
an operator or an agent) can report "X done, Y left, rate, ETA" without
touching the running process or tailing a growing log.

acta_crawl_log.csv / acta_data_quality_report.csv are written as their OWN
files, not appended into the core pipeline's crawl_log.csv/
data_quality_report.csv - those are fully rebuilt from scratch on every
main.py run, so appending here would just get silently wiped by the next
unrelated core rerun.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from rffm_scraper.acta_parsers import parse_acta_partido
from rffm_scraper.acta_quality_checks import run_acta_quality_checks
from rffm_scraper.config import Settings
from rffm_scraper.fetchers import extract_next_data, fetch_acta_partido
from rffm_scraper.http_client import RffmClient
from rffm_scraper.models import (
    CrawlLogEntry,
    MatchCardEvent,
    MatchGoalEvent,
    MatchLineupEntry,
    MatchOfficial,
    MatchStaff,
)
from rffm_scraper.row_io import atomic_write_text, validate_rows, write_csv

logger = logging.getLogger("rffm_scraper.acta_pipeline")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_targets(settings: Settings, scope_category: str) -> pd.DataFrame:
    """Load match-report fetch targets from matches.csv.

    dtype=str is critical here: without it, pandas infers id columns
    (match_id, home_team_id, ...) as float64 because unscheduled rows leave
    match_id blank, forcing the whole column to float - silently turning
    "5334831" into "5334831.0" everywhere downstream (URLs, cache paths,
    joins). Booleans are written by pandas as the literal strings
    "True"/"False" and are coerced back explicitly below.
    """
    path = settings.processed_dir / "matches.csv"
    df = pd.read_csv(path, dtype=str, keep_default_na=True)
    df["is_finished"] = df["is_finished"] == "True"

    cfg = settings.enrichment.acta_partido
    mask = (df["category"] == scope_category) & df["match_id"].notna()
    if cfg.skip_unplayed:
        mask &= df["is_finished"]
    if cfg.skip_byes:
        mask &= df["home_team_id"].notna() & df["away_team_id"].notna()
    return df[mask].reset_index(drop=True)


def _raw_path(settings: Settings, category: str, season_label: str, match_id: str):
    return settings.raw_dir / category.lower() / season_label / "acta" / f"{match_id}.html"


def _progress_path(settings: Settings, scope_category: str):
    return settings.discovery_dir / f"acta_progress_{scope_category.lower()}.json"


class _Progress:
    def __init__(self, settings: Settings, scope_category: str, total_targets: int):
        self.settings = settings
        self.scope_category = scope_category
        self.total_targets = total_targets
        self.completed = 0
        self.freshly_fetched_ok = 0
        self.skipped_cached = 0
        self.failed = 0
        self.total_fetch_seconds = 0.0
        self.started_at = _now_iso()
        self.last_match_id_processed: str | None = None

    def record_fetch(self, seconds: float) -> None:
        self.freshly_fetched_ok += 1
        self.total_fetch_seconds += seconds

    def to_dict(self) -> dict:
        avg = self.total_fetch_seconds / self.freshly_fetched_ok if self.freshly_fetched_ok else None
        remaining = self.total_targets - self.completed
        eta_seconds = avg * remaining if avg is not None else None
        eta_at = (
            (datetime.now(timezone.utc) + timedelta(seconds=eta_seconds)).isoformat()
            if eta_seconds is not None
            else None
        )
        return dict(
            scope_category=self.scope_category,
            started_at=self.started_at,
            last_updated_at=_now_iso(),
            total_targets=self.total_targets,
            completed=self.completed,
            freshly_fetched_ok=self.freshly_fetched_ok,
            skipped_cached=self.skipped_cached,
            failed=self.failed,
            remaining=remaining,
            avg_seconds_per_fresh_request=avg,
            estimated_seconds_remaining=eta_seconds,
            estimated_completion_at=eta_at,
            last_match_id_processed=self.last_match_id_processed,
        )

    def write(self) -> None:
        path = _progress_path(self.settings, self.scope_category)
        atomic_write_text(path, json.dumps(self.to_dict(), indent=2))


def run_acta_enrichment(settings: Settings, scope_category: str | None = None, force_refetch: bool | None = None) -> dict:
    if not settings.enrichment.fetch_acta_partido:
        raise RuntimeError(
            "enrichment.fetch_acta_partido is false in config - refusing to crawl "
            "/acta-partido/ (robots.txt-disallowed) without an explicit opt-in."
        )

    cfg = settings.enrichment.acta_partido
    scope_category = scope_category or cfg.scope_category
    force_refetch = cfg.force_refetch if force_refetch is None else force_refetch

    acta_settings = dataclasses.replace(
        settings,
        network=dataclasses.replace(settings.network, rate_limit_seconds=cfg.rate_limit_seconds),
    )
    client = RffmClient(acta_settings)

    targets = _load_targets(settings, scope_category)
    logger.info("acta-partido enrichment: %d target matches in category=%s", len(targets), scope_category)

    progress = _Progress(settings, scope_category, len(targets))
    progress.write()

    all_lineups: list[dict] = []
    all_goals: list[dict] = []
    all_cards: list[dict] = []
    all_staff: list[dict] = []
    all_officials: list[dict] = []
    all_warnings: list[dict] = []

    for _, row in targets.iterrows():
        match_id = row["match_id"]
        season_label = row["season"]
        category = row["category"]
        raw_path = _raw_path(settings, category, season_label, match_id)

        game = None
        if raw_path.exists() and not force_refetch:
            cached_html = raw_path.read_text(encoding="utf-8")
            page_props = extract_next_data(cached_html)
            game = (page_props or {}).get("game")
            if game is not None:
                progress.skipped_cached += 1
            else:
                logger.warning("Cached acta file unparseable, will refetch: %s", raw_path)

        if game is None:
            # Reaches here both on a cold cache and on a cache-read that
            # failed to yield a usable "game" object (e.g. a torn file from
            # an older, pre-atomic-write run) - either way, fetch fresh.
            fetch_started = time.monotonic()
            result = fetch_acta_partido(
                client, acta_settings, season_id=row["season_id"], competicion=row["competition_id"],
                grupo=row["group_id"], match_id=match_id,
            )
            if result.ok and result.raw_html:
                atomic_write_text(raw_path, result.raw_html)
                game = (result.page_props or {}).get("game")
                progress.record_fetch(time.monotonic() - fetch_started)

        progress.completed += 1
        progress.last_match_id_processed = match_id

        if game is None:
            progress.failed += 1
        else:
            parsed = parse_acta_partido(
                game, match_id=match_id, home_team_id=row["home_team_id"],
                away_team_id=row["away_team_id"],
                source_url=f"{settings.site.base_url}{settings.site.pages.acta_partido}/{match_id}",
            )
            all_lineups.extend(parsed["lineups"])
            all_goals.extend(parsed["goals"])
            all_cards.extend(parsed["cards"])
            all_staff.extend(parsed["staff"])
            all_officials.extend(parsed["officials"])
            all_warnings.extend(parsed["warnings"])

        if progress.completed % cfg.progress_report_every == 0:
            progress.write()
            logger.info(
                "acta-partido progress: %d/%d (cached=%d fresh=%d failed=%d)",
                progress.completed, progress.total_targets, progress.skipped_cached,
                progress.freshly_fetched_ok, progress.failed,
            )

    progress.write()

    lineups_df = pd.DataFrame(validate_rows(MatchLineupEntry, all_lineups, "match_lineup"))
    goals_df = pd.DataFrame(validate_rows(MatchGoalEvent, all_goals, "match_goal"))
    cards_df = pd.DataFrame(validate_rows(MatchCardEvent, all_cards, "match_card"))
    staff_df = pd.DataFrame(validate_rows(MatchStaff, all_staff, "match_staff"))
    officials_df = pd.DataFrame(validate_rows(MatchOfficial, all_officials, "match_official"))

    processed = settings.processed_dir
    processed.mkdir(parents=True, exist_ok=True)
    write_csv(lineups_df, processed / "match_lineups.csv")
    write_csv(goals_df, processed / "match_goals.csv")
    write_csv(cards_df, processed / "match_cards.csv")
    write_csv(staff_df, processed / "match_staff.csv")
    write_csv(officials_df, processed / "match_officials.csv")

    acta_crawl_log_df = pd.DataFrame(
        validate_rows(CrawlLogEntry, [dataclasses.asdict(e) for e in client.crawl_log], "acta_crawl_log")
    )
    write_csv(acta_crawl_log_df, processed / "acta_crawl_log.csv")

    quality_issues = run_acta_quality_checks(
        lineups_df, goals_df, cards_df, targets, set(targets["match_id"]), all_warnings,
    )
    write_csv(pd.DataFrame(quality_issues), processed / "acta_data_quality_report.csv")

    summary = dict(
        scope_category=scope_category,
        targets=len(targets),
        completed=progress.completed,
        freshly_fetched_ok=progress.freshly_fetched_ok,
        skipped_cached=progress.skipped_cached,
        failed=progress.failed,
        lineups=len(lineups_df),
        goals=len(goals_df),
        cards=len(cards_df),
        staff=len(staff_df),
        officials=len(officials_df),
        quality_issues=len(quality_issues),
    )
    logger.info("acta-partido enrichment summary: %s", summary)
    return summary
