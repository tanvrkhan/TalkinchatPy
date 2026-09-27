"""Modern TalkinChat lifecycle and command dispatch entry point."""

import argparse
import asyncio
import contextlib
import inspect
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

from websockets.exceptions import WebSocketException

import commands  # noqa: F401  # register command modules
from config import Config, ConfigError
from config_store import ConfigStore
from registry import DispatchContext, PermissionDenied, REGISTRY
from services.auth import AccessControl
from services.activity_store import ActivityStore
from services.card_session import CardSessionManager
from services.coin_ledger import CoinLedger
from services.cricket_manager import CricketManager
from services.cricket_stats import CricketStats
from services.cricket_store import CricketStore
from services.game_store import GameStore
from transports.talkinchat import (
    EventDecoder, EventKind, TalkinChatTransport, authenticate, websocket_headers,
)


class TalkinChatBot:
    def __init__(self, config, *, connector=None, authenticator=authenticate,
                 sleep=asyncio.sleep, registry=REGISTRY):
        self.config = config
        self.connector = connector or self._connect
        self.authenticator = authenticator
        self.sleep = sleep
        self.registry = registry
        self.decoder = EventDecoder()
        self.transport = None
        self.store = ConfigStore(config.state_dir)
        self.refresh_access()
        self.activity = ActivityStore(config.state_dir / "activity.sqlite3")
        self.activity.cleanup()
        self.card_sessions = CardSessionManager(
            GameStore(config.state_dir / "card_games.json"))
        self.cricket = CricketManager(
            CricketStore(config.state_dir / "cricket.json"),
            CoinLedger(config.state_dir / "coins.json"),
            CricketStats(config.state_dir / "cricket_stats.json"),
        )
        self._initialized = False

    async def _connect(self, url, headers=None):
        import websockets
        return await websockets.connect(
            url,
            open_timeout=self.config.connect_timeout,
            close_timeout=5,
            max_size=2 * 1024 * 1024,
            extra_headers=headers,
        )

    def _device_id(self):
        path = self.config.state_dir / "device_id"
        if path.is_file():
            return path.read_text(encoding="ascii").strip()
        self.config.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        value = secrets.token_hex(16)
        path.write_text(value + "\n", encoding="ascii")
        os.chmod(path, 0o600)
        return value

    async def run_connection(self):
        url = self.config.websocket_url
        headers = None
        if not url:
            device_id = self._device_id()
            auth = await asyncio.to_thread(
                self.authenticator, self.config.auth_url, self.config.username,
                self.config.password, device_id=device_id,
                timeout=self.config.connect_timeout,
            )
            url = f"wss://chatp.net:{auth.server}/server"
            headers = websocket_headers(
                self.config.username, self.config.password, auth, device_id=device_id)
        try:
            socket = self.connector(url, headers)
        except TypeError:
            socket = self.connector(url)
        if inspect.isawaitable(socket):
            socket = await socket
        self.transport = TalkinChatTransport(
            socket,
            self.config.username,
            self.config.password,
            upload_url=self.config.upload_url,
            max_upload_bytes=self.config.max_upload_bytes,
        )
        await self.transport.login()
        membership_task = None
        try:
            if headers is not None:
                await self.join_configured_rooms()
                membership_task = asyncio.create_task(self.maintain_room_membership())
            async for frame in socket:
                event = self.decoder.decode(frame)
                if event.kind == EventKind.LOGIN_SUCCESS:
                    await self.join_configured_rooms()
                    if membership_task is None:
                        membership_task = asyncio.create_task(
                            self.maintain_room_membership())
                elif event.kind == EventKind.TEXT and event.user_key != self.config.username.casefold():
                    self.activity.record_message(
                        event.event_id or f"message:{hash(frame)}", event.room, event.room,
                        event.user_key, event.user, event.body)
                    if self.config.collector_mode:
                        continue
                    context = DispatchContext(
                        event.user,
                        event.room,
                        self.access.level_of(event.user),
                        tuple(self.store.get("disabled", [])),
                    )
                    await self.dispatch(context, event.body)
                elif event.kind == EventKind.USER_JOINED:
                    self.activity.record_presence(
                        event.event_id or f"join:{hash(frame)}", event.room, event.room,
                        event.user_key, event.user, "join")
                    await self.handle_join(event)
        finally:
            if membership_task is not None:
                membership_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await membership_task

    async def join_configured_rooms(self):
        for room in self.config.rooms:
            await self.transport.join_room(room)
        self.mark_ready()

    async def maintain_room_membership(self):
        while True:
            await self.sleep(self.config.room_join_interval)
            try:
                await self.join_configured_rooms()
            except (ConnectionError, OSError, TimeoutError, WebSocketException):
                await self.transport.websocket.close()
                raise

    async def run_forever(self):
        await self.initialize()
        delay = 1.0
        while True:
            try:
                await self.run_connection()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except (ConnectionError, OSError, TimeoutError, WebSocketException):
                await self.sleep(delay)
                delay = min(delay * 2, 60.0)

    async def initialize(self):
        if self._initialized:
            return
        await self.card_sessions.restore()
        self._initialized = True

    async def reply(self, context, text):
        if context.is_dm:
            return await self.transport.send_dm(context.user, text)
        return await self.transport.reply(context.room, text)

    def refresh_access(self):
        self.access = AccessControl(
            self.config.owner,
            self.store.get("admins", []),
            self.store.get("room_authorities", {}),
        )

    def mark_ready(self):
        self.config.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.config.state_dir / ".ready.json.tmp"
        temporary.write_text(
            json.dumps({"ready": True, "rooms": len(self.config.rooms), "at": time.time()}) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.config.state_dir / "ready.json")

    async def dispatch(self, context, text):
        parsed = self.registry.parse(text)
        if parsed is None:
            return False
        spec = self.registry.get(parsed[0])
        if spec is None:
            return False
        context.room_authority = self.access.has_level(
            context.user, "admin", room=context.room, allow_room_admin=True)
        privileged = spec.room_admin or spec.level in {"admin", "creator"}
        try:
            handled = await self.registry.dispatch(self, context, text)
        except PermissionDenied as exc:
            if privileged:
                self._audit(context, spec.name, "rejected")
            await self.reply(context, str(exc))
            return True
        if handled and privileged:
            self._audit(context, spec.name, "success")
        return handled

    def _audit(self, context, action, outcome):
        self.activity.record_admin_action(
            secrets.token_hex(16), context.room, context.room,
            context.user_key, context.user, "", "", action, outcome,
            detail="",
        )

    async def handle_join(self, event):
        room_key = event.room.casefold()
        if not self.store.get("welcome_rooms", {}).get(room_key, False):
            return
        template = self.store.get("custom_welcomes", {}).get(room_key, "Welcome {user}!")
        try:
            message = str(template).format(user=event.user, room=event.room)
        except (KeyError, ValueError):
            message = f"Welcome {event.user}!"
        if self.store.get("welcome_images", {}).get(room_key, False):
            path = None
            try:
                from services.draw import draw_welcome
                path = await asyncio.to_thread(draw_welcome, event.user, event.room)
                url = await self.transport.upload(path, event.room, "image/png")
                await self.transport.send_image(event.room, url)
                return
            except Exception:
                pass
            finally:
                if path:
                    Path(path).unlink(missing_ok=True)
        await self.transport.say(event.room, message)


def check_readiness(config):
    config.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(config.state_dir, 0o700)
    lock_parent = config.ollama_lock.parent
    lock_parent.mkdir(mode=0o770, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=config.state_dir, prefix=".readiness-", delete=True):
        pass
    if not os.access(lock_parent, os.W_OK):
        raise ConfigError(f"Ollama lock directory is not writable: {lock_parent}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--check-readiness", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = Config.from_env(os.environ)
    except ConfigError as exc:
        parser.error(str(exc))
    if args.check_readiness:
        check_readiness(config)
        print("TalkinChat configuration and local runtime paths are ready.")
        return 0
    if args.check_config:
        print("TalkinChat configuration is valid.")
        return 0
    asyncio.run(TalkinChatBot(config).run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
