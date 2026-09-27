import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from bot import TalkinChatBot
from config import Config
from services.activity_store import ActivityStore


class StateConfinementTests(unittest.TestCase):
    def test_slap_default_is_beneath_talkinchat_state_directory(self):
        with tempfile.TemporaryDirectory() as root:
            env = dict(os.environ, TALKINCHAT_STATE_DIR=root)
            result = subprocess.run(
                [os.sys.executable, "-c", "import services.slap; print(services.slap.DATA_FILE)"],
                cwd=Path(__file__).parents[1], env=env, text=True,
                capture_output=True, check=True,
            )
            self.assertEqual(str(Path(root) / "slap_data.json"), result.stdout.strip())

    def test_bot_startup_applies_activity_retention(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "activity.sqlite3"
            old = ActivityStore(path, now=lambda: 1)
            old.record_message("old", "room", "Room", "user", "User", "expired", occurred_at=1)
            config = Config.from_env({
                "TALKINCHAT_USERNAME": "bot", "TALKINCHAT_PASSWORD": "pw",
                "TALKINCHAT_ROOM": "Room", "TALKINCHAT_STATE_DIR": root,
            })
            TalkinChatBot(config)
            current = ActivityStore(path)
            self.assertEqual([], current.creator_search("expired"))


if __name__ == "__main__":
    unittest.main()
