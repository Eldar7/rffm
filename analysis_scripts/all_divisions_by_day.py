import pandas as pd

season = '2025-2026'
matches_path = f'output/processed/rffm/{season}/matches.csv'
competitions_path = f'output/processed/rffm/{season}/competitions.csv'

matches = pd.read_csv(matches_path)
competitions = pd.read_csv(competitions_path)

# Merge to get division_level
matches = matches.merge(competitions[['competition_id', 'division_level']], on='competition_id', how='left')

# Get day of week
matches['match_date'] = pd.to_datetime(matches['match_date'])
matches['day_of_week'] = matches['match_date'].dt.day_name()

day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
day_names_ru = {
    'Monday': 'ПОНЕДЕЛЬНИК',
    'Tuesday': 'ВТОРНИК',
    'Wednesday': 'СРЕДА',
    'Thursday': 'ЧЕТВЕРГ',
    'Friday': 'ПЯТНИЦА',
    'Saturday': 'СУББОТА',
    'Sunday': 'ВОСКРЕСЕНЬЕ'
}

print('=' * 120)
print('КАКИЕ ДИВИЗИОНЫ В КАКОЙ ДЕНЬ ИГРАЮТ')
print('=' * 120)
print()

# For each day, show all divisions
for day in day_order:
    day_data = matches[matches['day_of_week'] == day]

    if len(day_data) == 0:
        continue

    day_total = len(day_data)
    division_counts = day_data['division_level'].value_counts().sort_values(ascending=False)

    print(f'{day_names_ru[day]} ({day_total:,} матчей)')
    print('-' * 120)

    for div, count in division_counts.items():
        pct = (count / day_total) * 100
        bar_length = int(pct / 2)  # Scale for display
        bar = '█' * bar_length
        print(f'  {str(div):<40} - {count:6d} ({pct:5.1f}%) {bar}')

    print()

print('=' * 120)
print('СВОДНАЯ ТАБЛИЦА - КАЖДЫЙ ДИВИЗИОН, ВСЕ ДНИ')
print('=' * 120)
print()

# Get all unique divisions
all_divisions = sorted(matches['division_level'].unique())

for div in all_divisions:
    div_data = matches[matches['division_level'] == div]
    div_total = len(div_data)

    print(f'{div} ({div_total:,} матчей):')

    day_breakdown = div_data['day_of_week'].value_counts()

    for day in day_order:
        if day in day_breakdown.index:
            count = day_breakdown[day]
            pct = (count / div_total) * 100
            print(f'  {day_names_ru[day]:<35} - {count:6d} ({pct:5.1f}%)')

    print()
