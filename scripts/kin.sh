#!/usr/bin/env bash
# Start Kin once and leave it running. When the code changes, Kin restarts by itself and
# reconnects to the band without a double-tap (a dropped band stays findable for 2 minutes).
#   bash scripts/kin.sh            # real band
#   bash scripts/kin.sh --sim      # pretend band
cd "$(dirname "$0")/.."
echo "Kin: double-tap the band now (blue blink). Pages: http://localhost:8700  and  http://localhost:8700/test"
KIN_RELOAD=1 exec .venv/bin/watchfiles --filter python --sigint-timeout 3 --ignore-paths kin/voiceprint.py \
  --target-type command ".venv/bin/python -m kin.app --no-console $*" kin
