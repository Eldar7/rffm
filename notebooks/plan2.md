# Career Path Analytics Plan

## Context

`player_career.ipynb` собрал `player_career.xlsx` — 289k строк, один игрок = одна строка, лайфтайм-агрегаты. Теперь цель — изучить **весь детский футбол** в RFFM:
- Чем отличаются игроки **топ-дивизиона своей возрастной группы** (SUPERLIGA/LIGA NACIONAL) от тех, кто играет в низших лигах той же возрастной группы?
- Как игрок движется по возрастной лестнице и что в его ранней игре это предсказывает?
- Кто «пропал с радаров» — перестал появляться в RFFM после хороших юношеских результатов (гипотеза: ушли в RFEF)?
- Кто сейчас в низших лигах, но **по цифрам похож на топ-игроков** из SUPERLIGA?

## Иерархия дивизионов по возрастам (из DIVISIONS.md)

| category_base | Топ-тир | Тир 2 | Тир 3 |
|---|---|---|---|
| JUVENIL | LIGA NACIONAL | DIVISION DE HONOR | PRIMERA DIVISION AUTONOMICA |
| CADETE | SUPERLIGA | DIVISION DE HONOR | PRIMERA DIVISION AUTONOMICA |
| INFANTIL | SUPERLIGA | DIVISION DE HONOR | PRIMERA DIVISION AUTONOMICA |
| ALEVIN | SUPERLIGA | DIVISION DE HONOR | PRIMERA DIVISION AUTONOMICA |
| BENJAMIN | DIVISION DE HONOR | PRIMERA DIVISION AUTONOMICA | PREFERENTE |
| PREBENJAMIN | PRIMERA DIVISION AUTONOMICA | PREFERENTE | PRIMERA |

**"Топ-игрок возрастной группы"** = division_level ∈ {`SUPERLIGA`, `LIGA NACIONAL`} для JUVENIL/CADETE/INFANTIL/ALEVIN; `DIVISION DE HONOR` для BENJAMIN; `PRIMERA DIVISION AUTONOMICA` для PREBENJAMIN.

---

## Новый ноутбук: `notebooks/career_analysis.ipynb`

### Секция 0 — Загрузка базы

Загрузить `player_career.xlsx` и распарсить list-колонки (`;`-separated → Python list).

### Секция 1 — Временна́я таблица участия (с сезоном)

Перезагрузить `player_competition_participation.csv` по всем 8 сезонам, добавить `category_base` + `division_level` из `competitions.csv`. Результат: `part_temporal` — столбцы: `player_id`, `season`, `category_base`, `division_level`, `club_name_raw`.

Параллельно: `pss_temporal` из `player_season_stats.csv` — `player_id`, `season`, `goals_total`, `matches_played`, `is_goalkeeper` для постатейной (по сезону) статистики.

### Секция 2 — Разметка

```python
TOP_TIER_BY_CAT = {
    "JUVENIL": {"LIGA NACIONAL"},
    "CADETE":  {"SUPERLIGA"},
    "INFANTIL":{"SUPERLIGA"},
    "ALEVIN":  {"SUPERLIGA"},
    "BENJAMIN":{"DIVISION DE HONOR"},
    "PREBENJAMIN": {"PRIMERA DIVISION AUTONOMICA"},
}

# Для каждого (player_id, category_base) — был ли в топ-тире?
# Из part_temporal: join TOP_TIER_BY_CAT, флаг top_tier_in_cat
# Merge обратно в career (или держать отдельно как part_labeled)
```

Дополнительные метки на `career`:
- `highest_category` — старшая возрастная категория (JUVENIL > CADETE > ... > PREBENJAMIN)
- `ever_top_tier` — bool, хоть раз в топ-тире своей возрастной группы
- `top_tier_categories` — список категорий, в которых был топ-тир
- `last_active_season` — последний сезон
- `birth_year` (numeric)

### Секция 3 — Профиль топ-игроков vs. остальных (внутри каждой категории)

Для каждой возрастной категории (CADETE, JUVENIL, INFANTIL, ALEVIN — где есть SUPERLIGA) сравнить две группы:
- Группа A: `top_tier_in_cat = True`
- Группа B: `top_tier_in_cat = False`, `category_base = та же`

Метрики (медиана + IQR):
- `goals_per_season` = goals_total / seasons_in_category
- `matches_per_season`
- `starter_rate` = starter_appearances / called_up
- `win_rate` (из acta)
- `captain_rate` = captain_appearances / acta_matches

Визуализация: boxplots side-by-side по категориям.

### Секция 4 — Путь вверх по лестнице

Из `part_temporal` для каждого игрока построить цепочку: в каком сезоне, в какой категории и в какой команде (`team_id`) он играл.

**4a. Базовая прогрессия**
1. **Прогрессия**: доля игроков, которые поднялись на следующий уровень (BENJAMIN → ALEVIN → ...) vs. «застряли» в той же категории 2+ сезонов
2. **Скорость**: среднее число сезонов на каждой ступени для топ-тир игроков vs. нетоп
3. **Пропуск ступени**: были ли игроки, которые перепрыгнули категорию?

**4b. Механизм продвижения: вместе с командой или индивидуальный трансфер?**

Для каждого игрока, который перешёл в более высокий дивизион (в той же или следующей возрастной категории), определить:

- **Продвинулся вместе с командой (promotion)**: `team_id` не изменился между сезонами, а `division_level` команды стал выше (клуб повысился в классе)
- **Индивидуальный трансфер вверх**: `team_id` изменился, новая команда в более высоком дивизионе
- **Трансфер горизонтальный**: `team_id` изменился, дивизион тот же
- **Трансфер вниз**: `team_id` изменился, новая команда в более низком дивизионе

```python
# Для каждого (player_id, season) взять team_id и division_level из part_temporal
# Отсортировать по сезону, сравнить два соседних сезона
# Классифицировать каждый переход
transitions = part_temporal.sort_values(["player_id", "season"]).groupby("player_id").apply(classify_transitions)
# classify_transitions: сравнивает строку N и N+1, возвращает тип перехода
```

Агрегировать: для каждого игрока — сколько переходов каждого типа.

Итоговый вопрос: топ-тировые игроки в основном попали туда через трансфер или через повышение своего клуба?

**4c. Перемешивание команд — насколько стабильны составы?**

Для каждой команды (team_id) в каждом сезоне: какая доля игроков осталась из прошлого сезона, какая ушла, какая пришла новых.

```python
# team_id, season → set of player_ids
# Overlap между (team_id, season) и (team_id, season-1): retention_rate
team_stability = ...
# median retention_rate по дивизионам:
# Топ-тир = стабильнее или наоборот больше ротации?
```

Дополнительно: куда уходят игроки из топ-тировых команд — в другую топ-тировую или в нижний дивизион?

**4d. «Кем были одноклубники» — тренировочный эффект команды**

Гипотеза: игроки, которые играли в командах с высоким средним уровнем (много топ-тировых сокомандников), сами впоследствии чаще поднимаются выше.

Для каждого игрока в каждом сезоне: доля сокомандников (по acta lineups), которые в следующих сезонах оказались в топ-тире.

### Секция 5 — Гипотеза RFEF: пропавшие игроки

```python
disappeared = career[
    (career["birth_year"] <= 2007) &           # возраст ≥ 17 в 2025-2026
    (career["highest_category"].isin(["CADETE", "JUVENIL"])) &
    (career["last_active_season"] <= "2023-2024") &  # нет активности последние ~2 сезона
    (~career["ever_top_tier"])                  # необязательный уточняющий фильтр
]
```

Отдельная таблица «сильные пропавшие» — те, кто достиг топ-тира и затем исчез.

Вывод: топ-30 «пропавших талантов» с `player_name`, `birth_year`, `last_active_season`, `highest_category`, `clubs`, `goals_total`.

### Секция 6 — «Похожие, но не замеченные» — lookalike в низших лигах

Цель: найти игроков, которые сейчас (2024-2025 / 2025-2026) играют в **нетоп** дивизионах, но по цифрам похожи на топ-тировых игроков той же возрастной группы.

Алгоритм:
1. Вычислить «профиль топ-тира» по категории (медиана goals_per_match, starter_rate, win_rate)
2. Для каждого нетоп-игрока той же категории вычислить euclidean distance к медиане топ-профиля (нормализованные фичи)
3. Топ-30 по близости к топ-профилю — это «незамеченные»

### Секция 7 — Экспорт

```
output/processed/rffm/career_analysis_top_tier_profile.csv
output/processed/rffm/career_analysis_disappeared.csv
output/processed/rffm/career_analysis_lookalikes.csv
```

---

## Ключевые файлы

- **Создать**: `notebooks/career_analysis.ipynb`
- **Читать**: `player_career.xlsx` + все 8 сезонов `player_competition_participation.csv`, `player_season_stats.csv`, `competitions.csv`
- **Записать**: 3 CSV с результатами

## Верификация

1. `ever_top_tier` rate — проверить, что топ-тир игроки составляют разумную долю (~5-20% от тех, кто вообще играл CADETE/JUVENIL)
2. Путевой анализ — убедиться что нет игроков DEBUTANTE, учтённых как «достигших CADETE» (хронология должна быть 18-19 → 20-21 → ...)
3. Таблица `disappeared` — проверить что нет игроков 2018-2019 рождения (им ещё нет 17 лет в 2025)
4. Lookalike-скор — проверить top-3 вручную: реально ли они в нижних лигах и реально ли хорошие цифры
