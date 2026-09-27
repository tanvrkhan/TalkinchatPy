import json
import tempfile
import unittest
from pathlib import Path


class FoundationTests(unittest.TestCase):
    def test_config_uses_talkinchat_paths_and_neutral_ollama_lock(self):
        from config import Config

        config = Config.from_env({
            "TALKINCHAT_USERNAME": " Bot ",
            "TALKINCHAT_PASSWORD": " secret ",
            "TALKINCHAT_ROOM": " My Room ",
            "TALKINCHAT_STATE_DIR": "/tmp/talkin-state",
        })
        self.assertEqual("Bot", config.username)
        self.assertEqual(("My Room",), config.rooms)
        self.assertEqual(Path("/tmp/talkin-state"), config.state_dir)
        self.assertEqual(Path("/run/lock/local-ollama.lock"), config.ollama_lock)
        self.assertNotIn("secret", repr(config))

    def test_config_rejects_missing_credentials_without_echoing_secret(self):
        from config import Config, ConfigError

        with self.assertRaises(ConfigError) as caught:
            Config.from_env({"TALKINCHAT_PASSWORD": "do-not-print"})
        self.assertNotIn("do-not-print", str(caught.exception))

    def test_copied_http_services_have_a_neutral_user_agent(self):
        import config

        self.assertIn("TalkinChat", config.DEFAULT_UA)

    def test_config_store_writes_atomically_beneath_state_directory(self):
        from config_store import ConfigStore

        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            store.set("admins", ["Alice"])
            self.assertEqual(["alice"], store.get("admins"))
            self.assertEqual(",", store.prefix())
            saved = json.loads((Path(directory) / "bot_config.json").read_text())
            self.assertEqual(["alice"], saved["admins"])
            self.assertEqual([], list(Path(directory).glob("*.tmp")))

    def test_registry_rejects_duplicate_aliases(self):
        from registry import CommandRegistry

        registry = CommandRegistry()
        registry.register("hello", aliases=("hi",))
        with self.assertRaises(ValueError):
            registry.register("other", aliases=("HI",))


if __name__ == "__main__":
    unittest.main()
