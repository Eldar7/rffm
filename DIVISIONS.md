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

## Validation

Run `analysis_scripts/validate_division_applies_to.py` to check which
`(division_level, category_base)` combinations actually appear in the
data and compare against the "Applies to" column above. The script also
prints an inverted view — per-category pyramid in age order — so you can
see the full tier ladder for each age group at a glance.
