# RFFM data collector — BENJAMÍN / PREBENJAMÍN, multi-season

Production-minded scraper for the Real Federación de Fútbol de Madrid (RFFM)
website (`https://www.rffm.es`). Covers competitions, groups, teams,
fixtures/results, standings, and top scorers for the **BENJAMÍN** and
**PREBENJAMÍN** base categories, discovered dynamically (not hardcoded)
across every game type the federation runs (Fútbol-7, Fútbol Sala, ...).
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
lineups/goals/cards/staff/officials) and `enrich_players.py` (player
profiles/season stats).

## Storage layout and resumability across many seasons

`output/processed/rffm/<season_label>/*.csv` — every season gets its own
directory (e.g. `2025-2026/`, `2026-2027/`), so re-running for a new season
never touches another season's committed files. The one exception is
`output/processed/rffm/coverage_manifest.csv`, a small cross-season index
(one row per `season × category × stage`) telling you at a glance whether a
given combination is `complete`, `complete_with_failures`, or still
`partial` — see `CLAUDE.md`'s "Is this season/category/stage done?" section
for the full schema and how to query it.

Raw HTML is deliberately **not** committed or persisted between environments
(git-ignored, as always) — so the two slow enrichment stages
(`enrich_acta.py`, `enrich_players.py`, which can mean tens of thousands of
rate-limited requests) are resumable purely from what's already committed:
on every run, a target is skipped if `{stage}_crawl_log.csv` already has a
successful fetch recorded for it, regardless of which machine or environment
originally fetched it. Output is flushed in batches (`csv_flush_every` in
`config.yaml`) as the crawl proceeds, not just once at the end, so a run
that gets interrupted (killed process, CI job timeout) only ever loses at
most one partial batch — the next run picks up exactly where it left off.

## Running via GitHub Actions

`.github/workflows/rffm-crawl.yml` runs any stage (`core` / `acta_partido` /
`fichajugador`) as a manually-dispatched job (`workflow_dispatch`, inputs:
season, stage, category scope), bounded by `timeout-minutes` so a job that
can't finish a season's full target list in one run just stops cleanly
mid-batch and commits whatever it got done — the resumability described
above means the next dispatch continues from there, with no manual
babysitting required for the actual crawl.

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

Discovery output is saved as a timestamped JSON manifest under
`output/raw/rffm/discovery/manifest_<season_id>_<timestamp>.json`.

## Discovered URL patterns

| Kind | Pattern | Notes |
|---|---|---|
| Calendario (fixtures+results) | `/competicion/calendario?temporada=&competicion=&grupo=&jornada=&tipojuego=` | **Returns every jornada for the group in one request**, regardless of the `jornada` value — used as the single source for the whole season's matches per group. `jornada=1` is always passed since the param is required by the route but ignored by the response. |
| Clasificaciones (standings) | `/competicion/clasificaciones?temporada=&competicion=&grupo=&tipojuego=` | |
| Goleadores (top scorers) | `/competicion/goleadores?temporada=&competicion=&grupo=&tipojuego=` | Only fetched when the group's `clasificacion_goleadores` flag is `"1"`. |
| Acta de partido (match report) | `/acta-partido/<match_id>?temporada=&competicion=&grupo=` | Enrichment only, **off by default** — see robots.txt note below. |
| Ficha de equipo (team profile) | `/fichaequipo/<team_id>` | Enrichment only, **off by default** — see robots.txt note below. |
| Ficha de jugador (player profile) | `/fichajugador/<player_id>?temporada=` | Enrichment only, **off by default** — see robots.txt note below. |

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
The core MVP (calendario/clasificaciones/goleadores + the `/api/*` discovery
endpoints) does **not** touch any disallowed path. The three enrichment
sources above are implemented but **off by default**
(`enrichment.fetch_acta_partido` / `enrichment.fetch_fichaequipo` in
`config.yaml`), requiring an explicit, informed opt-in per run — this is a
deliberate policy choice, not a limitation to work around.

## Entities collected

- **Core (always collected):** seasons, game types, competitions, groups,
  teams, team-group membership, matches (fixtures+results, one table — see
  below), standings, top scorers.
- **Enrichment (opt-in, `enrich_acta.py`):** match lineups, goals, cards,
  team staff (coaches/delegates), match officials (referees/field delegate).
- **Enrichment (opt-in, `enrich_players.py`):** player profiles, per-season
  player stats, per-player competition participation.

### matches.csv vs fixtures.csv

Both describe the same underlying matches — this repo materializes
`fixtures.csv` as **a filtered view of `matches.csv`** (`is_finished ==
False`), not a separate source or a duplicate table. `matches.csv` is the
complete, authoritative table (played and unplayed); `fixtures.csv` exists
purely as a convenience view of what's still upcoming/unplayed.

## Data dictionary and how to query the data

Full column-by-column schema for every table (core + enrichment), table
relationships, and ready-to-run pandas join recipes (including a worked
"results between two clubs" example) live in **`CLAUDE.md`** — kept as the
single source of truth for the data model on purpose, see that file's "Why
one file" section for why it isn't duplicated here too.

## What's collected successfully vs. limited (2025-2026 pilot)

- ✅ Full 2025-2026 BENJAMÍN/PREBENJAMÍN coverage across Futbol-7 **and**
  Futsal: 408 groups, 43 competitions, 25,410 matches, 3,167 standings rows,
  26,003 scorer rows, 2,144 teams, in one ~20-minute run against the live
  site (1,272 HTTP requests, 33 quality-report findings — see
  `output/processed/rffm/2025-2026/data_quality_report.csv`).
- ⚠️ Fallback/limited by design: acta-partido/fichaequipo/fichajugador
  enrichment is disabled by default (robots.txt), and even when enabled is
  intentionally scoped to a category pilot before widening (see
  `enrich_acta.py --scope`).
- ⚠️ Not modeled: match substitutions (zero populated examples found in the
  BENJAMÍN age bracket — nothing to validate a schema against yet),
  `otras_tarjetas`, full multi-season player career history (player
  profiles are fetched for 2025-2026 only, though the site holds history
  back to 2020-2021 per player).

## Project layout

```
config.yaml            # URL patterns, target season/categories, network policy
main.py                # core crawl: discovery + calendario/clasificaciones/goleadores → CSVs
enrich_acta.py          # opt-in: match lineups/goals/cards/staff/officials
enrich_players.py       # opt-in: player profiles/season stats
.github/workflows/
  rffm-crawl.yml          # manually-dispatched crawl job (any stage), commits+pushes on success
rffm_scraper/
  config.py             # typed Settings loaded from config.yaml
  http_client.py         # retry/backoff/rate-limit/crawl-log HTTP client
  discovery.py            # Stage A: /api/* discovery of competitions/groups
  fetchers.py              # Stage B: page fetchers (__NEXT_DATA__ extraction)
  parsers.py                # Stage C: page JSON → row dicts (matches/standings/scorers)
  acta_parsers.py             # match report JSON → lineups/goals/cards/staff/officials
  fichajugador_parsers.py       # player profile JSON → player/season-stats/participation
  normalize.py                   # category matching, dates, team-name/suffix parsing
  models.py                       # pydantic row schemas (one per CSV)
  row_io.py                        # shared CSV validation/writing/atomic-write/coverage-manifest/resumability helpers
  pipeline.py                       # core orchestration
  acta_pipeline.py                   # match-report enrichment orchestration (batched, resumable)
  player_pipeline.py                   # player-profile enrichment orchestration (batched, resumable)
  quality_checks.py / acta_quality_checks.py / player_quality_checks.py

output/processed/rffm/
  coverage_manifest.csv  # cross-season index: is season × category × stage done?
  2025-2026/*.csv         # one directory per season
  2026-2027/*.csv
```
