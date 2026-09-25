# Full Howdies Feature Port To TalkinChat Design

## Status

Approved scope: port the complete Howdiesbot feature set at source commit
`f2567a1` into the independent TalkinChat repository. Copy and adapt the code;
do not create a runtime dependency on Howdiesbot.

## Outcome

TalkinChat will provide the same user-facing commands, games, economy, social,
AI, media, moderation, activity, collector, reporting, diagnostics, multi-bot,
and operational features as Howdiesbot wherever TalkinChat can express the
behavior. Howdies-specific protocol features will use verified TalkinChat
operations or explicit text/DM fallbacks. No guessed websocket payloads are
allowed in production.

The parity baseline is the fresh `tanvrkhan/howdiesbot` `main` commit
`f2567a1`. Later Howdies changes are outside this migration and require a new
parity review.

## Non-Negotiable Isolation

TalkinChat remains independent from Howdiesbot in repository, Python
environment, process, service, credentials, configuration, databases, state,
logs, deployment releases, collectors, backups, and rollback. TalkinChat code
must not import Howdiesbot modules or read Howdiesbot runtime files.

The only shared runtime resource is the local Ollama server/model. Both bots
coordinate model access through `/run/lock/local-ollama.lock`, a neutral
cross-process file lock containing no credentials, usernames, room data, or
bot-specific state.

## Porting Strategy

The current TalkinChat legacy `main.py` remains available as a rollback target
until parity verification passes. The new runtime is built from the Howdies
module structure:

- `bot.py`: TalkinChat lifecycle, reconnect loop, normalized event handling,
  command dispatch, and feature orchestration.
- `commands.py`: compatibility import surface and command registrations.
- `command_modules/`: focused command groups for meta/media, rooms/admin,
  games, cards/cricket, economy/social, moderation, activity, and bot control.
- `registry.py`: comma/exclamation parsing, aliases, permissions, help, and
  dispatch metadata. Comma is the primary displayed prefix.
- `config.py`: immutable environment-backed runtime configuration.
- `config_store.py`: TalkinChat-only mutable operational configuration.
- `transports/talkinchat.py`: all TalkinChat websocket and upload payloads,
  event normalization, reconnect behavior, and capability declarations.
- `services/`: copied and adapted Howdies pure services, each retaining focused
  tests and TalkinChat-owned storage paths.

Business services cannot construct websocket payloads. Commands cannot access
raw websocket objects. Only the transport adapter knows TalkinChat handlers,
payload fields, endpoints, or upload forms.

## Verified TalkinChat Transport

The adapter is grounded in the existing TalkinChat protocol evidence:

- Websocket: `wss://chatp.net:5333/server`.
- Upload: `https://cdn.talkinchat.com/post.php`.
- Login handler: `login` with `id`, `username`, and `password`.
- Room join/leave: `room_join` and `room_leave` using stable room display names.
- Room messages: `room_message` with `text`, `image`, or `audio` type.
- Private messages: `chat_message` to a username.
- Incoming handlers currently verified: `login_event` and `room_event`.
- Incoming room event types currently verified: `text`, `image`, and
  `user_joined`.

The adapter exposes `say`, `reply`, `send_dm`, `send_image`, `send_audio`,
`upload`, `join_room`, `leave_room`, `rejoin_room`, `kick`, membership lookup,
and a capability query. Payload builders are pure functions with contract
tests.

## Capability Translation

Howdies composer buttons become numbered text options and ordinary commands.
Every interactive action carries a session/version token so stale or forged
commands are rejected just as stale Howdies buttons are rejected.

Private game information uses TalkinChat DMs. A game requiring hidden hands or
choices does not start unless the adapter confirms private delivery. Public
state always has a complete text representation; images are enhancements.

Roles, profile reads/writes, targeted room messages, muting, promotion,
ownership changes, rich presence, and richer membership controls remain
capability-gated. A verified payload implementation may enable a capability.
Otherwise commands return a precise text fallback and do not claim success.

Room names preserve configured display spelling and use Unicode case-folded
keys for lookup. Usernames preserve display spelling and use Unicode
case-folded keys for permissions and state because stable TalkinChat numeric
user IDs are not currently verified. State schemas reserve a nullable protocol
user ID so verified IDs can be adopted without rewriting history.

## Complete Feature Scope

The port includes every command registration and alias present in the baseline
Howdies `commands.py`. A generated parity manifest records source command,
aliases, category, permission level, TalkinChat implementation, capability
requirements, fallback, tests, and rollout status. CI fails when any baseline
command is absent from the manifest or registry.

Feature groups include:

1. Meta and help: help, syntax, ping, uptime, command categories, aliases, and
   comma-first examples.
2. Music and media: YouTube/JioSaavn audio, TTS, image/GIF search, drawing,
   uploads, OCR, and AI image generation with quotas and diagnostics.
3. Fun and AI: dictionary, horoscope, jokes, quotes, weather, wiki,
   translation, calculator, dice, coin flip, 8-ball, AI chat, AI profiles,
   roasts, compliments, and room auto-replies.
4. Rooms and administration: room information, members, recent users,
   where-is, joins/leaves/rejoin, room search, invites, command enable/disable,
   prefix, admins, welcomes, and configuration.
5. Economy and social: XP, health, shields, armor, market, purchases, daily
   streaks, gifts, ranks, transfers, reputation, profiles, likes, betting,
   blackjack, lottery, shipping, marriage, AFK, reminders, polls, and
   confessions.
6. Games: slap, bomb, continuous quizzes, scramble, math, emoji, fast finger,
   number game, word chain, would-you-rather, bingo, RPS, duel, roulette,
   vampire, story, hangman, tic-tac-toe, count, Thulla, Rang, UNO, and universal
   game termination.
7. Cross-room cricket: lobbies, teams, AI players, matchmaking, toss, private
   numbered choices, overs, wickets, stakes, bets, scoreboards, statistics,
   persistence, timeout replacement, settlement, cancellation, and restart
   recovery.
8. Moderation: censor lists/exemptions, warnings, automod, kick, mute/unmute,
   roles/promotions/demotions where supported, permission checks, and audit
   records.
9. Activity and privacy: public activity collection, message retention,
   creator history search, room reports, admin logs, last-active lookup,
   retention cleanup, and privacy-safe AI profile samples.
10. Collectors and bot operations: collector-only accounts, connect/disconnect,
    bot status, instance listing, command relay, game protocol recording,
    access/profile/button diagnostics, and health/readiness reporting.

## Data And Privacy

Public message text is retained for three days. Join/leave events, last
activity, moderation/audit events, and AI profiles are retained for thirty
days. Direct-message content is never collected. Creator history search can
read retained public text. Room reports expose metadata and totals, not message
text, and recheck current room authority for every page.

Collector accounts have separate credentials and systemd instances. Collector
mode cannot dispatch commands, participate in games, send room/DM messages,
upload media, or collect DMs. Collectors visit only rooms the account can
legitimately enter and record privacy-safe public activity.

Every privileged action, collector transition, and value-changing operation
emits a protected audit event without credentials, tokens, private content, or
signed URLs.

## State And Integrity

TalkinChat stores mutable state under `/var/lib/talkinchat-bot` with private
permissions. SQLite is used for activity, audit, quotas, and searchable data.
Atomic JSON stores with file locks are retained for deterministic game state
where the copied Howdies service already supplies validated atomic persistence.

Economy amounts are integer units. Reservations, transfers, purchases, stakes,
refunds, and settlements require idempotency keys and immutable transaction
records. Related changes succeed or fail together. Corrupt state is
quarantined rather than silently replaced.

Schema migrations are forward-safe, tested against fixtures, backed up before
activation, and recoverable. State is never migrated from Howdiesbot.

## Delivery Phases

1. Foundation replacement: new module structure, event models, TalkinChat
   adapter, registry, permissions, config/state roots, reconnect loop, malformed
   event handling, and parity manifest.
2. Shared utilities and media: normalization, uploads, music, images, drawing,
   OCR, TTS, fun utilities, Ollama locking, AI, profiles, image generation,
   quotas, and diagnostics.
3. Rooms and operations: membership caches, joins/leaves, welcomes, room
   search, recent users, admin configuration, capability fallbacks, audit, and
   multi-instance controls.
4. Economy and social: XP/health, market, ledger, ranks, transfers, reputation,
   relationships, AFK, reminders, polls, confessions, betting, blackjack, and
   lottery.
5. Core games: slap, bomb, quizzes, number/word games, bingo, RPS, duel,
   roulette, vampire, story, hangman, tic-tac-toe, and count.
6. Card games: shared session manager, private delivery preflight, Thulla, Rang,
   UNO, persistence, text controls, images, timeouts, and restart recovery.
7. Cricket: cross-room manager, durable lobbies/matches, AI, private choices,
   scores, bets, statistics, cancellation, and recovery.
8. Moderation and activity: censor, warnings, automod, supported room actions,
   collector services, retention, reports, creator history, and protocol
   diagnostics.
9. Parity and production cutover: generated command comparison, full tests,
   staging-account journeys, restart/reconnect recovery, blue-green release,
   readiness gate, automatic rollback, and legacy `main.py` retirement only
   after acceptance.

Every phase leaves a runnable TalkinChat bot and is committed and pushed after
its verification gate. Incomplete features remain disabled rather than
advertised in help.

## Testing And Acceptance

Tests are ported with their services and rewritten only where transport-facing
expectations differ. Required layers are:

- Pure unit tests for services, rules, parsers, permissions, normalization,
  ledgers, quotas, retention, and deterministic games.
- TalkinChat payload contract tests for login, room/DM/media operations,
  capability checks, uploads, room spelling, and normalized identities.
- Registry tests for both prefixes, aliases, help, permissions, disabled
  commands, stale actions, and DM/room restrictions.
- Recovery tests for reconnects, duplicate events, malformed JSON, partial
  frames, unknown handlers, timeouts, restart restoration, refunds, and
  idempotent settlements.
- Cross-room tests for state isolation, slap, card sessions, and cricket.
- Collector tests proving no DMs, commands, messages, media, or game actions.
- Security tests for permission bypass, forged actions, path confinement,
  secret redaction, history authorization, and upload limits.
- Deployment tests for immutable releases, shared TalkinChat-only state,
  readiness, automatic rollback, release cleanup, and continuous Howdiesbot
  availability.

Parity is complete when every baseline command appears in the manifest, every
enabled command has success/failure/permission tests, every unsupported
capability has an asserted fallback, the complete suite passes on Python 3.12,
staging-account journeys pass, TalkinChat survives restart/reconnect tests, and
Howdiesbot remains active with unchanged state and service configuration.

## Deployment And Rollback

TalkinChat adopts an independent blue-green release layout under
`/root/talkinchat/`: immutable releases, private staging directories, shared
TalkinChat state, `current` and `previous` symlinks, readiness markers, bounded
health checks, and automatic rollback. Its workflow, concurrency group,
service units, environment files, logs, and cleanup never reference Howdiesbot
paths or services.

The main service and collector instances are activated only after candidate
tests, compilation, dependency installation, state backup, configuration
validation, and staging-account readiness. Failed activation restores the
previous TalkinChat release. It never restarts or rolls back Howdiesbot.

## Operational Limits

Network operations have explicit connect/read timeouts. Upload size, media
duration, AI concurrency, image quotas, collector pacing, message retention,
game timers, and reconnect backoff are bounded and configurable. Logs are
structured, redact secrets/private content, and include correlation IDs for
commands, games, uploads, collector visits, and deployments.

## Self-Review

- Scope is locked to the fresh Howdies baseline commit and includes all command
  groups plus collector, privacy, diagnostics, and deployment behavior.
- The design copies code into TalkinChat ownership and preserves runtime
  isolation.
- Unverified protocol behavior is capability-gated and never guessed.
- Private game information has a verified-delivery prerequisite.
- Mutable data, value changes, migrations, retention, backups, and rollback
  have explicit integrity rules.
- Each phase is independently runnable, testable, commit-ready, and deployable.
- There are no unresolved placeholders; implementation details are delegated to
  the numbered implementation plan after this specification is approved.
