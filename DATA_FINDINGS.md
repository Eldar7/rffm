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

**Update (team_club_map.csv):** the finding above is specifically about the
one *representative* team_id per `club_name_raw` group failing to resolve
- it does not mean every other team of that same club also fails. Live
spot-checks found real cases where a non-representative sibling team (same
club, different `club_name_raw` spelling - e.g. "A.D. ARGANDA CLUB DE
FUTBOL 'B'" vs the already-resolved "A.D. ARGANDA C.F.") resolved fine on
its own `/fichaequipo/` page. `enrich_team_clubs.py`/`team_club_map.csv`
targets every team_id, not just representatives, and closes most of that
gap - see `DATA_DICTIONARY.md`'s `team_club_map.csv` entry. The 326 figure
above should not be read as "326 permanently unresolvable clubs" - re-check
against `team_club_map.csv` first.

---

## team_club_map.csv — `exact_name_match` false-positive on RFFM's placeholder team names (caught and fixed)

**Symptom (transient, already fixed - recorded so nobody re-discovers it the
hard way):** a first version of the `exact_name_match` seeding layer
(`team_club_pipeline.py`) briefly resolved all ~1,265 `team_id`s named
literally `"Equipo Casa (No asignado)"` / `"Equipo Fuera (No asignado)"` to
the *same* `club_id` - a single, real club that a nonsensical-looking
coincidence had connected them all to.

**Root cause:** `"Equipo Casa/Fuera (No asignado)"` is RFFM's own generic
placeholder label for a bye/no-show slot, reused *verbatim* as
`club_name_raw` across ~700-800 genuinely unrelated `team_id`s in different
groups/seasons - it is not a real club identity the way every other
`club_name_raw` value is. One specific `team_id` in that giant group,
`17145319`, was a placeholder in 2016-2021 but got reassigned by RFFM to a
real team ("C.D.E. AUPA - CIUDAD DE BOADILLA MENTEMA 'D'") starting
2022-2023 - a genuine, separately-confirmed case of RFFM reusing a numeric
`team_id` for a completely different real-world team over time (see the
`team_id` reuse note below). The moment `17145319` had *any* resolved
`club_id`, exact-string matching on the shared placeholder text handed that
same `club_id` to every other "No asignado" slot - a real false positive,
not hypothetical, caught by manually reviewing the resulting mapping before
this was documented.

**Fix:** `_NON_CLUB_NAME_PATTERN` in `team_club_pipeline.py` excludes
`club_name_raw` values matching `"No asignado"` or `"^Finalista "` (the
latter a bracket-TBD placeholder with the same reuse risk, verified small
but excluded on the same principle) from `exact_name_match` entirely. These
`team_id`s are correctly left unresolved - they're RFFM's own synthetic
bye/no-show slot, not a club to find (see the gap-classification work this
enables, if/when that table exists).

## `team_id` gets reused by RFFM for a completely different real-world team over time

Confirmed twice independently, both in `DIVISION DE HONOR DE JUVENILES`:
- `team_id=7208996` was `"Equipo Fuera (No asignado)"` in 2017-2018, then
  `"UCAM UNIVERSIDAD CATOLICA DE MURCIA C.F."` in 2019-2020/2020-2021 - same
  numeric id, same competition/group, different real entity.
- `team_id=17145319` was `"Equipo Casa (No asignado)"` through 2021-2022,
  then a real team ("C.D.E. AUPA...") from 2022-2023 onward (see the
  `exact_name_match` false-positive above - this is the id that caused it).

Implication: `team_id` is a stable identity *most* of the time (the premise
`team_club_map.csv`'s whole cross-season design relies on), but not an
absolute guarantee - RFFM appears to recycle a numeric slot, at minimum,
when it was previously a synthetic "No asignado" placeholder rather than a
real registered team. No evidence found (yet) of two *different real*
teams sharing a `team_id` over time - only placeholder-to-real reuse.

## team_club_map.csv `source="manual_review"` rows — evidence per row

Four `team_id`s resolved by human review during analysis, not by any
automated source - `club_name_raw` drifted too far from their real club's
registered spelling for `exact_name_match`'s exact-string rule to catch,
but independent evidence confirms the connection. Documented individually
per the `manual_review` source's own requirement (`models.py`):

- **`18310554` ("FUTURO VELILLA F. S.") → `club_id=16661239`.** Evidence:
  shares the exact same `venue_id=16974273` ("P.M. VELILLA DE SAN ANTONIO
  (futbol sala)") with the already-resolved `team_id=17155544`
  ("FUTURO VELILLA") across every season both appear.
- **`18439756` ("BRISTOL ATLETICO PIOVERA") → `club_id=17896583`.**
  Evidence: identical name (letter-for-letter) to the already-resolved
  `team_id=18586495` ("C.D. BRISTOL ATLÉTICO PIOVERA") - only the "C.D."
  prefix differs.
- **`18377739` ("C.D. MEJORADA") → `club_id=16660812`.** Evidence:
  `team_id` is consecutive with the already-resolved `team_id=18377738`
  ("MEJORADA") and `17155564`... `18377737` (PREBENJAMIN/BENJAMIN/ALEVIN of
  the same club, same 2016-2017 season) - a classic same-batch
  multi-category registration.
- **`17156256` ("OROQUIETA-ESPINILLO 'B'") → `club_id=16660505`.**
  Evidence: identical name modulo the hyphen, to the already-resolved
  `team_id=17148357` ("OROQUIETA ESPINILLO").

**Deliberately excluded from this batch** (found candidates, not confident
enough to add): `18408082` ("C.D.E. ESCUELA BREOGÁN") - `"C.D. ESCUELA
BREOGAN"` (note: no accent) is a genuine multi-branch academy with ~50
`team_id`s across dozens of Madrid venues; no venue/season/category overlap
found to pin down which specific branch `18408082` belongs to, so it stays
unresolved rather than guess. `18345500` ("SPORTING ALTO DE EXTREMADURA")
- no candidate found at all (see its own investigation above/below - a
genuinely real, single-season, three-match cup run with a distinct crest,
just no connection to anything else in this dataset).

## team_club_map.csv — resolving the 23 `unexplained` rows (6 real clubs)

Follow-up to the section above, done after `TEAM_CLUB_GAP_REASONS.md`'s
"unexplained" writeup identified exactly 6 distinct `club_name_raw` groups
behind all 23 `reason=unexplained` rows. One resolves via ordinary
`manual_review` evidence (an existing real `club_id`); the other 5 (really
4 real clubs - the 3 ELECTROCOR name variants are one club) get
`source=manual_synthetic` (see `TeamClubMapping`'s docstring in
`models.py` for the mechanism/id convention). This closes the
`unexplained` bucket to 0 rows.

- **`18405762`** ("GREDOS SAN DIEGO LAS SUERTES", 2017-2018, squad "B")
  → **`manual_review`, `club_id=16669730`**. Its own `/fichaequipo/`
  never resolved, but its exact-same-season, exact-same-`club_name_raw`
  sibling squads `17155665`/`18311375` (both "A", both 2017-2018) already
  resolve to `16669730` via `fichaequipo_direct` - same club_name_raw
  group only failed `exact_name_match` because *other* team_ids under this
  name (from 2025-2026 rosters) resolve to a *different* club_id (`4112`)
  - GREDOS SAN DIEGO LAS SUERTES itself apparently changed which of the
    two GREDOS SAN DIEGO org-level `club_id`s its squads register under,
  at some point between 2017-2018 and 2025-2026. The season-matched
  sibling evidence pins `18405762` to the 2017-2018-era id specifically.

- **C.D. ELECTROCOR (LAS ROZAS)** - 20 `team_id`s across 3 `club_name_raw`
  spellings (`"C.D. ELECTROCOR C.F."` 2016-2020, `"C.D. ELECTROCOR LAS
  ROZAS C.F."` 2020-2024, `"C.D. ELECTROCOR LAS ROZAS"` 2021-2025) → one
  new **`manual_synthetic`, `club_id=-2729917`** (`-min(team_id)` of the
  group). Confirmed one real, continuously-active club by
  `TEAM_CLUB_GAP_REASONS.md`'s own investigation (its `fase_zonal`
  satellite team_id proves it's still fielding real squads); RFFM's site
  never independently exposed a `codigo_club` for any of its 20
  registrations. Does not include the separate `fase_zonal` satellite
  team_id `21368885` ("ELECTROCOR LAS ROZAS ALEV F7 CERCEDA") -
  intentionally out of scope for this fix, a different, already-explained
  `reason`.

- **`18345500`** ("SPORTING ALTO DE EXTREMADURA") → **`manual_synthetic`,
  `club_id=-18345500`**. Single `team_id`, no merge ambiguity (nothing to
  attach it to, per the investigation above) - minted its own id rather
  than left invisible.

- **`18408082`** ("C.D.E. ESCUELA BREOGÁN") → **`manual_synthetic`,
  `club_id=-18408082`**. Deliberately given its OWN standalone id rather
  than guessed into any of the ~50 sibling BREOGÁN branches (per the
  "deliberately excluded" note above - which branch it belongs to is
  still genuinely unknown). Accepted tradeoff: this may end up a 51st,
  technically-separate `club_id` for what's really an existing branch -
  a minor split, not the wrong-merge risk a name guess would have carried.

## team_club_map.csv — resolving the 29 `reason=university_team` rows

Same treatment, done as a follow-up once the `unexplained` bucket above
hit 0 - `university_team` was `TEAM_CLUB_GAP_REASONS.md`'s own
lowest-precision, explicitly-not-fully-investigated reason (only 37% of
matching rows stayed unresolved). Investigated all 29 by normalizing
`club_name_raw` (strip accents, `UNIV.`/`UNIVERSIDAD` prefix, `FEMENINO`/
`F.S.M.`/`F.S.F.` suffixes) and grouping by real-world institution -
unlike BREOGÁN/GREDOS SAN DIEGO (multi-branch networks with genuine
who-is-this-team-actually ambiguity), a university name is essentially
unambiguous, so the only question was resolved-elsewhere-or-not per
institution:

- **25 team_ids across 11 real Madrid universities** (Alfonso X, Autónoma,
  Camilo José Cela, Carlos III, CEU San Pablo, Complutense, ESIC,
  Francisco de Vitoria, Politécnica, Pontificia Comillas, Rey Juan Carlos)
  → **`manual_review`**, attached to that university's own already-resolved
  `club_id` (found under a different accent/abbreviation/gender-suffix
  spelling - e.g. `UNIVERSIDAD AUTONOMA FEMENINO`'s `22097254` onto the
  same `club_id=16797423` as the men's-named `UNIVERSIDAD AUTONOMA`
  registrations). Confirmed this is standard practice in the dataset, not
  an assumption: 4 already-resolved real clubs elsewhere already mix
  `FEMENINO`/non-`FEMENINO` team registrations under one `club_id`.
- **4 team_ids across 3 universities with ZERO resolved variant anywhere**
  (`UNIVERSIDAD ANTONIO DE NEBRIJA` `2609758`; `UNIVERSIDAD CUNEF`/`UNIV.
  CUNEF F.S.M.` `14420560`+`21125332`; `UNIVERSIDAD EUROPEA DE MADRID`
  `2609763`) → **`manual_synthetic`**, same `-min(team_id)` convention.

This closes `university_team` to 0 rows, same as `unexplained` above.

---

## team_club_map.csv / team_club_gap_reasons.csv — two different "% done" numbers, don't conflate them

There are two unrelated coverage metrics for this pipeline; a query or a
status update that only says "84%" or "99%" without naming which one is
ambiguous and has already caused confusion once - always name the metric.

- **Resolution rate: how many `team_id`s have a `club_id` at all.**
  `len(team_club_map.csv) / (len(team_club_map.csv) + len(team_club_gap_reasons.csv))`
  = 14,281 / 16,921 = **84.4%**. This is *the* headline number for "is the
  team→club mapping done" - started at 51% (8,168/16,143) before this
  pipeline existed, using only `clubs.csv`'s one-representative-per-club
  sampling.
- **Gap-explanation rate: of the ~16% still without a `club_id`, how much
  has a documented structural reason** (`team_club_gap_reasons.csv`'s
  `reason` column, anything but `unexplained`) vs. is a genuine,
  currently-unresolved mystery (`unexplained`). 2,617 / 2,640 = **99.1%**
  explained, 23 rows (0.9%) still `unexplained` - deliberately left as-is,
  see that column's docstring in `models.py`.

These measure different populations (all `team_id`s vs. only the
unresolved ones) and answering "how done is this" with just one of them
reads as a much bigger or much smaller number than reality depending on
which one gets dropped - always state both together, or name which one is
being quoted.

For a full per-`reason` breakdown (how precise each classification rule
actually is, with real `team_id` examples and calendario links - some
rules are ~100% precise, `university_team` is closer to a coin flip), see
`TEAM_CLUB_GAP_REASONS.md` - kept as a separate file on purpose so reading
*this* file for an unrelated finding doesn't also load that whole
writeup.

```python
import pandas as pd
m = pd.read_csv("output/processed/rffm/team_club_map.csv", dtype=str)
g = pd.read_csv("output/processed/rffm/team_club_gap_reasons.csv", dtype=str)
resolution_rate = len(m) / (len(m) + len(g))
gap_explained_rate = (g["reason"] != "unexplained").mean()
```

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
structural gaps — small relative to table size, not crawl failures. Both
are now root-caused, below.

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

**Update:** `_load_target_player_ids()` now unions `match_cards`/
`match_goals` `player_id` alongside `match_lineups`, so these ids *are*
fetched as of this change - `players.csv` gains a real row for them
(marked `is_likely_coach=True` where the match_staff/season-stats
evidence above applies - see that column's entry below). Kept as a
worked example of the site's shared player/coach id space rather than
deleted, since the diagnosis itself remains true and useful context for
why `is_likely_coach` exists.

**Confirmed fixed, full rollout complete:** the fichajugador re-crawl
using the widened target list has now been run for all 9
fichajugador-covered seasons (2017-2018 through 2025-2026 - 2016-2017 has
no acta/fichajugador data at all, so nothing to widen there), 39,121
newly-fetched player_ids total (per-season target computation, not a
global one - see below for why that number differs from the
25,170/11,045 figures quoted earlier in this project's history).
Re-running `validate_parquet.py` after the full rollout:
`match_cards.player_id` orphans dropped from 11,045 to **2** - both
confirmed as live HTTP fetch failures for that specific id during the
crawl (a handful of `failed:`/`missing_after_this_run:` targets showed up
in every season's run summary; these two never got a successful fetch),
not a remaining logic gap. Re-fetching those two specifically (e.g. via
`retry_check.py` or a forced re-run) should close this to 0.

**Why the total target count (39,121) is larger than the original
25,170/11,045 figures:** those earlier numbers were computed against a
*global*, cross-season deduplication of `player_id` (matching
`players.parquet`'s own dedup-to-one-row-per-player treatment) - but the
crawler's actual resumability/target-computation is **per season
directory** (`output/processed/rffm/<season>/`, independent
`players.csv`/`fichajugador_crawl_log.csv` per season - see
`OPERATIONS.md`'s storage layout). A person carded as a coach in *both*
2022-2023 and 2024-2025, say, counts once in the global view but needs
two separate fetches (one per season) in the real pipeline, since each
season's crawl has no visibility into another season's `players.csv`.
Verified empirically before running: zero overlap between each season's
"new target" set and that same season's existing `players.csv` in every
one of the 9 seasons - so 39,121 was already the true minimal delta, not
inflated by re-fetching anyone already done.

**`match_cards`/`match_lineups`/`match_goals`'s `player_name_raw` is NOT
dropped** (correcting a stale claim that circulated in this project's
planning notes): checked directly - the column is present, and 99.08%
populated (1,173,201 / 1,184,111 `match_cards` rows; the 10,910 with a
`player_id` but blank `player_name_raw` are a small, separate edge case,
not a systemic write-path loss) in both the CSV and the Parquet copy.
`DATA_DICTIONARY.md` briefly documented it as "dropped, recover by
joining `players.csv`" - that was wrong and has been fixed; don't
re-investigate this as a bug.

**`players.csv.is_likely_coach`:** a derived flag (not scraped) added to
answer "was this `player_id` ever functioning as a coach rather than a
player" - see DATA_DICTIONARY.md's `players.csv` entry for exactly how
it's computed (`match_staff.person_id` cross-reference OR the "0 matches,
has cards" `player_season_stats` pattern from this same root-cause). Not
something `enrich_players.py` fetching more aggressively alone would have
produced - it needed the target-scope widening above *and* this
cross-reference to be useful.

**`player_competition_participation.team_id`/`.group_id`/`.competition_id`
not in `teams`/`groups`/`competitions`: 858/1,006/129 distinct values** as
of the fully-widened fichajugador re-crawl (was 767/981/129 before) —
spread across all 9 fichajugador-covered seasons, not concentrated in the
newest/least-stable one. The team names in the violating rows are real
clubs (e.g. "U.D. TALAMANCA", "MOSTOLES C.F."), not the known
placeholder/unassigned codes from the `clubs.csv` gap entry above — so
this isn't the same phenomenon. **The rise in `team_id`/`group_id` counts
(767→858, 981→1,006) is expected, not a regression**: widening fichajugador
targets added ~39,121 more `player_competition_participation` rows overall
(one newly-fetched profile can register several new team/group
combinations), so more instances of the *same already-diagnosed* gap
below surface - re-checked after the widening: 2,004 of 2,006 orphan
`team_id` rows (99.9%, same rate as before) still have an orphan
`competition_id`/`group_id` on the same row. `competition_id`'s count
staying exactly 129 makes sense too - it's a `COUNT(DISTINCT
competition_id)`, so new rows referencing an *already-orphaned*
competition don't move it; only a genuinely new missing competition
would.

**Root-caused:** anti-joining the *same* orphan rows against
`competitions`/`groups` (not just `teams`) shows **99.9% (1,769 of
1,770) of orphan `team_id` rows also have an orphan `competition_id` and
`group_id`** on the exact same row - this is not a per-team gap, it's
whole competitions/groups the core crawl never discovered that season, and
the team-level symptom is just downstream of that. Grouping the orphan
rows by `competition` name shows two distinct patterns, both consistent
with "core crawl's `/api/competitions` discovery is a point-in-time
snapshot, `player_competition_participation` (via `/fichajugador/`) is
fetched later and reflects the site's state at *that* later time":

1. **Second-phase/playoff competitions created after discovery ran** -
   `"... 2ª FASE"` / `"SEGUNDA FASE ..."` competitions dominate the list
   (e.g. `SEGUNDA FASE PRIMERA FEMENINO INFANTIL F7`, `PREBENJAMIN F7 - 2ª
   FASE`) - RFFM creates these mid/late-season once regular-season
   standings determine the bracket, so a core crawl that ran before that
   point can never see them, even for a category/season that *is* in
   scope (`PREBENJAMIN F7 - 2ª FASE` shows up despite `PREBENJAMIN` being
   this project's target category).
2. **Division tiers outside the crawled category/division scope** -
   `SEGUNDA ALEVIN` (471 rows), `TERCERA CADETE` (143 rows) - a
   lower-division tier of an otherwise-covered category that a given
   season's core crawl run didn't include (see CLAUDE.md's "Scope" -
   `--all-categories`/division coverage isn't guaranteed uniform across
   seasons; check that season's own `groups.csv`/`competitions.csv`).

Spread across all 9 seasons (not concentrated in the newest), consistent
with both causes being structural rather than a one-off crawl failure.
**Not a code bug to patch reactively** - fixing it for real means either
re-running core discovery periodically through a season (to catch
newly-created phase-2 competitions before they're needed) or deliberately
widening division-level scope, both product/scope decisions rather than
parser fixes. Left as documented, accepted behavior for now; worth
re-running `validate_parquet.py` after any future discovery-scheduling
change to see if the count drops. Not wired into `parquet-build.yml` as a
hard gate for the same reason as before (same posture
DATA_QUALITY_REPORT's `severity=warning` checks already take).

**Numbers drift as new seasons are added, still the same phenomenon:**
after the 2016-2017 season and 2017-2018..2020-2021's fichajugador re-crawl
(see the `match_cards.player_id` entry above) landed, the counts moved to
832/1006/129 team_id/group_id/competition_id orphans - consistent growth
from more seasons existing, not a new problem. Also found one single-row
sibling of this exact pattern: `scorers.team_id -> teams` now has 1
violation (`team_id=13538231`, 2021-2022) - same "team/competition/group
the core crawl never discovered that season" story, just surfaced through
`scorers.csv` instead of `player_competition_participation.csv`. Not
investigated further individually; same "accepted, re-check after a
discovery-scheduling change" posture as above.

---

## clubs_extended.csv — high null rate for older-season club_ids

**Symptom:** `enrich_club_profiles.py`'s first full backfill (2026-08-19,
1,054 target `club_id`s — the union across every season's `clubs.csv`)
returned `club: null` for 369/1,054 targets (35%) — no
`clubs_extended.csv`/`club_teams.csv` row at all for those, despite every
one of the 1,054 requests returning HTTP 200 (`club_profiles_crawl_log.csv`
has zero `success=False` rows for this run — see `failed: 0` in the run
summary). At a glance this looks like it could be a URL/parsing bug, since
35% seems high for "just some defunct clubs."

**This is not a bug — confirmed by live re-fetch of several null `club_id`s
outside the pipeline (`1029`, `1045`, `18104587`, `20798797`), all
independently reproducing `pageProps.club: null`.** The real explanation:
the null rate correlates almost perfectly with how old the season is that a
`club_id` was *only* ever seen in:

| Season (via that season's `clubs.csv`) | Null rate among that season's club_ids |
|---|---|
| 2016-2017 | 34.2% |
| 2018-2019 | 29.8% |
| 2020-2021 | 20.7% |
| 2022-2023 | 15.2% |
| 2024-2025 | 3.0% |
| 2025-2026 | 0.4% |

Only 20 of the 369 null `club_id`s appear in either of the two most recent
seasons' `clubs.csv` at all. This reads as `codigo_club` values that were
valid identities in RFFM's system years ago (still referenced by old
`fichaequipo` pages, which is how `clubs.csv` picked them up in the first
place) but have since been merged/deactivated/reassigned in whatever
manages `/fichaclub/` today — a genuine site-side identity drift over a
decade, not a crawl defect. Expected; don't re-investigate as a bug. See
`club_profiles_data_quality_report.csv`'s `club_profile_not_found` rows
(severity `info`, not `warning`) for the full list.

---

## career_analysis_*.csv / player_career.xlsx are stray notebook output, not a maintained table

**Symptom:** `output/processed/rffm/career_analysis_disappeared.csv`,
`career_analysis_out_career.csv`, `career_analysis_out_jumps.csv`,
`career_analysis_top_tier_profile.csv`, and `player_career.xlsx` sit in the
repo, git-tracked, with no generator in `analysis_scripts/` — grepping the
whole directory for their filenames or `.xlsx`/`career_analysis` turns up
nothing. Looks like an orphaned pipeline output missing its script.

**It isn't part of the pipeline at all.** These are hand-run Jupyter
notebook output: `notebooks/player_career.ipynb` builds a per-player
career table (seasons/categories/divisions/clubs/teams/competitions as
list columns) and writes it to `player_career.xlsx`
(`out.to_excel(out_path, index=False)`); `notebooks/career_analysis.ipynb`
reads that `.xlsx` back in (`pd.read_excel`) and derives the four
`career_analysis_*.csv` files from it — exploratory career-trajectory
analysis, not anything `build_site.py`/`analysis_scripts/*.py` reads or
regenerates. `analysis_scripts/player_career.py` is unrelated despite the
similar name — a small, current helper for a completely different stat
("X/Y seasons played") used by `player_card.html`/`team_card.html`.

**How they ended up committed is its own small mystery.** All five files
(plus the three `notebooks/*.ipynb` themselves) first appear in one commit,
`770a78e` (2026-08-13), authored by `rffm-crawl-bot` with the message
*"rffm-crawl checkpoint: fichajugador PREBENJAMIN (49000/75007)"* — an
automated crawl-progress checkpoint that, unrelatedly, also added 775 files
in one shot (34.5M insertions), including essentially the entire
`analysis_scripts/` directory and every root doc. Reads as the bot's commit
step sweeping up whatever was sitting in the working tree at that moment
(a parallel interactive/notebook session's untracked output included)
rather than a deliberate, reviewed addition of these specific files.

**Consequence:** out of scope for the CSV↔Parquet policy (`PARQUET_
CLOSURE.md`) entirely — there's no pipeline stage/generator to apply the
open/closed rule to, and no evidence anyone currently relies on these
files being present. Not deleted here (that's a separate, deliberate
decision for the project owner, same caution as CSV deletion in that
policy) - this entry exists so a future session doesn't re-investigate
"where's the generator for career_analysis_*.csv" as if it were a real gap.

---

## clubs.csv vs clubs_extended.csv — where they agree, where they don't, and why

**Symptom:** for the ~671 clubs present in both 2025-2026's `clubs.csv`
(`enrich_clubs.py`, from `/fichaequipo/<team_id>`) and the new
`clubs_extended.csv` (`enrich_club_profiles.py`, from
`/fichaclub/<club_id>`), several columns that *sound* like the same field
don't always match exactly. This looks like it could be a bug in one of the
two pipelines. It isn't — see `DATA_DICTIONARY.md`'s "Where each column
comes from" for the full field-by-field source mapping; this entry records
the empirical comparison that motivated writing it.

**Measured agreement** (2025-2026 `clubs.csv` vs `clubs_extended.csv`,
2026-08 backfill, 671 clubs present in both):

| Field pair | Match rate | Why the gap |
|---|---|---|
| `portal_web` (old) vs `portal_web` (new) | 670/671 (99.9%) | Noise-level; effectively the same value. |
| `crest_url` (old) vs `crest_url` (new) | 659/671 (98%) | Noise-level. |
| `postal_code` (old) vs `correspondence_postal_code` (new) | 668/671 (99.6%) after stripping `postal_code`'s known trailing-`.0` pandas artifact (same quirk `matches.csv`'s `home_score`/`away_score` have — see `DATA_DICTIONARY.md`) — only 5/671 (!) before that correction, which looks alarming until you realize it's a formatting artifact in the older file, not a data disagreement. |
| `correspondence_address` (old) vs `correspondence_address` (new) | ~355/671 (53%) as an exact string match | **Not** 47% wrong data — most "mismatches" are the same physical address written differently by the two source pages (`"Pº"` vs `"PASEO"`, `"Av."` vs `"Avenida"`, punctuation/capitalization). A small number are genuine content differences (see below). |

**Why the gap exists at all:** the two tables are sourced from two
different pages about two different things — `clubs.csv` reads a
per-*team* page (`/fichaequipo/<team_id>`, one representative team sampled
per club) captured on 2026-08-03; `clubs_extended.csv` reads the club's own
profile page (`/fichaclub/<club_id>`) captured on 2026-08-19. Sixteen days
apart, and from a page keyed by a different entity, so some drift/
formatting difference between "the same" field is expected, not a defect
in either pipeline.

**Genuine content differences found** (not formatting, not the pandas
artifact) — a handful of clubs where the address *and* postal code both
differ, e.g. `club_id` `30435` (MEXICO F.C. S.A.D.): `clubs.csv` has "Avda.
Juan Pablo II, 30 - 2º A" / `28860`; `clubs_extended.csv` has "Calle
Bulgaria 4, San Blas - Canillegas" / `28022`. Reads as the club having
genuinely moved/updated its address between the two data sources — not a
bug in either fetch. If you need a club's current address, prefer
`clubs_extended.csv` (sourced from the club's own profile rather than one
sampled team, and easy to re-freshen via `--force-refetch` — see
`OPERATIONS.md`).

---

## club_scorecard/*.csv is a WIP draft for a future club-metrics web page

**What it is:** `output/processed/rffm_analysis/club_scorecard/club_cohort.csv`
and `club_level.csv` are the batched-across-all-685-clubs output of
`analysis_scripts/club_scorecard.py` (added in `78da433` — "the metrics
catalog from the Aravaca/Union investigation, computed for any club or
batched across all 685"). The catalog is genuinely rich — size/structure,
division ceiling, retention curves (in-club vs in-football, per age
category from its own founding-cohort season), elite-reach split (in-club
vs after leaving), current top-team homegrown %, transfer balance between
clubs, squad continuity, discipline, playing-time equity (Gini), result
volatility — see the script's own module docstring for the full design
rationale (club identity resolved via `club_id`/`club_teams.parquet`, not
fragile `club_name_raw` string matching; a real bug found along the way —
Union de Aravaca's team_id 4937443 was missing from its own `/fichaclub/`
roster, understating a cohort by more than half).

**Project owner's stated intent: these CSVs are a draft/precursor for a
future club-metrics page on the site**, not a table meant to be queried or
converted long-term as-is — `club_scorecard.py` is a CLI script today, not
yet ported to the `build_all(out_dir)` report-generator pattern every other
`analysis_scripts/*.py` page follows (reading via `rffm_data.py` from
Parquet, writing HTML+JSON straight into the site build). Once that port
happens, these specific CSV files stop being needed at all — the page
would compute the same catalog on demand from the already-converted core
Parquet tables, the same way `club_profile.html`/`club_division_map.html`
already do.

**Consequence:** out of scope for the CSV↔Parquet policy (`PARQUET_
CLOSURE.md`) — not because of any (season, stage) closure question, but
because it isn't meant to persist as a data table at all. Not built into
a page here;
this entry exists so a future session finds this context (and the design
notes already in `club_scorecard.py`'s own docstring) instead of
re-deriving "why does this exist, should it move to Parquet" from scratch.

---
