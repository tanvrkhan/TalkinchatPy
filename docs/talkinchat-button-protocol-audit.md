# TalkinChat Interactive Button Protocol Audit

## Result

Android app version 5.8.3 does not expose a native interactive-message or bot
button schema. TalkinChat bot workflows must provide text-command controls.

## Evidence

- `ChatMessage` contains type, id, sender, recipient, body, URL, length, UID,
  state, offline state, timestamp, and ownership fields. It has no button,
  callback, keyboard, or reply-markup field.
- `RoomEvent` contains room message, presence, role, media, profile, and room
  metadata. It has no interactive-action model.
- The outbound `Query` protobuf has generic values used by existing app
  operations, but no app code constructs interactive chat messages from them.
- Android `Button` references belong to local screens and dialogs; they are not
  serialized into WebSocket room or private messages.

## Decision

The transport continues to report `Capabilities.BUTTONS` as unsupported. Game
and social prompts expose comma-prefixed commands, including numbered choices,
and retain version checks for stale actions. Native buttons may be reconsidered
only after a later official client or captured server event demonstrates an
actual interoperable schema.
