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
