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

Three entrypoints, must run in this order per season (each reads the
previous stage's committed output as its target list):

1. `main.py` → `rffm_scraper/pipeline.py` — competitions/groups/teams/
   matches/standings/scorers. Not category-scoped. ~20 min/season.
2. `enrich_acta.py` → `rffm_scraper/acta_pipeline.py` — match lineups/goals/
   cards/staff/officials. Reads `matches.csv`. Category-scoped, rate-limited,
   can take hours.
3. `enrich_players.py` → `rffm_scraper/player_pipeline.py` — player
   profiles/season stats/participation. Reads `match_lineups.csv` (needs
   step 2 done first for the categories it targets). Same order of
   magnitude as step 2.

`config.yaml`'s `target.season_label` picks the season (not CLI-overridable
— see the workflow walkthrough below for why that matters);
`enrichment.acta_partido.scope_category` / `enrichment.fichajugador.scope_category`
pick the category, overridable per-run via each entrypoint's `--scope` flag.

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
  `/api/seasons`), `stage` (`core`/`acta_partido`/`fichajugador`),
  `scope_category` (free text, ignored for `core`).
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

New season: dispatch `core` once → dispatch `acta_partido` with
`scope_category=<category>`, re-dispatching the same inputs until
`coverage_manifest.csv` shows `complete`/`complete_with_failures` for that
row → dispatch `fichajugador` the same way. Widening an already-`core`'d
season to a new category: skip straight to `acta_partido`/`fichajugador`
with the new `scope_category`.

**Checking progress:**
- Live, while a job runs: Actions tab → the running job → expand the crawl
  step → lines like `fichajugador progress: 4250/9743 (cached=... fresh=...
  failed=...)`, emitted every `progress_report_every` targets (default 25 —
  much more frequent than the `csv_flush_every` batch-flush).
- After a job ends: `coverage_manifest.csv`, updated only by that job's
  flushes/final commit.

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
  LFS. Largest table today (`match_lineups.csv`, ~26MB) has headroom;
  re-check as more seasons/categories accumulate.

## Testing pipeline changes safely

Never validate a resumability/batching change against the real committed
season data first — this recipe caught two real bugs (the union-check gap,
the int64/dtype merge failure) before they touched anything committed:

1. Scratch directory outside the repo; copy `config.yaml` in, point
   `paths.output_dir` at the scratch dir, shrink `csv_flush_every`/
   `progress_report_every` to force multiple batches on a tiny sample.
2. Copy a handful of real rows (`dtype=str`) from real `matches.csv`/
   `match_lineups.csv`, restricted to a small target set (~8 items).
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
season 2025-2026: `core` complete (both categories); `acta_partido` and
`fichajugador` complete for PREBENJAMIN only — BENJAMIN not started.
