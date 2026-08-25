# PARQUET_CLOSURE.md — the CSV↔Parquet git storage policy

Not the data model (`DATA_DICTIONARY.md` owns "which copy to query, what's
in it") and not the crawl mechanics (`OPERATIONS.md` owns `coverage_
manifest.csv`'s actual columns/status semantics and how the crawl sets
them). This file owns a narrower, cross-cutting question: **for a given
table, which physical format — the CSV the crawler writes, or its derived
Parquet copy — actually gets committed to git, when, and why.** Read this
before touching `analysis_scripts/build_parquet.py`, `analysis_scripts/
parquet_closure.py`, `.github/workflows/parquet-build.yml`, or either
`.claude/hooks/session-start*.sh` — not needed for writing an ordinary
query (`DATA_DICTIONARY.md`'s "Two copies of the data" section is enough
for that, and links here for the rest).

## The core rule, in one line per case

- **Closed** `(season, stage)` → its Parquet file is committed to git;
  its source CSV eventually gets deleted (manually — see "Closing" below).
- **Open** `(season, stage)` → its Parquet file is **never committed** —
  regenerated on demand instead. The source CSV stays the git-tracked
  copy of record.
- **Never closes, by design** — `clubs.csv` (stage `clubs`) and
  `clubs_extended.csv`/`club_teams.csv` (stage `club_profiles`): always
  open, same treatment as above, forever. See "Why some data never
  closes" below.
- **Structurally out of scope** — `players.csv`/`players_current.csv`:
  deduped to one row per `player_id` across all seasons, so there's no
  per-season partition for "closed" to even apply to. Its own precedent
  predates this whole policy (see "Where this started" below) and still
  works differently: `players_current.csv` is the permanent git-tracked
  canonical source; `players.parquet` is gitignored and rebuilt on demand,
  always — not because it's "open", but because it can't be partitioned
  at all.
- **Not a table at all** — `career_analysis_*.csv`/`player_career.xlsx`
  (stray Jupyter notebook output, no pipeline generator) and
  `club_scorecard/*.csv` (a WIP draft for a future site page, meant to stop
  existing as a standalone file once that page exists). Neither is
  produced by anything this policy governs — see their entries in
  `DATA_FINDINGS.md` for the full story on each.
- **`coverage_manifest.csv` itself** stays CSV, permanently, for a
  different reason entirely: it's the tiny, cross-season index this whole
  policy reads to decide everything else, and its value is being directly
  `git diff`-able in a PR — not part of this scheme, just adjacent to it.

## How "closed" is actually decided

`analysis_scripts/parquet_closure.py` is the one place this logic lives —
read its module docstring for the full reasoning; summarized:

- A `(season, stage)` is closed when `coverage_manifest.csv` shows
  `status == "complete"` for **every** `category_base` row of that pair —
  strictly `"complete"`, not `complete_with_failures`. That distinction
  matters: `OPERATIONS.md`'s `retry_check.py --fix` can and does reset a
  `complete_with_failures` row back to `partial` for a later re-crawl
  attempt, so it is not a safe "this will never change again" signal, no
  matter how long it's sat that way.
- `core` is `category_base="ALL"` (one row per season). `acta_partido`/
  `fichajugador`/`clubs` can have several category rows per season, and
  **all** of them must read `"complete"` — a season with 10 of 11
  `fichajugador` categories done still counts open. (The alternative —
  splitting `match_lineups`/etc. into one Parquet file per `(season,
  category)` instead of per season, so one category could close
  independently of its siblings — was considered and deliberately not
  done, since it means restructuring already-committed files. Revisit if
  a single long-tail category routinely holds a whole season open for
  months.)
- `crawl_log`/`data_quality_report` merge all four stages' rows for a
  season into one Parquet file each (`log_family` column) — the strictest
  case, closed only once `core` **and** `acta_partido` **and**
  `fichajugador` **and** `clubs` are all closed for that season.
- Check the live state any time: `python analysis_scripts/
  parquet_closure.py` (`--table <name>` / `--stage <stage>` to narrow it).
  Read-only — never writes, commits, or deletes anything.

## Why some data never closes

Two stages sit at "always open" not because they haven't finished yet, but
because the concept of "finished" doesn't apply to them:

- **`clubs` stage (`clubs.csv`).** Every season currently reads
  `complete_with_failures` — and per `OPERATIONS.md`, most of those
  "failures" are permanent structural gaps (phantom teams, university
  teams with no real club page), not a transient crawl issue worth
  retrying. It may also keep getting manual corrections indefinitely. It's
  tiny either way (1.6MB CSV / 720KB Parquet total across all 10 seasons,
  measured) — deliberately **not** special-cased to treat
  `complete_with_failures` as "good enough" despite the negligible size;
  the project owner's call was that perpetually-refinable data never gets
  its Parquet committed, full stop, size notwithstanding.
- **`club_profiles` stage (`clubs_extended.csv`/`club_teams.csv`).** No
  season dimension at all, and a `"complete"` manifest row here means only
  "the last `enrich_club_profiles.py` run finished" — `--force-refetch` is
  a deliberate, repeatable refresh (unlike `retry_check.py`'s genuine
  failure-retry for the other stages), so there's no state that ever means
  "this data is done." Hardcoded via `parquet_closure.STAGES_THAT_NEVER_
  CLOSE` rather than trusting the manifest's literal `"complete"` value,
  which would otherwise wrongly read as closed today.

## Old seasons keep changing — "old" is not "closed"

It's tempting to assume an old season is settled. It usually isn't, for
the enrichment stages specifically: `acta_partido`/`fichajugador` crawls
run per-category, sequentially, and can take months or years to finish a
single season — the 2017-2018 season's `acta_partido` stage was still
being actively crawled as late as August 2026, nine years after that
season was played. `coverage_manifest.csv`'s `status` for that specific
`(season, stage)` is the only signal that matters here — never the
season's calendar age. A season's `core` data (matches/standings/teams)
usually does settle once every fixture is played, which is why `core` is
closed for all 10 seasons as of this writing — but `acta_partido`/
`fichajugador` for that same season can (and currently do) stay open for
years afterward.

## Site builds and sessions: filling in what git doesn't have

Because an open `(season, stage)`'s Parquet file is never committed, a
plain `git clone` of this repo is missing it entirely — anything that
reads it (`rffm_data.py`, `analysis_scripts/*_v2.py`, an ad hoc DuckDB
query) needs it regenerated locally first, or hits `FileNotFoundError`.
Two places do that regeneration, at two different speeds:

- **`.claude/hooks/session-start.sh`** (sync, ~4s) — rebuilds only
  `players.parquet` (`build_parquet.py --players-only`), since that one's
  always missing on a fresh checkout regardless of open/closed status
  (see "structurally out of scope" above).
- **`.claude/hooks/session-start-open.sh`** (async, ~2min measured) —
  rebuilds every currently-open `(season, stage)` (`build_parquet.py
  --open-only`, which skips every already-closed season/table since
  that's already correct on disk via git checkout — ~4x faster than a
  full rebuild, which takes ~9min). Async because 2 minutes is too long to
  block every session start on; the accepted trade-off is a query in the
  first couple of minutes could race a still-open table, while every
  closed season has zero wait regardless.
- **`.github/workflows/pages-deploy.yml`** runs both rebuild steps
  synchronously before `build_site.py` — CI can afford the wait, and a
  partial site build (missing a report because its data wasn't ready) is
  worse than a slower one.

`rffm_data.py`/`analysis_scripts/*_v2.py` never know or care whether a
given Parquet file they're reading came from a git-committed closed
season or a just-regenerated open one — the read path is identical either
way. That's deliberate: the open/closed distinction is entirely a
git-storage decision, invisible to every report generator.

## What this buys — the actual git-history-compression argument

The measured motivation for all of the above, not just a stylistic
preference: a committed Parquet file is a zstd-compressed binary blob, and
git cannot delta binary blobs the way it deltas text — a full rewrite,
full size, no useful diff, on every commit that touches it. Two concrete
numbers from this project's own history:

- Partitioning by season alone (already in place before this policy)
  means an unchanged season's file is byte-identical across rebuilds, so
  git sees zero diff for it — only a season whose data actually changed
  produces a new commit-worthy file.
- `players.parquet` — deduped cross-season, can't be partitioned by season
  at all — was measured to cost noticeably more in git history committed
  as Parquet than the *same data* committed as CSV, despite the CSV being
  ~4x bigger per snapshot (see `build_parquet.py`'s `PLAYERS_CURRENT_CSV`
  comment for the exact figures). That comparison is what this whole
  policy generalizes: **don't commit a Parquet file at all until you're
  confident it will never need touching again** — write it to git history
  exactly once, ever, instead of repeatedly during however long a season
  takes to finish crawling.

Prior to this policy, `parquet-build.yml` committed every table's Parquet
on every run regardless of open/closed status — so an in-progress season
still got a fresh commit each time (bounded to that one season's own
partition file, not the whole table, but still real, repeated churn for
however many months/years that season's enrichment stays open). Now that
commit simply doesn't happen until the data is closed.

## Closing a `(season, stage)`

Committing its final Parquet **and** deleting its now-redundant source CSV
in the same action. This is a **separate, always-manual step** — never run
from `parquet-build.yml` or any scheduled workflow, never inferred
automatically, only on the project owner's explicit request, every time.
`parquet_closure.py`'s detector (above) identifies what's *eligible* to
close; the action that actually performs a close does not exist yet as of
this writing — deliberately not built ahead of being asked for, per the
same "never automatic" instruction.

## Where this started

`players.parquet`/`players_current.csv` (see "structurally out of scope"
above) is the original, narrower instance of this pattern — gitignored
Parquet, regenerate-on-demand, canonical CSV — that predates the general
open/closed policy and motivated it. The generalization to every other
table happened after a real production incident: `.github/workflows/
pages-deploy.yml` started reading `players.parquet` via a new v2 report
page and failed with `FileNotFoundError` on every run, because a fresh CI
checkout never had it (gitignored, and nothing rebuilt it before the site
build ran). Fixing that one table's gap directly led to asking the same
question of every other table — which is this document.
