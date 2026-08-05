# Tournament Naming Variants Across Seasons (RFFM)

This note documents a recurring analytics pitfall: the same competition
concept can appear with different labels depending on the season.

Scope here is intentionally narrow and evidence-based:
- Category track: PREBENJAMIN
- Game type: Futbol-7
- Concept: Primera / Preferente second-phase and Torneo de Campeones flow

## Why this matters

`division_level` is parsed from text labels. If one season writes the level
as a clear token (e.g., `PRIMERA`) and another writes a phase-heavy name
(e.g., `1ª PREBENJAMIN ...`), equivalent competitions may be split between
`PRIMERA` and `OTHER` unless corrected.

## Proven naming variants for the same concept

### Primera PREBENJAMIN - Torneo de Campeones / phase flow

Observed labels by season:

- 2021-2022:
  - `PRIMERA PREBENJAMIN F7 -TORNEO DE CAMPEONES`
- 2022-2023:
  - `PRIMERA PREBENJAMIN F7 - TORNEO DE CAMPEONES`
- 2023-2024:
  - `TORNEO DE CAMPEONES PRIMERA PREBENJAMIN`
  - `T. CAMPEONES PRIMERA PREBENJAMIN SEGUNDA FASE`
  - `T. CAMPEONES PRIMERA PREBENJAMIN FASE FINAL`
- 2024-2025:
  - `TORNEO DE CAMPEONES PRIMERA PREBENJAMIN`
  - `SEGUNDA FASE T. CAMPEONES PRIMERA PREBENJAMIN`
  - `FASE FINAL T. CAMPEONES PRIMERA PREBENJAMIN`
- 2025-2026:
  - `T. CAMPEONES 1ª PREBENJAMIN 1ª FASE`
  - `T. CAMPEONES 1ª PREBENJAMIN 2ª FASE`
  - `T. CAMPEONES 1ª PREBENJAMIN FASE FINAL`

Interpretation: these are naming variants of the same competition family,
not unrelated tournaments.

## Implemented correction in code

To avoid broad unintended reclassification, this repo uses a strict
season+competition_id override in discovery for proven ambiguous labels.

Current PRIMERA overrides:

- 2022-2023:
  - `16948677` (`1ª PREBENJAMIN - 2ª FASE - INICIO - 3 Y 4 MARZO`)
  - `16907698` (`1ª PREBENJAMIN - 2ª FASE - INICIO 10-11-17-18 FEBRERO`)
  - `16969301` (`1ª PREBENJAMIN 2º FASE GRUPO 11`)
- 2025-2026:
  - `26687967` (`T. CAMPEONES 1ª PREBENJAMIN 1ª FASE`)
  - `26700985` (`T. CAMPEONES 1ª PREBENJAMIN 2ª FASE`)
  - `26701868` (`T. CAMPEONES 1ª PREBENJAMIN FASE FINAL`)

See code in `rffm_scraper/discovery.py` (`DIVISION_LEVEL_OVERRIDES`).

## Guardrail for future edits

When proposing new overrides, require all of the following:

1. Cross-season semantic match to an already known competition family.
2. Exact `competition_id` evidence in a specific season.
3. Explicit acceptance that phase-only labels (e.g., generic `1ª Fase`) are
   not auto-promoted without additional proof.

This keeps fixes precise and avoids accidental relabeling of unrelated
competitions.
