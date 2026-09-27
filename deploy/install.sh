#!/usr/bin/env bash
set -euo pipefail

root_prefix="${ROOT_PREFIX:-}"
app_dir="${TALKINCHAT_APP_DIR:-${root_prefix}/opt/talkinchat/incoming/install}"
env_file="${root_prefix}/etc/talkinchat-bot.env"
state_dir="${root_prefix}/var/lib/talkinchat-bot"
unit_file="${root_prefix}/etc/systemd/system/talkinchat-bot.service"
base_dir="${root_prefix}/opt/talkinchat"
lock_file="${root_prefix}/run/lock/local-ollama.lock"
systemctl_bin="${SYSTEMCTL_BIN:-systemctl}"

install -d -m 0755 "$(dirname "$env_file")" "$(dirname "$unit_file")"
install -d -m 0755 "$base_dir" "$base_dir/releases" "$base_dir/incoming"
install -d -m 0700 "$state_dir"

if [[ -z "$root_prefix" ]]; then
    getent group talkinchat >/dev/null || groupadd --system talkinchat
    id talkinchat >/dev/null 2>&1 || useradd --system --gid talkinchat --home-dir /var/lib/talkinchat-bot --shell /usr/sbin/nologin talkinchat
    chown talkinchat:talkinchat "$state_dir"
    install -o talkinchat -g talkinchat -m 0660 /dev/null "$lock_file"
fi

if [[ ! -f "$env_file" ]]; then
    install -m 0640 "$app_dir/deploy/talkinchat-bot.env.example" "$env_file"
else
    chmod 0640 "$env_file"
fi
if [[ -z "$root_prefix" ]]; then chown root:talkinchat "$env_file"; fi

install -m 0644 "$app_dir/deploy/talkinchat-bot.service" "$unit_file"

if [[ "${SKIP_SYSTEM_PACKAGES:-0}" != "1" ]]; then
    packages=()
    python3 -c 'import ensurepip' >/dev/null 2>&1 || packages+=(python3-venv)
    command -v ffmpeg >/dev/null 2>&1 || packages+=(ffmpeg)
    command -v tesseract >/dev/null 2>&1 || packages+=(tesseract-ocr)
    if (( ${#packages[@]} > 0 )); then
        apt-get update -q
        DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
    fi
fi

"$systemctl_bin" daemon-reload
"$systemctl_bin" enable talkinchat-bot.service

credentials_complete=true
for key in TALKINCHAT_USERNAME TALKINCHAT_PASSWORD TALKINCHAT_ROOM; do
    value="$(sed -n "s/^${key}=//p" "$env_file" | tail -n 1)"
    if [[ -z "$value" ]]; then
        credentials_complete=false
    fi
done

if [[ "$credentials_complete" != "true" ]]; then
    "$systemctl_bin" stop talkinchat-bot.service
    echo "TalkinChat deployed; service is stopped until /etc/talkinchat-bot.env is configured."
fi
