#!/usr/bin/env python3
"""CLI entrypoint for the fichajugador (player profile) enrichment stage.

Off by default - robots.txt disallows /fichajugador/. Requires
`enrichment.fetch_fichajugador: true` in config.yaml as an explicit,
informed opt-in (checked again here as a second guard). Reads targets from
output/processed/rffm/<season>/match_lineups/<category>.csv, produced by `python enrich_acta.py`
- run that first.

Usage:
    python enrich_players.py [--config config.yaml] [--scope PREBENJAMIN]
                              [--force-refetch] [--log-level INFO]
"""
from __future__ import annotations

import argparse
import logging
import sys

from rffm_scraper.config import load_settings
from rffm_scraper.player_pipeline import run_player_enrichment


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RFFM fichajugador enrichment (player profiles/season stats/participation)")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--scope", default=None, help="Category label used for the raw-cache path (defaults to config's fichajugador.scope_category)")
    parser.add_argument("--force-refetch", action="store_true", help="Ignore cached raw HTML and refetch every player")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = load_settings(args.config)

    if not settings.enrichment.fetch_fichajugador:
        print(
            "enrichment.fetch_fichajugador is false in config.yaml - refusing to run.\n"
            "This stage crawls /fichajugador/, which robots.txt disallows; set it to "
            "true only as a deliberate, informed opt-in.",
            file=sys.stderr,
        )
        return 1

    summary = run_player_enrichment(settings, scope_category=args.scope, force_refetch=args.force_refetch or None)
    print("\n=== fichajugador enrichment summary ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
