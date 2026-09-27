import json
import os
import tempfile
import unittest
from pathlib import Path

from services.relay import RelayStore


class RelayStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = RelayStore(self.root, now=lambda: 1000.0)

    def test_request_is_private_and_claimed_once_by_exact_target(self):
        request_id = self.store.submit(
            "creator_command", "wardrobe", "sherry", 62590,
            {"command": "join Angels"},
        )
        request_file = self.root / "requests" / f"{request_id}.json"

        self.assertEqual(0o600, os.stat(request_file).st_mode & 0o777)
        self.assertEqual([], self.store.claim_requests("aibot"))
        claimed = self.store.claim_requests("WARDROBE")
        self.assertEqual(request_id, claimed[0]["id"])
        self.assertEqual("join Angels", claimed[0]["payload"]["command"])
        self.assertEqual([], self.store.claim_requests("wardrobe"))

    def test_expired_malformed_and_unknown_operations_never_claim(self):
        self.store.submit(
            "creator_command", "wardrobe", "sherry", 62590,
            {"command": "help"}, ttl=-1,
        )
        requests = self.root / "requests"
        (requests / "bad.json").write_text("not-json", encoding="utf-8")
        (requests / "unknown.json").write_text(json.dumps({
            "version": 1, "id": "unknown", "operation": "shell",
            "target": "wardrobe", "sender": "sherry", "sender_id": 62590,
            "created_at": 999, "expires_at": 1100, "payload": {},
        }), encoding="utf-8")

        self.assertEqual([], self.store.claim_requests("wardrobe"))
        self.assertEqual([], list(requests.glob("*.json")))

    def test_results_round_trip_only_to_target(self):
        self.store.submit_result(
            "abc123", "aibot", "sherry", 62590,
            ["first", "second"], source="wardrobe",
        )

        self.assertEqual([], self.store.claim_results("wardrobe"))
        results = self.store.claim_results("AIBOT")
        self.assertEqual(["first", "second"], results[0]["messages"])
        self.assertEqual("wardrobe", results[0]["source"])
        self.assertEqual([], self.store.claim_results("aibot"))

    def test_submit_rejects_invalid_operation_and_payload(self):
        with self.assertRaises(ValueError):
            self.store.submit("shell", "wardrobe", "sherry", 1, {})
        with self.assertRaises(ValueError):
            self.store.submit("creator_command", "wardrobe", "sherry", 1, "help")


if __name__ == "__main__":
    unittest.main()
