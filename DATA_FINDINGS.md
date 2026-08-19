# DATA_FINDINGS.md — empirical observations about the data

Things discovered through actual queries: expected "anomalies", traps,
patterns that look like bugs but aren't, and genuine data quality issues.
This is separate from `DATA_DICTIONARY.md` (which describes the schema) and
`OPERATIONS.md` (which covers the crawl mechanics).

**Before assuming something is a bug** — check here first.

---

## clubs.csv — 326 missing entries (2025-2026)

**Symptom:** `coverage_manifest.csv` shows `complete_with_failures` with
`targets_failed=326` for the `clubs` stage in 2025-2026. When joining
`teams.csv` → `clubs.csv` for these teams, the join produces NaN.

**This is not a crawl bug.** All 1146 HTTP fetches succeeded. The 326 gaps
are structural — the representative team for those clubs has no extractable
`codigo_club` from its fichaequipo page.

Three categories:

| Category | Count | Details |
|---|---|---|
| Phantom/placeholder teams | 2 | `Equipo Casa (No asignado)` / `Equipo Fuera (No asignado)` — RFFM synthetic entries, not real clubs |
| University teams | 17 | UNIVERSIDAD COMPLUTENSE, UNIVERSIDAD POLITÉCNICA, etc. — registered as institutions, RFFM has no fichaequipo profile for them |
| New/school clubs (high IDs ~26xxxxxx) | 307 | Recently registered clubs (CLG EVEREST SCHOOL, AMERICAN SCHOOL MADRID, etc.) that have a team page but no club profile yet |

**Consequence:** For these 326 teams, `clubs.csv` has no row — any join
that expects a club record will get NaN. Expected; don't re-investigate.

`clubs_data_quality_report.csv` also records 93 `redundant_club_target`
(severity=info): multiple teams resolved to the same `club_id`. These are
correctly deduped in the published `clubs.csv` (first-fetched row kept).
They are not duplicates in the data — they are the same real-world club
fielding multiple teams.

---

## club_profile.html — a club renamed across seasons can show up as two clubs

**Symptom:** Searching the club picker on `club_profile.html` for a club
you know spans several seasons sometimes turns up what looks like the same
club twice, or a club's donor/destination flows seem to "lose" a season's
worth of players with no `transfers.csv`-style explanation.

**Why:** `club_profile_data.py` has no stable cross-season club ID to key
off — `clubs.csv` (`club_id`) is opt-in (`enrich_clubs.py`) and not
guaranteed for every club/season (see the gap above), and `teams.csv`'s
`club_name_raw` is known to drift ~20% season-to-season (sponsor suffixes
added/dropped, abbreviations — see `player_cards.py`'s `tid_to_club`
comment). So club identity here is a same-season `club_name_raw` folded
through accent/case/punctuation normalization only (`club_profile_data.
club_key()`) — it merges cosmetic spelling variants but **not** a genuine
rename (sponsor change, legal-name change) between seasons; those land as
two separate entries in the club picker. This is the same limitation every
other cross-season club join in this project already carries, not a new
crawl bug — don't re-investigate it as one.

**Consequence for donor/destination flows:** a player's move is only ever
reported when they have a confirmed participation row in two
*calendar-adjacent* seasons (one at the target club, the other elsewhere) —
a gap year with no row, or a club rename that splits one real club into two
keys here, surfaces as "gap / unknown previous club" or "no data
afterward," never as a fabricated transfer. That's intentional caution, not
missing data.

---

## The trailing-".0" artifact silently broke "seasons played/eligible" for 10% of players

**Symptom:** `all_players.html`'s "Сезонов" column (and the same stat on
`player_card.html`) shows blank/unknown eligibility for a player who
clearly has fichajugador data for several seasons.

**Cause:** Several numeric-looking columns (`matchday`, `home_score`/
`away_score`, `team_id`, `venue_id`, `birth_year`, `jersey_number`,
`team_position`/`team_points`, ...) serialize with a spurious trailing
`.0` in some CSV files and not others — a pandas artifact from writing a
column that had *any* null in it at CSV-export time, not a real data
difference (`"5"` and `"5.0"` are the same value). `all_players.py`'s
`seasons_ratio()` gates on `birth_year.isdigit()` before computing the
stat — and `"2018.0".isdigit()` is `False`. Checked directly on the full
dataset: **30,325 players (10%)** have this exact silent breakage on the
CSV-driven site as of this writing.

**This is not new data corruption** — it's always been there, just never
surfaced because nothing compared the "clean" and "dirty" versions of the
same value before. `output/processed/rffm_parquet/` (real int types,
produced by `analysis_scripts/build_parquet.py`'s `compact_types`) doesn't
carry the artifact, so any report ported to read from there (see the
`_v2.py` report generators) fixes this as a side effect, not a deliberate
fix. If you're computing anything from a numeric-looking CSV string column
and get a suspiciously low match rate against `.isdigit()`/`int(x)`, check
for this before assuming a real gap — `int(float(x))` or a numeric
`pd.to_numeric()` conversion sidesteps it.

---

## `players.csv`'s birth_year "conflicts" across seasons are 100% a formatting artifact, 0% real

**Symptom:** Comparing a player's `birth_year` across different seasons'
`players.csv` files looks like it disagrees for a meaningful chunk of
players (raw string comparison flagged 18,594 — 6% of players).

**This is the same trailing-".0" artifact as above, not RFFM correcting
birth years.** Checked directly: comparing `birth_year` as *numbers*
instead of strings across every season, the real disagreement count is
**zero**, for every one of 303,968 players in the dataset. An earlier
build of `output/processed/rffm_parquet/players.parquet` had a
`birth_year_conflict` column based on the unnormalized (string) comparison
and a docstring claiming "the site itself edits birth years sometimes" —
that claim was wrong, traced to this artifact, and the column was removed
(nothing read it, and `players_by_season` already has the full per-season
history if a genuine conflict ever does show up in future data).

---

## Referential integrity gaps found by `analysis_scripts/validate_parquet.py`

This project's crawl-time checks (`data_quality_report.csv`'s 9
`check_name` types) are all plausibility/reconciliation checks
(value-range, site-vs-computed) — none of them check whether an ID column
actually resolves in the table it references. `validate_parquet.py`
(anti-join over `output/processed/rffm_parquet/`) does, and found two real,
structural gaps — small relative to table size, not crawl failures, not
yet root-caused past the pattern below:

**`match_cards.player_id` not in `players`: 11,045 distinct player_ids
(3.63% of the 303,968 this project knows about) — root-caused, mostly
coaches carded on the bench, not a crawl bug:**

1. `_load_target_player_ids()` in `rffm_scraper/player_pipeline.py` sources
   fichajugador fetch targets from `match_lineups` only, not
   `match_cards`/`match_goals` — so a card recipient who never appears in
   that match's lineup extraction never gets their `/fichajugador/<id>`
   page fetched, even when a real one exists on the site. Confirmed by
   hand: `https://www.rffm.es/fichajugador/<id>?temporada=<season_id>`
   returns a genuine `FICHA DEL JUGADOR` for IDs this project has no
   `players.csv` row for.
2. Most of these are coaches, not players who simply weren't fetched.
   Anti-joining the same (match_id, team_id, id) against `match_staff.
   person_id` explains 65% of the rows directly (same match, same team -
   real names, `role_kind='head_coach'`/`'other_staff'`), and another
   handful resolve if you drop the match/team restriction and just check
   whether the id appears as staff *anywhere* in `match_staff` (a coach
   who works with more than one team at the club). For the remainder
   (8,525 ids, 0.79% of all known players) that don't resolve to staff at
   all: fetched 8 of them live and cross-referenced age against the
   category their card was in - CADETE/JUVENIL/ALEVIN. Every single one
   with a listed age (6/8; the other 2 have no active-season
   team/category, i.e. inactive this season) was 21-35 years old, in
   categories whose player age bracket is 10-18 (DATA_DICTIONARY.md's
   "Category taxonomy" table). RFFM appears to use one person/`jugador` ID
   space for both playing and coaching roles - someone registered as an
   adult player elsewhere gets their youth-team coaching card logged under
   that same id, and this project's `match_staff` extraction doesn't
   catch every coach for every match.

**Not a data quality bug**, and not something `enrich_players.py` fetching
more aggressively would meaningfully fix - these ids mostly resolve to
real people, just not people functioning as *players* in the match the
card was recorded in, so adding them to `players.csv` would misrepresent
them as youth players. The more useful fix, if one is wanted, is
completeness of `match_staff`'s own coach/delegate capture, not
`_load_target_player_ids()`'s scope.

**`player_competition_participation.team_id`/`.group_id`/`.competition_id`
not in `teams`/`groups`/`competitions`: 767/981/129 distinct values**,
spread across all 9 fichajugador-covered seasons (25-301 per season, not
concentrated in the newest/least-stable one — checked, ruling out "core
crawl just hasn't caught up with enrichment yet" as the whole story). The
team names in the violating rows are real clubs (e.g. "U.D. TALAMANCA",
"MOSTOLES C.F."), not the known placeholder/unassigned codes from the
`clubs.csv` gap entry above — so this isn't the same phenomenon.

**Not yet investigated further** — root cause unconfirmed, could be teams/
groups that only ever appear via a registration and never actually play a
core-crawled match that season, or an endpoint-coverage asymmetry between
what `main.py`'s core crawl discovers and what fichajugador reports. Worth
running `validate_parquet.py` again after investigating to see if the
count changes. Not wired into `parquet-build.yml` as a hard gate yet for
exactly this reason - it would fail on every run until this is understood
or explicitly accepted as a known, permanent characteristic (same posture
DATA_QUALITY_REPORT's `severity=warning` checks already take).

---
