#!/usr/bin/env python3
"""CLI entrypoint for the clubs (fichaequipo) enrichment stage.

Off by default - robots.txt disallows /fichaequipo/. Requires
`enrichment.fetch_fichaequipo: true` in config.yaml as an explicit,
informed opt-in (checked again here as a second guard). Reads targets from
output/processed/rffm/{teams,team_group_membership,groups,matches}.csv,
produced by `python main.py` - run that first.

Usage:
    python enrich_clubs.py [--config config.yaml] [--scope PREBENJAMIN]
                            [--force-refetch] [--log-level INFO]
"""
from __future__ import annotations

import argparse
import logging
import sys

from rffm_scraper.club_pipeline import run_club_enrichment
from rffm_scraper.config import load_settings


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RFFM clubs enrichment (identity/address, one team per club)")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--scope", default=None, help="Category to enrich (defaults to config's clubs.scope_category)")
    parser.add_argument("--force-refetch", action="store_true", help="Ignore cached raw HTML and refetch every club")
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

    summary = run_club_enrichment(settings, scope_category=args.scope, force_refetch=args.force_refetch or None)
    print("\n=== clubs enrichment summary ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
