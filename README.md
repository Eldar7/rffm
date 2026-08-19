# RFFM data collector — multi-category, multi-season

Production-minded scraper for the Real Federación de Fútbol de Madrid (RFFM)
website (`https://www.rffm.es`). Covers competitions, groups, teams,
fixtures/results, standings, and top scorers, discovered dynamically (not
hardcoded) across every game type the federation runs (Fútbol-7, Fútbol-11,
Fútbol Sala, ...). **BENJAMÍN**/**PREBENJAMÍN** was this project's initial
development target, not a permanent restriction: `config.yaml`'s
`target.category_priority` still defaults to those two for a plain crawl,
but `main.py --all-categories` (or the GitHub Actions workflow's
`all_categories` input) discovers and collects every age/division category
the federation runs in one pass — see `DATA_DICTIONARY.md`'s "Category
taxonomy". `clubs.csv`/`venues.csv` are never category-scoped regardless.
Built to run repeatedly across **many seasons** (change `target.season_label`
in `config.yaml`, nothing else) without one season's crawl ever overwriting
another's — see "Storage layout" below.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py                      # full crawl: discovery + calendario/clasificaciones/goleadores
```

Output:
- `output/raw/rffm/...` — raw HTML per page fetched (gitignored, regenerated per run, **never pushed**)
- `output/processed/rffm/<season>/*.csv` — normalized, analysis-ready tables for that season (tracked in git)
- `output/processed/rffm/coverage_manifest.csv` — cross-season index of what's done (see below)

Optional enrichment stages (see "robots.txt and enrichment" below) each have
their own entrypoint and are off by default: `enrich_acta.py` (match
lineups/goals/cards/staff/officials), `enrich_players.py` (player
profiles/season stats), `enrich_clubs.py` (club identity/correspondence
address), `enrich_team_clubs.py` (complete `team_id -> club_id` mapping -
see "Entities collected" below for how it differs from `enrich_clubs.py`),
and `enrich_club_profiles.py` (full club profile + every team a
club has ever fielded, cross-season, from `/fichaclub/<club_id>`). Venue/field
data (`venues.csv`) is **not** a separate opt-in stage - it's part of the
core `main.py` crawl, since `/campo/` is not in robots.txt's `Disallow` list.

## Storage layout

`output/processed/rffm/<season_label>/*.csv` — every season gets its own
directory, so re-running for a new season never touches another season's
committed files. `output/processed/rffm/coverage_manifest.csv` is the one
cross-season exception: one upserted row per `(season, category, stage)`
telling you whether it's `complete`, `complete_with_failures`, or still
`partial`.

## Running this via GitHub Actions / resumability / operating at scale

See **`OPERATIONS.md`** — dependency order between the three entrypoints,
how the batched/resumable enrichment pipelines and `coverage_manifest.csv`
work, a step-by-step walkthrough of `.github/workflows/rffm-crawl.yml`, a
concrete "what to dispatch" recipe, the GitHub Actions limits that actually
apply to this repo, and how to test a pipeline change safely before it ever
touches committed data. Kept out of this file on purpose — same reasoning as
why the data dictionary lives only in `CLAUDE.md` (see that file's "Why one
file" section).

## How discovery works (no hardcoded competition/group IDs)

1. `GET /api/seasons` → resolve `season_label` ("2025-2026") to the site's
   internal `cod_temporada` ("21").
2. `GET /api/game-types` → every game type the federation runs (Futbol-11,
   Futbol-7, Fútbol Sala, Fútbol-5, Fútbol-Playa).
3. For **each** game type: `GET /api/competitions?temporada=&tipojuego=` →
   every competition in that season+game type, each carrying a raw
   `NombreCategoria` label. Category matching (`BENJAMIN`/`PREBENJAMIN`, with
   `PREBENJAMIN` checked *before* `BENJAMIN` since the former contains the
   latter as a substring) is accent/case/hyphen-insensitive
   (`rffm_scraper/normalize.py:match_category_base`), so it naturally covers
   every label variant on the site (`BENJAMIN`, `BENJAMÍN`, `PREFERENTE
   BENJAMIN F7`, `PRIMERA DIVISIÓN AUTONÓMICA PREBENJAMÍN`, `BENJAMIN SALA`,
   ...) without enumerating them.
4. For each matching competition: `GET /api/groups?competicion=` → every
   group, with metadata (`total_jornadas`, `total_equipos`,
   `clasificacion_goleadores` flag) used to plan the fetch.

Empirically for 2025-2026 this surfaces BENJAMÍN/PREBENJAMÍN competitions
under **both Futbol-7 and Futsal (Fútbol Sala)** — not just Futbol-7 — which
is exactly why game type isn't hardcoded.

With `--all-categories` (or the GitHub Actions workflow's `all_categories`
input), step 3's category matching is skipped entirely - every competition
in every game type is kept, with `category_base` classified via
`normalize.classify_age_category` against a fixed age vocabulary instead of
`category_priority` (see `DATA_DICTIONARY.md`'s "Category taxonomy" for the
full facet breakdown: age/gender/division/format).

Discovery output is saved as a timestamped JSON manifest under
`output/raw/rffm/discovery/manifest_<season_id>_<timestamp>.json`.

## Discovered URL patterns

| Kind | Pattern | Notes |
|---|---|---|
| Calendario (fixtures+results) | `/competicion/calendario?temporada=&competicion=&grupo=&jornada=&tipojuego=` | **Returns every jornada for the group in one request**, regardless of the `jornada` value — used as the single source for the whole season's matches per group. `jornada=1` is always passed since the param is required by the route but ignored by the response. |
| Clasificaciones (standings) | `/competicion/clasificaciones?temporada=&competicion=&grupo=&tipojuego=` | |
| Goleadores (top scorers) | `/competicion/goleadores?temporada=&competicion=&grupo=&tipojuego=` | Only fetched when the group's `clasificacion_goleadores` flag is `"1"`. |
| Campo (venue/field profile) | `/campo/<venue_id>` | **Not** robots.txt-disallowed - part of the core crawl, one request per unique `codigo_campo` seen in this run's calendario data. Address + exact lat/lon → `venues.csv`. |
| Acta de partido (match report) | `/acta-partido/<match_id>?temporada=&competicion=&grupo=` | Enrichment only, **off by default** — see robots.txt note below. |
| Ficha de equipo (team profile) | `/fichaequipo/<team_id>` | Enrichment only, **off by default** — see robots.txt note below. |
| Ficha de jugador (player profile) | `/fichajugador/<player_id>?temporada=` | Enrichment only, **off by default** — see robots.txt note below. |
| Ficha de club (club profile) | `/fichaclub/<club_id>` | Enrichment-adjacent, **off by default** (gated for consistency, not because robots.txt requires it). Takes the real `club_id`, not a `team_id` - a `team_id` returns `club: null`. Cross-season, not category/season-scoped. |

All of the above are server-rendered Next.js pages. Rather than scraping
visible HTML text, every fetcher locates the `<script id="__NEXT_DATA__"
type="application/json">` tag (a stable, markup-independent selector) and
parses its `props.pageProps` JSON directly — the page's actual data source,
not a re-derivation from rendered markup.

## Discovered JSON API endpoints

| Endpoint | Required params | Notes |
|---|---|---|
| `GET /api/seasons` | — | All seasons (`cod_temporada`/`nombre`/date range). |
| `GET /api/game-types` | — | All game types. |
| `GET /api/competitions` | `temporada`, `tipojuego` | Competitions for a season+game type; carries `NombreCategoria` for category filtering. |
| `GET /api/groups` | `competicion` | Groups within a competition. |
| `GET /api/results` | `idGroup`, `round` | **Found but not used** — returns a single round's matches, so covering a season would mean iterating `round` 1..N per group. The calendario page above returns the whole season in one request instead, which is strictly fewer requests for the same data. |

## robots.txt and enrichment

`https://www.rffm.es/robots.txt` explicitly disallows:
```
Disallow: /fichaequipo/
Disallow: /fichajugador/
Disallow: /acta-partido/
```
`/campo/` and `/fichaclub/` are **not** in this list. The core MVP
(calendario/clasificaciones/goleadores + `/campo/` + the `/api/*` discovery
endpoints) does **not** touch any disallowed path. The three still-disallowed
enrichment sources above are implemented but **off by default**
(`enrichment.fetch_acta_partido` / `enrichment.fetch_fichaequipo` /
`enrichment.fetch_fichajugador` in `config.yaml`), requiring an explicit,
informed opt-in per run — this is a deliberate policy choice, not a
limitation to work around. Note `fetch_fichaequipo` now gates both the
`enrich_clubs.py` stage (club identity, one representative team per club)
and the `enrich_team_clubs.py` stage (complete `team_id -> club_id`
mapping, every team) - see "Entities collected" below. `/fichaclub/` (`enrich_club_profiles.py`)
is legally fetchable without any opt-in - unlike `/campo/`, it's still
gated behind `enrichment.fetch_fichaclub` anyway, purely for consistency
with the other three enrichment stages, not because robots.txt requires it.

## Entities collected

- **Core (always collected):** seasons, game types, competitions, groups,
  teams, team-group membership, matches (fixtures+results, one table — see
  below), venues (playing fields: address, exact lat/lon, Google Maps link),
  standings, top scorers.
- **Enrichment (opt-in, `enrich_acta.py`):** match lineups, goals, cards,
  team staff (coaches/delegates), match officials (referees/field delegate).
- **Enrichment (opt-in, `enrich_players.py`):** player profiles, per-season
  player stats, per-player competition participation.
- **Enrichment (opt-in, `enrich_clubs.py`):** club identity (real RFFM
  `club_id`), website, correspondence address - one representative team per
  club, not every team (cheap, but leaves gaps when a club's teams have
  drifted `club_name_raw` spellings - see `enrich_team_clubs.py` below).
- **Enrichment (opt-in, `enrich_team_clubs.py`):** complete `team_id ->
  club_id` mapping (`team_club_map.csv`) - every team, not one
  representative per club, resolving exactly the gap `enrich_clubs.py`
  leaves. Cross-season: a `team_id`'s `club_id` is fetched at most once
  ever, regardless of how many seasons it appears in - see
  `DATA_DICTIONARY.md`.
- **Enrichment (opt-in, `enrich_club_profiles.py`):** full club profile
  (registered + correspondence address, socials, contact info, founding
  date) and every team the club has ever fielded - from `/fichaclub/<club_id>`,
  cross-season (not season-scoped, unlike every other enrichment stage).
  Append-only snapshot tables, not upserted - see `DATA_DICTIONARY.md`.

### matches.csv vs fixtures.csv

Both describe the same underlying matches — this repo materializes
`fixtures.csv` as **a filtered view of `matches.csv`** (`is_finished ==
False`), not a separate source or a duplicate table. `matches.csv` is the
complete, authoritative table (played and unplayed); `fixtures.csv` exists
purely as a convenience view of what's still upcoming/unplayed.

## Data dictionary and how to query the data

`CLAUDE.md` routes an analytics question to the right table (kept short —
it's auto-loaded into every session in this repo); **`DATA_DICTIONARY.md`**
has the full column-by-column schema, table relationships, and ready-to-run
pandas join recipes (including a worked "results between two clubs"
example). See `CLAUDE.md`'s "Why one file" section for why each concern
lives in exactly one of these.

## What's collected (current state)

- ✅ **2025-2026, all categories**: 1,210 groups, 248 competitions, 118,078
  matches, 708 venues, 10,521 standings rows, 113,966 scorer rows, 9,237
  teams (`--all-categories` core crawl, ~66 min against the live site).
  `acta_partido`/`fichajugador` enrichment is complete for **both**
  BENJAMÍN and PREBENJAMÍN (23,351 matches / 37,290 players between them) -
  still category-scoped by design, not yet dispatched for other categories.
  `clubs.csv`: 674 unique clubs resolved from 1,146 target teams (not
  category-scoped - covers every category present in this season's core
  data); 326 targets never returned a usable `codigo_club` (real gaps on
  RFFM's own fichaequipo pages, not fetch failures - every one of those 326
  requests came back HTTP 200, see `clubs_crawl_log.csv`) and 93 targets
  resolved to a `club_id` some other target had already covered (see
  `clubs_data_quality_report.csv`'s `club_coverage_gap` /
  `redundant_club_target` rows).
- ✅ **2024-2025, all categories (core only)**: a second season, 1,201
  groups, 223 competitions, 114,554 matches, 689 venues, 9,193 teams -
  demonstrates the multi-season storage layout; no enrichment run yet.
- ✅ **club_profiles (cross-season)**: first full backfill (2026-08-19)
  covered all 1,054 `club_id`s known across every season's `clubs.csv`
  (2016-2017 .. 2025-2026) - 685 resolved to a real `/fichaclub/` profile
  (8,946 team-roster rows total), 369 returned `club: null` (a stale/defunct
  `club_id` from an older season, not a fetch failure - see
  `DATA_FINDINGS.md`). 0 fetch failures out of 1,054 requests.
- ⚠️ Fallback/limited by design: acta-partido/fichaequipo/fichajugador
  enrichment is disabled by default (robots.txt). acta_partido/fichajugador
  are additionally category-scoped (`--scope`), typically piloted on one
  category before widening; `enrich_clubs.py`/`enrich_team_clubs.py` are
  **not** category-scoped (see "Entities collected" above) - one run covers
  every club/team regardless of category.
- ⚠️ Not modeled: match substitutions (zero populated examples found in the
  BENJAMÍN/PREBENJAMÍN age brackets — nothing to validate a schema against
  yet), `otras_tarjetas`, full multi-season player career history (player
  profiles are fetched for 2025-2026 only, though the site holds history
  back to 2020-2021 per player).

## Project layout

```
config.yaml            # URL patterns, target season/categories, network policy
OPERATIONS.md           # how to run/extend the crawl + GitHub Actions + resumability internals
DATA_DICTIONARY.md      # full schema: every table/column, join recipes, worked examples
main.py                # core crawl: discovery + calendario/clasificaciones/goleadores/campo → CSVs
enrich_acta.py          # opt-in: match lineups/goals/cards/staff/officials
enrich_players.py       # opt-in: player profiles/season stats
enrich_clubs.py         # opt-in: club identity/correspondence address
enrich_team_clubs.py    # opt-in: complete team_id -> club_id mapping, cross-season
enrich_club_profiles.py # opt-in: full club profile + team roster, cross-season
.github/workflows/
  rffm-crawl.yml          # manually-dispatched crawl job (any stage), commits+pushes on success
rffm_scraper/
  config.py             # typed Settings loaded from config.yaml
  http_client.py         # retry/backoff/rate-limit/crawl-log HTTP client
  discovery.py            # Stage A: /api/* discovery of competitions/groups
  fetchers.py              # Stage B: page fetchers (__NEXT_DATA__ extraction)
  parsers.py                # Stage C: page JSON → row dicts (matches/standings/scorers/venues)
  acta_parsers.py             # match report JSON → lineups/goals/cards/staff/officials
  fichajugador_parsers.py       # player profile JSON → player/season-stats/participation
  club_parsers.py                # fichaequipo JSON → club identity/address
  team_club_parsers.py            # fichaequipo JSON → team_id -> club_id mapping row
  club_profile_parsers.py         # fichaclub JSON → club profile/team roster
  normalize.py                   # category matching, dates, team-name/suffix parsing
  models.py                       # pydantic row schemas (one per CSV)
  row_io.py                        # shared CSV validation/writing/atomic-write/coverage-manifest/resumability helpers
  pipeline.py                       # core orchestration (incl. venue fetch)
  acta_pipeline.py                   # match-report enrichment orchestration (batched, resumable)
  player_pipeline.py                   # player-profile enrichment orchestration (batched, resumable)
  club_pipeline.py                      # club enrichment orchestration (batched, resumable)
  team_club_pipeline.py                  # team_id -> club_id resolution (batched, resumable, cross-season outputs)
  club_profile_pipeline.py               # club-profile enrichment orchestration (cross-season, append-only)
  quality_checks.py / acta_quality_checks.py / player_quality_checks.py / club_quality_checks.py / team_club_quality_checks.py / club_profile_quality_checks.py

output/processed/rffm/
  coverage_manifest.csv  # cross-season index: is season × category × stage done?
  2025-2026/*.csv         # one directory per season
  2026-2027/*.csv
```
