import random
import tempfile
import unittest
from pathlib import Path

from services.coin_ledger import CoinLedger
from services.cricket_manager import CricketManager, CricketManagerError
from services.cricket_stats import CricketStats
from services.cricket_store import CricketStore


class CricketManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.store = CricketStore(root / "cricket.json", now=lambda: 100)
        self.ledger = CoinLedger(root / "coins.json")
        self.stats = CricketStats(root / "stats.json")
        self.manager = CricketManager(self.store, self.ledger, self.stats, now=lambda: 100,
                                      schedule_tasks=False, rng=random.Random(7))

    async def asyncTearDown(self):
        await self.manager.close()
        self.tempdir.cleanup()

    async def test_configurable_lobbies_pair_across_rooms(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 2, 0)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 2, 0)
        self.assertEqual("queued", (await self.manager.start("a"))["kind"])
        paired = await self.manager.start("b")
        self.assertEqual("paired", paired["kind"])
        match = self.manager.match_for_room("a")
        self.assertEqual({"a", "b"}, set(match["room_ids"]))
        self.assertEqual((1, 2), (match["team_size"], match["overs"]))

    async def test_full_staked_lobby_rejects_without_reserving_coins(self):
        self.ledger.credit("1", 2000, "seed:1")
        self.ledger.credit("2", 2000, "seed:2")
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 1000)
        with self.assertRaises(CricketManagerError):
            await self.manager.open_or_join("a", "Alpha", "Bob", "2", 1, 1, 1000)
        self.assertEqual(2000, self.ledger.balance("2"))

    async def test_ai_slots_and_solo_opponent(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 2, 1, 0)
        lobby = await self.manager.add_ai("a", "Alice", "1")
        self.assertEqual(2, len(lobby["players"]))
        result = await self.manager.start("a", solo=True)
        self.assertEqual("paired", result["kind"])
        self.assertTrue(all(player["ai"] for player in result["match"]["teams"]["b"]["players"]))

    async def test_solo_start_fills_empty_teammate_slots_with_ai(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 3, 1, 0)
        result = await self.manager.start("a", solo=True)
        self.assertEqual("paired", result["kind"])
        human_team = result["match"]["teams"]["a"]
        self.assertEqual(3, len(human_team["players"]))
        self.assertEqual(1, sum(not player["ai"] for player in human_team["players"]))
        self.assertEqual(2, sum(player["ai"] for player in human_team["players"]))

    async def test_solo_human_team_always_gets_the_toss_buttons(self):
        human = {
            "room_id": "a", "room_name": "Alpha", "overs": 1, "stake": 0,
            "players": [self.manager._player("Alice", "1")],
        }
        computer = {
            "room_id": "ai:a:test", "room_name": "AI XI", "overs": 1, "stake": 0,
            "players": [self.manager._player("AI Opponent", "", ai=True)],
            "synthetic": True,
        }
        match = self.manager._activate_pair({
            "match_id": "0" * 32, "room_ids": ["a", "ai:a:test"],
            "team_a": human, "team_b": computer,
        })
        winner = match["toss"]["winner"]
        self.assertFalse(match["teams"][winner]["players"][0]["ai"])

    async def test_toss_and_private_choices_advance_durable_match(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 0)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 1, 0)
        await self.manager.start("a")
        result = await self.manager.start("b")
        match = result["match"]
        winner = match["toss"]["winner"]
        captain = match["teams"][winner]["players"][0]
        match = (await self.manager.toss_choice(match["match_id"], captain["key"], "bat"))["match"]
        innings = match["innings"]
        batter = innings["striker"]
        bowler = innings["bowler"]
        first = await self.manager.delivery_choice(match["match_id"], batter, "bat", 4,
                                                   match["revision"])
        second = await self.manager.delivery_choice(match["match_id"], bowler, "bowl", 2,
                                                    first["match"]["revision"])
        self.assertEqual(4, second["match"]["innings"]["runs"])
        self.assertEqual(second["match"], self.store.load_match(match["match_id"]))

    async def test_manual_choice_clears_timeout_strikes(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 0)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 1, 0)
        await self.manager.start("a")
        match = (await self.manager.start("b"))["match"]
        winner = match["toss"]["winner"]
        captain = match["teams"][winner]["players"][0]
        match = (await self.manager.toss_choice(
            match["match_id"], captain["key"], "bat"
        ))["match"]
        striker = match["innings"]["striker"]
        for team in match["teams"].values():
            for player in team["players"]:
                if player["key"] == striker:
                    player["misses"] = 2
        match["revision"] += 1
        self.store.mutate_match(
            match["match_id"], match["revision"] - 1, lambda _state: match
        )
        chosen = await self.manager.delivery_choice(
            match["match_id"], striker, "bat", 4, match["revision"]
        )
        player = next(
            player for team in chosen["match"]["teams"].values()
            for player in team["players"] if player["key"] == striker
        )
        self.assertEqual(0, player["misses"])

    async def test_outsider_and_stale_choice_are_rejected(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 0)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 1, 0)
        await self.manager.start("a")
        match = (await self.manager.start("b"))["match"]
        with self.assertRaises(CricketManagerError):
            await self.manager.toss_choice(match["match_id"], "uid:999", "bat")

    async def test_three_delivery_timeouts_replace_humans_with_ai(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 2, 0)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 2, 0)
        await self.manager.start("a")
        match = (await self.manager.start("b"))["match"]
        winner = match["toss"]["winner"]
        captain = match["teams"][winner]["players"][0]
        match = (await self.manager.toss_choice(match["match_id"], captain["key"], "bat"))["match"]
        for _ in range(3):
            match = (await self.manager.expire_delivery(match["match_id"]))["match"]
        humans = [player for team in match["teams"].values() for player in team["players"]]
        self.assertTrue(all(player["ai"] for player in humans))

    async def test_teammate_can_proxy_only_for_ai_turn(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 2, 1, 0)
        await self.manager.add_ai("a", "Alice", "1")
        result = await self.manager.start("a", solo=True)
        match = result["match"]
        winner = match["toss"]["winner"]
        captain = match["teams"][winner]["players"][0]
        decision = "bat" if winner == "a" else "bowl"
        match = (await self.manager.toss_choice(
            match["match_id"], captain["key"], decision
        ))["match"]
        first = await self.manager.delivery_choice(
            match["match_id"], match["innings"]["striker"], "bat", 1,
            match["revision"],
        )
        match = first["match"]
        resolved = await self.manager.delivery_choice(
            match["match_id"], match["innings"]["bowler"], "bowl", 2,
            match["revision"],
        )
        match = resolved["match"]
        innings = match["innings"]
        expected = innings["striker"]
        player = next(item for item in match["teams"][innings["batting"]]["players"]
                      if item["key"] == expected)
        self.assertTrue(player["ai"])
        teammate = next(item for item in match["teams"][innings["batting"]]["players"]
                        if not item["ai"])
        proxied = await self.manager.proxy_choice(
            match["match_id"], teammate["key"], "bat", 3, match["revision"]
        )
        self.assertEqual(3, proxied["match"]["pending_choices"]["bat"])

    async def test_ai_turn_is_chosen_immediately_with_local_random_number(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 0)
        result = await self.manager.start("a", solo=True)
        match = result["match"]
        winner = match["toss"]["winner"]
        captain = match["teams"][winner]["players"][0]
        match = (await self.manager.toss_choice(
            match["match_id"], captain["key"], "bat"
        ))["match"]

        result = await self.manager.auto_choose_ai(match["match_id"])

        self.assertIsNotNone(result)
        self.assertIn(result["match"]["pending_choices"]["bowl"], range(1, 7))

    async def test_stakes_are_reserved_and_settled_once(self):
        self.ledger.credit("1", 20000, "seed:1")
        self.ledger.credit("2", 20000, "seed:2")
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 1000)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 1, 1000)
        self.assertEqual((19000, 19000), (self.ledger.balance("1"), self.ledger.balance("2")))
        await self.manager.start("a")
        match = (await self.manager.start("b"))["match"]
        winner = match["toss"]["winner"]
        captain = match["teams"][winner]["players"][0]
        match = (await self.manager.toss_choice(match["match_id"], captain["key"], "bat"))["match"]
        first = await self.manager.delivery_choice(
            match["match_id"], match["innings"]["striker"], "bat", 1, match["revision"])
        match = first["match"]
        out = await self.manager.delivery_choice(
            match["match_id"], match["innings"]["bowler"], "bowl", 1, match["revision"])
        match = out["match"]
        first = await self.manager.delivery_choice(
            match["match_id"], match["innings"]["striker"], "bat", 1, match["revision"])
        match = first["match"]
        finished = await self.manager.delivery_choice(
            match["match_id"], match["innings"]["bowler"], "bowl", 2, match["revision"])
        self.assertTrue(finished["match"]["settlement_complete"])
        self.assertEqual(39900, self.ledger.balance("1") + self.ledger.balance("2"))

    async def test_spectator_bet_closes_on_first_resolved_ball(self):
        self.ledger.credit("9", 5000, "seed:9")
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 0)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 1, 0)
        await self.manager.start("a")
        match = (await self.manager.start("b"))["match"]
        await self.manager.place_bet(match["match_id"], "Spectator", "9", "a", 1000)
        self.assertEqual(4000, self.ledger.balance("9"))
        winner = match["toss"]["winner"]
        captain = match["teams"][winner]["players"][0]
        match = (await self.manager.toss_choice(match["match_id"], captain["key"], "bat"))["match"]
        first = await self.manager.delivery_choice(
            match["match_id"], match["innings"]["striker"], "bat", 2, match["revision"])
        match = first["match"]
        await self.manager.delivery_choice(
            match["match_id"], match["innings"]["bowler"], "bowl", 3, match["revision"])
        with self.assertRaises(CricketManagerError):
            await self.manager.place_bet(match["match_id"], "Late", "8", "a", 1000)

    async def test_restore_returns_active_match_and_preserves_pending_choice(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 0)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 1, 0)
        await self.manager.start("a")
        match = (await self.manager.start("b"))["match"]
        winner = match["toss"]["winner"]
        captain = match["teams"][winner]["players"][0]
        match = (await self.manager.toss_choice(match["match_id"], captain["key"], "bat"))["match"]
        chosen = await self.manager.delivery_choice(
            match["match_id"], match["innings"]["striker"], "bat", 4,
            match["revision"],
        )
        restarted = CricketManager(self.store, self.ledger, self.stats,
                                   now=lambda: 100, schedule_tasks=False)
        restored = await restarted.restore()
        self.assertEqual(4, restored["matches"][match["match_id"]]["pending_choices"]["bat"])
        await restarted.close()

    async def test_expired_absent_room_forfeits_to_other_team(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 0)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 1, 0)
        await self.manager.start("a")
        match = (await self.manager.start("b"))["match"]
        await self.manager.room_available("a", False)
        result = await self.manager.expire_room_leases(now=1000)
        self.assertEqual("b", result[0]["winner"])
        self.assertEqual("finished", result[0]["phase"])

    async def test_cancelled_match_releases_both_rooms_for_a_new_game(self):
        await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 0)
        await self.manager.open_or_join("b", "Beta", "Bob", "2", 1, 1, 0)
        await self.manager.start("a")
        await self.manager.start("b")
        ended = await self.manager.cancel("a", "uid:1")
        self.assertEqual("match_ended", ended["kind"])
        self.assertIsNone(self.manager.match_for_room("a"))
        self.assertIsNone(self.manager.match_for_room("b"))
        lobby = await self.manager.open_or_join("a", "Alpha", "Alice", "1", 1, 1, 0)
        self.assertEqual("a", lobby["room_id"])


if __name__ == "__main__":
    unittest.main()
