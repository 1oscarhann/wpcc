"""Phase 5 combat inside a RealmRoom: monster spawning and AI with telegraphed attacks, player hits with
lag compensation, dodge grace, damage/defence, knockback, poison, per-player loot, XP and KO.

Favour the player (D-009): player hits are checked where the monster *was* on the player's screen
(≤ 200 ms back); monster hits wait 100 ms and are cancelled by a dodge that started in that window.
"""

from __future__ import annotations

import math
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hearthforge.domain import forging, worldclock
from hearthforge.domain.mapgen import _mix, rand01
from hearthforge.realtime.protocol import ANIM, ENT, EV
from hearthforge.sim import motion as mo
from hearthforge.sim.rules import MoveRule

if TYPE_CHECKING:
    from hearthforge.config.schemas import EnemyCfg
    from hearthforge.sim.room import Player, RealmRoom

Q = 64
HISTORY = 8


@dataclass(frozen=True)
class Box:
    hw: float
    hh: float
    skin: float = 0.0001


@dataclass
class SpawnPoint:
    id: int
    x: float
    y: float
    biome: str
    enemy: str
    elite: bool
    count: int
    alive: set[int] = field(default_factory=set)
    respawn_at: int = 0
    night_only: bool = False  # the extra groups that only wake after dark (Phase 10)
    storm_block: int | None = None  # a Storm Elemental's spot, gone when that storm block ends


@dataclass
class Monster:
    id: int
    key: str
    cfg: EnemyCfg
    elite: bool
    spawn: int
    x: float
    y: float
    hx: float  # home
    hy: float
    hp: float
    hp_max: float
    dmg: float
    defence: float
    speed: float  # tiles per tick
    box: Box
    biome: str
    state: str = "idle"
    st_t: int = 0
    target: int | None = None
    dx: float = -1.0  # facing / attack direction (unit)
    dy: float = 0.0
    ox: float = 0.0  # telegraph origin
    oy: float = 0.0
    wx: float = 0.0  # wander target
    wy: float = 0.0
    kbx: float = 0.0
    kby: float = 0.0
    hurt: int = 0
    history: deque[tuple[int, float, float]] = field(default_factory=lambda: deque(maxlen=HISTORY))
    damagers: dict[int, float] = field(default_factory=dict)
    last_near: int = 0
    hit_players: set[int] = field(default_factory=set)
    night: bool = False  # spawned after dark: tougher, better loot (flag 16)
    minion_of: int | None = None  # summoned by this monster: no loot, a share of the XP
    next_summon: int = 0
    backoff: int = 0  # ticks spent backing away from a target (kiters give up and shoot after a while)
    scale: tuple[float, float, float] = (1.0, 1.0, 0.0)  # roaming spawns: the biome's hp/dmg/def scale


@dataclass
class PendingHit:
    resolve: int
    mid: int
    eid: int
    dmg: float
    dx: float
    dy: float
    kb: float
    poison: tuple[float, int] | None
    root: int = 0  # ticks


@dataclass
class Projectile:
    id: int
    owner: int
    x: float
    y: float
    vx: float
    vy: float
    left: float
    mv: MoveRule
    hit: set[int] = field(default_factory=set)


@dataclass
class Shot:
    """A monster's projectile: flies along the telegraphed line, hits the first player it touches."""

    id: int
    mid: int
    key: str  # sprite: arrow | spit | sting | ice | fire | bolt | rock
    x: float
    y: float
    vx: float  # tiles per tick
    vy: float
    left: float
    radius: float
    dmg: float
    kb: float
    poison: tuple[float, int] | None
    chain: int
    chain_radius: float
    chain_dmg: float
    hit: set[int] = field(default_factory=set)  # players it already passed (dodged through)


class Combat:
    def __init__(self, room: RealmRoom) -> None:
        self.room = room
        self.cfg = room.cfg
        self.en = room.cfg.enemies
        self.cb = room.cfg.combat
        self.hz = room.hz
        self.monsters: dict[int, Monster] = {}
        self.spawns: dict[int, SpawnPoint] = {}
        self.chunk_spawns: dict[tuple[int, int], list[int]] = {}
        self.pending: list[PendingHit] = []
        self.projectiles: dict[int, Projectile] = {}
        self.lag_ticks = int(self.cb.lag_comp_max * self.hz + 0.5)
        self.grace = max(1, int(self.cb.dodge_grace * self.hz + 0.5))
        self.respawn_ticks = int(self.en.respawn * self.hz)
        self.despawn_ticks = int(self.en.despawn_after * self.hz)
        self.ko_ticks = int(self.cfg.avatar.ko.respawn_delay * self.hz)
        self.decay = room.rules.kb_decay
        self.shots: dict[int, Shot] = {}
        self.wc = self.cfg.world_clock
        self.night = False
        self.weather = "clear"
        self.aggro = self.en.aggro_radius
        self.storm_points: dict[tuple[int, int], int] = {}  # chunk → spawn id, for the current storm block
        self.block = -1

    def _t(self, seconds: float) -> int:
        return max(1, int(seconds * self.hz + 0.5))

    # ── spawning ─────────────────────────────────────────────────────────────
    def _chunk_points(self, cx: int, cy: int) -> list[int]:
        hit = self.chunk_spawns.get((cx, cy))
        if hit is not None:
            return hit
        out: list[int] = []
        grid = self.room.grid
        cs = grid.cs
        seed = self.room.seed
        biome = grid.gen.biome(cx * cs + cs // 2, cy * cs + cs // 2)
        spec = self.en.biomes.get(biome)  # type: ignore[call-overload]
        if spec is not None and spec.roster:
            r0 = rand01(seed, cx, cy, 501)
            n_day = int(spec.groups_per_chunk + r0)
            n = int(spec.groups_per_chunk * self.wc.night.groups + r0)
            for i in range(max(n, n_day)):
                for attempt in range(10):
                    x = cx * cs + int(rand01(seed, cx * 31 + i, cy * 17 + attempt, 502) * cs)
                    y = cy * cs + int(rand01(seed, cx * 13 + attempt, cy * 29 + i, 503) * cs)
                    if not grid.solid(x, y) and grid.gen.biome(x, y) == biome:
                        break
                else:
                    continue
                r = rand01(seed, cx, cy, 510 + i)
                total = sum(spec.roster.values())
                acc = 0.0
                enemy = next(iter(spec.roster))
                for k, w in spec.roster.items():
                    acc += w / total
                    if r <= acc:
                        enemy = k
                        break
                ecfg = self.en.enemies[enemy]
                elite = rand01(seed, cx, cy, 520 + i) < spec.elite_chance and ecfg.elite_name is not None
                lo, hi = ecfg.group
                count = 1 if elite else lo + int(rand01(seed, cx, cy, 530 + i) * (hi - lo + 1))
                sid = _mix(seed, cx, cy, i) & 0x7FFFFFFF
                sp = SpawnPoint(sid, x + 0.5, y + 0.5, biome, enemy, elite, count, night_only=i >= n_day)
                self.spawns[sid] = sp
                out.append(sid)
        self.chunk_spawns[(cx, cy)] = out
        return out

    def _spawn(self, sp: SpawnPoint, t: int) -> None:
        for _ in range(sp.count):
            self.spawn_one(sp.enemy, sp.x, sp.y, sp.biome, t, elite=sp.elite, sp=sp)

    def spawn_one(
        self,
        key: str,
        x0: float,
        y0: float,
        biome: str,
        t: int,
        elite: bool = False,
        sp: SpawnPoint | None = None,
        minion_of: Monster | None = None,
        spread: float = 1.6,
    ) -> Monster:
        """One monster near (x0, y0), with elite, night, co-op and roaming scaling applied."""
        ecfg = self.en.enemies[key]
        el = self.en.elite
        rng = self.room.rng
        x, y = x0, y0
        for _try in range(6):
            cx, cy = x0 + rng.uniform(-spread, spread), y0 + rng.uniform(-spread, spread)
            if not self.room.grid.solid(int(cx), int(cy)):
                x, y = cx, cy
                break
        hp, dmg, defence = ecfg.hp, ecfg.dmg, ecfg.defence
        if ecfg.roaming:
            spec = self.en.biomes.get(biome) or self.en.biomes["meadow"]  # type: ignore[call-overload]
            sc = spec.scale
            hp, dmg, defence = hp * sc.hp, dmg * sc.dmg, defence + sc.defence
        if elite:
            hp, dmg = hp * el.hp, dmg * el.dmg
        if self.night:
            hp, dmg = hp * self.wc.night.hp, dmg * self.wc.night.dmg
        co = self.en.coop
        extra = len(self._players_near(x0, y0, co.radius)) - 1
        if extra > 0 and minion_of is None:
            hp *= 1 + co.hp_per_player * extra  # co-op (BALANCE §6.2)
        hp = round(hp)
        r = ecfg.radius * (el.scale if elite else 1)
        m = Monster(
            id=self.room.new_id(),
            key=key,
            cfg=ecfg,
            elite=elite,
            spawn=sp.id if sp is not None else 0,
            x=x,
            y=y,
            hx=x0 if sp is None else sp.x,
            hy=y0 if sp is None else sp.y,
            hp=hp,
            hp_max=hp,
            dmg=dmg,
            defence=defence,
            speed=ecfg.speed / self.hz,
            box=Box(r * 0.75, r * 0.5),
            biome=biome,
            state="hidden" if ecfg.archetype == "ambusher" else "idle",
            last_near=t,
            night=self.night,
            minion_of=minion_of.id if minion_of is not None else None,
        )
        m.wx, m.wy = x, y
        m.next_summon = t + self._t(ecfg.summon.every / 2) if ecfg.summon else 0
        self.monsters[m.id] = m
        if sp is not None:
            sp.alive.add(m.id)
        return m

    # ── day, night and weather ───────────────────────────────────────────────
    def _world(self, t: int) -> None:
        night, weather = self.room.world_now()
        was_night, self.night, self.weather = self.night, night, weather
        ws = self.wc.weather.states.get(weather)
        self.aggro = self.en.aggro_radius * (ws.aggro if ws else 1.0)
        if was_night and not night:
            # dawn: the night-only groups fade unless they're busy with someone
            for m in list(self.monsters.values()):
                sp = self.spawns.get(m.spawn)
                if sp is not None and sp.night_only and m.state in ("idle", "return", "hidden"):
                    self._fade(m)
        block = worldclock.block_index(self.wc, self.room.st.clock.now())
        if block != self.block:
            self.block = block
            for sid in self.storm_points.values():
                sp = self.spawns.pop(sid, None)
                if sp is None:
                    continue
                for mid in list(sp.alive):
                    sm = self.monsters.get(mid)
                    if sm is not None and sm.state in ("idle", "return"):
                        self._fade(sm)
            self.storm_points.clear()

    def _fade(self, m: Monster) -> None:
        self._broadcast(m.x, m.y, [EV["DEATH"], m.id, m.x, m.y, m.key, 2])  # 2: faded away, no loot
        self._remove(m, killed=False)

    def _storm_points(self, cx: int, cy: int) -> list[int]:
        """During a storm, some chunks near players get a Storm Elemental for that weather block."""
        ws = self.wc.weather.states.get(self.weather)
        if ws is None or ws.storm_spawns <= 0:
            return []
        hit = self.storm_points.get((cx, cy))
        if hit is not None:
            return [hit]
        seed = self.room.seed
        if rand01(seed ^ self.block, cx, cy, 601) >= ws.storm_spawns:
            self.storm_points[(cx, cy)] = -1
            return []
        grid = self.room.grid
        cs = grid.cs
        for attempt in range(10):
            x = cx * cs + int(rand01(seed, cx * 7 + self.block, cy + attempt, 602) * cs)
            y = cy * cs + int(rand01(seed, cx + attempt, cy * 11 + self.block, 603) * cs)
            if not grid.solid(x, y) and grid.gen.plot_at(x, y, 4) is None:
                break
        else:
            self.storm_points[(cx, cy)] = -1
            return []
        sid = _mix(seed, cx, cy, 9000 + self.block % 9973) & 0x7FFFFFFF
        biome = grid.gen.biome(x, y)
        if biome not in self.en.biomes:
            biome = "meadow"  # the village ring counts as meadow for a roaming spawn
        self.spawns[sid] = SpawnPoint(
            sid, x + 0.5, y + 0.5, biome, self.en.storm_enemy, False, 1, storm_block=self.block
        )
        self.storm_points[(cx, cy)] = sid
        return [sid]

    def _wake(self, t: int) -> None:
        cs = self.room.grid.cs
        r = self.en.wake_radius_chunks
        for p in self.room.players.values():
            pcx, pcy = int(p.m.x) // cs, int(p.m.y) // cs
            for cy in range(pcy - r, pcy + r + 1):
                for cx in range(pcx - r, pcx + r + 1):
                    for sid in self._chunk_points(cx, cy) + self._storm_points(cx, cy):
                        sp = self.spawns.get(sid)
                        if sp is None or (sp.night_only and not self.night) or sp.alive or t < sp.respawn_at:
                            continue
                        if sp.storm_block is not None and sp.respawn_at:
                            continue  # one Storm Elemental per chunk per storm
                        self._spawn(sp, t)

    def _despawn(self, t: int) -> None:
        cs = self.room.grid.cs
        reach = (self.en.wake_radius_chunks + 1) * cs
        for m in list(self.monsters.values()):
            if any(abs(p.m.x - m.x) < reach and abs(p.m.y - m.y) < reach for p in self.room.players.values()):
                m.last_near = t
            elif t - m.last_near > self.despawn_ticks:
                self._remove(m, killed=False)

    def _remove(self, m: Monster, killed: bool) -> None:
        self.monsters.pop(m.id, None)
        sp = self.spawns.get(m.spawn)
        if sp is not None:
            sp.alive.discard(m.id)
            if not sp.alive and killed:
                sp.respawn_at = self.room.tick_no + self.respawn_ticks

    # ── the tick ─────────────────────────────────────────────────────────────
    def tick(self, t: int) -> None:
        if t % self.hz == 1 or self.block < 0:
            self._world(t)
        if t % 10 == 0:
            self._wake(t)
        if t % self.hz == 0:
            self._despawn(t)
        for m in list(self.monsters.values()):
            self._ai(m, t)
            m.history.append((t, m.x, m.y))
        self._resolve_pending(t)
        self._projectiles(t)
        self._shots(t)

    def _players_near(self, x: float, y: float, r: float) -> list[Player]:
        return [
            p
            for p in self.room.players.values()
            if p.ko == 0 and p.linkdead == 0 and (p.m.x - x) ** 2 + (p.m.y - y) ** 2 <= r * r
        ]

    def _broadcast(self, x: float, y: float, ev: list[Any], r: float = 30.0) -> None:
        for p in self.room.players.values():
            if abs(p.m.x - x) <= r and abs(p.m.y - y) <= r:
                p.ev.append(ev)

    def _move(self, m: Monster, dx: float, dy: float) -> None:
        solid = self.room.grid.solid
        gen = self.room.grid.gen
        nx = mo._slide_x(m.x, m.y, dx, m.box, solid)  # type: ignore[arg-type]
        ny = mo._slide_y(nx, m.y, dy, m.box, solid)  # type: ignore[arg-type]
        # villages are safe: monsters never step into a plot
        if gen.plot_at(int(nx), int(ny), 2) is not None:
            if m.state == "chase":
                m.state, m.st_t, m.target = "return", 0, None
            return
        m.x, m.y = nx, ny

    def _ai(self, m: Monster, t: int) -> None:
        a = m.cfg.attack
        m.st_t += 1
        if m.hurt > 0:
            m.hurt -= 1
        # knockback first
        if m.kbx or m.kby:
            self._move(m, max(-0.9, min(0.9, m.kbx)), max(-0.9, min(0.9, m.kby)))
            m.kbx *= self.decay
            m.kby *= self.decay
            if m.kbx * m.kbx + m.kby * m.kby < 1e-5:
                m.kbx = m.kby = 0.0
        target = self.room.players.get(m.target) if m.target is not None else None
        if target is not None and (target.ko > 0 or target.linkdead > 0):
            target = None
        if m.state == "hidden":
            if self._players_near(m.x, m.y, m.cfg.ambush_radius or 4):
                m.state, m.st_t = "chase", 0
                near = self._players_near(m.x, m.y, m.cfg.ambush_radius or 4)
                m.target = near[0].eid
                self._broadcast(m.x, m.y, [EV["SFX"], "hiss", m.x, m.y])
            return
        if m.state in ("idle", "return"):
            home_d = math.hypot(m.x - m.hx, m.y - m.hy)
            if m.state == "return":
                if home_d < 0.8:
                    m.state, m.st_t = "idle", 0
                    m.hp = m.hp_max
                    m.damagers.clear()
                else:
                    self._step_toward(m, m.hx, m.hy, 1.0)
                    return
            if t % 4 == m.id % 4:
                near = sorted(
                    self._players_near(m.x, m.y, self.aggro),
                    key=lambda p: (p.m.x - m.x) ** 2 + (p.m.y - m.y) ** 2,
                )
                if near:
                    m.target, m.state, m.st_t = near[0].eid, "chase", 0
                    if m.key in ("wolf", "frost_wolf", "magma_hound"):
                        self._broadcast(m.x, m.y, [EV["SFX"], "growl", m.x, m.y])
                    return
            if m.st_t % (self.hz * 3) == 1:
                rng = self.room.rng
                m.wx, m.wy = m.hx + rng.uniform(-3, 3), m.hy + rng.uniform(-3, 3)
            if (m.wx - m.x) ** 2 + (m.wy - m.y) ** 2 > 0.09:
                self._step_toward(m, m.wx, m.wy, 0.35)
            return
        if m.state == "chase":
            if target is None or math.hypot(m.x - m.hx, m.y - m.hy) > self.en.leash_radius:
                m.state, m.st_t, m.target = "return", 0, None
                return
            dx, dy = target.m.x - m.x, target.m.y - m.y
            d = math.hypot(dx, dy)
            if m.cfg.summon is not None and t >= m.next_summon:
                self._summon(m, t)
            if m.cfg.keep_away and d < m.cfg.keep_away and m.backoff < self.hz * 2:
                m.backoff += 1  # kiters and summoners keep their distance, but not forever
                self._step_toward(m, m.x - dx, m.y - dy, 0.8)
                return
            if d <= a.trigger:
                m.backoff = 0
                self._start_windup(m, target)
                return
            m.backoff = max(0, m.backoff - 1)
            self._step_toward(m, target.m.x, target.m.y, 1.0)
            return
        if m.state == "windup":
            if m.st_t >= self._t(a.windup):
                m.state, m.st_t = "active", 0
                m.hit_players.clear()
                if a.shape == "line":
                    self._check_hit(m, t)
                elif a.shape == "shot":
                    self._fire(m)
            return
        if m.state == "active":
            steps = self._t(a.active)
            if a.lunge:
                self._move(m, m.dx * a.lunge / steps, m.dy * a.lunge / steps)
            if m.st_t >= steps:
                if a.shape == "circle":
                    self._check_hit(m, t)
                m.state, m.st_t = "recover", 0
            return
        if m.state == "recover" and m.st_t >= self._t(a.recover):
            m.state, m.st_t = ("chase" if target else "return"), 0

    def _step_toward(self, m: Monster, tx: float, ty: float, frac: float) -> None:
        dx, dy = tx - m.x, ty - m.y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return
        sp = min(d, m.speed * frac)
        ux, uy = dx / d, dy / d
        m.dx, m.dy = ux, uy
        # keep a little space from other monsters
        for o in self.monsters.values():
            if o is m:
                continue
            ox, oy = m.x - o.x, m.y - o.y
            od2 = ox * ox + oy * oy
            rr = (m.box.hw + o.box.hw) * 1.6
            if 1e-6 < od2 < rr * rr:
                od = math.sqrt(od2)
                ux += ox / od * 0.6
                uy += oy / od * 0.6
        ul = math.hypot(ux, uy) or 1.0
        self._move(m, ux / ul * sp, uy / ul * sp)

    def _start_windup(self, m: Monster, target: Player) -> None:
        a = m.cfg.attack
        dx, dy = target.m.x - m.x, target.m.y - m.y
        d = math.hypot(dx, dy) or 1.0
        m.dx, m.dy = dx / d, dy / d
        m.state, m.st_t = "windup", 0
        if a.shape == "circle":
            if a.at_target:  # a root circle right where the player stands
                m.ox, m.oy = target.m.x, target.m.y
            else:  # hop onto where the player is standing now
                reach = min(d, a.lunge if a.lunge else 0.0)
                m.ox, m.oy = m.x + m.dx * reach, m.y + m.dy * reach
            ev = [EV["TELEGRAPH"], m.id, 0, m.ox, m.oy, m.dx, m.dy, a.range, a.range, int(a.windup * 1000)]
        else:
            m.ox, m.oy = m.x, m.y
            length = max(a.range, a.lunge)
            ev = [EV["TELEGRAPH"], m.id, 1, m.ox, m.oy, m.dx, m.dy, length, a.width, int(a.windup * 1000)]
        self._broadcast(m.x, m.y, ev)

    def _check_hit(self, m: Monster, t: int) -> None:
        a = m.cfg.attack
        for p in self._players_near(m.ox, m.oy, max(a.range, a.lunge) + 1.5):
            if p.eid in m.hit_players:
                continue
            px, py = p.m.x - m.ox, p.m.y - m.oy
            if a.shape == "circle":
                inside = px * px + py * py <= (a.range + 0.25) ** 2
            else:
                length = max(a.range, a.lunge)
                along = px * m.dx + py * m.dy
                across = abs(px * -m.dy + py * m.dx)
                inside = -0.3 <= along <= length + 0.3 and across <= a.width / 2 + 0.25
            if not inside:
                continue
            m.hit_players.add(p.eid)
            if p.iframes > 0 or p.m.dodge > 0:
                p.ev.append([EV["HIT"], m.id, p.eid, 0, 0, 2])  # dodged!
                continue
            poison = (m.cfg.poison.dps, self._t(m.cfg.poison.duration)) if m.cfg.poison else None
            kb = a.knockback * (1.0 if not m.elite else 1.3)
            root = self._t(a.root) if a.root else 0
            self.pending.append(PendingHit(t + self.grace, m.id, p.eid, m.dmg, px, py, kb, poison, root))

    def _resolve_pending(self, t: int) -> None:
        keep: list[PendingHit] = []
        for h in self.pending:
            if h.resolve > t:
                keep.append(h)
                continue
            p = self.room.players.get(h.eid)
            if p is None or p.ko > 0:
                continue
            if p.m.dodge > 0 or p.iframes > 0:  # dodge grace: a dodge that started in the window wins
                p.ev.append([EV["HIT"], h.mid, p.eid, 0, 0, 2])
                continue
            self.damage_player(p, h.dmg, h.mid, kind=0)
            d = math.hypot(h.dx, h.dy) or 1.0
            imp = h.kb * self.cb.knockback.player_mult * (1 - self.decay)
            p.m.kbx += h.dx / d * imp
            p.m.kby += h.dy / d * imp
            p.iframes = max(p.iframes, 5)
            if h.poison and p.ko == 0:
                p.poison = max(p.poison, h.poison[1])
                p.poison_dps = h.poison[0]
            if h.root and p.ko == 0:
                p.rooted = max(p.rooted, h.root)
        self.pending = keep

    # ── kiters and summoners ─────────────────────────────────────────────────
    def _fire(self, m: Monster) -> None:
        a, sh = m.cfg.attack, m.cfg.shot
        assert sh is not None
        v = sh.speed / self.hz
        poison = (m.cfg.poison.dps, self._t(m.cfg.poison.duration)) if m.cfg.poison else None
        s = Shot(
            self.room.new_id(),
            m.id,
            sh.sprite,
            m.x + m.dx * 0.4,
            m.y + m.dy * 0.4,
            m.dx * v,
            m.dy * v,
            a.range,
            sh.radius,
            m.dmg,
            a.knockback,
            poison,
            sh.chain,
            sh.chain_radius,
            sh.chain_dmg,
        )
        self.shots[s.id] = s
        self._broadcast(m.x, m.y, [EV["SFX"], "zap" if sh.chain else "shoot", m.x, m.y])

    def _shots(self, t: int) -> None:
        solid = self.room.grid.solid
        for s in list(self.shots.values()):
            done = False
            for _ in range(2):
                s.x += s.vx / 2
                s.y += s.vy / 2
                s.left -= math.hypot(s.vx, s.vy) / 2
                if s.left <= 0 or solid(int(s.x), int(s.y)):
                    done = True  # trees and rocks are cover
                    break
                for p in self._players_near(s.x, s.y, s.radius + 0.3):
                    if p.eid in s.hit:
                        continue
                    s.hit.add(p.eid)
                    if p.iframes > 0 or p.m.dodge > 0:
                        p.ev.append([EV["HIT"], s.mid, p.eid, 0, 0, 2])  # dodged through it
                        continue
                    self._shot_hit(s, p, t)
                    done = True
                    break
                if done:
                    break
            if done:
                del self.shots[s.id]
                self._broadcast(s.x, s.y, [EV["PROJECTILE_END"], s.id, s.x, s.y])

    def _shot_hit(self, s: Shot, p: Player, t: int) -> None:
        self.pending.append(PendingHit(t + self.grace, s.mid, p.eid, s.dmg, s.vx, s.vy, s.kb, s.poison))
        prev, seen = p, {p.eid}
        for _ in range(s.chain):  # chain lightning jumps to the nearest other player
            near = [o for o in self._players_near(prev.m.x, prev.m.y, s.chain_radius) if o.eid not in seen]
            if not near:
                break
            nxt = min(near, key=lambda o: (o.m.x - prev.m.x) ** 2 + (o.m.y - prev.m.y) ** 2)
            self._broadcast(prev.m.x, prev.m.y, [EV["ZAP"], prev.m.x, prev.m.y, nxt.m.x, nxt.m.y])
            dx, dy = nxt.m.x - prev.m.x, nxt.m.y - prev.m.y
            self.pending.append(
                PendingHit(t + self.grace, s.mid, nxt.eid, s.dmg * s.chain_dmg, dx, dy, s.kb / 2, None)
            )
            seen.add(nxt.eid)
            prev = nxt

    def _summon(self, m: Monster, t: int) -> None:
        sc = m.cfg.summon
        assert sc is not None
        m.next_summon = t + self._t(sc.every)
        alive = sum(1 for o in self.monsters.values() if o.minion_of == m.id)
        n = min(sc.count, sc.max_alive - alive)
        for _ in range(n):
            mm = self.spawn_one(sc.enemy, m.x, m.y, m.biome, t, minion_of=m, spread=1.2)
            mm.state, mm.target = "chase", m.target
        if n > 0:
            self._broadcast(m.x, m.y, [EV["SFX"], "summon", m.x, m.y])

    def damage_player(self, p: Player, raw: float, src: int, kind: int) -> None:
        defence = p.stats.defence + p.armour
        taken = raw * (1 - defence / (defence + self.cb.defence_k))
        taken = max(1, round(taken))
        p.hp -= taken
        p.last_combat = self.room.tick_no
        self._broadcast(p.m.x, p.m.y, [EV["HIT"], src, p.eid, taken, 0, kind])
        if p.hp <= 0:
            self.knock_out(p)

    def poison_tick(self, p: Player) -> None:
        if p.ko == 0 and p.poison_dps > 0:
            self.damage_player(p, p.poison_dps, 0, kind=1)

    def knock_out(self, p: Player) -> None:
        room = self.room
        p.hp = 0
        p.ko = self.ko_ticks
        p.poison = 0
        p.rooted = 0
        p.m.atk = 0
        p.m.dodge = 0
        p.m.kbx = p.m.kby = 0.0
        self.pending = [h for h in self.pending if h.eid != p.eid]
        for m in self.monsters.values():
            if m.target == p.eid:
                m.target, m.state, m.st_t = None, "return", 0
        # lose a share of rare materials; they wait here as a marker (BALANCE §4)
        rate = self.cfg.avatar.ko.rare_loss
        lost: dict[str, int] = {}
        for _slot, key, qty, inst in list(p.inv):
            if inst or self.cfg.items[key].category != "rare_material":
                continue
            n = math.floor(qty * rate)
            if n == 0 and qty >= 2:
                n = 1
            if n > 0:
                lost[key] = lost.get(key, 0) + n
        life = self.cfg.avatar.ko.drop_lifetime
        death_id = uuid.uuid4()
        for key, n in lost.items():
            room.inv_remove(p, key, n)
            p.pending.removed[key] += n
            room.spawn_drop(p, key, n, p.m.x, p.m.y, ttl_s=life, death_id=death_id)
        if lost:
            p.pending.death_drops.append((death_id, p.m.x, p.m.y, dict(lost), time.time() + life))
        if lost:
            p.ev.append([EV["INVENTORY"], p.inv])
        self._broadcast(p.m.x, p.m.y, [EV["KO"], p.eid, lost])

    # ── player attacks ───────────────────────────────────────────────────────
    def player_attack(self, p: Player, mv: MoveRule) -> bool:
        if mv.shape == "throw":
            self._throw(p, mv)
            return True
        t = self.room.tick_no
        view = max(t - self.lag_ticks, min(t, p.view_tick or t))
        hit_any = False
        for m in list(self.monsters.values()):
            if m.state == "hidden":
                continue
            mx, my = self._pos_at(m, view)
            key = (p.atk_serial * 64 + p.m.atk_t, m.id) if mv.shape == "spin" else (p.atk_serial, m.id)
            if key in p.hits_done:
                continue
            if not self.room.in_shape(p, mv, mx, my, m.box.hw + 0.1):
                continue
            p.hits_done.add(key)
            hit_any = True
            self.hit_monster(p, m, mv, mx, my)
        return hit_any

    def _pos_at(self, m: Monster, tick: int) -> tuple[float, float]:
        for ht, hx, hy in reversed(m.history):
            if ht <= tick:
                return hx, hy
        return (m.history[0][1], m.history[0][2]) if m.history else (m.x, m.y)

    @staticmethod
    def is_dull(p: Player) -> bool:
        w = p.weapon
        return bool(w.get("instance_id")) and int(w.get("durability", 1)) <= 0

    def effects(self, p: Player) -> dict[str, float]:
        return forging.weapon_effects(p.weapon.get("modifiers") or [], self.is_dull(p))

    def damage_out(self, p: Player, mv: MoveRule, m: Monster) -> tuple[int, bool]:
        c = self.cb
        tier = max(1, min(5, int(p.weapon.get("tier", 1))))
        rarity = c.rarity_mult.get(p.weapon.get("rarity", "common"), 1.0)  # type: ignore[call-overload]
        eff = self.effects(p)
        crit = self.room.rng.random() < p.stats.crit + eff["crit"]
        dmg = mv.dmg * c.tier_mult[tier - 1] * (1 + p.stats.attack * c.attack_scaling) * rarity
        dmg *= 1 + eff["damage"]
        if self.is_dull(p):
            dmg *= self.cfg.forging.dull_damage  # P2: dull, never broken
        if crit:
            dmg *= c.crit_mult
        dmg *= 1 - m.defence / (m.defence + c.defence_k)
        return max(1, round(dmg)), crit

    def wear(self, p: Player) -> None:
        """A landed hit costs the weapon 1 durability; at 0 it goes Dull (P2)."""
        w = p.weapon
        if not w.get("instance_id") or int(w.get("durability", 0)) <= 0:
            return
        w["durability"] = int(w["durability"]) - 1
        p.pending.durability = True
        if w["durability"] == 0:
            self.room.toast(p, "weapon_dull")

    def hit_monster(self, p: Player, m: Monster, mv: MoveRule, fx: float, fy: float) -> None:
        dmg, crit = self.damage_out(p, mv, m)
        m.hp -= dmg
        m.damagers[p.eid] = m.damagers.get(p.eid, 0) + dmg
        m.hurt = 3
        p.last_combat = self.room.tick_no
        if m.state in ("idle", "return", "hidden"):
            m.state, m.st_t, m.target = "chase", 0, p.eid
        elif m.target is None:
            m.target = p.eid
        heavy = mv.shape == "spin" or mv.stamina > 0 or mv.dmg >= 20
        if heavy and not m.elite and m.state == "windup":
            m.state, m.st_t = "recover", 0  # stagger: a heavy hit interrupts the wind-up
        dx, dy = m.x - p.m.x, m.y - p.m.y
        d = math.hypot(dx, dy) or 1.0
        resist = self.en.elite.knockback_resist if m.elite else 0.0
        imp = mv.knockback * (1 + self.effects(p)["knockback"]) * (1 - resist) * (1 - self.decay)
        self.wear(p)
        m.kbx += dx / d * imp
        m.kby += dy / d * imp
        self._broadcast(m.x, m.y, [EV["HIT"], p.eid, m.id, dmg, 1 if crit else 0, 3 if heavy else 0])
        if m.hp <= 0:
            self._kill(m, p)

    def _kill(self, m: Monster, killer: Player) -> None:
        room = self.room
        self._broadcast(m.x, m.y, [EV["DEATH"], m.id, m.x, m.y, m.key, 1 if m.elite else 0])
        self._remove(m, killed=True)
        spec = self.en.biomes.get(m.biome)  # type: ignore[call-overload]
        el = self.en.elite
        rng = room.rng
        minion = m.minion_of is not None
        night = self.wc.night if m.night else None
        xp = 0
        if spec is not None:
            xp = int(spec.xp * (el.xp if m.elite else 1) * (self.en.minion_xp if minion else 1))
        shared: set[int] = set()  # party members nearby who didn't swing still get the XP (Phase 9)
        for eid in list(m.damagers):
            p = room.players.get(eid)
            if p is None or (p.m.x - m.x) ** 2 + (p.m.y - m.y) ** 2 > 24**2:
                continue
            if room.st.rooms is not None:
                r2 = room.cfg.social.party.xp_share_radius**2
                for o in room.st.rooms.party_players(room, p.user_id):
                    if o.eid not in m.damagers and (o.m.x - m.x) ** 2 + (o.m.y - m.y) ** 2 <= r2:
                        shared.add(o.eid)
            p.pending.stats[f"kill.{m.key}"] += 1
            p.pending.stats["kill.any"] += 1
            if xp:
                room.grant_xp(p, xp)
            if minion:
                continue  # summoned: a share of the XP, nothing else
            # every player who helped gets their own rolls (BALANCE §6.4)
            if spec is not None:
                lo, hi = spec.coins
                coins = rng.randint(lo, hi) * (2 if m.elite else 1)
                if coins:
                    room.spawn_drop(p, "coins", coins, m.x, m.y)
            for _ in range(el.loot_rolls if m.elite else 1):
                for drop in m.cfg.loot:
                    chance = drop.chance
                    if night and self.cfg.items[drop.item].category == "rare_material":
                        chance = min(1.0, chance * night.rare_chance)
                    if rng.random() < chance:
                        q = rng.randint(*drop.qty)
                        if night:
                            q = int(q * night.loot_qty + rng.random())
                        room.spawn_drop(p, drop.item, q, m.x, m.y)
        if xp:
            for eid in shared:
                op = room.players.get(eid)
                if op is not None and op.ko == 0:
                    room.grant_xp(op, xp)
        t = room.tick_no
        if m.cfg.split is not None:  # Big Slime: two little ones pop out, already angry
            sp = self.spawns.get(m.spawn)
            for i in range(m.cfg.split.count):
                c = self.spawn_one(m.cfg.split.into, m.x, m.y, m.biome, t, sp=sp, spread=0.7)
                c.state, c.st_t, c.target = "chase", 0, killer.eid
                ang = math.tau * (i + 0.25) / m.cfg.split.count
                c.kbx, c.kby = math.cos(ang) * 0.25, math.sin(ang) * 0.25
            self._broadcast(m.x, m.y, [EV["SFX"], "split", m.x, m.y])
        if m.cfg.summon is not None:  # a summoner's minions go with it
            for mm in list(self.monsters.values()):
                if mm.minion_of == m.id:
                    self._fade(mm)

    # ── projectiles (spear throw) ────────────────────────────────────────────
    def _throw(self, p: Player, mv: MoveRule) -> None:
        pr = Projectile(
            self.room.new_id(),
            p.eid,
            p.m.x + p.m.ax * 0.4,
            p.m.y + p.m.ay * 0.4,
            p.m.ax * mv.speed,
            p.m.ay * mv.speed,
            mv.range,
            mv,
        )
        self.projectiles[pr.id] = pr
        self._broadcast(p.m.x, p.m.y, [EV["SFX"], "throw", p.m.x, p.m.y])

    def _projectiles(self, t: int) -> None:
        solid = self.room.grid.solid
        for pr in list(self.projectiles.values()):
            owner = self.room.players.get(pr.owner)
            steps = 3
            done = owner is None
            for _ in range(steps):
                if done:
                    break
                pr.x += pr.vx / steps
                pr.y += pr.vy / steps
                pr.left -= math.hypot(pr.vx, pr.vy) / steps
                if solid(int(pr.x), int(pr.y)) or pr.left <= 0:
                    done = True
                    break
                for m in list(self.monsters.values()):
                    if m.id in pr.hit or m.state == "hidden":
                        continue
                    if (m.x - pr.x) ** 2 + (m.y - pr.y) ** 2 <= (m.box.hw + 0.35) ** 2:
                        pr.hit.add(m.id)
                        assert owner is not None
                        self.hit_monster(owner, m, pr.mv, pr.x, pr.y)
            if done:
                del self.projectiles[pr.id]
                self._broadcast(pr.x, pr.y, [EV["PROJECTILE_END"], pr.id, pr.x, pr.y])

    # ── snapshots ────────────────────────────────────────────────────────────
    def entities(self, p: Player, x0: float, x1: float, y0: float, y1: float) -> list[list[Any]]:
        out: list[list[Any]] = []
        for m in self.monsters.values():
            if not (x0 <= m.x <= x1 and y0 <= m.y <= y1):
                continue
            anim = {
                "idle": ANIM["idle"],
                "return": ANIM["walk"],
                "chase": ANIM["walk"],
                "windup": ANIM["windup"],
                "active": ANIM["active"],
                "recover": ANIM["recover"],
                "hidden": ANIM["hidden"],
            }[m.state]
            if m.state == "idle" and (m.wx - m.x) ** 2 + (m.wy - m.y) ** 2 > 0.09:
                anim = ANIM["walk"]
            flags = (1 if m.elite else 0) | (8 if m.hurt else 0) | (16 if m.night else 0)
            flags |= 32 if m.minion_of is not None else 0
            out.append(
                [
                    m.id,
                    ENT["monster"],
                    m.key,
                    round(m.x * Q),
                    round(m.y * Q),
                    round(m.dx * 100),
                    round(m.dy * 100),
                    anim,
                    m.st_t,
                    int(255 * max(0.0, m.hp) / m.hp_max),
                    flags,
                ]
            )
        for s in self.shots.values():
            if x0 <= s.x <= x1 and y0 <= s.y <= y1:
                d = math.hypot(s.vx, s.vy) or 1.0
                out.append(
                    [
                        s.id,
                        ENT["projectile"],
                        s.key,
                        round(s.x * Q),
                        round(s.y * Q),
                        round(s.vx / d * 100),
                        round(s.vy / d * 100),
                        0,
                        0,
                        0,
                        1,  # flag 1: a monster's shot
                    ]
                )
        for pr in self.projectiles.values():
            if x0 <= pr.x <= x1 and y0 <= pr.y <= y1:
                d = math.hypot(pr.vx, pr.vy) or 1.0
                out.append(
                    [
                        pr.id,
                        ENT["projectile"],
                        "spear",
                        round(pr.x * Q),
                        round(pr.y * Q),
                        round(pr.vx / d * 100),
                        round(pr.vy / d * 100),
                        0,
                        0,
                        0,
                        0,
                    ]
                )
        return out
