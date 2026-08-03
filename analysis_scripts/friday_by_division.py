import pandas as pd

season = '2025-2026'
matches_path = f'output/processed/rffm/{season}/matches.csv'
competitions_path = f'output/processed/rffm/{season}/competitions.csv'

matches = pd.read_csv(matches_path)
competitions = pd.read_csv(competitions_path)

# Merge to get division_level
matches = matches.merge(competitions[['competition_id', 'division_level']], on='competition_id', how='left')

# Filter for Friday
matches['match_date'] = pd.to_datetime(matches['match_date'])
matches['day_of_week'] = matches['match_date'].dt.day_name()

friday_data = matches[matches['day_of_week'] == 'Friday'].copy()

print('=' * 100)
print('ПЯТНИЦА - ПО ДИВИЗИОНАМ')
print('=' * 100)
print()

# Count by division
friday_by_division = friday_data['division_level'].value_counts().sort_values(ascending=False)
total_friday = len(friday_data)

print('ПЯТНИЦА - По дивизионам:')
print('-' * 100)
for div, count in friday_by_division.items():
    pct = (count / total_friday) * 100
    print(f'  {str(div):<40} - {count:5d} матчей ({pct:5.1f}%)')

print()
print('=' * 100)
print('ПЯТНИЦА - По времени и дивизионам (TOP 50)')
print('=' * 100)
print()

# Get time and division breakdown
friday_data['match_time'] = pd.to_datetime(friday_data['match_time'], format='%H:%M:%S', errors='coerce').dt.strftime('%H:%M')
time_division = friday_data.groupby(['match_time', 'division_level']).size().reset_index(name='count')
time_division = time_division.sort_values('count', ascending=False).head(50)

for _, row in time_division.iterrows():
    print(f"  {row['match_time']} - {str(row['division_level']):<40} - {row['count']:4d} матчей")
