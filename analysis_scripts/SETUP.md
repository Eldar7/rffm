# Setup Instructions for Stadium Analyzer

## Prerequisites
- Python 3.8+ installed on Windows
- Project root: `c:\git\personal\rffm`

## One-Time Setup

From **Windows PowerShell** (NOT Git Bash):

```powershell
cd c:\git\personal\rffm

# Create virtual environment
python -m venv venv

# Activate it
.\venv\Scripts\activate

# Install dependencies
pip install pandas
```

You should see `(venv)` in your PowerShell prompt.

## Usage

### Every Session

```powershell
cd c:\git\personal\rffm
.\venv\Scripts\activate
python analysis_scripts/stadium_analyzer.py <command> <args>
```

### Example Commands

```powershell
# Analyze stadium by ID
python analysis_scripts/stadium_analyzer.py venue 25693593

# Find stadium by name
python analysis_scripts/stadium_analyzer.py venue-name "STELLA MARIS"

# Find team by name
python analysis_scripts/stadium_analyzer.py team-name "ARAVACA"

# Compare multiple stadiums
python analysis_scripts/stadium_analyzer.py compare 201 212 25693593
```

## Deactivate venv

When done:
```powershell
deactivate
```

## Troubleshooting

**"venv not found"** → Run setup again in PowerShell (not Git Bash)

**"ModuleNotFoundError: pandas"** → Run `pip install pandas` after activation

**"Permission denied"** → On some systems, run PowerShell as Administrator

## Project Structure

```
c:\git\personal\rffm\
├── venv/                          # Virtual environment (created by setup)
├── analysis_scripts/
│   ├── stadium_analyzer.py        # Main analyzer script
│   ├── README.md                  # Quick reference
│   └── SETUP.md                   # This file
├── output/processed/rffm/2025-2026/
│   ├── matches.csv
│   ├── venues.csv
│   ├── teams.csv
│   ├── competitions.csv
│   └── ...
└── .claude/skills/
    └── analyze.md                 # Claude Code skill definition
```
