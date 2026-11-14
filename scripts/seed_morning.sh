#!/usr/bin/env bash
# Feeds a believable morning through the running Kin (same pipeline: brain, memory, summary), so the family page
# isn't empty at the start of a demo. Nothing here mentions Sarah, keys or money, so the live part stays fresh.
# Say it plainly if asked: "This morning was typed in through the same pipeline; everything after is live."
PORT="${KIN_PORT:-8700}"
k() { curl -s -X POST "http://127.0.0.1:$PORT/api/command" -H 'Content-Type: application/json' \
      -d "$(printf '{"cmd": %s}' "$(printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")" >/dev/null; }
k "2 Hello Joe, this is Doctor Patel's office."; sleep 0.5
k "2 Please take your new blood pressure pill with food, twice a day, starting tomorrow."; sleep 0.5
k "w Okay. With food, twice a day."; sleep 9
k "3 Hey Joe, it's Mike from next door. Could you water my plants on Saturday while I'm away?"; sleep 0.5
k "w Sure Mike, Saturday it is."; sleep 9
k "w I left my reading glasses on the nightstand."
echo "Morning seeded. The family page fills in within ~30 s."
