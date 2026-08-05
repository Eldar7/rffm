#!/usr/bin/env python3
"""CLI entrypoint for the RFFM BENJAMIN/PREBENJAMIN 2025-2026 scraper.

Usage:
    python main.py [--config config.yaml] [--workers N] [--limit-groups N]
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import pathlib
import sys

from rffm_scraper.config import load_settings
from rffm_scraper.pipeline import run_pipeline


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RFFM data collector (BENJAMIN/PREBENJAMIN 2025-2026 MVP)")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--season", help="Season label override, e.g. 2024-2025.")
    parser.add_argument(
        "--output-dir",
        help="Output root override. Use a separate directory for limited or experimental runs.",
    )
    parser.add_argument(
        "--all-categories", action="store_true",
        help="Discover every category the federation runs this season, not just "
             "config.yaml's target.category_priority - overrides config.yaml's "
             "target.crawl_all_categories to true for this run.",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="Concurrent core/venue fetch workers (default: 8). Each worker has its own rate limiter.",
    )
    parser.add_argument(
        "--limit-groups", type=int,
        help="Process only the first N discovered groups; records core coverage as partial. Use only with an isolated output directory.",
    )
    parser.add_argument(
        "--progress-report-every", type=int, default=25,
        help="Emit core and venue progress after every N completed targets (default: 25).",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = load_settings(args.config)
    if args.season:
        settings.target.season_label = args.season
    if args.output_dir:
        settings = dataclasses.replace(settings, output_dir=pathlib.Path(args.output_dir))
    if args.all_categories:
        settings.target.crawl_all_categories = True
    logging.getLogger("rffm_scraper").info(
        "Starting RFFM crawl: season=%s categories=%s",
        settings.target.season_label,
        "ALL" if settings.target.crawl_all_categories else settings.target.category_priority,
    )
    summary = run_pipeline(
        settings,
        workers=args.workers,
        limit_groups=args.limit_groups,
        progress_report_every=args.progress_report_every,
    )
    print("\n=== Run summary ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
