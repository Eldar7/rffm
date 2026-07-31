#!/usr/bin/env python3
"""CLI entrypoint for the RFFM BENJAMIN/PREBENJAMIN 2025-2026 scraper.

Usage:
    python main.py [--config config.yaml] [--log-level INFO] [--limit-groups N]
"""
from __future__ import annotations

import argparse
import logging
import sys

from rffm_scraper.config import load_settings
from rffm_scraper.pipeline import run_pipeline


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RFFM data collector (BENJAMIN/PREBENJAMIN 2025-2026 MVP)")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = load_settings(args.config)
    logging.getLogger("rffm_scraper").info(
        "Starting RFFM crawl: season=%s categories=%s",
        settings.target.season_label, settings.target.category_priority,
    )
    summary = run_pipeline(settings)
    print("\n=== Run summary ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
