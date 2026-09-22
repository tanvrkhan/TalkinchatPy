# TalkinchatPy

Legacy TalkinChat bot under staged modernization. The current runtime preserves
the original websocket, upload, music, draw, OCR, text-to-speech, and welcome
behavior while loading credentials from the environment.

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
Talkinchat Websocket Bot in Python
