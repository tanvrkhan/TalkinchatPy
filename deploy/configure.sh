#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/etc/talkinchat-bot.env"
SERVICE="talkinchat-bot.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this setup as root." >&2
  exit 1
fi

read -r -p "TalkinChat username: " username
read -r -s -p "TalkinChat password: " password
printf '\n'
read -r -p "TalkinChat room: " room

if [[ -z "${username}" || -z "${password}" || -z "${room}" ]]; then
  echo "Username, password, and room are all required." >&2
  exit 1
fi

escape_env_value() {
  local value="$1"
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  printf '"%s"' "$value"
}

python3 - "$ENV_FILE" \
  "TALKINCHAT_USERNAME=$(escape_env_value "$username")" \
  "TALKINCHAT_PASSWORD=$(escape_env_value "$password")" \
  "TALKINCHAT_ROOM=$(escape_env_value "$room")" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
updates = dict(item.split("=", 1) for item in sys.argv[2:])
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
result = []
seen = set()

for line in lines:
    key = line.split("=", 1)[0] if "=" in line else ""
    if key in updates:
        result.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        result.append(line)

for key, value in updates.items():
    if key not in seen:
        result.append(f"{key}={value}")

path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY

chmod 600 "$ENV_FILE"
systemctl restart "$SERVICE"
systemctl --no-pager --full status "$SERVICE"
