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

## Operating this project (storage, resumability, GitHub Actions)

This section is written to be self-sufficient — enough for a fresh session
with no prior conversation history to correctly run, debug, and extend the
crawl without re-deriving any of this from git history or trial and error.

### System overview

- `config.yaml` is the single source for URL patterns, network policy, and
  **target scope**: `target.season_label` picks the season;
  `enrichment.acta_partido.scope_category` / `enrichment.fichajugador.scope_category`
  pick the category (both overridable per-run via the `--scope` CLI flag,
  season is **not** CLI-overridable — see the GitHub Actions step-by-step
  below for how the workflow works around that).
- Three independent entrypoints, which **must run in this dependency order**
  for a given season (each reads the previous stage's committed output as
  its target list):
  1. `main.py` → core pipeline (`rffm_scraper/pipeline.py`) — competitions,
     groups, teams, matches, standings, scorers. Not category-scoped (covers
     every configured category in one pass). Fast (~20 min/season).
  2. `enrich_acta.py` → acta-partido pipeline (`rffm_scraper/acta_pipeline.py`)
     — match lineups/goals/cards/staff/officials. Reads `matches.csv`.
     Category-scoped, rate-limited, can take hours for a full category.
  3. `enrich_players.py` → fichajugador pipeline (`rffm_scraper/player_pipeline.py`)
     — player profiles/season stats/participation. Reads `match_lineups.csv`
     (so it needs step 2 done first for the categories it targets).
     Category-scoped, rate-limited, same order-of-magnitude runtime as step 2.
- Every path is resolved through `Settings` (`rffm_scraper/config.py`):
  `processed_dir` = `output/processed/rffm/<season_label>/` (season-scoped),
  `processed_root` = `output/processed/rffm/` (parent — home of
  `coverage_manifest.csv`, the one cross-season file), `raw_dir` =
  `output/raw/rffm/` (git-ignored, **never persisted across environments by
  design** — see Resumability below for why that's safe).

### Storage layout

`output/processed/rffm/<season_label>/*.csv` — every season gets its own
directory (e.g. `2025-2026/`, `2026-2027/`), so re-running for a new season
never touches another season's committed files. The one exception is
`output/processed/rffm/coverage_manifest.csv` (see below), which is
deliberately *not* inside a season directory since its whole purpose is to
be the one cross-season index.

### Resumability model — read this before touching acta_pipeline.py/player_pipeline.py/row_io.py

The acta-partido and fichajugador pipelines share this design (the core
pipeline doesn't need it — it's fast enough to just always run start-to-finish).

**Target list**: recomputed fresh on every run from already-committed data
(`matches.csv` for acta targets, `match_lineups.csv` for player targets) —
never itself persisted, so it's always accurate as of the latest commit.

**"Already done" = the UNION of two signals** (both required — this is the
single most important thing to preserve in any future change here):
1. `{stage}_crawl_log.csv`'s rows where `entity_id` has `success == True`.
   Needed because a target can legitimately produce **zero child rows**
   (e.g. a match with no reported lineup on the site — a known, separately
   tracked anomaly) — presence-in-primary-table alone can't tell that apart
   from "never attempted."
2. The primary output table's id column itself (`match_lineups.csv`'s
   `match_id` / `players.csv`'s `player_id`). Needed because data can
   already be fully committed while its crawl_log under-counts it — this
   actually happened: the original PREBENJAMIN pilot's crawl_log only ever
   recorded *fresh* HTTP fetches, never cache hits (cache hits didn't touch
   the network client at all, pre-this-design), so replaying just signal
   #1 against that real data found only 264/7618 acta targets and
   345/9743 player targets "done" — using it alone would have re-appended
   (duplicated) thousands of already-committed rows on the very first run
   under the new code. Caught during verification (see "Testing pipeline
   changes safely" below) before it ever touched committed data.

   **Never remove either half of this union without re-testing against a
   copy of real committed data first.**

**Batching**: every `csv_flush_every` targets (`config.yaml`, default 200),
the pipeline atomically merges its accumulated batch into each output CSV
(`row_io.append_or_write_csv`: read existing + `pd.concat` + atomic
temp-file-then-`os.replace` write — chosen over a true file append because a
process killed mid-append can leave a torn last CSV line that breaks
parsing of the *whole* file) and upserts one `coverage_manifest.csv` row
with `status="partial"`. A cache hit (raw HTML already on the runner's disk
from earlier in the *same* run/environment) never touches the network
client, so it synthesizes its own crawl_log row (`parser_type:
"html_next_data_cached"`) rather than silently going unlogged — this was a
real bug found and fixed during initial verification, for the same reason
signal #2 above exists.

**Final flush** (once the whole target list is exhausted, across however
many dispatches that took): re-reads the fully consolidated tables from
disk — **not** the in-memory batch lists, which after a resume only hold
*this run's* newly-processed rows — runs the existing quality checks
against that, and writes the last `coverage_manifest.csv` row with
`status` = `complete` (every target has a recorded success) or
`complete_with_failures` (target list exhausted, but some never succeeded —
see the matching `*_data_quality_report.csv`/`*_crawl_log.csv` for which
ones).

**Gotcha already hit once**: re-reading a table with plain `pd.read_csv(path)`
(no `dtype`) promotes an all-numeric id column like `match_id` to `int64`,
which then fails to merge/join against the `dtype=str` id columns used
everywhere else in this codebase (`ValueError: You are trying to merge on
int64 and str columns`). Both `_reread_table` helpers
(`acta_pipeline.py`/`player_pipeline.py`) force known id columns to `str` via
an explicit `_ID_COLUMNS` dict at the top of each file — extend that dict if
a new id-like column is ever added to one of these output tables; don't call
`pd.read_csv(path)` on them directly elsewhere.

### coverage_manifest.csv

One upserted row per `(season, category_base, stage)` — `category_base` is
`"ALL"` for the `core` stage (not category-scoped), a real category value
(`"BENJAMIN"`/`"PREBENJAMIN"`) otherwise. Columns: `season, season_id,
category_base, stage, status, targets_total, targets_completed,
targets_failed, started_at, last_updated_at, completed_at, notes`.
`status` ∈ `partial | complete | complete_with_failures` (see Resumability
above for exactly when each is written). This file only updates when a run
actually flushes/finishes — mid-run state is visible live in a job's log,
not in this file, until that job's next flush or completion (see "Running a
stage" below).

### The GitHub Actions workflow, step by step

`.github/workflows/rffm-crawl.yml`:

- **Trigger**: `workflow_dispatch` only, deliberately — no `schedule:` cron
  yet. Add one once this has been watched run cleanly a few times; this is a
  deliberate, revisitable choice, not an oversight.
- **Inputs**: `season_label` (free text — must match a season the site's
  `/api/seasons` actually has), `stage` (choice: `core`/`acta_partido`/
  `fichajugador`), `scope_category` (free text, ignored for `core`).
- **`permissions: contents: write`** — needed for the final push using the
  default `GITHUB_TOKEN`; no extra secrets required.
- **`concurrency`**: grouped on `(season_label, stage)`, `cancel-in-progress:
  false` — two dispatches for the *same* season+stage queue instead of
  racing on the same files; different stages/seasons run in parallel fine.
- **`timeout-minutes: 300`** — deliberately under GitHub's hard 6-hour/job
  ceiling (see Limits below).
- **Steps, in order**:
  1. `actions/checkout@v4` — checks out whichever branch was selected in the
     dispatch UI.
  2. `actions/setup-python@v5`, Python 3.12.
  3. `pip install -r requirements.txt`.
  4. **Patch `config.yaml`'s `target.season_label`** — a small inline
     `python3 - <<'EOF' ... EOF` step using PyYAML: load `config.yaml`, set
     `cfg["target"]["season_label"]` to the dispatch input, write it back.
     This exists because none of the three entrypoints currently accept a
     `--season` CLI flag (only `--scope`/category is CLI-overridable) — this
     is the workaround. **This edit is local to the runner and never
     committed** (the final commit step only stages `output/processed`,
     never `config.yaml`), so the repo's `config.yaml` always stays at
     whatever was last hand-edited, unaffected by any dispatch. If a
     `--season` flag is ever added to the entrypoints, this step can be
     replaced with just passing that flag.
  5. One of three steps, gated by `if: inputs.stage == '...'`, runs the
     matching entrypoint (`python3 main.py` / `python3 enrich_acta.py
     --scope "<scope_category>"` / `python3 enrich_players.py --scope
     "<scope_category>"`).
  6. **Commit and push**, with **`if: always()`**. This was a real bug found
     and fixed after the first version: `timeout-minutes` cancelling the job
     skips any not-yet-started step by default, which would have silently
     discarded everything already flushed to the runner's disk if the crawl
     step ran out of time. `if: always()` makes this step run even after a
     timeout/failure in the previous step. It stages `git add
     output/processed`, commits only if `git diff --cached` is non-empty (a
     pure no-op resume — e.g. re-dispatching after everything's already
     done — correctly produces zero commits), and pushes to whichever
     branch was checked out.

### Running a stage — recipe

For a brand-new season: dispatch `core` once (fast, no `scope_category`
needed) → dispatch `acta_partido` with `scope_category=<category>`,
re-dispatching with the same inputs until `coverage_manifest.csv` shows
`status` = `complete`/`complete_with_failures` for that row → dispatch
`fichajugador` the same way (same `scope_category`).

To widen an already-`core`-covered season to a new category: skip straight
to `acta_partido`/`fichajugador` with the new `scope_category`.

**Checking progress:**
- *Live*, while a job runs: Actions tab → the running job → expand the
  crawl step → log lines like `fichajugador progress: 4250/9743 (cached=...
  fresh=... failed=...)`, emitted every `progress_report_every` targets
  (`config.yaml`, default 25 — independent of, and much more frequent than,
  the `csv_flush_every` batch-flush cadence).
- *After* a job finishes (success, failure, or timeout): `coverage_manifest.csv`
  — only updated by that job's flushes/final commit, so it won't reflect a
  still-running job.

### GitHub Actions limits that actually apply here

- **Minutes**: only metered on **private** repos (public repos get
  unlimited Actions minutes on hosted runners regardless of plan). Private:
  Free 2,000 min/month, Pro/Team 3,000 min/month, Enterprise Cloud 50,000
  min/month — Linux runners (`ubuntu-latest`, what this workflow uses) count
  at a 1× multiplier (Windows 2×, macOS 10×). Check actual remaining quota
  at github.com → Settings → Billing and plans → Plans and usage → Actions
  (owner-only page, not queryable via any tool available in this session).
  Flipping the repo to public removes the limit entirely, but weigh that
  against this being real names of children (BENJAMÍN/PREBENJAMÍN, ~6-9
  years old) before doing it — private was a deliberate choice, not a
  default left unexamined.
- **Per-job hard ceiling**: 6 hours, non-negotiable even on paid plans. This
  workflow's `timeout-minutes: 300` (5h) is intentionally under it.
- **Concurrent jobs**: 20 for Free/Pro on Linux runners — not a practical
  constraint here since the `concurrency` group already serializes same-
  season-same-stage dispatches.
- **Git blob size**: GitHub warns above 50MB and blocks above 100MB per file
  without Git LFS. The largest table today (`match_lineups.csv`, ~26MB) has
  headroom; re-check as more seasons/categories accumulate. If a single
  season+stage table ever approaches this, the fix is Git LFS or finer
  partitioning — not a pipeline code change.

### Testing pipeline changes safely

Never validate a resumability/batching change directly against the real
committed season data on the first try — this is the recipe that caught
both real bugs above before they touched anything committed:

1. Create a scratch directory *outside* the repo. Copy `config.yaml` into it
   and rewrite `paths.output_dir` to point at the scratch dir (and shrink
   `csv_flush_every`/`progress_report_every` to force multiple batches on a
   tiny sample).
2. Copy a handful of real rows (`dtype=str`) from the real `matches.csv` /
   `match_lineups.csv`, restricted to a small target set (e.g. 8 items).
3. Copy the matching raw HTML cache files for exactly that small set from
   the real `output/raw/rffm/...` tree, so the run is fully offline (no live
   network calls at all).
4. Run the real entrypoint against the scratch config. Assert: no duplicate
   `(match_id, player_id)`/`player_id` rows in the output; `coverage_manifest.csv`
   reaches `status=complete`; a second run against the same scratch dir
   reports `processed_this_run: 0` (idempotent); and — the check that
   actually caught the union-vs-crawl-log-alone bug — a run with the
   scratch `{stage}_crawl_log.csv` deleted but the primary output table left
   intact *also* reports `processed_this_run: 0`, not a full re-download.

### Current state (check `coverage_manifest.csv` for the live picture — this paragraph will go stale)

As of this writing, season 2025-2026: `core` complete (both categories,
~25.4k matches); `acta_partido` complete for PREBENJAMIN only (BENJAMIN not
started); `fichajugador` complete for PREBENJAMIN only (BENJAMIN not
started).

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
