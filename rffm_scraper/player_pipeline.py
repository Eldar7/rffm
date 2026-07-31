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

Same resumability/progress/separate-report-files design as acta_pipeline.py
- see that module's docstring for the full rationale.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from datetime import datetime, timezone

import pandas as pd

from rffm_scraper.config import Settings
from rffm_scraper.fetchers import extract_next_data, fetch_fichajugador
from rffm_scraper.fichajugador_parsers import parse_player_profile
from rffm_scraper.http_client import RffmClient
from rffm_scraper.models import CrawlLogEntry, Player, PlayerCompetitionParticipation, PlayerSeasonStats
from rffm_scraper.player_quality_checks import run_player_quality_checks
from rffm_scraper.row_io import Progress, atomic_write_text, validate_rows, write_csv

logger = logging.getLogger("rffm_scraper.player_pipeline")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_target_player_ids(settings: Settings) -> list[str]:
    path = settings.processed_dir / "match_lineups.csv"
    df = pd.read_csv(path, dtype=str, keep_default_na=True)
    return sorted(df["player_id"].dropna().unique().tolist())


def _raw_path(settings: Settings, category: str, season_label: str, player_id: str):
    return settings.raw_dir / category.lower() / season_label / "fichajugador" / f"{player_id}.html"


def _progress_path(settings: Settings, scope_category: str):
    return settings.discovery_dir / f"fichajugador_progress_{scope_category.lower()}.json"


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
    logger.info("fichajugador enrichment: %d target players (scope=%s)", len(target_player_ids), scope_category)

    progress = Progress(_progress_path(settings, scope_category), scope_category, len(target_player_ids))
    progress.write()

    all_players: list[dict] = []
    all_season_stats: list[dict] = []
    all_competitions: list[dict] = []

    for player_id in target_player_ids:
        raw_path = _raw_path(settings, scope_category, season_label, player_id)

        player_json = None
        if raw_path.exists() and not force_refetch:
            cached_html = raw_path.read_text(encoding="utf-8")
            page_props = extract_next_data(cached_html)
            player_json = (page_props or {}).get("player")
            if player_json is not None:
                progress.skipped_cached += 1
            else:
                logger.warning("Cached fichajugador file unparseable, will refetch: %s", raw_path)

        if player_json is None:
            fetch_started = time.monotonic()
            result = fetch_fichajugador(client, player_settings, season_id=season_id, player_id=player_id)
            if result.ok and result.raw_html:
                atomic_write_text(raw_path, result.raw_html)
                player_json = (result.page_props or {}).get("player")
                progress.record_fetch(time.monotonic() - fetch_started)

        progress.completed += 1
        progress.last_item_processed = player_id

        if player_json is None:
            progress.failed += 1
        else:
            parsed = parse_player_profile(
                player_json,
                source_url=f"{settings.site.base_url}{settings.site.pages.fichajugador}/{player_id}?temporada={season_id}",
            )
            all_players.append(parsed["player"])
            all_season_stats.append(parsed["season_stats"])
            all_competitions.extend(parsed["competitions"])

        if progress.completed % cfg.progress_report_every == 0:
            progress.write()
            logger.info(
                "fichajugador progress: %d/%d (cached=%d fresh=%d failed=%d)",
                progress.completed, progress.total_targets, progress.skipped_cached,
                progress.freshly_fetched_ok, progress.failed,
            )

    progress.write()

    players_df = pd.DataFrame(validate_rows(Player, all_players, "player"))
    season_stats_df = pd.DataFrame(validate_rows(PlayerSeasonStats, all_season_stats, "player_season_stats"))
    competitions_df = pd.DataFrame(
        validate_rows(PlayerCompetitionParticipation, all_competitions, "player_competition_participation")
    )

    processed = settings.processed_dir
    processed.mkdir(parents=True, exist_ok=True)
    write_csv(players_df, processed / "players.csv")
    write_csv(season_stats_df, processed / "player_season_stats.csv")
    write_csv(competitions_df, processed / "player_competition_participation.csv")

    fichajugador_crawl_log_df = pd.DataFrame(
        validate_rows(CrawlLogEntry, [dataclasses.asdict(e) for e in client.crawl_log], "fichajugador_crawl_log")
    )
    write_csv(fichajugador_crawl_log_df, processed / "fichajugador_crawl_log.csv")

    lineups_df = pd.read_csv(processed / "match_lineups.csv", dtype=str, keep_default_na=True)
    quality_issues = run_player_quality_checks(players_df, season_stats_df, lineups_df, set(target_player_ids))
    write_csv(pd.DataFrame(quality_issues), processed / "fichajugador_data_quality_report.csv")

    summary = dict(
        scope_category=scope_category,
        targets=len(target_player_ids),
        completed=progress.completed,
        freshly_fetched_ok=progress.freshly_fetched_ok,
        skipped_cached=progress.skipped_cached,
        failed=progress.failed,
        players=len(players_df),
        season_stats=len(season_stats_df),
        competition_participations=len(competitions_df),
        quality_issues=len(quality_issues),
    )
    logger.info("fichajugador enrichment summary: %s", summary)
    return summary
