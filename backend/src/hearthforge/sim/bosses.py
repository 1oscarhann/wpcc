"""Phase 13: realm bosses. A data-driven brain (bosses.yaml) that drives a Monster: phases at HP shares,
an attack rotation per phase, area hazards with telegraphs (circle, line/charge, rain, cone, ring, radiating
lines), adds, regeneration, a vulnerable window and a blizzard. HP scales with the fighters around it (D-092).
Everyone with at least 1% of the damage who's still here gets their own loot when it falls.

The DB side (which boss, where, when, how hurt) lives in services/bosses.py; the room loads the realm's
waiting boss and hands back hp saves, damage tallies and the kill through its flush.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hearthforge.realtime.protocol import EV
from hearthforge.sim.combat import PendingHit

if TYPE_CHECKING:
    from hearthforge.config.schemas import BossAttackCfg, BossCfg, BossesCfg
    from hearthforge.sim.combat import Monster
    from hearthforge.sim.room import Player, RealmRoom

VULNERABLE = 256  # entity flags
BLIZZARD = 512

SHAPE = {"circle": 0, "line": 1, "ring": 2, "cone": 3}


@dataclass
class Hazard:
    resolve: int
    shape: str  # circle | line | ring | cone
    x: float
    y: float
    dx: float
    dy: float
    range: float
    width: float  # line width · ring inner radius · cone angle (degrees)
    dmg: float
    kb: float
    poison: bool = False
    slow: bool = False


@dataclass
class BossRow:
    """What the room knows about a waiting realm boss (from realm_bosses)."""

    id: str
    key: str
    x: float
    y: float
    hp_fraction: float
    expires_ms: int
    damage: dict[str, int] = field(default_factory=dict)  # user id → damage so far (from boss_damage)
    kills: dict[str, int] = field(default_factory=dict)  # user id → earlier kills of this boss (trophy rule)


class BossBrain:
    def __init__(self, ctl: Bosses, row: BossRow, cfg: BossCfg) -> None:
        self.ctl = ctl
        self.room = ctl.room
        self.row = row
        self.cfg = cfg
        self.phase = 0
        self.rot = 0
        self.atk: BossAttackCfg | None = None
        self.atk_key = ""
        self.hazards: list[Hazard] = []
        self.vuln_until = 0
        self.blizzard = False
        self.dmg_by_user: dict[str, float] = {k: float(v) for k, v in row.damage.items()}
        self.fighters = 1
        self.awake = False
        self.lunge_left = 0

    # ── helpers ──────────────────────────────────────────────────────────────
    def _t(self, s: float) -> int:
        return max(1, int(s * self.room.hz + 0.5))

    def _speed(self) -> float:
        return self.cfg.phases[self.phase].speed

    def flags(self, m: Monster) -> int:
        return (VULNERABLE if self.room.tick_no < self.vuln_until else 0) | (BLIZZARD if self.blizzard else 0)

    def on_hit(self, p: Player, dmg: float) -> float:
        """Player damage on the way in: the vulnerable window multiplies it; tally it per player."""
        if self.room.tick_no < self.vuln_until:
            dmg = round(dmg * self.cfg.vulnerable_mult)
        uid = str(p.user_id)
        self.dmg_by_user[uid] = self.dmg_by_user.get(uid, 0.0) + dmg
        self.ctl.dirty_damage.add((self.row.id, uid))
        return dmg

    def fighters_near(self, m: Monster) -> list[Player]:
        r2 = self.ctl.cfg.engage**2
        return [
            p
            for p in self.room.players.values()
            if p.ko == 0
            and not p.dungeon
            and p.linkdead == 0
            and (p.m.x - m.x) ** 2 + (p.m.y - m.y) ** 2 <= r2
        ]

    def scale(self, m: Monster, n: int) -> None:
        """HP × (1 + k × (fighters − 1)), keeping the share of HP it has left."""
        n = max(1, n)
        if n == self.fighters:
            return
        self.fighters = n
        frac = m.hp / m.hp_max if m.hp_max else 1.0
        m.hp_max = round(self.cfg.hp * (1 + self.ctl.cfg.hp_per_fighter * (n - 1)))
        m.hp = max(1.0, m.hp_max * frac)

    # ── the brain ────────────────────────────────────────────────────────────
    def tick(self, m: Monster, t: int) -> None:
        combat = self.room.combat
        m.kbx *= 0.2  # bosses barely budge
        m.kby *= 0.2
        self._resolve(m, t)
        if t % self.room.hz == 0:
            near = self.fighters_near(m)
            self.scale(m, len(near))
            if self.cfg.regen and m.burn[1] <= 0 and m.hp < m.hp_max:
                m.hp = min(m.hp_max, m.hp + m.hp_max * self.cfg.regen.per_s)
        if m.state == "return":
            if math.hypot(m.x - m.hx, m.y - m.hy) < 1.0:
                m.state, m.st_t = "idle", 0
                m.hp = m.hp_max
                self.phase, self.rot, self.blizzard, self.awake = 0, 0, False, False
                self._tell(m, ["reset", self.row.key])
            else:
                combat._step_toward(m, m.hx, m.hy, 1.2)
            return
        target = self.room.players.get(m.target) if m.target is not None else None
        if target is not None and (target.ko > 0 or target.dungeon or target.linkdead > 0):
            target = None
        if t % 10 == m.id % 10 or target is None:
            near = (
                self.fighters_near(m) if self.awake else combat._players_near(m.hx, m.hy, self.ctl.cfg.aggro)
            )
            near = [p for p in near if not p.dungeon]
            if near:
                target = min(near, key=lambda p: (p.m.x - m.x) ** 2 + (p.m.y - m.y) ** 2)
                m.target = target.eid
        if target is None:
            if self.awake and not self.fighters_near(m):
                m.state, m.st_t, m.target = "return", 0, None
            elif not self.awake and (m.x - m.hx) ** 2 + (m.y - m.hy) ** 2 > 1:
                combat._step_toward(m, m.hx, m.hy, 0.6)
            return
        if math.hypot(m.x - m.hx, m.y - m.hy) > self.ctl.cfg.leash + 6:
            m.state, m.st_t, m.target = "return", 0, None
            return
        if not self.awake:
            self.awake = True
            m.state, m.st_t = "chase", 0
            self._tell(m, ["wake", self.row.key, self.cfg.name, m.id])
            combat._broadcast(m.x, m.y, [EV["SFX"], "roar", m.x, m.y], r=40)
        self._phases(m, t)
        if m.state == "windup":
            if m.st_t >= self._t(self.atk.windup / self._speed()) if self.atk else True:
                m.state, m.st_t = "active", 0
                if self.atk is not None and self.atk.lunge:
                    self.lunge_left = self._t(0.3)
            return
        if m.state == "active":
            if self.lunge_left > 0 and self.atk is not None:
                steps = self._t(0.3)
                combat._move(m, m.dx * self.atk.lunge / steps, m.dy * self.atk.lunge / steps)
                self.lunge_left -= 1
                return
            m.state, m.st_t = "recover", 0
            if self.atk is not None and self.atk.vulnerable:
                self.vuln_until = t + self._t(self.atk.vulnerable)
                self._tell(m, ["vulnerable", m.id, int(self.atk.vulnerable * 1000)])
            return
        if m.state == "recover":
            if m.st_t >= self._t(self.atk.recover / self._speed()) if self.atk else True:
                m.state, m.st_t = "chase", 0
                self.rot += 1
            return
        # chase: walk in until the next attack in the rotation can be used
        ph = self.cfg.phases[self.phase]
        key = ph.attacks[self.rot % len(ph.attacks)]
        atk = self.cfg.attacks[key]
        d = math.hypot(target.m.x - m.x, target.m.y - m.y)
        if d <= atk.trigger and m.st_t > self._t(0.25):
            self._begin(m, key, atk, target, t)
            return
        combat._step_toward(m, target.m.x, target.m.y, self._speed())

    def _phases(self, m: Monster, t: int) -> None:
        frac = m.hp / m.hp_max if m.hp_max else 0
        while self.phase + 1 < len(self.cfg.phases) and frac <= self.cfg.phases[self.phase + 1].at:
            self.phase += 1
            ph = self.cfg.phases[self.phase]
            self.rot = 0
            if ph.blizzard:
                self.blizzard = True
            if ph.summon is not None:
                combat = self.room.combat
                for i in range(ph.summon.count):
                    c = combat.spawn_one(
                        ph.summon.enemy, m.x, m.y, self.cfg.biome, t, minion_of=m, spread=2.0
                    )
                    c.state, c.st_t, c.target = "chase", 0, m.target
                    ang = math.tau * (i + 0.5) / ph.summon.count
                    c.kbx, c.kby = math.cos(ang) * 0.3, math.sin(ang) * 0.3
            self._tell(m, ["phase", m.id, self.phase, ph.note or ""])

    def _begin(self, m: Monster, key: str, atk: BossAttackCfg, target: Player, t: int) -> None:
        combat = self.room.combat
        rng = self.room.rng
        self.atk, self.atk_key = atk, key
        dx, dy = target.m.x - m.x, target.m.y - m.y
        d = math.hypot(dx, dy) or 1.0
        m.dx, m.dy = dx / d, dy / d
        m.state, m.st_t = "windup", 0
        ph = self.cfg.phases[self.phase]
        dmg = m.dmg * atk.dmg * ph.dmg
        windup = atk.windup / self._speed()
        resolve = t + self._t(windup)
        shapes: list[
            tuple[str, float, float, float, float, float, float]
        ] = []  # shape, x, y, dx, dy, range, width
        if atk.shape == "circle":
            if atk.at_target:
                shapes.append(("circle", target.m.x, target.m.y, m.dx, m.dy, atk.range, atk.range))
            else:
                shapes.append(("circle", m.x, m.y, m.dx, m.dy, atk.range, atk.range))
        elif atk.shape == "line":
            shapes.append(("line", m.x, m.y, m.dx, m.dy, max(atk.range, atk.lunge), atk.width))
        elif atk.shape == "cone":
            shapes.append(("cone", m.x, m.y, m.dx, m.dy, atk.range, atk.angle))
        elif atk.shape == "ring":
            shapes.append(("ring", m.x, m.y, m.dx, m.dy, atk.range, atk.inner))
        elif atk.shape == "lines":
            base = math.atan2(m.dy, m.dx)
            for i in range(atk.count):
                a = base + math.tau * i / atk.count
                shapes.append(("line", m.x, m.y, math.cos(a), math.sin(a), atk.range, atk.width))
        elif atk.shape == "rain":
            for p in self.fighters_near(m) or [target]:
                for k in range(atk.count):
                    ang = rng.uniform(0, math.tau)
                    r = 0.0 if k == 0 else rng.uniform(1.0, atk.spread)  # one always lands right on you
                    x, y = p.m.x + math.cos(ang) * r, p.m.y + math.sin(ang) * r
                    shapes.append(("circle", x, y, 0.0, 1.0, atk.radius, atk.radius))
        for shape, x, y, ddx, ddy, rng_, w in shapes:
            self.hazards.append(
                Hazard(
                    resolve,
                    shape,
                    x,
                    y,
                    ddx,
                    ddy,
                    rng_,
                    w,
                    dmg,
                    atk.knockback,
                    atk.poison or atk.burn,
                    atk.slow,
                )
            )
            hid = self.room.new_id()
            combat._broadcast(
                x, y, [EV["TELEGRAPH"], hid, SHAPE[shape], x, y, ddx, ddy, rng_, w, int(windup * 1000)], r=40
            )

    def _resolve(self, m: Monster, t: int) -> None:
        if not self.hazards:
            return
        combat = self.room.combat
        keep = []
        for h in self.hazards:
            if h.resolve > t:
                keep.append(h)
                continue
            if h.shape == "circle":
                combat._broadcast(h.x, h.y, [EV["IMPACT"], h.x, h.y, h.range, "slam"], r=40)
            for p in combat._players_near(h.x, h.y, h.range + 8):
                if p.dungeon:
                    continue
                px, py = p.m.x - h.x, p.m.y - h.y
                dist = math.hypot(px, py)
                if h.shape == "circle":
                    inside = dist <= h.range + 0.25
                elif h.shape == "line":
                    along = px * h.dx + py * h.dy
                    across = abs(px * -h.dy + py * h.dx)
                    inside = -0.3 <= along <= h.range + 0.3 and across <= h.width / 2 + 0.25
                elif h.shape == "ring":
                    inside = h.width - 0.2 <= dist <= h.range + 0.25
                else:  # cone
                    ang = math.degrees(math.acos(max(-1.0, min(1.0, (px * h.dx + py * h.dy) / (dist or 1)))))
                    inside = dist <= h.range + 0.25 and (dist < 0.6 or ang <= h.width / 2)
                if not inside:
                    continue
                if p.iframes > 0 or p.m.dodge > 0:
                    p.ev.append([EV["HIT"], m.id, p.eid, 0, 0, 2])
                    continue
                poison = (h.dmg * 0.12, self._t(4.0)) if h.poison else None
                root = self._t(0.5) if h.slow else 0
                combat.pending.append(
                    PendingHit(t + combat.grace, m.id, p.eid, h.dmg, px, py, h.kb, poison, root)
                )
        self.hazards = keep

    # ── the end ──────────────────────────────────────────────────────────────
    def on_death(self, m: Monster, killer: Player) -> None:
        room = self.room
        rng = room.rng
        total = sum(self.dmg_by_user.values()) or 1.0
        loot = self.cfg.loot
        winners: list[str] = []
        for uid, dmg in sorted(self.dmg_by_user.items(), key=lambda kv: -kv[1]):
            if dmg / total < self.ctl.cfg.loot_min_share:
                continue
            p = room.by_user.get(uuid.UUID(uid))
            if p is None:  # left before the end: their share comes by mail (Phase 15)
                items = {item: rng.randint(lo, hi) for item, (lo, hi) in loot.rares.items()}
                if self.row.kills.get(uid, 0) == 0 or rng.random() < self.ctl.cfg.trophy_chance:
                    items[loot.trophy] = 1
                self.ctl.mail.append((uid, items, rng.randint(*loot.coins), self.cfg.name))
                continue
            winners.append(p.name)
            room.grant_xp(p, loot.xp)
            coins = rng.randint(*loot.coins)
            room.spawn_drop(p, "coins", coins, m.x, m.y)
            for item, (lo, hi) in loot.rares.items():
                room.spawn_drop(p, item, rng.randint(lo, hi), m.x, m.y)
            first = self.row.kills.get(uid, 0) == 0
            if first or rng.random() < self.ctl.cfg.trophy_chance:
                room.spawn_drop(p, loot.trophy, 1, m.x, m.y)
            p.pending.stats[f"kill.{self.cfg.enemy}"] += 1
            p.pending.stats["kill.realm_boss"] += 1
        for mm in list(room.combat.monsters.values()):  # its adds slink off
            if mm.minion_of == m.id:
                room.combat._fade(mm)
        self.hazards.clear()
        self._tell(m, ["down", self.row.key, self.cfg.name, winners[:4]], everyone=True)
        self.ctl.defeated(self.row, self.dmg_by_user)

    def _tell(self, m: Monster, ev: list[Any], everyone: bool = False) -> None:
        for p in self.room.players.values():
            if everyone or (p.m.x - m.x) ** 2 + (p.m.y - m.y) ** 2 < 40**2:
                p.ev.append([EV["BOSS"], *ev])


class Bosses:
    """The realm's boss, if one is awake (loaded by the room from realm_bosses)."""

    def __init__(self, room: RealmRoom) -> None:
        self.room = room
        self.cfg: BossesCfg = room.cfg.bosses
        self.rows: dict[str, BossRow] = {}
        self.live: dict[str, Monster] = {}  # row id → monster
        self.dirty_damage: set[tuple[str, str]] = set()
        self.done: list[tuple[BossRow, dict[str, float]]] = []  # kills, saved by the next flush
        self.reload = True  # load the waiting bosses on the next flush
        self.mail: list[tuple[str, dict[str, int], int, str]] = []  # loot for fighters who left early

    def set_rows(self, rows: list[BossRow]) -> None:
        """The waiting bosses right now (from the DB). New ones wake; vanished ones (expired) fade."""
        want = {r.id: r for r in rows}
        combat = self.room.combat
        for rid in list(self.live):
            if rid not in want:
                m = self.live.pop(rid)
                if combat is not None:
                    for mm in list(combat.monsters.values()):  # its adds go with it
                        if mm.minion_of == m.id:
                            combat._fade(mm)
                    if m.id in combat.monsters:
                        combat._fade(m)
                self.rows.pop(rid, None)
        for rid, r in want.items():
            if rid not in self.rows:
                self.rows[rid] = r
                for p in self.room.players.values():
                    p.ev.append(
                        [EV["BOSS"], "awake", r.key, self.cfg.bosses[r.key].name, r.x, r.y, r.expires_ms]
                    )

    def tick(self, t: int) -> None:
        combat = self.room.combat
        if combat is None:
            return
        for rid, r in self.rows.items():
            if rid in self.live:
                continue
            self.live[rid] = self._spawn(r, t)

    def _spawn(self, r: BossRow, t: int) -> Monster:
        combat = self.room.combat
        cfg = self.cfg.bosses[r.key]
        x, y = int(r.x), int(r.y)
        solid = self.room.grid.solid
        for rad in range(0, 12):
            spot = next(
                (
                    (x + dx, y + dy)
                    for dx in range(-rad, rad + 1)
                    for dy in range(-rad, rad + 1)
                    if not solid(x + dx, y + dy)
                    and not solid(x + dx + 1, y + dy)
                    and not solid(x + dx, y + dy + 1)
                ),
                None,
            )
            if spot is not None:
                x, y = spot
                break
        m = combat.spawn_one(cfg.enemy, x + 0.5, y + 0.5, cfg.biome, t, spread=0.0)
        m.hx, m.hy = x + 0.5, y + 0.5
        m.boss = True
        m.brain = BossBrain(self, r, cfg)
        m.hp_max = round(cfg.hp)
        m.hp = max(1.0, m.hp_max * r.hp_fraction)
        m.state = "idle"
        return m

    def defeated(self, row: BossRow, dmg: dict[str, float]) -> None:
        self.live.pop(row.id, None)
        self.rows.pop(row.id, None)
        self.done.append((row, dict(dmg)))

    def snapshot(self) -> list[dict[str, Any]]:
        """For the flush: HP shares to save."""
        out = []
        for rid, m in self.live.items():
            out.append({"id": rid, "hp_fraction": max(0.0, m.hp / m.hp_max) if m.hp_max else 1.0})
        return out

    def info(self) -> list[list[Any]]:
        """What a joining player needs for the map marker."""
        out = []
        for r in self.rows.values():
            m = self.live.get(r.id)
            x, y = (m.hx, m.hy) if m is not None else (r.x, r.y)
            out.append([r.key, self.cfg.bosses[r.key].name, x, y, r.expires_ms])
        return out
