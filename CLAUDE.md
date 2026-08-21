# CLAUDE.md — orientation for analytics sessions

This file is *auto-loaded into every session* in this repo (it's
`CLAUDE.md`), so it's kept deliberately lean: just enough to route an
analytics question to the right table and the right file. It is **not**
for implementing the scraper (see `README.md`: URL patterns, endpoints, how
the data was collected), **not** for running/extending the crawl pipelines
or GitHub Actions (see `OPERATIONS.md`), and **not** the full schema (see
`DATA_DICTIONARY.md` — exact columns, quirks, worked examples, join
recipes). **Before writing any actual query, read `DATA_DICTIONARY.md`** —
this file only tells you which table to look at, not its columns. If a
result looks wrong (unexpected NaNs, suspicious duplicates, counts that
seem off), check `DATA_FINDINGS.md` before assuming a bug — it records
known data quirks discovered through real queries.

## Scope

**BENJAMÍN**/**PREBENJAMÍN** was this project's initial development target,
**not** a permanent restriction — the crawler can discover and collect
every age/division category the federation runs (ALEVÍN, CADETE, INFANTIL,
JUVENIL, AFICIONADO, SENIOR, VETERANOS, UNIVERSITARIO, ...; see
`DATA_DICTIONARY.md`'s "Category taxonomy"), across every game type
(Futbol-7, Futbol-11, Futsal, as discovered — not hardcoded to one). A
given season's core crawl may or may not have used `--all-categories`
though — **don't assume scope from this file**; check that season's own
`groups.csv`/`competitions.csv` `category`/`category_base` values (or
`coverage_manifest.csv`'s `category_base` rows) for what it actually
covers. `clubs.csv`/`venues.csv` are never category-scoped (a club/venue
isn't an age-bracket concept) — they cover whatever categories that
season's core crawl found. `acta_partido`/`fichajugador` enrichment
*is* still category-scoped (`scope_category`) and is not necessarily run
for every category present in a season's core data — check
`coverage_manifest.csv`. Multiple **seasons** — starting with 2025-2026,
more added over time as separate crawls; always check
`coverage_manifest.csv` (below) for which season/category/stage
combinations actually have data before assuming a season is covered.

All tables live in `output/processed/rffm/<season>/*.csv` — one directory
per season, e.g. `output/processed/rffm/2025-2026/matches.csv`. This is a
**per-season partition**, not a duplicate/overlapping copy: re-running the
crawler for a new season writes to its own new directory and never touches
another season's files. The lone exception is `coverage_manifest.csv`
itself, which lives one level up at `output/processed/rffm/coverage_manifest.csv`
(see "Is this season done" below) since its whole purpose is to be the one
cross-season index. A compact, lossless copy of every table above also
lives at `output/processed/rffm_parquet/` (rebuilt from these CSVs by
`analysis_scripts/build_parquet.py`) — **default to querying that one**
for any new question, via DuckDB SQL or `pd.read_parquet`, not these CSVs
directly; see "How to answer a query" below and `DATA_DICTIONARY.md`'s
"Two copies of the data, two default tools" for why and exactly how the
two differ. Either way: answer questions by running a script (via Bash),
not by eyeballing rows.

## Is this season/category/stage done? — `coverage_manifest.csv`

Before trusting a season's numbers (especially for the enrichment stages,
which can take hours and run across multiple crawl sessions), check
`output/processed/rffm/coverage_manifest.csv` — one row per
`(season, category_base, stage)`. `status` is `complete`, `complete_with_failures`
(some targets never got a successful fetch — see `targets_failed`, and the
matching `*_data_quality_report.csv`/`*_crawl_log.csv` for which ones), or
`partial` (still running or was interrupted — `last_updated_at` tells you
how stale). Full column list and how/when this file gets written: `OPERATIONS.md`.

```python
import pandas as pd
coverage = pd.read_csv("output/processed/rffm/coverage_manifest.csv")
print(coverage[coverage["season"] == "2025-2026"])
```

One row is different: `stage == "club_profiles"` uses `season="ALL"` (a
synthetic key) since that stage is cross-season, not tied to any one
season's crawl — see `DATA_DICTIONARY.md`'s `clubs_extended.csv` entry.

## Tables at a glance

One line each — table name, PK, what it holds. **Exact columns, quirks,
FKs, and join recipes: `DATA_DICTIONARY.md`.**

Core (always collected):
- `competitions.csv` (`competition_id`) — season × category × phase
- `groups.csv` (`group_id`) — group within a competition
- `teams.csv` (`team_id`) — **a club is not a team**, see `DATA_DICTIONARY.md`
- `team_group_membership.csv` — team ↔ group/competition, this season
- `matches.csv` (`match_id`) — one row per fixture/result (`fixtures.csv` = unplayed-only view); `venue_id` FK → `venues.csv`
- `venues.csv` (`venue_id`) — one row per playing field: address + exact lat/lon + Google Maps link. Not robots.txt-gated, always collected.
- `standings.csv` — one row per team per group
- `scorers.csv` — aggregate top-scorer leaderboard per group
- `manifest_groups.csv` / `manifest_pages.csv` / `manifest_endpoints.csv` — discovery/fetch manifests
- `crawl_log.csv` / `data_quality_report.csv` — per-run HTTP log + anomaly findings

Enrichment (opt-in — see `README.md` for why opt-in, `OPERATIONS.md` for how/when populated):
- `match_lineups/<category>.csv` — per-match, per-player lineup (one file per scope_category)
- `match_goals/<category>.csv` — one row per goal event
- `match_cards/<category>.csv` — one row per card
- `match_staff/<category>.csv` — coaches/delegates per match
- `match_officials/<category>.csv` — referees/field delegate per match
- `players.csv` (`player_id`) — stable player identity (name, birth year)
- `player_season_stats.csv` — site-reported season aggregates per player
- `player_competition_participation.csv` — team/group registration per player (can be >1 row/player)
- `clubs.csv` (`club_id`, `enrich_clubs.py`) — one row per club: real RFFM club id, website, correspondence address (**not** a stadium address — see `DATA_DICTIONARY.md`)
- `team_club_map.csv` (`team_id`, `enrich_team_clubs.py`) — the complete `team_id → club_id` mapping, every team not just one representative per club. **Use this, not `club_name_raw`, whenever you need a `club_id` starting from a `team_id`** — `club_name_raw` drifts in spelling between teams of the same club. Cross-season, one row per `team_id` (not a snapshot log)
- `team_club_gap_reasons.csv` (`team_id`, also `enrich_team_clubs.py`) — why a `team_id` still isn't in `team_club_map.csv` (technical no-show, FASE ZONAL, non-federated local cup, ...). Cross-season, fully recomputed every run (not a snapshot log) — see `DATA_DICTIONARY.md`
- `clubs_extended.csv` / `club_teams.csv` (`enrich_club_profiles.py`) — richer club profile + every team the club has ever fielded, from `/fichaclub/<club_id>`. Cross-season, **append-only snapshot log** (not one row per `club_id` — see `DATA_DICTIONARY.md` for the "get current state" recipe)

## How to answer a query

**Procedure, every time:**
1. **Resolve names to IDs first.** Never filter `matches.csv`/`standings.csv`
   free-text columns directly by a club/player name the user typed — go
   through `teams.csv`/`players.csv` to get canonical `team_id`/`player_id`
   values, *then* filter everything else by ID. Free-text columns carry the
   site's raw formatting (quotes, accents, case) and are unreliable keys.
2. **Load only the tables the question needs** (table below).
3. **Query `output/processed/rffm_parquet/` by default** — one self-contained
   DuckDB SQL query (or `pd.read_parquet` if you'd rather stay in pandas)
   via Bash, no season loop for most tables. Fall back to the CSVs under
   `output/processed/rffm/<season>/` (pandas, `dtype=str`) only if you're
   working inside `analysis_scripts/*.py` report-generator code that isn't
   on the Parquet path yet, or need a column the Parquet copy drops (rare —
   see `DATA_DICTIONARY.md`). Either way: don't hand-inspect rows for
   anything beyond a first look.
4. **Sanity-check the row count** before presenting. Zero rows for two
   clubs/players that plausibly interacted is a signal something upstream
   is wrong (name typo, wrong scope, ID resolved against the wrong club),
   not necessarily a true negative.

**Question type → tables → join key:** (same table names in either copy —
`teams`/`matches`/etc., not `teams.csv`; `match_lineups/*` means glob
across categories for the CSVs, across seasons for the Parquet copy - see
"Two copies of the data" in `DATA_DICTIONARY.md`)

| Question | Tables | Join |
|---|---|---|
| Club vs. club results / head-to-head | `teams`, `matches` | `club_name_raw` → `team_id` list → `home_team_id`/`away_team_id` |
| What teams/levels does a club field this season | `teams`, `team_group_membership`, `groups`, `competitions` | `team_id` → `group_id` → `competition_id` |
| League table / standings | `standings` | `group_id` (+ `team_id` for one team) |
| Top scorers in a group | `scorers` | `group_id` |
| A team's fixture list | `matches` | `home_team_id`/`away_team_id` |
| Where does a team/club play (address, map link) | `teams`, `matches`, `venues` | `club_name_raw` → `team_id` → `matches.venue_id` → `venues` |
| A club's identity/website/correspondence address, starting from a `team_id` | `team_club_map`, `clubs` | `team_id` → `club_id` (via `team_club_map`, complete) → `clubs` — opt-in tables, check `coverage_manifest.csv` first |
| A club's identity/website/correspondence address, starting from a name | `clubs` | `club_name_raw` — opt-in table, check `coverage_manifest.csv` first |
| A club's full profile (address, socials, founding date) or every team it has ever fielded | `clubs_extended`, `club_teams` | `club_id` — cross-season, append-only (take the latest `scraped_at` per `club_id`), see `DATA_DICTIONARY.md` |
| A player's appearances/goals/cards | `match_lineups/*`, `match_goals/*`, `match_cards/*`, `matches` | `player_id` → `match_id` → `matches` for date/context; glob all category files |
| Did a player move teams/clubs | `match_lineups/*`, `matches`, `player_competition_participation` | `player_id`, sorted by `match_date`, diff `team_id` (see recipe in `DATA_DICTIONARY.md`) |
| Match report detail (lineup, staff, ref) | `match_lineups/*`, `match_staff/*`, `match_officials/*` | `match_id` |

Worked examples (two-clubs head-to-head, cross-season concat, the
player-transfer-detection recipe, card-type code mapping, known
gaps/quirks, the crawl-log-families detail) are all in `DATA_DICTIONARY.md`
— go there once you know which tables you need from the routing table above.

## Why one file (per concern)

This project briefly had three overlapping docs (`README.md`'s data
dictionary, this file, and an unrelated, since-deleted `DATA_DICTIONARY.md`
someone else committed independently) describing the same schema — they
drifted out of sync with the actual code within the same day (wrong
`card_type_label`/`role_kind` example values, a raw-vs-cleaned team-name
mismatch). The `DATA_DICTIONARY.md` that exists now is a deliberate reboot
of that name, not a repeat of the mistake: this time there's exactly one
file per concern, and every other file links instead of re-describing.

- **`README.md`** — first read: what this project is, how the scraper
  works, URL patterns/endpoints, storage layout.
- **`CLAUDE.md`** (this file, auto-loaded every session) — routing only:
  which table for which question, the query procedure, pointers onward.
- **`DATA_DICTIONARY.md`** — the actual data model: every column, quirks,
  join recipes, worked examples. Deliberately *not* auto-loaded (unlike
  this file) — read it explicitly before running a query, so sessions that
  never touch the data don't pay to load ~250 lines of schema they won't use.
- **`OPERATIONS.md`** — running/extending the crawl: the GitHub Actions
  workflow, the resumability/batching design, `coverage_manifest.csv`
  mechanics, how to test a pipeline change safely.
- **`DATA_FINDINGS.md`** — empirical observations: expected "anomalies",
  join traps, patterns that look like bugs but aren't, and genuine quality
  issues discovered through real queries. Add entries here instead of
  re-investigating the same surprises.

If you're about to add a column description to this file, or a paragraph
explaining *how the crawler works* to `DATA_DICTIONARY.md`, or *what a
column means* to `OPERATIONS.md` — that's the signal it belongs in a
different file instead. Link to it, don't copy it.
