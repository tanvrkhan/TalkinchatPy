import tempfile
import unittest
from pathlib import Path
from services import slap


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_file = slap.DATA_FILE
        slap.DATA_FILE = str(Path(self.tempdir.name) / "slap.json")
        slap._data = {}

    def tearDown(self):
        slap.DATA_FILE = self.old_file
        slap._data = {}
        self.tempdir.cleanup()

    def test_armor_is_permanent_and_cannot_be_bought_twice(self):
        slap._rec("Alice")["xp"] = 2_000_000
        result = slap.buy_item("Alice", 9, "armor")
        self.assertTrue(result["ok"])
        self.assertEqual(slap.get_xp("Alice"), 1_000_000)
        self.assertEqual(slap.buy_item("Alice", 9, "armor")["error"], "owned")

    def test_insufficient_purchase_does_not_mutate_record(self):
        slap._rec("Alice")["xp"] = 100
        result = slap.buy_item("Alice", 9, "armor")
        self.assertEqual(result["error"], "xp")
        self.assertEqual(slap.get_xp("Alice"), 100)
        self.assertFalse(slap._rec("Alice").get("armor", False))

    def test_market_contains_armor_and_both_shields(self):
        self.assertEqual([item["id"] for item in slap.market_items()],
                         ["armor", "shield-1h", "shield-24h"])


if __name__ == "__main__":
    unittest.main()
