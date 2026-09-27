#!/usr/bin/env bash
set -euo pipefail

release_id="${1:?release id required}"
incoming="${2:?incoming directory required}"
base="/opt/talkinchat"
releases="$base/releases"
release="$releases/$release_id"
current="$base/current"
previous="$base/previous"
state="/var/lib/talkinchat-bot"
env_file="/etc/talkinchat-bot.env"
service="talkinchat-bot.service"

rollback() {
    echo "TalkinChat activation failed; starting rollback." >&2
    if [[ -L "$previous" ]]; then
        target="$(readlink -f "$previous")"
        ln -sfn "$target" "$current.rollback"
        mv -Tf "$current.rollback" "$current"
        systemctl restart "$service" || true
    else
        systemctl stop "$service" || true
    fi
}
trap rollback ERR

TALKINCHAT_APP_DIR="$incoming" bash "$incoming/deploy/install.sh"
install -d -m 0755 "$releases"
test ! -e "$release"
mv "$incoming" "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --disable-pip-version-check -q -r "$release/requirements.txt"
"$release/.venv/bin/python" -m compileall -q "$release"

backup="$base/backup-$release_id.tar.gz"
tar -C "$state" -czf "$backup" .
chmod 0600 "$backup"

if [[ -L "$current" ]]; then
    ln -sfn "$(readlink -f "$current")" "$previous.next"
    mv -Tf "$previous.next" "$previous"
fi
ln -sfn "$release" "$current.next"
mv -Tf "$current.next" "$current"

credentials_complete=true
for key in TALKINCHAT_USERNAME TALKINCHAT_PASSWORD TALKINCHAT_ROOM; do
    value="$(sed -n "s/^${key}=//p" "$env_file" | tail -n 1)"
    [[ -n "$value" ]] || credentials_complete=false
done

if [[ "$credentials_complete" == "true" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
    runuser -u talkinchat -- "$release/.venv/bin/python" "$release/bot.py" --check-readiness
    rm -f "$state/ready.json"
    systemctl restart "$service"
    for _ in $(seq 1 30); do
        [[ -s "$state/ready.json" ]] && break
        sleep 1
    done
    test -s "$state/ready.json"
    systemctl is-active --quiet "$service"
else
    systemctl stop "$service"
    echo "TalkinChat release activated; credentials are still required."
fi

trap - ERR
find "$releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -nr | awk 'NR>5 {sub(/^[^ ]+ /, ""); print}' \
    | while IFS= read -r old; do rm -rf -- "$old"; done
find "$base" -maxdepth 1 -name 'backup-*.tar.gz' -printf '%T@ %p\n' \
    | sort -nr | awk 'NR>5 {sub(/^[^ ]+ /, ""); print}' \
    | while IFS= read -r old; do rm -f -- "$old"; done

echo "TalkinChat release $release_id activated."
