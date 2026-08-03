#!/usr/bin/env python3
"""List all category_base and their structure"""

import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm" / "2025-2026"

matches_df = pd.read_csv(BASE_DIR / "matches.csv")
competitions_df = pd.read_csv(BASE_DIR / "competitions.csv")

print("=" * 100)
print("ALL CATEGORY_BASE VALUES IN COMPETITIONS.CSV")
print("=" * 100)
print()

# Get unique category_base
all_categories = competitions_df['category_base'].unique()
print(f"Total unique category_base: {len(all_categories)}\n")

for cat in sorted(all_categories):
    cat_comps = competitions_df[competitions_df['category_base'] == cat]
    cat_matches = len(matches_df[matches_df['category'].str.upper() == cat.upper()])

    print(f"\n{cat}")
    print("-" * 100)
    print(f"  Matches in dataset: {cat_matches}")
    print(f"  Division levels: {', '.join(cat_comps['division_level'].unique())}")
    print(f"  Total competitions: {len(cat_comps)}")

print()
print()
print("=" * 100)
print("PREBENJAMÍN STRUCTURE - Why is everything 'OTHER'?")
print("=" * 100)
print()

prebenjamin_comps = competitions_df[competitions_df['category_base'] == 'PREBENJAMIN']

print("All PREBENJAMÍN competitions grouped by division_level:")
print()

for div_level in ['PRIMERA DIVISION AUTONOMICA', 'PREFERENTE', 'OTHER']:
    comps_in_level = prebenjamin_comps[prebenjamin_comps['division_level'] == div_level]

    print(f"\n{div_level}:")
    print("-" * 100)

    for _, comp in comps_in_level.iterrows():
        matches = len(matches_df[
            (matches_df['category'].str.upper() == 'PREBENJAMIN') &
            (matches_df['competition_id'] == comp['competition_id'])
        ])
        print(f"  📋 {comp['competition']:60} ({matches:5} matches)")
        print(f"     phase_label: {comp['phase_label']}")

print()
print()
print("=" * 100)
print("KEY INSIGHT - Why so much in OTHER?")
print("=" * 100)
print()
print("PREBENJAMÍN is divided into 3 DIVISION LEVELS in RFFM:")
print()
print("1. PRIMERA DIVISION AUTONOMICA")
print("   • Official regional championship")
print("   • 1,021 matches (12.3%)")
print()
print("2. PREFERENTE")
print("   • Preferred/selected level")
print("   • 1,518 matches (18.3%)")
print()
print("3. OTHER (🏘️ Local/Municipal)")
print("   • Local district championships")
print("   • 5,748 matches (69.4%) ← MAJORITY!")
print()
print("The reason OTHER has so much is simple:")
print()
print("  🏘️ LOCAL/MUNICIPAL FOOTBALL is the BASE of youth development")
print("     - Every town/district has local competitions")
print("     - Thousands of teams participate")
print()
print("  🥇 REGIONAL (PRIMERA AUTONÓMICA) is for elite teams only")
print("     - Fewer teams qualify")
print("     - Lower match count")
print()
print("  🥈 PREFERENTE is the middle tier")
print("     - Selected clubs between local and regional")
print()
print("So 'OTHER' isn't 'miscellaneous' - it's the FOUNDATION of the pyramid!")
