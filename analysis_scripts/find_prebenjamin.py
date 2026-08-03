#!/usr/bin/env python3
"""Find PREBENJAMÍN venues for specific clubs"""

import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm" / "2025-2026"

matches_df = pd.read_csv(BASE_DIR / "matches.csv")
teams_df = pd.read_csv(BASE_DIR / "teams.csv")
venues_df = pd.read_csv(BASE_DIR / "venues.csv")

# Find PREBENJAMIN matches
prebenjamin_matches = matches_df[matches_df['category'].str.upper() == 'PREBENJAMIN']

print(f"Total PREBENJAMÍN matches in dataset: {len(prebenjamin_matches)}")
print()

# Find teams for ARAVACA C.F. - CEIBA
ceiba_teams = teams_df[teams_df['team_name_raw'].str.contains('ARAVACA.*CEIBA', case=False, regex=True, na=False)]
union_teams = teams_df[teams_df['team_name_raw'].str.contains('UNION DE ARAVACA', case=False, na=False)]

print("=" * 80)
print("ARAVACA C.F. - CEIBA - Teams in system:")
print("=" * 80)
ceiba_ids = []
for _, team in ceiba_teams.iterrows():
    ceiba_ids.append(team['team_id'])
    print(f"  ID: {team['team_id']:8} - {team['team_name_raw']}")

print("\n" + "=" * 80)
print("C.D. UNIÓN DE ARAVACA - Teams in system:")
print("=" * 80)
union_ids = []
for _, team in union_teams.iterrows():
    union_ids.append(team['team_id'])
    print(f"  ID: {team['team_id']:8} - {team['team_name_raw']}")

# Get PREBENJAMÍN matches for ARAVACA C.F. - CEIBA
print("\n" + "=" * 80)
print("PREBENJAMÍN VENUES - ARAVACA C.F. - CEIBA")
print("=" * 80)

ceiba_prebenjamin = prebenjamin_matches[
    (prebenjamin_matches['home_team_id'].isin(ceiba_ids)) |
    (prebenjamin_matches['away_team_id'].isin(ceiba_ids))
]

if len(ceiba_prebenjamin) > 0:
    print(f"Total PREBENJAMÍN matches: {len(ceiba_prebenjamin)}\n")

    # Get unique venues
    venue_counts = {}
    for _, match in ceiba_prebenjamin.iterrows():
        venue_id = match['venue_id']
        if venue_id not in venue_counts:
            venue_counts[venue_id] = 0
        venue_counts[venue_id] += 1

    for venue_id, count in sorted(venue_counts.items(), key=lambda x: x[1], reverse=True):
        venue_info = venues_df[venues_df['venue_id'] == venue_id]
        if len(venue_info) > 0:
            v = venue_info.iloc[0]
            print(f"  {v['venue_name']:60} - {count:2} matches")
else:
    print("  ❌ No PREBENJAMÍN matches found")

# Get PREBENJAMÍN matches for C.D. UNIÓN DE ARAVACA
print("\n" + "=" * 80)
print("PREBENJAMÍN VENUES - C.D. UNIÓN DE ARAVACA")
print("=" * 80)

union_prebenjamin = prebenjamin_matches[
    (prebenjamin_matches['home_team_id'].isin(union_ids)) |
    (prebenjamin_matches['away_team_id'].isin(union_ids))
]

if len(union_prebenjamin) > 0:
    print(f"Total PREBENJAMÍN matches: {len(union_prebenjamin)}\n")

    # Get unique venues
    venue_counts = {}
    for _, match in union_prebenjamin.iterrows():
        venue_id = match['venue_id']
        if venue_id not in venue_counts:
            venue_counts[venue_id] = 0
        venue_counts[venue_id] += 1

    for venue_id, count in sorted(venue_counts.items(), key=lambda x: x[1], reverse=True):
        venue_info = venues_df[venues_df['venue_id'] == venue_id]
        if len(venue_info) > 0:
            v = venue_info.iloc[0]
            print(f"  {v['venue_name']:60} - {count:2} matches")
else:
    print("  ❌ No PREBENJAMÍN matches found")

print()
