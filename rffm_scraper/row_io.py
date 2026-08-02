"""Shared row-validation, CSV-writing, and atomic-file-write helpers.

Used by pipeline.py and every enrichment pipeline (acta_pipeline.py,
player_pipeline.py) so none of them need to reach into another module's
internals to get the same "validate through the pydantic Row model, drop and
log anything invalid, then write a CSV" behavior.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
from datetime import datetime, timedelta, timezone

import pandas as pd

logger = logging.getLogger("rffm_scraper.row_io")


def validate_rows(model_cls, rows: list[dict], label: str) -> list[dict]:
    validated = []
    for row in rows:
        try:
            validated.append(model_cls(**row).model_dump())
        except Exception as exc:  # pydantic ValidationError or similar
            logger.warning("Dropping invalid %s row: %s (row=%s)", label, exc, row)
    return validated


def write_csv(df: pd.DataFrame, path: pathlib.Path) -> None:
    """Atomic: writes via a temp file + os.replace, matching
    atomic_write_text below, so a process killed mid-write never leaves a
    truncated/corrupt CSV at the final path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, path)
    logger.info("Wrote %s (%d rows)", path, len(df))


def append_or_write_csv(new_rows_df: pd.DataFrame, path: pathlib.Path) -> None:
    """Batch-flush primitive for resumable pipelines: merges new_rows_df into
    whatever is already at path (if anything) and atomically rewrites the
    whole file via write_csv above.

    Deliberately read-concat-replace rather than a true file append: a
    process killed mid true-append can leave a torn last line that breaks
    parsing of the *entire* file, while read-concat-atomic-replace can never
    leave a torn file. The reread cost is paid once per batch (whatever
    csv_flush_every is set to), not once per row, so it stays cheap.
    """
    if path.exists():
        existing_df = pd.read_csv(path, dtype=str, keep_default_na=True)
        combined = pd.concat([existing_df, new_rows_df], ignore_index=True)
    else:
        combined = new_rows_df
    write_csv(combined, path)


def downgrade_crawl_log_if_no_content(entry: dict, *, content_ok: bool) -> dict:
    """RffmClient.get()'s crawl-log entry reflects HTTP-level success only (a
    200 response) - it is recorded before the caller ever looks at the page's
    embedded content object. already_done_ids() below treats success==True
    as "fully processed, never retry", so an HTTP-200-but-unparseable-page
    (missing/broken __NEXT_DATA__, or a page with no usable business object)
    would otherwise be marked done forever with no automatic retry - the
    fetch "succeeded" but nothing was actually extracted. Downgrade success
    to False in that case so the target is correctly retried on the next
    run. No-op when content_ok is True or the entry was already a failure.
    """
    if entry["success"] and not content_ok:
        entry = dict(entry)
        entry["success"] = False
        suffix = "fetched OK (HTTP) but no usable content object in page (missing/unparseable __NEXT_DATA__ or empty page)"
        entry["message"] = f"{entry['message']}; {suffix}" if entry["message"] else suffix
    return entry


def already_done_ids(crawl_log_path: pathlib.Path, entity_type: str | None = None) -> set[str]:
    """Resumability source of truth for the batched enrichment pipelines:
    the set of entity_ids with at least one *successful* fetch already
    recorded in a {stage}_crawl_log.csv (empty set if that file doesn't
    exist yet, e.g. first run for this season).

    Deliberately keyed off the crawl log rather than presence in the
    primary output table (match_lineups.csv / players.csv): a legitimately
    processed target can produce zero child rows (e.g. a match with no
    reported lineup on the site - a known, separately-flagged anomaly in
    acta_quality_checks.py), which would be indistinguishable from "never
    attempted" if presence-in-primary-table were the marker instead. This
    also gives automatic retry-on-resume for free - a target that failed
    has no success==True row, so it's simply absent from this set and gets
    retried on the next run, no separate retry queue needed.
    """
    if not crawl_log_path.exists():
        return set()
    df = pd.read_csv(crawl_log_path, dtype=str, keep_default_na=True)
    mask = df["success"] == "True"
    if entity_type is not None:
        mask &= df["entity_type"] == entity_type
    return set(df.loc[mask, "entity_id"].dropna())


_COVERAGE_MANIFEST_COLUMNS = [
    "season", "season_id", "category_base", "stage", "status",
    "targets_total", "targets_completed", "targets_failed",
    "started_at", "last_updated_at", "completed_at", "notes",
]


def upsert_coverage_manifest(
    processed_root: pathlib.Path,
    *,
    season: str,
    season_id: str,
    category_base: str,
    stage: str,
    status: str,
    targets_total: int,
    targets_completed: int,
    targets_failed: int,
    started_at: str,
    completed_at: str | None = None,
    notes: str = "",
) -> None:
    """Upsert one row (keyed by season+category_base+stage) into the
    cross-season output/processed/rffm/coverage_manifest.csv - the single,
    git-tracked place to check "is season X / category Y / stage Z done"
    without loading the full per-row crawl logs. Called after every batch
    flush in the enrichment pipelines (so a hard-killed process leaves an
    accurate `partial` row - the last successful write to this file *is*
    the truth, no separate interruption-detection needed) and once at the
    end of the core pipeline run.
    """
    path = processed_root / "coverage_manifest.csv"
    if path.exists():
        df = pd.read_csv(path, dtype=str, keep_default_na=True)
    else:
        df = pd.DataFrame(columns=_COVERAGE_MANIFEST_COLUMNS)

    key = (df["season"] == season) & (df["category_base"] == category_base) & (df["stage"] == stage)
    df = df[~key]

    row = dict(
        season=season,
        season_id=season_id,
        category_base=category_base,
        stage=stage,
        status=status,
        targets_total=targets_total,
        targets_completed=targets_completed,
        targets_failed=targets_failed,
        started_at=started_at,
        last_updated_at=_now_iso(),
        completed_at=completed_at or "",
        notes=notes,
    )
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df = df.sort_values(["season", "stage", "category_base"]).reset_index(drop=True)
    write_csv(df, path)


def git_push_progress(branch: str, message: str) -> bool:
    """Mid-run checkpoint push for the batched enrichment pipelines
    (acta_pipeline.py, player_pipeline.py), called every few batch flushes
    when GIT_PUSH_BRANCH-style periodic pushing is enabled (see those
    modules for the call site).

    Unlike the GitHub Actions workflow's single end-of-run commit - which,
    if it's the ONLY place progress is ever pushed, means a run cancelled by
    the job timeout can lose its entire multi-hour output in one go, since
    nothing survives on the ephemeral runner past the job ending - this
    pushes straight to a branch created fresh for this one run
    (rffm-crawl.yml creates it before invoking the crawl), so nothing else
    is ever pushing to it concurrently: no fetch/rebase dance needed here,
    just add+commit+push.

    Never raises: a failed checkpoint here (network blip, whatever) must not
    abort an hours-long crawl over a push that can simply be retried by the
    next periodic checkpoint or the workflow's own final commit.
    """
    try:
        subprocess.run(["git", "add", "output/processed"], check=True)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if staged.returncode == 0:
            return True  # nothing new since the last checkpoint
        subprocess.run(["git", "commit", "-m", message], check=True)
        subprocess.run(["git", "push", "origin", f"HEAD:{branch}"], check=True)
        logger.info("Pushed mid-run checkpoint to %s", branch)
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("Mid-run checkpoint push to %s failed (crawl continues): %s", branch, exc)
        return False


def atomic_write_text(path: pathlib.Path, content: str) -> None:
    """Write content to path via a temp file + os.replace, so a process
    killed mid-write never leaves a truncated file at the final path - a
    torn file would otherwise be indistinguishable from a complete one to a
    naive "does this path exist" resume check."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Progress:
    """Shared progress-checkpoint tracker for long-running enrichment crawls
    (acta_pipeline.py, player_pipeline.py). Written atomically to a small
    JSON file every N items so a separate process/agent can cheaply read
    "X done, Y left, rate, ETA" on demand without disturbing the crawl or
    tailing a growing log."""

    def __init__(self, checkpoint_path: pathlib.Path, scope_label: str, total_targets: int):
        self.checkpoint_path = checkpoint_path
        self.scope_label = scope_label
        self.total_targets = total_targets
        self.completed = 0
        self.freshly_fetched_ok = 0
        self.skipped_cached = 0
        self.failed = 0
        self.total_fetch_seconds = 0.0
        self.started_at = _now_iso()
        self.last_item_processed: str | None = None

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
            scope=self.scope_label,
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
            last_item_processed=self.last_item_processed,
        )

    def write(self) -> None:
        atomic_write_text(self.checkpoint_path, json.dumps(self.to_dict(), indent=2))
