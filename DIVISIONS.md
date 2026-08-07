# RFFM Division Hierarchy

This file documents the `division_level` values used in `competitions.csv`
and their relative prestige/tier ordering. Use `tier` for cross-category
comparisons (lower number = higher tier). `division_level` is parsed from
`NombreCategoria` (with `nombre` as fallback) by
`rffm_scraper.normalize.classify_division_level` — see `DATA_DICTIONARY.md`
for the parsing mechanics.

> **Important**
>
> `tier` is a scraper-defined prestige ranking, not an official RFFM
> promotion/relegation hierarchy.
>
> Different age groups use different competition pyramids
> (e.g. SUPERLIGA for Cadete/Infantil/Alevín, LIGA NACIONAL for Juvenil,
> TERCERA FEDERACION for adult football). The tier values provide a
> normalised ordering for analytical purposes only — comparing tiers
> across age groups (e.g. BENJAMIN PRIMERA vs JUVENIL SEGUNDA) is
> usually not meaningful.

## Tier table

| tier | division_level | Applies to | Notes |
|------|----------------|------------|-------|
| 1 | `SUPERLIGA` | ALEVIN, INFANTIL, CADETE | Top youth competition level in observed RFFM structures. |
| 1 | `LIGA NACIONAL` | JUVENIL | Highest observed regional youth level for Juvenil. |
| 2 | `DIVISION DE HONOR` | ALEVIN, BENJAMIN, INFANTIL, CADETE, JUVENIL | Elite youth tier below SUPERLIGA where present. |
| 3 | `PRIMERA DIVISION AUTONOMICA` | AFICIONADO, ALEVIN, BENJAMIN, INFANTIL, CADETE, JUVENIL, PREBENJAMIN | Highest common regional division. FEMENINO expected but not yet observed in crawled seasons. |
| 4 | `PREFERENTE` | AFICIONADO, ALEVIN, BENJAMIN, CADETE, INFANTIL, JUVENIL, PREBENJAMIN, SENIOR | Regional level below Primera División Autonómica. Top of the pyramid for SENIOR Fútbol Sala (SEGUNDA DIVISION B is a parallel RFEF track, not a tier above it in the regional ladder). |
| 5 | `SEGUNDA DIVISION B` | SENIOR | Legacy division token found in competition names. |
| 5 | `TERCERA FEDERACION` | AFICIONADO, FEMENINO | Highest adult federation competition observed in RFFM datasets. Both appear as `category_base=OTHER` in crawled data — expected structurally but not yet confirmed via a clean `category_base`. |
| 6 | `PRIMERA` | AFICIONADO, ALEVIN, BENJAMIN, CADETE, INFANTIL, JUVENIL, PREBENJAMIN, SENIOR | Bottom of the pyramid for BENJAMIN and PREBENJAMIN (no lower tier exists for them). Only tier observed for SENIOR Futbol-7. |
| 7 | `SEGUNDA` | AFICIONADO, ALEVIN, CADETE, INFANTIL, JUVENIL, SENIOR | Bottom of the pyramid for most Futbol-11 youth categories. Not observed for BENJAMIN or PREBENJAMIN. |
| 8 | `TERCERA` | SENIOR | Exclusively SENIOR Fútbol Sala in observed data. Bottom of the SENIOR sala pyramid. |
| — | `FASE ZONAL` | youth categories | Competition phase rather than league tier — cross-zone playoff structure. |
| — | `CAMPEONATO UNIVERSITARIO` | UNIVERSITARIO | Separate university competition structure. |
| — | `LIGA UNIVERSITARIA` | UNIVERSITARIO | Separate university competition structure. |
| — | `OTHER` | any | No recognised division token found. |

## Notes on using `tier`

`tier` is not a column in `competitions.csv` — it is a lookup you apply
from this table. To compare two competitions by level, join on
`division_level` and map to `tier`.

SUPERLIGA and LIGA NACIONAL share tier 1 because they are the top level
in their respective age-group pyramids, not because they are comparable
to each other. Same for SEGUNDA DIVISION B and TERCERA FEDERACION at tier 5.

FASE ZONAL, CAMPEONATO UNIVERSITARIO, and LIGA UNIVERSITARIA are outside
the main pyramid and have no numeric tier.

## `OTHER` — what it means

`OTHER` means neither `NombreCategoria` nor `nombre` contained any
recognised division token. It is **not** a data quality issue — it is a
genuine property of RFFM's naming: many single-format or copa competitions
simply have no tier name (e.g. `"BENJAMIN SALA"` is the only sala league
for that age, so RFFM does not bother naming it `"PRIMERA BENJAMIN SALA"`).

If you need to filter out these unranked competitions, use:
```python
df[df["division_level"] != "OTHER"]
```

There are two independent `OTHER` values — `category_base=OTHER` (age
group unrecognised) and `division_level=OTHER` (tier unrecognised) — a
competition can hit either or both. See the inventory below for what
actually lands in each, as observed across every crawled season
(2018-2019 .. 2025-2026).

### `category_base = OTHER` — inventory

Unlike `division_level=OTHER` (genuinely no tier), most `category_base=OTHER`
rows *do* belong to a real age/format bracket — the site's own category
label just doesn't encode an age token the classifier recognises. Observed
`category_label_raw` values, grouped by what they actually are:

| `category_label_raw` (as crawled) | What it is | Why it's `OTHER` |
|---|---|---|
| `TERCERA FEDERACION`, `SEGUNDA FEDERACION` | RFEF national adult men's tiers (Segunda/Tercera Federación) — Madrid clubs' senior/reserve teams playing in the federation-wide pyramid, one level above the regional ladder this project mostly tracks | These are **RFEF** competitions, not an RFFM age category — no `AFICIONADO`/`SENIOR` token to key off |
| `TERCERA FEDERACION DE FÚTBOL FEMENINO` | Women's equivalent of the above | Same, plus "Femenino" isn't an age token |
| `PREFERENTE FEMENINO SALA`, `PRIMERA DIVISION AUTONOMICA FEMENINO SALA`, `PREFERENTE FUTBOL FEMENINO`, `PRIMERA FUTBOL FEMENINO`, `PRIMERA DIVISION AUTONÓMICA FEMENINO`, `PRIMERA DIVISIÓN DE FÚTBOL FEMENINO SALA`, `TERCERA DIVISIÓN DE FÚTBOL FEMENINO` (sala) | Real, regular club leagues for women's teams (11-a-side and sala), each with a genuine tier — `division_level` for these is usually classified correctly (e.g. `PRIMERA DIVISION AUTONOMICA`, see `competitions.csv`) | RFFM runs women's football as one open category rather than split by youth age bracket, so there is no `ALEVIN`/`JUVENIL`/etc token to parse — **do not** treat these as data-quality gaps; a club fielding a women's team will show up here and only here |
| `SELECCIONES TERRITORIALES` | Regional **representative squads** (selección) facing other territories' selections — not a club competition at all | Participants are representative teams, not club teams; `team_id`s here generally won't resolve to a `club_name_raw` the way a normal club team does |
| `TORNEO INTERCENTROS PENITENCIARIOS` | RFFM's prison inter-facility tournament — a genuine social-inclusion competition it runs, distinct from the club pyramid | No age/club framing applies |
| `COPA RFFM COMPETICIONES LOCALES` | A cup aggregating local/municipal leagues (not RFFM-run regular leagues) into one RFFM-administered knockout | Source leagues aren't part of the age pyramid this project classifies |
| `FUTBOL ANDANDO F-7` | "Walking football" — a low-impact recreational modality, typically open/veteran | Not an age-bracket competition |
| `FASE ZONAL 7` | A zonal phase (see `FASE ZONAL` in the tier table) that landed with a bare `"7"` suffix instead of an age token in its raw label | Labeling gap in the source, not a different competition family |

Net takeaway: except for `SELECCIONES TERRITORIALES` (not a club competition)
and the RFEF/social-inclusion/recreational rows, everything in this bucket
is a **real club competition** — mostly women's football, which this
project's category classifier cannot age-bucket because RFFM itself
doesn't organise it that way. Do not filter `category_base != "OTHER"`
when trying to enumerate every competition a club's teams played in — use
the `matches.csv`-based join instead (see `club_division_map.py`'s
`club_all_comps` below).

### The post-season phase pattern (torneo de campeones / playoff / copa)

Most tiers in the table above are not single flat leagues — RFFM regularly
layers a **second, post-season phase** on top of the regular-season group
stage: a "torneo de campeones"/"final campeón"/"copa" knockout among group
winners, sometimes a relegation "segunda fase" for mid/bottom teams. These
show up as *separate* `competition_id` rows in `competitions.csv`, usually
sharing the parent league's `division_level` (correctly) but with a
different `phase_label` (`competitions.csv`/`matches.csv` column):
`regular_season` for the base league, vs. `phase fase final`, `playoff`,
`phase segunda fase`, `playoff FASE FINAL`, `phase 7 fase`, `playoff 7 FASE`
for everything layered on top. **`phase_label` is the reliable
discriminator** — matching on name substrings (`"CAMPEONES"`, `"FINAL"`,
`"COPA"`) is brittle across seasons (see `TOURNAMENT_NAMING_VARIANTS.md` for
a documented case where the same concept was labelled 6 different ways
across 5 seasons for one category alone).

This is what "Copa de Campeones de Autonómica Juvenil" (mentioned as
apparently missing) actually is: the post-season phase of `PRIMERA DIVISION
AUTONOMICA` / `JUVENIL`, observed as `FINAL CAMPEON PRIMERA DIVISION
AUTONOMICA JUVENIL` (2023-2024, 2024-2025) and `FINAL COPA PRIMERA DIVISION
AUTONOMICA JUVENIL` (2025-2026) — not a separately-named competition that
was dropped, just this recurring phase pattern applied to Juvenil, filed
under the same `division_level` as the parent league. It was never absent
from the data; `club_division_map.html`'s per-club "all competitions" list
(see below) surfaces it explicitly with a "плей-офф/final" badge instead of
folding it into the parent league's matrix cell.

### `club_division_map.html` now covers every tier, not just the 6 common ones

`analysis_scripts/club_division_map.py`'s matrix previously only had 6
columns per category (`DIV_ORDER` = Honor/Autonómica/Preferente/Primera/
Segunda/Tercera) and — critically — **filtered every club whose only
presence was outside that list out of the page entirely**, not just out of
one column. That silently dropped `SUPERLIGA` (top tier for Alevín/
Infantil/Cadete), `LIGA NACIONAL` (top tier for Juvenil — this is "Nacional
Juvenil"; Real Madrid, Atlético, Getafe, Rayo Vallecano and others field a
team there and had vanished from the page), `TERCERA FEDERACION`/`SEGUNDA
DIVISION B` (adult), and the university tracks. `DIV_ORDER` now matches
this file's tier table in full, and the matrix is additionally restricted
to `phase_label == "regular_season"` so the post-season phases described
above don't fork off extra matrix columns — they still appear in full in
each club's "Все соревнования клуба"/"Todas las competiciones del club"
modal section, which is sourced from `matches.csv` (not `standings.csv`)
specifically so single-elimination cups that never produced a table are not
missed either.

## Validation

Run `analysis_scripts/validate_division_applies_to.py` to check which
`(division_level, category_base)` combinations actually appear in the
data and compare against the "Applies to" column above. The script also
prints an inverted view — per-category pyramid in age order — so you can
see the full tier ladder for each age group at a glance.
