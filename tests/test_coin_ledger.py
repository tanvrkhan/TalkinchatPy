import tempfile
import threading
import unittest
from pathlib import Path

from services.coin_ledger import CoinLedger, InsufficientCoins


class CoinLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "coins.json"
        self.ledger = CoinLedger(self.path)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_credit_is_idempotent_and_balance_never_negative(self):
        self.assertTrue(self.ledger.credit("1", 5000, "welcome")["applied"])
        self.assertFalse(self.ledger.credit("1", 5000, "welcome")["applied"])
        self.assertEqual(5000, self.ledger.balance("1"))
        with self.assertRaises(InsufficientCoins):
            self.ledger.reserve("1", 6000, "stake")
        self.assertEqual(5000, self.ledger.balance("1"))

    def test_reserve_and_release_preserve_funds(self):
        self.ledger.credit("1", 5000, "seed")
        reserve = self.ledger.reserve("1", 2000, "stake")
        self.assertEqual(3000, self.ledger.balance("1"))
        released = self.ledger.release(reserve["reservation_id"], "cancel")
        self.assertTrue(released["applied"])
        self.assertEqual(5000, self.ledger.balance("1"))
        self.assertFalse(self.ledger.release(reserve["reservation_id"], "cancel")["applied"])

    def test_settle_consumes_reservations_and_pays_exactly_once(self):
        for uid in ("1", "2"):
            self.ledger.credit(uid, 2000, f"seed:{uid}")
        reservations = [
            self.ledger.reserve(uid, 1000, f"stake:{uid}")["reservation_id"]
            for uid in ("1", "2")
        ]
        result = self.ledger.settle(reservations, {"1": 1900}, 100, "match:m1")
        self.assertTrue(result["applied"])
        self.assertEqual((2900, 1000), (self.ledger.balance("1"), self.ledger.balance("2")))
        self.assertFalse(self.ledger.settle(reservations, {"1": 1900}, 100,
                                            "match:m1")["applied"])

    def test_two_instances_credit_concurrently_without_lost_updates(self):
        ledgers = [CoinLedger(self.path), CoinLedger(self.path)]
        threads = [threading.Thread(target=ledger.credit,
                                    args=("1", 1000, f"credit:{index}"))
                   for index, ledger in enumerate(ledgers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(2000, self.ledger.balance("1"))


if __name__ == "__main__":
    unittest.main()
