# Operations — running and extending the RFFM crawl

Audience: whoever needs to actually **run, debug, or extend** the crawl
pipelines and the GitHub Actions workflow — not a first read of what this
project is (see `README.md`) and not analytics queries against the data
(see `CLAUDE.md`). Design rationale for the pipeline internals lives
primarily in code docstrings (`rffm_scraper/acta_pipeline.py`,
`player_pipeline.py`, `row_io.py`) — this file is the map to those plus
everything that isn't code (GitHub Actions mechanics, limits, how to
dispatch, how to test a change safely) and a couple of hard-won invariants
worth restating so they don't get silently broken.

## Dependency order

Four entrypoints. `enrich_clubs.py` only depends on step 1 (not on
`enrich_acta.py`), so it can run any time after `main.py` - it's listed
third here only because it's the newer addition, not because of an ordering
requirement:

1. `main.py` → `rffm_scraper/pipeline.py` — competitions/groups/teams/
   matches/venues/standings/scorers. Not category-scoped. ~20 min/season.
   Venues (`venues.csv`, one row per unique `codigo_campo` seen in this
   run's matches) are fetched here too, not a separate stage - `/campo/`
   isn't robots.txt-gated.
2. `enrich_acta.py` → `rffm_scraper/acta_pipeline.py` — match lineups/goals/
   cards/staff/officials. Reads `matches.csv`. Category-scoped, rate-limited,
   can take hours.
3. `enrich_clubs.py` → `rffm_scraper/club_pipeline.py` — club identity/
   correspondence address. Reads `teams.csv` (+ `matches.csv` for
   `season_id`). **Not** category-scoped, unlike the other two enrichment
   stages - a club is not an age-bracket concept, the same club routinely
   fields both a BENJAMIN and a PREBENJAMIN team, so every unique
   `club_name_raw` in `teams.csv` is a target regardless of category. One
   representative team per club, so the target count is roughly
   `teams.csv`'s row count divided by teams-per-club, not one request per
   team - a few hundred requests, not thousands.
4. `enrich_players.py` → `rffm_scraper/player_pipeline.py` — player
   profiles/season stats/participation. Reads `match_lineups/<category>.csv`
   (needs step 2 done first for the categories it targets). Same order of
   magnitude as step 2.

`config.yaml`'s `target.season_label` picks the season (not CLI-overridable
— see the workflow walkthrough below for why that matters);
`enrichment.acta_partido.scope_category` / `enrichment.fichajugador.scope_category`
pick the category, overridable per-run via each entrypoint's `--scope`
flag. `enrich_clubs.py` has no `--scope` - see point 3 above.

## Storage layout

`output/processed/rffm/<season_label>/*.csv` — one directory per season, so
a new season's crawl never touches another season's committed files.
`output/processed/rffm/coverage_manifest.csv` (see below) is the one
exception, living one level up since it's a cross-season index.
`output/raw/rffm/...` is git-ignored and never persisted between
environments by design — resumability does not depend on it surviving.

## Resumability — the two invariants to never accidentally break

Full design rationale is in `acta_pipeline.py`'s and `player_pipeline.py`'s
module docstrings. The short version, restated here because both were
violated once during development and are easy to reintroduce by accident:

1. **"Already done" must be the union of `{stage}_crawl_log.csv` successes
   AND presence in the primary output table**, not either alone. Crawl-log
   alone misses legitimately-zero-child-row targets that a naive presence
   check would (wrongly) call "never attempted"; primary-table alone misses
   the fact that a target can produce zero rows on purpose. Using crawl-log
   alone against the real PREBENJAMIN pilot data (whose original crawl_log
   predates this design and only ever recorded fresh HTTP fetches, never
   cache hits) found only 264/7618 acta targets and 345/9743 player targets
   "done" — enough to re-append thousands of duplicate rows on first run.
2. **Cache hits must synthesize their own crawl_log row.** A cache hit never
   touches the network client, so it never logs itself unless the pipeline
   does it explicitly (`parser_type: "html_next_data_cached"`). Skipping
   this silently breaks invariant #1's crawl-log half.

Also: rereading an output table for the end-of-run quality-check pass must
force known id columns to `str` (`_ID_COLUMNS` in both `_reread_table`
helpers) — plain `pd.read_csv(path)` promotes an all-numeric id column like
`match_id` to `int64`, which then fails to merge against the `dtype=str` id
columns used everywhere else in this codebase.

Batching: every `csv_flush_every` targets (`config.yaml`, default 200), a
batch is atomically merged into each output CSV
(`row_io.append_or_write_csv`) and one `coverage_manifest.csv` row is
upserted with `status="partial"`. The final flush re-reads the fully
consolidated tables from disk (not the in-memory batch, which after a
resume only holds this run's new rows) before running quality checks and
writing the final `status` (`complete` / `complete_with_failures`).

## coverage_manifest.csv

One upserted row per `(season, category_base, stage)`. `category_base` is
`"ALL"` for `core` (not category-scoped). Columns: `season, season_id,
category_base, stage, status, targets_total, targets_completed,
targets_failed, started_at, last_updated_at, completed_at, notes`. `status`
∈ `partial | complete | complete_with_failures`. Only updates when a run
flushes/finishes — a still-running job's live progress is in its log, not
here (see "Checking progress" below).

## The GitHub Actions workflow (`.github/workflows/rffm-crawl.yml`)

- **Trigger**: `workflow_dispatch` only (no `schedule:` cron yet —
  deliberate, add one once this has run cleanly a few times).
- **Inputs**: `season_label` (free text, must exist in the site's
  `/api/seasons`), `stage` (`core`/`acta_partido`/`fichajugador`/`clubs`),
  `scope_category` (free text, ignored for `core`), `workers` (integer,
  default 0 = use `config.yaml` value; ignored for `core`). Currently
  `config.yaml` defaults all three enrichment stages to `workers: 8`.
- `permissions: contents: write` for the final push via the default
  `GITHUB_TOKEN` — no extra secrets.
- `concurrency` grouped on `(season_label, stage)`, `cancel-in-progress: false`
  — same season+stage dispatches queue instead of racing on the same files.
- `timeout-minutes: 300`, intentionally under GitHub's hard 6h/job ceiling.
- Steps: checkout → setup Python 3.12 → `pip install -r requirements.txt` →
  patch `config.yaml`'s `target.season_label` in place via an inline PyYAML
  snippet (works around the entrypoints not having a `--season` CLI flag;
  this edit is local to the runner and never committed — the final commit
  step only stages `output/processed`) → run the entrypoint matching
  `stage` → **commit and push, with `if: always()`**. That last condition
  matters: without it, a `timeout-minutes` cancellation skips any
  not-yet-started step by default, which would silently discard everything
  already flushed to the runner's disk. Commits only if `git diff --cached`
  is non-empty (a no-op resume correctly produces zero commits).

## Running a stage — recipe

New season: dispatch `core` once (this also produces `venues.csv`) →
dispatch `acta_partido` with `scope_category=<category>`, re-dispatching the
same inputs until `coverage_manifest.csv` shows
`complete`/`complete_with_failures` for that row → dispatch `fichajugador`
the same way. `clubs` only needs `core` done first and can be dispatched any
time after it (independently of `acta_partido`/`fichajugador`, and only
once per season - it covers every category in one pass, `scope_category` is
ignored), same re-dispatch-until-complete pattern for resuming an
interrupted run. Widening an already-`core`'d season to a new category:
skip straight to `acta_partido`/`fichajugador` with the new
`scope_category` (`clubs` needs no re-dispatch - it was never
category-scoped to begin with).

**Parallel workers for enrichment stages:** `acta_partido`, `fichajugador`,
and `clubs` all support parallel HTTP workers (`config.yaml`'s
`*.workers`, CLI `--workers N`, or the `rffm-crawl.yml` `workers` input).
Each worker gets its own `RffmClient` and independent rate-limit bucket, so
`workers=8` with `rate_limit_seconds=1.25` yields ~6 req/s vs ~0.8 req/s
serial. Empirically: 7 942 PREBENJAMIN matches (2022-2023) completed in
~22 min at 8 workers vs ~2.8 h serial; a 20 k-match category like INFANTIL
should fit in ~55 min. `crawl-all.yml` uses the config default (currently 8)
without needing any change. Set `workers: 1` in config (or `--workers 1`)
to revert to serial if you suspect a rate-limiting issue.

**Checking progress:**
- Live, while a job runs: Actions tab → the running job → expand the crawl
  step → lines like `fichajugador progress: 4250/9743 (cached=... fresh=...
  failed=...)`, emitted every `progress_report_every` targets (default 25 —
  much more frequent than the `csv_flush_every` batch-flush).
- After a job ends: `coverage_manifest.csv`, updated only by that job's
  flushes/final commit.

## Bulk orchestration (`crawl-all.yml`)

`crawl-all.yml` runs the entire backfill plan — all seasons, all stages, all
categories — as a self-chaining sequence of `rffm-crawl.yml` invocations.
It is the right tool when you want to "crawl everything and walk away."

### How it works

1. `crawl-all` runs. It installs pandas, calls
   `.github/scripts/next_crawl_step.py`, which reads `coverage_manifest.csv`
   and returns the next incomplete step from the hardcoded plan (see below).
2. It calls `rffm-crawl.yml` via `workflow_call` (synchronous — this runner
   blocks until the child finishes, including its `merge-to-main` job).
3. Once the child finishes (regardless of success/failure/cancel), it
   dispatches a **new** `crawl-all` run via `gh workflow run` and exits.
4. The new run repeats from step 1 — picks the next uncovered step —
   forming a self-sustaining chain until `next_crawl_step.py` exits 1
   ("all done").

Each link of the chain runs one crawl stage (≤ 5h), so the 6h job limit
is never hit. The chain is safe to interrupt at any time: re-dispatch
`crawl-all` manually and it continues from exactly where it stopped (the
manifest is the single source of truth, not any runner-local state).

### The plan

Ordered newest-to-oldest, full sequence per season:

```
core (--all-categories) → clubs → acta_partido × 10 categories → fichajugador × 10 categories
```

Categories in priority order: BENJAMIN, PREBENJAMIN, ALEVIN, INFANTIL,
CADETE, JUVENIL, AFICIONADO, SENIOR, VETERANOS, UNIVERSITARIO. OTHER
(cup/copa competitions) is excluded — no meaningful acta/fichajugador data.

Seasons with only BENJAMIN+PREBENJAMIN in `groups.csv` (crawled before
`--all-categories` existed) are flagged for core re-crawl automatically
by `next_crawl_step.py` — it detects the narrow category set and omits
those core rows from "done", forcing a full re-crawl with `--all-categories`
before any enrichment for the new categories is attempted.

### Running it

**Dry-run first** (prints the next step, does nothing):
> Actions → "RFFM crawl-all (orchestrator)" → Run workflow → `dry_run=true`

**Live run:**
> Actions → "RFFM crawl-all (orchestrator)" → Run workflow → `dry_run=false`

To stop the chain: simply don't re-dispatch after the current run finishes,
or cancel the currently-running `crawl-all`. The chain has no daemon process
— each link is an independent workflow run that ends cleanly.

### Error handling

- **Child `rffm-crawl` failed or cancelled**: `continue-on-error: true` on
  the call step means the dispatch still fires. The child's `merge-to-main`
  job (separate runner, `if: always()`) ensures partial data reached main
  before the next run starts. `next_crawl_step.py` will re-queue the same
  step since the manifest row is still `partial` or missing.
- **Dispatch step itself failed** (API flake): 3 retries with backoff. If
  all fail, the chain stops with an explicit error — re-dispatch manually.
- **All done**: `next_crawl_step.py` exits 1, `crawl-all` skips the crawl
  and dispatch steps and exits cleanly.

### Two-job structure of `rffm-crawl.yml`

`rffm-crawl.yml` now has two jobs:

- **`crawl`**: runs the pipeline, commits and pushes to the run-branch
  (`if: always()` so a timeout/cancel still pushes whatever was collected).
- **`merge-to-main`**: separate runner, `needs: crawl`, `if: always()`.
  Fetches the run-branch and rebases it onto main. Runs even when `crawl`
  was cancelled — this is the key guarantee that partial progress from a
  timed-out run reaches main before the next run does a fresh checkout.

## Experimental local parallel core crawl

`main.py` is sequential by default (`--workers 1`) and the GitHub Actions
workflow deliberately keeps that default. For an isolated local benchmark or
a deliberately approved high-throughput run, core accepts these overrides:

```powershell
python main.py `
  --season 2024-2025 `
  --output-dir C:\temp\rffm-2024-2025-test `
  --all-categories `
  --workers 12 `
  --limit-groups 60 `
  --progress-report-every 10 `
  --log-level INFO
```

- `--season` changes only the in-memory target season; it does not rewrite
  `config.yaml`.
- `--output-dir` is required in practice for a limited or experimental run so
  it cannot replace a season's tracked output.
- `--limit-groups` processes the first `N` discovered groups and records the
  resulting core row in `coverage_manifest.csv` as `partial`. It is a test
  facility, not a resumable full-core mode.
- `--workers` parallelizes three independent stages: `/api/groups` discovery,
  group pages, and `/campo/<venue_id>` pages. Each worker owns its own HTTP
  session and rate limiter; worker results are collected centrally in stable
  discovery order before CSVs are built, avoiding concurrent CSV writes.
- `--progress-report-every` emits a heartbeat with completed targets, rate,
  and elapsed time. This fixes the previous core behaviour where logs could
  be silent until the final CSV writes.

### Throughput guardrails

The configured `network.rate_limit_seconds` applies **per worker** in this
experimental mode. Increasing workers therefore increases aggregate request
rate; it is not merely a local CPU setting. Start with a limited isolated run,
inspect `crawl_log.csv` for non-200 responses, and do not start a full run if
there are `429`, timeouts, or server errors.

A 12-worker all-category test for 2024-2025 on 2026-08-02 completed discovery
of 223 competitions / 1,201 groups in about 19 seconds, then processed an
isolated 60-group sample in about 51 seconds and its 347 venues in about 42
seconds. All 757 requests returned HTTP 200 and output keys had no duplicates.
The measured group rate was about 1.17 groups/second, so 12 workers did **not**
demonstrate a five-minute full-season crawl; it suggests roughly 17 minutes
for the group phase before discovery, venue fetches, parsing, and writes.
Treat five minutes as an unproven target, not an operating promise.

### Full local run: 2024-2025 core, 24 workers (2026-08-03)

Following up on the 12-worker sample above, a **full, non-sample** core crawl
of 2024-2025 (both categories) was run manually on a local machine —
**not through the GitHub Actions workflow**, which still defaults to
`--workers 1` (see above). This was a one-off, deliberately-approved run to
get real season data and a real throughput number, not a pipeline-safety
test — it wrote directly to the tracked `output/processed/rffm/2024-2025/`
(no `--output-dir` override), unlike the "testing pipeline changes safely"
recipe below, which always uses a scratch dir.

Command:

```powershell
python main.py --season 2024-2025 --all-categories --workers 24 --log-level INFO
```

Result: discovery (223 competitions / 1,201 groups) in ~13s, then all 1,201
groups plus 689 venues in ~409s, for a wall time of about **7m22s**
(00:37:59–00:45:21 UTC+2) end to end — comfortably under the 12-worker
projection. 4,465 HTTP requests logged, 4,464 returned 200; one
`group_goleadores` (scorers) page returned 500 and exhausted its retries
(`data_quality_report.csv` / `crawl_log.csv` have the one row) — the run
continued and finished normally, since a single-target failure doesn't
abort the whole core stage. No 429s. `coverage_manifest.csv` records this
row as `season=2024-2025, category_base=ALL, stage=core, status=complete,
targets_completed=1201/1201, targets_failed=0`.

Sustained group-processing throughput was about **1,201 groups / 359s ≈
3.3 groups/second** — roughly 2.9× the 12-worker test's 1.17 groups/s from
a ~2× worker increase, so 24 workers *did* help here, slightly better than
linearly (plausible reasons: the 12-worker sample's 60 groups were an
unusually heavy subset — 12,089 matches, 347 venues — not fixed per-request
overhead amortizing better at 24). This is one run, not a swept benchmark;
treat "24 is clearly better than 12" as supported for this one season, and
48 workers as still untested and a higher risk of tripping RFFM's
(unknown) rate limiting.

This run was a manual/local exception, not a change to the default
workflow. The GitHub Actions path (`--workers 1`, see above) remains the
plan for any crawl meant to be reproducible and unattended going forward;
raising its default worker count is a separate, not-yet-made decision that
should follow the same "isolated test → inspect `crawl_log.csv` → then
scale" pattern used here.

## GitHub Actions limits that apply here

- **Minutes**: only metered on private repos (public repos: unlimited on
  hosted runners, any plan). Private: Free 2,000/mo, Pro/Team 3,000/mo,
  Enterprise Cloud 50,000/mo; Linux runners (`ubuntu-latest`, used here)
  count at 1× (Windows 2×, macOS 10×). Check actual usage at github.com →
  Settings → Billing and plans → Plans and usage → Actions (owner-only,
  not queryable via any tool available to an agent session). Going public
  removes the limit but exposes real names of children (BENJAMÍN/
  PREBENJAMÍN, ~6-9 y/o) — private was a deliberate choice.
- **Per-job hard ceiling**: 6h, non-negotiable. `timeout-minutes: 300` here
  is intentionally under it.
- **Concurrent jobs**: 20 for Free/Pro on Linux — not a practical constraint
  given the `concurrency` group already serializes same-season-same-stage.
- **Git blob size**: GitHub warns >50MB, blocks >100MB per file without Git
  LFS. Acta enrichment tables are now split per-category
  (`match_lineups/ALEVIN.csv` etc.) — largest file ~25MB; headroom is safe
  even for the biggest category.

## Testing pipeline changes safely

Never validate a resumability/batching change against the real committed
season data first — this recipe caught two real bugs (the union-check gap,
the int64/dtype merge failure) before they touched anything committed:

1. Scratch directory outside the repo; copy `config.yaml` in, point
   `paths.output_dir` at the scratch dir, shrink `csv_flush_every`/
   `progress_report_every` to force multiple batches on a tiny sample.
2. Copy a handful of real rows (`dtype=str`) from real `matches.csv`/
   `match_lineups/<category>.csv`, restricted to a small target set (~8 items).
3. Copy the matching raw HTML cache files for that small set from the real
   `output/raw/rffm/...` tree — the run should be fully offline.
4. Run the real entrypoint against the scratch config. Assert: no duplicate
   id rows in the output; `coverage_manifest.csv` reaches `complete`; a
   second run reports `processed_this_run: 0`; and — the check that
   actually caught the union-check bug — a run with the scratch
   `{stage}_crawl_log.csv` deleted but the primary output table intact
   *also* reports `processed_this_run: 0`, not a full re-download.

## Current state

Check `coverage_manifest.csv` for the live picture. As of this writing,
season 2025-2026: `core` complete via an `--all-categories` GitHub Actions
dispatch (11 `category_base` values, not just BENJAMÍN/PREBENJAMÍN - see
`DATA_DICTIONARY.md`'s "Category taxonomy"), including `venues.csv`;
`acta_partido` and `fichajugador` complete for **both** BENJAMÍN and
PREBENJAMÍN; `clubs` `complete_with_failures` (674 unique clubs from 1,146
targets across every category, 326 genuine `codigo_club` gaps on RFFM's own
pages - not fetch failures, see `clubs_data_quality_report.csv`). No other
categories have acta_partido/fichajugador enrichment yet. Season 2024-2025:
`core` complete (all categories, via the manual 24-worker run above, not
GitHub Actions), including `venues.csv`; no enrichment stages started yet.

## Fixing `complete_with_failures` — `retry_check.py`

`coverage_manifest.csv` marks a stage `complete_with_failures` when some
targets were attempted but produced no output. Two failure modes exist:

**acta_partido / fichajugador** — a success=False row in the stage crawl log
(`acta_crawl_log.csv` / `fichajugador_crawl_log.csv`). Typical cause:
HTTP 200 but `__NEXT_DATA__` was absent or empty at fetch time (transient
rendering issue on the site). The data is often available if you re-fetch.

**clubs** — no failed log row exists. The pipeline writes success=True for
every HTTP fetch that returned a page; `missing` is computed as
`target_team_ids − done_ids`. Missing means the page had no `codigo_club`
in `pageProps.team` — either a structural gap (phantom teams, university
teams, newly registered school clubs — see `DATA_FINDINGS.md`) or a
transient rendering issue. The distinction matters: structural gaps are
permanent and not worth retrying.

### `analysis_scripts/retry_check.py`

Checks each failed/missing target live against the site and shows which are
now retryable (data present), then optionally clears the log entries so the
next orchestrator run re-fetches only those targets.

```bash
# Show what's retryable (read-only):
python analysis_scripts/retry_check.py --workers 6

# Only check specific stages:
python analysis_scripts/retry_check.py --stages acta_partido fichajugador

# Check and fix (prompts before writing):
python analysis_scripts/retry_check.py --fix --workers 6

# Check and fix, clubs only:
python analysis_scripts/retry_check.py --fix --stages clubs
```

What `--fix` does per stage type:
- **acta_partido / fichajugador**: deletes the `success=False` log rows for
  retryable IDs → pipeline sees them as not-yet-attempted on next run.
- **clubs**: deletes the `success=True` log rows for retryable team_ids →
  pipeline re-fetches them (they fall out of `done_ids`).

Both: reset the manifest row to `status=partial` so the orchestrator queues
the stage again.

After running `--fix`: commit the modified `*_crawl_log.csv` and
`coverage_manifest.csv`, then trigger `crawl-all.yml` on GitHub Actions.
