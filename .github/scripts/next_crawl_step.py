"""Print the next crawl step that hasn't been completed yet.

Reads coverage_manifest.csv and compares it against the full ordered plan.
Prints one line to stdout: "season_label|stage|scope_category|all_categories"
or nothing if everything is done.

Exit codes:
  0 — step found and printed
  1 — all done (nothing to print)
  2 — usage/file error
"""
from __future__ import annotations

import csv
import os
import sys

MANIFEST_PATH = "output/processed/rffm/coverage_manifest.csv"

# Enrichment categories in priority order (OTHER skipped — cup/copa competitions
# have no meaningful acta/fichajugador data worth crawling at scale).
ENRICH_CATEGORIES = [
    "BENJAMIN", "PREBENJAMIN", "ALEVIN", "INFANTIL",
    "CADETE", "JUVENIL", "AFICIONADO", "SENIOR", "VETERANOS", "UNIVERSITARIO",
]

# Seasons newest-first. core uses --all-categories for every season so that
# old seasons (2018-2023, previously crawled with only BENJAMIN+PREBENJAMIN)
# get the full category set on re-crawl.
SEASONS = [
    "2025-2026",
    "2024-2025",
    "2023-2024",
    "2022-2023",
    "2021-2022",
    "2020-2021",
    "2019-2020",
    "2018-2019",
]

# Full ordered plan: for each season, the complete sequence of steps.
# core first (all-categories), then clubs, then per-category enrich stages.
def build_plan() -> list[dict]:
    steps = []
    for season in SEASONS:
        steps.append({"season": season, "stage": "core", "scope": "", "all_categories": True})
        steps.append({"season": season, "stage": "clubs", "scope": "", "all_categories": False})
        for cat in ENRICH_CATEGORIES:
            steps.append({"season": season, "stage": "acta_partido", "scope": cat, "all_categories": False})
        for cat in ENRICH_CATEGORIES:
            steps.append({"season": season, "stage": "fichajugador", "scope": cat, "all_categories": False})
    return steps


def _seasons_needing_core_recrawl() -> set[str]:
    """Seasons whose groups.csv has only BENJAMIN+PREBENJAMIN — core was run
    without --all-categories and must be re-crawled to get full coverage."""
    limited = set()
    groups_glob = os.path.join(
        os.path.dirname(MANIFEST_PATH), "*", "groups.csv"
    )
    import glob
    for path in glob.glob(groups_glob):
        season = os.path.basename(os.path.dirname(path))
        with open(path, newline="", encoding="utf-8") as f:
            cats = {r["category"] for r in csv.DictReader(f) if r.get("category")}
        real_cats = cats - {"OTHER"}
        if real_cats and real_cats <= {"BENJAMIN", "PREBENJAMIN"}:
            limited.add(season)
    return limited


def load_done() -> set[tuple[str, str, str]]:
    """Return set of (season, stage, scope) that are complete or complete_with_failures.

    Core entries for seasons that were crawled with only BENJAMIN+PREBENJAMIN
    are excluded so the orchestrator re-crawls them with --all-categories.
    """
    needs_core_recrawl = _seasons_needing_core_recrawl()

    done: set[tuple[str, str, str]] = set()
    if not os.path.exists(MANIFEST_PATH):
        return done
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status", "") in ("complete", "complete_with_failures"):
                scope = row.get("category_base", "")
                if row["stage"] in ("core", "clubs"):
                    scope = "ALL"
                if row["stage"] == "core" and row["season"] in needs_core_recrawl:
                    continue  # force re-crawl with --all-categories
                done.add((row["season"], row["stage"], scope))
    return done


def manifest_scope(step: dict) -> str:
    """The category_base value as stored in coverage_manifest for this step."""
    if step["stage"] in ("core", "clubs"):
        return "ALL"
    return step["scope"]


def main() -> int:
    plan = build_plan()
    done = load_done()
    total = len(plan)
    done_count = sum(1 for s in plan if (s["season"], s["stage"], manifest_scope(s)) in done)
    for step in plan:
        key = (step["season"], step["stage"], manifest_scope(step))
        if key not in done:
            print(f"{step['season']}|{step['stage']}|{step['scope']}|{str(step['all_categories']).lower()}|{done_count}|{total}")
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
