"""VillageHub: pushes village state to everyone watching a village (owner now; visitors in Phase 15)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING

from fastapi import WebSocket
from sqlalchemy import select

from hearthforge.db.models import Village
from hearthforge.realtime.protocol import encode
from hearthforge.services import village as village_svc

if TYPE_CHECKING:
    from hearthforge.state import AppState

log = logging.getLogger("hearthforge.hub")


class VillageHub:
    def __init__(self, st: AppState, poll_interval: float = 10.0) -> None:
        self.st = st
        self.subs: dict[str, set[WebSocket]] = defaultdict(set)
        self.versions: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._dirty: set[str] = set()
        self.poll_interval = poll_interval

    def subscribe(self, owner_id: str, ws: WebSocket) -> None:
        self.subs[owner_id].add(ws)

    def unsubscribe(self, owner_id: str, ws: WebSocket) -> None:
        s = self.subs.get(owner_id)
        if s:
            s.discard(ws)
            if not s:
                self.subs.pop(owner_id, None)
                self.versions.pop(owner_id, None)

    def unsubscribe_all(self, ws: WebSocket) -> None:
        for owner in list(self.subs):
            self.unsubscribe(owner, ws)

    async def send_state(self, owner_id: str, state: dict) -> None:
        self.versions[owner_id] = state["version"]
        frame = encode("VILLAGE_STATE", owner_id, state["version"], state)
        for ws in list(self.subs.get(owner_id, ())):
            try:
                await ws.send_bytes(frame)
            except Exception:  # noqa: BLE001 - a dead socket must not block the others
                self.unsubscribe(owner_id, ws)

    async def publish(self, owner_id: str, state: dict | None = None) -> None:
        """Push the latest (settled) state to subscribers. Coalesces bursts per village."""
        if owner_id not in self.subs:
            return
        if state is not None:
            await self.send_state(owner_id, state)
            return
        lock = self._locks[owner_id]
        if lock.locked():
            self._dirty.add(owner_id)
            return
        async with lock:
            while True:
                self._dirty.discard(owner_id)
                async with self.st.sessionmaker() as session:
                    state = await village_svc.read_state(
                        session, self.st.config, uuid.UUID(owner_id), self.st.clock.now()
                    )
                await self.send_state(owner_id, state)
                if owner_id not in self._dirty:
                    break

    async def fallback_poll(self) -> None:
        """Safety net if NOTIFY is missed or the worker is down: re-check watched villages every few seconds.
        Reading settles due timers lazily, so completions still arrive without the worker."""
        while True:
            await asyncio.sleep(self.poll_interval)
            owners = list(self.subs)
            if not owners:
                continue
            try:
                async with self.st.sessionmaker() as session:
                    rows = (
                        await session.execute(
                            select(Village.user_id, Village.version).where(
                                Village.user_id.in_([uuid.UUID(o) for o in owners])
                            )
                        )
                    ).all()
                now = self.st.clock.now()
                due = await self._owners_with_due_work(owners, now)
                for uid, version in rows:
                    oid = str(uid)
                    if self.versions.get(oid) != version or oid in due:
                        with contextlib.suppress(Exception):
                            await self.publish(oid)
            except Exception:  # noqa: BLE001
                log.exception("village fallback poll failed")

    async def _owners_with_due_work(self, owners: list[str], now) -> set[str]:  # noqa: ANN001
        from hearthforge.db.models import BuildingState, VillageBuilding

        async with self.st.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(Village.user_id)
                    .join(VillageBuilding, VillageBuilding.village_id == Village.id)
                    .where(
                        Village.user_id.in_([uuid.UUID(o) for o in owners]),
                        VillageBuilding.state != BuildingState.active,
                        VillageBuilding.work_completes_at <= now,
                    )
                )
            ).all()
        return {str(r[0]) for r in rows}
