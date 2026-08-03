#!/usr/bin/env python3
"""Check what OTHER category contains in raw data"""

import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm" / "2025-2026"

matches_df = pd.read_csv(BASE_DIR / "matches.csv")
competitions_df = pd.read_csv(BASE_DIR / "competitions.csv")

# Get all PREBENJAMIN matches
prebenjamin = matches_df[matches_df['category'].str.upper() == 'PREBENJAMIN'].copy()

# Get OTHER division matches
prebenjamin_other = prebenjamin.merge(
    competitions_df[['competition_id', 'category_base', 'category_label_raw', 'division_level', 'competition']],
    on='competition_id',
    how='left'
)

# Filter to OTHER
other_matches = prebenjamin_other[prebenjamin_other['division_level'] == 'OTHER']

print("=" * 100)
print("PREBENJAMÍN - OTHER Division Analysis")
print("=" * 100)
print()

print("Total OTHER matches: {}\n".format(len(other_matches)))

print("Raw Category Labels (category_label_raw):")
print("-" * 100)

category_raw_counts = other_matches['category_label_raw'].value_counts()
for cat_raw, count in category_raw_counts.items():
    pct = (count / len(other_matches)) * 100
    print(f"  {cat_raw:60} - {count:5} matches ({pct:6.1f}%)")

print()
print("=" * 100)
print("Competition Names (for OTHER) - from matches.csv:")
print("-" * 100)

# Get the original matches columns
other_from_original = prebenjamin[prebenjamin.index.isin(other_matches.index)]
comp_counts = other_from_original['competition'].value_counts().head(20)
for comp, count in comp_counts.items():
    pct = (count / len(other_matches)) * 100
    print(f"  {comp:70} - {count:5} matches ({pct:6.1f}%)")

print()
print("=" * 100)
print("Category Base (for OTHER):")
print("-" * 100)

cat_base_counts = other_matches['category_base'].value_counts()
for cat_base, count in cat_base_counts.items():
    pct = (count / len(other_matches)) * 100
    print(f"  {cat_base:60} - {count:5} matches ({pct:6.1f}%)")

print()
print("=" * 100)
print("Sample matches from OTHER category:")
print("-" * 100)
print()

sample = prebenjamin[prebenjamin.index.isin(other_matches.index)][['competition', 'match_date', 'match_time', 'home_team', 'away_team']].head(10)
for idx, row in sample.iterrows():
    print(f"📋 {row['competition']}")
    print(f"   {row['match_date']} {row['match_time']}: {row['home_team']} vs {row['away_team']}")
    print()
