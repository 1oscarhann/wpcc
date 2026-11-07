"""VillageHub: pushes village state to everyone watching a village (owner now; visitors in Phase 15)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from hearthforge.db.models import Village
from hearthforge.realtime.protocol import encode
from hearthforge.services import village as village_svc

if TYPE_CHECKING:
    from hearthforge.realtime.conn import Conn
    from hearthforge.state import AppState

log = logging.getLogger("hearthforge.hub")


class VillageHub:
    def __init__(self, st: AppState, poll_interval: float = 10.0) -> None:
        self.st = st
        self.subs: dict[str, set[Conn]] = defaultdict(set)
        self.versions: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._dirty: set[str] = set()
        self.poll_interval = poll_interval
        self.users: dict[str, set[Conn]] = defaultdict(set)  # every live socket, by user (Phase 9)
        # Phase 13 (P18): online = a live socket, or one that dropped less than `offline_grace` ago
        self.online_since: dict[str, datetime] = {}
        self.offline_at: dict[str, datetime] = {}

    def register(self, ws: Conn) -> None:
        uid = ws.user_id
        if not self.users.get(uid):
            now = self.st.clock.now()
            gone = self.offline_at.pop(uid, None)
            grace = self.st.config.waves.eligible.offline_grace
            if gone is None or (now - gone).total_seconds() > grace or uid not in self.online_since:
                self.online_since[uid] = now
        self.users[uid].add(ws)

    def unregister(self, ws: Conn) -> None:
        s = self.users.get(ws.user_id)
        if s is not None:
            s.discard(ws)
            if not s:
                self.users.pop(ws.user_id, None)
                self.offline_at[ws.user_id] = self.st.clock.now()

    def online(self) -> set[str]:
        return set(self.users)

    def online_for(self, uid: str) -> float | None:
        """Seconds this user has been online (P18), or None if they're offline."""
        now = self.st.clock.now()
        if uid not in self.users:
            gone = self.offline_at.get(uid)
            if gone is None or (now - gone).total_seconds() > self.st.config.waves.eligible.offline_grace:
                return None
        since = self.online_since.get(uid)
        return (now - since).total_seconds() if since is not None else None

    async def notify(self, user_ids: list[str] | set[str], kind: str, payload: dict | None = None) -> None:
        """A small nudge to every socket of these users (e.g. 'realm' → refetch the realm)."""
        frame = encode("NOTIFY", kind, payload or {})
        for uid in user_ids:
            for ws in list(self.users.get(uid, ())):
                with contextlib.suppress(Exception):
                    await ws.send_bytes(frame)

    def subscribe(self, owner_id: str, ws: Conn) -> None:
        self.subs[owner_id].add(ws)

    def unsubscribe(self, owner_id: str, ws: Conn) -> None:
        s = self.subs.get(owner_id)
        if s:
            s.discard(ws)
            if not s:
                self.subs.pop(owner_id, None)
                self.versions.pop(owner_id, None)

    def unsubscribe_all(self, ws: Conn) -> None:
        for owner in list(self.subs):
            self.unsubscribe(owner, ws)

    async def send_state(self, owner_id: str, state: dict) -> None:
        if self.st.rooms is not None:
            self.st.rooms.on_village_state(owner_id, state)
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
            if state is not None and self.st.rooms is not None:
                self.st.rooms.on_village_state(owner_id, state)
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
            # Phase 14: a villager is due to arrive (or the leaving clock ran out): push a fresh state
            step = timedelta(seconds=self.st.config.villagers.arrival.every)
            villagers_due = (
                await session.execute(
                    select(Village.user_id).where(
                        Village.user_id.in_([uuid.UUID(o) for o in owners]),
                        Village.villagers_at.is_not(None),
                        Village.villagers_at + step <= now,
                    )
                )
            ).all()
        return {str(r[0]) for r in rows} | {str(r[0]) for r in villagers_due}
