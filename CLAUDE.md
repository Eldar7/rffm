# CLAUDE.md — orientation for analytics sessions

This file is for a *future session* answering analytics questions against
the collected RFFM data — not for someone implementing the scraper (see
`README.md` for that: URL patterns, endpoints, how the data was collected).
This is the **single source of truth for the data model** — there is no
separate data-dictionary file; keeping one instead of several is deliberate,
see "Why one file" at the bottom.

## Scope

Season **2025-2026** only, categories **BENJAMÍN** and **PREBENJAMÍN**
(`category`/`category_base` column value `"BENJAMIN"`/`"PREBENJAMIN"`),
across every game type the federation runs under those categories (Futbol-7
and Futsal, as discovered — not hardcoded to one).

All tables live in `output/processed/rffm/*.csv`. Answer questions by
running a pandas script (via Bash), not by eyeballing CSV rows — see
"How to answer a query" below.

## Why pandas, not SQL

Data lives as flat CSVs, not in a database — pandas reads one in a single
line, nothing to provision. Pandas isn't "better than SQL" in general; if
you'd genuinely rather write SQL, **DuckDB** can query these CSVs directly
with zero setup (`duckdb.sql("SELECT * FROM 'output/processed/rffm/matches.csv'")`).
But this repo has an established pandas convention (every join recipe below
is written in it) — default to pandas for consistency unless SQL is
explicitly requested.

## Core tables

- **`competitions.csv`** (`competition_id` PK) — a competition is a
  season × category × phase, e.g. "PREFERENTE BENJAMÍN F-7". `phase_label`
  distinguishes regular season from playoff stages ("T. CAMPEONES...",
  "SEGUNDA FASE...") that the site models as *separate* competitions under
  the same category. Columns: `season, season_id, category_base,
  category_label_raw, competition, competition_id, phase_label, game_type,
  game_type_id, source_url, scraped_at`.
- **`groups.csv`** (`group_id` PK) — belongs to a `competition_id`. Columns:
  `season, season_id, category, competition, competition_id, group,
  group_id, group_label_raw, subgroup_label, source_url, scraped_at`.
- **`teams.csv`** (`team_id` PK) — **a club is not a team**. `club_name_raw`
  is the club (e.g. `"ARAVACA C.F. - CEIBA"`); `squad_suffix` (e.g. `"A"`,
  `"B"`) plus `team` (cleaned display name, suffix without quotes, e.g.
  `"ARAVACA C.F. - CEIBA A"`) identify which squad. **A club can field
  several teams across different groups/levels simultaneously** — filter by
  `club_name_raw`, never by a single `team_id`, when the question is about a
  club. Columns: `team_id, team, team_name_raw, club_name_raw, squad_suffix,
  source_team_url, scraped_at`.
  - **Important:** `team_name_raw` (here) and `home_team`/`away_team` (in
    `matches.csv`) and `team` (in `standings.csv`) all carry the site's raw
    quote-wrapped suffix, e.g. `"A.D. VILLAVICIOSA DE ODON 'A'"` — **not**
    the cleaned `teams.team` value. Never exact-match a club/team name
    against these raw columns; always resolve to `team_id` via `teams.csv`
    first (see the algorithm below).
- **`team_group_membership.csv`** — `team_id` ↔ `group_id`/`competition_id`
  for this season. Columns: `season, season_id, competition_id, group_id,
  team_id, team, source_url, scraped_at`.
- **`matches.csv`** (`match_id` PK when present) — one row per
  fixture/result, `home_team_id`/`away_team_id` FK to `teams.csv`.
  `fixtures.csv` is `matches.csv` filtered to `is_finished == False` — treat
  `matches.csv` as the source of truth, `fixtures.csv` as a convenience
  view. A bye/unassigned opponent (site's `codigo_equipo_*="-1"`) yields
  `home_team_id`/`away_team_id = null`, not a fabricated id.
  `home_score`/`away_score` are `null` together for unplayed matches, never
  partially null. **Known formatting quirk:** `matchday`, `home_score`,
  `away_score` currently serialize with a trailing `.0` (e.g. `"3.0"` not
  `"3"`) whenever the column has any null in it — a pandas artifact, not a
  data issue. **Don't use bare `int(x)` on these** (`int("3.0")` raises
  `ValueError`) — read with `dtype=str` and convert via
  `pd.to_numeric(col, errors="coerce")`, or `int(float(x))` per value.
  Columns: `season, season_id, category, competition, competition_id,
  group, group_id, game_type, game_type_id, phase_label, matchday,
  matchday_label, match_id, home_team, home_team_id, away_team,
  away_team_id, home_score, away_score, match_date, match_time,
  match_datetime_raw, venue, status, is_finished, is_scheduled,
  result_text_raw, source_url, source_type, scraped_at`.
- **`standings.csv`** — one row per team per group. Includes
  `sanction_points`. Columns: `season, season_id, category, competition,
  competition_id, group, group_id, team, team_id, position, played, wins,
  draws, losses, goals_for, goals_against, goal_diff, points,
  sanction_points, source_url, scraped_at`.
- **`scorers.csv`** — aggregate top-scorer leaderboard per group (name,
  `team_id`, goals). **Not** a full per-match player log — that's the
  enrichment tables below. Columns: `season, competition_id, group_id,
  team_id, player_name, goals, source_url, scraped_at`.
- **`manifest_groups.csv` / `manifest_pages.csv` / `manifest_endpoints.csv`**
  — discovery/page/endpoint manifests (what was found and fetched).
- **`crawl_log.csv`** / **`data_quality_report.csv`** — every HTTP request
  this run and automated anomaly findings (see "Two intentionally separate
  crawl-log families" below for why there are several of each).

## Enrichment tables (opt-in — see README for how/when these get populated)

- **`match_lineups.csv`** — per-match, per-player. FK `match_id` →
  `matches.csv`, FK `player_id` → `players.csv`. Columns: `match_id,
  team_id, player_id, player_name_raw, jersey_number, is_starter,
  is_substitute, is_captain, is_goalkeeper, position_raw,
  position_abbr_raw, sex_raw, source_url, scraped_at`.
- **`match_goals.csv`** — one row per goal event. `goal_type_raw` (site's
  `tipo_gol`, values `"100"/"101"/"102"` observed) is kept **opaque** —
  no confirmed decoding exists (unlike cards, below). Columns: `match_id,
  team_id, player_id, player_name_raw, minute, minute_raw, goal_type_raw,
  source_url, scraped_at`.
- **`match_cards.csv`** — one row per card. `card_type_raw` is the site's
  raw `codigo_tipo_amonestacion` code; `card_type_label` is a **derived,
  inferred** decoding — `"100"→"amarilla"`, `"101"→"roja"`,
  `"102"→"doble_amarilla"` (lowercase Spanish, matching the site's own
  wording, **not** English) — see "Card-type mapping" below for the
  inference basis. `minute == 999` is a known sentinel (card issued when not
  literally in play) — treat as anomalous, not a literal minute. Columns:
  `match_id, team_id, player_id, player_name_raw, minute, minute_raw,
  card_type_raw, card_type_label, is_second_yellow, source_url, scraped_at`.
- **`match_staff.csv`** — coaches/delegates, always has a real `team_id`.
  `role_kind` is one of exactly `"head_coach"`, `"assistant_coach"`,
  `"team_delegate"`, `"other_staff"` (never plain `"coach"`/`"delegate"`).
  Columns: `match_id, team_id, role_kind, role_raw, person_id, person_name,
  source_url, scraped_at`.
- **`match_officials.csv`** — referees/field delegate, **no `team_id`**
  (neutral). `official_kind` is `"referee"` or `"field_delegate"`. Columns:
  `match_id, official_kind, official_id, official_name, role_raw,
  source_url, scraped_at`.
- **`players.csv`** (`player_id` PK) — stable identity only:
  `player_id, player_name, birth_year` (birth year, **not** age, which goes
  stale every year), `source_url, scraped_at`.
- **`player_season_stats.csv`** — site-reported season aggregates (matches
  played, goals, cards) — **all values come verbatim from the site**, none
  are locally computed, including `goals_per_match`. Useful to
  cross-validate our own per-match counts. Columns: `player_id, season,
  season_id, called_up, starter_appearances, substitute_appearances,
  matches_played, goals_total, goals_per_match, yellow_cards, red_cards,
  second_yellow_cards, is_goalkeeper, jersey_number, source_url,
  scraped_at`.
- **`player_competition_participation.csv`** — which team(s)/group(s) a
  player is registered to this season. **Can be more than one row per
  player** (e.g. reserve-team + first-team dual registration — this is
  *not* itself a "transfer", see the join recipe below). Columns:
  `player_id, season, season_id, competition_id, competition, group_id,
  group, team_id, team, club_name_raw, team_position, team_points,
  source_url, scraped_at`.

## How to answer a query

**Procedure, every time:**
1. **Resolve names to IDs first.** Never filter `matches.csv`/`standings.csv`
   free-text columns directly by a club/player name the user typed — go
   through `teams.csv`/`players.csv` to get canonical `team_id`/`player_id`
   values, *then* filter everything else by ID. Free-text columns carry the
   site's raw formatting (quotes, accents, case) and are unreliable keys.
2. **Load only the CSVs the question needs** (table below).
3. **Run one self-contained pandas script via Bash** — don't hand-inspect
   CSV rows for anything beyond a first look.
4. **Sanity-check the row count** before presenting. Zero rows for two
   clubs/players that plausibly interacted is a signal something upstream
   is wrong (name typo, wrong scope, ID resolved against the wrong club),
   not necessarily a true negative.

**Question type → CSVs → join key:**

| Question | CSVs | Join |
|---|---|---|
| Club vs. club results / head-to-head | `teams`, `matches` | `club_name_raw` → `team_id` list → `home_team_id`/`away_team_id` |
| What teams/levels does a club field this season | `teams`, `team_group_membership`, `groups`, `competitions` | `team_id` → `group_id` → `competition_id` |
| League table / standings | `standings` | `group_id` (+ `team_id` for one team) |
| Top scorers in a group | `scorers` | `group_id` |
| A team's fixture list | `matches` | `home_team_id`/`away_team_id` |
| A player's appearances/goals/cards | `match_lineups`, `match_goals`, `match_cards`, `matches` | `player_id` → `match_id` → `matches` for date/context |
| Did a player move teams/clubs | `match_lineups`, `matches`, `player_competition_participation` | `player_id`, sorted by `match_date`, diff `team_id` (see recipe below) |
| Match report detail (lineup, staff, ref) | `match_lineups`, `match_staff`, `match_officials` | `match_id` |

**Worked example — "give me all results between two clubs":**

```python
import pandas as pd

teams = pd.read_csv("output/processed/rffm/teams.csv", dtype=str)
matches = pd.read_csv("output/processed/rffm/matches.csv", dtype=str)

club_a, club_b = "ARAVACA C.F. - CEIBA", "C.D. UNION DE ARAVACA"
ids_a = teams.loc[teams["club_name_raw"] == club_a, "team_id"]
ids_b = teams.loc[teams["club_name_raw"] == club_b, "team_id"]

h2h = matches[
    (matches["home_team_id"].isin(ids_a) & matches["away_team_id"].isin(ids_b))
    | (matches["home_team_id"].isin(ids_b) & matches["away_team_id"].isin(ids_a))
].copy()

# scores carry the known trailing-.0 quirk (see matches.csv notes above) - coerce, don't bare-int()
h2h["home_score"] = pd.to_numeric(h2h["home_score"], errors="coerce")
h2h["away_score"] = pd.to_numeric(h2h["away_score"], errors="coerce")

h2h = h2h.sort_values("match_date")
print(h2h[["match_date", "home_team", "away_team", "home_score", "away_score", "competition", "group"]])
```

**Recipe — "did player X move between teams/clubs?"** (no materialized
`transfers.csv` on purpose — the site doesn't expose one, and a speculative
one risks being wrong):
1. Join `match_lineups.csv` to `matches.csv` on `match_id` to get
   `match_date`/`category`/`competition_id` per appearance.
2. Per `player_id`, sort by `match_date`, look at consecutive `team_id`
   values.
3. A `team_id` change is a **candidate** move, not confirmed — check first:
   - **Category change** (PREBENJAMIN → BENJAMIN) usually means age
     progression, not a transfer.
   - **`player_competition_participation.csv`** — if the player has *two*
     concurrent rows this season (dual registration), an apparent "change"
     in `match_lineups.csv` may just reflect which of their two teams
     played that week, not a move.

## Card-type code mapping (inferred, not officially documented)

`/fichajugador/` explicitly labels its card breakdown
(`codigo_tipo_tarjeta` → `nombre`): `100` = Amarillas (yellow), `101` =
Rojas (red), `102` = Doble Amarilla (second yellow). `match_cards.csv`'s
`card_type_raw` (from acta-partido's `codigo_tipo_amonestacion`) uses the
same numeric codes, so `card_type_label` is derived via this mapping —
**this is an inference from a same-numbering cross-reference, not a
site-documented fact**, kept alongside the untouched `card_type_raw` so
it's easy to revise. `goal_type_raw` (`tipo_gol`) has **no** analogous
breakdown anywhere on the site and stays undecoded/opaque — don't assume it
mirrors the card mapping.

## Promotion/relegation (ascensos y descensos) — official, not inferred

RFFM publishes a season-specific **"Bases de Ascensos y Descensos"** PDF
(approved by the Comisión Delegada, typically each July before the season
starts) that governs how teams move between divisions
(`competition`/`competition_id` level, e.g. División de Honor → 1ª División
Autonómica → Preferente → Primera). It is **not** derivable from
`standings.csv` alone.

Full transcript + archived source PDF for **2025-2026**:
`docs/regulations/2025-2026/bases_ascensos_descensos_f7_f5.md` (the PDF
itself is scanned images — OCR'd via `pdftoppm` + `tesseract -l spa`, see
that file for the extraction method and the raw OCR text alongside it).

Headline points (season 2025-2026, BENJAMÍN/PREBENJAMÍN, Fútbol-7 — see the
doc above for full detail and Prebenjamín's two-phase season structure,
which is why `SEGUNDA FASE`/`SUBGRUPO ... A`/`SUBGRUPO ... B` rows exist in
`competitions.csv`/`groups.csv`):

- Promotion/relegation is decided by **final table position** (top-2 /
  bottom-4, division-dependent) — no playoff for these two categories in
  2025-2026 (playoffs only apply to Infantil Femenino in this document).
- Table position is **necessary but not sufficient** to know who actually
  moved: a club's filial/dependent status can block a promotion (next
  eligible team gets it instead), same-club A/B teams competing for one
  slot are resolved by points-per-game coefficient (not raw points, since
  groups can play different match counts) with letter-swapping if "B"
  outranks "A", and "supernumerary" groups relegate one extra team to
  rebalance division sizes.
- The **"Torneo de Campeones"** competitions in our data
  (`phase_label = "playoff"` / `"playoff FASE FINAL"`) are a separate
  end-of-season champions' cup among group winners — the ascensos/descensos
  document never mentions them, so treat them as **unrelated** to which
  division a team plays in next season (inference from the document's
  silence, not a confirmed fact).
- To confirm an actual division change for a team, **diff
  `team_id` → `competition_id`/`group_id` in `team_group_membership.csv`
  across two consecutive seasons** — don't infer it from one season's
  `standings.csv` position.
- **Rules are re-published every season and do change** (e.g. Prebenjamín's
  entire ascenso/descenso system is being abolished for 2026-2027 in favor
  of self-registration, per RFFM's own announcement). When a future session
  adds another season's data, fetch and read **that season's own** Bases de
  Ascensos y Descensos PDF from
  `https://www.rffm.es/federacion-rffm/documentacion-y-circulares/bases-de-competicion`
  rather than assuming the 2025-2026 rules above still hold — save it under
  `docs/regulations/<season>/` following the same structure.

## Known gaps / do not re-derive speculatively

- **Nullable-int-as-float CSV formatting** (see `matches.csv` notes above)
  — a known, not-yet-fixed pandas serialization quirk, not a data problem.
- Match substitutions: not modeled — zero populated examples were found in
  the BENJAMÍN/PREBENJAMÍN age bracket to validate a schema against. Raw
  acta HTML is archived per match, so this is revisitable once older
  categories (which likely do report subs) are in scope.
- `otras_tarjetas`, `codacta_origen`: present on acta-partido but
  uncharacterized/unused.
- Coach ids (`cod_entrenador_local`) and "otros técnicos" ids
  (`cod_tecnico`) are **not confirmed to share an id namespace** — don't
  join across `role_kind` boundaries in `match_staff.csv` assuming they do.
- Player profiles are fetched for season 2025-2026 only; the site holds
  per-player history back to 2020-2021 (`listado_temporadas`) if a future
  session wants multi-season career tracking.

## Two intentionally separate crawl_log/quality-report families

`acta_crawl_log.csv`/`acta_data_quality_report.csv` and
`fichajugador_crawl_log.csv`/`fichajugador_data_quality_report.csv` are kept
**separate** from the core pipeline's `crawl_log.csv`/`data_quality_report.csv`,
on purpose: the core files are fully rebuilt from scratch on every `main.py`
run, so an appending enrichment stage on top of them would get silently
wiped by the next unrelated core rerun. Want a unified view across all
crawl logs? `pd.concat()` them at analysis time — don't merge the files on
disk.

## Why one file

This project briefly had three overlapping docs (`README.md`'s data
dictionary, this file, and a separate `DATA_DICTIONARY.md`) describing the
same schema — they drifted out of sync with the actual code within the same
day (wrong `card_type_label`/`role_kind` example values, a raw-vs-cleaned
team-name mismatch). `CLAUDE.md` is now the only place the schema is
described in full; `README.md` covers how the scraper itself works and
links here instead of duplicating columns.
