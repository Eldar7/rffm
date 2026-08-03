# RFFM Stadium & Club Analysis Scripts

Python scripts for analyzing RFFM 2025-2026 season data: stadiums, teams, competitions, match statistics.

## Quick Start

**Setup** (one-time, Windows PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\activate
pip install pandas
```

**Use** (every session):
```powershell
.\venv\Scripts\activate
python analysis_scripts/stadium_analyzer.py venue 25693593
```

See [SETUP.md](SETUP.md) for detailed instructions.

## Commands

```
stadium_analyzer.py venue <id>
    Analyze specific stadium by ID
    Example: venue 25693593

stadium_analyzer.py venue-name "<search>"
    Find and analyze stadium by name (partial match)
    Example: venue-name "STELLA MARIS"

stadium_analyzer.py team <id>
    Analyze team stats by ID
    Example: team 12345

stadium_analyzer.py team-name "<search>"
    Find and analyze team by name (partial match)
    Example: team-name "ARAVACA"

stadium_analyzer.py compare <id1> <id2> [<id3> ...]
    Side-by-side comparison of multiple venues
    Example: compare 201 212 25693593
```

## Output

Each report includes:
- 📍 Venue info: location, surface, field type
- 📊 Statistics: total matches, unique teams
- 🏆 Top 12 clubs by match count
- ⚽ Competitions: breakdown by age group, format, match count

## Real Examples

**Stella Maris College (Futbol-7, U-9):**
```powershell
python analysis_scripts/stadium_analyzer.py venue 25693593
```
→ 129 matches, 17 unique teams, ALEVIN (U-9) Futbol-7

**All Aravaca stadiums:**
```powershell
python analysis_scripts/stadium_analyzer.py venue-name "ARAVACA"
```
→ ANTONIO SANFIZ (11-a-side, 325 matches)
→ NTRA. SRA. BUEN CAMINO (11-a-side, 312 matches)
→ STELLA MARIS COLLEGE (7-a-side, 129 matches)

**Compare three Aravaca stadiums:**
```powershell
python analysis_scripts/stadium_analyzer.py compare 201 212 25693593
```

**C.D. Unión de Aravaca team analysis:**
```powershell
python analysis_scripts/stadium_analyzer.py team-name "UNION DE ARAVACA"
```
→ Win/loss/draw record, home/away split, top venues

## Files

- `stadium_analyzer.py` — Main analyzer (pandas-based)
- `README.md` — This file
- `SETUP.md` — Detailed setup instructions
