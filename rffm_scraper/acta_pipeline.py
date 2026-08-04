"""Enrichment pipeline: /acta-partido/<match_id> -> lineups/goals/cards/staff/officials.

Separate from pipeline.py on purpose - this stage is optional (robots.txt
disallows the path; only runs when explicitly opted into), can cover tens of
thousands of matches (order-of-magnitude more requests than the core crawl),
and must be independently resumable across a run that may be interrupted -
including across a *cold* environment (e.g. a fresh GitHub Actions job) that
has none of a previous run's local state.

Resumability has two layers:
  1. Within-process/within-environment: raw acta HTML is cached at a
     deterministic per-match path
     (output/raw/rffm/{category}/{season}/acta/{match_id}.html), written
     atomically (row_io.atomic_write_text). On rerun, an existing cached
     file is parsed directly (no network call) unless force_refetch=True.
     This layer is NOT assumed to survive between environments (raw HTML is
     git-ignored and not pushed), so it's a local speed optimization only.
  2. Across any environment, via committed data: "has match X already been
     fully handled" is answered by acta_crawl_log.csv (success==True for
     that match_id) - see row_io.already_done_ids for why this is the
     source of truth rather than presence in match_lineups.csv (a match can
     legitimately produce zero lineup rows, which would be indistinguishable
     from "never attempted" otherwise). This is what lets a run resume
     cleanly on a brand new machine/job with nothing but this git repo.

Output tables and the crawl log are flushed in batches (every
`csv_flush_every` matches, row_io.append_or_write_csv) rather than once at
the end, so a run killed mid-way (container restart, GitHub Actions job
timeout) never loses more than one partial batch - already-flushed matches
are simply absent from the next run's `remaining` set via layer 2 above.

Progress: a small JSON checkpoint is written atomically every
`progress_report_every` matches to
output/raw/rffm/discovery/acta_progress_<season>_<scope>.json, so a separate
read (by an operator or an agent) can report "X done, Y left, rate, ETA"
without touching the running process or tailing a growing log. This is a
convenience only - not the resumability source of truth (that's #2 above).

output/processed/rffm/coverage_manifest.csv gets one upserted row per
(season, category, "acta_partido") after every batch flush, so there is
always a git-tracked, timestamped answer to "is this season/category done"
even if the process is hard-killed between flushes (the last successful
write to that file *is* the truth - see row_io.upsert_coverage_manifest).

acta_crawl_log.csv / acta_data_quality_report.csv are written as their OWN
files, not appended into the core pipeline's crawl_log.csv/
data_quality_report.csv - those are fully rebuilt from scratch on every
main.py run, so appending here would just get silently wiped by the next
unrelated core rerun.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import time
from datetime import datetime, timezone

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

logger = logging.getLogger("rffm_scraper.acta_pipeline")

# When set (by rffm-crawl.yml, to a branch it created just for this run),
# a mid-run checkpoint is pushed to that branch every _PUSH_EVERY_N_FLUSHES
# batch flushes - see row_io.git_push_progress for why this exists (a
# GitHub Actions job timeout can otherwise discard an entire multi-hour
# run's output in one go, since nothing survives past the ephemeral runner
# except what was actually pushed). Unset for local/non-CI runs, where
# there is no dedicated per-run branch to push to and this is a no-op.
_PUSH_BRANCH = os.environ.get("RFFM_GIT_PUSH_BRANCH")
_PUSH_EVERY_N_FLUSHES = 5

# (batch dict key, subdir, filename template, pydantic model, validate_rows label)
# Files are written to processed/<subdir>/<scope_category>.csv so each
# category's data stays in its own file (avoids the >100 MB GitHub limit
# that a single match_lineups.csv hits once several categories are combined).
_OUTPUT_TABLES = [
    ("lineups", "match_lineups", MatchLineupEntry, "match_lineup"),
    ("goals", "match_goals", MatchGoalEvent, "match_goal"),
    ("cards", "match_cards", MatchCardEvent, "match_card"),
    ("staff", "match_staff", MatchStaff, "match_staff"),
    ("officials", "match_officials", MatchOfficial, "match_official"),
]


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


def _guard_against_silent_empty_scope(
    settings: Settings, *, season_label: str, scope_category: str, stage: str,
) -> None:
    """Refuse to proceed if _load_targets found 0 matches for scope_category
    but coverage_manifest.csv already shows this exact (season, scope,
    stage) had a nonzero target count before.

    Without this, a 0-target run falls through run_acta_enrichment's normal
    completion logic ("missing = set() - done_ids = set()" -> status
    "complete") and upsert_coverage_manifest overwrites the last-known-good
    progress row with a false "complete, 0/0" - indistinguishable from a
    legitimately empty scope. This has a real trigger: matches.csv's
    `category` column is denormalized from discovery's category_base (see
    pipeline.py), so any change to how category_base is computed (e.g. a
    core crawl re-run under different taxonomy rules) can silently empty
    out what `category == scope_category` matches, with no error anywhere
    in between. See DATA_DICTIONARY.md's "Category taxonomy" section for
    the incident that motivated this guard.
    """
    manifest_path = settings.processed_root / "coverage_manifest.csv"
    if not manifest_path.exists():
        return
    existing = pd.read_csv(manifest_path, dtype=str, keep_default_na=True)
    prior = existing[
        (existing["season"] == season_label)
        & (existing["category_base"] == scope_category)
        & (existing["stage"] == stage)
    ]
    if prior.empty:
        return
    prior_targets_total = int(prior.iloc[-1]["targets_total"] or 0)
    if prior_targets_total > 0:
        raise RuntimeError(
            f"{stage}: matches.csv has 0 rows with category={scope_category!r}, but "
            f"coverage_manifest.csv already shows {prior_targets_total} targets for "
            f"(season={season_label!r}, category_base={scope_category!r}, stage={stage!r}) from a "
            f"previous run. Refusing to overwrite that with a false 'complete, 0/0' row. This "
            f"usually means matches.csv's category taxonomy changed upstream (e.g. a core "
            f"all-categories re-run) and scope_category no longer matches anything in it - check "
            f"DATA_DICTIONARY.md's 'Category taxonomy' section and re-run core if so."
        )


def _progress_path(settings: Settings, season_label: str, scope_category: str):
    return settings.discovery_dir / f"acta_progress_{season_label}_{scope_category.lower()}.json"


# id-like columns forced to str on reread (below) - everything else is left
# to pandas' natural dtype inference (numeric columns like `minute` need to
# stay comparable to int bounds in the quality checks). Without this, an ID
# column with no nulls infers as int64, which then fails to merge/join
# against the dtype=str id columns in matches_df/targets ("You are trying to
# merge on int64 and str columns") - caught by the verification dry run.
_ID_COLUMNS = {
    "match_lineups": ["match_id", "team_id", "player_id"],
    "match_goals": ["match_id", "team_id", "player_id"],
    "match_cards": ["match_id", "team_id", "player_id"],
}


def _reread_table(processed, subdir: str, scope_category: str) -> pd.DataFrame:
    """Read a fully-consolidated output table back from disk for the
    end-of-run quality-check pass - the in-memory batch lists only hold
    *this run's* newly-processed rows once a run has resumed past a
    previous partial run, so quality checks (which need the full picture)
    must read the merged-on-disk state instead."""
    path = processed / subdir / f"{scope_category}.csv"
    if not path.exists():
        return pd.DataFrame()
    id_cols = _ID_COLUMNS.get(subdir)
    dtype = {col: str for col in id_cols} if id_cols else None
    return pd.read_csv(path, dtype=dtype)


def _flush_batch(processed, scope_category: str, batches: dict[str, list[dict]], crawl_log_rows: list[dict]) -> None:
    """Merge one batch's accumulated rows into each output CSV + the crawl
    log, atomically. Clears the batch lists in place so callers can keep
    reusing the same dict/list objects across the whole run."""
    for key, subdir, model_cls, label in _OUTPUT_TABLES:
        rows = batches[key]
        if rows:
            df = pd.DataFrame(validate_rows(model_cls, rows, label))
            out_path = processed / subdir / f"{scope_category}.csv"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            append_or_write_csv(df, out_path)
            rows.clear()

    if crawl_log_rows:
        log_df = pd.DataFrame(validate_rows(CrawlLogEntry, crawl_log_rows, "acta_crawl_log"))
        append_or_write_csv(log_df, processed / "acta_crawl_log.csv")
        crawl_log_rows.clear()


def run_acta_enrichment(settings: Settings, scope_category: str | None = None, force_refetch: bool | None = None) -> dict:
    if not settings.enrichment.fetch_acta_partido:
        raise RuntimeError(
            "enrichment.fetch_acta_partido is false in config - refusing to crawl "
            "/acta-partido/ (robots.txt-disallowed) without an explicit opt-in."
        )

    cfg = settings.enrichment.acta_partido
    scope_category = scope_category or cfg.scope_category
    force_refetch = cfg.force_refetch if force_refetch is None else force_refetch
    season_label = settings.target.season_label

    acta_settings = dataclasses.replace(
        settings,
        network=dataclasses.replace(settings.network, rate_limit_seconds=cfg.rate_limit_seconds),
    )
    client = RffmClient(acta_settings)

    targets = _load_targets(settings, scope_category)
    target_match_ids: list[str] = targets["match_id"].tolist()
    season_id = targets["season_id"].iloc[0] if len(targets) else ""

    processed = settings.processed_dir
    processed.mkdir(parents=True, exist_ok=True)

    if not target_match_ids:
        _guard_against_silent_empty_scope(
            settings, season_label=season_label, scope_category=scope_category, stage="acta_partido",
        )

    # Resumability source of truth: the UNION of (a) crawl-log successes and
    # (b) match_ids already present in match_lineups/<scope>.csv. (a) alone
    # catches a match that legitimately produced zero lineup rows (which (b)
    # can't tell apart from "never attempted"); (b) alone catches matches
    # whose data is already fully committed but whose crawl_log entry predates
    # this batched design (older runs only logged *fresh* fetches, never
    # cache hits, so an old crawl_log can under-count relative to what's
    # actually in match_lineups/<scope>.csv) - relying on (a) alone in that
    # case would re-fetch-from-cache and duplicate already-committed rows via
    # append_or_write_csv. Together they're safe against both failure modes.
    done_ids: set[str] = already_done_ids(processed / "acta_crawl_log.csv", entity_type="match_acta")
    lineups_path = processed / "match_lineups" / f"{scope_category}.csv"
    if lineups_path.exists():
        done_ids |= set(pd.read_csv(lineups_path, usecols=["match_id"], dtype=str)["match_id"].dropna())
    already_done_this_scope = done_ids & set(target_match_ids)
    remaining = targets[~targets["match_id"].isin(done_ids)].reset_index(drop=True)

    logger.info(
        "acta-partido enrichment: %d targets total, %d already done, %d remaining (season=%s category=%s)",
        len(targets), len(already_done_this_scope), len(remaining), season_label, scope_category,
    )

    progress = Progress(_progress_path(settings, season_label, scope_category), scope_category, len(targets))
    progress.completed = len(already_done_this_scope)
    progress.write()

    started_at = _now_iso()
    batches: dict[str, list[dict]] = {key: [] for key, _, _, _ in _OUTPUT_TABLES}
    pending_crawl_log_rows: list[dict] = []
    all_warnings: list[dict] = []
    flush_count = 0

    for i, (_, row) in enumerate(remaining.iterrows(), start=1):
        match_id = row["match_id"]
        row_season_label = row["season"]
        category = row["category"]
        raw_path = _raw_path(settings, category, row_season_label, match_id)
        source_url = f"{settings.site.base_url}{settings.site.pages.acta_partido}/{match_id}"

        game = None
        cache_hit = False
        if raw_path.exists() and not force_refetch:
            cached_html = raw_path.read_text(encoding="utf-8")
            page_props = extract_next_data(cached_html)
            game = (page_props or {}).get("game")
            if game is not None:
                progress.skipped_cached += 1
                cache_hit = True
            else:
                logger.warning("Cached acta file unparseable, will refetch: %s", raw_path)

        if game is None:
            # Reaches here both on a cold cache and on a cache-read that
            # failed to yield a usable "game" object - either way, fetch
            # fresh. This also records a real crawl_log entry via `client`.
            fetch_started = time.monotonic()
            result = fetch_acta_partido(
                client, acta_settings, season_id=row["season_id"], competicion=row["competition_id"],
                grupo=row["group_id"], match_id=match_id,
            )
            if result.ok and result.raw_html:
                atomic_write_text(raw_path, result.raw_html)
                game = (result.page_props or {}).get("game")
                progress.record_fetch(time.monotonic() - fetch_started)
            log_entry = downgrade_crawl_log_if_no_content(
                dataclasses.asdict(client.crawl_log[-1]), content_ok=game is not None,
            )
            pending_crawl_log_rows.append(log_entry)
        elif cache_hit:
            # A cache hit never touches the network client, so it never
            # produces a crawl_log entry on its own - synthesize one so this
            # match is correctly marked "done" for future/other-environment
            # resumability (layer 2), not just this process's raw-HTML cache.
            pending_crawl_log_rows.append(dict(
                run_id=client.run_id, timestamp=_now_iso(), stage="acta_partido",
                entity_type="match_acta", entity_id=match_id, source_url=source_url,
                http_status=None, success=True, retry_count=0,
                parser_type="html_next_data_cached", raw_saved_path=str(raw_path),
                message="served_from_raw_cache",
            ))

        progress.completed += 1
        progress.last_item_processed = match_id

        if game is None:
            progress.failed += 1
        else:
            done_ids.add(match_id)
            parsed = parse_acta_partido(
                game, match_id=match_id, home_team_id=row["home_team_id"],
                away_team_id=row["away_team_id"], source_url=source_url,
            )
            batches["lineups"].extend(parsed["lineups"])
            batches["goals"].extend(parsed["goals"])
            batches["cards"].extend(parsed["cards"])
            batches["staff"].extend(parsed["staff"])
            batches["officials"].extend(parsed["officials"])
            all_warnings.extend(parsed["warnings"])

        if progress.completed % cfg.progress_report_every == 0:
            progress.write()
            logger.info(
                "acta-partido progress: %d/%d (cached=%d fresh=%d failed=%d)",
                progress.completed, progress.total_targets, progress.skipped_cached,
                progress.freshly_fetched_ok, progress.failed,
            )

        if i % cfg.csv_flush_every == 0:
            _flush_batch(processed, scope_category, batches, pending_crawl_log_rows)
            progress.write()
            upsert_coverage_manifest(
                settings.processed_root, season=season_label, season_id=season_id,
                category_base=scope_category, stage="acta_partido", status="partial",
                targets_total=len(target_match_ids), targets_completed=progress.completed,
                targets_failed=progress.failed, started_at=started_at,
            )
            flush_count += 1
            if _PUSH_BRANCH and flush_count % _PUSH_EVERY_N_FLUSHES == 0:
                git_push_progress(
                    _PUSH_BRANCH,
                    f"rffm-crawl checkpoint: acta_partido {scope_category} "
                    f"({progress.completed}/{progress.total_targets})",
                )

    # Final flush - runs even if `remaining` was empty (everything already
    # done in a previous run/environment) or shorter than one full batch.
    _flush_batch(processed, scope_category, batches, pending_crawl_log_rows)
    progress.write()
    if _PUSH_BRANCH:
        git_push_progress(
            _PUSH_BRANCH,
            f"rffm-crawl checkpoint: acta_partido {scope_category} "
            f"({progress.completed}/{progress.total_targets}, final)",
        )

    missing = set(target_match_ids) - done_ids
    final_status = "complete" if not missing else "complete_with_failures"
    upsert_coverage_manifest(
        settings.processed_root, season=season_label, season_id=season_id,
        category_base=scope_category, stage="acta_partido", status=final_status,
        targets_total=len(target_match_ids), targets_completed=progress.completed,
        targets_failed=len(missing), started_at=started_at, completed_at=_now_iso(),
    )

    lineups_df = _reread_table(processed, "match_lineups", scope_category)
    goals_df = _reread_table(processed, "match_goals", scope_category)
    cards_df = _reread_table(processed, "match_cards", scope_category)

    quality_issues = run_acta_quality_checks(
        lineups_df, goals_df, cards_df, targets, set(target_match_ids), all_warnings,
    )
    write_csv(pd.DataFrame(quality_issues), processed / "acta_data_quality_report.csv")

    summary = dict(
        scope_category=scope_category,
        targets=len(targets),
        already_done_before_this_run=len(already_done_this_scope),
        processed_this_run=len(remaining),
        completed=progress.completed,
        freshly_fetched_ok=progress.freshly_fetched_ok,
        skipped_cached=progress.skipped_cached,
        failed=progress.failed,
        missing_after_this_run=len(missing),
        status=final_status,
        lineups=len(lineups_df),
        goals=len(goals_df),
        cards=len(cards_df),
        quality_issues=len(quality_issues),
    )
    logger.info("acta-partido enrichment summary: %s", summary)
    return summary
