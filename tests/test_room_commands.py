import asyncio
import tempfile
import unittest
from pathlib import Path

import commands  # noqa: F401
from config_store import ConfigStore
from registry import DispatchContext, REGISTRY
from registry import PermissionDenied
from transports.talkinchat import OperationResult


class Recorder:
    def __init__(self):
        self.session = None

    def start(self, room, target, game, creator):
        self.session = {"room_id": room, "target": target.casefold(), "game": game,
                        "creator": creator, "events": 0, "started_at": 1, "path": "/tmp/x"}
        return dict(self.session)

    def status(self, room):
        return dict(self.session) if self.session and self.session["room_id"] == room else None

    def stop(self, room):
        result = self.status(room)
        if result is None:
            raise ValueError("No game recording is active in this room.")
        self.session = None
        return result


class Transport:
    def __init__(self):
        self.joined = []

    async def join_room(self, room):
        self.joined.append(room)

    async def kick(self, room, user):
        self.kicked = (room, user)
        return OperationResult(True)

    async def set_role(self, room, user, role):
        self.role = (room, user, role)
        return OperationResult(True)

    async def invite(self, room, user):
        self.invited = (room, user)
        return OperationResult(True)


class Bot:
    def __init__(self, root):
        self.transport = Transport()
        self.store = ConfigStore(root)
        self.game_recorder = Recorder()
        self.replies = []

    async def reply(self, context, text):
        self.replies.append(text)

    def refresh_access(self):
        pass

    def members_for_room(self, room):
        return ("Alice", "Bob")


class RoomCommandTests(unittest.TestCase):
    def test_join_preserves_room_spelling(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            asyncio.run(REGISTRY.dispatch(
                bot, DispatchContext("owner", "", "admin"), ",join My Room"))
            self.assertEqual(["My Room"], bot.transport.joined)

    def test_kick_uses_verified_transport_and_validates_target(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            asyncio.run(REGISTRY.dispatch(
                bot, DispatchContext("owner", "My Room", "admin"), ",kick Alice"))
            self.assertEqual(("My Room", "Alice"), bot.transport.kicked)
            self.assertIn("Alice", bot.replies[-1])

    def test_admin_owner_member_and_setrole_use_verified_transport(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            context = DispatchContext("owner", "My Room", "creator")
            for command, role in (
                    (",admin Alice", "admin"), (",owner Bob", "owner"),
                    (",member Carol", "member"), (",setrole Dave none", "none")):
                self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, command)))
                self.assertEqual(("My Room", command.split()[1], role), bot.transport.role)

    def test_admin_configuration_syntax_still_manages_bot_admins(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            context = DispatchContext("owner", "My Room", "creator")
            self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",admin add Helper")))
            self.assertEqual(["helper"], bot.store.get("admins"))

    def test_moderation_commands_require_room_authority(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            ordinary = DispatchContext("user", "My Room")
            for command in (",kick Alice", ",admin Alice", ",owner Alice", ",member Alice"):
                with self.assertRaises(PermissionDenied):
                    asyncio.run(REGISTRY.dispatch(bot, ordinary, command))

    def test_role_aliases_resolve_to_native_handlers(self):
        self.assertIs(REGISTRY.get("owner"), REGISTRY.get("makeowner"))
        self.assertIs(REGISTRY.get("member"), REGISTRY.get("demote"))
        self.assertIs(REGISTRY.get("promote"), REGISTRY.get("a"))
        self.assertIs(REGISTRY.get("setrole"), REGISTRY.get("role"))

    def test_ownership_transfer_is_creator_only(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            room_admin = DispatchContext(
                "moderator", "My Room", room_authority=True)
            self.assertTrue(asyncio.run(REGISTRY.dispatch(
                bot, room_admin, ",owner Alice")))
            self.assertFalse(hasattr(bot.transport, "role"))
            self.assertIn("creator", bot.replies[-1].casefold())

    def test_invite_and_member_list_are_native(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            context = DispatchContext("owner", "My Room", "creator")
            self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",invite Alice")))
            self.assertEqual(("My Room", "Alice"), bot.transport.invited)
            self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",who")))
            self.assertIn("Alice", bot.replies[-1])
            self.assertIn("Bob", bot.replies[-1])

    def test_censorkick_toggle_and_public_game_recording_are_initialized(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            context = DispatchContext("owner", "My Room", "creator")
            self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",censorkick on")))
            self.assertTrue(bot.store.get("censorkick_rooms")["my room"])
            self.assertTrue(asyncio.run(REGISTRY.dispatch(
                bot, context, ",recordgame start OtherBot cricket")))
            self.assertEqual("otherbot", bot.game_recorder.status("My Room")["target"])
            self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",recordgame stop")))
            self.assertIsNone(bot.game_recorder.status("My Room"))


if __name__ == "__main__":
    unittest.main()
