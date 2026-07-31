# CLAUDE.md — orientation for analytics sessions

This file is for a *future session* that wants to answer analytics questions
against the collected RFFM data, not for someone implementing the scraper.
See `README.md` for how the data was collected; this file is about how to
use it.

## Scope

Season **2025-2026** only, categories **BENJAMÍN** and **PREBENJAMÍN**
(`category` column value `"BENJAMIN"`/`"PREBENJAMIN"`), across every game
type the federation runs under those categories (Futbol-7 and Futsal, as
discovered — not hardcoded to one).

## Core tables and how they join

All tables live in `output/processed/rffm/*.csv`.

- `competitions.csv` (`competition_id`) — a competition is a season × category ×
  phase, e.g. "PREFERENTE BENJAMÍN F-7". `phase_label` distinguishes regular
  season from playoff stages ("T. CAMPEONES...") that the site models as
  *separate* competitions under the same category.
- `groups.csv` (`group_id`) — belongs to a `competition_id`.
- `teams.csv` (`team_id`) — **a club is not a team**. `club_name_raw` is the
  club (e.g. "ARAVACA C.F. - CEIBA"); `team`/`squad_suffix` identify which
  squad of that club (e.g. suffix `"A"`, `"B"`). **To answer "how did club X
  do at BENJAMÍN", filter/group by `club_name_raw`, not by a single `team_id`
  — a club can field several teams across different groups/levels
  simultaneously.**
- `team_group_membership.csv` — `team_id` ↔ `group_id`/`competition_id` for
  this season. Join this to `teams.csv` to get, per club, every team/level
  it's registered at.
- `matches.csv` (`match_id` when available) — one row per fixture/result,
  `home_team_id`/`away_team_id` FK to `teams.csv`. `fixtures.csv` is just
  `matches.csv` filtered to `is_finished == False` — treat `matches.csv` as
  the source of truth, `fixtures.csv` as a convenience view.
- `standings.csv` — `team_id` + `group_id`/`competition_id`, includes
  `sanction_points`.
- `scorers.csv` — aggregate top-scorer leaderboard per group (name, `team_id`,
  goals). This is **not** a full per-match player log.

### Example: "compare club A vs club B at BENJAMÍN level"

1. `teams.csv` filtered by `club_name_raw in (A, B)` → all their `team_id`s.
2. `team_group_membership.csv` on those `team_id`s → which `group_id`s/levels
   each club's teams play in this season (this answers "what teams does the
   club field and at what level").
3. `matches.csv`/`standings.csv` on those `team_id`s → results/points/goal
   difference, aggregated back up to `club_name_raw` for a club-level (not
   single-team) comparison.

## Planned enrichment tables (see README "What's collected" for current status)

Once `enrich_acta.py` / `enrich_players.py` have been run (opt-in, robots.txt
governed — see README), these additional tables exist:

- `match_lineups.csv`, `match_goals.csv`, `match_cards.csv` — per-match,
  per-player facts, FK `match_id` → `matches.csv`, FK `player_id` → `players.csv`.
- `match_staff.csv` (coaches/delegates, always has a `team_id`) and
  `match_officials.csv` (referees/field delegate, **no** `team_id` — neutral).
- `players.csv` (`player_id`, name, `birth_year` — not age, which goes stale),
  `player_season_stats.csv` (site-reported season aggregates: matches played,
  goals, cards — useful to cross-validate our own per-match counts),
  `player_competition_participation.csv` (which team(s)/group(s) a player is
  registered to this season — **can be more than one row per player**, e.g. a
  reserve-team + first-team dual registration; this is not itself a
  "transfer").

### "Did player X move between teams/clubs?" — join recipe (no materialized `transfers.csv` on purpose)

There is no single "transfers" table — the site doesn't expose one, and
building a speculative one risks being wrong. Instead:

1. Join `match_lineups.csv` to `matches.csv` on `match_id` to get
   `match_date`/`category`/`competition_id` per appearance.
2. Per `player_id`, sort by `match_date`, and look at consecutive `team_id`
   values.
3. A `team_id` change is a **candidate** move, not a confirmed one — check
   two things before calling it a transfer:
   - **Category change** (e.g. PREBENJAMIN → BENJAMIN) usually means age
     progression to the next category, not a club transfer.
   - **`player_competition_participation.csv`** — if the player has *two*
     concurrent rows this season (dual registration), an apparent "change" in
     `match_lineups.csv` may just reflect which of their two teams played
     that week, not a move.

### Card-type code mapping (inferred, not officially documented)

`/fichajugador/` explicitly labels its card breakdown
(`codigo_tipo_tarjeta` → `nombre`): `100` = Amarillas (yellow), `101` = Rojas
(red), `102` = Doble Amarilla (second yellow). `match_cards.csv`'s
`card_type_raw` (from acta-partido's `codigo_tipo_amonestacion`) uses the same
numeric codes, so `card_type_label` is derived via this mapping — **this is
an inference from a same-numbering cross-reference, not a site-documented
fact**, kept alongside the untouched `card_type_raw` so it's easy to revise.
`goal_type_raw` (`tipo_gol`: 100/101/102 on goal events) has **no** analogous
breakdown anywhere on the site and stays undecoded/opaque — don't assume it
mirrors the card mapping.

## Known gaps / do not re-derive speculatively

- Match substitutions: not modeled — zero populated examples were found in
  the BENJAMÍN/PREBENJAMÍN age bracket to validate a schema against. Raw acta
  HTML is archived per match, so this is revisitable once older categories
  (which likely do report subs) are in scope.
- `otras_tarjetas`, `codacta_origen`: present on acta-partido but
  uncharacterized/unused.
- `999` as an event minute is a known sentinel (seen on a card entry issued
  when not literally "in play") — treat minute values that high as anomalous,
  not literal, when analyzing timing.
- Coach ids (`cod_entrenador_local`) and "otros técnicos" ids (`cod_tecnico`)
  are **not confirmed to share an id namespace** — don't join across
  `role_kind` boundaries in `match_staff.csv` assuming they do.
- Player profiles are fetched for season 2025-2026 only; the site holds
  per-player history back to 2020-2021 (`listado_temporadas`) if a future
  session wants multi-season career tracking.

## Two intentionally separate crawl_log/quality-report files

`acta_crawl_log.csv`/`acta_data_quality_report.csv` and
`fichajugador_crawl_log.csv`/`fichajugador_data_quality_report.csv` are kept
**separate** from the core pipeline's `crawl_log.csv`/`data_quality_report.csv`,
on purpose: the core files are fully rebuilt from scratch on every `main.py`
run, so an appending enrichment stage on top of them would get silently wiped
by the next unrelated core rerun. If a unified view across all crawl logs is
ever wanted, `pd.concat()` them at analysis time — don't merge the files on
disk.
