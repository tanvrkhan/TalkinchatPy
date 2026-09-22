#!/usr/bin/env bash
set -euo pipefail

root_prefix="${ROOT_PREFIX:-}"
app_dir="${TALKINCHAT_APP_DIR:-${root_prefix}/root/TalkinchatPy}"
env_file="${root_prefix}/etc/talkinchat-bot.env"
state_dir="${root_prefix}/var/lib/talkinchat-bot"
unit_file="${root_prefix}/etc/systemd/system/talkinchat-bot.service"
systemctl_bin="${SYSTEMCTL_BIN:-systemctl}"

install -d -m 0755 "$(dirname "$env_file")" "$(dirname "$unit_file")"
install -d -m 0700 "$state_dir"

if [[ ! -f "$env_file" ]]; then
    install -m 0600 "$app_dir/deploy/talkinchat-bot.env.example" "$env_file"
else
    chmod 0600 "$env_file"
fi

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

if [[ "${SKIP_DEPENDENCIES:-0}" != "1" ]]; then
    python3 -m venv "$app_dir/.venv"
    "$app_dir/.venv/bin/python" -m pip install --disable-pip-version-check -q -r "$app_dir/requirements.txt"
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

if [[ "$credentials_complete" == "true" ]]; then
    "$systemctl_bin" restart talkinchat-bot.service
    "$systemctl_bin" is-active talkinchat-bot.service
else
    "$systemctl_bin" stop talkinchat-bot.service
    echo "TalkinChat deployed; service is stopped until /etc/talkinchat-bot.env is configured."
fi
