"""RoomManager: creates a RealmRoom on the first ENTER_AVATAR of a realm, reaps it when empty (PLAN §2.4)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from hearthforge.core.errors import GameError
from hearthforge.db.models import Avatar, AvatarLocation, DeathDrop, NodeHarvest, Realm, RealmMember, User
from hearthforge.domain import mapgen, plotlayout
from hearthforge.realtime.protocol import ROOM_LEFT
from hearthforge.services import inventory
from hearthforge.services import village as village_svc
from hearthforge.sim import motion as mo
from hearthforge.sim.room import EMPTY_ROOM_TTL, Player, RealmRoom
from hearthforge.sim.stats import stats_for

if TYPE_CHECKING:
    from hearthforge.realtime.conn import Conn
    from hearthforge.state import AppState

log = logging.getLogger("hearthforge.rooms")


class RoomManager:
    def __init__(self, st: AppState) -> None:
        self.st = st
        self.rooms: dict[uuid.UUID, RealmRoom] = {}
        self._lock = asyncio.Lock()

    def find(self, user_id: uuid.UUID) -> tuple[RealmRoom, Player] | None:
        for room in self.rooms.values():
            p = room.by_user.get(user_id)
            if p is not None:
                return room, p
        return None

    async def _room(self, realm: Realm) -> RealmRoom:
        room = self.rooms.get(realm.id)
        if room is not None and not room.closed:
            return room
        room = RealmRoom(self.st, realm.id, realm.seed)
        await self.load_villages(room)
        if self.st.settings.monsters_enabled:
            from hearthforge.sim.combat import Combat

            room.combat = Combat(room)
        self.rooms[realm.id] = room
        room.start()
        log.info("room up for realm %s", realm.id)
        return room

    async def load_villages(self, room: RealmRoom) -> None:
        cfg = self.st.config
        async with self.st.sessionmaker() as s:
            members = list(
                (await s.execute(select(RealmMember).where(RealmMember.realm_id == room.realm_id))).scalars()
            )
        states: dict[str, dict[str, Any]] = {}
        for m in members:
            async with self.st.sessionmaker() as s:
                states[str(m.user_id)] = await village_svc.read_state(s, cfg, m.user_id, self.st.clock.now())
        room.set_villages(states, {m.plot_index for m in members})

    async def enter(self, conn: Conn, user_id: uuid.UUID) -> tuple[RealmRoom, Player]:
        async with self._lock:
            found = self.find(user_id)
            if found is not None:
                room, p = found
                room.reattach(p, conn)
                await conn.send_bytes(room.joined_frame(p))
                return room, p
            async with self.st.sessionmaker() as s:
                row = (
                    await s.execute(
                        select(Realm, RealmMember, User, Avatar)
                        .join(RealmMember, RealmMember.realm_id == Realm.id)
                        .join(User, User.id == RealmMember.user_id)
                        .join(Avatar, Avatar.user_id == User.id)
                        .where(RealmMember.user_id == user_id)
                    )
                ).one_or_none()
                if row is None:
                    raise GameError("no_realm", "You're not in a realm.")
                realm, member, user, avatar = row
                if realm.mapgen_version != self.st.config.mapgen.version:
                    raise GameError("mapgen_version", "This realm was made with a different map version.")
                loadout = await inventory.loadout(s, self.st.config, user_id)
                now = self.st.clock.now()
                harvested = list(
                    (
                        await s.execute(
                            select(NodeHarvest).where(
                                NodeHarvest.user_id == user_id,
                                NodeHarvest.realm_id == realm.id,
                                NodeHarvest.respawn_at > now,
                            )
                        )
                    ).scalars()
                )
                markers = list(
                    (
                        await s.execute(
                            select(DeathDrop).where(
                                DeathDrop.user_id == user_id,
                                DeathDrop.realm_id == realm.id,
                                DeathDrop.recovered_at.is_(None),
                                DeathDrop.expires_at > now,
                            )
                        )
                    ).scalars()
                )
            room = await self._room(realm)
            p = self._make_player(room, conn, user, avatar, member.plot_index, loadout)
            wall = time.time()
            for h in harvested:
                p.depleted[h.node_id] = wall + (h.respawn_at - now).total_seconds()
            room.add_player(p)
            for dd in markers:  # your KO marker is still lying where you fell
                left = (dd.expires_at - now).total_seconds()
                for it in dd.items:
                    room.spawn_drop(p, it["item_key"], it["qty"], dd.x, dd.y, ttl_s=left, death_id=dd.id)
            await conn.send_bytes(room.joined_frame(p))
            return room, p

    def _make_player(
        self, room: RealmRoom, conn: Conn, user: User, av: Avatar, plot_index: int, loadout: dict[str, Any]
    ) -> Player:
        cfg = self.st.config
        lay = mapgen.layout(cfg.mapgen)
        ox, oy = lay.plot_origins[plot_index]
        tpl = plotlayout.template(cfg)
        vstate = room.villages.get(str(user.id))
        size = vstate["size"] if vstate else cfg.mapgen.plot.start_size
        lo = (cfg.mapgen.plot.frame - size) // 2
        door = (ox + tpl.door[0] + 0.5, oy + tpl.door[1] + 0.5)
        stats = stats_for(cfg, av.level)
        x, y = door
        if av.location == AvatarLocation.wild and av.realm_id == room.realm_id:
            px, py = float(av.pos_x), float(av.pos_y)
            if not room.grid.solid(int(px), int(py)):
                x, y = px, py
        m = mo.Motion(x=x, y=y, st=stats.st_max, st_max=stats.st_max)
        return Player(
            eid=room.new_id(),
            user_id=user.id,
            name=user.username,
            appearance=av.appearance,
            conn=conn,
            m=m,
            level=av.level,
            xp=av.xp,
            hp=float(min(max(1, av.hp), stats.hp_max)),
            stats=stats,
            weapon=loadout["weapon"],
            quick={int(k): v for k, v in loadout["quick"].items()},
            inv=loadout["inv"],
            inv_cap=loadout["inv_capacity"],
            home_rect=(ox + lo, oy + lo, size, size),
            home_door=door,
            armour=int(loadout.get("armour", 0)),
        )

    async def leave(self, user_id: uuid.UUID, conn: Conn | None = None) -> None:
        """LEAVE_AVATAR. Refused while combat-locked."""
        found = self.find(user_id)
        if found is None:
            return
        room, p = found
        if conn is not None and p.conn is not conn:
            return
        if room.tick_no - p.last_combat < room.combat_lock:
            raise GameError("in_combat", "You can't leave Avatar Mode mid-fight.")
        await room.remove_player(p, ROOM_LEFT["left"])

    def disconnected(self, conn: Conn) -> None:
        found = self.find(uuid.UUID(conn.user_id))
        if found is None:
            return
        room, p = found
        if p.conn is conn:
            room.disconnect(p)

    async def reload_loadout(self, user_id: uuid.UUID) -> None:
        """After a REST inventory change: refresh the room's mirror, keeping unflushed pickups."""
        found = self.find(user_id)
        if found is None:
            return
        room, p = found
        async with self.st.sessionmaker() as s:
            lo = await inventory.loadout(s, self.st.config, user_id)
        if p.pending.durability and lo["weapon"].get("instance_id") == p.weapon.get("instance_id"):
            lo["weapon"]["durability"] = p.weapon.get(
                "durability", lo["weapon"]["durability"]
            )  # unflushed wear
        p.weapon = lo["weapon"]
        p.armour = int(lo.get("armour", 0))
        p.quick = {int(k): v for k, v in lo["quick"].items()}
        p.inv = lo["inv"]
        p.inv_cap = lo["inv_capacity"]
        for key, qty in p.pending.grants.items():
            room.inv_add(p, key, qty)
        if p.m.atk:
            p.m.atk = 0
            p.m.atk_t = 0
        from hearthforge.realtime.protocol import EV

        p.ev.append([EV["INVENTORY"], p.inv])
        p.ev.append([EV["PLAYER"], *room.roster_entry(p)])
        for o in room.players.values():
            if o is not p:
                o.ev.append([EV["PLAYER"], *room.roster_entry(p)])

    def on_village_state(self, owner_id: str, state: dict[str, Any]) -> None:
        for room in self.rooms.values():
            room.update_village(owner_id, state)

    async def reaper(self, interval: float = 10.0) -> None:
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            for rid, room in list(self.rooms.items()):
                if room.empty_since is not None and now - room.empty_since > EMPTY_ROOM_TTL:
                    del self.rooms[rid]
                    with contextlib.suppress(Exception):
                        await room.stop()
                    log.info("room down for realm %s", rid)

    async def shutdown(self) -> None:
        for room in list(self.rooms.values()):
            with contextlib.suppress(Exception):
                await room.stop()
        self.rooms.clear()
