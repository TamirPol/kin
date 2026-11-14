#!/usr/bin/env bash
# Puts one API key into .env without showing it on screen or in shell history.
#   bash scripts/set_key.sh OPENAI_API_KEY
set -euo pipefail
cd "$(dirname "$0")/.."
name="${1:?usage: bash scripts/set_key.sh KEY_NAME}"
[ -f .env ] || cp .env.example .env
printf 'Paste your %s and press Enter (hidden): ' "$name"
IFS= read -rs value
echo
[ -n "$value" ] || { echo "Nothing entered; .env unchanged."; exit 1; }
KEY_NAME="$name" KEY_VALUE="$value" python3 - <<'EOF'
import os, pathlib
p = pathlib.Path(".env"); name, value = os.environ["KEY_NAME"], os.environ["KEY_VALUE"].strip()
lines = p.read_text().splitlines()
for i, l in enumerate(lines):
    if l.startswith(name + "="):
        lines[i] = f"{name}={value}"
        break
else:
    lines.append(f"{name}={value}")
p.write_text("\n".join(lines) + "\n")
os.chmod(p, 0o600)
print(f"Saved {name} to .env ({len(value)} characters, ends ...{value[-4:]}).")
EOF
