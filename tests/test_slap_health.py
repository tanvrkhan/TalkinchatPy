import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

from services import slap


class SlapHealthTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_file = slap.DATA_FILE
        slap.DATA_FILE = str(Path(self.tempdir.name) / "slap.json")
        slap._data = {}
        slap._pending = None

    def tearDown(self):
        slap.DATA_FILE = self.old_file
        slap._data = {}
        slap._pending = None
        self.tempdir.cleanup()

    def seed(self, user, **values):
        record = slap._rec(user)
        record.update(values)
        return record

    def test_health_recovers_ten_per_complete_minute_and_caps(self):
        self.seed("Alice", health=20, health_updated_at=1_000)
        self.assertEqual(slap.health("Alice", now=1_179)["health"], 40)
        self.assertEqual(slap.health("Alice", now=9_000)["health"], 100)

    def test_legacy_and_malformed_health_normalize_safely(self):
        self.seed("Alice", health="bad", health_updated_at=-1)
        status = slap.health("Alice", now=2_000)
        self.assertEqual(status["health"], 100)
        self.assertEqual(status["health_updated_at"], 2_000)

    def test_critical_armor_and_shield_precedence(self):
        self.seed("Alice", health=100, health_updated_at=2_000, armor=True)
        result = slap.apply_slap_damage("Alice", critical=True, now=2_000)
        self.assertEqual((result["damage"], result["health"]), (25, 75))
        slap._data["alice"]["shield_until"] = 3_000
        result = slap.apply_slap_damage("Alice", critical=True, now=2_001)
        self.assertEqual((result["damage"], result["health"], result["blocked"]),
                         (0, 75, True))

    def test_low_health_cannot_raise_hand(self):
        self.seed("Alice", health=0, health_updated_at=2_000)
        result = slap.slap("Alice", 1, 7, "", now=2_010)
        self.assertEqual(result["action"], "health")
        self.assertEqual(result["health"], 0)
        self.assertEqual(result["wait"], 50)

    def test_slap_immediately_plays_against_bot_without_pending_human(self):
        self.seed("Alice", xp=10_000, health=100, health_updated_at=2_000)
        with mock.patch.object(slap.random, "randint", return_value=0), \
                mock.patch.object(slap.random, "random", return_value=0.05):
            result = slap.slap("Alice", 1, 7, "", now=2_000)
        self.assertEqual("fight", result["action"])
        self.assertEqual("Alice", result["winner"]["name"])
        self.assertEqual("TalkinChat Bot", result["loser"]["name"])
        self.assertIsNone(slap.pending())
        self.assertTrue(result["critical"])
        self.assertEqual(result["damage"], 50)
        self.assertEqual(result["loser"]["health"], 50)
        self.assertEqual(result["gained"], slap.WIN_BASE)
        self.assertEqual(result["lost"], 0)

    def test_add_xp_once_persists_xp_and_award_key_atomically(self):
        first = slap.add_xp_once("Alice", "1", 5_000, "card:one:reward:alice")
        slap._data = {}
        slap._load()
        duplicate = slap.add_xp_once(
            "Alice", "1", 5_000, "card:one:reward:alice"
        )

        self.assertEqual({"applied": True, "xp": 5_000}, first)
        self.assertEqual({"applied": False, "xp": 5_000}, duplicate)
        self.assertEqual(5_000, slap.get_xp("Alice"))
        persisted = json.loads(Path(slap.DATA_FILE).read_text(encoding="utf-8"))
        self.assertEqual(
            ["card:one:reward:alice"], persisted["alice"]["award_keys"]
        )

    def test_add_xp_once_does_not_mutate_memory_when_atomic_replace_fails(self):
        slap.add_xp("Alice", "1", 100)
        before = Path(slap.DATA_FILE).read_text(encoding="utf-8")

        with mock.patch.object(slap.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                slap.add_xp_once("Alice", "1", 50, "card:two:reward:alice")

        self.assertEqual(100, slap.get_xp("Alice"))
        self.assertEqual(before, Path(slap.DATA_FILE).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
