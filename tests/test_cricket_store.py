import tempfile
import threading
import unittest
from pathlib import Path

from services.cricket_store import CricketStore, StoreConflict, StaleRevision


def lobby(room, user, uid, size=1, overs=1, stake=0):
    return {
        "room_id": str(room), "room_name": str(room), "creator_key": f"uid:{uid}",
        "team_size": size, "overs": overs, "stake": stake, "status": "lobby",
        "players": [{"user": user, "userid": str(uid), "key": f"uid:{uid}", "ai": False}],
        "created_at": 1,
    }


class CricketStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "cricket.json"
        self.store = CricketStore(self.path, now=lambda: 100)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_one_lobby_per_room_and_user_across_rooms(self):
        self.store.save_lobby(lobby("a", "Alice", 1))
        with self.assertRaises(StoreConflict):
            self.store.save_lobby(lobby("a", "Bob", 2))
        with self.assertRaises(StoreConflict):
            self.store.save_lobby(lobby("b", "Alice", 1))

    def test_oldest_compatible_different_rooms_pair_once(self):
        first = lobby("a", "Alice", 1)
        second = lobby("b", "Bob", 2)
        self.store.save_lobby(first)
        self.store.save_lobby(second)
        self.store.queue_team("a")
        self.store.queue_team("b")
        match = self.store.pair_oldest()
        self.assertEqual({"a", "b"}, set(match["room_ids"]))
        self.assertIsNone(self.store.pair_oldest())

    def test_concurrent_pairing_returns_one_match(self):
        for room, uid in (("a", 1), ("b", 2)):
            self.store.save_lobby(lobby(room, room, uid))
            self.store.queue_team(room)
        stores = [CricketStore(self.path), CricketStore(self.path)]
        results = []
        threads = [threading.Thread(target=lambda s=store: results.append(s.pair_oldest()))
                   for store in stores]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, sum(result is not None for result in results))

    def test_mutation_rejects_stale_revision(self):
        self.store.save_match("m1", {"match_id": "m1", "revision": 2})
        with self.assertRaises(StaleRevision):
            self.store.mutate_match("m1", 1, lambda state: state)
        changed = self.store.mutate_match(
            "m1", 2, lambda state: {**state, "revision": 3, "value": "ok"}
        )
        self.assertEqual("ok", changed["value"])

    def test_claim_and_archive_are_idempotent(self):
        self.store.save_match("m1", {"match_id": "m1", "revision": 1})
        self.assertTrue(self.store.claim("reward:m1"))
        self.assertFalse(self.store.claim("reward:m1"))
        self.assertTrue(self.store.archive_match("m1", {"winner": "a"}))
        self.assertFalse(self.store.archive_match("m1", {"winner": "a"}))
        self.assertIsNone(self.store.load_match("m1"))

    def test_finished_match_no_longer_owns_its_rooms(self):
        self.store.save_match("m1", {
            "match_id": "m1", "revision": 1, "phase": "finished",
            "room_ids": ["a", "b"],
            "teams": {
                "a": {"players": [{"key": "uid:1", "ai": False}]},
                "b": {"players": [{"key": "uid:2", "ai": False}]},
            },
        })
        self.assertIsNone(self.store.match_for_room("a"))
        created = self.store.save_lobby(lobby("a", "Alice", 1))
        self.assertEqual("a", created["room_id"])

    def test_active_match_can_be_resolved_for_private_player_commands(self):
        self.store.save_match("m1", {
            "match_id": "m1", "revision": 1, "phase": "toss",
            "room_ids": ["a", "b"],
            "teams": {
                "a": {"players": [{"key": "alice", "ai": False}]},
                "b": {"players": [{"key": "bob", "ai": False}]},
            },
        })
        self.assertEqual("m1", self.store.match_for_player("ALICE")["match_id"])
        self.assertIsNone(self.store.match_for_player("outsider"))


if __name__ == "__main__":
    unittest.main()
