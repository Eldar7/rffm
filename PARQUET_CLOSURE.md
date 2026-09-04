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

## The rule

| Case | Git-tracked copy | Parquet ever committed? |
|---|---|---|
| **Closed** `(season, stage)` | none — CSV deleted once closed | Yes, once, treated as final |
| **Open** `(season, stage)` | CSV (copy of record) | Never — regenerated on demand |
| **Never closes** (`clubs`, `club_profiles` stages) | CSV, forever | Never |
| **Structurally out of scope** (`players`) | `players_current.csv`, forever | Never (gitignored, always regenerated) |
| **The index this policy reads** (`coverage_manifest.csv`) | CSV, forever | n/a — not a data table, this file has no Parquet copy at all |
| **Not a pipeline table at all** | whatever it is, untouched | n/a — this policy doesn't apply |

`coverage_manifest.csv` stays CSV for a different reason than everything
else above: it's tiny, and its whole value is being directly `git diff`-able
in a PR — a Parquet copy would work against that, not for it.

## Table → owning stage

From `analysis_scripts/parquet_closure.py`'s `TABLE_STAGE` — the live
source of truth if this table ever drifts from the code:

| Stage | Tables |
|---|---|
| `core` | `matches`, `standings`, `scorers`, `groups`, `competitions`, `team_group_membership`, `teams`, `venues`, `game_types`, `seasons`, `manifest_groups`, `manifest_pages`, `manifest_endpoints` |
| `acta_partido` | `match_lineups`, `match_goals`, `match_cards`, `match_staff`, `match_officials` |
| `fichajugador` | `player_competition_participation`, `player_season_stats`, `players_by_season` |
| `clubs` | `clubs` |
| `club_profiles` (never closes) | `clubs_extended`, `club_teams` |
| n/a — merged log families | `crawl_log`, `data_quality_report` (need core **and** acta_partido **and** fichajugador **and** clubs all closed for that season — one file mixes all four) |
| n/a — structurally exempt | `players` (see "Where this started" below) |

## Current status (snapshot — re-run for the live answer)

`python analysis_scripts/parquet_closure.py`. As of 2026-08-25:

| Stage | Closed | Still open |
|---|---|---|
| `core` | all 10 seasons | — |
| `acta_partido` | 8/9 | 2017-2018 |
| `fichajugador` | 3/9 | 2017-2018, 2021-2022, 2022-2023, 2023-2024, 2024-2025, 2025-2026 |
| `clubs` | 0/10 | all 10 (see "Why some data never closes") |
| `club_profiles` | never applicable | always |

## How "closed" is actually decided

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
- Read-only, safe anytime: `python analysis_scripts/parquet_closure.py`
  (`--table <name>` / `--stage <stage>` to narrow it). Never writes,
  commits, or deletes anything.

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
  perpetually-refinable data never gets its Parquet committed, full stop,
  size notwithstanding.
- **`club_profiles` stage (`clubs_extended.csv`/`club_teams.csv`).** No
  season dimension at all, and a `"complete"` manifest row here means only
  "the last `enrich_club_profiles.py` run finished" — `--force-refetch` is
  a deliberate, repeatable refresh (unlike `retry_check.py`'s genuine
  failure-retry for the other stages), so there's no state that ever means
  "this data is done." Hardcoded via `parquet_closure.STAGES_THAT_NEVER_
  CLOSE` rather than trusting the manifest's literal `"complete"` value,
  which would otherwise wrongly read as closed today.

## Old seasons keep changing — "old" is not "closed"

`acta_partido`/`fichajugador` crawls run per-category, sequentially, and
can take months or years to finish a single season — the 2017-2018
season's `acta_partido` stage was still being actively crawled as late as
August 2026, nine years after that season was played.
`coverage_manifest.csv`'s `status` for that specific `(season, stage)` is
the only signal that matters — never the season's calendar age. `core`
data (matches/standings/teams) usually does settle once every fixture is
played (all 10 seasons are closed there as of this writing), but
`acta_partido`/`fichajugador` for the same season can, and currently do,
stay open for years afterward.

## Site builds and sessions: filling in what git doesn't have

An open `(season, stage)`'s Parquet file is never committed, so a plain
`git clone` is missing it — anything reading it needs it regenerated
locally first, or hits `FileNotFoundError`.

| What | Rebuilds | Mode | Speed |
|---|---|---|---|
| `.claude/hooks/session-start.sh` | `players.parquet` only | sync | ~4s |
| `.claude/hooks/session-start-open.sh` | every open `(season, stage)` | async | ~2min |
| `pages-deploy.yml` (both steps) | both of the above | sync | ~2min combined |

`--open-only` skips every already-closed season/table (already correct on
disk via git checkout) — ~4x faster than a full rebuild (~9min). The
SessionStart hook is async because 2 minutes is too long to block every
session start on; the accepted trade-off is a query in the first couple of
minutes could race a still-open table, while every closed season has zero
wait regardless. CI runs both synchronously instead — a partial site build
is worse than a slower one. Either way, `rffm_data.py`/`analysis_scripts/
*_v2.py` never know or care whether a Parquet file they're reading came
from git or was just regenerated on demand — the read path is identical.

## The git-history goal: one birth-commit per file, zero diffs, ever

The measured motivation for this whole policy: a committed Parquet file is
a zstd-compressed binary blob, and git cannot delta binary blobs the way
it deltas text — appending a second commit that touches the same file is a
full rewrite, full size, no useful diff, forever bloating repo history.
Two numbers from this project's own history: partitioning by season alone
means an unchanged season's file is byte-identical across rebuilds (zero
diff); `players.parquet` — deduped cross-season, can't be partitioned at
all — was measured to cost noticeably more in git history committed as
Parquet than the *same data* committed as CSV, despite the CSV being ~4x
bigger per snapshot (`build_parquet.py`'s `PLAYERS_CURRENT_CSV` comment
has the exact figures).

**The goal this policy is working toward: every committed Parquet file
should have exactly one commit in its entire git history — the commit
that created it — and never a second.** Closing late (only once
`coverage_manifest.csv` is strictly `"complete"`) is what makes that
achievable in the first place: a file committed too early and then
touched again by a routine commit is exactly the diff-cost this exists to
avoid.

**If a closed file ever does need to change** (a bug in
`build_parquet.py`'s type-handling, a `(season, stage)` closed prematurely
that turns out to need a correction) — the fix is **not** a new commit on
top of it. That would leave two versions in reachable history, the exact
outcome this policy exists to prevent. The fix is to **rewrite git history**
so the original birth-commit is amended/replaced in place (interactive
rebase, or an equivalent history-rewriting tool) and force-pushed, so
that file's history still shows exactly one version, ever — as if the
corrected content had been the only thing ever committed.

**This is a destructive operation on shared history** — the same class of
risk as any other force-push, and more consequential than the plain "close
= commit + delete CSV" action above, since it invalidates history anyone
else has already based work on. It follows the exact same rule as
closing and CSV deletion: **only ever on the project owner's explicit,
specific request, never automatically, never inferred, never bundled into
a routine workflow run.** Expected to be rare in practice — if closing is
only ever done once `coverage_manifest.csv` is genuinely `"complete"` (the
whole point of the strict rule above), a closed file needing correction at
all should be the exception, not something this policy routinely triggers.

## Enforcement — nothing used to stop a manual commit

`parquet_closure.py`'s closure logic was, until now, only ever consulted
by `parquet-build.yml`'s own git-add step (`--list-committable`). Nothing
stopped an ordinary `git add`/`git commit` from committing an open-season
or never-closing-stage Parquet snapshot anyway - e.g. after
`.claude/hooks/session-start-open.sh` regenerates one locally for
querying (which it's supposed to do, on disk only). Not hypothetical:
commits `d7bf2da`/`83ac65f` (`clubs/`, `clubs_extended.parquet`,
`club_teams.parquet`, `2017-2018` `acta_partido` - caught and reverted
within the same PR before it reached `main`) and `42fec3f`
(`crawl_log`/`data_quality_report` for every season - never reverted,
still committed on `main` as of this writing, ~39.5MB, even though
`log_family_closed_seasons()` is currently empty) both happened this way.

Two guards now close that gap, both driven by the same script,
`analysis_scripts/check_parquet_commit.py` (which just calls
`parquet_closure.py`'s existing functions - no separate policy to drift):

- **`scripts/git-hooks/pre-commit`** - a real git pre-commit hook that
  blocks staging a Parquet file for a `(table, season)` that isn't
  closed. `.git/hooks/` isn't itself git-tracked, so
  `.claude/hooks/session-start.sh` re-links it on every Claude Code
  session start (unconditional - cheap, no network); a contributor not
  using Claude Code installs it once with `bash scripts/git-hooks/install.sh`.
  Bypassable with `git commit --no-verify` for a deliberate, reviewed
  exception (project owner's call, same as everywhere else in this file).
- **`.github/workflows/check-parquet-closure.yml`** - the same check
  against a PR's full diff vs its base branch, independent of whether the
  hook was installed or was skipped. Read-only, doesn't commit anything.

The `42fec3f` cleanup (removing the currently-committed
`crawl_log`/`data_quality_report` files) hasn't been done - like closing
itself, deleting committed data is a separate, deliberate, project-owner
step, not something either guard above does on its own.

## Closing a `(season, stage)`

Committing its final Parquet **and** deleting its now-redundant source CSV
in the same action. A **separate, always-manual step** — never run from
`parquet-build.yml` or any scheduled workflow, never inferred
automatically, only on the project owner's explicit request, every time.
`parquet_closure.py`'s detector (above) identifies what's *eligible* to
close; the action that actually performs a close does not exist yet as of
this writing — deliberately not built ahead of being asked for.

## Where this started

`players.parquet`/`players_current.csv` is the original, narrower instance
of this pattern — gitignored Parquet, regenerate-on-demand, canonical CSV
— that predates the general open/closed policy and motivated it. It still
works slightly differently from everything else in the table above: it's
not "open", it's structurally exempt (deduped cross-season, no season
partition to close). The generalization to every other table happened
after a real production incident: `pages-deploy.yml` started reading
`players.parquet` via a new v2 report page and failed with
`FileNotFoundError` on every run, because a fresh CI checkout never had it
(gitignored, nothing rebuilt it before the site build ran). Fixing that
one table's gap directly led to asking the same question of every other
table — which is this document.
