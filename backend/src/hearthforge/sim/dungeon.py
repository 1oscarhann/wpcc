"""Delves (Phase 12): party instances inside the realm room.

An instance's tiles live far east of the map (x ≥ space.x0), one `slot × slot` square each, so the
room's collision, combat and snapshots just work and parties never see each other (the area of
interest is far smaller than a slot). WorldGrid.solid asks `DungeonSpace.solid` for those columns.

Flow: entering a room for the first time triggers it. Combat rooms lock their doors and spawn a pack;
the doors open when it's dead. Puzzle rooms (rune plates in order, or levers that light lamps) keep
the doors deeper in locked until solved. Treasure rooms hold a chest per player. The mini-boss is a
tough elite. The boss calls adds and enrages; killing it opens a portal home and records the run.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from hearthforge.domain import dungeon as dom
from hearthforge.realtime.protocol import EV

if TYPE_CHECKING:
    from hearthforge.sim.combat import Monster
    from hearthforge.sim.room import Player, RealmRoom

BOSS_FLAG = 64


def utc_day(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%d")


@dataclass
class Instance:
    id: int
    slot: int
    key: str  # cave:<poi> | daily:<day>
    kind: str  # cave | daily
    name: str
    biome: str
    difficulty: int
    layout: dom.Layout
    ox: int
    oy: int
    entrance: tuple[float, float]  # where you come back out
    party: str | None
    members: set[uuid.UUID] = field(default_factory=set)
    names: dict[uuid.UUID, str] = field(default_factory=dict)
    visited: set[int] = field(default_factory=set)
    cleared: set[int] = field(default_factory=set)
    locked: set[int] = field(default_factory=set)  # door ids
    pack: dict[int, set[int]] = field(default_factory=dict)  # room id → live monster ids
    plates_next: int = 0
    plates_on: set[int] = field(default_factory=set)  # prop indices lit
    lamps: int = 0
    solved: set[int] = field(default_factory=set)
    chests: dict[int, set[uuid.UUID]] = field(default_factory=dict)  # prop index → who opened it
    boss_id: int | None = None
    boss_phase: int = 0
    enraged: bool = False
    boss_dead: bool = False
    started: float = field(default_factory=time.time)
    clear_ms: int | None = None
    deaths: int = 0
    empty_since: float | None = None
    solid: bytearray = field(default_factory=bytearray)

    def local(self, x: float, y: float) -> tuple[float, float]:
        return x - self.ox, y - self.oy

    def world(self, x: float, y: float) -> tuple[float, float]:
        return x + self.ox, y + self.oy


class DungeonSpace:
    def __init__(self, room: RealmRoom) -> None:
        self.room = room
        self.cfg = room.cfg.dungeons
        self.x0 = self.cfg.space.x0
        self.size = self.cfg.space.slot
        self.instances: dict[int, Instance] = {}
        self.by_slot: dict[int, Instance] = {}
        self._next = 1
        self.runs: list[dict[str, Any]] = []  # finished runs waiting to be saved (persist drains this)
        room.grid.dungeon_solid = self.solid
        room.grid.dungeon_x0 = self.x0

    # ── geometry ─────────────────────────────────────────────────────────────
    def solid(self, x: int, y: int) -> bool:
        inst = self.by_slot.get((x - self.x0) // self.size)
        if inst is None:
            return True
        lx, ly = x - inst.ox, y - inst.oy
        if not (0 <= lx < inst.layout.w and 0 <= ly < inst.layout.h):
            return True
        return inst.solid[ly * inst.layout.w + lx] == 1

    def inside(self, x: float) -> bool:
        return x >= self.x0

    def of(self, p: Player) -> Instance | None:
        return self.instances.get(p.dungeon) if p.dungeon else None

    def _rebuild_solid(self, inst: Instance) -> None:
        lay = inst.layout
        s = bytearray(lay.w * lay.h)
        for i, t in enumerate(lay.tiles):
            s[i] = 1 if t in (dom.VOID, dom.WALL) else 0
        for pr in lay.props:
            if pr.kind in ("pillar", "chest", "lamp"):
                s[pr.y * lay.w + pr.x] = 1
        for d in lay.doors:
            if d.id in inst.locked:
                for x, y in d.tiles:
                    s[y * lay.w + x] = 1
        inst.solid = s

    # ── entering and leaving ─────────────────────────────────────────────────
    def enter(
        self, p: Player, key: str, kind: str, biome: str, ret: tuple[float, float], name: str
    ) -> str | None:
        if p.ko > 0:
            return "ko"
        if p.dungeon:
            return "already_in"
        found = self.room.st.rooms.party_of(p.user_id) if self.room.st.rooms is not None else None
        party = found.id if found is not None else None
        inst = next(
            (
                i
                for i in self.instances.values()
                if i.key == key
                and i.clear_ms is None
                and (i.party == party if party else p.user_id in i.members)
            ),
            None,
        )
        if inst is None:
            inst = self._create(key, kind, biome, ret, party, name)
        if len(inst.members) >= self.cfg.max_party and p.user_id not in inst.members:
            return "full"
        inst.members.add(p.user_id)
        inst.names[p.user_id] = p.name
        inst.empty_since = None
        p.dungeon = inst.id
        p.dungeon_return = ret
        sx, sy = inst.world(*inst.layout.start)
        p.m.x, p.m.y = sx, sy
        p.m.dodge = 0
        p.inputs.clear()
        p.iframes = self.room.hz * 2
        p.ev.append([EV["DUNGEON_ENTER"], self.enter_payload(inst)])
        self.room.toast(p, "delve_enter", {"name": inst.name})
        return None

    def _create(
        self, key: str, kind: str, biome: str, ret: tuple[float, float], party: str | None, name: str
    ) -> Instance:
        slot = 0
        while slot in self.by_slot:
            slot += 1
        lay = self.cfg.layout
        day = utc_day()
        seed = (
            dom.seed_for("daily", day)
            if kind == "daily"
            else dom.seed_for(self.room.seed, key, day if self.cfg.reseed == "daily" else "")
        )
        layout = dom.generate(seed, lay.cols, lay.rows, lay.cell_w, lay.cell_h, lay.rooms)
        spec = self.room.cfg.enemies.biomes.get(biome)  # type: ignore[call-overload]
        inst = Instance(
            id=self._next,
            slot=slot,
            key=key,
            kind=kind,
            name=name,
            biome=biome,
            difficulty=spec.difficulty if spec else 1,
            layout=layout,
            ox=self.x0 + slot * self.size,
            oy=8,
            entrance=ret,
            party=party,
        )
        self._next += 1
        inst.lamps = layout.lamps_start
        self._rebuild_solid(inst)
        self.instances[inst.id] = inst
        self.by_slot[slot] = inst
        return inst

    def enter_payload(self, inst: Instance) -> dict[str, Any]:
        return {
            "id": inst.id,
            "name": inst.name,
            "kind": inst.kind,
            "biome": inst.biome,
            "difficulty": inst.difficulty,
            "origin": [inst.ox, inst.oy],
            "layout": inst.layout.to_wire(),
            "state": self.state(inst),
            "started_ms": int(inst.started * 1000),
        }

    def state(self, inst: Instance) -> dict[str, Any]:
        return {
            "locked": sorted(inst.locked),
            "visited": sorted(inst.visited),
            "cleared": sorted(inst.cleared),
            "plates": sorted(inst.plates_on),
            "lamps": inst.lamps,
            "solved": sorted(inst.solved),
            "portal": inst.boss_dead,
            "clear_ms": inst.clear_ms,
        }

    def leave(self, p: Player, teleport: bool = True) -> None:
        inst = self.of(p)
        p.dungeon = 0
        if inst is None:
            return
        inst.members.discard(p.user_id)
        if not inst.members:
            inst.empty_since = time.monotonic()
        if teleport:
            x, y = p.dungeon_return or inst.entrance
            p.m.x, p.m.y = x, y
            p.m.dodge = 0
            p.inputs.clear()
            p.iframes = self.room.hz
            p.pending.save_pos = True
        p.ev.append([EV["DUNGEON_LEFT"]])

    # ── the tick ─────────────────────────────────────────────────────────────
    def tick(self, t: int) -> None:
        if not self.instances:
            return
        players = self.room.players
        for inst in list(self.instances.values()):
            if inst.empty_since is not None and time.monotonic() - inst.empty_since > self.cfg.idle_close:
                self._close(inst)
                continue
            here = [p for p in players.values() if p.dungeon == inst.id and p.ko == 0]
            for p in here:
                lx, ly = inst.local(p.m.x, p.m.y)
                r = inst.layout.room_at(lx, ly)
                if r is not None and r.id not in inst.visited:
                    self._on_enter(inst, r, p, here)
                if r is not None and r.kind == "puzzle" and r.puzzle == "plates" and r.id not in inst.solved:
                    self._plates(inst, r, int(lx), int(ly))
            if t % 5 == 0:
                self._check_packs(inst)
                self._boss(inst)

    def _members(self, inst: Instance) -> list[Player]:
        return [p for p in self.room.players.values() if p.dungeon == inst.id]

    def _broadcast(self, inst: Instance, ev: list[Any]) -> None:
        for p in self._members(inst):
            p.ev.append(ev)

    def _set_locked(self, inst: Instance, doors: set[int]) -> None:
        inst.locked = doors
        self._rebuild_solid(inst)
        # nobody stays stuck inside a door that just shut: nudge them into the room
        lay = inst.layout
        for p in self._members(inst):
            lx, ly = inst.local(p.m.x, p.m.y)
            if inst.solid[int(ly) * lay.w + int(lx)] == 1:
                r = lay.room_at(lx, ly) or min(
                    lay.rooms, key=lambda rr: (rr.cx - lx) ** 2 + (rr.cy - ly) ** 2
                )
                nx = min(max(lx, r.x + 1.5), r.x + r.w - 1.5)
                ny = min(max(ly, r.y + 1.5), r.y + r.h - 1.5)
                p.m.x, p.m.y = inst.world(nx, ny)
        self._broadcast(inst, [EV["DUNGEON"], "doors", sorted(inst.locked)])

    def _on_enter(self, inst: Instance, r: dom.Room, p: Player, here: list[Player]) -> None:
        inst.visited.add(r.id)
        self._broadcast(inst, [EV["DUNGEON"], "visit", r.id])
        if r.kind in ("combat", "miniboss", "boss"):
            self._spawn_pack(inst, r)
            self._set_locked(inst, inst.locked | set(r.doors))
            self._broadcast(inst, [EV["SFX"], "gate", p.m.x, p.m.y])
        elif r.kind == "puzzle":
            gates = {d.id for d in inst.layout.doors if d.gate and d.rooms[0] == r.id}
            self._set_locked(inst, inst.locked | gates)
        elif r.kind == "entrance":
            inst.cleared.add(r.id)

    def _spawn_pack(self, inst: Instance, r: dom.Room) -> None:
        combat = self.room.combat
        if combat is None:
            return
        rng = self.room.rng
        en = self.room.cfg.enemies
        spec = en.biomes.get(inst.biome)  # type: ignore[call-overload]
        roster = list(spec.roster) if spec else ["slime"]
        weights = list(spec.roster.values()) if spec else [1.0]
        t = self.room.tick_no
        ids: set[int] = set()

        def put(key: str, elite: bool = False) -> Monster:
            x = r.x + 1.5 + rng.random() * (r.w - 3)
            y = r.y + 1.5 + rng.random() * (r.h - 3)
            wx, wy = inst.world(x, y)
            m = combat.spawn_one(key, wx, wy, inst.biome, t, elite=elite, spread=0.5)
            m.hx, m.hy = inst.world(r.cx, r.cy)
            m.state, m.target = ("idle", None) if m.state == "hidden" else ("idle", None)
            m.dungeon = inst.id
            ids.add(m.id)
            return m

        if r.kind == "combat":
            lo, hi = self.cfg.combat.monsters
            for _ in range(rng.randint(lo, hi)):
                put(rng.choices(roster, weights)[0])
        elif r.kind == "miniboss":
            key = rng.choices([k for k in roster if not en.enemies[k].summon] or roster)[0]
            m = put(key, elite=True)
            m.hp = m.hp_max = round(m.hp_max * self.cfg.miniboss.hp)
            for _ in range(self.cfg.miniboss.adds):
                put(rng.choices(roster, weights)[0])
        elif r.kind == "boss":
            m = put(self.cfg.boss.enemy)
            m.x, m.y = inst.world(r.cx, r.cy - 1)
            m.boss = True
            inst.boss_id = m.id
            self._broadcast(inst, [EV["DUNGEON"], "boss", m.id, en.enemies[self.cfg.boss.enemy].name])
        inst.pack[r.id] = ids
        # everyone in the room gets aggro'd: no sneaking past a pack
        for mid in ids:
            mm = combat.monsters.get(mid)
            if mm is not None:
                near = [p for p in self._members(inst) if inst.layout.room_at(*inst.local(p.m.x, p.m.y)) is r]
                if near:
                    mm.state, mm.target = "chase", near[0].eid

    def _check_packs(self, inst: Instance) -> None:
        combat = self.room.combat
        if combat is None:
            return
        for rid, ids in list(inst.pack.items()):
            alive = {i for i in ids if i in combat.monsters}
            inst.pack[rid] = alive
            if alive or rid in inst.cleared:
                continue
            r = inst.layout.rooms[rid]
            inst.cleared.add(rid)
            self._set_locked(inst, inst.locked - set(r.doors))
            self._broadcast(inst, [EV["DUNGEON"], "cleared", rid])
            xp = self.cfg.xp.room * inst.difficulty
            for p in self._members(inst):
                self.room.grant_xp(p, xp)
            if r.kind == "boss":
                self._boss_down(inst, r)

    def _boss(self, inst: Instance) -> None:
        combat = self.room.combat
        if combat is None or inst.boss_id is None or inst.boss_dead:
            return
        m = combat.monsters.get(inst.boss_id)
        if m is None:
            return
        frac = m.hp / m.hp_max
        b = self.cfg.boss
        while inst.boss_phase < len(b.adds_at) and frac <= b.adds_at[inst.boss_phase]:
            inst.boss_phase += 1
            r = next(r for r in inst.layout.rooms if r.kind == "boss")
            spec = self.room.cfg.enemies.biomes.get(inst.biome)  # type: ignore[call-overload]
            roster = list(spec.roster) if spec else ["slime"]
            swarm = [k for k in roster if self.room.cfg.enemies.enemies[k].archetype == "swarmer"] or roster
            for _ in range(b.adds):
                mm = combat.spawn_one(swarm[0], m.x, m.y, inst.biome, self.room.tick_no, spread=2.0)
                mm.dungeon = inst.id
                mm.state, mm.target = "chase", m.target
                inst.pack[r.id].add(mm.id)
            self._broadcast(inst, [EV["SFX"], "summon", m.x, m.y])
            self._broadcast(inst, [EV["DUNGEON"], "phase", inst.boss_phase])
        if not inst.enraged and frac <= b.enrage_at:
            inst.enraged = True
            m.speed *= b.enrage_speed
            self._broadcast(inst, [EV["DUNGEON"], "enrage", m.id])

    def _boss_down(self, inst: Instance, r: dom.Room) -> None:
        inst.boss_dead = True
        inst.clear_ms = int((time.time() - inst.started) * 1000)
        bl = self.cfg.boss_loot
        rng = self.room.rng
        cx, cy = inst.world(r.cx, r.cy)
        for p in self._members(inst):
            self.room.spawn_drop(p, "coins", rng.randint(*bl.coins) * inst.difficulty, cx, cy + 1)
            self.room.spawn_drop(p, "ancient_rune", rng.randint(*bl.runes), cx, cy + 1)
            if rng.random() < bl.blueprint:
                self.room.spawn_drop(p, rng.choice(self.cfg.blueprints), 1, cx, cy + 1)
            self.room.grant_xp(p, self.cfg.xp.boss * inst.difficulty)
            p.pending.stats["delve.cleared"] += 1
            if inst.kind == "daily":
                p.pending.stats["delve.daily"] += 1
        self._broadcast(inst, [EV["DUNGEON"], "portal", inst.clear_ms])
        self.runs.append(
            {
                "kind": inst.kind,
                "key": inst.key,
                "day": utc_day(),
                "seed": inst.layout.seed,
                "realm_id": self.room.realm_id,
                "names": [inst.names[u] for u in sorted(inst.names, key=str)],
                "user_ids": sorted(str(u) for u in inst.names),
                "clear_ms": inst.clear_ms,
                "deaths": inst.deaths,
                "biome": inst.biome,
            }
        )

    def _plates(self, inst: Instance, r: dom.Room, lx: int, ly: int) -> None:
        for i, pr in enumerate(inst.layout.props):
            if pr.kind != "plate" or pr.room != r.id or (pr.x, pr.y) != (lx, ly) or i in inst.plates_on:
                continue
            if pr.data == inst.plates_next:
                inst.plates_on.add(i)
                inst.plates_next += 1
                self._broadcast(inst, [EV["DUNGEON"], "plates", sorted(inst.plates_on)])
                if inst.plates_next >= 3:
                    self._solve(inst, r)
            else:  # wrong order: they all go dark again
                inst.plates_on.clear()
                inst.plates_next = 0
                self._broadcast(inst, [EV["DUNGEON"], "plates", []])
                self._broadcast(inst, [EV["SFX"], "fizzle", *inst.world(lx + 0.5, ly + 0.5)])

    def _solve(self, inst: Instance, r: dom.Room) -> None:
        inst.solved.add(r.id)
        inst.cleared.add(r.id)
        gates = {d.id for d in inst.layout.doors if d.gate and d.rooms[0] == r.id}
        self._set_locked(inst, inst.locked - gates)
        self._broadcast(inst, [EV["DUNGEON"], "solved", r.id])
        for p in self._members(inst):
            self.room.grant_xp(p, self.cfg.xp.puzzle * inst.difficulty)

    # ── using things (levers, chests, the portal) ────────────────────────────
    def use(self, p: Player, index: int) -> None:
        inst = self.of(p)
        if inst is None or p.ko > 0 or not 0 <= index < len(inst.layout.props):
            return
        pr = inst.layout.props[index]
        wx, wy = inst.world(pr.x + 0.5, pr.y + 0.5)
        if (wx - p.m.x) ** 2 + (wy - p.m.y) ** 2 > 2.4**2:
            return
        r = inst.layout.rooms[pr.room]
        if pr.kind == "lever" and r.id not in inst.solved:
            inst.lamps ^= inst.layout.lever_masks[pr.data]
            self._broadcast(inst, [EV["DUNGEON"], "lamps", inst.lamps, index])
            if inst.lamps == 0b111:
                self._solve(inst, r)
        elif pr.kind == "chest" and p.user_id not in inst.chests.setdefault(index, set()):
            inst.chests[index].add(p.user_id)
            tr = self.cfg.treasure
            rng = self.room.rng
            self.room.spawn_drop(p, "coins", rng.randint(*tr.coins) * inst.difficulty, wx, wy + 0.8)
            spec = self.room.cfg.enemies.biomes.get(inst.biome)  # type: ignore[call-overload]
            mats = sorted(
                {d.item for k in (spec.roster if spec else {}) for d in self.room.cfg.enemies.enemies[k].loot}
            )
            for _ in range(tr.rolls):
                if mats:
                    self.room.spawn_drop(p, rng.choice(mats), rng.randint(1, 3), wx, wy + 0.8)
            if rng.random() < tr.rune:
                self.room.spawn_drop(p, "ancient_rune", 1, wx, wy + 0.8)
            if rng.random() < tr.blueprint:
                self.room.spawn_drop(p, rng.choice(self.cfg.blueprints), 1, wx, wy + 0.8)
            p.ev.append([EV["DUNGEON"], "chest", index])
        elif pr.kind == "portal" or (pr.kind == "exit" and inst.boss_dead):
            self.leave(p)

    def portal_at(self, inst: Instance) -> tuple[float, float] | None:
        if not inst.boss_dead:
            return None
        r = next(r for r in inst.layout.rooms if r.kind == "boss")
        return inst.world(r.cx, r.cy + 2)

    def try_portal(self, p: Player) -> bool:
        inst = self.of(p)
        at = self.portal_at(inst) if inst is not None else None
        if at is None or (at[0] - p.m.x) ** 2 + (at[1] - p.m.y) ** 2 > 2.2**2:
            return False
        self.leave(p)
        return True

    # ── lifecycle ────────────────────────────────────────────────────────────
    def drop(self, p: Player) -> None:
        """A member left the room or was knocked out: out of the instance, no teleport."""
        inst = self.of(p)
        if inst is not None and p.ko > 0:
            inst.deaths += 1
        self.leave(p, teleport=False)

    def _close(self, inst: Instance) -> None:
        combat = self.room.combat
        if combat is not None:
            for m in [m for m in combat.monsters.values() if getattr(m, "dungeon", 0) == inst.id]:
                combat._remove(m, killed=False)
        self.instances.pop(inst.id, None)
        self.by_slot.pop(inst.slot, None)
