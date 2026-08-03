#!/usr/bin/env python3
"""Explain what OTHER division means for PREBENJAMÍN"""

import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm" / "2025-2026"

matches_df = pd.read_csv(BASE_DIR / "matches.csv")
competitions_df = pd.read_csv(BASE_DIR / "competitions.csv")

print("=" * 100)
print("PREBENJAMÍN - THREE DIVISIONS EXPLAINED")
print("=" * 100)
print()

# Get all PREBENJAMÍN competitions
all_prebenjamin_comps = competitions_df[competitions_df['category_base'] == 'PREBENJAMIN'].copy()

divisions = [
    ('PRIMERA DIVISION AUTONOMICA', '🥇 Regional/Autonomous Competition'),
    ('PREFERENTE', '🥈 Preferred/Selected Competition'),
    ('OTHER', '🏘️  Local/District Competition'),
]

for div_level, description in divisions:
    comps = all_prebenjamin_comps[all_prebenjamin_comps['division_level'] == div_level]

    print(f"\n{div_level}")
    print(f"{description}")
    print("-" * 100)

    print(f"Total competitions: {len(comps)}\n")

    for idx, comp in comps.iterrows():
        matches_count = len(matches_df[
            (matches_df['category'].str.upper() == 'PREBENJAMIN') &
            (matches_df['competition_id'] == comp['competition_id'])
        ])
        print(f"  📋 {comp['competition']:60} ({matches_count:4} matches)")

print()
print("=" * 100)
print("KEY INSIGHT")
print("=" * 100)
print()
print("OTHER = Municipales/Locales (District Competitions)")
print()
print("It's NOT 'miscellaneous' - it's a specific category in RFFM:")
print("  • PRIMERA DIVISIÓN AUTONÓMICA = Regional/Autonomous")
print("  • PREFERENTE = Preferred (mid-level)")
print("  • OTHER = Local/Municipal (district-level)")
print()
print("So 'OTHER' for PREBENJAMÍN means LOCAL YOUTH FOOTBALL competitions.")
