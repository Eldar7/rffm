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
    df.to_csv(path, index=False)
    logger.info("Wrote %s (%d rows)", path, len(df))


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
