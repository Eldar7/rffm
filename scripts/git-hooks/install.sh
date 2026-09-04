#!/bin/bash
set -euo pipefail

# Manual installer for human contributors (not running inside Claude Code,
# so .claude/hooks/session-start.sh's automatic install never fires).
# Same hook that session-start.sh links on every session start - see
# scripts/git-hooks/pre-commit and PARQUET_CLOSURE.md's "Enforcement"
# section.

repo_root="$(git rev-parse --show-toplevel)"
cp "$repo_root/scripts/git-hooks/pre-commit" "$repo_root/.git/hooks/pre-commit"
chmod +x "$repo_root/.git/hooks/pre-commit"
echo "Installed $repo_root/.git/hooks/pre-commit"
