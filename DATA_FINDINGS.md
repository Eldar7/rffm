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
