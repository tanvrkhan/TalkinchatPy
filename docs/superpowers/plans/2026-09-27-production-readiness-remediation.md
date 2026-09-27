# TalkinChat Production Readiness Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every finding in the 2026-09-27 whole-work audit and deploy a secure, recoverable, feature-complete TalkinChat runtime without affecting Howdiesbot.

**Architecture:** Keep the modular bot/registry/transport/services structure and make permission checks authoritative at dispatch. Move every mutable artifact beneath the TalkinChat state root, wire lifecycle services explicitly, replace compatibility registrations with real TalkinChat-safe handlers, and deploy immutable releases through a least-privilege systemd account with automatic rollback.

**Tech Stack:** Python 3.12, asyncio, websockets 12, SQLite/atomic JSON, unittest, systemd, Bash, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-25-full-howdies-feature-port-design.md`

## Global Constraints

- Howdiesbot may not be restarted, modified, or share credentials/state/logs with TalkinChat.
- Comma and exclamation prefixes remain accepted; comma remains primary in help.
- Unsupported TalkinChat protocol capabilities must return honest text fallbacks.
- All behavior changes are test-first and each task ends with the complete suite passing.
- Credentials remain outside Git and are never printed.

## Review Focus

- Ordinary users cannot invoke room-admin or global-admin mutations.
- Deployment never deletes mutable economy, game, activity, or configuration state.
- Every baseline command has a native handler or a capability-specific, truthful implementation; no generic placeholder layer remains.
- WebSocket protocol closure, malformed frames, failed login, and idle disconnects recover with bounded backoff.
- Failed activation restores the prior TalkinChat release while Howdiesbot remains active.

---

### Task 1: Authoritative permissions and audit records

**Files:** Modify `registry.py`, `bot.py`, `services/auth.py`, `command_modules/moderation.py`, `command_modules/rooms.py`; add permission and audit tests.

- [ ] Add failing tests proving ordinary users cannot mutate censor/warnings, room authorities are scoped, and privileged changes write sanitized audit records.
- [ ] Pass an authorization callback in dispatch context and enforce `room_admin` plus configured room authorities.
- [ ] Record successful and rejected privileged actions without message bodies or secrets.
- [ ] Run focused and full tests; commit.

### Task 2: Durable state, retention, and lifecycle recovery

**Files:** Modify `config.py`, `bot.py`, `services/slap.py`, `services/activity_store.py`, `services/card_session.py`; add lifecycle tests.

- [ ] Add failing tests for state-root confinement, retention cleanup, restored card timers, and WebSocket protocol reconnects.
- [ ] Route economy state and locks beneath `TALKINCHAT_STATE_DIR`; remove repository-local mutable defaults.
- [ ] Restore persisted sessions, schedule retention cleanup, and catch transport closure exceptions with bounded backoff.
- [ ] Run focused and full tests; commit.

### Task 3: Welcome, media, and readiness behavior

**Files:** Modify `bot.py`, `command_modules/media.py`, `command_modules/rooms.py`, `services/upload.py`; add welcome/upload/readiness tests.

- [ ] Add failing tests for configured join welcomes, welcome-image fallback, verified uploads, and dependency-aware readiness.
- [ ] Wire join events to TalkinChat-owned welcome configuration and transport upload.
- [ ] Replace the obsolete Howdies upload module with verified TalkinChat helpers.
- [ ] Implement offline config checks separately from bounded operational readiness checks.
- [ ] Run focused and full tests; commit.

### Task 4: Native utility, room, social, and moderation parity

**Files:** Replace `command_modules/compat.py`; extend focused command modules and pure services; update parity manifest/tests.

- [ ] Add table-driven failing tests requiring native handlers and success/failure/permission behavior for each utility, room, social, moderation, and operations command.
- [ ] Port protocol-independent Howdies behavior and use explicit capability fallbacks only where TalkinChat cannot perform the operation.
- [ ] Remove generic “recognized but not enabled” responses and mark implemented manifest statuses accurately.
- [ ] Run focused and full tests; commit.

### Task 5: Native games, cards, and cricket parity

**Files:** Extend game/card/cricket command modules and services; add command journey and restart tests.

- [ ] Add failing command-level tests for all game controls, private delivery, stakes, cancellation, statistics, and restart restoration.
- [ ] Connect existing pure engines to complete text-first TalkinChat command flows.
- [ ] Implement remaining protocol-independent games with durable room-scoped state.
- [ ] Run focused and full tests; commit.

### Task 6: Least-privilege immutable deployment

**Files:** Add `deploy/release.sh`, collector unit and runbook; modify service, installer, workflow, and deployment tests.

- [ ] Add failing deployment tests for a dedicated user, restrictive umask, immutable releases, state backup, current/previous links, health gate, rollback, cleanup, and Howdies isolation.
- [ ] Deploy under `/opt/talkinchat/releases`, run as `talkinchat`, retain state in `/var/lib/talkinchat-bot`, and share only the neutral Ollama lock group/path.
- [ ] Activate only after config/readiness checks and roll back automatically on failure.
- [ ] Run shell/unit/full tests; commit.

### Task 7: Final verification and production cutover

**Files:** Update README/runbook and verification evidence.

- [ ] Run formatting, compilation, dependency, unit, integration, contract, permission, recovery, and deployment suites on Python 3.12.
- [ ] Push the branch and master; require the GitHub deployment job to pass.
- [ ] Verify VM permissions, service security, TalkinChat isolation, rollback links, sanitized logs, and continuous Howdiesbot availability.
- [ ] If credentials are present, verify login/join/help/reconnect/media and graceful restart; otherwise leave the service safely stopped and provide the secure setup command.
