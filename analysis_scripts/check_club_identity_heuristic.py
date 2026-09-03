#!/usr/bin/env python3
"""
Ratchet guard against the club_name_raw-based "club identity" heuristic
(`tid_to_club = dict(zip(team_id, club_name_raw))` and its variants) that
club_identity.py replaced - see that module's docstring for the full case
against it (a club's own sponsor/name change silently splits it into two
"clubs", and rarely, two different real clubs sharing identical registered
text silently merge into one).

Not a general lint pass - the plain word `club_name_raw` shows up in lots
of legitimate places (club_identity.py itself, anything just displaying
the raw string). This looks specifically for it being used to BUILD an
identity/grouping key: `dict(zip(...club_name_raw...))`, `.groupby(...
club_name_raw...)`, or the literal `tid_to_club`/`club_key` names every
offending file happened to reuse.

ALLOWLIST below is every file already known to do this - a file on it is
one still-open migration to club_identity.py, tracked and expected. A file
NOT on it that still matches means someone (a person, or me on a later
task) reintroduced the heuristic - fail loudly rather than let it recur
silently, since nothing else in the codebase would catch it. The list is
meant to shrink to empty, never grow - a file that no longer matches must
be removed (this script fails on stale allowlist entries too), and no new
name should ever be added without first checking club_identity.py can't
already do what's needed.

Usage:
    python analysis_scripts/check_club_identity_heuristic.py
Exit 0: no unexpected offenders, allowlist is exactly accurate.
Exit 1: otherwise (prints exactly what's wrong).
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent

# Every file still carrying the heuristic as of the club_identity.py
# migration starting - remove an entry the moment that file switches to
# club_identity.resolve()/attach_club_id(). Keep alphabetical.
ALLOWLIST = {
    "all_players.py",
    "club_division_map.py",
    "club_profile_data.py",  # v1, superseded by the now-migrated club_profile_data_v2.py
    "debutante_analysis.py",
    "player_cards.py",
    "season_comparison.py",
    "season_comparison_v2.py",
    "team_cards.py",
    "weird_scores_report.py",
    "weird_scores_report_v2.py",
}

# A file legitimately reading/re-deriving club_name_raw for reasons that
# are NOT the identity heuristic (club_identity.py builds the real thing
# from it; this checker script's own source would false-positive on its
# docstring/regex text).
EXEMPT_ALWAYS = {"club_identity.py", "check_club_identity_heuristic.py"}

PATTERNS = [
    re.compile(r"dict\(\s*zip\([^)]*club_name_raw", re.S),
    re.compile(r"\.groupby\([^)]*club_name_raw"),
    re.compile(r"\btid_to_club\b"),
    re.compile(r"\bclub_key\s*\("),
]


def offenders() -> set[str]:
    hits = set()
    for path in sorted(HERE.glob("*.py")):
        if path.name in EXEMPT_ALWAYS:
            continue
        text = path.read_text(encoding="utf-8")
        if any(p.search(text) for p in PATTERNS):
            hits.add(path.name)
    return hits


def main() -> int:
    found = offenders()
    unexpected = found - ALLOWLIST
    stale = ALLOWLIST - found

    ok = True
    if unexpected:
        ok = False
        print("club identity heuristic reintroduced in file(s) not on the allowlist:")
        for name in sorted(unexpected):
            print(f"  {name}")
        print("Use club_identity.py (resolve()/attach_club_id()) instead - see its module docstring.")
    if stale:
        ok = False
        print("allowlist entry no longer matches (migration done - remove it from ALLOWLIST):")
        for name in sorted(stale):
            print(f"  {name}")

    if ok:
        print(f"OK - {len(found)} file(s) still pending migration (allowlist accurate).")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
