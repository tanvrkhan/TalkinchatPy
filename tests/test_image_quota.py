import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.image_quota import ImageQuotaStore


class ImageQuotaStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tempdir.name) / "quota.sqlite3")
        self.now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
        self.store = ImageQuotaStore(self.path, daily_limit=4,
                                     user_daily_limit=3, cooldown_seconds=300)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_reservation_persists_and_reports_personal_remainder(self):
        decision = self.store.reserve("7", "1253", self.now)

        self.assertTrue(decision.allowed)
        self.assertEqual(2, decision.remaining)
        self.assertIsNotNone(decision.reservation_id)

        reopened = ImageQuotaStore(self.path, 4, 3, 300)
        self.assertEqual(1, reopened.submitted_count("7", self.now.date()))

    def test_check_does_not_consume_quota_and_reports_cooldown(self):
        self.store.reserve("7", "1253", self.now)

        decision = self.store.check("7", self.now + timedelta(seconds=10))

        self.assertFalse(decision.allowed)
        self.assertEqual("cooldown", decision.reason)
        self.assertEqual(290, decision.retry_after)
        self.assertEqual(2, decision.remaining)
        self.assertEqual(1, self.store.submitted_count("7", self.now.date()))

    def test_personal_and_global_limits_are_enforced(self):
        for minute in (0, 5, 10):
            self.assertTrue(self.store.reserve(
                "7", "1253", self.now + timedelta(minutes=minute)).allowed)

        personal = self.store.reserve("7", "1253", self.now + timedelta(minutes=15))
        self.assertFalse(personal.allowed)
        self.assertEqual("user_limit", personal.reason)
        self.assertEqual(0, personal.remaining)

        self.assertTrue(self.store.reserve(
            "8", "1253", self.now + timedelta(minutes=15)).allowed)
        global_limit = self.store.reserve(
            "9", "1253", self.now + timedelta(minutes=15))
        self.assertFalse(global_limit.allowed)
        self.assertEqual("global_limit", global_limit.reason)
        self.assertIsNone(global_limit.remaining)

    def test_utc_day_rollover_resets_limits(self):
        self.store.reserve("7", "1253", self.now)

        tomorrow = self.now + timedelta(days=1)
        decision = self.store.reserve("7", "1253", tomorrow)

        self.assertTrue(decision.allowed)
        self.assertEqual(2, decision.remaining)

    def test_cloudflare_quota_closes_only_the_current_utc_day(self):
        self.store.close_day(self.now)

        closed = self.store.check("7", self.now)
        tomorrow = self.store.check("7", self.now + timedelta(days=1))

        self.assertFalse(closed.allowed)
        self.assertEqual("global_limit", closed.reason)
        self.assertIsNone(closed.remaining)
        self.assertTrue(tomorrow.allowed)

    def test_competing_reservations_cannot_overspend_last_slot(self):
        store = ImageQuotaStore(self.path, daily_limit=1,
                                user_daily_limit=3, cooldown_seconds=0)
        barrier = threading.Barrier(2)
        results = []

        def reserve(user):
            barrier.wait()
            results.append(store.reserve(user, "1253", self.now))

        threads = [threading.Thread(target=reserve, args=(str(user),))
                   for user in (7, 8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, sum(result.allowed for result in results))
        self.assertEqual(1, store.submitted_count(None, self.now.date()))

    def test_unlimited_creator_bypasses_personal_cooldown_and_local_global_limit(self):
        store = ImageQuotaStore(self.path, daily_limit=1,
                                user_daily_limit=1, cooldown_seconds=300)

        first = store.reserve("creator", "1253", self.now, unlimited=True)
        second = store.reserve("creator", "1253", self.now, unlimited=True)

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertIsNone(first.remaining)
        self.assertIsNone(second.remaining)
        self.assertEqual(2, store.submitted_count("creator", self.now.date()))

    def test_cloudflare_closed_day_still_stops_unlimited_creator(self):
        self.store.close_day(self.now)

        decision = self.store.check("creator", self.now, unlimited=True)

        self.assertFalse(decision.allowed)
        self.assertEqual("global_limit", decision.reason)


if __name__ == "__main__":
    unittest.main()
