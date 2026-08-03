import pandas as pd
import numpy as np

season = '2025-2026'
matches_path = f'output/processed/rffm/{season}/matches.csv'
competitions_path = f'output/processed/rffm/{season}/competitions.csv'

matches = pd.read_csv(matches_path)
competitions = pd.read_csv(competitions_path)

matches = matches.merge(competitions[['competition_id', 'category_base']], on='competition_id', how='left')
prebenjamin = matches[matches['category_base'] == 'PREBENJAMIN'].copy()

# Get day of week
prebenjamin['match_date'] = pd.to_datetime(prebenjamin['match_date'])
prebenjamin['day_of_week'] = prebenjamin['match_date'].dt.day_name()

# Filter for Friday
friday_data = prebenjamin[prebenjamin['day_of_week'] == 'Friday'].copy()

print('=' * 120)
print('АНАЛИЗ СТАБИЛЬНОСТИ ВРЕМЁН ЗАПУСКА ДЛЯ КОМАНД ПО ПЯТНИЦАМ')
print('=' * 120)
print()

# Get all teams that play on Friday
friday_teams = set(friday_data['home_team_id'].unique()) | set(friday_data['away_team_id'].unique())

print(f'Всего команд, играющих по пятницам: {len(friday_teams)}')
print()

# For each team, analyze time distribution
team_time_stability = {}
team_time_counts = {}
team_game_counts = {}

for team_id in friday_teams:
    home_games = friday_data[friday_data['home_team_id'] == team_id]
    away_games = friday_data[friday_data['away_team_id'] == team_id]
    all_games = pd.concat([home_games, away_games])

    times = all_games['match_time'].dropna().unique()
    num_games = len(all_games)
    num_times = len(times)

    team_game_counts[team_id] = num_games
    team_time_counts[team_id] = num_times

    # Stability metric: 1.0 = идеально стабильна (одно время), 0.0 = хаос
    # Формула: если у команды N игр, и она играет в K разных времён,
    # то стабильность = 1 - (K-1)/(N-1)
    if num_games == 1:
        stability = 1.0
    else:
        stability = 1.0 - (num_times - 1) / (num_games - 1)

    team_time_stability[team_id] = stability

print('=' * 120)
print('ПРИМЕРЫ КОМАНД - РАЗНЫЙ УРОВЕНЬ СТАБИЛЬНОСТИ')
print('=' * 120)
print()

# Find examples of stable teams
stability_series = pd.Series(team_time_stability)
game_counts = pd.Series(team_game_counts)

# Super stable (одно время для всех игр)
super_stable = [t for t, s in team_time_stability.items() if s == 1.0 and game_counts[t] >= 3]
# Mostly stable (одно-два времени)
mostly_stable = [t for t, s in team_time_stability.items() if 0.7 <= s < 1.0 and game_counts[t] >= 3]
# Mixed (3+ разных времён)
mixed = [t for t, s in team_time_stability.items() if 0.3 <= s < 0.7 and game_counts[t] >= 3]
# Chaotic (много разных времён)
chaotic = [t for t, s in team_time_stability.items() if s < 0.3 and game_counts[t] >= 3]

print('🟢 СУПЕР-СТАБИЛЬНЫЕ (одно время для всех игр)')
print('-' * 120)
for idx, team_id in enumerate(super_stable[:5]):
    games = friday_data[(friday_data['home_team_id'] == team_id) | (friday_data['away_team_id'] == team_id)]
    times = games['match_time'].value_counts().sort_values(ascending=False)
    print(f'Team {team_id}: {game_counts[team_id]} игр')
    for time, count in times.items():
        print(f'  {time}: {count} матчей')
    print()

print('🟡 СТАБИЛЬНЫЕ (в основном одно время)')
print('-' * 120)
for idx, team_id in enumerate(mostly_stable[:5]):
    games = friday_data[(friday_data['home_team_id'] == team_id) | (friday_data['away_team_id'] == team_id)]
    times = games['match_time'].value_counts().sort_values(ascending=False)
    print(f'Team {team_id}: {game_counts[team_id]} игр, стабильность {team_time_stability[team_id]:.2f}')
    for time, count in times.items():
        pct = (count / game_counts[team_id]) * 100
        print(f'  {time}: {count} матчей ({pct:.1f}%)')
    print()

print('🟠 НЕСТАБИЛЬНЫЕ (разные времена)')
print('-' * 120)
for idx, team_id in enumerate(mixed[:5]):
    games = friday_data[(friday_data['home_team_id'] == team_id) | (friday_data['away_team_id'] == team_id)]
    times = games['match_time'].value_counts().sort_values(ascending=False)
    print(f'Team {team_id}: {game_counts[team_id]} игр, стабильность {team_time_stability[team_id]:.2f}')
    for time, count in times.items():
        pct = (count / game_counts[team_id]) * 100
        print(f'  {time}: {count} матчей ({pct:.1f}%)')
    print()

print('=' * 120)
print('РАСПРЕДЕЛЕНИЕ СТАБИЛЬНОСТИ ПО ВСЕМ КОМАНДАМ')
print('=' * 120)
print()

# Filter teams with at least 3 games
teams_with_multiple_games = [t for t, n in team_game_counts.items() if n >= 3]
stabilities = [team_time_stability[t] for t in teams_with_multiple_games]

print(f'Команды с 3+ играми: {len(teams_with_multiple_games)}')
print()

# Distribution
bins = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
bin_labels = ['0-10%', '10-20%', '20-30%', '30-40%', '40-50%', '50-60%', '60-70%', '70-80%', '80-90%', '90-100%']

print('Стабильность (вероятность играть в одно время):')
print('-' * 120)

for i in range(len(bins) - 1):
    low, high = bins[i], bins[i + 1]
    count = sum(1 for s in stabilities if low <= s < high) + (1 if high == 1.0 and sum(1 for s in stabilities if s == 1.0) > 0 else 0)

    if i == len(bins) - 2:  # last bin
        count = sum(1 for s in stabilities if low <= s <= high)

    pct = (count / len(teams_with_multiple_games)) * 100 if teams_with_multiple_games else 0
    bar = '█' * int(pct / 2)
    print(f'  {bin_labels[i]:<12} - {count:4d} команд ({pct:5.1f}%) {bar}')

print()
print('Статистика:')
print('-' * 120)
print(f'  Средняя стабильность:        {np.mean(stabilities):.3f}')
print(f'  Медиана:                     {np.median(stabilities):.3f}')
print(f'  Мин стабильность:            {np.min(stabilities):.3f}')
print(f'  Макс стабильность:           {np.max(stabilities):.3f}')
print(f'  Стд. отклонение:             {np.std(stabilities):.3f}')
print()

# Categories
super_stable_count = len([s for s in stabilities if s == 1.0])
high_stable_count = len([s for s in stabilities if 0.8 <= s < 1.0])
medium_stable_count = len([s for s in stabilities if 0.5 <= s < 0.8])
low_stable_count = len([s for s in stabilities if s < 0.5])

print('Категории стабильности:')
print('-' * 120)
print(f'  🟢 СУПЕР-СТАБИЛЬНЫЕ (100%):       {super_stable_count:4d} ({super_stable_count/len(teams_with_multiple_games)*100:5.1f}%)')
print(f'  🟢 СТАБИЛЬНЫЕ (80-99%):          {high_stable_count:4d} ({high_stable_count/len(teams_with_multiple_games)*100:5.1f}%)')
print(f'  🟡 СРЕДНИЕ (50-79%):            {medium_stable_count:4d} ({medium_stable_count/len(teams_with_multiple_games)*100:5.1f}%)')
print(f'  🔴 НЕСТАБИЛЬНЫЕ (<50%):         {low_stable_count:4d} ({low_stable_count/len(teams_with_multiple_games)*100:5.1f}%)')
print()
print(f'  ✅ СТАБИЛЬНЫХ (80%+):           {super_stable_count + high_stable_count:4d} ({(super_stable_count + high_stable_count)/len(teams_with_multiple_games)*100:5.1f}%)')
print(f'  ⚠️  НЕСТАБИЛЬНЫХ (<80%):        {medium_stable_count + low_stable_count:4d} ({(medium_stable_count + low_stable_count)/len(teams_with_multiple_games)*100:5.1f}%)')
