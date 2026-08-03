#!/usr/bin/env python3
"""Analyze PREBENJAMÍN match schedule - days and times"""

import pandas as pd
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm" / "2025-2026"

matches_df = pd.read_csv(BASE_DIR / "matches.csv")

# Get all PREBENJAMIN matches
prebenjamin = matches_df[matches_df['category'].str.upper() == 'PREBENJAMIN'].copy()

# Convert date to datetime
prebenjamin['match_date_dt'] = pd.to_datetime(prebenjamin['match_date'])
prebenjamin['day_of_week'] = prebenjamin['match_date_dt'].dt.day_name()
prebenjamin['time'] = prebenjamin['match_time'].str.extract(r'(\d{2}:\d{2})')

print("PREBENJAMÍN - Days of Week Distribution:")
print("=" * 80)

# Order days properly
day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
day_counts = prebenjamin['day_of_week'].value_counts()

for day in day_order:
    if day in day_counts.index:
        count = day_counts[day]
        pct = (count / len(prebenjamin)) * 100
        print(f"  {day:12} - {count:5} matches ({pct:6.1f}%)")

print()
print("PREBENJAMÍN - Match Times Distribution:")
print("=" * 80)

time_counts = prebenjamin['time'].value_counts().sort_index()
for time, count in time_counts.head(15).items():
    pct = (count / len(prebenjamin)) * 100
    print(f"  {time} - {count:5} matches ({pct:6.1f}%)")

print()
print("PREBENJAMÍN - Day + Time Combinations (Top 20):")
print("=" * 80)

prebenjamin['day_time'] = prebenjamin['day_of_week'] + ' ' + prebenjamin['time']
day_time_counts = prebenjamin['day_time'].value_counts().head(20)

for day_time, count in day_time_counts.items():
    pct = (count / len(prebenjamin)) * 100
    print(f"  {day_time:25} - {count:5} matches ({pct:6.1f}%)")

print()
print("PREBENJAMÍN - Date Range:")
print("=" * 80)
print(f"  First match: {prebenjamin['match_date_dt'].min().strftime('%Y-%m-%d %A')}")
print(f"  Last match:  {prebenjamin['match_date_dt'].max().strftime('%Y-%m-%d %A')}")
print(f"  Total span:  {(prebenjamin['match_date_dt'].max() - prebenjamin['match_date_dt'].min()).days} days")
