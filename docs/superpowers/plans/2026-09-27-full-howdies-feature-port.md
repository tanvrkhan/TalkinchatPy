# Full Howdies Feature Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Copy the complete Howdiesbot feature baseline at commit `f2567a1` into TalkinChat ownership, translate its protocol boundary, and deploy a separately configured TalkinChat bot beside Howdiesbot.

**Architecture:** Preserve `main.py` as the rollback runtime while introducing a modular `bot.py`, command registry, command modules, pure services, and a single `TalkinChatTransport` boundary. All mutable data, credentials, processes, releases, logs, and service units remain TalkinChat-specific; only Ollama and its neutral cross-process lock are shared.

**Tech Stack:** Python 3.12, asyncio, websockets, requests, Pillow, SQLite, unittest, GitHub Actions, systemd, rsync

**Spec:** `docs/superpowers/specs/2026-09-25-full-howdies-feature-port-design.md`

**Global Constraints:** Never import Howdiesbot at runtime, guess unsupported TalkinChat payloads, expose credentials, collect DM content, mix room state, use mutable display names as database identifiers, or alter/restart Howdiesbot. Keep comma as the displayed prefix while accepting comma and exclamation. Keep the legacy entry point deployable until live login/join and rollback checks pass.

**Review Focus:** Protocol payload correctness, capability fallbacks, permission enforcement, transaction/idempotency invariants, reconnect recovery, private-game delivery, path/secret isolation, parity-manifest completeness, and deployment rollback.

## Shared Interface Map

| Producer | Interface | Consumers |
|---|---|---|
| `config.py` | immutable `Config.from_env`, TalkinChat paths and bounded timeouts | bot, services, deployment validation |
| `transports/talkinchat.py` | normalized events; `say`, `reply`, `send_dm`, `send_image`, `send_audio`, `upload`, room operations, capabilities | bot and command contexts only |
| `registry.py` | decorator, parser, aliases, permission metadata, help catalog | command modules and bot dispatcher |
| `config_store.py` | atomic TalkinChat-only mutable settings | commands, welcomes, moderation |
| `services/*` | protocol-free business operations | command modules and bot orchestration |
| `parity/howdies-f2567a1.json` | source command inventory and TalkinChat status/fallback | parity test, help, release gate |

### Task 1: Freeze parity inputs and establish the modular skeleton

**Files:** Create `parity/howdies-f2567a1.json`, `scripts/check_parity.py`, `tests/test_parity_manifest.py`, `config.py`, `registry.py`, `config_store.py`, `commands.py`, `command_modules/__init__.py`, `services/__init__.py`, `transports/__init__.py`; modify `requirements.txt`, `.gitignore`.

- [ ] Generate a deterministic command/alias inventory from the clean Howdies `f2567a1` reference and record source commit, category, permission, capability, fallback, and rollout status for every registration.
- [ ] Write a failing parity test that rejects duplicate names/aliases, missing baseline commands, absent fallbacks, and a primary prefix other than comma.
- [ ] Copy the Howdies registry/config-store/service source into this repository as TalkinChat-owned code, retaining license/provenance notes and pinning required dependencies.
- [ ] Replace `HOWDIES_` names and paths with `TALKINCHAT_` equivalents; keep state beneath `TALKINCHAT_STATE_DIR` (default `/var/lib/talkinchat-bot`).
- [ ] Run `python3 -m unittest tests.test_parity_manifest -v`, `python3 scripts/check_parity.py`, compile all Python files, and commit/push the foundation.

### Task 2: Implement and contract-test the TalkinChat transport

**Files:** Create `transports/talkinchat.py`, `tests/test_talkinchat_transport.py`, `tests/test_transport_events.py`; modify `config.py`.

- [ ] Write failing pure payload tests for login, room join/leave, text/image/audio room messages, DM messages, uploads, stable room spelling, and username/room case-folding.
- [ ] Write failing event tests for login, text, image, join, unknown handler/type, malformed JSON, missing fields, duplicates, and partial websocket frames.
- [ ] Implement immutable normalized event models and payload builders grounded only in verified `wss://chatp.net:5333/server` and `https://cdn.talkinchat.com/post.php` behavior.
- [ ] Implement the adapter methods and capability declarations; unsupported kick/role/profile/button/member operations must return typed unsupported results without sending guessed payloads.
- [ ] Add bounded upload size, connect/read timeouts, correlation IDs, and redacted structured logging.
- [ ] Run focused transport tests, compile checks, `git diff --check`, then commit/push.

### Task 3: Build lifecycle, dispatch, permissions, and reconnect recovery

**Files:** Create `bot.py`, `command_modules/meta.py`, `tests/test_registry.py`, `tests/test_permissions.py`, `tests/test_bot_reconnect.py`, `tests/test_cross_room_dispatch.py`; modify `commands.py`, `config_store.py`.

- [ ] Write failing tests for comma/exclamation parsing, aliases, help examples, disabled commands, creator/admin/room-admin checks, room/DM restrictions, normalized identities, and room-isolated contexts.
- [ ] Write deterministic reconnect tests for backoff, relogin, rejoin, duplicate suppression, cancellation, malformed events, and continuation after unknown events.
- [ ] Implement `CommandContext`, registry dispatch, permission resolution, capability-aware replies, and comma-first help.
- [ ] Implement `TalkinChatBot` login/join/event loop with bounded exponential reconnect and explicit shutdown; commands receive the transport interface, never raw websockets.
- [ ] Add `--check-config`, `--check-readiness`, and collector-mode startup validation without connecting to production.
- [ ] Run registry/permission/reconnect/cross-room tests and the full current suite, then commit/push.

### Task 4: Port shared utility, AI, media, upload, and welcome services

**Files:** Copy/adapt `services/ai.py`, `services/draw.py`, `services/fun.py`, `services/image_generation.py`, `services/image_quota.py`, `services/images.py`, `services/music.py`, `services/upload.py` and related tests; create `services/ollama_lock.py`, `command_modules/media.py`, `command_modules/fun_ai.py`.

- [ ] Port service tests first, changing only Howdies transport expectations and adding timeout, size, quota, traversal, and failure-fallback cases.
- [ ] Implement neutral Ollama serialization with `/run/lock/local-ollama.lock`, bounded acquisition, process-safe release, and no bot state in the lock.
- [ ] Adapt music, draw, OCR, TTS, image/GIF search, AI image generation, uploads, utility commands, profiles, roasts, compliments, and auto-replies to transport methods.
- [ ] Preserve legacy TalkinChat welcome/music/draw/upload behavior and use text or DM fallback when rich media is unavailable.
- [ ] Run all utility/media/AI tests plus an offline command smoke test, then commit/push.

### Task 5: Port rooms, membership, configuration, audit, and bot operations

**Files:** Create/adapt `services/activity_store.py`, `services/auth.py`, `services/relay.py`, `command_modules/rooms.py`, `command_modules/operations.py`, `tests/test_rooms.py`, `tests/test_capability_fallbacks.py`, `tests/test_bot_operations.py`.

- [ ] Write failing tests for room name preservation, case-insensitive lookup, membership cache updates, recent users, joins/leaves/rejoin, welcomes, admins, enable/disable, and mutable prefix compatibility.
- [ ] Add capability tests proving roles, profile changes, buttons, kick, targeted messages, and membership controls either use verified support or return precise text fallbacks.
- [ ] Port room search, room info, who/where-is, config, access diagnostics, instance status, connect/disconnect, and relay with creator authorization and protected audit events.
- [ ] Ensure all bot-instance credentials/config/state are TalkinChat-only and collector credentials are separately addressable.
- [ ] Run room/operation/security tests and full suite, then commit/push.

### Task 6: Port economy and social features with transactional integrity

**Files:** Copy/adapt `services/coin_ledger.py`, `services/slap.py`, social/economy helpers, `command_modules/economy.py`, `command_modules/social.py`, and related Howdies tests; create `tests/test_economy_security.py`.

- [ ] Port ledger tests first for balanced integer entries, authorization, idempotency, transfer/purchase/stake/refund atomicity, concurrency, corrupt-state quarantine, and cross-room identity normalization.
- [ ] Port XP, health, shields, armor, market, daily streaks, gifts, ranks, reputation, profiles, likes, betting, blackjack, lottery, shipping, marriage, AFK, reminders, polls, and confessions.
- [ ] Route every value change through the ledger with immutable reason, actor, timestamp, and idempotency key; never use floating point.
- [ ] Add command success/failure/permission tests and protected audit records without private content.
- [ ] Run economy/social/ledger tests and full suite, then commit/push.

### Task 7: Port core room and cross-room games

**Files:** Copy/adapt `services/game_control.py`, `services/game_store.py`, `services/game_recorder.py`, quiz/game helpers, `command_modules/games.py`, and related tests.

- [ ] Port deterministic tests for slap, bomb, quizzes, scramble, math, emoji, fast finger, number, word chain, would-you-rather, bingo, RPS, duel, roulette, vampire, story, hangman, tic-tac-toe, count, and universal termination.
- [ ] Replace buttons with numbered/versioned text actions and reject stale, forged, wrong-room, or unauthorized actions.
- [ ] Enforce one compatible game session per scope, bounded timers, deterministic cancellation, restart restoration, and room isolation.
- [ ] Preserve public text state even when game images are sent; private choices must use DM and fail closed when unavailable.
- [ ] Run game, recovery, abuse, and cross-room tests, then commit/push.

### Task 8: Port Thulla, Rang, and UNO card sessions

**Files:** Copy/adapt `services/card_session.py`, `services/cards.py`, `services/thulla.py`, `services/rang.py`, `services/uno.py`, `command_modules/cards.py`, and related tests.

- [ ] Port card-rule, session-transition, image-rendering, timeout, persistence, stale-action, and restart-recovery tests.
- [ ] Require successful private-delivery preflight before games with hidden hands begin; abort without mutating stakes when DM is unavailable.
- [ ] Implement numbered text controls with session/version tokens for hand, trump, color, challenge, catch-UNO, resume, and play actions.
- [ ] Keep sessions room-safe and make cancellation/refund idempotent.
- [ ] Run all card tests and full suite, then commit/push.

### Task 9: Port durable cross-room cricket

**Files:** Copy/adapt `services/cricket.py`, `services/cricket_ai.py`, `services/cricket_models.py`, `services/cricket_renderer.py`, `services/cricket_store.py`, `command_modules/cricket.py`, and related tests.

- [ ] Port model, manager, store, rendering, AI-choice, cross-room, timeout, settlement, cancellation, and restart-recovery tests before adapter changes.
- [ ] Implement lobbies, teams, AI players, matchmaking, toss, overs, wickets, private numbered choices, scoreboards, statistics, stakes, and bets.
- [ ] Use durable unique match/action IDs; settlements and refunds must remain idempotent under reconnect and restart.
- [ ] Verify private choices cannot leak into room output or logs and wrong-player/wrong-match/stale actions are rejected.
- [ ] Run cricket, ledger integration, recovery, and full tests, then commit/push.

### Task 10: Port moderation, activity retention, collectors, history, and reports

**Files:** Extend `services/activity_store.py`, `services/auth.py`; create `command_modules/moderation.py`, `command_modules/activity.py`, collector entry/config; add `tests/test_moderation.py`, `tests/test_activity_privacy.py`, `tests/test_collector_mode.py`, `tests/test_history_authorization.py`.

- [ ] Write failing tests for censor/exemptions, warnings, automod, current-authority rechecks, creator history, report metadata, retention cleanup, and audit redaction.
- [ ] Prove collector mode cannot dispatch commands, collect DMs, send room/DM/media messages, upload, or join games; apply bounded room pacing.
- [ ] Store public room messages for three days and activity/audit/profile data for thirty days in TalkinChat SQLite; never store DM bodies.
- [ ] Implement moderation capability fallbacks and creator-authorized history/report pagination with reauthorization on every request.
- [ ] Run privacy/moderation/collector/security tests and full suite, then commit/push.

### Task 11: Close command parity and production quality gates

**Files:** Complete `command_modules/*`, `commands.py`, `parity/howdies-f2567a1.json`; create `tests/test_command_parity.py`, `tests/test_malformed_and_limits.py`; update `README.md` and operational docs.

- [ ] Compare the live registry against the source inventory and fail for every missing command/alias, undocumented capability, advertised-disabled command, or missing fallback/test mapping.
- [ ] Add table-driven permission, room/DM, malformed-input, resource-limit, and fallback tests for every registered command.
- [ ] Run formatting/static checks available in the repository, dependency audit, compile checks, all unit/integration/contract tests, and `git diff --check` on Python 3.12.
- [ ] Review secret/path isolation, logs, state migrations, backup/restore, and all requirements in the approved spec; record verification evidence.
- [ ] Commit/push the parity-complete runtime while keeping `main.py` as rollback.

### Task 12: Blue-green deploy, staging login, cutover, and rollback proof

**Files:** Replace/adapt `deploy/install.sh`, `deploy/talkinchat-bot.service`, `.github/workflows/deploy.yml`; create `deploy/release.sh`, `deploy/talkinchat-collector@.service`, deployment contract/tests and runbook.

- [ ] Port immutable release/current/previous layout, private staging, TalkinChat-only backup, readiness marker, bounded health checks, release cleanup, and automatic rollback tests.
- [ ] Change the service entry point to `bot.py` only after config validation and offline readiness pass; keep legacy `main.py` selectable for immediate rollback.
- [ ] Push `master`, observe GitHub Actions, and verify TalkinChat paths/service/logs/state are separate while `howdies-bot.service` remains active and unchanged.
- [ ] On the VM, validate credential-key presence without printing values, start TalkinChat, and verify staging-account login, configured room join, comma/exclamation help, reconnect, media fallback, and graceful restart from sanitized logs.
- [ ] Prove rollback by switching to `previous`, checking service readiness, and returning to the accepted release; document exact release IDs and evidence.
- [ ] Run the final local and deployed verification gates, commit/push any corrections, and report login instructions without exposing the password.

## Plan Self-Review

- All nine delivery phases and every feature group from the approved specification map to Tasks 1-12.
- Shared interfaces identify producer/consumer order, so transport, registry, configuration, and ledger dependencies precede their consumers.
- Every task starts with behavioral tests, ends with focused/full verification, and creates a recoverable commit/push checkpoint.
- Unsupported protocol features are capability-gated with explicit fallback tests; no task authorizes guessed payloads.
- Deployment keeps legacy rollback and requires live login/join evidence without touching Howdiesbot.
- The plan contains no placeholder tasks; credentials remain external and are checked only for presence.
