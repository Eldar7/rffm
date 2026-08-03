#!/usr/bin/env python3
"""Detailed analysis of PREBENJAMÍN Saturday schedule"""

import pandas as pd
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm" / "2025-2026"

matches_df = pd.read_csv(BASE_DIR / "matches.csv")
competitions_df = pd.read_csv(BASE_DIR / "competitions.csv")

# Get all PREBENJAMIN matches
prebenjamin = matches_df[matches_df['category'].str.upper() == 'PREBENJAMIN'].copy()

# Convert date to datetime
prebenjamin['match_date_dt'] = pd.to_datetime(prebenjamin['match_date'])
prebenjamin['day_of_week'] = prebenjamin['match_date_dt'].dt.day_name()
prebenjamin['time'] = prebenjamin['match_time'].str.extract(r'(\d{2}:\d{2})')

# Split by days
friday = prebenjamin[prebenjamin['day_of_week'] == 'Friday'].copy()
saturday = prebenjamin[prebenjamin['day_of_week'] == 'Saturday'].copy()

print("=" * 100)
print("PREBENJAMÍN - FRIDAY vs SATURDAY BREAKDOWN")
print("=" * 100)
print()

print(f"FRIDAY:   {len(friday):5} matches (63.7%)")
print(f"SATURDAY: {len(saturday):5} matches (26.1%)")
print()

# Saturday times
print("SATURDAY - Times Distribution:")
print("-" * 100)

sat_times = saturday['time'].value_counts().sort_index()
for time, count in sat_times.items():
    pct = (count / len(saturday)) * 100
    print(f"  {time} - {count:4} matches ({pct:6.1f}%)")

print()
print("=" * 100)
print("SATURDAY - By Division/Competition")
print("=" * 100)
print()

# Get division level for Saturday matches
sat_with_div = saturday.merge(
    competitions_df[['competition_id', 'division_level']],
    on='competition_id',
    how='left'
)

# Division level distribution
print("SATURDAY - By Division Level:")
print("-" * 100)

div_counts = sat_with_div['division_level'].value_counts()
for div, count in div_counts.items():
    pct = (count / len(saturday)) * 100
    print(f"  {div:30} - {count:4} matches ({pct:6.1f}%)")

print()
print("SATURDAY - By Competition Name (Top 15):")
print("-" * 100)

comp_counts = saturday['competition'].value_counts().head(15)
for comp, count in comp_counts.items():
    pct = (count / len(saturday)) * 100
    print(f"  {comp:60} - {count:4} matches ({pct:6.1f}%)")

print()
print("=" * 100)
print("FRIDAY - By Division/Competition")
print("=" * 100)
print()

# Get division level for Friday matches
fri_with_div = friday.merge(
    competitions_df[['competition_id', 'division_level']],
    on='competition_id',
    how='left'
)

# Division level distribution
print("FRIDAY - By Division Level:")
print("-" * 100)

div_counts = fri_with_div['division_level'].value_counts()
for div, count in div_counts.items():
    pct = (count / len(friday)) * 100
    print(f"  {div:30} - {count:4} matches ({pct:6.1f}%)")

print()
print("FRIDAY - By Competition Name (Top 15):")
print("-" * 100)

comp_counts = friday['competition'].value_counts().head(15)
for comp, count in comp_counts.items():
    pct = (count / len(friday)) * 100
    print(f"  {comp:60} - {count:4} matches ({pct:6.1f}%)")

print()
print("=" * 100)
print("COMPARISON - Friday vs Saturday by Division Level")
print("=" * 100)
print()

print(f"{'Division Level':<35} {'Friday':>12} {'Saturday':>12} {'Total':>12}")
print("-" * 100)

all_divs = set(fri_with_div['division_level'].unique()) | set(sat_with_div['division_level'].unique())
for div in sorted(all_divs):
    fri_count = len(fri_with_div[fri_with_div['division_level'] == div])
    sat_count = len(sat_with_div[sat_with_div['division_level'] == div])
    total = fri_count + sat_count

    fri_pct = (fri_count / len(friday)) * 100 if fri_count > 0 else 0
    sat_pct = (sat_count / len(saturday)) * 100 if sat_count > 0 else 0

    print(f"{div:<35} {fri_count:5} ({fri_pct:4.1f}%) {sat_count:5} ({sat_pct:4.1f}%) {total:5}")

print()
print("=" * 100)
print("TIME PATTERNS - Which divisions at what times on SATURDAY")
print("=" * 100)
print()

saturday_time_div = saturday.merge(
    competitions_df[['competition_id', 'division_level']],
    on='competition_id',
    how='left'
)

saturday_time_div['time_div'] = saturday_time_div['time'] + ' - ' + saturday_time_div['division_level']
time_div_counts = saturday_time_div['time_div'].value_counts().sort_index().head(20)

for time_div, count in time_div_counts.items():
    print(f"  {time_div:45} - {count:4} matches")
