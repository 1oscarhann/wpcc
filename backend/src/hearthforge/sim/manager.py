"""RoomManager: creates a RealmRoom on the first ENTER_AVATAR of a realm, reaps it when empty (PLAN §2.4)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
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


@dataclass
class Party:
    """In memory only (D-025): a restart disbands parties and players just re-form them."""

    id: str
    realm_id: uuid.UUID
    leader: uuid.UUID
    members: list[uuid.UUID] = field(default_factory=list)


class RoomManager:
    def __init__(self, st: AppState) -> None:
        self.st = st
        self.rooms: dict[uuid.UUID, RealmRoom] = {}
        self._lock = asyncio.Lock()
        self.parties: dict[str, Party] = {}
        self.invites: dict[uuid.UUID, tuple[str, uuid.UUID, float]] = {}  # invitee → (party, inviter, expiry)

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
        room.weather_seed = realm.weather_seed
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
                from hearthforge.services import world as world_svc

                fog = await world_svc.load_fog(s, self.st.config, user_id, realm.id)
                attuned = await world_svc.attuned(s, user_id)
            room = await self._room(realm)
            p = self._make_player(room, conn, user, avatar, member.plot_index, loadout)
            p.fog = fog
            p.attuned = attuned
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

    # ── realm changes (Phase 9) ─────────────────────────────────────────────
    async def evict(self, user_id: uuid.UUID) -> None:
        """Their village moved to another realm: out of this room (the client goes back to Build Mode)."""
        found = self.find(user_id)
        if found is not None:
            room, p = found
            self.leave_party(user_id)
            await room.remove_player(p, ROOM_LEFT["moved"])

    async def refresh_realm(self, realm_id: uuid.UUID) -> None:
        """Members came or went: reload every village's buildings (collision) in that realm's room."""
        room = self.rooms.get(realm_id)
        if room is not None and not room.closed:
            await self.load_villages(room)
            from hearthforge.realtime.protocol import encode

            frame = encode("BLOCKS", room.grid.block_rects, sorted(room.claimed))
            for p in list(room.players.values()):
                asyncio.create_task(room._send(p, frame))

    # ── parties (Phase 9) ───────────────────────────────────────────────────
    def party_of(self, user_id: uuid.UUID) -> Party | None:
        for party in self.parties.values():
            if user_id in party.members:
                return party
        return None

    def party_players(self, room: RealmRoom, user_id: uuid.UUID) -> list[Player]:
        party = self.party_of(user_id)
        if party is None:
            return []
        return [p for uid in party.members if (p := room.by_user.get(uid)) is not None]

    def invite(self, room: RealmRoom, inviter: Player, target_eid: int) -> str | None:
        """Returns an error code, or None when the invite went out."""
        target = room.players.get(target_eid)
        if target is None or target is inviter:
            return "no_player"
        party = self.party_of(inviter.user_id)
        if party is not None and len(party.members) >= self.st.config.social.party.max_size:
            return "party_full"
        if party is not None and target.user_id in party.members:
            return "already_in"
        if party is None:
            party = Party(secrets.token_hex(4), room.realm_id, inviter.user_id, [inviter.user_id])
            self.parties[party.id] = party
        self.invites[target.user_id] = (
            party.id,
            inviter.user_id,
            time.monotonic() + self.st.config.social.party.invite_ttl,
        )
        from hearthforge.realtime.protocol import EV

        target.ev.append([EV["PARTY_INVITE"], party.id, inviter.name])
        self._push_party(party, room)
        return None

    def accept(self, room: RealmRoom, p: Player, party_id: str) -> str | None:
        inv = self.invites.get(p.user_id)
        if inv is None or inv[0] != party_id or inv[2] < time.monotonic():
            return "invite_expired"
        party = self.parties.get(party_id)
        if party is None:
            return "invite_expired"
        if len(party.members) >= self.st.config.social.party.max_size:
            return "party_full"
        del self.invites[p.user_id]
        self.leave_party(p.user_id)
        party.members.append(p.user_id)
        self._push_party(party, room)
        return None

    def leave_party(self, user_id: uuid.UUID) -> None:
        party = self.party_of(user_id)
        if party is None:
            return
        party.members.remove(user_id)
        room = self.rooms.get(party.realm_id)
        if room is not None:
            from hearthforge.realtime.protocol import EV

            p = room.by_user.get(user_id)
            if p is not None:
                p.ev.append([EV["PARTY"], None])
        if len(party.members) <= 1:
            for uid in party.members:
                if room is not None and (o := room.by_user.get(uid)) is not None:
                    from hearthforge.realtime.protocol import EV

                    o.ev.append([EV["PARTY"], None])
            del self.parties[party.id]
            return
        if party.leader == user_id:
            party.leader = party.members[0]
        if room is not None:
            self._push_party(party, room)

    def party_state(self, party: Party, room: RealmRoom) -> dict[str, Any]:
        out = []
        for uid in party.members:
            o = room.by_user.get(uid)
            out.append(
                {
                    "user_id": str(uid),
                    "eid": o.eid if o else None,
                    "name": o.name if o else "?",
                    "level": o.level if o else 0,
                    "hp": round(o.hp) if o else 0,
                    "hp_max": o.stats.hp_max if o else 1,
                    "here": o is not None,
                    "x": round(o.m.x, 1) if o else None,
                    "y": round(o.m.y, 1) if o else None,
                }
            )
        return {"id": party.id, "leader": str(party.leader), "members": out}

    def _push_party(self, party: Party, room: RealmRoom) -> None:
        from hearthforge.realtime.protocol import EV

        state = self.party_state(party, room)
        for uid in party.members:
            o = room.by_user.get(uid)
            if o is not None:
                o.ev.append([EV["PARTY"], state])

    def party_tick(self, room: RealmRoom) -> None:
        """Once a second: party frames (HP bars, map dots) for everyone in a party in this room."""
        for party in list(self.parties.values()):
            if party.realm_id == room.realm_id:
                self._push_party(party, room)
        now = time.monotonic()
        for uid, (_pid, _inviter, exp) in list(self.invites.items()):
            if exp < now:
                del self.invites[uid]

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
