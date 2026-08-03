import pandas as pd

season = '2025-2026'
matches_path = f'output/processed/rffm/{season}/matches.csv'
competitions_path = f'output/processed/rffm/{season}/competitions.csv'
teams_path = f'output/processed/rffm/{season}/teams.csv'

matches = pd.read_csv(matches_path)
competitions = pd.read_csv(competitions_path)
teams = pd.read_csv(teams_path)

# Merge to get division_level, category, and team info
matches = matches.merge(competitions[['competition_id', 'division_level', 'category_base']], on='competition_id', how='left')

# Filter for PREBENJAMIN only
prebenjamin = matches[matches['category_base'] == 'PREBENJAMIN'].copy()

# Get day of week and time
prebenjamin['match_date'] = pd.to_datetime(prebenjamin['match_date'])
prebenjamin['day_of_week'] = prebenjamin['match_date'].dt.day_name()
prebenjamin['match_time'] = pd.to_datetime(prebenjamin['match_time'], format='%H:%M:%S', errors='coerce').dt.strftime('%H:%M')

print('=' * 120)
print('АНАЛИЗ: ОДНИ ЛИ КОМАНДЫ ИГРАЮТ В РАЗНЫЕ ДНИ И ВРЕМЯ?')
print('=' * 120)
print()

# Get all unique teams in PREBENJAMIN
all_teams = set(prebenjamin['home_team_id'].unique()) | set(prebenjamin['away_team_id'].unique())
print(f'Всего уникальных команд в ПРЕДЖАМИНЕ: {len(all_teams)}')
print()

# For each team, check how many different days they play
team_day_distribution = {}
team_time_distribution = {}
team_division_distribution = {}

for team_id in all_teams:
    home_games = prebenjamin[prebenjamin['home_team_id'] == team_id]
    away_games = prebenjamin[prebenjamin['away_team_id'] == team_id]
    all_games = pd.concat([home_games, away_games])

    days = all_games['day_of_week'].unique()
    times = all_games['match_time'].dropna().unique()
    divisions = all_games['division_level'].unique()

    team_day_distribution[team_id] = len(days)
    team_time_distribution[team_id] = len(times)
    team_division_distribution[team_id] = len(divisions)

# Analyze distribution
print('Распределение команд по количеству ДНЕЙ, в которые они играют:')
print('-' * 120)
day_count_dist = pd.Series(team_day_distribution).value_counts().sort_index()
for days, teams_count in day_count_dist.items():
    pct = (teams_count / len(all_teams)) * 100
    print(f'  {days} день(ей):     {teams_count:4d} команд ({pct:5.1f}%)')

print()
print('Распределение команд по количеству ВРЕМЁН ЗАПУСКА:')
print('-' * 120)
time_count_dist = pd.Series(team_time_distribution).value_counts().sort_index()
for times, teams_count in time_count_dist.items():
    pct = (teams_count / len(all_teams)) * 100
    print(f'  {times} время(я):    {teams_count:4d} команд ({pct:5.1f}%)')

print()
print('Распределение команд по количеству ДИВИЗИОНОВ:')
print('-' * 120)
div_count_dist = pd.Series(team_division_distribution).value_counts().sort_index()
for divs, teams_count in div_count_dist.items():
    pct = (teams_count / len(all_teams)) * 100
    print(f'  {divs} дивизион(ов): {teams_count:4d} команд ({pct:5.1f}%)')

print()
print('=' * 120)
print('СТАТИСТИКА КОМАНД')
print('=' * 120)
print()
print(f'Команды, играющие в 1 день:              {day_count_dist.get(1, 0):4d} ({day_count_dist.get(1, 0)/len(all_teams)*100:5.1f}%)')
print(f'Команды, играющие в 2+ дня:             {sum(day_count_dist[day_count_dist.index > 1]):4d} ({sum(day_count_dist[day_count_dist.index > 1])/len(all_teams)*100:5.1f}%)')
print()
print(f'Команды с 1 временем запуска:           {time_count_dist.get(1, 0):4d} ({time_count_dist.get(1, 0)/len(all_teams)*100:5.1f}%)')
print(f'Команды с 2+ временами запуска:         {sum(time_count_dist[time_count_dist.index > 1]):4d} ({sum(time_count_dist[time_count_dist.index > 1])/len(all_teams)*100:5.1f}%)')
print()
print(f'Команды в 1 дивизионе:                  {div_count_dist.get(1, 0):4d} ({div_count_dist.get(1, 0)/len(all_teams)*100:5.1f}%)')
print(f'Команды в 2+ дивизионах:                {sum(div_count_dist[div_count_dist.index > 1]):4d} ({sum(div_count_dist[div_count_dist.index > 1])/len(all_teams)*100:5.1f}%)')

print()
print('=' * 120)
print('АНАЛИЗ: ПЯТНИЦА vs СУББОТА - РАЗНЫЕ ЛИ КОМАНДЫ?')
print('=' * 120)
print()

# Get teams that play on Friday and Saturday
friday_data = prebenjamin[prebenjamin['day_of_week'] == 'Friday']
saturday_data = prebenjamin[prebenjamin['day_of_week'] == 'Saturday']

friday_teams = set(friday_data['home_team_id'].unique()) | set(friday_data['away_team_id'].unique())
saturday_teams = set(saturday_data['home_team_id'].unique()) | set(saturday_data['away_team_id'].unique())

both_days = friday_teams & saturday_teams
only_friday = friday_teams - saturday_teams
only_saturday = saturday_teams - friday_teams

print(f'Команды, играющие в ОБА дня (пятница + суббота): {len(both_days):4d} ({len(both_days)/len(all_teams)*100:5.1f}%)')
print(f'Команды ТОЛЬКО в пятницу:                         {len(only_friday):4d} ({len(only_friday)/len(all_teams)*100:5.1f}%)')
print(f'Команды ТОЛЬКО в субботу:                         {len(only_saturday):4d} ({len(only_saturday)/len(all_teams)*100:5.1f}%)')

print()
print(f'Всего команд (пятница):  {len(friday_teams)}')
print(f'Всего команд (суббота):  {len(saturday_teams)}')
print(f'Всего уникальных команд: {len(all_teams)}')

print()
print('=' * 120)
print('ВРЕМЯ ЗАПУСКА - ПЯТНИЦА vs СУББОТА')
print('=' * 120)
print()

friday_times = friday_data.groupby('match_time').size().sort_values(ascending=False)
print('ПЯТНИЦА - Времена запуска (TOP 10):')
print('-' * 120)
for time, count in friday_times.head(10).items():
    pct = (count / len(friday_data)) * 100
    print(f'  {time}: {count:5d} матчей ({pct:5.1f}%)')

print()
saturday_times = saturday_data.groupby('match_time').size().sort_values(ascending=False)
print('СУББОТА - Времена запуска (TOP 10):')
print('-' * 120)
for time, count in saturday_times.head(10).items():
    pct = (count / len(saturday_data)) * 100
    print(f'  {time}: {count:5d} матчей ({pct:5.1f}%)')
