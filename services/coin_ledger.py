"""Atomic coin balances and reservations for games and the market."""

import copy
import fcntl
import json
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path


class CoinError(ValueError):
    pass


class InsufficientCoins(CoinError):
    pass


class CoinLedger:
    _guard = threading.Lock()
    _locks = {}

    def __init__(self, path, opening_balance=0):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.opening_balance = self._amount(opening_balance, allow_zero=True)
        with self._guard:
            self._thread_lock = self._locks.setdefault(str(self.path), threading.RLock())
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    @staticmethod
    def _amount(value, allow_zero=False):
        if type(value) is not int or value < (0 if allow_zero else 1):
            raise CoinError("Coin amounts must be positive integers.")
        return value

    @staticmethod
    def _empty():
        return {"version": 1, "balances": {}, "reservations": {},
                "operations": {}, "fees": 0}

    @contextmanager
    def _locked(self):
        with self._thread_lock:
            with open(self._lock_path, "a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def balance(self, user_id):
        with self._locked():
            state = self._read()
            return int(state["balances"].get(str(user_id), self.opening_balance))

    def credit(self, user_id, amount, key):
        amount = self._amount(amount)
        return self._mutate_once(key, lambda state: self._credit(state, user_id, amount))

    def reserve(self, user_id, amount, key):
        amount = self._amount(amount)

        def operation(state):
            uid = str(user_id)
            balance = int(state["balances"].get(uid, self.opening_balance))
            if balance < amount:
                raise InsufficientCoins("Not enough coins for that stake.")
            reservation_id = uuid.uuid4().hex
            state["balances"][uid] = balance - amount
            state["reservations"][reservation_id] = {
                "user_id": uid, "amount": amount, "status": "reserved",
            }
            return {"reservation_id": reservation_id, "balance": balance - amount}

        return self._mutate_once(key, operation)

    def release(self, reservation_id, key):
        def operation(state):
            reservation = state["reservations"].get(str(reservation_id))
            if not reservation or reservation["status"] != "reserved":
                raise CoinError("Reservation is not available.")
            uid, amount = reservation["user_id"], reservation["amount"]
            state["balances"][uid] = int(
                state["balances"].get(uid, self.opening_balance)
            ) + amount
            reservation["status"] = "released"
            return {"reservation_id": str(reservation_id),
                    "balance": state["balances"][uid]}

        try:
            return self._mutate_once(key, operation)
        except CoinError:
            with self._locked():
                state = self._read()
                prior = state["operations"].get(str(key))
                if prior is not None:
                    return {"applied": False, **copy.deepcopy(prior)}
            raise

    def settle(self, reservation_ids, payouts, fee, key):
        fee = self._amount(fee, allow_zero=True)
        payouts = {str(uid): self._amount(amount, allow_zero=True)
                   for uid, amount in payouts.items()}

        def operation(state):
            reservations = []
            for reservation_id in reservation_ids:
                reservation = state["reservations"].get(str(reservation_id))
                if not reservation or reservation["status"] != "reserved":
                    raise CoinError("Settlement reservation is not available.")
                reservations.append(reservation)
            pool = sum(item["amount"] for item in reservations)
            if sum(payouts.values()) + fee != pool:
                raise CoinError("Settlement payouts and fee must equal the reserved pool.")
            for uid, amount in payouts.items():
                state["balances"][uid] = int(
                    state["balances"].get(uid, self.opening_balance)
                ) + amount
            for reservation in reservations:
                reservation["status"] = "settled"
            state["fees"] += fee
            return {"pool": pool, "payouts": copy.deepcopy(payouts), "fee": fee}

        return self._mutate_once(key, operation)

    def _credit(self, state, user_id, amount):
        uid = str(user_id)
        state["balances"][uid] = int(
            state["balances"].get(uid, self.opening_balance)
        ) + amount
        return {"balance": state["balances"][uid]}

    def _mutate_once(self, key, operation):
        key = str(key).strip()
        if not key:
            raise CoinError("An idempotency key is required.")
        with self._locked():
            state = self._read()
            if key in state["operations"]:
                return {"applied": False, **copy.deepcopy(state["operations"][key])}
            result = operation(state)
            state["operations"][key] = copy.deepcopy(result)
            self._write(state)
            return {"applied": True, **result}

    def _read(self):
        if not self.path.exists():
            return self._empty()
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                state = json.load(stream)
        except (json.JSONDecodeError, UnicodeDecodeError):
            evidence = self.path.with_name(f"{self.path.name}.corrupt.{uuid.uuid4().hex}")
            os.replace(self.path, evidence)
            raise CoinError("Coin ledger was corrupt and has been quarantined.")
        if not self._valid(state):
            raise CoinError("Coin ledger schema is invalid.")
        return state

    @staticmethod
    def _valid(state):
        return (isinstance(state, dict) and state.get("version") == 1
                and isinstance(state.get("balances"), dict)
                and isinstance(state.get("reservations"), dict)
                and isinstance(state.get("operations"), dict)
                and type(state.get("fees")) is int)

    def _write(self, state):
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
