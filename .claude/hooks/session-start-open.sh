#!/bin/bash
set -euo pipefail

# Web/remote sessions only - see session-start.sh for the same guard.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Async: --open-only takes ~2 minutes (measured), too slow to block every
# session start on. Trade-off (see the session-start-hook skill): a query
# against a still-open (season, stage) table run in the first ~2 minutes
# of the session could race this and hit a stale/missing file. Accepted -
# most of the dataset (every CLOSED season/stage - currently all of core,
# 8/9 of acta_partido, 3/9 of fichajugador) is already present via git
# checkout with no wait at all; this hook only needs to fill in the
# currently-open handful (see analysis_scripts/parquet_closure.py --stage
# for the live list) that parquet-build.yml deliberately never commits.
echo '{"async": true, "asyncTimeout": 300000}'

cd "$CLAUDE_PROJECT_DIR"
pip install -q -r requirements.txt
python analysis_scripts/build_parquet.py --output-dir output/processed/rffm_parquet --open-only
