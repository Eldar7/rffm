import pandas as pd

season = '2025-2026'
matches_path = f'output/processed/rffm/{season}/matches.csv'
competitions_path = f'output/processed/rffm/{season}/competitions.csv'

matches = pd.read_csv(matches_path)
competitions = pd.read_csv(competitions_path)

# Merge to get division_level and category_base
matches = matches.merge(competitions[['competition_id', 'division_level', 'category_base']], on='competition_id', how='left')

print('=' * 100)
print('ВСЕ КАТЕГОРИИ - ОБЩИЙ СЧЁТ')
print('=' * 100)
print()

# Total by category
category_counts = matches['category_base'].value_counts().sort_values(ascending=False)
total_matches = len(matches)

print('Все матчи по категориям:')
print('-' * 100)
for cat, count in category_counts.items():
    pct = (count / total_matches) * 100
    print(f'  {str(cat):<40} - {count:6d} матчей ({pct:5.1f}%)')

print()
print(f'ВСЕГО МАТЧЕЙ: {total_matches}')

print()
print('=' * 100)
print('ПО ДНЯМ НЕДЕЛИ - ВСЕ КАТЕГОРИИ')
print('=' * 100)
print()

matches['match_date'] = pd.to_datetime(matches['match_date'])
matches['day_of_week'] = matches['match_date'].dt.day_name()

day_counts = matches['day_of_week'].value_counts()
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

print('-' * 100)
for day in day_order:
    if day in day_counts.index:
        count = day_counts[day]
        pct = (count / total_matches) * 100
        print(f'  {day_names_ru[day]:<40} - {count:6d} матчей ({pct:5.1f}%)')

print()
print('=' * 100)
print('РАСПРЕДЕЛЕНИЕ ПО КАТЕГОРИЯМ И ДНЯМ')
print('=' * 100)
print()

# Detailed breakdown
for cat in category_counts.index[:15]:
    cat_data = matches[matches['category_base'] == cat]
    cat_total = len(cat_data)
    print(f'{cat} ({cat_total} матчей):')

    day_breakdown = cat_data['day_of_week'].value_counts()
    for day in day_order:
        if day in day_breakdown.index:
            count = day_breakdown[day]
            pct = (count / cat_total) * 100
            print(f'  {day_names_ru[day]:<35} - {count:6d} ({pct:5.1f}%)')
    print()
