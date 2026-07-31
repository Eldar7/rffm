# RFFM — Bases de Ascensos y Descensos, Fútbol-7 y Fútbol-5, Temporada 2025-2026

**Source:** Real Federación de Fútbol de Madrid (RFFM), official document
"BASES DE ASCENSOS Y DESCENSOS COMPETICIÓN F-7 Y F-5, TEMPORADA 2025-2026",
approved by the Comisión Delegada on 10 July 2025.

- Published on: https://www.rffm.es/federacion-rffm/documentacion-y-circulares/bases-de-competicion
- Direct PDF fetched from: `https://rffm-cms.s3.eu-west-1.amazonaws.com/BASES_ASCENSOS_Y_DESCENSOS_Futbol_7_Temporada_2025_2026_853def12f8.pdf`
- Archived copy: `bases_ascensos_descensos_f7_f5.pdf` (same directory) — **fetch a fresh
  copy for any other season**; the filename/hash changes each year and old
  links can 404. Search `rffm.es` → "Bases de competición" or
  `site:rffm-cms.s3.eu-west-1.amazonaws.com BASES_ASCENSOS_Y_DESCENSOS` if the
  link above has gone stale.
- **The PDF is a scanned image, not text** — `pdftotext` returns nothing.
  Extracted here via `pdftoppm -r 300 -png` + `tesseract -l spa`. OCR is
  imperfect (accents/quotes sometimes mangled); the transcript below has been
  manually cleaned for the sections relevant to BENJAMÍN/PREBENJAMÍN. Treat
  numbers here as reliable (cross-checked against the source images), but
  re-OCR and re-check if this document is ever amended.

This transcript covers only the sections relevant to this project's scope
(BENJAMÍN, PREBENJAMÍN, Fútbol-7, plus the common provisions that apply to
them). The source PDF also covers Infantil Femenino, Alevín, Alevín
Femenino, Benjamín Femenino, and Debutante Fútbol-5, which are out of scope
here and omitted.

---

## Division ladder, 2025-2026 (Fútbol-7)

Team/group counts are fixed **per season** by this same document — always
re-check them for other seasons, don't assume they carry over.

**BENJAMÍN** (no Femenino split at this level in the ladder below — Benjamín
Femenino is a separate, parallel competition not covered here):

```
División de Honor Benjamín        4 groups × 13 teams   (top division)
        ↓ descenso / ↑ ascenso
1ª División Autonómica Benjamín   8 groups × 13 teams
        ↓ descenso / ↑ ascenso
Preferente Benjamín               16 groups × 13 teams
        ↓ descenso / ↑ ascenso
Primera Benjamín                  group count TBD (announced once known)
                                   (bottom division — no descenso from here)
```

**PREBENJAMÍN** (no División de Honor tier — ladder starts one level lower):

```
1ª División Autonómica Prebenjamín   8 groups × 12 teams   (top division)
        ↓ descenso / ↑ ascenso
Preferente Prebenjamín               16 groups × 12 teams
        ↓ descenso / ↑ ascenso
Primera Prebenjamín                  group count TBD
                                      (bottom division — no descenso from here)
```

## Prebenjamín's two-phase season structure

Unlike Benjamín (single round-robin per group, one final table), every
Prebenjamín division plays a **two-phase season** — this is why our
`groups.csv`/`competitions.csv` for Prebenjamín show `SEGUNDA FASE ...` /
`SUBGRUPO ... A` / `SUBGRUPO ... B` rows distinct from the regular-season
group:

1. **Primera Fase** — single round-robin (one match per pairing) among all
   teams in the group.
2. **Segunda Fase** — the group splits into two subgroups, each playing a
   double round-robin, **carrying forward** Primera Fase points:
   - **Subgrupo "A"** = top 6 (1ª Div. Autonómica / Preferente) or top half
     of Primera Fase's table. Plays to **ascend**.
   - **Subgrupo "B"** = bottom 6 / bottom half. Plays for **permanencia**
     (to avoid relegation) — winning Subgrupo B is a good result, but it is
     **not** promotion and not equivalent to winning the group/division.

This is why, e.g., Aravaca C.F. - Ceiba 'A' (Prebenjamín, Grupo 8) shows up
as **1st in "SUBGRUPO 8 B"** in our standings.csv: they finished 7th in the
Primera Fase table (bottom half → sent to Subgrupo B), then topped Subgrupo
B in the Segunda Fase — a strong finish, but it means "survived comfortably
in the permanence group," not "won the division" or "got promoted."

(Note: `phase_label` values in this repo's `competitions.csv` — regular
season / "phase segunda fase" / playoff — reflect this same
Primera-Fase → Segunda-Fase → (for Benjamín, later) Torneo de Campeones
staging.)

---

## BENJAMÍN — rules by division

**División de Honor** (4 groups × 13)
- Ascensos: none — top division.
- Descensos: bottom 4 of each group, fixed, → 1ª División Autonómica.

**1ª División Autonómica** (8 groups × 13)
- Ascensos: top 2 of each group → División de Honor ("con opciones de
  ascenso" — i.e. provisional on the common provisions below, e.g. filial
  restrictions).
- Descensos: bottom 4 of each group → Preferente.

**Preferente** (16 groups × 13)
- Ascensos: top 2 of each group → 1ª División Autonómica.
- Descensos: bottom 4 of each group, fixed, → Primera.

**Primera** (group count TBD)
- Ascensos: enough teams to fill Preferente's relegation vacancies; **the
  group winner is always guaranteed promotion**, minimum, regardless of the
  vacancy count.
- Descensos: none — bottom division.

---

## PREBENJAMÍN — rules by division

**1ª División Autonómica** (8 groups × 12)
- Ascensos: none — top division.
- Descensos: bottom 4 of each group's **Subgrupo "B"** (Segunda Fase),
  fixed, → Preferente.

**Preferente** (16 groups × 12)
- Ascensos: top 2 of each group → 1ª División Autonómica.
- Descensos: bottom 4 of each group's Subgrupo "B", fixed, → Primera —
  **plus additional relegations if needed** so that the champion of the
  group below (Primera) can be promoted.

**Primera** (group count TBD)
- Ascensos: exactly enough to fill Preferente's relegation vacancies; the
  group winner is always guaranteed promotion, minimum.
- Descensos: none — bottom division.

---

## Common provisions (Disposiciones Comunes) — apply to both categories

1. **Filial/dependency block.** A team that earns promotion consumes that
   right *unless* blocked by a "regulatory impediment" (`filialidad,
   dependencia` — e.g. being a reserve/dependent team of a club already
   represented at that level). If blocked, the next best-placed eligible
   team in the same group promotes instead.
2. **Post-season vacancies.** If a vacancy in a higher division appears
   *after* 30 June, the best-placed team to fill it is decided by a tie-break
   cascade: (a) final league position → (b) **points coefficient** (points
   ÷ matches played — this normalizes across groups that played different
   numbers of matches) → (c) overall goal difference → (d) goals for → (e)
   **goals-for coefficient** (goals ÷ matches played) → (f) if still tied, a
   one-off decisive match at a neutral venue and time set by the competent
   federation body.
3. **Same-club "A"/"B" collision.** If a club's 'A' and 'B' teams both
   qualify for promotion into the same division but only one slot is
   available, the team with the better **points coefficient** (points ÷
   matches played) goes up; ties broken by the same cascade as #2. If 'B'
   ends up promoting instead of 'A', **the letters swap** for the following
   season (B becomes A, A becomes B).
4. **Supernumerary groups.** Any group left with an irregular ("above
   quota") team count relegates **one extra team**, purely to rebalance
   division sizes by the following season.
5. **Playoffs.** RFFM playoffs ("Play Off de ascenso") for promotion appear
   in this document **only** for Infantil Femenino — **not** for Benjamín or
   Prebenjamín Fútbol-7. Promotion/relegation for our two categories in
   2025-2026 is decided by final table position alone, no playoff.
6. **Match format (Benjamín/Prebenjamín specific):** all Benjamín divisions
   play "sede" format (neutral/hosted, not home-and-away) unless the
   Subcomité de Competición changes it. Club-per-group caps: up to 2 teams
   of the same club in División de Honor/1ª Div. Autonómica, up to 3 in
   Preferente (Benjamín); up to 2 in 1ª Div. Autonómica/Preferente
   (Prebenjamín) — Primera has no fixed cap, decided ad hoc by the
   Subcomité.

## What this does *not* cover — "Torneo de Campeones"

This document never mentions "Torneo de Campeones" / "T. Campeones" at all.
Those competitions (visible in our `competitions.csv` as
`phase_label = "playoff"` / `"playoff FASE FINAL"`, e.g. "T. CAMPEONES 1ª
DIV. AUT. BENJAMIN FINAL") appear to be a **separate end-of-season
champions' cup** among group/level winners, run in parallel — **not** part
of the promotion/relegation mechanism described here. Treat a team's
Torneo de Campeones result as **not** implying anything about which
division they play in next season. This is an inference from the
document's silence, not a positive confirmation — revisit if RFFM ever
publishes a Torneo de Campeones-specific regulation.

## Caveat — these rules are re-published every season and do change

This exact ruleset applies to **2025-2026 only**. Known upcoming change:
per RFFM's own announcement ("Conoce los cambios de las Bases de
Competición de Cadete a Prebenjamín"), Prebenjamín's entire
ascenso/descenso system is being **abolished** for **2026-2027**, replaced
by a self-registration model ("auto inscripción de equipos") with no
sporting promotion/relegation at all. Division team-counts also shift
season to season (e.g. Infantil's Primera División Autonómica goes from 1
group to 2 for 2026-2027, alongside a new División de Honor tier). **Do
not assume this document's numbers or mechanism apply to any season other
than 2025-2026** — re-fetch and re-read that season's own "Bases de
Ascensos y Descensos" PDF before drawing conclusions about division
movement in other years.

## Practical implication for this repo's data

`standings.csv` position/points alone tell you which teams **satisfy the
sporting criteria** for promotion/relegation (top-2, bottom-4, etc.) — they
do **not** by themselves prove a team actually moved, because of the
filial-block, vacancy-substitution, and A/B-swap rules above. To confirm an
actual division change for a team across two seasons, diff `team_id` →
`competition_id`/`group_id` in `team_group_membership.csv` between the two
seasons, rather than inferring it from one season's `standings.csv` table
position.
