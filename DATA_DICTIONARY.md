# DATA_DICTIONARY.md — full schema, join recipes, known quirks

Read this before writing any query. `CLAUDE.md` (auto-loaded into every
session in this repo) only keeps a one-line-per-table index plus the
question→table routing table — everything below (exact columns, quirks,
worked examples) lives only here on purpose, so sessions that never touch
the data don't pay to load it. See `CLAUDE.md`'s "Scope" and "How to answer
a query" for the season-partitioned paths and the query procedure/routing
table this file assumes.

## Why pandas, not SQL

Data lives as flat CSVs, not in a database — pandas reads one in a single
line, nothing to provision. Pandas isn't "better than SQL" in general; if
you'd genuinely rather write SQL, **DuckDB** can query these CSVs directly
with zero setup (`duckdb.sql("SELECT * FROM 'output/processed/rffm/2025-2026/matches.csv'")`).
But this repo has an established pandas convention (every recipe below is
written in it) — default to pandas for consistency unless SQL is explicitly
requested.

## Core tables

- **`competitions.csv`** (`competition_id` PK) — a competition is a
  season × category × phase, e.g. "PREFERENTE BENJAMÍN F-7". `phase_label`
  distinguishes regular season from playoff stages ("T. CAMPEONES...",
  "SEGUNDA FASE...") that the site models as *separate* competitions under
  the same category. `category_base`/`is_femenino`/`division_level` are
  parsed facets of `category_label_raw` — see "Category taxonomy" below
  before filtering by any of the three. Columns: `season, season_id,
  category_base, category_label_raw, is_femenino, division_level,
  competition, competition_id, phase_label, game_type, game_type_id,
  source_url, scraped_at`.
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
    first (see `CLAUDE.md`'s query procedure).
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
  match_datetime_raw, venue, venue_id, status, is_finished, is_scheduled,
  result_text_raw, source_url, source_type, scraped_at`. `venue` is the
  site's raw venue name string (e.g. `"COTORRUELO 1-A(HA)"`); `venue_id` is
  the numeric field id (site's `codigo_campo`) — FK to `venues.csv`, `null`
  for unscheduled matches with no assigned venue yet.
- **`venues.csv`** (`venue_id` PK) — one row per distinct playing field
  (`/campo/<venue_id>`, allowed by `robots.txt` — fetched as part of the
  core crawl, one request per unique `venue_id` seen in this run's
  `matches.csv`, not gated behind `enrichment`). Has exact
  `latitude`/`longitude` from the site (not geocoded), so
  `google_maps_url` is precise, not a name-based guess. Columns: `venue_id,
  venue_name, address, locality, province, postal_code, latitude,
  longitude, google_maps_url, field_type_raw, surface_raw, source_url,
  scraped_at`.
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
  this run (including `elapsed_seconds`, the end-to-end client duration) and
  automated anomaly findings (see "Two intentionally separate crawl-log
  families" below for why there are several of each).

## Category taxonomy

RFFM's own category naming (`NombreCategoria`, preserved verbatim as
`category_label_raw`) packs four independent facets into one free-text
string, e.g. `"PRIMERA DIVISIÓN AUTONÓMICA BENJAMÍN F7"` = division
*Primera División Autonómica* + age *Benjamín* + format *Futbol-7* (+ no
explicit gender marker). Never filter or group by `category_label_raw`
directly — parse (or, for the two already-derived columns below, just
read) the facet you actually want:

| Facet | Column | Source |
|---|---|---|
| Age group | `competitions.category_base` (also denormalized as `category` in `groups`/`matches`/`standings`/`scorers`) | parsed from `category_label_raw` |
| Game format | `competitions.game_type` / `game_type_id` | **not** parsed from the label — comes from a separate `/api/game-types` field, authoritative. The label sometimes *also* carries a redundant format suffix ("F-7"/"F7"/"SALA") but only when it differs from the division's default format, so don't parse it from there. |
| Gender | `competitions.is_femenino` | parsed from `category_label_raw` |
| Division / level | `competitions.division_level` | parsed from `category_label_raw` |

`is_femenino`/`division_level` live **only on `competitions.csv`** (one row
per competition) — not duplicated onto `groups`/`matches`/`standings`,
which already carry ~118k+ rows/season; join on `competition_id` if you
need them there.

**Scope note:** BENJAMÍN/PREBENJAMÍN was this project's initial development
target, not a permanent restriction (see `CLAUDE.md`'s "Scope"). A core
crawl (`--all-categories` / GitHub Actions `all_categories: true` input,
`stage: core` only) discovers every category the federation runs — season
2025-2026's committed core data is one such all-categories crawl (11
`category_base` values, not just the original two). `clubs.csv` is never
category-scoped either way (a club isn't an age-bracket concept - see
`club_pipeline.py`), so it covers whatever categories that season's core
data has. `acta_partido`/`fichajugador` remain category-scoped
(`scope_category`) and are **not** run against every category by default -
check `coverage_manifest.csv` for which `(season, category_base, stage)`
combinations are actually enriched vs. core-only.

### Age group (`category_base`)

Matched via `rffm_scraper.normalize.classify_age_category` against a fixed
vocabulary (`AGE_CATEGORY_VOCABULARY`), substring-matched most-specific
first (`PREBENJAMIN` before `BENJAMIN`, since the former contains the
latter): `DEBUTANTE, PREBENJAMIN, BENJAMIN, ALEVIN, INFANTIL, CADETE,
JUVENIL, VETERANOS, UNIVERSITARIO, AFICIONADO, SENIOR`. No match → `OTHER`.

Typical ages (RFEF standard — boundaries are approximate and can vary by
competition or season):

| `category_base` | Typical age | Birth years (2026–27) |
|---|---|---|
| `DEBUTANTE` | 4–5 (pre-Prebenjamín) | 2021–2022 |
| `PREBENJAMIN` | 6–7 | 2019–2020 |
| `BENJAMIN` | 8–9 | 2017–2018 |
| `ALEVIN` | 10–11 | 2015–2016 |
| `INFANTIL` | 12–13 | 2013–2014 |
| `CADETE` | 14–15 | 2011–2012 |
| `JUVENIL` | 16–18 | 2008–2010 |
| `AFICIONADO` | 19+ (amateur) | ≤ 2007 |
| `SENIOR` | 19+ (federated adult) | ≤ 2007 |
| `UNIVERSITARIO` | student category | — |
| `VETERANOS` | 35+\* | — |
| `OTHER` | unclassified | — |

`PREBENJAMIN` through `JUVENIL` form a continuous age progression.
`AFICIONADO` and `SENIOR` are adult tiers, not a next step in that ladder.
`UNIVERSITARIO` and `VETERANOS` are competition-specific categories — not
part of the standard progression.

\* VETERANOS minimum age varies by competition.

The match is tried against `NombreCategoria` first; if that produces
`OTHER`, the competition `nombre` field is tried as a fallback. This
handles FASE ZONAL competitions, where `NombreCategoria` is the generic
`"FASE ZONAL SALA"` / `"FASE ZONAL 7"` but `nombre` embeds the age group
directly (e.g. `"FASE ZONAL 3 benjamin VALDEMORO FS"`). `OTHER` is only
the final result when neither field contains any age-group token.

Note: RFFM sometimes abbreviates "ALEVIN" as "ALEV" (e.g.
`"DIVISION DE HONOR ALEV-F7"`) — the vocabulary matches on the `ALEV` stem
for this reason, not the full word.

This is the same substring-matching approach `match_category_base()` uses
for this project's configured `target.category_priority` (currently just
`[PREBENJAMIN, BENJAMIN]`, used for the normal 2-category scoped crawl) —
`classify_age_category` is its `--all-categories` counterpart, fixed
instead of config-driven, covering every age RFFM runs.

**Important — this is why `category_base` must stay a consolidated bucket,
not a raw-label passthrough:** `enrich_acta.py --scope BENJAMIN` filters
`matches.csv` with `df["category"] == scope_category` — an exact string
match. An earlier version of the `--all-categories` code path used
`category_label_raw` directly as `category_base`, which fragmented
BENJAMIN across 8 different raw labels (`"PRIMERA BENJAMIN F7"`,
`"DIVISIÓN DE HONOR BENJAMÍN F7"`, ...) and PREBENJAMIN across 4 more — so
the literal string `"BENJAMIN"` stopped existing anywhere in `matches.csv`,
and any acta_partido re-run for that scope would have silently found 0
targets. Worse: `acta_pipeline.py`'s completion logic treats 0 remaining
targets as `status="complete"`, so a 0-target run would have overwritten a
correct progress row with a false `complete, 0/0` — masking the breakage
rather than erroring. There's now a guard against this specific failure
mode in `acta_pipeline.py` (`_guard_against_silent_empty_scope` — raises
instead of upserting a false-complete row when a previously-nonzero
scope suddenly resolves to 0 targets), but the real fix is this: always
classify into a fixed vocabulary, never pass the raw label through.

### Gender (`is_femenino`)

`True` iff `category_label_raw` contains "FEMENIN" (covers both
"FEMENINO"/"FEMENINA"). **RFFM does not consistently mark the converse** —
only one category this season (`"CAMPEONATO UNIVERSITARIO MASCULINO"`)
carries an explicit men's marker. `is_femenino=False` means "no explicit
women's marker found", **not** "confirmed men's/mixed" — don't report it
as the latter.

### Division / level (`division_level`)

The messiest facet — RFFM's division naming isn't fully orthogonal to age
the way BENJAMIN/PREBENJAMIN's is. Matched via
`rffm_scraper.normalize.classify_division_level`, most-specific first:
`PRIMERA DIVISION AUTONOMICA, DIVISION DE HONOR, PREFERENTE, SEGUNDA
DIVISION B, TERCERA FEDERACION, PRIMERA, SEGUNDA, TERCERA, SUPERLIGA, LIGA
NACIONAL, FASE ZONAL, CAMPEONATO UNIVERSITARIO, LIGA UNIVERSITARIA`. Match
is tried against `NombreCategoria` first; if that produces `OTHER`, the
competition `nombre` is tried as fallback (same pattern as `category_base`).
No match in either → `OTHER` (e.g. bare `"BENJAMIN SALA"` with no explicit
tier — a real, common case, not a parsing gap). **Tier ordering and full
`OTHER` taxonomy: `DIVISIONS.md`.**

### Known `OTHER` cases (2025-2026, both facets) — genuine ambiguity, not bugs

A handful of RFFM's 93 2025-2026 categories carry no age word at all —
mostly senior/adult federation-tier leagues (`TERCERA FEDERACION`, `SEGUNDA
DIVISIÓN B DE FÚTBOL SALA`, `TERCERA DIVISIÓN DE FÚTBOL SALA`) or leisure
formats (`FUTBOL ANDANDO F-7` — walking football, `FASE ZONAL
7`/`FASE ZONAL SALA` — a zonal qualifying phase, age unclear) or
gender-only labels missing an age word entirely (`PREFERENTE FEMENINO
SALA`, `PREFERENTE FUTBOL FEMENINO`, `PRIMERA FUTBOL FEMENINO`, `PRIMERA
DIVISION AUTONOMICA FEMENINO SALA`, `PRIMERA DIVISIÓN AUTONÓMICA
FEMENINO`). These land in `age_category=OTHER` deliberately rather than
being guessed at (e.g. assuming the federation-tier ones are "SENIOR") —
if you need them classified, verify against the site rather than assuming
the vocabulary's silence means "not adult."

If a future season's labels don't fit this vocabulary well (new wording,
new abbreviations), it's a pure function of `category_label_raw` (always
preserved) — fix `normalize.py`'s vocabulary and re-run **core only**, no
re-crawl of enrichment data needed.

## Enrichment tables (opt-in — see README.md for why opt-in/robots.txt, OPERATIONS.md for how/when a run populates these)

- **`match_lineups/<category>.csv`** — per-match, per-player, one file per
  `scope_category` (e.g. `match_lineups/ALEVIN.csv`). FK `match_id` →
  `matches.csv`, FK `player_id` → `players.csv`. Columns: `match_id,
  team_id, player_id, jersey_number, is_starter, is_substitute, is_captain,
  is_goalkeeper, position_raw, position_abbr_raw, sex_raw`.
  Dropped columns and how to recover them:
  `player_name_raw` → join `players.csv` on `player_id`;
  `source_url` → `f"https://www.rffm.es/acta-partido/{match_id}"`;
  `scraped_at` → join `acta_crawl_log.csv` on `entity_id=match_id` where
  `success=True`, take `timestamp`.
- **`match_goals/<category>.csv`** — one row per goal event. `goal_type_raw`
  (site's `tipo_gol`, values `"100"/"101"/"102"` observed) is kept
  **opaque** — no confirmed decoding exists (unlike cards, below). Columns:
  `match_id, team_id, player_id, minute, minute_raw, goal_type_raw`.
  `player_name_raw`, `source_url`, `scraped_at` dropped (see above).
- **`match_cards/<category>.csv`** — one row per card. `card_type_raw` is
  the site's raw `codigo_tipo_amonestacion` code; `card_type_label` is a
  **derived, inferred** decoding — `"100"→"amarilla"`, `"101"→"roja"`,
  `"102"→"doble_amarilla"` (lowercase Spanish, matching the site's own
  wording, **not** English) — see "Card-type mapping" below for the
  inference basis. `minute == 999` is a known sentinel (card issued when
  not literally in play) — treat as anomalous, not a literal minute.
  Columns: `match_id, team_id, player_id, minute, minute_raw,
  card_type_raw, card_type_label, is_second_yellow`.
  `player_name_raw`, `source_url`, `scraped_at` dropped (see above).
- **`match_staff/<category>.csv`** — coaches/delegates, always has a real
  `team_id`. `role_kind` is one of exactly `"head_coach"`,
  `"assistant_coach"`, `"team_delegate"`, `"other_staff"`. Columns:
  `match_id, team_id, role_kind, role_raw, person_id, person_name`.
  `person_name` is kept (no separate coaches table exists).
  `source_url`, `scraped_at` dropped (see above).
- **`match_officials/<category>.csv`** — referees/field delegate, **no
  `team_id`** (neutral). `official_kind` is `"referee"` or
  `"field_delegate"`. Columns: `match_id, official_kind, official_id,
  official_name, role_raw`.
  `official_name` is kept (no separate officials table exists).
  `source_url`, `scraped_at` dropped (see above).
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
- **`clubs.csv`** (`club_id` PK, `enrich_clubs.py`) — one row per unique
  club (`club_name_raw` in `teams.csv`), from `/fichaequipo/<team_id>`.
  `club_id` is the site's own `codigo_club` — confirmed identical across
  every team of the same club by live sampling, so it is the real RFFM
  club identity, **not** a surrogate this project invented; join
  `teams.csv` to `clubs.csv` on `club_name_raw` (there is no `club_id`
  column in `teams.csv` itself). `representative_team_id` records which one
  team's fichaequipo page the row was actually fetched from — only one team
  per club is fetched (codigo_club/address don't vary by team), not every
  team. **`correspondence_address`/`locality`/`province`/`postal_code` are
  a correspondence address (where official club mail goes), not a stadium
  address** — RFFM does not publish a per-club venue; for playing fields,
  join `matches.csv`'s `venue_id` to `venues.csv` instead (see worked
  example below). Deliberately excludes the source page's
  `telefonos`/`email_correspondencia`/`fax` — personal contact info of a
  club delegate, not public club data. Columns: `club_id, club_name_raw,
  portal_web, crest_url, correspondence_address, locality, province,
  postal_code, representative_team_id, source_url, scraped_at`.
- **`clubs_extended.csv` / `club_teams.csv`** (`enrich_club_profiles.py`,
  from `/fichaclub/<club_id>`) — the club's own richer site profile: takes
  the real `club_id` (`codigo_club`) directly in the URL (not a `team_id` -
  a `team_id` there returns `club: null`), and returns every team the club
  has ever fielded, not just one representative team the way `clubs.csv`
  does. Targets are every `club_id` already present across every season's
  `clubs.csv` (cross-season - not one of these per season, unlike every
  other table above; both files live at the processed root next to
  `coverage_manifest.csv`, not inside a season directory). Not to be
  confused with `analysis_scripts/club_profile.py`'s unrelated "Club
  Profile" HTML report (donor/destination player-career flows) - same
  English phrase, different feature entirely.

  **Both tables are append-only snapshot logs, not one row per `club_id`
  like every other table in this file.** A club's profile/roster is the
  site's *current* state and genuinely drifts over time (new/deactivated
  teams, name changes) - unlike match results or a player's per-season
  stats, which are a fixed historical record once written. So a fetch never
  overwrites a prior row; every successful `/fichaclub/` fetch (the initial
  backfill, or a later deliberate `--force-refetch` refresh run) appends a
  fresh snapshot stamped with that fetch's own `scraped_at`. `club_id` is
  **not** unique in either file - get the current state with:

  ```python
  clubs_extended = pd.read_csv("output/processed/rffm/clubs_extended.csv", dtype=str)
  current = clubs_extended.sort_values("scraped_at").groupby("club_id").tail(1)
  ```

  Full history (what changed, when) is just the file itself - nothing extra
  to compute. `coverage_manifest.csv` records this stage as
  `season="ALL", category_base="ALL", stage="club_profiles"` (a synthetic
  key, same convention as `category_base="ALL"` elsewhere) since it isn't
  tied to any one season.

  `clubs_extended.csv` columns: `club_id, club_name, crest_url, delegacion,
  comarca, cif, registered_address, registered_locality,
  registered_province, registered_postal_code, correspondence_address,
  correspondence_locality, correspondence_province,
  correspondence_postal_code, correspondence_titular,
  correspondence_tratamiento, correspondence_email, portal_web, twitter,
  facebook, linkedin, instagram, telefonos, fax, fecha_fundacion,
  presidente, source_url, scraped_at`. `registered_*` is the club's real
  registered address (`domicilio` on the source page); `correspondence_*` is
  a separate mailing address (`domicilio_correspondencia`) - the same two
  distinct addresses `clubs.csv` already has under different names, plus
  the registered one clubs.csv doesn't carry at all. **Deliberately
  includes `telefonos`/`fax`/`correspondence_email`/`correspondence_titular`/
  `presidente`** (a club officer's personal contact info) - unlike
  `clubs.csv`, which excludes these on purpose; this table's inclusion is
  an equally deliberate, explicit choice for this table, not an
  inconsistency. `crest_url` is a relative path (e.g.
  `/pnfg/pimg/Clubes/...`), same convention as `clubs.csv`'s `crest_url` -
  prepend `https://www.rffm.es` to get a fetchable image URL.

  `club_teams.csv` columns: `club_id, team_id, categoria, team_name_raw,
  en_competicion, source_url, scraped_at`. One row per `(club_id, team)` per
  snapshot. `team_id` is the *same id space* as `teams.csv`'s `team_id`
  (confirmed by cross-reference - e.g. team_id `106`/`107`/`300231` under
  club_id `1011` match ARAVACA C.F.'s team_ids in every season's
  `teams.csv`), so it's directly joinable, though a given `team_id` here
  won't necessarily appear in any one season's `teams.csv` (this table
  covers the team's entire history at the club, not one season).
  `en_competicion`: the site's own flag - `True` if the team is currently
  registered in a live competition, `False` if it's a historical/inactive
  team the club has fielded in the past.

  **`club: null` is a valid, successful outcome**, not a fetch failure - a
  stale/defunct `club_id` genuinely has no `/fichaclub/` profile on the
  site (see `DATA_FINDINGS.md`'s "clubs_extended.csv - high null rate for
  older-season club_ids", ~35% of all 1,054 target club_ids as of the
  initial 2026-08 backfill, concentrated almost entirely in `club_id`s only
  ever seen in 2016-2019 seasons' `clubs.csv` - 0.4% for 2025-2026 alone).
  These club_ids simply have no row in `clubs_extended.csv`/`club_teams.csv`
  at all; `club_profiles_data_quality_report.csv` records each one as an
  `info`-severity `club_profile_not_found` row (not a warning) - see
  `club_profiles_crawl_log.csv` to distinguish "confirmed null" (`success`
  is `True`) from a genuine fetch failure (`club_profile_coverage_gap`,
  `success` is `False`).

### Where each club-data column comes from

Two different tables can look like they overlap because they describe the
same real-world clubs, but they read two different site pages, keyed by two
different entity types - this table is the definitive column→source
mapping so it's never a guessing game which one is authoritative for a
given field. See `DATA_FINDINGS.md`'s "clubs.csv vs clubs_extended.csv" for
the empirical agreement rate between the two (spoiler: high for
`portal_web`/`crest_url`/postal code, lower for free-text address strings -
formatting, not wrong data).

**`clubs.csv`** — source page `/fichaequipo/<team_id>` (one representative
team per club), JSON key `pageProps.team`:

| Column | Site JSON field | Notes |
|---|---|---|
| `club_id` | `codigo_club` | |
| `club_name_raw` | `nombre_club` | |
| `portal_web` | `portal_web` | |
| `crest_url` | `escudo_club` | relative path |
| `correspondence_address` | `domicilio_correspondencia` | mailing address, not a stadium |
| `locality` / `province` / `postal_code` | `localidad_correspondencia` / `provincia_correspondencia` / `codigo_postal_correspondencia` | |
| `representative_team_id` | — | the `team_id` this row was fetched with, not a JSON field |
| `telefonos` / `email_correspondencia` / `fax` | *(excluded)* | deliberately dropped — personal contact info |

**`clubs_extended.csv`** — source page `/fichaclub/<club_id>` (the club
itself, every team it has ever fielded), JSON key `pageProps.club`:

| Column | Site JSON field | Notes |
|---|---|---|
| `club_id` | `codigo` | |
| `club_name` | `nombre_club` | |
| `crest_url` | `escudo` | relative path, same convention as `clubs.csv` |
| `delegacion` / `comarca` | `delegacion` / `comarca` | RFFM's internal district grouping — no equivalent in `clubs.csv` |
| `cif` | `CIF` | Spanish tax ID — no equivalent in `clubs.csv` |
| `registered_address` / `registered_locality` / `registered_province` / `registered_postal_code` | `domicilio` / `localidad` / `provincia` / `codigo_postal` | the club's real registered address — **`clubs.csv` has no equivalent at all**, only the correspondence one below |
| `correspondence_address` / `correspondence_locality` / `correspondence_province` / `correspondence_postal_code` | `domicilio_correspondencia` / `localidad_correspondencia` / `provincia_correspondencia` / `codigo_postal_correspondencia` | same concept as `clubs.csv`'s `correspondence_address`/`locality`/`province`/`postal_code`, independently fetched from a different page |
| `correspondence_titular` / `correspondence_tratamiento` | `titular_correspondencia` / `tratamiento_correspondencia` | the named contact person for club mail — no equivalent in `clubs.csv` (excluded there as personal info) |
| `correspondence_email` | `email_correspondencia` | excluded from `clubs.csv`; deliberately included here |
| `portal_web` | `portal_web` | same concept as `clubs.csv`'s `portal_web` |
| `twitter` / `facebook` / `linkedin` / `instagram` | same-named fields | no equivalent in `clubs.csv` |
| `telefonos` / `fax` | `telefonos` / `fax` | excluded from `clubs.csv`; deliberately included here |
| `fecha_fundacion` | `fecha_fundacion` | founding date — no equivalent in `clubs.csv` |
| `presidente` | `presidente` | club president's name — no equivalent in `clubs.csv` |

**`club_teams.csv`** — same source page/fetch as `clubs_extended.csv`
(one page returns both), JSON key `pageProps.club.equipos_club[]`:

| Column | Site JSON field | Notes |
|---|---|---|
| `club_id` | — | the `club_id` this page was fetched with, not a per-item JSON field |
| `team_id` | `codigo_equipo` | same id space as `teams.csv`'s `team_id` |
| `categoria` | `categoria` | |
| `team_name_raw` | `nombre_equipo` | |
| `en_competicion` | `en_competicion` | `"1"`/`"0"` mapped to `True`/`False` |

No table in this project has ever listed every team a club has fielded
before this one — there's no `clubs.csv` equivalent to compare against.

## Worked example — "give me all results between two clubs" (season 2025-2026)

```python
import pandas as pd

teams = pd.read_csv("output/processed/rffm/2025-2026/teams.csv", dtype=str)
matches = pd.read_csv("output/processed/rffm/2025-2026/matches.csv", dtype=str)

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

**Querying across multiple seasons:** read each season's file and
`pd.concat()` at analysis time — same rule as the crawl-log families below,
never merge the season-partitioned files together on disk.

```python
import glob
import pandas as pd

matches_all_seasons = pd.concat(
    (pd.read_csv(p, dtype=str) for p in sorted(glob.glob("output/processed/rffm/*/matches.csv"))),
    ignore_index=True,
)
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

## Worked example — a club's playing fields + Google Maps links (season 2025-2026)

Two separate address concepts, joined through two different keys — do not
conflate them:

```python
import pandas as pd

teams = pd.read_csv("output/processed/rffm/2025-2026/teams.csv", dtype=str)
matches = pd.read_csv("output/processed/rffm/2025-2026/matches.csv", dtype=str)
venues = pd.read_csv("output/processed/rffm/2025-2026/venues.csv", dtype=str)
clubs = pd.read_csv("output/processed/rffm/2025-2026/clubs.csv", dtype=str)  # requires enrich_clubs.py to have run

club_name = "GETAFE C.F. S.A.D."

# Correspondence address (club_name_raw -> clubs.csv, no stadium guarantee)
print(clubs.loc[clubs["club_name_raw"] == club_name])

# Actual playing fields this club's teams host matches at, with precise
# lat/lon-derived Google Maps links (club_name_raw -> teams.csv -> team_id
# -> matches.csv home rows -> venue_id -> venues.csv)
team_ids = teams.loc[teams["club_name_raw"] == club_name, "team_id"]
home_venue_ids = matches.loc[matches["home_team_id"].isin(team_ids), "venue_id"].dropna().unique()
print(venues[venues["venue_id"].isin(home_venue_ids)][["venue_name", "address", "google_maps_url"]])
```

`clubs.csv` is opt-in (`enrich_clubs.py`, robots.txt-disallowed page) — check
`coverage_manifest.csv` (`stage == "clubs"`) before assuming it covers the
club you need. `venues.csv` is always present (core crawl) but only
contains venues that appear in *this run's* `matches.csv` — a club whose
teams haven't played yet this season may have no `venue_id` rows at all.

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

## Three intentionally separate crawl_log/quality-report families

`acta_crawl_log.csv`/`acta_data_quality_report.csv`,
`fichajugador_crawl_log.csv`/`fichajugador_data_quality_report.csv`, and
`clubs_crawl_log.csv`/`clubs_data_quality_report.csv` are kept **separate**
from the core pipeline's `crawl_log.csv`/`data_quality_report.csv`, on
purpose: the core files are fully rebuilt from scratch on every `main.py`
run, so an appending enrichment stage on top of them would get silently
wiped by the next unrelated core rerun. Want a unified view across all
crawl logs? `pd.concat()` them at analysis time — don't merge the files on
disk. (Each of these lives inside its season's directory alongside that
season's other tables — `crawl_log.csv` is per-season too, not global.) Note
`venues.csv`'s own fetches (`/campo/<id>`) log into core's `crawl_log.csv`,
not a fourth family — that stage isn't robots.txt-gated, so it runs inside
`main.py` itself rather than as a separate enrichment entrypoint.

`club_profiles_crawl_log.csv`/`club_profiles_data_quality_report.csv` is a
fifth family, with two differences from the three above: it lives at the
processed root (`output/processed/rffm/`), not inside any season's
directory, since the stage itself is cross-season (see `clubs_extended.csv`
above); and unlike the others, a `success=True` row here does not imply a
row was written to the primary output table — `club: null` is a valid
successful outcome with no `clubs_extended.csv`/`club_teams.csv` row at all
(see above).

Unlike core's `crawl_log.csv` (rebuilt from scratch every run), the three
enrichment crawl logs grow incrementally across a season's crawl and also
double as the crawler's own resumability marker — mechanics and why in
`OPERATIONS.md`, not relevant to querying the data itself.
