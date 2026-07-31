# RFFM Data Dictionary — Complete Schema & Query Recipes

**Season:** 2025-2026 | **Categories:** BENJAMÍN, PREBENJAMÍN | **Game Types:** Fútbol-7, Fútsal

This is your **reference guide** for writing queries against the processed CSV data. All tables live in `output/processed/rffm/*.csv`.

---

## 🏗️ Data Model Overview

```
competitions.csv (one per season × category × phase)
├── groups.csv (one per group within a competition)
│   ├── team_group_membership.csv (team ↔ group mapping)
│   │   └── teams.csv (canonical team records)
│   │       ├── matches.csv (fixtures + results)
│   │       └── standings.csv (league positions)
│   └── scorers.csv (top scorers per group)
```

**Key principle:** A **club** (e.g. "ARAVACA C.F. - CEIBA") can field multiple **teams** (suffix 'A', 'B', 'C', ...) across different competitions/groups/levels simultaneously. Always filter by `club_name_raw` to see all teams from one club.

---

## 📋 Core Tables

### 1. `competitions.csv`

**One row per competition.** A competition = season × category × phase (e.g., "PREFERENTE BENJAMÍN F-7" regular season is one row; "T. CAMPEONES BENJAMÍN F-7" playoff is another).

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `season` | str | Season label | `"2025-2026"` |
| `season_id` | str | Site's internal season ID | `"21"` |
| `category_base` | str | Base category (normalized) | `"BENJAMIN"`, `"PREBENJAMIN"` |
| `category_label_raw` | str | Raw category name from site | `"BENJAMÍN F-7"`, `"BENJAMIN SALA"` |
| `competition` | str | Full competition name | `"PREFERENTE BENJAMÍN F-7"` |
| `competition_id` | str | **PK** Site's competition ID | `"24038021"` |
| `phase_label` | str | Coarse phase classification | `"regular_season"`, `"playoff"`, `"phase 2ª FASE"` |
| `game_type` | str | Game type discovered | `"Futbol-7"`, `"Futbol Sala"` |
| `game_type_id` | str | Site's game-type ID | `"2"` |
| `source_url` | str | URL this was fetched from | `/api/competitions?temporada=21&tipojuego=2` |
| `scraped_at` | str | ISO timestamp when scraped | `"2026-07-31T11:28:31.567595+00:00"` |

**Usage:** Filter by `category_base` and `phase_label` to group competitions logically.

---

### 2. `groups.csv`

**One row per group within a competition.** A competition can have multiple groups (e.g., "Grupo 1", "Grupo 2", etc.).

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `season` | str | Season label | `"2025-2026"` |
| `season_id` | str | Season ID | `"21"` |
| `category` | str | Category (normalized) | `"BENJAMIN"` |
| `competition` | str | Competition name | `"PREFERENTE BENJAMÍN F-7"` |
| `competition_id` | str | FK to competitions | `"24038021"` |
| `group` | str | Group display name | `"Grupo 1"`, `"Cuadrangular 1"` |
| `group_id` | str | **PK** Site's group ID | `"24038022"` |
| `group_label_raw` | str | Raw group name from site | `"Grupo 1"`, `"Cuadrangular 1"` |
| `subgroup_label` | str / NULL | Subgroup label if present | `"Zona Sur"` or `NULL` |
| `source_url` | str | URL fetched | `/api/groups?competicion=24038021` |
| `scraped_at` | str | Timestamp | ISO datetime |

**Usage:** Join `competitions` + `groups` to navigate competition hierarchy.

---

### 3. `teams.csv`

**One row per canonical `team_id`.** Stores team metadata and critical **club ↔ team split**.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `team_id` | str | **PK** Site's team ID | `"116"` |
| `team` | str | Display name (club + suffix) | `"ARAVACA C.F. - CEIBA A"` |
| `team_name_raw` | str | Raw name from site | `"ARAVACA C.F. - CEIBA 'A'"` |
| `club_name_raw` | str | **Club name** (parsed from raw) | `"ARAVACA C.F. - CEIBA"` |
| `squad_suffix` | str / NULL | Squad letter (parsed from raw) | `"A"`, `"B"`, `"C"` or `NULL` |
| `source_team_url` | str | Link to team profile | `/fichaequipo/116` |
| `scraped_at` | str | Timestamp | ISO datetime |

**Critical:** Use `club_name_raw` to group all teams of one club together.

**Example:** All teams from "ARAVACA C.F. - CEIBA":
```sql
SELECT * FROM teams WHERE club_name_raw = 'ARAVACA C.F. - CEIBA'
-- Returns rows for 'A', 'B', 'C', 'D', 'E' squads (if they exist in data)
```

---

### 4. `team_group_membership.csv`

**Many-to-many: which team played in which group this season.**

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `season` | str | Season | `"2025-2026"` |
| `season_id` | str | Season ID | `"21"` |
| `competition_id` | str | FK to competitions | `"24038021"` |
| `group_id` | str | FK to groups | `"24038022"` |
| `team_id` | str | FK to teams | `"116"` |
| `team` | str | Team display name | `"ARAVACA C.F. - CEIBA A"` |
| `source_url` | str | Source | calendario page URL |
| `scraped_at` | str | Timestamp | ISO datetime |

**Usage:** To find all groups a team (or club's teams) competed in:
```sql
SELECT DISTINCT competition_id, group_id, team_id
FROM team_group_membership
WHERE team_id IN (SELECT team_id FROM teams WHERE club_name_raw = 'ARAVACA C.F. - CEIBA')
```

---

### 5. `matches.csv`

**One row per fixture/result.** Includes both played and unplayed matches. Scores are `NULL` together for unplayed matches, never partially `NULL`.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `season` | str | Season | `"2025-2026"` |
| `season_id` | str | Season ID | `"21"` |
| `category` | str | Category | `"BENJAMIN"` |
| `competition` | str | Competition name | `"PREFERENTE BENJAMÍN F-7"` |
| `competition_id` | str | FK | `"24038021"` |
| `group` | str | Group name | `"Grupo 1"` |
| `group_id` | str | FK | `"24038022"` |
| `game_type` | str | Game type | `"Futbol-7"` |
| `game_type_id` | str | Game type ID | `"2"` |
| `phase_label` | str | Phase | `"regular_season"` or `"playoff 1ª FASE"` |
| `matchday` | int / NULL | Round number (parsed) | `1`, `2`, ..., `24` or `NULL` |
| `matchday_label` | str / NULL | Raw round label | `"1 (11-10-2025)"` or `NULL` |
| `match_id` | str / NULL | **Acta ID** (unique match ID) | `"12345"` or `NULL` (for byes) |
| `home_team` | str | Home team name | `"ARAVACA C.F. - CEIBA A"` |
| `home_team_id` | str / NULL | FK to teams (NULL for bye) | `"116"` or `NULL` |
| `away_team` | str | Away team name | `"REAL MADRID C.F. A"` |
| `away_team_id` | str / NULL | FK to teams (NULL for bye) | `"14"` or `NULL` |
| `home_score` | int / NULL | Goals home scored | `3`, `0`, ..., or `NULL` (unplayed) |
| `away_score` | int / NULL | Goals away scored | `2`, `1`, ..., or `NULL` (unplayed) |
| `match_date` | str / NULL | Match date (ISO YYYY-MM-DD) | `"2025-10-11"` or `NULL` |
| `match_time` | str / NULL | Match time (HH:MM) | `"10:00"`, `"14:30"` or `NULL` |
| `match_datetime_raw` | str / NULL | Raw combined datetime | `"11-10-2025 10:00"` or `NULL` |
| `venue` | str / NULL | Stadium name | `"Campo 1"`, `"Polideportivo X"` or `NULL` |
| `status` | str | Match status | `"finished"`, `"scheduled"`, `"unscheduled"` |
| `is_finished` | bool | Whether scores exist | `true` or `false` |
| `is_scheduled` | bool | Whether date/time assigned | `true` or `false` |
| `result_text_raw` | str / NULL | Score as text | `"3-2"`, `"0-0"` or `NULL` |
| `source_url` | str | Source page | calendario page URL |
| `source_type` | str | Parser type | `"calendario_page"` |
| `scraped_at` | str | Timestamp | ISO datetime |

**Key:** `is_finished` tells you whether to trust `home_score` and `away_score`.

---

### 6. `standings.csv`

**One row per team per group.** League positions, points, goal differential, and sanction penalties.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `season` | str | Season | `"2025-2026"` |
| `season_id` | str | Season ID | `"21"` |
| `category` | str | Category | `"BENJAMIN"` |
| `competition` | str | Competition name | `"PREFERENTE BENJAMÍN F-7"` |
| `competition_id` | str | FK | `"24038021"` |
| `group` | str | Group name | `"Grupo 1"` |
| `group_id` | str | FK | `"24038022"` |
| `team` | str | Team display name | `"ARAVACA C.F. - CEIBA A"` |
| `team_id` | str / NULL | FK to teams | `"116"` |
| `position` | int / NULL | Final position in group | `1`, `2`, ..., `13` |
| `played` | int / NULL | Matches played | `24` |
| `wins` | int / NULL | Matches won | `18` |
| `draws` | int / NULL | Matches drawn | `4` |
| `losses` | int / NULL | Matches lost | `2` |
| `goals_for` | int / NULL | Goals scored | `108` |
| `goals_against` | int / NULL | Goals conceded | `48` |
| `goal_diff` | int / NULL | Goal differential | `+60` |
| `points` | int / NULL | League points | `58` (3 per win, 1 per draw) |
| `sanction_points` | int / NULL | Deducted points | `0` or positive deduction |
| `source_url` | str | Source page | clasificaciones page URL |
| `scraped_at` | str | Timestamp | ISO datetime |

**Usage:** For league positions and season performance.

---

### 7. `scorers.csv`

**Top-scorer leaderboard per group.** Aggregate only (not per-match); for detailed goal events, use enrichment tables.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `season` | str | Season | `"2025-2026"` |
| `competition_id` | str | FK | `"24038021"` |
| `group_id` | str | FK | `"24038022"` |
| `team_id` | str / NULL | FK to teams | `"116"` or `NULL` |
| `player_name` | str | Player name | `"Juan García"` |
| `goals` | int / NULL | Goals scored this group | `15`, `12`, ... |
| `source_url` | str | Source page | goleadores page URL |
| `scraped_at` | str | Timestamp | ISO datetime |

**Note:** This is **not** a full player log. Per-match goal events require `match_goals.csv` (enrichment).

---

## 📊 Enrichment Tables (Optional — Opt-in)

These are populated by `enrich_acta.py` and `enrich_players.py` (currently disabled by default in `config.yaml` due to robots.txt).

### 8. `match_lineups.csv` (Enrichment)

**Per-match, per-player lineup entry.** Includes starters, substitutes, captains, goalkeepers.

| Column | Type | Description |
|--------|------|-------------|
| `match_id` | str | FK to matches |
| `team_id` | str | FK to teams |
| `player_id` | str | Player ID |
| `player_name_raw` | str | Player name |
| `jersey_number` | int / NULL | Jersey # |
| `is_starter` | bool / NULL | Whether started |
| `is_substitute` | bool / NULL | Whether was sub |
| `is_captain` | bool / NULL | Whether was captain |
| `is_goalkeeper` | bool / NULL | Whether was GK |
| `position_raw` | str / NULL | Position (raw) |
| `position_abbr_raw` | str / NULL | Position abbr. |
| `sex_raw` | str / NULL | Sex code |
| `source_url` | str | Acta-partido URL |
| `scraped_at` | str | Timestamp |

---

### 9. `match_goals.csv` (Enrichment)

**One row per goal event in a match.**

| Column | Type | Description |
|--------|------|-------------|
| `match_id` | str | FK to matches |
| `team_id` | str | Scoring team |
| `player_id` | str / NULL | Player ID (if recorded) |
| `player_name_raw` | str | Player name |
| `minute` | int / NULL | Minute scored (parsed) |
| `minute_raw` | str / NULL | Raw minute string |
| `goal_type_raw` | str / NULL | Goal type code (undocumented) |
| `source_url` | str | Acta-partido URL |
| `scraped_at` | str | Timestamp |

---

### 10. `match_cards.csv` (Enrichment)

**One row per card (yellow/red) in a match.**

| Column | Type | Description |
|--------|------|-------------|
| `match_id` | str | FK to matches |
| `team_id` | str | Team of player carded |
| `player_id` | str / NULL | Player ID |
| `player_name_raw` | str | Player name |
| `minute` | int / NULL | Minute carded |
| `minute_raw` | str / NULL | Raw minute |
| `card_type_raw` | str / NULL | Card code: `"100"` (yellow), `"101"` (red), `"102"` (double yellow) |
| `card_type_label` | str / NULL | Decoded: `"Yellow"`, `"Red"`, `"Second Yellow"` |
| `is_second_yellow` | bool / NULL | Whether 2nd yellow became red |
| `source_url` | str | Acta-partido URL |
| `scraped_at` | str | Timestamp |

**Note:** Minute `999` is a sentinel (card issued outside play); treat as anomalous.

---

### 11. `match_staff.csv` (Enrichment)

**Coaches and delegation staff per match.**

| Column | Type | Description |
|--------|------|-------------|
| `match_id` | str | FK to matches |
| `team_id` | str | Team the staff member is associated with |
| `role_kind` | str | `"coach"` or `"delegate"` or other |
| `role_raw` | str | Raw role from acta |
| `person_id` | str / NULL | Staff member ID |
| `person_name` | str | Staff member name |
| `source_url` | str | Acta-partido URL |
| `scraped_at` | str | Timestamp |

---

### 12. `match_officials.csv` (Enrichment)

**Referees and field officials (neutral, not tied to a team).**

| Column | Type | Description |
|--------|------|-------------|
| `match_id` | str | FK to matches |
| `official_kind` | str | `"referee"`, `"field_delegate"`, etc. |
| `official_id` | str / NULL | Official ID |
| `official_name` | str | Official name |
| `role_raw` | str | Raw role |
| `source_url` | str | Acta-partido URL |
| `scraped_at` | str | Timestamp |

---

### 13. `players.csv` (Enrichment)

**Player profile snapshot for 2025-2026.**

| Column | Type | Description |
|--------|------|-------------|
| `player_id` | str | **PK** Player ID |
| `player_name` | str | Player name |
| `birth_year` | int / NULL | Birth year (not age, for future-proofing) |
| `source_url` | str | fichajugador URL |
| `scraped_at` | str | Timestamp |

---

### 14. `player_season_stats.csv` (Enrichment)

**Aggregate season statistics per player (site-reported, not computed).**

| Column | Type | Description |
|--------|------|-------------|
| `player_id` | str | FK to players |
| `season` | str | Season |
| `season_id` | str | Season ID |
| `called_up` | int / NULL | Times called up |
| `starter_appearances` | int / NULL | Starts |
| `substitute_appearances` | int / NULL | Sub appearances |
| `matches_played` | int / NULL | Total matches |
| `goals_total` | int / NULL | Goals (aggregate) |
| `goals_per_match` | float / NULL | Computed ratio |
| `yellow_cards` | int / NULL | Total yellows |
| `red_cards` | int / NULL | Total reds |
| `second_yellow_cards` | int / NULL | 2nd yellows |
| `is_goalkeeper` | bool / NULL | Position flag |
| `jersey_number` | int / NULL | Jersey worn |
| `source_url` | str | fichajugador URL |
| `scraped_at` | str | Timestamp |

---

### 15. `player_competition_participation.csv` (Enrichment)

**Which team(s)/group(s) each player is registered to this season.**

**Important:** A player can have **multiple rows** (dual registration: reserve + first team).

| Column | Type | Description |
|--------|------|-------------|
| `player_id` | str | FK to players |
| `season` | str | Season |
| `season_id` | str | Season ID |
| `competition_id` | str | FK to competitions |
| `competition` | str | Competition name |
| `group_id` | str | FK to groups |
| `group` | str | Group name |
| `team_id` | str | FK to teams |
| `team` | str | Team name |
| `club_name_raw` | str / NULL | Club (parsed from team) |
| `team_position` | int / NULL | Position in group final table |
| `team_points` | int / NULL | Team's final points |
| `source_url` | str | fichajugador URL |
| `scraped_at` | str | Timestamp |

---

## 🔑 Key Relationships

### Club → All Teams
```
teams: club_name_raw = 'ARAVACA C.F. - CEIBA'
       → all rows with suffixes A, B, C, D, E, ...
```

### Team → All Competitions
```
team_group_membership: team_id IN (...)
                      → all (competition_id, group_id, team)
```

### Team → All Matches (Home & Away)
```
matches: home_team_id = '116' OR away_team_id = '116'
```

### Team → League Position
```
standings: team_id = '116' AND group_id = '24038022'
         → position, points, goals, etc.
```

### Player → All Appearances
```
match_lineups: player_id = '12345'
match_goals: player_id = '12345'
match_cards: player_id = '12345'
```

---

## 📌 Common Query Patterns

### 1. **All Teams from a Club**
```python
# Pandas
club_teams = teams[teams['club_name_raw'] == 'ARAVACA C.F. - CEIBA']
```

### 2. **Club Performance Across All Competitions**
```python
# Get all team_ids for club
club_team_ids = teams[teams['club_name_raw'] == 'ARAVACA C.F. - CEIBA']['team_id'].tolist()

# Get all groups where these teams competed
team_groups = team_group_membership[
    team_group_membership['team_id'].isin(club_team_ids)
]

# Get standings for each (team, group) pair
club_standings = standings[
    (standings['team_id'].isin(club_team_ids)) &
    (standings['group_id'].isin(team_groups['group_id']))
]
```

### 3. **Head-to-Head: Club A vs Club B**
```python
# Get all team_ids for each club
club_a_teams = teams[teams['club_name_raw'] == 'CLUB A']['team_id'].tolist()
club_b_teams = teams[teams['club_name_raw'] == 'CLUB B']['team_id'].tolist()

# Matches where A played B
h2h = matches[
    ((matches['home_team_id'].isin(club_a_teams)) & 
     (matches['away_team_id'].isin(club_b_teams))) |
    ((matches['home_team_id'].isin(club_b_teams)) & 
     (matches['away_team_id'].isin(club_a_teams)))
]
```

### 4. **Top Scorers in a Group**
```python
group_scorers = scorers[scorers['group_id'] == '24038022'].sort_values('goals', ascending=False)
```

### 5. **Fixture List for a Team**
```python
team_id = '116'
team_matches = matches[
    (matches['home_team_id'] == team_id) | (matches['away_team_id'] == team_id)
].sort_values('match_date')
```

---

## ⚠️ Data Quality & Known Gaps

- **Byes / Unassigned teams:** Have `team_id = NULL` in matches (coded as `"-1"` on site, normalized to `NULL`)
- **Unplayed matches:** Have `is_finished = False`, scores are both `NULL`
- **Match lineups enrichment:** Disabled by default; requires `enrich_acta.py`
- **Player history:** Only 2025-2026 is collected; site holds back to 2020-2021 (`listado_temporadas`)
- **Match substitutions:** Not modeled (zero examples found in BENJAMÍN age bracket)
- **Card minute `999`:** Sentinel value; treat as anomalous, not literal play-time
- **Coach ID namespaces:** `cod_entrenador_local` vs `cod_tecnico` don't share confirmed namespace; don't join across role boundaries

---

## 🎯 This Document as a Cheat Sheet

- **Need to filter by club?** → Use `teams[teams['club_name_raw'] == 'X']` → get all `team_id`s
- **Need to know which leagues a team played in?** → Join `team_group_membership` + `competitions`
- **Need match results?** → Use `matches` with `is_finished = True`
- **Need league standings?** → Use `standings` (one row per team per group)
- **Need player data?** → Use enrichment tables (lineups, goals, cards, stats)

All timestamps are ISO 8601 UTC. All IDs are strings (to preserve leading zeros and mixed alphanumeric).
