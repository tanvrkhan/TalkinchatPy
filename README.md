# TalkinchatPy

Modern TalkinChat bot using the verified websocket/upload protocol with a
modular command registry, transport adapter, AI/media services, economy,
games, moderation, public activity retention, and reconnect recovery. The
legacy `main.py` remains in the repository as a manual rollback target.

The runtime authenticates through TalkinChat's binary API, discovers its
assigned WebSocket server dynamically, and exchanges protobuf frames matching
Android app version 5.8.3.

## Runtime configuration

Required variables:

- `TALKINCHAT_USERNAME`
- `TALKINCHAT_PASSWORD`
- `TALKINCHAT_ROOM`

`TALKINCHAT_OWNER` is optional and defaults to `TALKINCHAT_USERNAME`.

## VM service

The GitHub Actions deployment installs an isolated service named
`talkinchat-bot.service` under `/opt/talkinchat/current`. Immutable releases
live under `/opt/talkinchat/releases`; the prior accepted release is retained
at `/opt/talkinchat/previous` for automatic rollback. Credentials live only in
`/etc/talkinchat-bot.env`, state belongs under `/var/lib/talkinchat-bot`, and
logs are available from journald:

```bash
systemctl status talkinchat-bot --no-pager
journalctl -u talkinchat-bot -n 100 --no-pager
```

The installer preserves the environment file and keeps the service stopped
until all required values are present. After editing the file with mode `0600`,
start it with:

```bash
/opt/talkinchat/current/deploy/configure.sh
```

Rollback is independent from Howdiesbot: activation restores the
`/opt/talkinchat/previous` release automatically if readiness or login fails.
The service runs as the dedicated unprivileged `talkinchat` account.

The service runs `bot.py`. Commands accept both `,` and `!`; help displays the
comma prefix. TalkinChat and Howdiesbot share only the local Ollama endpoint and
the neutral `/run/lock/local-ollama.lock` coordination file.
Talkinchat Websocket Bot in Python
