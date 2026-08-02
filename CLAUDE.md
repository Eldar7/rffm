# CLAUDE.md — orientation for analytics sessions

This file is *auto-loaded into every session* in this repo (it's
`CLAUDE.md`), so it's kept deliberately lean: just enough to route an
analytics question to the right table and the right file. It is **not**
for implementing the scraper (see `README.md`: URL patterns, endpoints, how
the data was collected), **not** for running/extending the crawl pipelines
or GitHub Actions (see `OPERATIONS.md`), and **not** the full schema (see
`DATA_DICTIONARY.md` — exact columns, quirks, worked examples, join
recipes). **Before writing any actual query, read `DATA_DICTIONARY.md`** —
this file only tells you which table to look at, not its columns.

## Scope

Categories **BENJAMÍN** and **PREBENJAMÍN**
(`category`/`category_base` column value `"BENJAMIN"`/`"PREBENJAMIN"`),
across every game type the federation runs under those categories (Futbol-7
and Futsal, as discovered — not hardcoded to one). Multiple **seasons** —
starting with 2025-2026, more added over time as separate crawls; always
check `coverage_manifest.csv` (below) for which season/category/stage
combinations actually have data before assuming a season is covered.

All tables live in `output/processed/rffm/<season>/*.csv` — one directory
per season, e.g. `output/processed/rffm/2025-2026/matches.csv`. This is a
**per-season partition**, not a duplicate/overlapping copy: re-running the
crawler for a new season writes to its own new directory and never touches
another season's files. The lone exception is `coverage_manifest.csv`
itself, which lives one level up at `output/processed/rffm/coverage_manifest.csv`
(see "Is this season done" below) since its whole purpose is to be the one
cross-season index. Answer questions by running a pandas script (via Bash),
not by eyeballing CSV rows — see "How to answer a query" below.

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
- `match_lineups.csv` — per-match, per-player lineup
- `match_goals.csv` — one row per goal event
- `match_cards.csv` — one row per card
- `match_staff.csv` — coaches/delegates per match
- `match_officials.csv` — referees/field delegate per match
- `players.csv` (`player_id`) — stable player identity (name, birth year)
- `player_season_stats.csv` — site-reported season aggregates per player
- `player_competition_participation.csv` — team/group registration per player (can be >1 row/player)
- `clubs.csv` (`club_id`, `enrich_clubs.py`) — one row per club: real RFFM club id, website, correspondence address (**not** a stadium address — see `DATA_DICTIONARY.md`)

## How to answer a query

**Procedure, every time:**
1. **Resolve names to IDs first.** Never filter `matches.csv`/`standings.csv`
   free-text columns directly by a club/player name the user typed — go
   through `teams.csv`/`players.csv` to get canonical `team_id`/`player_id`
   values, *then* filter everything else by ID. Free-text columns carry the
   site's raw formatting (quotes, accents, case) and are unreliable keys.
2. **Load only the CSVs the question needs** (table below).
3. **Run one self-contained pandas script via Bash** — don't hand-inspect
   CSV rows for anything beyond a first look.
4. **Sanity-check the row count** before presenting. Zero rows for two
   clubs/players that plausibly interacted is a signal something upstream
   is wrong (name typo, wrong scope, ID resolved against the wrong club),
   not necessarily a true negative.

**Question type → CSVs → join key:**

| Question | CSVs | Join |
|---|---|---|
| Club vs. club results / head-to-head | `teams`, `matches` | `club_name_raw` → `team_id` list → `home_team_id`/`away_team_id` |
| What teams/levels does a club field this season | `teams`, `team_group_membership`, `groups`, `competitions` | `team_id` → `group_id` → `competition_id` |
| League table / standings | `standings` | `group_id` (+ `team_id` for one team) |
| Top scorers in a group | `scorers` | `group_id` |
| A team's fixture list | `matches` | `home_team_id`/`away_team_id` |
| Where does a team/club play (address, map link) | `teams`, `matches`, `venues` | `club_name_raw` → `team_id` → `matches.venue_id` → `venues` |
| A club's identity/website/correspondence address | `clubs` | `club_name_raw` (join to `teams` if starting from a `team_id`) — opt-in table, check `coverage_manifest.csv` first |
| A player's appearances/goals/cards | `match_lineups`, `match_goals`, `match_cards`, `matches` | `player_id` → `match_id` → `matches` for date/context |
| Did a player move teams/clubs | `match_lineups`, `matches`, `player_competition_participation` | `player_id`, sorted by `match_date`, diff `team_id` (see recipe in `DATA_DICTIONARY.md`) |
| Match report detail (lineup, staff, ref) | `match_lineups`, `match_staff`, `match_officials` | `match_id` |

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

If you're about to add a column description to this file, or a paragraph
explaining *how the crawler works* to `DATA_DICTIONARY.md`, or *what a
column means* to `OPERATIONS.md` — that's the signal it belongs in a
different file instead. Link to it, don't copy it.
