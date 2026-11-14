#!/usr/bin/env bash
# Between judge groups: wipe today's memory (voices and contacts are kept), wait for Kin to come back, seed a morning.
cd "$(dirname "$0")/.."
PORT="${KIN_PORT:-8700}"
bash scripts/clean_slate.sh
for i in $(seq 1 40); do
  sleep 1
  curl -s "http://127.0.0.1:$PORT/api/snapshot" | grep -q '"band": *"connected"\|"band":"connected"' && break
done
sleep 2
bash scripts/seed_morning.sh
