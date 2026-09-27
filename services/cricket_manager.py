"""Durable orchestration for cross-room cricket."""

import asyncio
import copy
import random
import time
import uuid

from services import cricket
from services.cricket_store import StoreConflict, StoreError


class CricketManagerError(ValueError):
    pass


class CricketManager:
    STAKES = {0, 1000, 5000, 10000}

    def __init__(self, store, ledger, stats=None, *, now=time.time, rng=None,
                 sleep=asyncio.sleep, schedule_tasks=True,
                 on_rooms=None, on_private=None):
        self.store = store
        self.ledger = ledger
        self.stats = stats
        self._now = now
        self._rng = rng or random.Random()
        self._sleep = sleep
        self._schedule_tasks = schedule_tasks
        self.on_rooms = on_rooms
        self.on_private = on_private
        self._tasks = {}

    @staticmethod
    def _player(user, userid, *, ai=False, key=None, reservation_id=None):
        return {
            "user": str(user), "userid": str(userid or ""),
            "key": key or (f"uid:{userid}" if not ai else f"ai:{uuid.uuid4().hex}"),
            "ai": bool(ai), "misses": 0, "reservation_id": reservation_id,
        }

    def _reserve_stake(self, room, user, userid, stake):
        if not stake:
            return None
        try:
            result = self.ledger.reserve(
                userid, stake, f"cricket:lobby:{room}:stake:{userid}"
            )
        except ValueError as exc:
            raise CricketManagerError(str(exc)) from exc
        return result["reservation_id"]

    async def open_or_join(self, room_id, room_name, user, userid,
                           team_size=3, overs=3, stake=0):
        try:
            team_size, overs, stake = int(team_size), int(overs), int(stake)
        except (TypeError, ValueError) as exc:
            raise CricketManagerError("Cricket format values must be numbers.") from exc
        if team_size not in {1, 2, 3} or not 1 <= overs <= 5 or stake not in self.STAKES:
            raise CricketManagerError("Use 1-3 players, 1-5 overs, and stake 0/1000/5000/10000.")
        room = str(room_id)
        current = self.store.lobby(room)
        key = f"uid:{userid}"
        if current is not None and any(
                item["key"] == key for item in current["players"]):
            return current
        if current is not None and len(current["players"]) >= current["team_size"]:
            raise CricketManagerError("That cricket team is already full.")
        effective_stake = current["stake"] if current is not None else stake
        reservation_id = self._reserve_stake(room, user, userid, effective_stake)
        participant = self._player(user, userid, reservation_id=reservation_id)
        if current is None:
            lobby = {
                "room_id": room, "room_name": str(room_name or room),
                "creator_key": participant["key"], "team_size": team_size,
                "overs": overs, "stake": stake, "status": "lobby",
                "players": [participant], "created_at": float(self._now()),
                "reservations": [],
            }
            try:
                return self.store.save_lobby(lobby)
            except StoreError as exc:
                if reservation_id:
                    self.ledger.release(
                        reservation_id, f"cricket:lobby:{room}:rollback:{userid}"
                    )
                raise CricketManagerError(str(exc)) from exc
        if (current["team_size"], current["overs"], current["stake"]) != (
                team_size, overs, stake):
            # Plain join commands use defaults; an existing lobby owns its format.
            team_size, overs, stake = current["team_size"], current["overs"], current["stake"]
        try:
            return self.store.update_lobby(
                room, lambda lobby: {**lobby, "players": [*lobby["players"], participant]}
            )
        except StoreError as exc:
            if reservation_id:
                self.ledger.release(
                    reservation_id, f"cricket:lobby:{room}:rollback:{userid}"
                )
            raise CricketManagerError(str(exc)) from exc

    async def add_ai(self, room_id, user, userid):
        room = str(room_id)
        lobby = self.store.lobby(room)
        if lobby is None:
            raise CricketManagerError("Open a cricket lobby first.")
        if lobby["creator_key"] != f"uid:{userid}":
            raise CricketManagerError("Only the lobby creator can add AI players.")
        if len(lobby["players"]) >= lobby["team_size"]:
            raise CricketManagerError("That cricket team is already full.")
        number = 1 + sum(player.get("ai", False) for player in lobby["players"])
        ai = self._player(f"AI {number}", "", ai=True)
        return self.store.update_lobby(
            room, lambda current: {**current, "players": [*current["players"], ai]}
        )

    async def leave(self, room_id, user, userid):
        room = str(room_id)
        key = f"uid:{userid}"
        lobby = self.store.lobby(room)
        if lobby is None:
            raise CricketManagerError("No cricket lobby exists in this room.")
        if lobby["creator_key"] == key:
            for player in lobby["players"]:
                if player.get("reservation_id"):
                    self.ledger.release(
                        player["reservation_id"],
                        f"cricket:lobby:{room}:cancel:{player['key']}",
                    )
            self.store.delete_lobby(room)
            return None
        departing = next((player for player in lobby["players"] if player["key"] == key), None)
        if departing and departing.get("reservation_id"):
            self.ledger.release(
                departing["reservation_id"], f"cricket:lobby:{room}:leave:{key}"
            )
        return self.store.update_lobby(
            room, lambda current: {
                **current,
                "players": [player for player in current["players"] if player["key"] != key],
            },
        )

    async def start(self, room_id, solo=False):
        room = str(room_id)
        try:
            self.store.queue_team(room)
        except StoreError as exc:
            raise CricketManagerError(str(exc)) from exc
        pair = self.store.pair_oldest()
        if pair is None and solo:
            lobby = self.store.lobby(room)
            if lobby is None:
                raise CricketManagerError("The cricket lobby is no longer available.")
            synthetic_room = f"ai:{room}:{uuid.uuid4().hex[:8]}"
            opponent = {
                "room_id": synthetic_room, "room_name": "AI XI",
                "creator_key": "ai:captain", "team_size": lobby["team_size"],
                "overs": lobby["overs"], "stake": lobby["stake"],
                "status": "lobby", "created_at": float(self._now()),
                "players": [self._player(f"AI Opponent {index + 1}", "", ai=True)
                            for index in range(lobby["team_size"])],
                "reservations": [], "synthetic": True,
            }
            self.store.save_lobby(opponent)
            self.store.queue_team(synthetic_room)
            pair = self.store.pair_oldest()
        if pair is None:
            return {"kind": "queued", "lobby": self.store.lobby(room)}
        match = self._activate_pair(pair)
        return {"kind": "paired", "match": match}

    def _activate_pair(self, pair):
        team_a = self._team_from_lobby(pair["team_a"])
        team_b = self._team_from_lobby(pair["team_b"])
        match = cricket.new_match(
            pair["match_id"], team_a, team_b, pair["team_a"]["overs"],
            seed=int(pair["match_id"][:12], 16),
        )
        synthetic_a = bool(pair["team_a"].get("synthetic"))
        synthetic_b = bool(pair["team_b"].get("synthetic"))
        if synthetic_a != synthetic_b:
            match["toss"]["winner"] = "b" if synthetic_a else "a"
        match.update({
            "room_ids": pair["room_ids"], "stake": pair["team_a"]["stake"],
            "bets": [], "betting_open": True, "created_at": float(self._now()),
            "deadline": float(self._now()) + 30,
            "room_presence": {
                str(room_id): {"present": True, "deadline": None}
                for room_id in pair["room_ids"]
            },
        })
        self.store.save_match(match["match_id"], match)
        self._arm_deadline(match)
        return match

    @staticmethod
    def _team_from_lobby(lobby):
        return {
            "room_id": lobby["room_id"], "room_name": lobby["room_name"],
            "players": copy.deepcopy(lobby["players"]),
        }

    def match_for_room(self, room_id):
        return self.store.match_for_room(room_id)

    async def toss_choice(self, match_id, player_key, decision):
        current = self.store.load_match(match_id)
        if current is None:
            raise CricketManagerError("Cricket match no longer exists.")
        winner = current["toss"]["winner"]
        captain = current["teams"][winner]["players"][0]
        if captain["key"] != player_key and not captain.get("ai"):
            raise CricketManagerError("Only the toss-winning captain may choose.")
        try:
            transition = cricket.choose_toss(current, winner, decision)
            transition.snapshot["deadline"] = float(self._now()) + 30
            saved = self.store.mutate_match(
                match_id, current["revision"], lambda _state: transition.snapshot
            )
        except (cricket.CricketError, StoreError) as exc:
            raise CricketManagerError(str(exc)) from exc
        self._arm_deadline(saved)
        return {"kind": "toss", "match": saved, "events": transition.events}

    async def delivery_choice(self, match_id, player_key, side, number, revision):
        current = self.store.load_match(match_id)
        if current is None:
            raise CricketManagerError("Cricket match no longer exists.")
        try:
            candidate = copy.deepcopy(current)
            innings = candidate.get("innings") or {}
            team_key = innings.get("batting") if side == "bat" else innings.get("bowling")
            for player in candidate.get("teams", {}).get(team_key, {}).get("players", []):
                if player.get("key") == player_key and not player.get("ai"):
                    player["misses"] = 0
                    break
            transition = cricket.submit_choice(
                candidate, side, player_key, int(number), int(revision)
            )
            transition.snapshot["deadline"] = float(self._now()) + 30
            if any(event["kind"] in {"runs", "wicket"} for event in transition.events):
                transition.snapshot["betting_open"] = False
            saved = self.store.mutate_match(
                match_id, current["revision"], lambda _state: transition.snapshot
            )
        except (ValueError, cricket.CricketError, StoreError) as exc:
            raise CricketManagerError(str(exc)) from exc
        if saved.get("phase") == "finished":
            saved = self._settle_finished(saved)
        else:
            self._arm_deadline(saved)
        return {"kind": "delivery", "match": saved, "events": transition.events}

    async def place_bet(self, match_id, user, userid, team, amount):
        current = self.store.load_match(match_id)
        if current is None or not current.get("betting_open"):
            raise CricketManagerError("Cricket betting is closed for this match.")
        if team not in {"a", "b"}:
            raise CricketManagerError("Choose team A or B.")
        reservation = None
        try:
            amount = int(amount)
            reservation = self.ledger.reserve(
                userid, amount, f"cricket:bet:{match_id}:{userid}"
            )
            candidate = copy.deepcopy(current)
            candidate["bets"].append({
                "user": str(user), "userid": str(userid), "team": team,
                "amount": amount, "reservation_id": reservation["reservation_id"],
            })
            candidate["revision"] += 1
            saved = self.store.mutate_match(
                match_id, current["revision"], lambda _state: candidate
            )
        except (ValueError, StoreError) as exc:
            if reservation and reservation.get("reservation_id"):
                self.ledger.release(
                    reservation["reservation_id"],
                    f"cricket:bet:{match_id}:{userid}:rollback",
                )
            raise CricketManagerError(str(exc)) from exc
        return {"kind": "bet", "match": saved, "bet": candidate["bets"][-1]}

    @staticmethod
    def _split_pool(pool, recipients):
        recipients = sorted(set(str(value) for value in recipients if value))
        if not recipients:
            return {}, pool
        fee = pool * 5 // 100
        distributable = pool - fee
        base, remainder = divmod(distributable, len(recipients))
        payouts = {uid: base + (1 if index < remainder else 0)
                   for index, uid in enumerate(recipients)}
        return payouts, fee

    def _settle_finished(self, match):
        if match.get("settlement_complete"):
            return match
        winner = match.get("winner")
        reservations = [player.get("reservation_id")
                        for team in match["teams"].values()
                        for player in team["players"] if player.get("reservation_id")]
        pool = int(match.get("stake", 0)) * len(reservations)
        winners = [player.get("userid") for player in match["teams"][winner]["players"]
                   if not player.get("ai") and player.get("userid")] if winner else []
        if reservations:
            payouts, fee = self._split_pool(pool, winners)
            self.ledger.settle(
                reservations, payouts, fee, f"cricket:match:{match['match_id']}:stakes"
            )
        bets = match.get("bets", [])
        if bets:
            winning_bets = [bet for bet in bets if bet["team"] == winner]
            if not winning_bets:
                for bet in bets:
                    self.ledger.release(
                        bet["reservation_id"],
                        f"cricket:match:{match['match_id']}:bet-refund:{bet['userid']}",
                    )
            else:
                bet_pool = sum(bet["amount"] for bet in bets)
                fee = bet_pool * 5 // 100
                distributable = bet_pool - fee
                winning_total = sum(bet["amount"] for bet in winning_bets)
                payouts = {}
                assigned = 0
                for bet in sorted(winning_bets, key=lambda item: item["userid"]):
                    share = distributable * bet["amount"] // winning_total
                    payouts[bet["userid"]] = payouts.get(bet["userid"], 0) + share
                    assigned += share
                if payouts:
                    payouts[sorted(payouts)[0]] += distributable - assigned
                self.ledger.settle(
                    [bet["reservation_id"] for bet in bets], payouts, fee,
                    f"cricket:match:{match['match_id']}:bets",
                )
        if self.stats is not None:
            self.stats.apply_match(
                self._stats_summary(match), f"cricket:match:{match['match_id']}:stats"
            )
        current = self.store.load_match(match["match_id"])
        candidate = copy.deepcopy(current)
        candidate["settlement_complete"] = True
        candidate["revision"] += 1
        settled = self.store.mutate_match(
            match["match_id"], current["revision"], lambda _state: candidate
        )
        self.store.archive_match(match["match_id"], settled)
        return settled

    @staticmethod
    def _stats_summary(match):
        records = {}
        for team_key, team in match["teams"].items():
            for player in team["players"]:
                if player.get("ai") or not player.get("userid"):
                    continue
                records[player["key"]] = {
                    "userid": player["userid"], "user": player["user"],
                    "team": team_key, "runs": 0, "balls": 0, "wickets": 0,
                    "runs_conceded": 0,
                }
        for event in match.get("history", []):
            batter = records.get(event.get("player"))
            bowler = records.get(event.get("bowler_player"))
            if batter:
                batter["balls"] += 1
                batter["runs"] += int(event.get("runs", 0))
            if bowler:
                bowler["wickets"] += int(event.get("kind") == "wicket")
                bowler["runs_conceded"] += int(event.get("runs", 0))
        return {"winner": match.get("winner"), "players": list(records.values())}

    async def proxy_choice(self, match_id, teammate_key, side, number, revision):
        current = self.store.load_match(match_id)
        if current is None or current.get("phase") not in {"active", "super_over"}:
            raise CricketManagerError("No cricket delivery is waiting.")
        innings = current["innings"]
        expected = innings["striker"] if side == "bat" else innings["bowler"]
        team_key = innings["batting"] if side == "bat" else innings["bowling"]
        team = current["teams"][team_key]["players"]
        target = next((item for item in team if item["key"] == expected), None)
        teammate = next((item for item in team if item["key"] == teammate_key), None)
        if not target or not target.get("ai") or not teammate or teammate.get("ai"):
            raise CricketManagerError("Proxy choices are only for your team's AI player.")
        return await self.delivery_choice(match_id, expected, side, number, revision)

    async def auto_choose_ai(self, match_id):
        current = self.store.load_match(match_id)
        if current is None or current.get("phase") not in {"active", "super_over"}:
            return None
        innings = current["innings"]
        delivery = (
            current.get("innings_number"), innings.get("balls"),
            innings.get("striker"), innings.get("bowler"),
        )
        result = None
        for side in ("bat", "bowl"):
            if side in current.get("pending_choices", {}):
                continue
            innings = current["innings"]
            player_key = innings["striker"] if side == "bat" else innings["bowler"]
            team_key = innings["batting"] if side == "bat" else innings["bowling"]
            player = next(item for item in current["teams"][team_key]["players"]
                          if item["key"] == player_key)
            if not player.get("ai"):
                continue
            result = await self.delivery_choice(
                match_id, player_key, side, self._rng.randint(1, 6), current["revision"]
            )
            current = result["match"]
            updated = current.get("innings") or {}
            current_delivery = (
                current.get("innings_number"), updated.get("balls"),
                updated.get("striker"), updated.get("bowler"),
            )
            if current_delivery != delivery:
                break
        return result

    async def expire_delivery(self, match_id):
        current = self.store.load_match(match_id)
        if current is None or current.get("phase") not in {"active", "super_over"}:
            raise CricketManagerError("No cricket delivery is waiting.")
        original_revision = current["revision"]
        candidate = copy.deepcopy(current)
        events = []
        for side in ("bat", "bowl"):
            if side in candidate.get("pending_choices", {}):
                continue
            innings = candidate["innings"]
            player_key = innings["striker"] if side == "bat" else innings["bowler"]
            team_key = innings["batting"] if side == "bat" else innings["bowling"]
            player = next(item for item in candidate["teams"][team_key]["players"]
                          if item["key"] == player_key)
            if not player.get("ai"):
                player["misses"] = int(player.get("misses", 0)) + 1
                if player["misses"] >= 3:
                    player["ai"] = True
                    player["user"] = f"{player['user']} (AI)"
                    events.append({"kind": "ai_replacement", "player": player_key})
            number = self._rng.randint(1, 6)
            transition = cricket.submit_choice(
                candidate, side, player_key, number, candidate["revision"]
            )
            candidate = transition.snapshot
            events.extend(transition.events)
        candidate["deadline"] = float(self._now()) + 30
        try:
            saved = self.store.mutate_match(
                match_id, original_revision, lambda _state: candidate
            )
        except StoreError as exc:
            raise CricketManagerError(str(exc)) from exc
        if saved.get("phase") == "finished":
            saved = self._settle_finished(saved)
        else:
            self._arm_deadline(saved)
        return {"kind": "timeout", "match": saved, "events": tuple(events)}

    async def restore(self):
        recovered = self.store.recover()
        for match in recovered["matches"].values():
            if match.get("phase") in {"toss", "active", "super_over"}:
                self._arm_deadline(match)
        return recovered

    async def room_available(self, room_id, present):
        match = self.store.match_for_room(room_id)
        if match is None:
            return None
        room = str(room_id)
        candidate = copy.deepcopy(match)
        candidate.setdefault("room_presence", {})[room] = {
            "present": bool(present),
            "deadline": None if present else float(self._now()) + 60,
        }
        candidate["revision"] += 1
        return self.store.mutate_match(
            match["match_id"], match["revision"], lambda _state: candidate
        )

    async def expire_room_leases(self, now=None):
        now = float(self._now() if now is None else now)
        results = []
        for match in list(self.store.recover()["matches"].values()):
            if match.get("phase") == "finished":
                continue
            expired = [room for room, presence in match.get("room_presence", {}).items()
                       if not presence.get("present")
                       and presence.get("deadline") is not None
                       and float(presence["deadline"]) <= now]
            if not expired:
                continue
            loser_room = expired[0]
            loser = next((key for key, team in match["teams"].items()
                          if str(team["room_id"]) == loser_room), None)
            if loser is None:
                continue
            candidate = copy.deepcopy(match)
            candidate["phase"] = "finished"
            candidate["winner"] = "b" if loser == "a" else "a"
            candidate["result"] = {"winner": candidate["winner"], "forfeit": loser}
            candidate["pending_choices"] = {}
            candidate["revision"] += 1
            saved = self.store.mutate_match(
                match["match_id"], match["revision"], lambda _state: candidate
            )
            results.append(self._settle_finished(saved))
        return results

    async def cancel(self, room_id, player_key=None, is_admin=False):
        lobby = self.store.lobby(room_id)
        if lobby is not None:
            if not is_admin and player_key != lobby.get("creator_key"):
                raise CricketManagerError("Only the lobby creator or an admin can end it.")
            for player in lobby["players"]:
                if player.get("reservation_id"):
                    self.ledger.release(
                        player["reservation_id"],
                        f"cricket:lobby:{lobby['room_id']}:end:{player['key']}",
                    )
            self.store.delete_lobby(room_id)
            return {"kind": "lobby_ended", "room_ids": [str(room_id)]}
        match = self.store.match_for_room(room_id)
        if match is None:
            raise CricketManagerError("No cricket game is active here.")
        participants = {player["key"] for team in match["teams"].values()
                        for player in team["players"]}
        if not is_admin and player_key not in participants:
            raise CricketManagerError("Only a player or admin can end this match.")
        candidate = copy.deepcopy(match)
        candidate["phase"] = "finished"
        candidate["winner"] = None
        candidate["result"] = {"winner": None, "no_contest": True}
        candidate["revision"] += 1
        saved = self.store.mutate_match(
            match["match_id"], match["revision"], lambda _state: candidate
        )
        for team in saved["teams"].values():
            for player in team["players"]:
                if player.get("reservation_id"):
                    self.ledger.release(
                        player["reservation_id"],
                        f"cricket:match:{match['match_id']}:cancel:{player['key']}",
                    )
        for bet in saved.get("bets", []):
            self.ledger.release(
                bet["reservation_id"],
                f"cricket:match:{match['match_id']}:cancel-bet:{bet['userid']}",
            )
        self.store.archive_match(match["match_id"], saved)
        return {"kind": "match_ended", "room_ids": saved["room_ids"], "match": saved}

    def _arm_deadline(self, match):
        if not self._schedule_tasks or match.get("phase") not in {"toss", "active", "super_over"}:
            return
        match_id = match["match_id"]
        old = self._tasks.pop(match_id, None)
        if old is not None and old is not asyncio.current_task():
            old.cancel()
        self._tasks[match_id] = asyncio.create_task(
            self._deadline_loop(match_id, float(match.get("deadline", self._now() + 30)))
        )

    async def _deadline_loop(self, match_id, deadline):
        try:
            for remaining in (15, 5, 0):
                delay = max(0.0, deadline - remaining - float(self._now()))
                if delay:
                    await self._sleep(delay)
                current = self.store.load_match(match_id)
                if current is None or float(current.get("deadline", -1)) != deadline:
                    return
                if remaining and self.on_rooms is not None:
                    result = self.on_rooms(
                        current.get("room_ids", []),
                        {"kind": "deadline_warning", "remaining": remaining},
                        [cricket.public_view(current, room)
                         for room in current.get("room_ids", [])],
                    )
                    if asyncio.iscoroutine(result):
                        await result
            current = self.store.load_match(match_id)
            if current is None:
                return
            if current["phase"] == "toss":
                winner = current["toss"]["winner"]
                captain = current["teams"][winner]["players"][0]
                result = await self.toss_choice(
                    match_id, captain["key"], self._rng.choice(("bat", "bowl"))
                )
            else:
                result = await self.expire_delivery(match_id)
            if self.on_rooms is not None:
                latest = result["match"]
                callback = self.on_rooms(
                    latest.get("room_ids", []), result,
                    [cricket.public_view(latest, room)
                     for room in latest.get("room_ids", [])],
                )
                if asyncio.iscoroutine(callback):
                    await callback
        except asyncio.CancelledError:
            raise
        finally:
            if self._tasks.get(match_id) is asyncio.current_task():
                self._tasks.pop(match_id, None)

    async def close(self):
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
