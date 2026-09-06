"""One-time offline backfill for the phase_label bug fixed in
rffm_scraper/normalize.py (see DATA_FINDINGS.md's "Systematic audit" entry,
'2ª FASE misclassification' sub-section, for the full diagnosis).

phase_label is a pure function of a competition's already-collected raw
name (the `competition` column, verbatim in both competitions.csv and
matches.csv - see normalize.py's phase_label_from_competition_name()). The
bug was in that function, not in the crawl itself, so every already-crawled
season can be corrected by recomputing phase_label from the `competition`
column already on disk - no live fetch, no re-crawl.

Rewrites output/processed/rffm/<season>/{competitions,matches}.csv IN
PLACE, touching only the phase_label field of rows whose recomputed value
differs from what's stored - every other byte of every other row is
preserved exactly (verified: a raw csv.reader/writer round-trip with
lineterminator="\\n" and encoding="utf-8-sig" reproduces the file
byte-for-byte, so the only diff this script produces is the actual field
changes). Does not touch scraped_at - this is a correctness fix to already-
collected data, not a new crawl.

After running this, rebuild the Parquet copies:
    python analysis_scripts/build_parquet.py --output-dir output/processed/rffm_parquet

Run: python analysis_scripts/backfill_phase_label.py [--dry-run]
"""

import argparse
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rffm_scraper.normalize import phase_label_from_competition_name

ROOT = "output/processed/rffm"


def backfill_file(path: str, competition_col: str, phase_col: str, dry_run: bool) -> int:
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    header = rows[0]
    comp_idx = header.index(competition_col)
    phase_idx = header.index(phase_col)

    changed = 0
    for row in rows[1:]:
        new_label = phase_label_from_competition_name(row[comp_idx])
        if row[phase_idx] != new_label:
            row[phase_idx] = new_label
            changed += 1

    if changed and not dry_run:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)

    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report counts, don't write")
    args = parser.parse_args()

    total = 0
    for season_dir in sorted(glob.glob(os.path.join(ROOT, "*"))):
        if not os.path.isdir(season_dir):
            continue
        season = os.path.basename(season_dir)

        comp_path = os.path.join(season_dir, "competitions.csv")
        if os.path.exists(comp_path):
            n = backfill_file(comp_path, "competition", "phase_label", args.dry_run)
            if n:
                print(f"{season}/competitions.csv: {n} rows corrected")
                total += n

        matches_path = os.path.join(season_dir, "matches.csv")
        if os.path.exists(matches_path):
            n = backfill_file(matches_path, "competition", "phase_label", args.dry_run)
            if n:
                print(f"{season}/matches.csv: {n} rows corrected")
                total += n

    verb = "would be" if args.dry_run else "were"
    print(f"\nTotal: {total} rows {verb} corrected.")
    if not args.dry_run and total:
        print("Now rebuild the Parquet copies: "
              "python analysis_scripts/build_parquet.py --output-dir output/processed/rffm_parquet")


if __name__ == "__main__":
    main()
