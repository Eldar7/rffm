# Strategy for Fixing `division_level` Classification

## Current State
- **44 competitions** are tagged as `division_level == 'OTHER'`
- These span multiple categories, game types, and clear competitive structures
- Problem: We're treating LOCAL/MUNICIPAL competitions the same as truly unknown competitions

## Patterns Discovered

### 1. PREBENJAMÍN (Futbol-7) — Clear local tier
```
PRIMERA PREBENJAMÍN F-7           (2,910 matches)  → MUNICIPAL/LOCAL TIER
SEGUNDA FASE PRIMERA PREBENJAMIN  (2,640 matches)  → MUNICIPAL/LOCAL TIER (secondary phase)
T. CAMPEONES 1ª PREBENJAMIN       (   99 matches)  → MUNICIPAL/LOCAL TIER (playoff)
```

### 2. FUTSAL Competitions — Structured by age + phase
```
BENJAMIN 1ª Fase FS      (291 matches)  → PRIMARY phase
BENJAMIN 2ª Fase FS      (422 matches)  → SECONDARY phase
COPA BENJAMIN FS         ( 31 matches)  → CUP/PLAYOFF
```
Pattern: Age group + phase number = clear LOCAL tier

### 3. Specialty Competitions — Niche categories
```
FUTBOL ANDANDO F-7           (63 matches)  → Futbol-7 adapted for blind/low-vision
DEBUTANTE                  (1664 matches)  → Futbol-5 beginner category
FIESTA DE LOS DEBUTANTES    (120 matches)  → Futbol-5 beginner event
```
These are LOCAL/EXHIBITION tier by nature

### 4. VETERANOS/MASTERS — Age-based categories
```
VETERANOS MASCULINO F11      (56 matches)  → Masters/senior
COPA RFFM VETERANOS MOVEMBER (13 matches)  → Cup
```
Likely REGIONAL tier (masters are usually consolidated regionally)

## Classification Rules

### Rule 1: Phase-based Local Competitions
**Pattern:** `PRIMERA ... F-7` + `SEGUNDA FASE` + `T. CAMPEONES`
```
IF competition_name contains ('PRIMERA' or 'SEGUNDA' or 'FASE' or 'CAMPEONES')
   AND game_type in ('Futbol-7', 'Fútbol Sala')
   THEN division_level = 'LOCAL' (or 'MUNICIPAL')
```

### Rule 2: Specialty/Adapted Sports
**Pattern:** `FUTBOL ANDANDO`, `DEBUTANTE`, `FIESTA DE LOS`
```
IF competition_name contains ('ANDANDO' or 'DEBUTANTE' or 'FIESTA DE LOS')
   THEN division_level = 'LOCAL' (exhibition/beginner level)
```

### Rule 3: Futsal Leagues with Clear Phase Structure
**Pattern:** `<AGE> <PHASE> FS`, `COPA <AGE> FS`
```
IF game_type == 'Fútbol Sala'
   AND (
      competition_name matches r'^\w+ [12]ª Fase FS'
      OR competition_name matches r'^COPA \w+ .* FS'
   )
   THEN division_level = 'LOCAL'
```

### Rule 4: Female-only age categories (youth)
**Pattern:** `JUVENIL FEMENINO FS`, `CADETE FEMENINO FS`, `INFANTIL FEMENINO FS`
```
IF game_type == 'Fútbol Sala'
   AND competition_name contains ('FEMENINO')
   AND category matches (INFANTIL, CADETE, JUVENIL, ALEVÍN, BENJAMÍN)
   THEN division_level = 'LOCAL'
```

### Rule 5: VETERANOS → REGIONAL
```
IF competition_name contains 'VETERANOS'
   THEN division_level = 'REGIONAL' (or REGIONAL if large federation)
```

## Why PREBENJAMÍN is Special

1. **Size**: 69.4% of all PREBENJAMÍN matches are `OTHER` tier (5,748 / 8,287)
2. **Simplicity**: No AUTONÓMICA/PREFERENTE/REGIONAL split like older age categories
3. **Age**: PREBENJAMÍN (U-7-8) don't have competitive regional structure
4. **Geography**: Very young players don't travel; competitions are municipal
5. **Scalability**: Clear LOCAL tier can absorb ALL F-7 and "beginner" futsal

## Implementation Order

1. ✅ **Phase 1**: Extract all `division_level == 'OTHER'` competitions
2. ✅ **Phase 2**: Analyze patterns (DONE above)
3. 🔧 **Phase 3**: Build detection rules (regex + keyword matching)
4. 🔧 **Phase 4**: Validate accuracy against random sample
5. 🔧 **Phase 5**: Apply to competitions.csv, regenerate outputs

## Risk Mitigation

- **Test on 2025-2026 first**: Don't retroactively rewrite historical data
- **Log confidence scores**: Mark which rule fired + probability
- **Manual review sample**: Spot-check 10-20 uncertain cases
- **Archive old division_level**: Keep backup in case reversal needed
