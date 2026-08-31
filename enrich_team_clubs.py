#!/usr/bin/env python3
"""CLI entrypoint for the team_clubs (fichaequipo, full coverage) enrichment
stage.

Off by default - robots.txt disallows /fichaequipo/. Requires
`enrichment.fetch_fichaequipo: true` in config.yaml as an explicit,
informed opt-in (checked again here as a second guard) - same page and same
flag as enrich_clubs.py, just a different, complete target-selection
strategy (see team_club_pipeline.py's module docstring for why that
pipeline's one-representative-per-club_name_raw sampling leaves a real
coverage gap this stage exists to close).

Not category-scoped, like enrich_clubs.py - a club is not an age-bracket
concept. Cross-season, unlike enrich_clubs.py: targets are drawn from the
current config.yaml season_label's teams.csv, but the "already resolved"
check and the output tables (team_club_map.csv, team_clubs_crawl_log.csv)
are shared across every season, so a team_id is fetched at most once ever,
regardless of how many seasons' teams.csv it appears in.

Usage:
    python enrich_team_clubs.py [--config config.yaml]
                                 [--force-refetch] [--log-level INFO]
"""
from __future__ import annotations

import argparse
import logging
import sys

from rffm_scraper.config import load_settings
from rffm_scraper.team_club_pipeline import run_team_club_enrichment


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RFFM team_clubs enrichment (complete team_id -> club_id resolution)"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--force-refetch", action="store_true",
        help="Ignore cached raw HTML and refetch every remaining target (does not re-fetch "
             "team_ids already resolved or already attempted - see module docstring)",
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

    if not settings.enrichment.fetch_fichaequipo:
        print(
            "enrichment.fetch_fichaequipo is false in config.yaml - refusing to run.\n"
            "This stage crawls /fichaequipo/, which robots.txt disallows; set it to "
            "true only as a deliberate, informed opt-in.",
            file=sys.stderr,
        )
        return 1

    summary = run_team_club_enrichment(settings, force_refetch=args.force_refetch or None, workers=args.workers)
    print("\n=== team_clubs enrichment summary ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
