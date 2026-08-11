# Plan: Notebook — Division Jump Lookalikes

## Context

Player 13794529 (PLATERO SOLIS, AITOR, born 2014) spent 2024-2025 ALEVÍN at
A.C.D. ENTIERGAL in **PRIMERA ALEVIN F-7** (tier 6), then jumped to
**DIVISIÓN DE HONOR ALEVIN** (tier 2) at C.D.A. NAVALCARNERO in 2025-2026 —
skipping PREFERENTE and PRIMERA DIVISION AUTONOMICA (2 intermediate divisions).

Goal: find all players born ≥ 2011 (= not older than PREBENJAMÍN age in
2018-2019) who made the same kind of 2-division leap **within the same age
category** between any two consecutive seasons.

---

## Key data findings

- 8 seasons: 2018-2019 → 2025-2026 (all have fichajugador + acta enrichment).
- `players.csv` is per-season; `birth_year` is reliable there.
- `player_competition_participation.csv` (per-season): one row per player per
  competition registration. Has `competition_id`, `team`, `club_name_raw`.
  Join to `competitions.csv` on `competition_id` to get `division_level`,
  `category_base`, `game_type`, `phase_label`, `is_femenino`.
- `player_season_stats.csv` (per-season): **one row per player per season**
  (site-aggregated totals). Columns: `matches_played`, `goals_total`,
  `goals_per_match`, `yellow_cards`, `red_cards`, `called_up`,
  `starter_appearances`, `substitute_appearances`.
- Tier map (to define in notebook, from DIVISIONS.md):
  `SUPERLIGA/LIGA NACIONAL=1, DIVISION DE HONOR=2, PRIMERA DIVISION AUTONOMICA=3,
  PREFERENTE=4, PRIMERA=6, SEGUNDA=7, TERCERA=8`
- Youth ALEVÍN pyramid (in raw tier numbers): 1→2→3→4→6 (no tier 5).
  "2 divisions skipped" = raw tier diff ≥ 4 (PRIMERA→DIVISION DE HONOR = 6-2=4).
  The threshold 4 matches the reference player's jump exactly.
- Filter: `phase_label == "regular_season"` to exclude cup/playoff registrations
  (those share the same `division_level` as the parent league but aren't the
  player's actual league level).
- Filter: `is_femenino == False` (default, configurable param).
- For dual registrations (same player, same season, same category, two teams),
  take the **lowest tier** (best division) as the player's tier for that season.

---

## Notebook: `notebooks/division_jumpers.ipynb`

### Cell structure

**Cell 1 — Setup & params**
```python
BASE = Path("../output/processed/rffm")
SEASONS = sorted(...)

TIER_MAP = {
    'SUPERLIGA': 1, 'LIGA NACIONAL': 1,
    'DIVISION DE HONOR': 2,
    'PRIMERA DIVISION AUTONOMICA': 3,
    'PREFERENTE': 4,
    'SEGUNDA DIVISION B': 5, 'TERCERA FEDERACION': 5,
    'PRIMERA': 6, 'SEGUNDA': 7, 'TERCERA': 8,
}

REF_PLAYER_ID = '13794529'
MIN_BIRTH_YEAR = 2011   # PREBENJAMÍN age or younger in 2018-2019
MIN_TIER_DIFF  = 4      # raw tier diff = "2 divisions skipped" (PRIMERA→DH = 4)
EXCLUDE_FEMENINO = True
```

**Cell 2 — Reference player career** (show PLATERO SOLIS, AITOR as the
concrete example, with a table: season, category, division, tier, club, team,
goals, matches)

**Cell 3 — Load competitions across all seasons**  
Concat `competitions.csv` from every season. Keep: `competition_id`, `season`,
`category_base`, `division_level`, `game_type`, `phase_label`, `is_femenino`.

**Cell 4 — Load player participation + enrich with tier**
1. Concat `player_competition_participation.csv` from every season.  
2. Left-join on `competition_id` → add `division_level`, `category_base`,
   `game_type`, `phase_label`, `is_femenino`.  
3. Filter: `phase_label == "regular_season"` AND (if `EXCLUDE_FEMENINO`:
   `is_femenino == False`).  
4. Map `division_level → tier` via `TIER_MAP` (NaN for OTHER/FASE ZONAL).  
5. Drop rows where `tier` is NaN.  
6. Per `(player_id, season, category_base)`: keep row with **min tier**
   (= best division). Also keep `club_name_raw`, `team` from that best-tier row.

Result: `df_part` — one row per `(player_id, season, category_base)` with
`division_level`, `tier`, `game_type`, `club_name_raw`, `team`.

**Cell 5 — Load player stats (per-season aggregated totals)**  
Concat `player_season_stats.csv`. Keep: `player_id`, `season`,
`matches_played`, `goals_total`, `goals_per_match`, `yellow_cards`,
`red_cards`, `called_up`, `starter_appearances`.  
Result: `df_stats` — one row per `(player_id, season)`.

**Cell 6 — Load player identities (birth_year)**  
Concat `players.csv`, deduplicate per `player_id` (keep last seen row).
Result: `df_players` — one row per player, columns: `player_id`, `player_name`,
`birth_year`.

**Cell 7 — Detect division jumps**
```python
# sort df_part by (player_id, season)
# within same (player_id, category_base), find consecutive season pairs
# where tier decreases (improved) by >= MIN_TIER_DIFF
# result: df_jumps_raw with columns:
#   player_id, prev_season, jump_season, category_base,
#   prev_tier, jump_tier, tier_diff,
#   prev_division, jump_division, prev_game_type, jump_game_type,
#   prev_club, prev_team, jump_club, jump_team
```

Key: consecutive seasons are defined as adjacent entries in the sorted season
list for the same `(player_id, category_base)`. Two seasons are "consecutive"
if there's no intermediate season for that player+category. (Optional: also
check that the seasons are actually adjacent years, e.g. 2024-2025→2025-2026.)

**Cell 8 — Filter cohort + merge metadata**
1. Merge `df_jumps_raw` with `df_players` → filter `birth_year >= MIN_BIRTH_YEAR`.
2. Merge with `df_stats` (twice: prev_season and jump_season) to get pre/post stats.

Result: `df_jumps` — one row per jump event.  
Columns:
- `player_id, player_name, birth_year`
- `first_season` (from df_part: earliest season for this player)
- `jump_from_season, jump_to_season, category_base`
- `from_division, from_tier, from_game_type, from_club, from_team`
- `to_division, to_tier, to_game_type, to_club, to_team`
- `tier_diff`
- `pre_matches, pre_goals, pre_goals_per_match, pre_yellow, pre_red`
- `post_matches, post_goals, post_goals_per_match, post_yellow, post_red`

**Cell 9 — Full career table for jump players**  
For all `player_id` values in `df_jumps`:
1. Filter `df_part` and `df_stats` to these players.
2. Merge on `(player_id, season)`.
3. Add `is_jump_season` boolean (True when season appears as `jump_to_season`
   for this player).

Result: `df_career` — long format, one row per `(player_id, season)`.  
Columns: `player_id, player_name, birth_year, season, category_base,
division_level, tier, game_type, club_name_raw, team,
matches_played, goals_total, goals_per_match, yellow_cards, red_cards,
called_up, starter_appearances, is_jump_season`.

**Cell 10 — Display summary**
- `print(f"Found {len(df_jumps)} jump events for {df_jumps.player_id.nunique()} unique players")`
- Table sorted by tier_diff descending (most dramatic first)
- Distribution: tier_diff counts, category_base breakdown

**Cell 11 — Per-player career view**  
For each player in `df_jumps`, display their `df_career` rows (styled with
`is_jump_season` highlighted). Reference player 13794529 should appear here.

**Cell 12 — Export**
```python
df_jumps.to_csv("../output/processed/rffm/career_analysis_lookalikes.csv", index=False)
df_career.to_csv("../output/processed/rffm/career_analysis_lookalikes_career.csv", index=False)
```

(The `career_analysis_lookalikes.csv` path matches what already exists in
`output/processed/rffm/` per git status.)

---

## Verification

After running the notebook:
1. Confirm player 13794529 appears in `df_jumps` with
   `from_division=PRIMERA`, `to_division=DIVISION DE HONOR`, `tier_diff=4`.
2. Sanity-check count: expect ~dozens to low-hundreds of jump events
   (a dramatic 2-division leap is uncommon).
3. Check reference player's career table matches known facts:
   2024-2025 = A.C.D. ENTIERGAL, PRIMERA, 24 goals; 2025-2026 = NAVALCARNERO,
   DIVISION DE HONOR, 2 goals.
4. Spot-check birth_year filter: all players in df_jumps should have birth_year >= 2011.
