# TalkinChat Deployment Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the existing TalkinChat bot to the Howdies VM as an isolated, credential-gated systemd service without changing its user-visible behavior.

**Architecture:** Load runtime identity and room settings from a validated environment module instead of source code. GitHub Actions deploys to `/root/TalkinchatPy`, installs an independent virtual environment, installs `talkinchat-bot.service`, and preserves `/etc/talkinchat-bot.env` plus `/var/lib/talkinchat-bot`. The first deployment succeeds with the service stopped until credentials are entered securely on the VM.

**Tech Stack:** Python 3, unittest, GitHub Actions, rsync, systemd, virtualenv

**Spec:** `docs/talkinchat-modernization-design.md`

## Global Constraints

- Keep TalkinChat separate from Howdiesbot in process, environment, credentials, state, logs, deployment path, and systemd service.
- Preserve the current websocket endpoint, upload endpoint, commands, music, draw, upload, and welcome behavior.
- Never commit or print the TalkinChat password.
- Keep the service stopped when required credentials are absent.
- Share no runtime files with Howdiesbot; a neutral Ollama lock can be added only when the AI service is ported.

---

### Task 1: Environment-backed runtime settings

**Files:**
- Create: `runtime_config.py`
- Modify: `main.py`
- Create: `tests/test_runtime_config.py`

**Interfaces:**
- Produces: `RuntimeConfig.from_env(environ)` and `RuntimeConfig.require_valid()`.
- Consumes: `TALKINCHAT_USERNAME`, `TALKINCHAT_PASSWORD`, `TALKINCHAT_ROOM`, and optional `TALKINCHAT_OWNER`.

- [ ] Write tests proving whitespace is normalized, owner defaults to username, and missing required values fail without exposing the password.
- [ ] Run `python3 -m unittest tests.test_runtime_config -v` and confirm the tests fail because `runtime_config` does not exist.
- [ ] Implement the immutable configuration object and replace hardcoded runtime identity values in `main.py`.
- [ ] Run the focused tests and `python3 -m py_compile main.py runtime_config.py`.
- [ ] Commit the independently runnable configuration change.

### Task 2: Isolated systemd deployment assets

**Files:**
- Create: `deploy/talkinchat-bot.service`
- Create: `deploy/talkinchat-bot.env.example`
- Create: `deploy/install.sh`
- Create: `tests/test_deploy_install.sh`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Produces: system unit `talkinchat-bot.service`, environment file `/etc/talkinchat-bot.env`, state directory `/var/lib/talkinchat-bot`, and virtual environment `/root/TalkinchatPy/.venv`.
- Consumes: deployed repository at `/root/TalkinchatPy`.

- [ ] Add a shell test that installs into a temporary root and verifies paths, permissions, and credential-gated startup behavior.
- [ ] Run the shell test and confirm it fails before `deploy/install.sh` exists.
- [ ] Implement an idempotent installer that never overwrites the environment file and enables the unit without starting it when credentials are missing.
- [ ] Document secure credential entry, service start, status, logs, and rollback commands.
- [ ] Run the shell test plus `systemd-analyze verify deploy/talkinchat-bot.service` when available.
- [ ] Commit the deployment assets.

### Task 3: GitHub Actions deployment and VM verification

**Files:**
- Create: `.github/workflows/deploy.yml`
- Create: `tests/test_deploy_contract.py`

**Interfaces:**
- Consumes: GitHub secrets `VM_HOST`, `VM_USER`, and `VM_SSH_KEY`.
- Produces: deployment to `/root/TalkinchatPy` and installation through `deploy/install.sh`.

- [ ] Add contract tests asserting the workflow targets `master`, uses a TalkinChat-specific concurrency group and paths, excludes secrets/state, and never restarts Howdiesbot.
- [ ] Run the contract test and confirm it fails because the workflow is absent.
- [ ] Implement checkout, tests, SSH setup, rsync, remote install, and credential-gated service status reporting.
- [ ] Run all unit and deployment contract tests, compile checks, and `git diff --check`.
- [ ] Push `master`, watch the Actions run, and verify `/root/TalkinchatPy`, `/etc/talkinchat-bot.env`, and `talkinchat-bot.service` on the VM while confirming `howdies-bot.service` remains active.
- [ ] Commit any verification-driven correction and push again before handoff.
