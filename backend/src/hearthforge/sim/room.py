"""RealmRoom: one per active realm, ticking at 20 Hz (PLAN §2.4, §2.5).

Owns avatars, per-player drops, per-player node depletion and (Phase 5) monsters. Pure-ish: all DB
work goes through `persist.flush`, which runs as its own task once a second (write-behind), so a slow
database never stalls the tick. Drops only exist in memory until granted, so a crash can lose about a
second of pickups but never duplicate anything.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import random
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hearthforge.domain import worldclock
from hearthforge.realtime.protocol import ANIM, ENT, EV, ROOM_LEFT, SELF_FLAG, encode
from hearthforge.sim import motion as mo
from hearthforge.sim import rules as rules_mod
from hearthforge.sim.grid import WorldGrid
from hearthforge.sim.rules import (
    ATK_ABILITY,
    ATK_HEAVY,
    ATK_LIGHT,
    ATK_NONE,
    BTN_OFFHAND,
    BTN_POTION,
    MoveRule,
    Rules,
)
from hearthforge.sim.stats import Stats, add_xp, stats_for, xp_to_next

if TYPE_CHECKING:
    from hearthforge.realtime.conn import Conn
    from hearthforge.state import AppState

log = logging.getLogger("hearthforge.room")

Q = 64  # positions on the wire are 1/64 tile
AOI_X, AOI_Y = 28, 18  # half-extent of the area of interest, tiles
INPUT_RATE = 25.0  # inputs per second, sustained
INPUT_BURST = 25.0
INPUT_QUEUE_MAX = 20  # 1 s of inputs: TCP stalls arrive as bursts, and dropping any desyncs prediction
DROP_PICKABLE_AFTER = 4  # ticks: let the drop pop before it flies to you
EMPTY_ROOM_TTL = 120.0  # seconds a room lingers after its last avatar leaves
STARVE_REPEAT = 4  # ticks without input before others see us as standing still


@dataclass
class Input:
    seq: int
    client_tick: int
    view_tick: int
    mx: int
    my: int
    ax: int
    ay: int
    buttons: int


@dataclass
class Drop:
    id: int
    owner: int  # player entity id
    key: str
    qty: int
    x: float
    y: float
    born: int
    ttl: int  # tick it vanishes
    death_id: uuid.UUID | None = None  # part of a KO marker (persisted in death_drops)


@dataclass
class Pending:
    """Write-behind ops for one player, flushed together in one transaction."""

    grants: Counter[str] = field(default_factory=Counter)
    coins: int = 0
    xp: bool = False
    harvests: list[tuple[int, float]] = field(default_factory=list)  # node_id, respawn epoch s
    consumed: Counter[str] = field(default_factory=Counter)
    removed: Counter[str] = field(default_factory=Counter)  # KO losses
    deposit: bool = False
    save_pos: bool = False
    durability: bool = False  # the equipped weapon wore down
    recovered: Counter[str] = field(default_factory=Counter)  # items picked back up from a KO marker
    death_drops: list[tuple[uuid.UUID, float, float, dict[str, int], float]] = field(default_factory=list)
    recovered_ids: set[uuid.UUID] = field(default_factory=set)
    stats: Counter[str] = field(default_factory=Counter)  # user_stats increments (kills, gathering…)
    fog: bool = False  # newly revealed map chunks to save (Phase 9)
    waystones: set[int] = field(default_factory=set)  # newly attuned waystones (Phase 9)
    pois: dict[str, float] = field(default_factory=dict)  # POI key → when used (Phase 10)
    lore: set[str] = field(default_factory=set)  # lore entries read for the first time

    def empty(self) -> bool:
        return not (
            self.pois
            or self.lore
            or self.stats
            or self.fog
            or self.waystones
            or self.recovered
            or self.durability
            or self.death_drops
            or self.recovered_ids
            or self.grants
            or self.coins
            or self.xp
            or self.harvests
            or self.consumed
            or self.removed
            or self.deposit
            or self.save_pos
        )

    def merge(self, o: Pending) -> None:
        self.grants.update(o.grants)
        self.coins += o.coins
        self.xp |= o.xp
        self.harvests = o.harvests + self.harvests
        self.consumed.update(o.consumed)
        self.removed.update(o.removed)
        self.deposit |= o.deposit
        self.save_pos |= o.save_pos
        self.recovered.update(o.recovered)
        self.death_drops = o.death_drops + self.death_drops
        self.recovered_ids |= o.recovered_ids
        self.durability |= o.durability
        self.stats.update(o.stats)
        self.fog |= o.fog
        self.waystones |= o.waystones
        self.pois = {**o.pois, **self.pois}
        self.lore |= o.lore


@dataclass
class Player:
    eid: int
    user_id: uuid.UUID
    name: str
    appearance: dict[str, Any]
    conn: Conn
    m: mo.Motion
    level: int
    xp: int
    hp: float
    stats: Stats
    weapon: dict[str, Any]
    quick: dict[int, list[Any]]
    inv: list[list[Any]]  # [slot, key, qty, is_instance]
    inv_cap: int
    home_rect: tuple[int, int, int, int]  # buildable square, world tiles
    home_door: tuple[float, float]
    inputs: deque[Input] = field(default_factory=deque)
    last_seq: int = 0
    ack_seq: int = 0
    last_move: tuple[int, int, int, int] = (0, 0, 0, 0)
    view_tick: int = 0
    in_tokens: float = 25.0
    in_last: float = field(default_factory=time.monotonic)
    strikes: int = 0
    depleted: dict[int, float] = field(default_factory=dict)  # node_id → respawn epoch seconds
    node_hits: dict[int, int] = field(default_factory=dict)
    ev: list[list[Any]] = field(default_factory=list)
    pending: Pending = field(default_factory=Pending)
    last_combat: int = -10_000  # tick of the last damage dealt or taken
    iframes: int = 0
    ko: int = 0  # ticks until respawn
    poison: int = 0  # ticks left
    rooted: int = 0  # ticks left: a summoner's root circle holds you in place (Phase 10)
    poison_dps: float = 0.0
    potion_cd: int = 0
    toast_cd: dict[str, int] = field(default_factory=dict)
    hits_done: set[tuple[int, int]] = field(default_factory=set)  # (attack serial, target) this swing
    atk_serial: int = 0
    dirty: asyncio.Event = field(default_factory=asyncio.Event)
    writer: asyncio.Task[None] | None = None
    deposit_wait: int = 0
    armour: int = 0  # defence from equipped armour
    linkdead: int = 0  # ticks left of the reconnect grace (frozen + invulnerable)
    starved: int = 0  # ticks in a row with no input
    last_save: float = field(default_factory=time.monotonic)
    fog: bytearray | None = None  # revealed chunks in this realm (Phase 9)
    fog_chunk: tuple[int, int] = (-1, -1)
    attuned: set[int] = field(default_factory=set)  # waystones this player can travel to
    pois: dict[str, float] = field(default_factory=dict)  # POIs used: key "x,y" → epoch s (Phase 10)
    blessing: tuple[str, int] | None = None  # shrine blessing key, tick it ends
    # Phase 11
    offhand: dict[str, Any] = field(default_factory=dict)  # {key, type, tier, rarity, modifiers}
    armour_key: str | None = None
    blocking: bool = False
    prev_buttons: int = 0
    charges: int = 0  # bombs
    recharge_at: int = 0  # tick the next bomb charge comes back
    offhand_ready: int = 0  # tick the tome can cast again
    food: tuple[str, float, int] | None = None  # buff, value, tick it ends
    regen_until: int = 0  # stamina potion's regen boost
    use_ready: dict[str, int] = field(default_factory=dict)  # cooldown group → tick it's ready
    mods: tuple[float, float, float] = (1.0, 1.0, 1.0)  # speed, dodge, stamina regen
    rules: Rules | None = None  # per-player movement rules when mods aren't all 1
    party: str | None = None  # party id (in memory, D-025)

    @property
    def w(self) -> str:
        return self.weapon["type"]

    def flags(self, tick: int, combat_lock: int) -> int:
        f = 0
        if self.iframes > 0 or self.m.dodge > 0 or self.linkdead > 0:
            f |= SELF_FLAG["iframes"]
        if self.ko > 0:
            f |= SELF_FLAG["ko"]
        if tick - self.last_combat < combat_lock:
            f |= SELF_FLAG["in_combat"]
        if self.poison > 0:
            f |= SELF_FLAG["poisoned"]
        if self.rooted > 0:
            f |= SELF_FLAG["rooted"]
        return f


class RealmRoom:
    def __init__(self, st: AppState, realm_id: uuid.UUID, seed: int) -> None:
        from hearthforge.sim import rules as rules_mod

        self.st = st
        self.cfg = st.config
        self.realm_id = realm_id
        self.seed = seed
        self.rules: Rules = rules_mod.resolve(self.cfg)
        self.hz = self.rules.hz
        self.grid = WorldGrid(self.cfg, seed)
        self.tick_no = 0
        self.players: dict[int, Player] = {}
        self.by_user: dict[uuid.UUID, Player] = {}
        self.drops: dict[int, Drop] = {}
        self.villages: dict[str, dict[str, Any]] = {}  # owner id → village state (for blocks)
        self.claimed: set[int] = set()
        self.rng = random.Random()
        self._next_id = 1
        self._task: asyncio.Task[None] | None = None
        self._prefetch_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_lock = asyncio.Lock()
        self.empty_since: float | None = time.monotonic()
        self.closed = False
        c = self.cfg.combat
        self.combat_lock = int(c.combat_lock * self.hz + 0.5)
        self.regen_delay = int(self.cfg.avatar.regen.delay * self.hz + 0.5)
        self.tick_ms_samples: deque[float] = deque(maxlen=200)
        self.combat: Any = None  # Phase 5: sim.combat.Combat (monsters, hits, loot)
        self.weather_seed = 0  # the realm's weather timeline (Phase 10), set by the manager

    # ── lifecycle ────────────────────────────────────────────────────────────
    def new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name=f"room-{self.realm_id}")
            self._prefetch_task = asyncio.create_task(self.prefetch(), name=f"prefetch-{self.realm_id}")

    async def prefetch(self, radius: int = 3) -> None:
        """Generate map chunks around avatars on a worker thread, so a tick never pays ~45 ms for one."""
        loop = asyncio.get_running_loop()
        gen = self.grid.gen
        cs = self.grid.cs
        n = self.grid.size // cs
        while not self.closed:
            await asyncio.sleep(0.4)
            want = []
            for p in list(self.players.values()):
                pcx, pcy = int(p.m.x) // cs, int(p.m.y) // cs
                for cy in range(max(0, pcy - radius), min(n, pcy + radius + 1)):
                    for cx in range(max(0, pcx - radius), min(n, pcx + radius + 1)):
                        if (cx, cy) not in gen._chunks:
                            want.append((abs(cx - pcx) + abs(cy - pcy), cx, cy))
            for _d, cx, cy in sorted(want)[:6]:
                with contextlib.suppress(Exception):
                    await loop.run_in_executor(None, gen.chunk, cx, cy)

    async def stop(self) -> None:
        self.closed = True
        for p in list(self.players.values()):
            await self.remove_player(p, ROOM_LEFT["shutdown"])
        for task in (self._task, self._prefetch_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        await self.flush()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        period = 1.0 / self.hz
        nxt = loop.time()
        while not self.closed:
            nxt += period
            t0 = time.perf_counter()
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - one bad tick must not kill the realm
                log.exception("tick %s failed in realm %s", self.tick_no, self.realm_id)
            self.tick_ms_samples.append((time.perf_counter() - t0) * 1000)
            if self.tick_no % self.hz == 0 and (self._flush_task is None or self._flush_task.done()):
                self._flush_task = asyncio.create_task(self.flush())
            delay = nxt - loop.time()
            if delay < -0.25:  # fell far behind (debugger, GC): don't try to catch up in a burst
                nxt = loop.time()
                delay = 0
            await asyncio.sleep(max(0.0, delay))

    # ── villages / blocks ────────────────────────────────────────────────────
    def set_villages(self, states: dict[str, dict[str, Any]], claimed: set[int]) -> None:
        from hearthforge.domain.blocks import village_blocks

        self.villages = states
        self.claimed = claimed
        rects = [r for s in states.values() for r in village_blocks(self.cfg, s)]
        self.grid.set_blocks(rects, claimed)

    def update_village(self, owner_id: str, state: dict[str, Any]) -> None:
        if owner_id not in self.villages:
            return
        old = self.grid.block_rects
        self.set_villages({**self.villages, owner_id: state}, self.claimed)
        if self.grid.block_rects != old:
            frame = encode("BLOCKS", self.grid.block_rects, sorted(self.claimed))
            for p in self.players.values():
                asyncio.create_task(self._send(p, frame))

    # ── players ──────────────────────────────────────────────────────────────
    def add_player(self, p: Player) -> None:
        assert p.user_id not in self.by_user, "use reattach() for a returning player"
        self.players[p.eid] = p
        self.by_user[p.user_id] = p
        self.empty_since = None
        p.writer = asyncio.create_task(self._writer(p), name=f"writer-{p.eid}")
        info = self.roster_entry(p)
        for o in self.players.values():
            if o is not p:
                o.ev.append([EV["PLAYER"], *info])

    def reattach(self, p: Player, conn: Conn) -> None:
        """Same user again (reconnect within the grace, or a second tab): keep the avatar, swap the socket."""
        old = p.conn
        p.conn = conn
        p.linkdead = 0
        p.inputs.clear()
        p.last_seq = 0
        p.ack_seq = 0
        if old is not conn:
            asyncio.create_task(self._send_raw(old, encode("ROOM_LEFT", ROOM_LEFT["replaced"])))

    def disconnect(self, p: Player) -> None:
        if self.players.get(p.eid) is p:
            p.linkdead = self.hz * 5
            p.pending.save_pos = True

    @staticmethod
    async def _send_raw(conn: Conn, frame: bytes) -> None:
        with contextlib.suppress(Exception):
            await conn.send_bytes(frame)

    def roster_entry(self, p: Player) -> list[Any]:
        return [p.eid, str(p.user_id), p.name, p.appearance, p.w, p.level]

    def joined_frame(self, p: Player) -> bytes:
        now = time.time()
        depleted = [[nid, max(0, int((t - now) * 1000))] for nid, t in p.depleted.items() if t > now]
        info = self.player_info(p)
        return encode(
            "ROOM_JOINED",
            str(self.realm_id),
            self.tick_no,
            p.eid,
            self.self_state(p),
            info,
            self.grid.block_rects,
            sorted(self.claimed),
            depleted,
            [self.roster_entry(o) for o in self.players.values()],
        )

    def player_info(self, p: Player) -> dict[str, Any]:
        return {
            "level": p.level,
            "xp": p.xp,
            "xp_next": xp_to_next(self.cfg, p.level),
            "hp_max": p.stats.hp_max,
            "attack": p.stats.attack,
            "defence": p.stats.defence + p.armour,
            "weapon": p.weapon,
            "offhand": p.offhand,
            "mods": list(p.mods),
            "quick": {str(k): v for k, v in p.quick.items()},
            "inv": p.inv,
            "inv_capacity": p.inv_cap,
            "home": {"rect": list(p.home_rect), "door": list(p.home_door)},
            "hz": self.hz,
        }

    async def remove_player(self, p: Player, reason: int) -> None:
        if self.players.get(p.eid) is not p:
            return
        del self.players[p.eid]
        if self.by_user.get(p.user_id) is p:
            del self.by_user[p.user_id]
        for d in [d for d in self.drops.values() if d.owner == p.eid]:
            del self.drops[d.id]
        if p.writer:
            p.writer.cancel()
        p.pending.save_pos = True
        if self.st.rooms is not None:
            self.st.rooms.leave_party(p.user_id)
        for o in self.players.values():
            o.ev.append([EV["PLAYER_LEFT"], p.eid])
        with contextlib.suppress(Exception):
            await p.conn.send_bytes(encode("ROOM_LEFT", reason))
        await self.flush_player(p)
        if not self.players:
            self.empty_since = time.monotonic()

    async def _send(self, p: Player, frame: bytes) -> None:
        with contextlib.suppress(Exception):
            await p.conn.send_bytes(frame)

    async def _writer(self, p: Player) -> None:
        """Latest-wins sender: a slow socket skips snapshots, but events accumulate into the next one."""
        try:
            while True:
                await p.dirty.wait()
                p.dirty.clear()
                frame = self.snapshot(p)
                try:
                    await p.conn.send_bytes(frame)
                except Exception:  # noqa: BLE001
                    return
        except asyncio.CancelledError:
            return

    def on_input(self, p: Player, f: list[Any]) -> bool:
        """Validate and queue one INPUT. False = protocol violation (the caller counts strikes)."""
        ok = self._accept_input(p, f)
        if not ok:
            log.debug("rejected input from %s: %r (last seq %s)", p.name, f, p.last_seq)
        return ok

    def _accept_input(self, p: Player, f: list[Any]) -> bool:
        if len(f) != 8 or not all(isinstance(v, int) and not isinstance(v, bool) for v in f):
            return False
        seq, ct, vt, mx, my, ax, ay, b = f
        lim = self.rules.input_max
        if seq <= p.last_seq or not all(-lim <= v <= lim for v in (mx, my, ax, ay)) or not 0 <= b < 1 << 16:
            return False
        # token bucket: 25 inputs/s sustained (PLAN §2.5), with a 1 s burst so a TCP stall that releases
        # a clump of inputs never loses one (a lost input = a visible correction)
        now = time.monotonic()
        p.in_tokens = min(INPUT_BURST, p.in_tokens + (now - p.in_last) * INPUT_RATE)
        p.in_last = now
        if p.in_tokens < 1.0:
            return False
        p.in_tokens -= 1.0
        p.last_seq = seq
        p.inputs.append(Input(seq, ct, vt, mx, my, ax, ay, b))
        while len(p.inputs) > INPUT_QUEUE_MAX:
            p.inputs.popleft()
        return True

    # ── the tick ─────────────────────────────────────────────────────────────
    def tick(self) -> None:
        self.tick_no += 1
        t = self.tick_no
        solid = self.grid.solid
        for p in list(self.players.values()):
            if p.linkdead > 0:
                p.linkdead -= 1
                p.inputs.clear()
                if p.linkdead == 0:
                    asyncio.create_task(self.remove_player(p, ROOM_LEFT["left"]))
                continue
            if p.ko > 0:
                p.ko -= 1
                p.inputs.clear()
                if p.ko == 0:
                    self.respawn(p)
                continue
            # one input per tick, two or three while catching up. A tick with no input doesn't step the
            # avatar at all: the client predicted nothing for it, so stepping would desync prediction.
            n = 3 if len(p.inputs) > 6 else 2 if len(p.inputs) > 2 else 1
            for _ in range(n):
                if not p.inputs:
                    p.starved += 1
                    if p.starved > STARVE_REPEAT:
                        p.last_move = (0, 0, p.last_move[2], p.last_move[3])
                    break
                inp = p.inputs.popleft()
                p.starved = 0
                p.ack_seq = inp.seq
                p.view_tick = inp.view_tick
                p.last_move = (inp.mx, inp.my, inp.ax, inp.ay)
                self.step_player(p, inp.mx, inp.my, inp.ax, inp.ay, inp.buttons, solid)
            self.player_timers(p, t)
        if self.combat is not None:
            self.combat.tick(t)
        self.tick_drops(t)
        if t % self.hz == 0:
            self.tick_nodes()
            if self.st.rooms is not None:
                self.st.rooms.party_tick(self)
        for p in self.players.values():
            p.dirty.set()

    def step_player(self, p: Player, mx: int, my: int, ax: int, ay: int, b: int, solid: mo.Solid) -> None:
        r = p.rules or self.rules
        w = r.weapons[p.w]
        if p.rooted > 0:
            mx = my = 0  # rooted: you can still swing, aim and drink, just not walk
        started = mo.step(p.m, mx, my, ax, ay, b, r, w, solid)
        if started:
            p.atk_serial += 1
            p.hits_done.clear()
            mv = mo.current_move(p.m, w)
            assert mv is not None
            ev = [EV["SWING"], p.eid, started, p.m.atk_i, round(p.m.ax * 100), round(p.m.ay * 100)]
            for o in self.players.values():
                if o is not p:
                    o.ev.append(ev)
        if p.m.atk != ATK_NONE:
            mv = mo.current_move(p.m, w)
            if mv is not None and self.is_hit_tick(mv, p.m.atk_t):
                self.resolve_attack(p, mv)
        if b & BTN_POTION:
            self.use_potion(p)
        self.offhand_input(p, b)
        p.prev_buttons = b

    @staticmethod
    def is_hit_tick(mv: MoveRule, t: int) -> bool:
        if mv.hits > 1:
            k = t - mv.windup
            return 0 <= k < mv.hits * mv.interval and k % mv.interval == 0
        return t == mv.windup

    def player_timers(self, p: Player, t: int) -> None:
        if p.iframes > 0:
            p.iframes -= 1
        if p.potion_cd > 0:
            p.potion_cd -= 1
        if p.rooted > 0:
            p.rooted -= 1
        if t % self.hz == 0:
            self.tick_buffs(p, t)
        if p.poison > 0:
            p.poison -= 1
            if t % self.hz == 0 and self.combat is not None:
                self.combat.poison_tick(p)
        elif t - p.last_combat > self.regen_delay and p.hp < p.stats.hp_max and t % 5 == 0:
            p.hp = min(
                float(p.stats.hp_max), p.hp + p.stats.hp_max * self.cfg.avatar.regen.per_second * 5 / self.hz
            )
        if p.deposit_wait > 0:
            p.deposit_wait -= 1
        elif t % 10 == 0 and self.in_home(p) and not p.pending.deposit and self.has_resources(p):
            p.pending.deposit = True
            p.deposit_wait = self.hz * 2
        if t % 5 == 0:
            self.explore(p)

    # ── exploration: fog of war and waystones (Phase 9) ──────────────────────
    def explore(self, p: Player) -> None:
        from hearthforge.services import world as world_svc

        cs = self.cfg.mapgen.chunk_size
        chunk = (int(p.m.x) // cs, int(p.m.y) // cs)
        if p.fog is not None and chunk != p.fog_chunk:
            p.fog_chunk = chunk
            if world_svc.reveal(self.cfg, p.fog, chunk[0], chunk[1], self.cfg.social.fog.reveal_radius):
                p.pending.fog = True
        r2 = self.cfg.social.waystone.attune_radius**2
        for w in self.grid.gen.waystones:
            if w.index not in p.attuned and (w.x + 0.5 - p.m.x) ** 2 + (w.y + 0.5 - p.m.y) ** 2 <= r2:
                p.attuned.add(w.index)
                p.pending.waystones.add(w.index)
                p.ev.append([EV["WAYSTONE"], w.index, w.name, sorted(p.attuned)])

    def travel(self, p: Player, index: int) -> str | None:
        """Fast travel between attuned waystones (P12). Returns an error code or None."""
        if p.ko > 0:
            return "ko"
        if self.tick_no - p.last_combat < self.combat_lock:
            return "in_combat"
        stones = {w.index: w for w in self.grid.gen.waystones}
        dest = stones.get(index)
        if dest is None or index not in p.attuned:
            return "not_attuned"
        r2 = self.cfg.social.waystone.use_radius**2
        if not any(
            w.index in p.attuned and (w.x + 0.5 - p.m.x) ** 2 + (w.y + 0.5 - p.m.y) ** 2 <= r2
            for w in stones.values()
        ):
            return "not_at_waystone"
        for dx, dy in ((0, 1), (1, 1), (-1, 1), (1, 0), (-1, 0), (0, 2), (0, -1)):
            x, y = dest.x + dx, dest.y + dy
            if not self.grid.solid(x, y):
                p.m.x, p.m.y = x + 0.5, y + 0.5
                break
        p.m.dodge = 0
        p.m.atk = ATK_NONE
        p.inputs.clear()
        p.iframes = self.hz  # a moment to get your bearings
        p.pending.save_pos = True
        p.ev.append([EV["TELEPORT"], p.m.x, p.m.y, index])
        return None

    # ── points of interest (Phase 10) ────────────────────────────────────────
    def blessing(self, p: Player, stat: str) -> float:
        """The active shrine blessing's bonus for `stat` (damage | defence | coins), else 0."""
        if p.blessing is None or p.blessing[1] <= self.tick_no:
            return 0.0
        b = self.cfg.pois.shrines.blessings.get(p.blessing[0])
        return float(getattr(b, stat, 0.0)) if b else 0.0

    def restore_blessing(self, p: Player) -> None:
        """Back in the world within a blessing's duration: it's still on you."""
        sh = self.cfg.pois.shrines
        now = time.time()
        for poi in self.grid.gen.pois:
            at = p.pois.get(poi.key)
            if poi.kind == "shrine" and at is not None and now - at < sh.duration:
                keys = list(sh.blessings)
                p.blessing = (
                    keys[poi.variant % len(keys)],
                    self.tick_no + int((sh.duration - (now - at)) * self.hz),
                )

    def interact(self, p: Player, index: int) -> None:
        pc = self.cfg.pois
        pois = self.grid.gen.pois
        if p.ko > 0 or not 0 <= index < len(pois):
            return
        poi = pois[index]
        if (poi.x + 0.5 - p.m.x) ** 2 + (poi.y + 0.5 - p.m.y) ** 2 > (pc.interact_radius + 0.75) ** 2:
            self.toast(p, "poi_too_far")
            return
        now = time.time()
        used = p.pois.get(poi.key)

        def mark() -> None:
            p.pois[poi.key] = now
            p.pending.pois[poi.key] = now

        data: dict[str, Any] = {}
        if poi.kind == "ruins":
            if used is not None:
                self.toast(p, "chest_empty")
                return
            ch = pc.chests[poi.biome]  # type: ignore[index]
            loot: dict[str, int] = {}
            coins = self.rng.randint(*ch.coins)
            pool = list(ch.pool.items())
            for _ in range(ch.rolls):
                k, (lo, hi) = pool[self.rng.randrange(len(pool))]
                loot[k] = loot.get(k, 0) + self.rng.randint(lo, hi)
            for k, chance in ch.rare.items():
                if self.rng.random() < chance:
                    loot[k] = loot.get(k, 0) + 1
            self.spawn_drop(p, "coins", coins, poi.x + 0.5, poi.y + 0.9)
            for k, q in loot.items():
                self.spawn_drop(p, k, q, poi.x + 0.5, poi.y + 0.9)
            mark()
            p.pending.stats["poi.chest"] += 1
            data = {"coins": coins, "loot": loot}
        elif poi.kind == "shrine":
            sh = pc.shrines
            if used is not None and now - used < sh.cooldown:
                self.toast(p, "shrine_resting", {"minutes": int((sh.cooldown - (now - used)) // 60) + 1})
                return
            keys = list(sh.blessings)
            key = keys[poi.variant % len(keys)]
            b = sh.blessings[key]
            p.blessing = (key, self.tick_no + int(sh.duration * self.hz))
            mark()
            p.pending.stats["poi.shrine"] += 1
            data = {"blessing": key, "name": b.name, "text": b.text, "secs": int(sh.duration)}
        elif poi.kind == "lore_stone":
            entries = pc.lore[poi.biome]  # type: ignore[index]
            i = poi.variant % len(entries)
            e = entries[i]
            first = used is None
            if first:
                mark()
                p.pending.lore.add(f"{poi.biome}:{i}")
                p.pending.stats["lore.read"] += 1
                self.grant_xp(p, pc.lore_xp)
            data = {"title": e.title, "text": e.text, "first": first, "xp": pc.lore_xp if first else 0}
        elif poi.kind == "lost_villager":
            if used is not None:
                self.toast(p, "villager_home")
                return
            lv = pc.lost_villager
            name = lv.names[poi.variant % len(lv.names)]
            coins = self.rng.randint(*lv.coins)
            self.spawn_drop(p, "coins", coins, poi.x + 0.5, poi.y + 0.9)
            self.grant_xp(p, lv.xp)
            mark()
            p.pending.stats["villagers.found"] += 1
            data = {"name": name, "coins": coins}
        else:  # cave (sealed for now) or a trader's stall: remembered for the map
            if used is None:
                mark()
            if poi.kind == "merchant":
                data = {"merchant_id": f"wild:{index}"}
        p.ev.append([EV["POI"], index, poi.kind, data])

    def in_home(self, p: Player) -> bool:
        x, y, w, h = p.home_rect
        return x <= p.m.x < x + w and y <= p.m.y < y + h

    def has_resources(self, p: Player) -> bool:
        res = self.cfg.resources.resources
        return any(s[1] in res and not s[3] for s in p.inv)

    # ── attacks: gathering here, monsters in Phase 5 (sim.combat) ───────────
    def resolve_attack(self, p: Player, mv: MoveRule) -> None:
        if self.combat is not None and self.combat.player_attack(p, mv):
            return
        if mv.shape in ("arc", "line", "circle"):
            self.gather(p, mv)

    def in_shape(self, p: Player, mv: MoveRule, tx: float, ty: float, pad: float) -> bool:
        dx, dy = tx - p.m.x, ty - p.m.y
        d2 = dx * dx + dy * dy
        reach = mv.range + pad
        if d2 > reach * reach:
            return False
        if mv.shape in ("spin", "throw", "circle") or d2 < 1e-9:
            return True
        along = dx * p.m.ax + dy * p.m.ay
        if mv.shape == "line":
            across = abs(dx * -p.m.ay + dy * p.m.ax)
            return -pad <= along <= reach and across <= mv.width / 2 + pad
        half = math.radians(mv.arc) / 2
        return along >= math.sqrt(d2) * math.cos(min(math.pi, half + 0.35))

    def world_now(self) -> tuple[bool, str]:
        """(is it night, current weather) for this realm — pure functions of the clock (P9)."""
        wc = self.cfg.world_clock
        t = self.st.clock.now()
        return worldclock.is_night(wc, t), worldclock.weather_at(wc, self.weather_seed, t)

    def gather(self, p: Player, mv: MoveRule) -> None:
        best: tuple[float, int, int, str] | None = None
        r = int(mv.range + 2)
        cx, cy = int(p.m.x), int(p.m.y)
        now = time.time()
        night, weather = self.world_now()
        nodes = self.cfg.nodes.nodes
        for ty in range(cy - r, cy + r + 1):
            for tx in range(cx - r, cx + r + 1):
                key = self.grid.node_at(tx, ty)
                if key is None:
                    continue
                if nodes[key].night_only and not night:
                    continue  # moonpetals only open at night (the client hides them by day)
                nid = self.grid.node_id(tx, ty)
                if p.depleted.get(nid, 0) > now:
                    continue
                if not self.in_shape(p, mv, tx + 0.5, ty + 0.5, 0.55):
                    continue
                d = (tx + 0.5 - p.m.x) ** 2 + (ty + 0.5 - p.m.y) ** 2
                if best is None or d < best[0]:
                    best = (d, tx, ty, key)
        if best is None:
            return
        _, tx, ty, key = best
        node = self.cfg.nodes.nodes[key]
        nid = self.grid.node_id(tx, ty)
        hits = p.node_hits.get(nid, 0) + 1
        if hits < node.hits:
            p.node_hits[nid] = hits
            p.ev.append([EV["NODE"], nid, hits, node.hits, 0, 0, node.sound])
            return
        p.node_hits.pop(nid, None)
        respawn_at = now + node.respawn
        p.depleted[nid] = respawn_at
        p.pending.harvests.append((nid, respawn_at))
        p.ev.append([EV["NODE"], nid, node.hits, node.hits, 1, int(node.respawn * 1000), node.sound])
        loot: dict[str, int] = {}
        ws = self.cfg.world_clock.weather.states.get(weather)
        boost = ws.rare_node.get(key, 1.0) if ws else 1.0  # e.g. snow → frost spires give 1.5×
        for k, (lo, hi) in node.yields.items():
            q = self.rng.randint(lo, hi)
            loot[k] = int(q * boost + self.rng.random()) if boost != 1.0 else q
        for k, b in node.bonus.items():
            if self.rng.random() < min(1.0, b.chance * boost):
                loot[k] = loot.get(k, 0) + self.rng.randint(*b.qty)
        nx, ny = tx + 0.5, ty + 0.5
        for k, q in loot.items():
            if q > 0:
                self.spawn_drop(p, k, q, nx + (p.m.x - nx) * 0.4, ny + (p.m.y - ny) * 0.4)
        self.grant_xp(p, node.xp)

    # ── drops ────────────────────────────────────────────────────────────────
    def spawn_drop(
        self,
        p: Player,
        key: str,
        qty: int,
        x: float,
        y: float,
        ttl_s: float = 120,
        death_id: uuid.UUID | None = None,
    ) -> Drop:
        d = Drop(
            self.new_id(),
            p.eid,
            key,
            qty,
            x + self.rng.uniform(-0.35, 0.35),
            y + self.rng.uniform(-0.35, 0.35),
            self.tick_no,
            self.tick_no + int(ttl_s * self.hz),
            death_id,
        )
        self.drops[d.id] = d
        return d

    def tick_drops(self, t: int) -> None:
        r2 = self.cfg.avatar.pickup_radius**2
        for d in list(self.drops.values()):
            if t >= d.ttl:
                del self.drops[d.id]
                continue
            p = self.players.get(d.owner)
            if p is None or p.ko > 0 or t - d.born < DROP_PICKABLE_AFTER:
                continue
            if (d.x - p.m.x) ** 2 + (d.y - p.m.y) ** 2 > r2:
                continue
            if d.key == "coins":
                p.pending.coins += d.qty
            else:
                fit = self.inv_fit(p, d.key, d.qty)
                if fit <= 0:
                    self.toast(p, "bag_full")
                    continue
                self.inv_add(p, d.key, fit)
                if d.death_id is not None:
                    p.pending.recovered[d.key] += fit
                else:
                    p.pending.grants[d.key] += fit
                    p.pending.stats[f"gather.{d.key}"] += fit
                p.ev.append([EV["INVENTORY"], p.inv])
                if fit < d.qty:
                    d.qty -= fit
                    p.ev.append([EV["PICKUP"], d.id, d.key, fit, 0])
                    self.toast(p, "bag_full")
                    continue
            del self.drops[d.id]
            p.ev.append([EV["PICKUP"], d.id, d.key, d.qty, 1])
            if d.death_id is not None and not any(o.death_id == d.death_id for o in self.drops.values()):
                p.pending.recovered_ids.add(d.death_id)

    def toast(self, p: Player, key: str, args: dict[str, Any] | None = None) -> None:
        if p.toast_cd.get(key, 0) > self.tick_no:
            return
        p.toast_cd[key] = self.tick_no + self.hz * 4
        p.ev.append([EV["TOAST"], key, args or {}])

    # inventory mirror (same ordering rules as services.inventory)
    def inv_fit(self, p: Player, key: str, qty: int) -> int:
        info = self.cfg.items[key]
        room = sum(info.max_stack - s[2] for s in p.inv if s[1] == key and not s[3] and s[2] < info.max_stack)
        room += (p.inv_cap - len(p.inv)) * info.max_stack
        return min(qty, room)

    def inv_add(self, p: Player, key: str, qty: int) -> None:
        info = self.cfg.items[key]
        left = qty
        for s in sorted(p.inv, key=lambda s: s[0]):
            if left <= 0:
                break
            if s[1] == key and not s[3] and s[2] < info.max_stack:
                n = min(left, info.max_stack - s[2])
                s[2] += n
                left -= n
        used = {s[0] for s in p.inv}
        for i in range(p.inv_cap):
            if left <= 0:
                break
            if i not in used:
                n = min(left, info.max_stack)
                p.inv.append([i, key, n, False])
                left -= n
        p.inv.sort(key=lambda s: s[0])

    def inv_remove(self, p: Player, key: str, qty: int) -> int:
        left = qty
        for s in sorted(p.inv, key=lambda s: -s[0]):
            if left <= 0:
                break
            if s[1] == key and not s[3]:
                n = min(left, s[2])
                s[2] -= n
                left -= n
        p.inv[:] = [s for s in p.inv if s[2] > 0]
        return qty - left

    def inv_count(self, p: Player, key: str) -> int:
        return sum(s[2] for s in p.inv if s[1] == key and not s[3])

    # ── nodes, xp, potions, KO ──────────────────────────────────────────────
    def tick_nodes(self) -> None:
        now = time.time()
        for p in self.players.values():
            back = [nid for nid, at in p.depleted.items() if at <= now]
            for nid in back:
                del p.depleted[nid]
                p.ev.append([EV["NODE"], nid, 0, 0, 0, 0, ""])

    def grant_xp(self, p: Player, amount: int) -> None:
        if amount <= 0:
            return
        level, xp, gained = add_xp(self.cfg, p.level, p.xp, amount)
        p.level, p.xp = level, xp
        p.pending.xp = True
        if gained:
            p.stats = stats_for(self.cfg, level)
            p.m.st_max = p.stats.st_max
            p.hp = float(p.stats.hp_max)
            p.m.st = p.m.st_max
        p.ev.append([EV["XP"], amount, p.level, p.xp, xp_to_next(self.cfg, p.level), gained, p.stats.hp_max])

    def use_potion(self, p: Player) -> None:
        """The potion button: the first healing potion in your quick-slots."""
        items = self.cfg.items_cfg.items
        for slot in sorted(p.quick):
            it = items.get(p.quick[slot][0])
            if it is not None and it.use is not None and it.use.heal > 0:
                self.use_quick(p, slot - 4)
                return
        self.toast(p, "no_potions")

    def use_quick(self, p: Player, idx: int) -> None:
        """Quick-slot 1–4 (equipment slots 4–7): drink or eat what's there (Phase 11)."""
        slot = 4 + idx
        if p.ko > 0 or slot not in p.quick:
            return
        key, qty = p.quick[slot]
        it = self.cfg.items_cfg.items.get(key)
        if it is None or it.use is None or qty <= 0:
            return
        u = it.use
        t = self.tick_no
        if p.use_ready.get(u.group, 0) > t:
            return
        if u.heal and p.hp >= p.stats.hp_max:
            self.toast(p, "full_hp")
            return
        p.use_ready[u.group] = t + int(u.cooldown * self.hz)
        if u.group == "potion":
            p.potion_cd = int(u.cooldown * self.hz)
        p.quick[slot] = [key, qty - 1]
        if qty - 1 <= 0:
            del p.quick[slot]
        p.pending.consumed[key] += 1
        quick = {str(k): v for k, v in p.quick.items()}
        if u.heal:
            heal = round(p.stats.hp_max * u.heal)
            p.hp = min(float(p.stats.hp_max), p.hp + heal)
            p.ev.append([EV["HEAL"], p.eid, heal, quick])
            return
        if u.stamina:
            p.m.st = min(p.m.st_max, p.m.st + p.m.st_max * u.stamina)
            p.regen_until = t + int(u.duration * self.hz)
        if u.buff:
            p.food = (u.buff, u.value, t + int(u.duration * self.hz))
        p.ev.append([EV["BUFF"], key, u.buff or "stamina", u.value, int(u.duration * 1000), quick])
        self.recompute_mods(p)

    def food(self, p: Player, stat: str) -> float:
        f = p.food
        return f[1] if f is not None and f[0] == stat and f[2] > self.tick_no else 0.0

    def recompute_mods(self, p: Player) -> None:
        """Plate armour, swift food and stamina potions change your own movement rules. The client gets
        the same three numbers (MOVE_MODS) and builds identical rules, so prediction stays exact."""
        am = self.cfg.combat.armour_move.get(p.armour_key or "")
        speed = (am.speed if am else 1.0) * (1 + self.food(p, "speed"))
        dodge = am.dodge if am else 1.0
        regen = 1.5 if p.regen_until > self.tick_no else 1.0
        mods = (speed, dodge, regen)
        if mods != p.mods:
            p.mods = mods
            p.rules = rules_mod.scaled(self.rules, *mods) if mods != (1.0, 1.0, 1.0) else None
            p.ev.append([EV["MOVE_MODS"], *mods])

    def tick_buffs(self, p: Player, t: int) -> None:
        changed = False
        if p.food is not None and p.food[2] <= t:
            p.food = None
            changed = True
        if p.regen_until and p.regen_until <= t:
            p.regen_until = 0
            changed = True
        if changed:
            self.recompute_mods(p)
        if p.offhand.get("type") == "bombs":
            full = self.cfg.combat.offhands.bombs.charges
            if p.charges < full and p.recharge_at and p.recharge_at <= t:
                p.charges += 1
                p.recharge_at = (
                    t + int(self.cfg.combat.offhands.bombs.recharge * self.hz) if p.charges < full else 0
                )
                self.offhand_state(p)

    # ── offhands (Phase 11, the F key) ───────────────────────────────────────
    def set_offhand(self, p: Player, offhand: dict[str, Any]) -> None:
        if offhand.get("instance_id") != p.offhand.get("instance_id"):
            p.charges = self.cfg.combat.offhands.bombs.charges if offhand.get("type") == "bombs" else 0
            p.recharge_at = 0
            p.offhand_ready = 0
        p.offhand = offhand
        self.offhand_state(p)

    def offhand_state(self, p: Player) -> None:
        ready = max(0, p.offhand_ready - self.tick_no) if p.offhand.get("type") == "tome" else 0
        if p.offhand.get("type") == "bombs" and p.recharge_at:
            ready = max(0, p.recharge_at - self.tick_no)
        p.ev.append([EV["OFFHAND"], p.offhand.get("type") or "", p.charges, int(ready * 1000 / self.hz)])

    def offhand_input(self, p: Player, b: int) -> None:
        kind = p.offhand.get("type")
        held = bool(b & BTN_OFFHAND)
        pressed = held and not p.prev_buttons & BTN_OFFHAND
        if kind == "shield":
            p.blocking = held and p.m.atk == ATK_NONE and p.m.dodge == 0 and p.ko == 0
            return
        p.blocking = False
        if not pressed or p.ko > 0 or self.combat is None or p.m.dodge > 0:
            return
        t = self.tick_no
        if kind == "bombs":
            if p.charges <= 0:
                self.toast(p, "no_bombs")
                return
            self.combat.throw_bomb(p)
            p.charges -= 1
            if not p.recharge_at:
                p.recharge_at = t + int(self.cfg.combat.offhands.bombs.recharge * self.hz)
            p.last_combat = t
            self.offhand_state(p)
        elif kind == "tome":
            if p.offhand_ready > t:
                return
            self.combat.cast_tome(p)
            p.offhand_ready = t + int(self.cfg.combat.offhands.tome.cooldown * self.hz)
            p.last_combat = t
            self.offhand_state(p)

    def respawn(self, p: Player) -> None:
        p.m = mo.Motion(x=p.home_door[0], y=p.home_door[1], st=p.stats.st_max, st_max=p.stats.st_max)
        p.hp = float(p.stats.hp_max)
        p.iframes = self.hz * 2
        p.poison = 0
        p.inputs.clear()
        p.ev.append([EV["RESPAWN"], p.m.x, p.m.y])

    # ── snapshots ────────────────────────────────────────────────────────────
    def self_state(self, p: Player) -> list[Any]:
        return [*p.m.to_list(), round(p.hp, 1), p.stats.hp_max, p.flags(self.tick_no, self.combat_lock)]

    def snapshot(self, p: Player) -> bytes:
        x0, x1, y0, y1 = p.m.x - AOI_X, p.m.x + AOI_X, p.m.y - AOI_Y, p.m.y + AOI_Y
        ents: list[list[Any]] = []
        for o in self.players.values():
            if o is p or not (x0 <= o.m.x <= x1 and y0 <= o.m.y <= y1):
                continue
            ents.append(self.avatar_ent(o))
        for d in self.drops.values():
            if d.owner == p.eid and x0 <= d.x <= x1 and y0 <= d.y <= y1:
                ents.append([d.id, ENT["drop"], d.key, round(d.x * Q), round(d.y * Q), 0, 0, 0, 0, 0, d.qty])
        if self.combat is not None:
            ents.extend(self.combat.entities(p, x0, x1, y0, y1))
        ev, p.ev = p.ev, []
        return encode("SNAPSHOT", self.tick_no, p.ack_seq, self.self_state(p), ents, ev)

    def avatar_ent(self, o: Player) -> list[Any]:
        m = o.m
        if o.ko > 0:
            anim, at = ANIM["ko"], 0
        elif m.dodge > 0:
            anim, at = ANIM["dodge"], m.dodge
        elif m.atk != ATK_NONE:
            anim, at = ANIM["attack"], m.atk_t
        elif o.last_move[0] or o.last_move[1]:
            anim, at = ANIM["walk"], 0
        else:
            anim, at = ANIM["idle"], 0
        hp_pct = int(255 * max(0.0, o.hp) / o.stats.hp_max)
        return [
            o.eid,
            ENT["avatar"],
            o.w,
            round(m.x * Q),
            round(m.y * Q),
            round(m.fx * 100),
            round(m.fy * 100),
            anim,
            at,
            hp_pct,
            o.flags(self.tick_no, self.combat_lock),
        ]

    # ── persistence ──────────────────────────────────────────────────────────
    async def flush(self) -> None:
        async with self._flush_lock:
            for p in list(self.players.values()):
                await self._flush_one(p)

    async def flush_player(self, p: Player) -> None:
        async with self._flush_lock:
            await self._flush_one(p)

    async def _flush_one(self, p: Player) -> None:
        from hearthforge.sim import persist

        if time.monotonic() - p.last_save > 30:
            p.pending.save_pos = True
        if p.pending.empty():
            return
        if p.pending.save_pos:
            p.last_save = time.monotonic()
        ops, p.pending = p.pending, Pending()
        try:
            result = await persist.flush_player(self, p, ops)
        except Exception:  # noqa: BLE001 - keep the ops and retry next second
            log.exception("flush failed for %s", p.user_id)
            ops.merge(p.pending)
            p.pending = ops
            return
        persist.apply_result(self, p, result)

    def bench_stats(self) -> dict[str, float]:
        s = sorted(self.tick_ms_samples)
        if not s:
            return {}
        return {"p50": s[len(s) // 2], "p99": s[int(len(s) * 0.99) - 1], "max": s[-1]}


__all__ = ["ATK_ABILITY", "ATK_HEAVY", "ATK_LIGHT", "Drop", "Input", "Pending", "Player", "RealmRoom"]
