#!/bin/bash
set -euo pipefail

# Web/remote sessions only - a local dev checkout typically already has
# dependencies installed and players.parquet regenerated as needed.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# output/processed/rffm_parquet/players.parquet is deliberately gitignored
# (see .gitignore / DATA_DICTIONARY.md's "Two copies of the data" section)
# - every other table under rffm_parquet/ is committed and present right
# after checkout, but this one is regenerated from the git-tracked
# players_current.csv. Without this, any report/query that reads the
# "players" table (rffm_data.read_table("players"), or an ad hoc DuckDB
# query against players.parquet) fails with FileNotFoundError on a fresh
# session - this bit the pages-deploy.yml CI workflow for real (see git
# history) before that workflow got its own explicit rebuild step; this
# hook gives interactive sessions the same fix automatically.
pip install -q -r requirements.txt
python analysis_scripts/build_parquet.py --output-dir output/processed/rffm_parquet --players-only
