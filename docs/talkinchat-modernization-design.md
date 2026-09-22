# TalkinChat Bot Modernization Design

## Status

Accepted for phased implementation. This document records the target architecture
and constraints before replacing the legacy monolithic `main.py`.

## Goals

- Preserve TalkinChat's websocket and upload transports while moving behavior into
  maintainable modules patterned after the Howdiesbot architecture.
- Keep TalkinChat independent from Howdiesbot in repository, process, app
  identity, environment, credentials, state, database/config, logs, deployment,
  and systemd service.
- Allow both bots to share the same local Ollama server/model only through a
  neutral cross-process lock that has no bot-specific state.
- Preserve existing music, draw, upload, image OCR, text-to-speech, welcome, room
  join/leave/rejoin, and owner-only operational behavior unless explicitly
  changed by a later implementation note.
- Accept both comma and exclamation command prefixes. Comma is the primary prefix
  shown in help, examples, and documentation.

## Verified Legacy Protocol

Inspection of `main.py` on `master` verified these current transport values and
payload shapes:

- Websocket endpoint: `wss://chatp.net:5333/server`.
- Upload endpoint: `https://cdn.talkinchat.com/post.php`.
- Login payload: `{"handler":"login","id":..., "username":..., "password":...}`.
- Initial room join payload: `{"handler":"room_join","id":..., "name": room}`.
- Room leave payload: `{"handler":"room_leave","id":..., "name": room}`.
- Room message payload: `{"handler":"room_message","id":..., "room": room,
  "type": "text"|"image"|"audio", "url": ..., "body": ..., "length": ...}`.
- Private message payload: `{"handler":"chat_message","id":..., "to": user,
  "type": "text"|"audio", "url": ..., "body": ..., "length": ...}`.
- Upload form fields: `file`, `jid`, `is_private`, `room`, and `device_id`.
- Incoming event handlers currently used: `login_event`, `room_event`; room
  event types currently used: `text`, `image`, and `user_joined`.

Unverified protocol features such as roles, buttons, profile changes, richer
membership controls, and kick semantics must be treated as optional
capabilities. The adapter must expose stable methods for them, but callers must
receive text fallbacks or explicit unsupported-capability results when the
protocol support is not proven.

## Architecture

The modernization will replace the single-file runtime with these modules:

- `bot.py`: application entrypoint, lifecycle, reconnect loop, signal handling,
  dependency wiring, and top-level logging.
- `commands.py`: command implementations only. Commands receive a normalized
  command context and use services/transport interfaces instead of raw websocket
  payloads.
- `registry.py`: command registration, prefix parsing, aliases, help metadata,
  permissions, and dispatch. It accepts `,command` and `!command`, and renders
  help with comma examples.
- `config_store.py`: TalkinChat-only configuration and state persistence,
  including rooms, owner identities, welcome settings, feature toggles, and
  durable per-room command state.
- `services/`: pure or mostly pure services for reusable behavior:
  - `services/ai.py`: Ollama client guarded by the neutral lock.
  - `services/media.py`: uploads, image generation/composition, OCR, text to
    speech, and media validation.
  - `services/music.py`: YouTube/JioSaavn lookup and audio duration limits.
  - `services/social.py`: economy and social features when ported.
  - `services/games.py`: game state and command logic when ported.
  - `services/moderation.py`: permissions, room operations, and audit events.
  - `services/utils.py`: normalization, ids, clock, retry helpers, and parsing.
- `transports/talkinchat.py`: websocket/upload adapter exposing `say`, `reply`,
  `send_dm`, `send_image`, `kick`, room membership operations, reconnect, event
  normalization, and raw-payload builders covered by tests.

Dependencies point inward: commands depend on service interfaces and the
transport abstraction; services do not depend on websocket payload details;
transport code does not own business rules.

## Runtime Isolation

TalkinChat must have its own:

- Python virtual environment and dependency lock.
- Environment variables and secret files.
- Config/state database or files.
- Logs and audit files.
- systemd unit, service user where practical, working directory, and deployment
  path.
- Process supervisor settings and restart policy.

Shared Ollama access is allowed only by a neutral lock such as a file lock under
an agreed runtime directory. The lock protects local model concurrency and must
not store usernames, rooms, command state, credentials, or bot-specific config.

## Normalization And Permissions

- Room names remain stable and are matched case-insensitively. The configured
  display spelling is preserved for outbound payloads.
- Usernames are normalized for comparisons, permissions, and state keys while
  preserving original display names in messages.
- Owner/moderation checks are capability-based. Commands declare required
  capabilities, and the registry enforces them before command execution.
- Unsupported protocol capabilities return safe text feedback rather than
  raising through the command layer.

## Migration Phases

1. Foundation: module skeleton, config store, transport adapter, registry,
   prefix handling, logging, reconnect handling, and test harness.
2. Shared AI/media/utility services: Ollama lock/client, upload, OCR, draw,
   text-to-speech, id generation, and normalization.
3. Economy/social features: port state and commands into isolated TalkinChat
   storage.
4. Games: port game commands with deterministic pure service tests.
5. Moderation/operations: permissions, room membership operations, capability
   checks, audit logs, and owner commands.
6. Independent deployment: TalkinChat-specific environment, credentials,
   database/config, logs, staging account verification, and systemd service.

Each phase should keep the bot runnable or provide an explicit staging entrypoint
until the legacy `main.py` can be retired.

## Test Strategy

- Pure service tests for parsing, normalization, permissions, media decisions,
  AI lock behavior, economy/social rules, and games.
- Transport payload tests for login, room join/leave, room messages, private
  messages, uploads, unsupported capabilities, and room membership operations.
- Prefix, command, help, and permission tests for comma/exclamation handling and
  owner-only commands.
- Reconnect and malformed-event tests for dropped sockets, invalid JSON,
  missing keys, unknown handlers, and partial payloads.
- Cross-room tests proving state separation, room-name case-insensitivity, and
  stable display names.
- Staging-account verification before production deployment, including upload,
  draw, music, welcome, reconnect, and text fallback behavior.

## Self-Review

- Separation: the design keeps TalkinChat independent from Howdiesbot and limits
  sharing to the neutral Ollama lock.
- Protocol grounding: endpoints and known payloads are verified from the cloned
  `master` branch rather than assumed from handoff notes.
- Compatibility: existing transport, upload, music, draw, and welcome behavior
  are preserved as migration requirements.
- Safety: unverified TalkinChat features are modeled as optional capabilities
  with fallbacks instead of guessed schemas.
- Testability: business rules move into pure services, while transport payloads
  and reconnect behavior receive dedicated tests.

