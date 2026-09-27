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

chmod 640 "$ENV_FILE"
chown root:talkinchat "$ENV_FILE"
rm -f /var/lib/talkinchat-bot/ready.json
systemctl restart "$SERVICE"
for _ in $(seq 1 30); do
  [[ -s /var/lib/talkinchat-bot/ready.json ]] && break
  sleep 1
done
if [[ ! -s /var/lib/talkinchat-bot/ready.json ]]; then
  echo "TalkinChat did not confirm login. Check the username, password, and room." >&2
  journalctl -u "$SERVICE" -n 20 --no-pager >&2 || true
  exit 1
fi
systemctl --no-pager --full status "$SERVICE"
