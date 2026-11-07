"""Phase 13: monster waves on a village, simulated inside the realm room.

A wave is a few sub-waves of monsters that spawn outside the village gate and march along a flow field
to the Storehouse (or the Town Hall if there isn't one). They break off to fight anyone close by:
players, and the village's guards. Watchtowers shoot at them. Every monster that reaches the Storehouse
"gets through": it vanishes with a sack and counts toward what's stolen (worked out in the DB by
services/waves.py when the wave ends). Buildings are never damaged (BALANCE §9).
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hearthforge.domain import mapgen
from hearthforge.domain.placement import rotated_footprint
from hearthforge.realtime.protocol import ANIM, ENT, EV
from hearthforge.sim import motion as mo

if TYPE_CHECKING:
    from hearthforge.config.schemas import WaveComposition
    from hearthforge.sim.combat import Monster
    from hearthforge.sim.room import Player, RealmRoom

Q = 64
FRIENDLY = 128  # entity flag: a guard, on your side


@dataclass(frozen=True)
class _Box:
    hw: float
    hh: float
    skin: float = 0.0001


GUARD_BOX = _Box(0.3, 0.22)


@dataclass
class Guard:
    id: int
    owner: str
    name: str
    hx: float  # post
    hy: float
    x: float
    y: float
    hp: float
    hp_max: float
    dmg: float
    state: str = "idle"  # idle | chase | attack | return
    st_t: int = 0
    target: int | None = None
    dx: float = 0.0
    dy: float = 1.0
    cool: int = 0
    hurt: int = 0
    history: deque[tuple[int, float, float]] = field(default_factory=lambda: deque(maxlen=8))


@dataclass
class Tower:
    id: int
    x: float
    y: float
    dmg: float
    next_fire: int = 0


@dataclass
class Arrow:
    resolve: int
    target: int
    dmg: float


@dataclass
class WaveRun:
    wave_id: str
    owner: str
    th: int
    comp: WaveComposition
    origin: tuple[int, int]
    goal: set[tuple[int, int]]
    spawn: tuple[float, float]
    out: tuple[int, int]  # outward from the gate
    started: int
    plot: int = -1  # the plot it raids (monsters may step into this one)
    dist: dict[tuple[int, int], int] = field(default_factory=dict)
    sub: int = 0
    next_sub: int = 0
    monsters: set[int] = field(default_factory=set)
    spawned: int = 0
    killed: int = 0
    through: int = 0
    guards: dict[int, Guard] = field(default_factory=dict)
    guards_total: int = 0
    towers: list[Tower] = field(default_factory=list)
    arrows: list[Arrow] = field(default_factory=list)
    helpers: dict[str, list[Any]] = field(default_factory=dict)  # user id → [name, kills]
    ended: bool = False


class Defence:
    """All the waves running in one realm room (usually none, at most one per village)."""

    def __init__(self, room: RealmRoom) -> None:
        self.room = room
        self.cfg = room.cfg.waves
        self.runs: dict[str, WaveRun] = {}  # owner id → run
        self.results: list[dict[str, Any]] = []  # finished runs, saved by the room's next flush
        self.by_monster: dict[int, str] = {}  # wave monster id → owner

    def _t(self, seconds: float) -> int:
        return max(1, int(seconds * self.room.hz + 0.5))

    # ── starting a wave ──────────────────────────────────────────────────────
    def start(self, wave_id: str, owner: str, th: int) -> str | None:
        """Begin a wave on `owner`'s village. Returns an error code, or None."""
        if owner in self.runs:
            return "already_running"
        state = self.room.villages.get(owner)
        if state is None:
            return "no_village"
        comp = self.cfg.composition.get(min(5, max(2, th)))
        if comp is None:
            return "no_composition"
        ox, oy = state["origin"]
        defs = self.room.cfg.buildings
        target = next((b for b in state["buildings"] if b["key"] == "storehouse"), None) or next(
            (b for b in state["buildings"] if b["key"] == "town_hall"), None
        )
        if target is None:
            return "no_target"
        w, h = rotated_footprint(defs[target["key"]].footprint, target["rotation"])
        bx, by = ox + target["x"], oy + target["y"]
        ring = {(x, by - 1) for x in range(bx, bx + w)} | {(x, by + h) for x in range(bx, bx + w)}
        ring |= {(bx - 1, y) for y in range(by, by + h)} | {(bx + w, y) for y in range(by, by + h)}
        goal = {g for g in ring if not self.room.grid.solid(*g)}
        gx, gy, side = state["gate"]
        out = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}[side]
        d = self.cfg.spawn_distance
        sx, sy = ox + gx + 1 + out[0] * d, oy + gy + 1 + out[1] * d
        run = WaveRun(
            wave_id=wave_id,
            owner=owner,
            th=th,
            comp=comp,
            origin=(ox, oy),
            goal=goal,
            spawn=(sx, sy),
            out=out,
            started=self.room.tick_no,
            next_sub=self.room.tick_no + self._t(2.0),
        )
        origins = mapgen.layout(self.room.cfg.mapgen).plot_origins
        run.plot = origins.index(tuple(state["origin"])) if tuple(state["origin"]) in origins else -1
        self._flow(run, state)
        self._muster(run, state)
        self.runs[owner] = run
        self._tell(run, ["start", run.comp.subwaves, run.guards_total, len(run.towers)])
        return None

    def _flow(self, run: WaveRun, state: dict[str, Any]) -> None:
        """BFS distances to the goal over the village and a margin around it (walls, fence and buildings
        block; the gate lets them in)."""
        frame = state["frame"]
        ox, oy = run.origin
        m = int(self.cfg.spawn_distance) + 6
        x0, x1, y0, y1 = ox - m, ox + frame + m, oy - m, oy + frame + m
        solid = self.room.grid.solid
        dist: dict[tuple[int, int], int] = {}
        q: deque[tuple[int, int]] = deque()
        for g in run.goal:
            dist[g] = 0
            q.append(g)
        while q:
            cx, cy = q.popleft()
            dd = dist[(cx, cy)] + 1
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if not (x0 <= nx < x1 and y0 <= ny < y1) or (nx, ny) in dist or solid(nx, ny):
                    continue
                dist[(nx, ny)] = dd
                q.append((nx, ny))
        run.dist = dist
        # make sure the spawn spot is on the field (step back toward the gate until it is)
        sx, sy = run.spawn
        for k in range(int(self.cfg.spawn_distance) + 4):
            tx, ty = int(sx - run.out[0] * k), int(sy - run.out[1] * k)
            if (tx, ty) in dist:
                run.spawn = (tx + 0.5, ty + 0.5)
                break

    def _muster(self, run: WaveRun, state: dict[str, Any]) -> None:
        """Guards fall in at their posts; watchtowers get their bows."""
        ox, oy = run.origin
        defs = self.room.cfg.buildings
        g = self.cfg.guards
        villagers = state.get("villagers")
        for b in state["buildings"]:
            if b["level"] < 1:
                continue
            w, h = rotated_footprint(defs[b["key"]].footprint, b["rotation"])
            if b["key"] == "guard_post":
                slots = (defs["guard_post"].cfg.jobs or [1])[b["level"] - 1]
                if villagers is None:
                    names = [f"Guard {i + 1}" for i in range(slots)]
                else:
                    names = [v["name"] for v in villagers if v.get("job") == b["id"]][:slots]
                mult = 1 + g.per_level * (b["level"] - 1)
                for i, name in enumerate(names):
                    hx = ox + b["x"] + w / 2 + (i - (len(names) - 1) / 2) * 0.9
                    hy = oy + b["y"] + h + 0.6
                    gid = self.room.new_id()
                    run.guards[gid] = Guard(
                        gid, run.owner, name, hx, hy, hx, hy, g.hp * mult, g.hp * mult, g.dmg * mult
                    )
                run.guards_total += len(names)
            elif b["key"] == "watchtower" and defs["watchtower"].cfg.tower_dmg:
                dmg = defs["watchtower"].cfg.tower_dmg[b["level"] - 1]
                run.towers.append(Tower(self.room.new_id(), ox + b["x"] + w / 2, oy + b["y"] + h - 0.4, dmg))

    # ── the tick ─────────────────────────────────────────────────────────────
    def tick(self, t: int) -> None:
        for run in list(self.runs.values()):
            self._spawn_subwave(run, t)
            self._guards(run, t)
            self._towers(run, t)
            self._check_end(run, t)

    def _spawn_subwave(self, run: WaveRun, t: int) -> None:
        if run.sub >= run.comp.subwaves or t < run.next_sub:
            return
        combat = self.room.combat
        if combat is None:
            return
        state = self.room.villages.get(run.owner)
        if state is not None and run.sub > 0:
            self._flow(run, state)  # the village may have changed since the last sub-wave
        rng = self.room.rng
        comp = run.comp
        keys = list(comp.roster)
        weights = [comp.roster[k] for k in keys]
        last = run.sub == comp.subwaves - 1
        elites = comp.elites if last else (1 if comp.elites > 1 and run.sub == comp.subwaves // 2 else 0)
        n = comp.size
        for i in range(n):
            key = rng.choices(keys, weights)[0]
            m = combat.spawn_one(key, run.spawn[0], run.spawn[1], comp.biome, t, elite=i < elites, spread=1.4)
            self._enlist(run, m)
        if last and comp.miniboss:
            m = combat.spawn_one(comp.miniboss, run.spawn[0], run.spawn[1], comp.biome, t, elite=True)
            m.hp = m.hp_max = round(m.hp_max * self.cfg.miniboss_hp)
            self._enlist(run, m)
        run.sub += 1
        run.next_sub = t + self._t(self.cfg.subwave_gap)
        self._tell(run, ["sub", run.sub, run.comp.subwaves, len(run.monsters)])
        sx, sy = run.spawn
        combat._broadcast(sx, sy, [EV["SFX"], "horn", sx, sy], r=60)

    def _enlist(self, run: WaveRun, m: Monster) -> None:
        m.wave = run.owner
        m.hp = m.hp_max = max(1, round(m.hp_max * self.cfg.hp_mult))
        m.state, m.st_t = "march", 0
        run.monsters.add(m.id)
        run.spawned += 1
        self.by_monster[m.id] = run.owner

    def _check_end(self, run: WaveRun, t: int) -> None:
        combat = self.room.combat
        alive = {mid for mid in run.monsters if combat is not None and mid in combat.monsters}
        run.monsters = alive
        timeout = t - run.started > self._t(self.cfg.max_duration)
        if run.sub < run.comp.subwaves and not timeout:
            return
        if alive and not timeout:
            return
        for mid in list(alive):  # stragglers give up and slink off
            m = combat.monsters.get(mid) if combat is not None else None
            if m is not None:
                combat._broadcast(m.x, m.y, [EV["DEATH"], m.id, m.x, m.y, m.key, 2])
                combat._remove(m, killed=False)
            self.by_monster.pop(mid, None)
        self._finish(run)

    def _finish(self, run: WaveRun) -> None:
        run.ended = True
        self.runs.pop(run.owner, None)
        for g in run.guards.values():  # everyone heads home; fallen guards are back next time
            self.room.combat._broadcast(g.x, g.y, [EV["DEATH"], g.id, g.x, g.y, "guard", 2])
        frac = run.through / run.spawned if run.spawned else 0.0
        self.results.append(
            {
                "wave_id": run.wave_id,
                "owner": run.owner,
                "th": run.th,
                "biome": run.comp.biome,
                "spawned": run.spawned,
                "killed": run.killed,
                "through": run.through,
                "through_frac": frac,
                "won": frac < self.cfg.win_if_through_below,
                "guards": run.guards_total,
                "guards_left": sum(1 for g in run.guards.values() if g.hp > 0),
                "towers": len(run.towers),
                "helpers": [[name, kills] for uid, (name, kills) in run.helpers.items() if uid != run.owner],
            }
        )

    def _tell(self, run: WaveRun, ev: list[Any]) -> None:
        """Wave news goes to the owner and anyone near the village."""
        state = self.room.villages.get(run.owner)
        cx = run.origin[0] + (state["frame"] / 2 if state else 24)
        cy = run.origin[1] + (state["frame"] / 2 if state else 24)
        for p in self.room.players.values():
            if str(p.user_id) == run.owner or (abs(p.m.x - cx) < 60 and abs(p.m.y - cy) < 60):
                p.ev.append([EV["WAVE"], run.owner, *ev])

    # ── wave monsters ────────────────────────────────────────────────────────
    def wave_ai(self, m: Monster, t: int) -> None:
        """March on the Storehouse; fight whoever gets in the way. Called by Combat._ai."""
        combat = self.room.combat
        run = self.runs.get(m.wave)
        if run is None:
            return
        a = m.cfg.attack
        if m.state == "windup":
            if m.st_t >= combat._t(a.windup):
                m.state, m.st_t = "active", 0
                m.hit_players.clear()
                if a.shape == "line":
                    self._strike(m, t)
            return
        if m.state == "active":
            steps = combat._t(a.active)
            if a.lunge:
                combat._move(m, m.dx * a.lunge / steps, m.dy * a.lunge / steps)
            if m.st_t >= steps:
                if a.shape == "circle":
                    self._strike(m, t)
                m.state, m.st_t = "recover", 0
            return
        if m.state == "recover":
            if m.st_t >= combat._t(a.recover):
                m.state, m.st_t = "chase" if (m.target or m.gtarget) else "march", 0
            return
        # pick a fight with anyone close (players first)
        if t % 4 == m.id % 4:
            self._pick(m, run)
        tx, ty = self._target_pos(m, run)
        if tx is not None and ty is not None:
            d = math.hypot(tx - m.x, ty - m.y)
            if d > self.cfg.leash:
                m.target = m.gtarget = None
                m.state = "march"
            elif d <= a.trigger:
                self._windup(m, tx, ty)
                return
            else:
                m.state = "chase"
                combat._step_toward(m, tx, ty, 1.0)
                return
        m.state = "march"
        # follow the flow field
        cx, cy = int(m.x), int(m.y)
        if (cx, cy) in run.goal or self._near_goal(m, run):
            self._through(m, run)
            return
        here = run.dist.get((cx, cy))
        if here is None:  # off the field: head for the gate, then the storehouse
            combat._step_toward(m, run.spawn[0], run.spawn[1], 1.0)
            return
        best = None
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            dd = run.dist.get((nx, ny))
            if dd is not None and dd < here and (best is None or dd < best[0]):
                best = (dd, nx, ny)
        if best is None:
            self._through(m, run)  # standing next to the goal already
            return
        combat._step_toward(m, best[1] + 0.5, best[2] + 0.5, 1.0)

    def _near_goal(self, m: Monster, run: WaveRun) -> bool:
        return any((g[0] + 0.5 - m.x) ** 2 + (g[1] + 0.5 - m.y) ** 2 < 0.5 for g in run.goal)

    def _pick(self, m: Monster, run: WaveRun) -> None:
        combat = self.room.combat
        aggro2 = self.cfg.aggro**2
        if m.target is not None:
            p = self.room.players.get(m.target)
            if p is None or p.ko > 0 or (p.m.x - m.x) ** 2 + (p.m.y - m.y) ** 2 > self.cfg.leash**2:
                m.target = None
        if m.gtarget is not None:
            g = run.guards.get(m.gtarget)
            if g is None or g.hp <= 0:
                m.gtarget = None
        if m.target is not None or m.gtarget is not None:
            return
        near = [p for p in combat._players_near(m.x, m.y, self.cfg.aggro) if not p.dungeon]
        if near:
            m.target = min(near, key=lambda p: (p.m.x - m.x) ** 2 + (p.m.y - m.y) ** 2).eid
            return
        gs = [g for g in run.guards.values() if g.hp > 0 and (g.x - m.x) ** 2 + (g.y - m.y) ** 2 <= aggro2]
        if gs:
            m.gtarget = min(gs, key=lambda g: (g.x - m.x) ** 2 + (g.y - m.y) ** 2).id

    def _target_pos(self, m: Monster, run: WaveRun) -> tuple[float | None, float | None]:
        if m.target is not None:
            p = self.room.players.get(m.target)
            if p is not None and p.ko == 0:
                return p.m.x, p.m.y
            m.target = None
        if m.gtarget is not None:
            g = run.guards.get(m.gtarget)
            if g is not None and g.hp > 0:
                return g.x, g.y
            m.gtarget = None
        return None, None

    def _windup(self, m: Monster, tx: float, ty: float) -> None:
        a = m.cfg.attack
        dx, dy = tx - m.x, ty - m.y
        d = math.hypot(dx, dy) or 1.0
        m.dx, m.dy = dx / d, dy / d
        m.state, m.st_t = "windup", 0
        if a.shape == "circle":
            reach = min(d, a.lunge if a.lunge else 0.0)
            m.ox, m.oy = m.x + m.dx * reach, m.y + m.dy * reach
            ev = [EV["TELEGRAPH"], m.id, 0, m.ox, m.oy, m.dx, m.dy, a.range, a.range, int(a.windup * 1000)]
        else:
            m.ox, m.oy = m.x, m.y
            length = max(a.range, a.lunge)
            ev = [EV["TELEGRAPH"], m.id, 1, m.ox, m.oy, m.dx, m.dy, length, a.width, int(a.windup * 1000)]
        self.room.combat._broadcast(m.x, m.y, ev)

    def _strike(self, m: Monster, t: int) -> None:
        """The attack lands: players (with dodge grace, via Combat) and guards in the shape."""
        combat = self.room.combat
        combat._check_hit(m, t)
        run = self.runs.get(m.wave)
        if run is None:
            return
        a = m.cfg.attack
        for g in run.guards.values():
            if g.hp <= 0:
                continue
            px, py = g.x - m.ox, g.y - m.oy
            if a.shape == "circle":
                inside = px * px + py * py <= (a.range + 0.25) ** 2
            else:
                length = max(a.range, a.lunge)
                along = px * m.dx + py * m.dy
                across = abs(px * -m.dy + py * m.dx)
                inside = -0.3 <= along <= length + 0.3 and across <= a.width / 2 + 0.25
            if inside:
                self._hurt_guard(run, g, m.dmg, m.id)

    def _through(self, m: Monster, run: WaveRun) -> None:
        combat = self.room.combat
        run.through += 1
        combat._broadcast(m.x, m.y, [EV["DEATH"], m.id, m.x, m.y, m.key, 2])
        self._tell(run, ["steal", m.x, m.y, run.through])
        combat._remove(m, killed=False)
        run.monsters.discard(m.id)
        self.by_monster.pop(m.id, None)

    def on_kill(self, m: Monster, killer: Player | None) -> None:
        """A wave monster died (to a player, a guard or a tower)."""
        owner = self.by_monster.pop(m.id, None)
        run = self.runs.get(owner) if owner else None
        if run is None:
            return
        run.killed += 1
        run.monsters.discard(m.id)
        if killer is not None:
            h = run.helpers.setdefault(str(killer.user_id), [killer.name, 0])
            h[1] += 1

    # ── guards ───────────────────────────────────────────────────────────────
    def _guards(self, run: WaveRun, t: int) -> None:
        combat = self.room.combat
        if combat is None:
            return
        g_cfg = self.cfg.guards
        speed = g_cfg.speed / self.room.hz
        for g in run.guards.values():
            if g.hp <= 0:
                continue
            g.st_t += 1
            g.cool = max(0, g.cool - 1)
            g.hurt = max(0, g.hurt - 1)
            g.history.append((t, g.x, g.y))
            m = combat.monsters.get(g.target) if g.target is not None else None
            if m is None or m.hp <= 0 or math.hypot(m.x - g.hx, m.y - g.hy) > g_cfg.leash:
                g.target = None
                m = None
            if m is None and t % 4 == g.id % 4:
                best = None
                for mid in run.monsters:
                    mm = combat.monsters.get(mid)
                    if mm is None:
                        continue
                    d2 = (mm.x - g.hx) ** 2 + (mm.y - g.hy) ** 2
                    if d2 <= g_cfg.aggro**2 and (best is None or d2 < best[0]):
                        best = (d2, mm)
                if best is not None:
                    m = best[1]
                    g.target = m.id
            if m is None:
                d = math.hypot(g.hx - g.x, g.hy - g.y)
                if d > 0.2:
                    g.state = "return"
                    self._gstep(g, g.hx, g.hy, speed)
                else:
                    g.state = "idle"
                    g.hp = min(g.hp_max, g.hp + g.hp_max * 0.01)  # a breather at the post
                continue
            d = math.hypot(m.x - g.x, m.y - g.y)
            if d > g_cfg.range:
                g.state = "chase"
                self._gstep(g, m.x, m.y, speed)
                continue
            g.dx, g.dy = (m.x - g.x) / (d or 1), (m.y - g.y) / (d or 1)
            if g.cool == 0:
                g.state, g.st_t = "attack", 0
                g.cool = self._t(g_cfg.attack_every)
                self._guard_hit(run, g, m)
            elif g.st_t > 6:
                g.state = "chase"

    def _gstep(self, g: Guard, tx: float, ty: float, speed: float) -> None:
        dx, dy = tx - g.x, ty - g.y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return
        sp = min(d, speed)
        g.dx, g.dy = dx / d, dy / d
        solid = self.room.grid.solid
        nx = mo._slide_x(g.x, g.y, g.dx * sp, GUARD_BOX, solid)  # type: ignore[arg-type]
        ny = mo._slide_y(nx, g.y, g.dy * sp, GUARD_BOX, solid)  # type: ignore[arg-type]
        g.x, g.y = nx, ny

    def _guard_hit(self, run: WaveRun, g: Guard, m: Monster) -> None:
        combat = self.room.combat
        dmg = max(1, round(g.dmg * (1 - m.defence / (m.defence + 100))))
        m.hp -= dmg
        m.hurt = 4
        kx, ky = m.x - g.x, m.y - g.y
        kd = math.hypot(kx, ky) or 1
        m.kbx += kx / kd * 0.15
        m.kby += ky / kd * 0.15
        if m.gtarget is None and m.target is None:
            m.gtarget = g.id  # hit back
        combat._broadcast(m.x, m.y, [EV["HIT"], g.id, m.id, dmg, 0, 0])
        if m.hp <= 0:
            self._monster_down(m)

    def _monster_down(self, m: Monster) -> None:
        combat = self.room.combat
        combat._broadcast(m.x, m.y, [EV["DEATH"], m.id, m.x, m.y, m.key, 1 if m.elite else 0])
        combat._remove(m, killed=False)
        self.on_kill(m, None)

    def _hurt_guard(self, run: WaveRun, g: Guard, dmg: float, src: int) -> None:
        g.hp -= dmg
        g.hurt = 4
        self.room.combat._broadcast(g.x, g.y, [EV["HIT"], src, g.id, round(dmg), 0, 0])
        if g.hp <= 0:
            self.room.combat._broadcast(g.x, g.y, [EV["DEATH"], g.id, g.x, g.y, "guard", 2])
            self._tell(run, ["guard_down", g.name])

    # ── watchtowers ──────────────────────────────────────────────────────────
    def _towers(self, run: WaveRun, t: int) -> None:
        combat = self.room.combat
        if combat is None:
            return
        keep = []
        for a in run.arrows:
            if a.resolve > t:
                keep.append(a)
                continue
            m = combat.monsters.get(a.target)
            if m is None or m.hp <= 0:
                continue
            dmg = max(1, round(a.dmg * (1 - m.defence / (m.defence + 100))))
            m.hp -= dmg
            m.hurt = 4
            combat._broadcast(m.x, m.y, [EV["HIT"], 0, m.id, dmg, 0, 0])
            if m.hp <= 0:
                self._monster_down(m)
        run.arrows = keep
        r2 = self.cfg.towers.range**2
        for tw in run.towers:
            if t < tw.next_fire:
                continue
            best = None
            for mid in run.monsters:
                m = combat.monsters.get(mid)
                if m is None:
                    continue
                d2 = (m.x - tw.x) ** 2 + (m.y - tw.y) ** 2
                if d2 <= r2 and (best is None or d2 < best[0]):
                    best = (d2, m)
            if best is None:
                continue
            m = best[1]
            tw.next_fire = t + self._t(self.cfg.towers.every)
            flight = max(2, int(math.sqrt(best[0]) * 1.2))
            run.arrows.append(Arrow(t + flight, m.id, tw.dmg))
            combat._broadcast(tw.x, tw.y, [EV["TOWER"], tw.x, tw.y - 1.6, m.x, m.y - 0.4, flight * 50])

    # ── for the wire ─────────────────────────────────────────────────────────
    def entities(self, p: Player, x0: float, x1: float, y0: float, y1: float) -> list[list[Any]]:
        out: list[list[Any]] = []
        for run in self.runs.values():
            for g in run.guards.values():
                if g.hp <= 0 or not (x0 <= g.x <= x1 and y0 <= g.y <= y1):
                    continue
                anim = {"idle": ANIM["idle"], "attack": ANIM["active"]}.get(g.state, ANIM["walk"])
                out.append(
                    [
                        g.id,
                        ENT["monster"],
                        "guard",
                        round(g.x * Q),
                        round(g.y * Q),
                        round(g.dx * 100),
                        round(g.dy * 100),
                        anim,
                        g.st_t,
                        int(255 * max(0.0, g.hp) / g.hp_max),
                        FRIENDLY | (8 if g.hurt else 0),
                    ]
                )
        return out

    def guard_names(self) -> dict[int, str]:
        return {g.id: g.name for run in self.runs.values() for g in run.guards.values()}

    def home_spot(self, owner: str) -> tuple[float, float] | None:
        """Just inside the gate of this village (the "Defend!" hop)."""
        state = self.room.villages.get(owner)
        if state is None:
            return None
        ox, oy = state["origin"]
        gx, gy, side = state["gate"]
        inward = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}[side]
        x, y = ox + gx + 1 + inward[0] * 2, oy + gy + 0.5 + inward[1] * 2
        if side in ("W", "E"):
            x, y = ox + gx + 0.5 + inward[0] * 2, oy + gy + 1 + inward[1] * 2
        return x, y

    def plot_of(self, owner: str) -> int:
        run = self.runs.get(owner)
        return run.plot if run is not None else -2

    def busy(self) -> bool:
        return bool(self.runs)


def new_wave_id() -> str:
    return str(uuid.uuid4())
