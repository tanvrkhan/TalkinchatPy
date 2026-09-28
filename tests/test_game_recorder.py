import json
import stat
import tempfile
import unittest
from pathlib import Path

from services.game_recorder import GameRecorder


class GameRecorderTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.recorder = GameRecorder(self.tempdir.name, now=lambda: 1000.0)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_records_only_public_frames_from_the_selected_room(self):
        session = self.recorder.start("7", "CricketBot", "cricket", "Sherry")
        self.assertTrue(self.recorder.record({
            "handler": "chatroommessage", "roomid": "7",
            "username": "CricketBot", "text": "Choose heads or tails",
            "contents": {"data": [{"t": "Heads", "sm": ",heads"}]},
        }))
        self.assertFalse(self.recorder.record({
            "handler": "chatroommessage", "roomid": "8",
            "username": "CricketBot", "text": "Another room",
        }))
        self.assertFalse(self.recorder.record({
            "handler": "chatroommessage", "roomid": "7", "secret": True,
            "userid": 9, "username": "CricketBot", "text": "Private",
        }))
        result = self.recorder.stop("7")

        lines = [json.loads(line) for line in Path(session["path"]).read_text().splitlines()]
        self.assertEqual(1, result["events"])
        self.assertEqual(["start", "frame", "stop"], [line["kind"] for line in lines])
        self.assertEqual(",heads", lines[1]["frame"]["contents"]["data"][0]["sm"])
        self.assertEqual(0o600, stat.S_IMODE(Path(session["path"]).stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE(Path(self.tempdir.name).stat().st_mode))

    def test_status_is_room_scoped_and_second_start_is_rejected(self):
        self.recorder.start(7, "CricketBot", "cricket", "Sherry")
        with self.assertRaisesRegex(ValueError, "already active"):
            self.recorder.start(7, "OtherBot", "cricket", "Sherry")
        self.assertIsNone(self.recorder.status(8))
        self.assertEqual("cricketbot", self.recorder.status("7")["target"])


if __name__ == "__main__":
    unittest.main()
