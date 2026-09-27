import json
import multiprocessing
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.game_store import GameStore


def _claim_reward_in_process(path, key, start, results):
    start.wait()
    results.put(GameStore(path).claim_reward(key))


class GameStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "games.json"
        self.store = GameStore(self.path)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_save_round_trips_snapshots_and_normalizes_room_ids(self):
        snapshot = {
            "game": "bingo",
            "public": {"phase": "playing", "called": [7, 19]},
            "private": {"alice": {"marked": [7]}},
        }

        self.store.save(1253, snapshot)

        self.assertEqual({"1253": snapshot}, GameStore(self.path).load_all())

    def test_failed_replacement_leaves_the_last_complete_state_intact(self):
        self.store.save("7", {"round": 1})

        with patch("services.game_store.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.store.save("7", {"round": 2})

        self.assertEqual({"7": {"round": 1}}, GameStore(self.path).load_all())
        self.assertFalse(list(self.path.parent.glob(".games.json.*.tmp")))

    def test_corrupt_file_is_quarantined_and_load_fails_closed(self):
        bad_contents = "{this is not json"
        self.path.write_text(bad_contents, encoding="utf-8")

        self.assertEqual({}, self.store.load_all())
        self.assertIs(False, self.store.claim_reward("bingo:7:first-line:alice"))

        copies = list(self.path.parent.glob("games.json.corrupt.*"))
        self.assertFalse(self.path.exists())
        self.assertEqual(1, len(copies))
        self.assertEqual(bad_contents, copies[0].read_text(encoding="utf-8"))

    def test_unknown_schema_version_is_quarantined_without_interpreting_games(self):
        source = {"version": 99, "games": {"7": {"round": 3}}, "claimed_rewards": []}
        self.path.write_text(json.dumps(source), encoding="utf-8")

        self.assertEqual({}, self.store.load_all())

        copies = list(self.path.parent.glob("games.json.corrupt.*"))
        self.assertEqual(1, len(copies))
        self.assertEqual(source, json.loads(copies[0].read_text(encoding="utf-8")))

    def test_missing_schema_version_is_quarantined_without_interpreting_games(self):
        source = {"games": {"7": {"round": 3}}, "claimed_rewards": []}
        self.path.write_text(json.dumps(source), encoding="utf-8")

        self.assertEqual({}, self.store.load_all())

        copies = list(self.path.parent.glob("games.json.corrupt.*"))
        self.assertEqual(1, len(copies))
        self.assertEqual(source, json.loads(copies[0].read_text(encoding="utf-8")))

    def test_non_finite_snapshots_do_not_replace_valid_state(self):
        self.store.save("7", {"round": 1})

        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.store.save("7", {"score": value})
                self.assertEqual({"7": {"round": 1}}, self.store.load_all())

    def test_delete_removes_only_the_requested_room(self):
        self.store.save("7", {"round": 1})
        self.store.save("8", {"round": 2})

        self.store.delete(7)

        self.assertEqual({"8": {"round": 2}}, self.store.load_all())

    def test_delete_removes_a_stored_null_snapshot(self):
        self.store.save("7", None)

        self.assertIs(True, self.store.delete("7"))

        self.assertEqual({}, GameStore(self.path).load_all())

    def test_reward_claim_is_idempotent_across_reload(self):
        first = GameStore(self.path)
        self.assertIs(True, first.claim_reward("bingo:7:first-line:alice"))

        second = GameStore(self.path)
        self.assertIs(False, second.claim_reward("bingo:7:first-line:alice"))

    def test_threaded_reward_claims_allow_exactly_one_winner(self):
        start = threading.Barrier(2)
        results = []

        def claim():
            start.wait()
            results.append(GameStore(self.path).claim_reward("bingo:7:full-card:alice"))

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual([False, True], sorted(results))

    def test_process_reward_claims_allow_exactly_one_winner(self):
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [
            context.Process(
                target=_claim_reward_in_process,
                args=(str(self.path), "bingo:7:four-corners:alice", start, results),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        start.set()
        claimed = [results.get(timeout=10) for _ in processes]
        for process in processes:
            process.join(timeout=10)

        self.assertTrue(all(process.exitcode == 0 for process in processes))
        self.assertEqual([False, True], sorted(claimed))


if __name__ == "__main__":
    unittest.main()
