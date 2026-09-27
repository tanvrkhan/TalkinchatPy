"""Modern TalkinChat lifecycle and command dispatch entry point."""

import argparse
import asyncio
import inspect
import os

import commands  # noqa: F401  # register command modules
from config import Config, ConfigError
from config_store import ConfigStore
from registry import DispatchContext, REGISTRY
from services.auth import AccessControl
from services.activity_store import ActivityStore
from services.card_session import CardSessionManager
from services.coin_ledger import CoinLedger
from services.cricket_manager import CricketManager
from services.cricket_stats import CricketStats
from services.cricket_store import CricketStore
from services.game_store import GameStore
from transports.talkinchat import EventDecoder, EventKind, TalkinChatTransport


class TalkinChatBot:
    def __init__(self, config, *, connector=None, sleep=asyncio.sleep, registry=REGISTRY):
        self.config = config
        self.connector = connector or self._connect
        self.sleep = sleep
        self.registry = registry
        self.decoder = EventDecoder()
        self.transport = None
        self.store = ConfigStore(config.state_dir)
        self.access = AccessControl(config.owner, self.store.get("admins", []))
        self.activity = ActivityStore(config.state_dir / "activity.sqlite3")
        self.card_sessions = CardSessionManager(
            GameStore(config.state_dir / "card_games.json"))
        self.cricket = CricketManager(
            CricketStore(config.state_dir / "cricket.json"),
            CoinLedger(config.state_dir / "coins.json"),
            CricketStats(config.state_dir / "cricket_stats.json"),
        )

    async def _connect(self, url):
        import websockets
        return await websockets.connect(
            url,
            open_timeout=self.config.connect_timeout,
            close_timeout=5,
            max_size=2 * 1024 * 1024,
        )

    async def run_connection(self):
        socket = self.connector(self.config.websocket_url)
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
        async for frame in socket:
            event = self.decoder.decode(frame)
            if event.kind == EventKind.LOGIN_SUCCESS:
                for room in self.config.rooms:
                    await self.transport.join_room(room)
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
                await self.registry.dispatch(self, context, event.body)
            elif event.kind == EventKind.USER_JOINED:
                self.activity.record_presence(
                    event.event_id or f"join:{hash(frame)}", event.room, event.room,
                    event.user_key, event.user, "join")

    async def run_forever(self):
        delay = 1.0
        while True:
            try:
                await self.run_connection()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except (ConnectionError, OSError, TimeoutError):
                await self.sleep(delay)
                delay = min(delay * 2, 60.0)

    async def reply(self, context, text):
        if context.is_dm:
            return await self.transport.send_dm(context.user, text)
        return await self.transport.reply(context.room, text)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--check-readiness", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = Config.from_env(os.environ)
    except ConfigError as exc:
        parser.error(str(exc))
    if args.check_config or args.check_readiness:
        print("TalkinChat configuration is valid.")
        return 0
    asyncio.run(TalkinChatBot(config).run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
