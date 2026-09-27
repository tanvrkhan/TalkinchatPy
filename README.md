# TalkinchatPy

Modern TalkinChat bot using the verified websocket/upload protocol with a
modular command registry, transport adapter, AI/media services, economy,
games, moderation, public activity retention, and reconnect recovery. The
legacy `main.py` remains in the repository as a manual rollback target.

## Runtime configuration

Required variables:

- `TALKINCHAT_USERNAME`
- `TALKINCHAT_PASSWORD`
- `TALKINCHAT_ROOM`

`TALKINCHAT_OWNER` is optional and defaults to `TALKINCHAT_USERNAME`.

## VM service

The GitHub Actions deployment installs an isolated service named
`talkinchat-bot.service` in `/root/TalkinchatPy`. Its credentials live only in
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
chmod 600 /etc/talkinchat-bot.env
systemctl restart talkinchat-bot
systemctl is-active talkinchat-bot
```

Rollback is independent from Howdiesbot: deploy an earlier TalkinchatPy commit
to `/root/TalkinchatPy` and restart only `talkinchat-bot.service`.

The service runs `bot.py`. Commands accept both `,` and `!`; help displays the
comma prefix. TalkinChat and Howdiesbot share only the local Ollama endpoint and
the neutral `/run/lock/local-ollama.lock` coordination file.
Talkinchat Websocket Bot in Python
