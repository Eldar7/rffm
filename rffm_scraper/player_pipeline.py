"""Enrichment pipeline: /fichajugador/<player_id> -> player profile/season stats/participation.

Runs *after* acta_pipeline.py: targets are the unique player_ids already
collected in match_lineups.csv (that file only contains whichever category
scope the acta stage was last run for, so no further category filtering
happens here - the scope is inherited from it).

Known simplification: scorers.csv does not currently capture codigo_jugador
(only player_name, aggregated from the goleadores page), so it cannot be
unioned in as a defensive fallback source the way the plan originally
proposed - documented here rather than silently dropped. Coverage gaps are
still caught by player_quality_checks.py's coverage/reconciliation checks.

Same resumability/progress/batched-flush/coverage-manifest design as
acta_pipeline.py - see that module's docstring for the full rationale
(crawl-log-based "already done" as the cross-environment resumability
source of truth, batched atomic flush so a killed run loses at most one
partial batch, output/processed/rffm/coverage_manifest.csv upserted after
every flush).
"""
from __future__ import annotations

import dataclasses
import logging
import os
import time
from datetime import datetime, timezone

import pandas as pd

from rffm_scraper.config import Settings
from rffm_scraper.fetchers import extract_next_data, fetch_fichajugador
from rffm_scraper.fichajugador_parsers import parse_player_profile
from rffm_scraper.http_client import RffmClient
from rffm_scraper.models import CrawlLogEntry, Player, PlayerCompetitionParticipation, PlayerSeasonStats
from rffm_scraper.player_quality_checks import run_player_quality_checks
from rffm_scraper.row_io import (
    Progress,
    already_done_ids,
    append_or_write_csv,
    atomic_write_text,
    downgrade_crawl_log_if_no_content,
    git_push_progress,
    upsert_coverage_manifest,
    validate_rows,
    write_csv,
)

logger = logging.getLogger("rffm_scraper.player_pipeline")

# See acta_pipeline.py for why this exists - same GIT_PUSH_BRANCH-gated
# mid-run checkpoint mechanism, same rationale (bound a GitHub Actions job
# timeout's data loss to a few batches instead of the whole run).
_PUSH_BRANCH = os.environ.get("RFFM_GIT_PUSH_BRANCH")
_PUSH_EVERY_N_FLUSHES = 5

# (batch dict key, output filename, pydantic model, validate_rows label)
_OUTPUT_TABLES = [
    ("players", "players.csv", Player, "player"),
    ("season_stats", "player_season_stats.csv", PlayerSeasonStats, "player_season_stats"),
    ("competitions", "player_competition_participation.csv", PlayerCompetitionParticipation, "player_competition_participation"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_target_player_ids(settings: Settings) -> list[str]:
    lineups_dir = settings.processed_dir / "match_lineups"
    frames = [
        pd.read_csv(p, usecols=["player_id"], dtype=str)
        for p in sorted(lineups_dir.glob("*.csv"))
    ]
    if not frames:
        return []
    return sorted(pd.concat(frames)["player_id"].dropna().unique().tolist())


def _raw_path(settings: Settings, category: str, season_label: str, player_id: str):
    return settings.raw_dir / category.lower() / season_label / "fichajugador" / f"{player_id}.html"


def _progress_path(settings: Settings, season_label: str, scope_category: str):
    return settings.discovery_dir / f"fichajugador_progress_{season_label}_{scope_category.lower()}.json"


# id-like columns forced to str on reread - see acta_pipeline._ID_COLUMNS
# for why (an ID column with no nulls otherwise infers as int64, breaking
# joins/lookups against dtype=str id columns elsewhere - e.g. would make
# player_quality_checks._check_jugados_reconciliation's
# lineup_counts.get(player_id, 0) silently miss on every player, since a
# dict keyed by str player_id never matches an int64 lookup key).
_ID_COLUMNS = {
    "players.csv": ["player_id"],
    "player_season_stats.csv": ["player_id"],
    "player_competition_participation.csv": ["player_id", "team_id", "group_id", "competition_id"],
}


def _reread_table(processed, filename: str) -> pd.DataFrame:
    """Read a fully-consolidated output table back from disk for the
    end-of-run quality-check pass - see acta_pipeline._reread_table for why
    (in-memory batch lists only hold this run's newly-processed rows once a
    run has resumed past a previous partial run)."""
    path = processed / filename
    if not path.exists():
        return pd.DataFrame()
    id_cols = _ID_COLUMNS.get(filename)
    dtype = {col: str for col in id_cols} if id_cols else None
    return pd.read_csv(path, dtype=dtype)


def _flush_batch(processed, batches: dict[str, list[dict]], crawl_log_rows: list[dict]) -> None:
    for key, filename, model_cls, label in _OUTPUT_TABLES:
        rows = batches[key]
        if rows:
            validated = validate_rows(model_cls, rows, label)
            rows.clear()
            if validated:
                df = pd.DataFrame(validated)
                append_or_write_csv(df, processed / filename)

    if crawl_log_rows:
        validated_log = validate_rows(CrawlLogEntry, crawl_log_rows, "fichajugador_crawl_log")
        crawl_log_rows.clear()
        if validated_log:
            log_df = pd.DataFrame(validated_log)
            append_or_write_csv(log_df, processed / "fichajugador_crawl_log.csv")


def run_player_enrichment(settings: Settings, scope_category: str | None = None, force_refetch: bool | None = None) -> dict:
    if not settings.enrichment.fetch_fichajugador:
        raise RuntimeError(
            "enrichment.fetch_fichajugador is false in config - refusing to crawl "
            "/fichajugador/ (robots.txt-disallowed) without an explicit opt-in."
        )

    cfg = settings.enrichment.fichajugador
    scope_category = scope_category or cfg.scope_category
    force_refetch = cfg.force_refetch if force_refetch is None else force_refetch
    season_label = settings.target.season_label

    player_settings = dataclasses.replace(
        settings,
        network=dataclasses.replace(settings.network, rate_limit_seconds=cfg.rate_limit_seconds),
    )
    client = RffmClient(player_settings)

    # season_id ("21") is needed for the fichajugador URL; matches.csv already
    # has it per-row, so pull it from there rather than re-resolving via
    # /api/seasons (avoids an extra network round-trip for one lookup).
    matches_path = settings.processed_dir / "matches.csv"
    matches_df = pd.read_csv(matches_path, dtype=str, keep_default_na=True)
    season_id = matches_df.loc[matches_df["season"] == season_label, "season_id"].iloc[0]

    target_player_ids = _load_target_player_ids(settings)

    processed = settings.processed_dir
    processed.mkdir(parents=True, exist_ok=True)

    # Resumability source of truth: the UNION of (a) crawl-log successes and
    # (b) player_ids already present in players.csv - see
    # acta_pipeline.run_acta_enrichment for why both are needed (in short:
    # (a) alone can under-count against data committed by an older,
    # pre-batching run that never logged cache hits, which would otherwise
    # cause append_or_write_csv to duplicate already-committed rows).
    done_ids: set[str] = already_done_ids(processed / "fichajugador_crawl_log.csv", entity_type="player_ficha")
    players_path = processed / "players.csv"
    if players_path.exists():
        done_ids |= set(pd.read_csv(players_path, usecols=["player_id"], dtype=str)["player_id"].dropna())
    already_done_this_scope = done_ids & set(target_player_ids)
    remaining = [pid for pid in target_player_ids if pid not in done_ids]

    logger.info(
        "fichajugador enrichment: %d targets total, %d already done, %d remaining (season=%s scope=%s)",
        len(target_player_ids), len(already_done_this_scope), len(remaining), season_label, scope_category,
    )

    progress = Progress(_progress_path(settings, season_label, scope_category), scope_category, len(target_player_ids))
    progress.completed = len(already_done_this_scope)
    progress.write()

    started_at = _now_iso()
    batches: dict[str, list[dict]] = {key: [] for key, _, _, _ in _OUTPUT_TABLES}
    pending_crawl_log_rows: list[dict] = []
    flush_count = 0

    for i, player_id in enumerate(remaining, start=1):
        raw_path = _raw_path(settings, scope_category, season_label, player_id)
        source_url = f"{settings.site.base_url}{settings.site.pages.fichajugador}/{player_id}?temporada={season_id}"

        player_json = None
        cache_hit = False
        if raw_path.exists() and not force_refetch:
            cached_html = raw_path.read_text(encoding="utf-8")
            page_props = extract_next_data(cached_html)
            player_json = (page_props or {}).get("player")
            if player_json is not None:
                progress.skipped_cached += 1
                cache_hit = True
            else:
                logger.warning("Cached fichajugador file unparseable, will refetch: %s", raw_path)

        if player_json is None:
            fetch_started = time.monotonic()
            result = fetch_fichajugador(client, player_settings, season_id=season_id, player_id=player_id)
            if result.ok and result.raw_html:
                atomic_write_text(raw_path, result.raw_html)
                player_json = (result.page_props or {}).get("player")
                progress.record_fetch(time.monotonic() - fetch_started)
            log_entry = downgrade_crawl_log_if_no_content(
                dataclasses.asdict(client.crawl_log[-1]), content_ok=player_json is not None,
            )
            pending_crawl_log_rows.append(log_entry)
        elif cache_hit:
            # Cache hits never touch the network client, so they never
            # produce a crawl_log entry on their own - synthesize one so
            # this player is correctly marked "done" for cross-environment
            # resumability, not just this process's raw-HTML cache.
            pending_crawl_log_rows.append(dict(
                run_id=client.run_id, timestamp=_now_iso(), stage="fichajugador",
                entity_type="player_ficha", entity_id=player_id, source_url=source_url,
                http_status=None, success=True, retry_count=0,
                parser_type="html_next_data_cached", raw_saved_path=str(raw_path),
                message="served_from_raw_cache",
            ))

        progress.completed += 1
        progress.last_item_processed = player_id

        if player_json is None:
            progress.failed += 1
        else:
            done_ids.add(player_id)
            parsed = parse_player_profile(player_json, source_url=source_url)
            batches["players"].append(parsed["player"])
            batches["season_stats"].append(parsed["season_stats"])
            batches["competitions"].extend(parsed["competitions"])

        if progress.completed % cfg.progress_report_every == 0:
            progress.write()
            logger.info(
                "fichajugador progress: %d/%d (cached=%d fresh=%d failed=%d)",
                progress.completed, progress.total_targets, progress.skipped_cached,
                progress.freshly_fetched_ok, progress.failed,
            )

        if i % cfg.csv_flush_every == 0:
            _flush_batch(processed, batches, pending_crawl_log_rows)
            progress.write()
            upsert_coverage_manifest(
                settings.processed_root, season=season_label, season_id=season_id,
                category_base=scope_category, stage="fichajugador", status="partial",
                targets_total=len(target_player_ids), targets_completed=progress.completed,
                targets_failed=progress.failed, started_at=started_at,
            )
            flush_count += 1
            if _PUSH_BRANCH and flush_count % _PUSH_EVERY_N_FLUSHES == 0:
                git_push_progress(
                    _PUSH_BRANCH,
                    f"rffm-crawl checkpoint: fichajugador {scope_category} "
                    f"({progress.completed}/{progress.total_targets})",
                )

    # Final flush - runs even if `remaining` was empty (everything already
    # done in a previous run/environment) or shorter than one full batch.
    _flush_batch(processed, batches, pending_crawl_log_rows)
    progress.write()
    if _PUSH_BRANCH:
        git_push_progress(
            _PUSH_BRANCH,
            f"rffm-crawl checkpoint: fichajugador {scope_category} "
            f"({progress.completed}/{progress.total_targets}, final)",
        )

    missing = set(target_player_ids) - done_ids
    final_status = "complete" if not missing else "complete_with_failures"
    upsert_coverage_manifest(
        settings.processed_root, season=season_label, season_id=season_id,
        category_base=scope_category, stage="fichajugador", status=final_status,
        targets_total=len(target_player_ids), targets_completed=progress.completed,
        targets_failed=len(missing), started_at=started_at, completed_at=_now_iso(),
    )

    players_df = _reread_table(processed, "players.csv")
    season_stats_df = _reread_table(processed, "player_season_stats.csv")
    competitions_df = _reread_table(processed, "player_competition_participation.csv")
    lineups_dir = processed / "match_lineups"
    lineups_frames = [pd.read_csv(p, dtype=str) for p in sorted(lineups_dir.glob("*.csv"))] if lineups_dir.exists() else []
    lineups_df = pd.concat(lineups_frames) if lineups_frames else pd.DataFrame()

    quality_issues = run_player_quality_checks(players_df, season_stats_df, lineups_df, set(target_player_ids))
    write_csv(pd.DataFrame(quality_issues), processed / "fichajugador_data_quality_report.csv")

    summary = dict(
        scope_category=scope_category,
        targets=len(target_player_ids),
        already_done_before_this_run=len(already_done_this_scope),
        processed_this_run=len(remaining),
        completed=progress.completed,
        freshly_fetched_ok=progress.freshly_fetched_ok,
        skipped_cached=progress.skipped_cached,
        failed=progress.failed,
        missing_after_this_run=len(missing),
        status=final_status,
        players=len(players_df),
        season_stats=len(season_stats_df),
        competition_participations=len(competitions_df),
        quality_issues=len(quality_issues),
    )
    logger.info("fichajugador enrichment summary: %s", summary)
    return summary
