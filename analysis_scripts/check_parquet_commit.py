#!/usr/bin/env python3
"""Guard for the open/closed Parquet git policy (see PARQUET_CLOSURE.md).

Nothing previously stopped an ordinary `git add`/`git commit` from
committing an open-season or never-closing-stage Parquet snapshot -
`parquet_closure.py`'s closure logic was only ever consulted by
parquet-build.yml's own git-add step. That gap is not hypothetical: it's
exactly how commits d7bf2da/83ac65f (clubs/, clubs_extended.parquet,
club_teams.parquet, 2017-2018 acta_partido - caught and reverted within
the same PR before merge) and 42fec3f (crawl_log/data_quality_report for
every season - never reverted, still committed on main as of this
writing) got into git history: a session ran session-start-open.sh to
regenerate open-season/never-closing Parquet locally for querying (as
intended), then a routine `git add`/`git commit` swept the regenerated
files in too. This script is the guard that would have caught both -
reusable from a git pre-commit hook (staged files) and from CI (files
changed vs a PR's base ref).

Deliberately conservative: only flags files this policy actually has an
opinion on - the season-partitioned tables in parquet_closure.TABLE_STAGE/
LOG_FAMILY_TABLES (must be closed), plus players.parquet/clubs_extended.
parquet/club_teams.parquet (PARQUET_CLOSURE.md says these must never be
committed at all - gitignored / club_profiles never closes). A path it
doesn't recognize (e.g. team_club_map.parquet/team_club_gap_reasons.parquet
- out of scope for this policy, not in TABLE_STAGE, no PARQUET_CLOSURE.md
row - see that file's "Table -> owning stage" section) is left alone
rather than guessed at; inventing a rule the project hasn't stated would
just trade false negatives for false positives.

Usage:
    python analysis_scripts/check_parquet_commit.py <path> [<path> ...]
    git diff --cached --name-only --diff-filter=ACMR \
        -- output/processed/rffm_parquet | \
        xargs -r python analysis_scripts/check_parquet_commit.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import parquet_closure as pc  # noqa: E402

# PARQUET_CLOSURE.md: gitignored (players.parquet) or "never closes" so its
# Parquet copy is never committed at all (clubs_extended.parquet/
# club_teams.parquet - club_profiles stage), regardless of season.
NEVER_COMMIT_FILES = {
    "players.parquet": "gitignored (see .gitignore) - the CSV is the git-tracked copy, never this",
    "clubs_extended.parquet": "club_profiles stage never closes - PARQUET_CLOSURE.md: Parquet copy is never committed",
    "club_teams.parquet": "club_profiles stage never closes - PARQUET_CLOSURE.md: Parquet copy is never committed",
}


def _relative_to_parquet_dir(raw: str) -> Path | None:
    parts = Path(raw).parts
    if "rffm_parquet" not in parts:
        return None
    return Path(*parts[parts.index("rffm_parquet") + 1:])


def check(paths: list[str]) -> list[tuple[str, str]]:
    manifest = pc.load_manifest()
    violations = []
    for raw in paths:
        rel = _relative_to_parquet_dir(raw)
        if rel is None:
            continue
        parts = rel.parts

        if len(parts) == 1:
            reason = NEVER_COMMIT_FILES.get(parts[0])
            if reason:
                violations.append((raw, reason))
            continue

        if len(parts) != 2 or not parts[1].endswith(".parquet"):
            continue
        table, season = parts[0], parts[1][: -len(".parquet")]

        if table in pc.LOG_FAMILY_TABLES:
            closed = pc.log_family_closed_seasons(manifest)
        elif table in pc.TABLE_STAGE:
            closed = pc.table_closed_seasons(table, manifest)
        else:
            continue  # out of this policy's scope - not TABLE_STAGE/LOG_FAMILY_TABLES

        if season not in closed:
            how = (
                "python analysis_scripts/parquet_closure.py"
                if table in pc.LOG_FAMILY_TABLES
                else f"python analysis_scripts/parquet_closure.py --table {table}"
            )
            violations.append((
                raw,
                f"({table!r}, season={season!r}) is not a closed (season, stage) pair - "
                f"run `{how}` to see why",
            ))
    return violations


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        return
    violations = check(paths)
    if not violations:
        return
    print(
        "Blocked: these staged Parquet files aren't safe to commit under the "
        "open/closed policy\nin PARQUET_CLOSURE.md:\n",
        file=sys.stderr,
    )
    for path, reason in violations:
        print(f"  {path}\n    {reason}\n", file=sys.stderr)
    print(
        "Only parquet-build.yml's automated job (via `parquet_closure.py "
        "--list-committable`) is\nmeant to commit these. If this is a deliberate, "
        "reviewed exception (project owner's\nexplicit call - see PARQUET_CLOSURE.md), "
        "bypass with `git commit --no-verify`.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
