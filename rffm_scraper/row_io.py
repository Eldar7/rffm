"""Shared row-validation, CSV-writing, and atomic-file-write helpers.

Used by pipeline.py and every enrichment pipeline (acta_pipeline.py,
player_pipeline.py) so none of them need to reach into another module's
internals to get the same "validate through the pydantic Row model, drop and
log anything invalid, then write a CSV" behavior.
"""
from __future__ import annotations

import logging
import os
import pathlib

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
