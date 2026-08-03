#!/usr/bin/env python3
"""
Stadium & Club Analyzer for RFFM 2025-2026 Season
Analyzes matches, teams, competitions at venues
"""

import pandas as pd
from pathlib import Path
from collections import Counter
from typing import Optional, Dict, List
import sys

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm" / "2025-2026"

# Load data once
venues_df = pd.read_csv(BASE_DIR / "venues.csv")
matches_df = pd.read_csv(BASE_DIR / "matches.csv")
teams_df = pd.read_csv(BASE_DIR / "teams.csv")
competitions_df = pd.read_csv(BASE_DIR / "competitions.csv")
clubs_df = pd.read_csv(BASE_DIR / "clubs.csv")


def find_venue(search_term: str) -> Optional[Dict]:
    """Find venue by name (partial match)"""
    results = venues_df[venues_df['venue_name'].str.contains(search_term, case=False, na=False)]
    if len(results) == 0:
        return None
    return results.iloc[0].to_dict()


def find_team(search_term: str) -> Optional[Dict]:
    """Find team by name (partial match)"""
    results = teams_df[teams_df['team_name_raw'].str.contains(search_term, case=False, na=False)]
    if len(results) == 0:
        return None
    return results.iloc[0].to_dict()


def analyze_venue(venue_id: int) -> Dict:
    """Analyze all matches at a specific venue"""
    venue_info = venues_df[venues_df['venue_id'] == venue_id]
    if len(venue_info) == 0:
        return {"error": f"Venue {venue_id} not found"}

    venue = venue_info.iloc[0]
    venue_matches = matches_df[matches_df['venue_id'] == venue_id]

    if len(venue_matches) == 0:
        return {
            "venue_id": venue_id,
            "venue_name": venue['venue_name'],
            "address": venue['address'],
            "matches": 0,
            "error": "No matches found"
        }

    # Get all teams (home and away)
    home_teams = venue_matches['home_team_id'].tolist()
    away_teams = venue_matches['away_team_id'].tolist()
    all_team_ids = home_teams + away_teams
    team_counts = Counter(all_team_ids)

    # Get team details
    top_teams = []
    for team_id, count in team_counts.most_common(12):
        team_info = teams_df[teams_df['team_id'] == team_id]
        if len(team_info) > 0:
            top_teams.append({
                "team_id": team_id,
                "team_name": team_info.iloc[0]['team_name_raw'],
                "matches": count
            })

    # Competitions summary
    comp_summary = venue_matches.groupby(['category', 'competition', 'game_type']).size().reset_index(name='count')
    comp_list = []
    for _, row in comp_summary.iterrows():
        comp_info = competitions_df[competitions_df['competition_id'] == row['competition']]
        comp_name = comp_info.iloc[0]['competition'] if len(comp_info) > 0 else 'Unknown'
        comp_list.append({
            "category": row['category'],
            "competition": comp_name,
            "game_type": row['game_type'],
            "matches": int(row['count'])
        })

    return {
        "venue_id": int(venue_id),
        "venue_name": venue['venue_name'],
        "address": venue['address'],
        "locality": venue['locality'],
        "field_type": venue['field_type_raw'],
        "surface": venue['surface_raw'],
        "total_matches": len(venue_matches),
        "unique_teams": len(team_counts),
        "top_teams": top_teams,
        "competitions": sorted(comp_list, key=lambda x: x['matches'], reverse=True)
    }


def analyze_team(team_id: int) -> Dict:
    """Analyze all matches for a specific team"""
    team_info = teams_df[teams_df['team_id'] == team_id]
    if len(team_info) == 0:
        return {"error": f"Team {team_id} not found"}

    team = team_info.iloc[0]

    # Get home and away matches
    home_matches = matches_df[matches_df['home_team_id'] == team_id]
    away_matches = matches_df[matches_df['away_team_id'] == team_id]

    total_matches = len(home_matches) + len(away_matches)
    if total_matches == 0:
        return {
            "team_id": team_id,
            "team_name": team['team_name_raw'],
            "error": "No matches found"
        }

    # Calculate stats
    home_wins = len(home_matches[home_matches['home_score'] > home_matches['away_score']])
    home_draws = len(home_matches[home_matches['home_score'] == home_matches['away_score']])
    home_losses = len(home_matches[home_matches['home_score'] < home_matches['away_score']])

    away_wins = len(away_matches[away_matches['away_score'] > away_matches['home_score']])
    away_draws = len(away_matches[away_matches['away_score'] == away_matches['home_score']])
    away_losses = len(away_matches[away_matches['away_score'] < away_matches['home_score']])

    total_wins = home_wins + away_wins
    total_draws = home_draws + away_draws
    total_losses = home_losses + away_losses

    # Venues
    all_matches = pd.concat([home_matches, away_matches])
    venue_counts = all_matches['venue_id'].value_counts()

    venues_list = []
    for venue_id, count in venue_counts.head(5).items():
        venue_info = venues_df[venues_df['venue_id'] == venue_id]
        if len(venue_info) > 0:
            venues_list.append({
                "venue_id": int(venue_id),
                "venue_name": venue_info.iloc[0]['venue_name'],
                "matches": int(count)
            })

    return {
        "team_id": int(team_id),
        "team_name": team['team_name_raw'],
        "total_matches": total_matches,
        "home_matches": len(home_matches),
        "away_matches": len(away_matches),
        "stats": {
            "wins": total_wins,
            "draws": total_draws,
            "losses": total_losses,
            "home": {
                "wins": home_wins,
                "draws": home_draws,
                "losses": home_losses
            },
            "away": {
                "wins": away_wins,
                "draws": away_draws,
                "losses": away_losses
            }
        },
        "top_venues": venues_list
    }


def compare_venues(venue_ids: List[int]) -> Dict:
    """Compare multiple venues side by side"""
    results = []
    for venue_id in venue_ids:
        results.append(analyze_venue(venue_id))
    return {"venues": results}


def print_venue_report(analysis: Dict):
    """Pretty print venue analysis"""
    if "error" in analysis:
        print(f"❌ Error: {analysis['error']}")
        return

    print(f"\n{'='*100}")
    print(f"📍 {analysis['venue_name']}")
    print(f"{'='*100}")
    print(f"   Address: {analysis['address']}, {analysis['locality']}")
    print(f"   Field Type: {analysis['field_type']} | Surface: {analysis['surface']}")
    print(f"\n📊 STATISTICS")
    print(f"   Total Matches: {analysis['total_matches']}")
    print(f"   Unique Teams: {analysis['unique_teams']}")

    print(f"\n🏆 TOP 12 CLUBS BY MATCHES")
    print(f"   {'-'*85}")
    for i, team in enumerate(analysis['top_teams'], 1):
        print(f"   {i:2}. {team['team_name']:60} - {team['matches']:2} matches")

    print(f"\n⚽ COMPETITIONS")
    print(f"   {'-'*85}")
    for comp in analysis['competitions']:
        print(f"   {comp['category']:12} | {comp['competition']:40} | {comp['game_type']:12} | {comp['matches']:2} matches")
    print()


def print_team_report(analysis: Dict):
    """Pretty print team analysis"""
    if "error" in analysis:
        print(f"❌ Error: {analysis['error']}")
        return

    print(f"\n{'='*100}")
    print(f"⚽ {analysis['team_name']}")
    print(f"{'='*100}")
    print(f"   Total Matches: {analysis['total_matches']}")
    print(f"   Home/Away: {analysis['home_matches']} / {analysis['away_matches']}")

    stats = analysis['stats']
    print(f"\n📊 STATISTICS")
    print(f"   Overall: {stats['wins']}-{stats['draws']}-{stats['losses']} (W-D-L)")
    print(f"   Home:    {stats['home']['wins']}-{stats['home']['draws']}-{stats['home']['losses']}")
    print(f"   Away:    {stats['away']['wins']}-{stats['away']['draws']}-{stats['away']['losses']}")

    print(f"\n🏟️  TOP VENUES")
    print(f"   {'-'*85}")
    for venue in analysis['top_venues']:
        print(f"   {venue['venue_name']:60} - {venue['matches']:2} matches")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python stadium_analyzer.py venue <venue_id>")
        print("  python stadium_analyzer.py venue-name <name_substring>")
        print("  python stadium_analyzer.py team <team_id>")
        print("  python stadium_analyzer.py team-name <name_substring>")
        print("  python stadium_analyzer.py compare <venue_id1> <venue_id2> [<venue_id3>...]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "venue" and len(sys.argv) > 2:
        venue_id = int(sys.argv[2])
        analysis = analyze_venue(venue_id)
        print_venue_report(analysis)

    elif command == "venue-name" and len(sys.argv) > 2:
        search = " ".join(sys.argv[2:])
        venue = find_venue(search)
        if venue is None:
            print(f"❌ Venue not found: {search}")
        else:
            analysis = analyze_venue(venue['venue_id'])
            print_venue_report(analysis)

    elif command == "team" and len(sys.argv) > 2:
        team_id = int(sys.argv[2])
        analysis = analyze_team(team_id)
        print_team_report(analysis)

    elif command == "team-name" and len(sys.argv) > 2:
        search = " ".join(sys.argv[2:])
        team = find_team(search)
        if team is None:
            print(f"❌ Team not found: {search}")
        else:
            analysis = analyze_team(team['team_id'])
            print_team_report(analysis)

    elif command == "compare" and len(sys.argv) > 3:
        venue_ids = [int(v) for v in sys.argv[2:]]
        comparison = compare_venues(venue_ids)
        for analysis in comparison['venues']:
            print_venue_report(analysis)

    else:
        print(f"❌ Invalid command or missing arguments: {command}")
        sys.exit(1)
