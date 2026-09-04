# TEAM_CLUB_GAP_REASONS.md — deep dive on `team_club_gap_reasons.csv`'s classification

**Not auto-loaded, not linked from `CLAUDE.md`.** This file exists so that
reading `DATA_FINDINGS.md` for an unrelated finding doesn't also pull in a
full per-reason validation writeup nobody asked for. Read this only when
you're actually working with `team_club_gap_reasons.csv` — verifying its
classification, investigating a specific unresolved `team_id`, or deciding
whether a `reason` value can be trusted as a hard rule vs. a strong-but-
imperfect signal. Pointed to from `DATA_DICTIONARY.md`'s
`team_club_gap_reasons.csv` entry and `DATA_FINDINGS.md`'s coverage-metrics
section — start there, land here only on demand.

For the two top-line coverage numbers (84.4% resolved, 99.1% of the
remaining gap explained), see `DATA_FINDINGS.md`'s "two different % done
numbers" section — not repeated here.

## How to read the precision numbers below

`team_club_gap_reasons.csv`'s classifier only ever runs against `team_id`s
that are **already unresolved** (absent from `team_club_map.csv`) - a
`reason` value is never a claim that "every team matching this pattern is
unresolvable," only that *this specific* `team_id` is unresolved *and*
matches the pattern. To judge how strong a signal each pattern actually is,
the tables below show, for every `team_id` matching the pattern **regardless
of resolution status**: how many exist in total, how many are genuinely
unresolved (correctly explained by this `reason`), and how many resolve
anyway (the pattern's "exception rate" - not a bug, just tells you how much
to trust the pattern as a predictor). Query used for all numbers below:

```python
import pandas as pd, glob
m = pd.read_csv("output/processed/rffm/team_club_map.csv", dtype=str)
resolved_ids = set(m["team_id"])
# ...build `ids` = every team_id matching the reason's pattern (name or
# competition, per-reason below), then:
resolved = ids & resolved_ids
unresolved = ids - resolved_ids
```

---

## `technical_no_show`

**Rule:** `club_name_raw` matches `No asignado` or `^Finalista\s` -
RFFM's own synthetic placeholder labels, not real teams at all (`Equipo
Casa (No asignado)`, `Equipo Fuera (No asignado)`, `Finalista N F-7`/`F-11`
bracket-TBD slots).

**Precision: 1270/1271 (99.9%) unresolved.**

The one exception, `team_id=17145319`, is the already-documented
`team_id`-reuse case (`DATA_FINDINGS.md`'s "`team_id` gets reused by RFFM
for a completely different real-world team over time") - RFFM recycled a
`No asignado` placeholder slot for a genuinely different real team
("C.D.E. AUPA - MENTEMA BOADILLA") in a later season, which resolved
normally via `fichaclub_roster`. Not a classifier bug - the placeholder
label really was that `team_id`'s *original* name; it just isn't its
*current* one.

Example (a `Finalista` bracket placeholder, distinct from the bulk
`No asignado` case): `team_id=-10004643`, `club_name_raw="Equipo Casa (No
asignado)"` - negative `team_id`s are themselves a signal these are
synthetic byes, not real registrations (see `DATA_DICTIONARY.md`'s known
`matches.csv`/`teams.csv` quirks).

---

## `fase_zonal`

**Rule:** appears in a `matches.csv` row whose `competition_id` has
`competitions.csv`'s `division_level == "FASE ZONAL"` - one-day district
development festivals RFFM never ties to a club_id.

**Precision: 1092/1117 (97.8%) unresolved**, 25 resolve anyway (a team can
legitimately have a real `club_id` *and* have sent a squad to a FASE ZONAL
festival once - the festival itself just isn't why they're resolved or not).

Worked example - **CDE MEJORSALA**, a real, ongoing multi-team club (most
of its ~20 `team_id`s across seasons resolve normally via
`fichaclub_roster`/`exact_name_match`). But its `FASE ZONAL`-only
registrations classify separately and correctly:
`team_id=21368155`, `club_name_raw="CDE MEJORSALA sede Buitrago/Berrueco"`
- this is the specific one-off "final" festival team investigated live
earlier (2 vs. 2 mini-tournament, no real opposing club identity to
recover) - `division_level=FASE ZONAL` for its competition confirms it's
exactly this festival category, not a normal league fixture:
```
2023-2024 INFANTIL 'DEPORTE INFANTIL SAN FERNANDO F-SALA -cadete-'
https://www.rffm.es/competicion/calendario?temporada=19&competicion=21331720&grupo=21331722&jornada=1&tipojuego=3
```
Same pattern for the **ELECTROCOR** family below - one of its registration
contexts (`ELECTROCOR LAS ROZAS ALEV F7 CERCEDA`) is `fase_zonal`, while its
main club identity (`C.D. ELECTROCOR LAS ROZAS C.F.`) is `unexplained` - see
that section.

---

## `non_federated_local_cup`

**Rule:** played in a competition whose name contains "COMPETICIONES
LOCALES" (e.g. "II COPA RFFM COMPETICIONES LOCALES F11") - per RFFM's own
published rules for this cup (found via web search, see original
investigation), entry is restricted to champions of non-federated
*municipal* leagues, who were never RFFM club members to begin with.

**Precision: 130/131 (99.2%) unresolved.**

Example: `team_id=15280988`, `club_name_raw="BAR KATY EL SALVADOR TATTOO
CF"` -
```
2022-2023 'II COPA RFFM COMPETICIONES LOCALES F11'
https://www.rffm.es/competicion/calendario?temporada=18&competicion=17133644&grupo=17133647&jornada=1&tipojuego=1
```
a sponsor-named bar-league team, exactly the population this cup targets.

The one exception, `team_id=21418012` ("LAS ROZAS C.F.", resolved via
`exact_name_match` to `club_id=30423`), is a normal federated club that
also fielded a team in this cup once - the cup apparently doesn't
strictly enforce "non-federated entrants only," or this was a guest/
exhibition slot. Doesn't undermine the rule as a classifier (99.2% is
still very high precision), just means "played in COMPETICIONES LOCALES"
is evidence, not proof, same as every other reason here except
`prison_league`.

---

## `prison_league`

**Rule:** played in a competition whose name contains "PENITENCIARIOS"
(e.g. "XI TORNEO INTERCENTROS PENITENCIARIOS RFEF") - correctional-facility
teams.

**Precision: 14/14 (100%) unresolved - no exceptions found.** The cleanest
rule in this table.

Example: `team_id=10618864`, `club_name_raw="C.P ALCALÁ - MECO"` (a real
Spanish prison, Centro Penitenciario Alcalá-Meco):
```
2022-2023 '2ª FASE: XI TORNEO INTERCENTROS PENITENCIARIOS RFEF'
https://www.rffm.es/competicion/calendario?temporada=18&competicion=17119855&grupo=17119856&jornada=1&tipojuego=2
```

---

## `out_of_region_national_tier`

**Rule:** played in `PRIMERA NACIONAL` / `PRIMERA NACIONAL FEMENINO` /
`DIVISION DE HONOR DE JUVENILES` - national-tier competitions where clubs
from *other* autonomous communities' federations play Madrid clubs.

**Precision: 62/94 (66%) unresolved, 32/94 (34%) resolve.** This is
*expected and correct*, not a weak rule read the wrong way: the 32 that
resolve are the Madrid-based participants (who have a normal RFFM
`club_id` like any other Madrid club), and the 62 that don't are literally
*other* federations' clubs, who structurally cannot have an RFFM `club_id`
- RFFM's site only assigns `codigo_club` within its own federation. The
competition itself is a mix by design; only the out-of-region half is
this `reason`.

Example: `team_id=10723274`, `club_name_raw="C.D. BADAJOZ 1905"` (Extremadura,
not Madrid):
```
2019-2020 JUVENIL 'DIVISION DE HONOR DE JUVENILES'
https://www.rffm.es/competicion/calendario?temporada=15&competicion=10723232&grupo=10723402&jornada=1&tipojuego=1
```

---

## `representative_squad`

**Rule:** `club_name_raw` contains "SELECCION" - a representative/regional
squad (e.g. "SELECCION VASCA (AFICIONADOS)"), not a normal club.

**Precision: 66/68 (97%) unresolved.**

Example: `team_id=11264638`, `club_name_raw="SELECCION VASCA (AFICIONADOS)"`.

The 2 exceptions (`team_id=436774`/`321414`, both `club_name_raw="SELECCION
FEMENINA SUB -"`) resolve to the same `club_id=8888` - RFFM apparently does
maintain one institutional `club_id` for this specific national-team-style
entry, unlike the regional autonomous-community squads that don't get one.
A real, narrow exception, not a data error.

---

## `university_team` — was the weakest signal in this table, now resolved to 0

**Update:** all 29 rows below were resolved via `manual_review`/
`manual_synthetic` `team_club_map.csv` entries, as a follow-up once the
`unexplained` bucket above was closed - see `DATA_FINDINGS.md`'s
"resolving the 29 `reason=university_team` rows" section for the
per-university evidence. Left here, unmodified, as the historical record
of why this reason was originally the lowest-confidence one in this file.

**Rule:** `club_name_raw` contains "UNIVERSIDAD" or "UNIV.".

**Precision: only 30/81 (37%) unresolved - 51/81 (63%) resolve anyway.**
Unlike every other reason above, this one is a coin-flip at best. **Do not
read `university_team` as "university teams don't get a `club_id`"** -
most do. It only explains why *this specific* `team_id` doesn't, given
nothing else in the priority list matched first; a large, real population
of university sports-league entries resolve completely normally.

Side-by-side, same "university intramural league" context, opposite
outcomes:
- **Resolves normally:** `team_id=17283514`, `club_name_raw="UNIV.
  FRANCISCO DE VITORIA F.S.M."` → `club_id=16797421` (via
  `clubs_representative`).
- **Stays `unexplained`... no, correctly classified `university_team`:**
  `team_id=14420498`, `club_name_raw="UNIVERSIDAD ESIC"`:
  ```
  2024-2025 UNIVERSITARIO 'CAMPEONATO UNIVERSITARIO MASCULINO'
  https://www.rffm.es/competicion/calendario?temporada=20&competicion=21576264&grupo=21576312&jornada=1&tipojuego=1
  ```
Both play in the same `CAMPEONATO UNIVERSITARIO` competition family, same
season. No pattern found (yet) predicting which university teams get a
`fichaequipo`-resolvable `club_id` and which don't - left as a genuinely
open question, not investigated further (low priority: only ~29 rows
total in `team_club_gap_reasons.csv`, ~0.2% of all `team_id`s).

---

## `unexplained` — was 23 genuine residual gaps, now resolved to 0

**Update:** all 23 rows below were resolved via `manual_review`/
`manual_synthetic` `team_club_map.csv` entries - see `DATA_FINDINGS.md`'s
"resolving the 23 `unexplained` rows" section for the per-club evidence
and `TeamClubMapping`'s docstring in `models.py` for the mechanism. Left
here, unmodified, as the historical record of how each was found and why
it didn't match any automated rule - re-run the classifier query at the
top of this file against a fresh `team_club_map.csv` to confirm 0 remain.

No rule matched originally. Two sub-populations, both real:

**A real, ongoing club RFFM never gave a resolvable `fichaequipo`/
`fichaclub` profile to** - the clearest case is the **C.D. ELECTROCOR LAS
ROZAS** family: ~20 `team_id`s spanning 2016-2025 under variants of "C.D.
ELECTROCOR LAS ROZAS C.F.", none resolvable. Confirmed still active as
recently as this pipeline's own data: one of its registration contexts,
`team_id=21368885` ("ELECTROCOR LAS ROZAS ALEV F7 CERCEDA"), correctly
classifies as `fase_zonal` (a district festival appearance) rather than
`unexplained` - proving the club is real and playing, just never
independently assigned a `codigo_club` for its main squads' own
`/fichaequipo/` pages. Contrast with **C.D. PRODET POZUELO** (a similar
"maybe deleted club?" candidate raised during the original investigation)
- re-checked against the finished pipeline and **all 8 of its `team_id`s
across every season now resolve** via `team_club_map.csv`; it was never
actually a genuine gap, just a casualty of `clubs.csv`'s
one-representative-per-name-group sampling (the exact problem this whole
pipeline was built to fix - see `README.md`'s `enrich_team_clubs.py`
entry). Don't assume every "looks orphaned" report from before this
pipeline existed is still true - re-check against current
`team_club_map.csv` first.

**Investigated candidates deliberately left unresolved, evidence
insufficient to confirm a specific `club_id`:** `C.D.E. ESCUELA BREOGÁN`
(`team_id=18408082`) and `SPORTING ALTO DE EXTREMADURA`
(`team_id=18345500`) - both fully written up with the evidence considered
and why it wasn't enough, in `DATA_FINDINGS.md`'s "`source="manual_review"`
rows" section ("Deliberately excluded from this batch") - not repeated
here.

No further investigation planned for the remaining `unexplained` rows
(23 total) - left as-is per explicit decision, "до лучших времён" (for
whenever it becomes worth revisiting, not now).
