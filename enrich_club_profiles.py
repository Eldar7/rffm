#!/usr/bin/env python3
"""CLI entrypoint for the club-profiles (fichaclub) enrichment stage.

Not robots.txt-disallowed, but gated behind `enrichment.fetch_fichaclub:
true` in config.yaml anyway, for consistency with the other three
enrichment stages (checked again here as a second guard). Reads targets
from every output/processed/rffm/<season>/clubs.csv already committed
(cross-season, not season-scoped) - run main.py + enrich_clubs.py for at
least one season first.

clubs_extended.csv/club_teams.csv are append-only snapshot logs, not
upserted - see club_profile_pipeline.py's module docstring. Default
(no --force-refetch) is a resumable backfill: only club_ids with no prior
successful fetch are targeted. --force-refetch takes a fresh snapshot of
every target club_id, appended alongside whatever snapshots already exist -
use it for a deliberate periodic refresh, not routine re-runs.

Usage:
    python enrich_club_profiles.py [--config config.yaml]
                                    [--force-refetch] [--log-level INFO]
"""
from __future__ import annotations

import argparse
import logging
import sys

from rffm_scraper.club_profile_pipeline import run_club_profile_enrichment
from rffm_scraper.config import load_settings


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RFFM club-profiles enrichment (full club profile + team roster, from /fichaclub/<club_id>)"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--force-refetch", action="store_true",
        help="Take a fresh snapshot of every target club_id, even ones already successfully fetched before",
    )
    parser.add_argument("--workers", type=int, default=None, help="Parallel fetch threads (default: from config, 8)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = load_settings(args.config)

    if not settings.enrichment.fetch_fichaclub:
        print(
            "enrichment.fetch_fichaclub is false in config.yaml - refusing to run.\n"
            "Set it to true as a deliberate opt-in (not robots.txt-disallowed, but "
            "gated for consistency with the other enrichment stages).",
            file=sys.stderr,
        )
        return 1

    summary = run_club_profile_enrichment(settings, force_refetch=args.force_refetch or None, workers=args.workers)
    print("\n=== club_profiles enrichment summary ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
