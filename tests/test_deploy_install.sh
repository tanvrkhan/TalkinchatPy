#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

app_dir="$tmp_root/root/TalkinchatPy"
mkdir -p "$app_dir/deploy" "$tmp_root/bin"
cp "$repo_root/deploy/install.sh" "$app_dir/deploy/install.sh"
cp "$repo_root/deploy/talkinchat-bot.service" "$app_dir/deploy/talkinchat-bot.service"
cp "$repo_root/deploy/talkinchat-bot.env.example" "$app_dir/deploy/talkinchat-bot.env.example"
cp "$repo_root/requirements.txt" "$app_dir/requirements.txt"

grep -q 'python3-venv' "$app_dir/deploy/install.sh"
grep -q 'ffmpeg' "$app_dir/deploy/install.sh"
grep -q 'tesseract-ocr' "$app_dir/deploy/install.sh"

systemctl_log="$tmp_root/systemctl.log"
cat > "$tmp_root/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
EOF
chmod +x "$tmp_root/bin/systemctl"

ROOT_PREFIX="$tmp_root" \
TALKINCHAT_APP_DIR="$app_dir" \
SKIP_SYSTEM_PACKAGES=1 \
SKIP_DEPENDENCIES=1 \
SYSTEMCTL_BIN="$tmp_root/bin/systemctl" \
SYSTEMCTL_LOG="$systemctl_log" \
    bash "$app_dir/deploy/install.sh"

env_file="$tmp_root/etc/talkinchat-bot.env"
unit_file="$tmp_root/etc/systemd/system/talkinchat-bot.service"

test -f "$env_file"
test "$(stat -f '%Lp' "$env_file" 2>/dev/null || stat -c '%a' "$env_file")" = "600"
test -d "$tmp_root/var/lib/talkinchat-bot"
test -f "$unit_file"
grep -q '^WorkingDirectory=/root/TalkinchatPy$' "$unit_file"
grep -q '^EnvironmentFile=/etc/talkinchat-bot.env$' "$unit_file"
grep -q '^daemon-reload$' "$systemctl_log"
grep -q '^enable talkinchat-bot.service$' "$systemctl_log"
grep -q '^stop talkinchat-bot.service$' "$systemctl_log"
if grep -q '^restart talkinchat-bot.service$' "$systemctl_log"; then
    echo "installer restarted service without credentials" >&2
    exit 1
fi

echo "deployment installer contract passed"
