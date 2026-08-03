# Division Level Classification Task — TODO

## Phase 1: Pattern Detection (✅ Complete)
- [x] Analyze all 44 `division_level == 'OTHER'` competitions
- [x] Identify patterns: PREBENJAMÍN F-7, FUTSAL phases, specialty sports, VETERANOS
- [x] Document classification strategy in `division_level_strategy.md`

## Phase 2: Build Classification Function (In Progress)
- [ ] Create `classify_division_level.py` with detection rules:
  - [ ] Rule 1: Phase-based Local Competitions (PRIMERA/SEGUNDA/FASE/CAMPEONES F-7)
  - [ ] Rule 2: Specialty/Adapted Sports (FUTBOL ANDANDO, DEBUTANTE)
  - [ ] Rule 3: Futsal with Phase Structure (BENJAMIN 1ª/2ª Fase FS, COPA)
  - [ ] Rule 4: Female Youth Age Categories (INFANTIL/CADETE/JUVENIL FEMENINO FS)
  - [ ] Rule 5: VETERANOS → REGIONAL tier
- [ ] Add confidence scoring (which rule fired + probability)
- [ ] Log unclassified cases for manual review

## Phase 3: Validation (Not Started)
- [ ] Test on 2025-2026 dataset
- [ ] Manual review sample: 10-20 uncertain cases
- [ ] Measure accuracy against expected patterns
- [ ] Check for false positives/negatives

## Phase 4: Apply to Data (Not Started)
- [ ] Backup original `competitions.csv`
- [ ] Apply classification to 2025-2026 `competitions.csv`
- [ ] Verify no regressions (count by division_level before/after)
- [ ] Regenerate downstream outputs if needed

## Phase 5: Document & Future-Proof (Not Started)
- [ ] Add classification logic to crawler/scraper (so future seasons are pre-classified)
- [ ] Document decision in `README.md` or `DATA_DICTIONARY.md`
- [ ] Update `OPERATIONS.md` if enrichment stages need adjustment

---

## Key Decision Points
- [ ] New tier name: `LOCAL` vs `MUNICIPAL` vs `BEGINNER`?
  - Recommendation: `LOCAL` (consistent with international football classifications)
- [ ] Include VETERANOS in REGIONAL or keep as OTHER for review?
  - Recommendation: REGIONAL (masters competitions are typically federation-wide)
- [ ] Apply retroactively to prior seasons (2024-2025, etc.) or only 2025-2026?
  - Recommendation: Only 2025-2026 (avoid rewriting historical data; revisit per-season if needed)

---

## Estimated Effort
- Phase 2: 1-2 hours (rule building + testing)
- Phase 3: 1 hour (manual validation)
- Phase 4: 30 min (data application)
- Phase 5: 30 min (documentation)
- **Total: 3-4 hours**

## Files Modified
- `analysis_scripts/analyze_other_divisions.py` — current analysis
- `analysis_scripts/division_level_strategy.md` — strategy doc
- `analysis_scripts/classify_division_level.py` — (to create)
- `output/processed/rffm/2025-2026/competitions.csv` — (to update)

## PR Checklist
- [ ] All TODOs in Phase 2–5 complete
- [ ] Validation report in commit message
- [ ] Link to related GitHub issue (if any)
- [ ] Mark for review by data lead
