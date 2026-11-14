#!/usr/bin/env bash
# Fresh start before a demo: wipes today's conversations, people, to-dos, items, alerts and purchases.
# Keeps voiceprints (voices Kin learned) and your keys. A backup of the old memory is kept as kin.db.bak.
cd "$(dirname "$0")/.."
[ -f kin.db ] && cp kin.db kin.db.bak && rm -f kin.db && echo "Memory cleared (backup: kin.db.bak)."
# a real content change so the auto-reloader restarts Kin (a plain touch isn't always noticed)
echo "# reload $(date +%s)" > kin/_reload.py && echo "Kin restarts with a clean slate."
