import asyncio
import tempfile
import unittest
from pathlib import Path

from bot import TalkinChatBot, check_readiness
from config import Config
from transports.talkinchat import Event, EventKind


class FakeTransport:
    def __init__(self, upload_error=None):
        self.messages = []
        self.images = []
        self.upload_error = upload_error

    async def say(self, room, text):
        self.messages.append((room, text))

    async def upload(self, path, room, mime_type):
        if self.upload_error:
            raise self.upload_error
        return "https://cdn.talkinchat.com/welcome.png"

    async def send_image(self, room, url):
        self.images.append((room, url))


class WelcomeAndReadinessTests(unittest.TestCase):
    def config(self, root):
        return Config.from_env({
            "TALKINCHAT_USERNAME": "bot", "TALKINCHAT_PASSWORD": "pw",
            "TALKINCHAT_ROOM": "My Room", "TALKINCHAT_STATE_DIR": root,
            "TALKINCHAT_OLLAMA_LOCK": str(Path(root) / "locks" / "ollama.lock"),
        })

    def test_join_event_sends_configured_welcome_text_case_insensitively(self):
        with tempfile.TemporaryDirectory() as root:
            bot = TalkinChatBot(self.config(root))
            bot.transport = FakeTransport()
            bot.store.set("welcome_rooms", {"my room": True})
            bot.store.set("custom_welcomes", {"my room": "Welcome {user} to {room}!"})
            event = Event(EventKind.USER_JOINED, room="MY ROOM", user="Alice", user_key="alice")
            asyncio.run(bot.handle_join(event))
            self.assertEqual([("MY ROOM", "Welcome Alice to MY ROOM!")], bot.transport.messages)

    def test_welcome_image_failure_degrades_to_text(self):
        with tempfile.TemporaryDirectory() as root:
            bot = TalkinChatBot(self.config(root))
            bot.transport = FakeTransport(RuntimeError("upload failed"))
            bot.store.set("welcome_rooms", {"my room": True})
            bot.store.set("welcome_images", {"my room": True})
            event = Event(EventKind.USER_JOINED, room="My Room", user="Alice", user_key="alice")
            asyncio.run(bot.handle_join(event))
            self.assertEqual([("My Room", "Welcome Alice!")], bot.transport.messages)

    def test_readiness_creates_private_state_and_lock_directories(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.config(str(Path(root) / "state"))
            check_readiness(config)
            self.assertTrue(config.state_dir.is_dir())
            self.assertEqual(0o700, config.state_dir.stat().st_mode & 0o777)
            self.assertTrue(config.ollama_lock.parent.is_dir())


if __name__ == "__main__":
    unittest.main()
