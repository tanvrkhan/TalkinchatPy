import tempfile
import unittest
from pathlib import Path

from services.cricket_stats import CricketStats


class CricketStatsTests(unittest.TestCase):
    def test_match_statistics_apply_once(self):
        with tempfile.TemporaryDirectory() as directory:
            stats = CricketStats(Path(directory) / "stats.json")
            summary = {
                "winner": "a",
                "players": [
                    {"userid": "1", "user": "Alice", "team": "a",
                     "runs": 20, "balls": 8, "wickets": 1, "runs_conceded": 10},
                    {"userid": "2", "user": "Bob", "team": "b",
                     "runs": 10, "balls": 9, "wickets": 0, "runs_conceded": 20},
                ],
            }
            self.assertTrue(stats.apply_match(summary, "match:m1"))
            self.assertFalse(stats.apply_match(summary, "match:m1"))
            alice = stats.player("1")
            self.assertEqual((1, 1, 20, 1),
                             (alice["matches"], alice["wins"], alice["runs"], alice["wickets"]))
            self.assertEqual(250.0, alice["strike_rate"])
            self.assertEqual("Alice", stats.leaderboard("runs", 10, 0)[0]["user"])


if __name__ == "__main__":
    unittest.main()
