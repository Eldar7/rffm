#!/usr/bin/env python3
"""Check what game formats PREBENJAMÍN uses"""

import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm" / "2025-2026"

matches_df = pd.read_csv(BASE_DIR / "matches.csv")

# Get all PREBENJAMIN matches
prebenjamin = matches_df[matches_df['category'].str.upper() == 'PREBENJAMIN']

print("PREBENJAMÍN - Game Type Distribution:")
print("=" * 80)

game_type_counts = prebenjamin['game_type'].value_counts()
for game_type, count in game_type_counts.items():
    pct = (count / len(prebenjamin)) * 100
    print(f"  {game_type:15} - {count:5} matches ({pct:6.1f}%)")

print()
print(f"Total PREBENJAMÍN matches: {len(prebenjamin)}")
print()

# Also check by venue type
print("PREBENJAMÍN - Venue Field Types:")
print("=" * 80)

venues_df = pd.read_csv(BASE_DIR / "venues.csv")
venue_ids = prebenjamin['venue_id'].unique()
venues_at_prebenjamin = venues_df[venues_df['venue_id'].isin(venue_ids)]

field_type_counts = venues_at_prebenjamin['field_type_raw'].value_counts()
for field_type, count in field_type_counts.items():
    pct = (count / len(venues_at_prebenjamin)) * 100
    print(f"  {field_type:15} - {count:3} venues")

print()
print("Sample PREBENJAMÍN matches with field types:")
print("=" * 80)

sample = prebenjamin.head(10).copy()
sample = sample.merge(venues_df[['venue_id', 'venue_name', 'field_type_raw']], on='venue_id')

for _, match in sample.iterrows():
    print(f"  {match['game_type']:12} | {match['field_type_raw']:15} | {match['venue_name']}")
