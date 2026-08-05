# DEBUTANTE в RFFM: что это за феномен

## Коротко
DEBUTANTE в этих данных выглядит как отдельный младший пласт соревнований (младше PREBENJAMIN), но не как ровная классическая лига по шаблону PREBENJAMIN.

Основные признаки:
- отдельная возрастная сущность в текущем парсинге
- много матчей и много клубов
- расписание в основном на выходные, а не только пятница
- по части групп это не "игра каждую неделю весь сезон" в строгом смысле

## Что уже исправлено в данных
Раньше DEBUTANTE попадал в OTHER. Сейчас парсинг исправлен: DEBUTANTE выделяется как отдельная возрастная категория.

Код:
- [analysis_scripts/debutante_analysis.py](analysis_scripts/debutante_analysis.py)
- [rffm_scraper/normalize.py](rffm_scraper/normalize.py)

## Масштаб явления
По всем сезонам, где DEBUTANTE присутствует в текущем processed-слое:
- матчей: 10447
- сезоны с матчами: 2018-2019, 2019-2020, 2021-2022, 2022-2023, 2023-2024, 2024-2025, 2025-2026

Сводка по сезонам:
- [reports/debutante_matches_by_season.csv](reports/debutante_matches_by_season.csv)

## Кто играет
По всем сезонам:
- 213 уникальных названий клубов (raw)
- 211 без служебных строк "No asignado"
- около 208 после простого нормализующего дедупа названий

Готовые таблицы:
- [reports/debutante_clubs_all.csv](reports/debutante_clubs_all.csv)
- [reports/debutante_clubs_by_season.csv](reports/debutante_clubs_by_season.csv)

## Особенности расписания
### По всем сезонам (матчи с датой)
- понедельник: 93
- вторник: 112
- среда: 80
- четверг: 70
- пятница: 2535
- суббота: 4570
- воскресенье: 2011

Вывод: основной игровой день DEBUTANTE - суббота, затем пятница и воскресенье.

### Сезон 2025-2026
- матчей: 1784
- с датой: 1691
- без даты: 93
- диапазон дат: 2025-11-14 ... 2026-06-14
- уникальных игровых дат: 61

Детализация по группе/неделям:
- [reports/debutante_weekly_stability_2025-2026.csv](reports/debutante_weekly_stability_2025-2026.csv)

## Стабильность "каждую неделю"
Если брать строгий критерий "в каждую игровую неделю сезона":
- в 2025-2026 таких клубов нет

Файлы:
- [reports/debutante_2025-2026_clubs_every_global_week.csv](reports/debutante_2025-2026_clubs_every_global_week.csv)
- [reports/debutante_2025-2026_club_week_stability_summary.csv](reports/debutante_2025-2026_club_week_stability_summary.csv)

Если брать мягкий критерий "без дыр внутри собственного активного отрезка", тогда отдельные клубы есть (например, C.D. CARRANZA, JUVENTUD SANSE, JUVENTUD SANSE TRINITY COLLEGE).

## Рейтинг клубов по одной команде DEBUTANTE (2025-2026)
Это таблица "лучшей команды клуба" (максимум матчей у одной команды клуба):
- [reports/debutante_2025-2026_clubs_by_best_team_matches.csv](reports/debutante_2025-2026_clubs_by_best_team_matches.csv)

Полный рейтинг команд:
- [reports/debutante_2025-2026_teams_by_matches.csv](reports/debutante_2025-2026_teams_by_matches.csv)

## Кейс "пустой календарь"
Иногда ссылка на календарь на сайте может визуально показываться пустой, хотя в processed-данных матчи есть.
Для аналитики приоритетный источник истины в этом проекте:
- [output/processed/rffm/2025-2026/matches.csv](output/processed/rffm/2025-2026/matches.csv)
- [output/processed/rffm/2025-2026/manifest_pages.csv](output/processed/rffm/2025-2026/manifest_pages.csv)

Пример собранных ссылок по одному клубу (8960999-кейс):
- [reports/aravaca_request_8960999_debutante_team_links.csv](reports/aravaca_request_8960999_debutante_team_links.csv)
- [reports/aravaca_request_8960999_debutante_calendar_links.csv](reports/aravaca_request_8960999_debutante_calendar_links.csv)

## Как быстро пересобрать отчеты
Запуск:
- c:/git/personal/rffm/.venv/Scripts/python.exe analysis_scripts/debutante_analysis.py

Скрипт перегенерирует ключевые CSV по DEBUTANTE в папке reports.
