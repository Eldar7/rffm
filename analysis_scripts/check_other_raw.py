#!/usr/bin/env python3
"""Check raw competition names for OTHER"""

import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm" / "2025-2026"

matches_df = pd.read_csv(BASE_DIR / "matches.csv")
competitions_df = pd.read_csv(BASE_DIR / "competitions.csv")

# Get PREBENJAMIN
prebenjamin = matches_df[matches_df['category'].str.upper() == 'PREBENJAMIN'].copy()

# Merge with competitions
prebenjamin_with_comp = prebenjamin.merge(
    competitions_df[['competition_id', 'division_level', 'category_label_raw', 'competition']],
    on='competition_id',
    how='left'
)

# Filter to OTHER
other_matches = prebenjamin_with_comp[prebenjamin_with_comp['division_level'] == 'OTHER']

print("=" * 100)
print("OTHER Division - What competitions are inside?")
print("=" * 100)
print()

print(f"Total OTHER matches: {len(other_matches)}")
print()

print("Competition names (from competitions.csv 'competition' column):")
print("-" * 100)

comp_counts = other_matches['competition'].value_counts()
if len(comp_counts) == 0 or comp_counts.isna().all():
    print("  ⚠️  All empty/NaN!")
    print()
    print("  Sample rows:")
    for idx, row in other_matches[['competition_id', 'competition', 'category_label_raw']].head(10).iterrows():
        print(f"    competition_id={row['competition_id']}, competition='{row['competition']}', raw='{row['category_label_raw']}'")
else:
    for comp, count in comp_counts.head(20).items():
        pct = (count / len(other_matches)) * 100
        print(f"  {comp:70} - {count:5} matches ({pct:6.1f}%)")

print()
print("=" * 100)
print("What's in competitions.csv for OTHER competitions?")
print("=" * 100)
print()

# Get competition IDs from OTHER matches
other_comp_ids = other_matches['competition_id'].unique()
other_comps_full = competitions_df[competitions_df['competition_id'].isin(other_comp_ids)]

print(f"Total unique competition_id in OTHER: {len(other_comp_ids)}")
print()

print("Full competition records:")
print("-" * 100)

cols_to_show = ['competition_id', 'division_level', 'category_label_raw', 'competition', 'phase_label']
for idx, row in other_comps_full[cols_to_show].head(15).iterrows():
    print(f"ID: {row['competition_id']}")
    print(f"  Division: {row['division_level']}")
    print(f"  Raw Category: {row['category_label_raw']}")
    print(f"  Competition: {row['competition']}")
    print(f"  Phase: {row['phase_label']}")
    print()
