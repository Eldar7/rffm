# RFFM Division Hierarchy

This file documents the `division_level` values used in `competitions.csv`
and their relative prestige/tier ordering. Use `tier` for cross-category
comparisons (lower number = higher tier). `division_level` is parsed from
`NombreCategoria` (with `nombre` as fallback) by
`rffm_scraper.normalize.classify_division_level` — see `DATA_DICTIONARY.md`
for the parsing mechanics.

## Tier table

| tier | division_level | Notes |
|------|---------------|-------|
| 1 | `PRIMERA DIVISION AUTONOMICA` | Top regional tier. Spans AFICIONADO, ALEVIN, CADETE, INFANTIL, JUVENIL. |
| 2 | `DIVISION DE HONOR` | Second tier for youth (ALEVIN–JUVENIL). Not used for adult categories. |
| 3 | `SUPERLIGA` | Third tier for some youth formats (ALEVIN, CADETE, INFANTIL). |
| 3 | `LIGA NACIONAL` | National league tier for JUVENIL specifically. Parallel to SUPERLIGA. |
| 4 | `PREFERENTE` | Present across most age groups and adult categories. |
| 5 | `SEGUNDA DIVISION B` | Adult/senior only (appears as SENIOR and sala formats). |
| 5 | `TERCERA FEDERACION` | Adult federation tier (RFEF). Parallel to SEGUNDA DIVISION B. |
| 6 | `PRIMERA` | Most common mid-tier across all ages. |
| 7 | `SEGUNDA` | Below PRIMERA. Youth and SENIOR. |
| 8 | `TERCERA` | Lowest named tier. Appears in adult sala. |
| — | `FASE ZONAL` | Zonal qualifying phase — not a standing league tier, cross-zone playoff structure. Age group parsed from `nombre`. |
| — | `CAMPEONATO UNIVERSITARIO` | University championship, separate pyramid (UNIVERSITARIO only). |
| — | `LIGA UNIVERSITARIA` | University league, separate pyramid (UNIVERSITARIO only). |
| — | `OTHER` | No division token in either `NombreCategoria` or `nombre`. Typical cases: bare age-only labels (`BENJAMIN SALA`, `ALEVIN FEMENINO SALA`, `PREBENJAMIN SALA`), special formats (`FUTBOL ANDANDO F-7`, `DEBUTANTE`), and copa/torneo competitions with no tier marker. |

## Notes on using `tier`

`tier` is not a column in `competitions.csv` — it is a lookup you apply
from this table. To compare two competitions by level, join on
`division_level` and map to `tier`.

The tier ordering is **within-pyramid only** — it is meaningful when
comparing two competitions of the same `category_base` and `game_type`.
Comparing tiers across age groups (e.g. BENJAMIN PRIMERA vs JUVENIL
SEGUNDA) is usually not meaningful.

SUPERLIGA and LIGA NACIONAL share tier 3 because they appear at the same
level in different category contexts; they are not strictly comparable to
each other. Same for SEGUNDA DIVISION B and TERCERA FEDERACION at tier 5.

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
