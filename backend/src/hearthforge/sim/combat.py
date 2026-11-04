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
            n = int(spec.groups_per_chunk + rand01(seed, cx, cy, 501))
            for i in range(n):
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
                elite = rand01(seed, cx, cy, 520 + i) < spec.elite_chance
                lo, hi = ecfg.group
                count = 1 if elite else lo + int(rand01(seed, cx, cy, 530 + i) * (hi - lo + 1))
                sid = _mix(seed, cx, cy, i) & 0x7FFFFFFF
                self.spawns[sid] = SpawnPoint(sid, x + 0.5, y + 0.5, biome, enemy, elite, count)
                out.append(sid)
        self.chunk_spawns[(cx, cy)] = out
        return out

    def _spawn(self, sp: SpawnPoint, t: int) -> None:
        ecfg = self.en.enemies[sp.enemy]
        el = self.en.elite
        rng = self.room.rng
        for _ in range(sp.count):
            x, y = sp.x, sp.y
            for _try in range(6):
                cx, cy = sp.x + rng.uniform(-1.6, 1.6), sp.y + rng.uniform(-1.6, 1.6)
                if not self.room.grid.solid(int(cx), int(cy)):
                    x, y = cx, cy
                    break
            hp = ecfg.hp * (el.hp if sp.elite else 1)
            r = ecfg.radius * (el.scale if sp.elite else 1)
            m = Monster(
                id=self.room.new_id(),
                key=sp.enemy,
                cfg=ecfg,
                elite=sp.elite,
                spawn=sp.id,
                x=x,
                y=y,
                hx=sp.x,
                hy=sp.y,
                hp=hp,
                hp_max=hp,
                dmg=ecfg.dmg * (el.dmg if sp.elite else 1),
                defence=ecfg.defence,
                speed=ecfg.speed / self.hz,
                box=Box(r * 0.75, r * 0.5),
                biome=sp.biome,
                state="hidden" if ecfg.archetype == "ambusher" else "idle",
                last_near=t,
            )
            m.wx, m.wy = x, y
            self.monsters[m.id] = m
            sp.alive.add(m.id)

    def _wake(self, t: int) -> None:
        cs = self.room.grid.cs
        r = self.en.wake_radius_chunks
        for p in self.room.players.values():
            pcx, pcy = int(p.m.x) // cs, int(p.m.y) // cs
            for cy in range(pcy - r, pcy + r + 1):
                for cx in range(pcx - r, pcx + r + 1):
                    for sid in self._chunk_points(cx, cy):
                        sp = self.spawns[sid]
                        if not sp.alive and t >= sp.respawn_at:
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
        if t % 10 == 0:
            self._wake(t)
        if t % self.hz == 0:
            self._despawn(t)
        for m in list(self.monsters.values()):
            self._ai(m, t)
            m.history.append((t, m.x, m.y))
        self._resolve_pending(t)
        self._projectiles(t)

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
                    self._players_near(m.x, m.y, self.en.aggro_radius),
                    key=lambda p: (p.m.x - m.x) ** 2 + (p.m.y - m.y) ** 2,
                )
                if near:
                    m.target, m.state, m.st_t = near[0].eid, "chase", 0
                    if m.key == "wolf":
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
            if d <= a.trigger:
                self._start_windup(m, target)
                return
            self._step_toward(m, target.m.x, target.m.y, 1.0)
            return
        if m.state == "windup":
            if m.st_t >= self._t(a.windup):
                m.state, m.st_t = "active", 0
                m.hit_players.clear()
                if a.shape == "line":
                    self._check_hit(m, t)
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
            # hop onto where the player is standing now
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
            self.pending.append(PendingHit(t + self.grace, m.id, p.eid, m.dmg, px, py, kb, poison))

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
        self.pending = keep

    def damage_player(self, p: Player, raw: float, src: int, kind: int) -> None:
        taken = raw * (1 - p.stats.defence / (p.stats.defence + self.cb.defence_k))
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

    def damage_out(self, p: Player, mv: MoveRule, m: Monster) -> tuple[int, bool]:
        c = self.cb
        tier = max(1, min(5, int(p.weapon.get("tier", 1))))
        rarity = c.rarity_mult.get(p.weapon.get("rarity", "common"), 1.0)  # type: ignore[call-overload]
        crit = self.room.rng.random() < p.stats.crit
        dmg = mv.dmg * c.tier_mult[tier - 1] * (1 + p.stats.attack * c.attack_scaling) * rarity
        if crit:
            dmg *= c.crit_mult
        dmg *= 1 - m.defence / (m.defence + c.defence_k)
        return max(1, round(dmg)), crit

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
        imp = mv.knockback * (1 - resist) * (1 - self.decay)
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
        for eid in list(m.damagers):
            p = room.players.get(eid)
            if p is None or (p.m.x - m.x) ** 2 + (p.m.y - m.y) ** 2 > 24**2:
                continue
            # every player who helped gets their own rolls (BALANCE §6.4)
            if spec is not None:
                lo, hi = spec.coins
                coins = rng.randint(lo, hi) * (2 if m.elite else 1)
                if coins:
                    room.spawn_drop(p, "coins", coins, m.x, m.y)
                xp = int(spec.xp * (el.xp if m.elite else 1))
                room.grant_xp(p, xp)
            for _ in range(el.loot_rolls if m.elite else 1):
                for drop in m.cfg.loot:
                    if rng.random() < drop.chance:
                        room.spawn_drop(p, drop.item, rng.randint(*drop.qty), m.x, m.y)
        _ = killer

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
            flags = (1 if m.elite else 0) | (8 if m.hurt else 0)
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
