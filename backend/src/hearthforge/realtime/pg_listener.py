"""LISTEN hf_events on a dedicated direct connection (D-004/D-005). Reconnects forever."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING

import asyncpg

from hearthforge.services.events import CHANNEL
from hearthforge.settings import asyncpg_dsn

if TYPE_CHECKING:
    from hearthforge.state import AppState

log = logging.getLogger("hearthforge.listener")


class PgListener:
    def __init__(self, st: AppState) -> None:
        self.st = st

    def _on_event(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        try:
            msg = json.loads(payload)
        except ValueError:
            return
        if msg.get("kind") == "village.changed" and self.st.village_hub is not None:
            asyncio.get_running_loop().create_task(self.st.village_hub.publish(msg["owner_id"]))

    async def run(self) -> None:
        backoff = 1.0
        dsn, kw = asyncpg_dsn(self.st.settings.database_url)
        while True:
            conn = None
            try:
                conn = await asyncpg.connect(dsn, **kw)
                await conn.add_listener(CHANNEL, self._on_event)
                log.info("listening on %s", CHANNEL)
                backoff = 1.0
                while True:
                    await asyncio.sleep(30)
                    await conn.execute("SELECT 1")  # keepalive; raises if the connection died
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("listener disconnected (%s); retrying in %.0fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                if conn is not None:
                    with contextlib.suppress(Exception):
                        await conn.close()
