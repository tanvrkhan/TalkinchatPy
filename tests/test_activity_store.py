import tempfile
import threading
import unittest
from pathlib import Path

from services.activity_store import ActivityStore


class ActivityStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tempdir.name) / "activity.sqlite3")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_replayed_message_event_is_stored_once(self):
        store = ActivityStore(self.db, now=lambda: 1_000)
        event = dict(event_key="message:44", room_id="7", room_name="Old",
                     user_id="9", username="Alice", text="hello", occurred_at=900)
        store.record_message(**event)
        store.record_message(**event)
        report = store.room_report("7", since=0, limit=20)
        self.assertEqual(report.message_count, 1)
        self.assertEqual(len(report.entries), 1)

    def test_room_rename_keeps_one_room_identity(self):
        store = ActivityStore(self.db)
        store.record_room("7", "Old")
        store.record_room("7", "New")
        self.assertEqual(store.room_name("7"), "New")

    def test_cleanup_applies_three_and_thirty_day_boundaries(self):
        day = 86400
        store = ActivityStore(self.db, now=lambda: 40 * day)
        store.record_message("old-message", "7", "Room", "9", "Alice", "old", 36 * day)
        store.record_message("new-message", "7", "Room", "9", "Alice", "new", 38 * day)
        store.record_presence("old-presence", "7", "Room", "9", "Alice", "join", 9 * day)
        store.record_presence("new-presence", "7", "Room", "9", "Alice", "leave", 11 * day)
        store.cleanup(batch_size=50)
        self.assertEqual([row.text for row in store.creator_search("")], ["new"])
        report = store.room_report("7", since=0, limit=20)
        self.assertEqual([row.kind for row in report.entries], ["leave", "message"])

    def test_two_store_instances_can_write_concurrently(self):
        stores = [ActivityStore(self.db), ActivityStore(self.db)]

        def writer(index):
            for value in range(20):
                stores[index].record_message(
                    f"{index}:{value}", "7", "Room", str(index),
                    f"User{index}", str(value), 100 + value,
                )

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(stores[0].room_report("7", since=0, limit=100).message_count, 40)

    def test_last_activity_is_room_scoped_and_uses_latest_event(self):
        store = ActivityStore(self.db)
        store.record_presence("p1", "7", "Room", "9", "Alice", "join", 100)
        store.record_message("m1", "7", "Room", "9", "Alice", "hi", 120)
        store.record_message("m2", "8", "Other", "9", "Alice", "elsewhere", 140)
        activity = store.last_active("7", "9")
        self.assertEqual((activity.kind, activity.occurred_at), ("message", 120))


if __name__ == "__main__":
    unittest.main()
