"""The shared fixed-step player update (PLAN §2.5). frontend/src/sim/motion.ts is a line-for-line twin,
checked against /shared/golden/movement.json by both test suites.

Determinism rules for both ports: only + − × ÷ and sqrt (IEEE-exact in CPython and V8), no trig,
no hypot, the same operation order, floor/ceil on doubles. Everything time-based is in whole ticks.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, fields

from hearthforge.sim.rules import (
    ATK_ABILITY,
    ATK_HEAVY,
    ATK_LIGHT,
    ATK_NONE,
    BTN_ABILITY,
    BTN_DODGE,
    BTN_HEAVY,
    BTN_LIGHT,
    MoveRule,
    Rules,
    WeaponRule,
)

Solid = Callable[[int, int], bool]


@dataclass(slots=True)
class Motion:
    x: float
    y: float
    st: float  # stamina
    st_max: float
    fx: float = 0.0  # facing (unit vector)
    fy: float = 1.0
    st_delay: int = 0  # ticks before stamina regenerates
    dodge: int = 0  # dodge ticks left
    ddx: float = 0.0  # dodge velocity, tiles per tick
    ddy: float = 0.0
    dodge_cd: int = 0
    atk: int = ATK_NONE  # attack in progress
    atk_i: int = 0  # which light swing (combo index)
    atk_t: int = 0  # ticks since the attack started
    ax: float = 0.0  # locked attack direction (unit)
    ay: float = 1.0
    combo: int = 0  # next light swing index
    combo_t: int = 0  # ticks left to continue the combo
    ab_cd: int = 0  # ability cooldown ticks
    kbx: float = 0.0  # knockback velocity, tiles per tick
    kby: float = 0.0

    def to_list(self) -> list[float | int]:
        return [getattr(self, f.name) for f in fields(self)]

    @classmethod
    def from_list(cls, v: list) -> Motion:  # noqa: ANN001
        return cls(*v)


MOTION_FIELDS = [f.name for f in fields(Motion)]


def current_move(m: Motion, w: WeaponRule) -> MoveRule | None:
    if m.atk == ATK_LIGHT:
        return w.light[m.atk_i]
    if m.atk == ATK_HEAVY:
        return w.heavy
    if m.atk == ATK_ABILITY:
        return w.ability
    return None


def _unit(x: float, y: float) -> tuple[float, float, float]:
    l2 = x * x + y * y
    if l2 <= 0.0:
        return 0.0, 0.0, 0.0
    ln = math.sqrt(l2)
    return x / ln, y / ln, l2


def _slide_x(x: float, y: float, dx: float, r: Rules, solid: Solid) -> float:
    if dx == 0.0:
        return x
    nx = x + dx
    r0 = math.floor(y - r.hh)
    r1 = math.ceil(y + r.hh) - 1
    if dx > 0.0:
        cur = math.ceil(x + r.hw) - 1
        new = math.ceil(nx + r.hw) - 1
        col = cur + 1
        while col <= new:
            row = r0
            while row <= r1:
                if solid(col, row):
                    return col - r.hw - r.skin
                row += 1
            col += 1
    else:
        cur = math.floor(x - r.hw)
        new = math.floor(nx - r.hw)
        col = cur - 1
        while col >= new:
            row = r0
            while row <= r1:
                if solid(col, row):
                    return col + 1 + r.hw + r.skin
                row += 1
            col -= 1
    return nx


def _slide_y(x: float, y: float, dy: float, r: Rules, solid: Solid) -> float:
    if dy == 0.0:
        return y
    ny = y + dy
    c0 = math.floor(x - r.hw)
    c1 = math.ceil(x + r.hw) - 1
    if dy > 0.0:
        cur = math.ceil(y + r.hh) - 1
        new = math.ceil(ny + r.hh) - 1
        row = cur + 1
        while row <= new:
            col = c0
            while col <= c1:
                if solid(col, row):
                    return row - r.hh - r.skin
                col += 1
            row += 1
    else:
        cur = math.floor(y - r.hh)
        new = math.floor(ny - r.hh)
        row = cur - 1
        while row >= new:
            col = c0
            while col <= c1:
                if solid(col, row):
                    return row + 1 + r.hh + r.skin
                col += 1
            row -= 1
    return ny


def _clamp(v: float, lim: float) -> float:
    return lim if v > lim else (-lim if v < -lim else v)


def step(
    m: Motion, mx: int, my: int, ax: int, ay: int, buttons: int, r: Rules, w: WeaponRule, solid: Solid
) -> int:
    """Advance one tick. Returns the attack kind that *started* this tick (0 if none), so the server
    can spend stamina/cooldowns once and schedule hits."""
    # input → move vector (analog magnitude kept below full tilt, clamped to 1 above it)
    vx = mx / r.input_max
    vy = my / r.input_max
    l2 = vx * vx + vy * vy
    moving = l2 > r.deadzone2
    if l2 > 1.0:
        ln = math.sqrt(l2)
        vx = vx / ln
        vy = vy / ln
    aux, auy, al2 = _unit(float(ax), float(ay))
    if al2 <= 0.0:
        aux, auy = m.fx, m.fy

    # timers
    if m.dodge_cd > 0:
        m.dodge_cd -= 1
    if m.ab_cd > 0:
        m.ab_cd -= 1
    if m.combo_t > 0:
        m.combo_t -= 1
        if m.combo_t == 0:
            m.combo = 0

    # attack progression
    if m.atk != ATK_NONE:
        m.atk_t += 1
        mv = current_move(m, w)
        if mv is not None and m.atk_t >= mv.length:
            if m.atk == ATK_LIGHT:
                m.combo_t = w.combo_window
                if m.combo_t == 0:
                    m.combo = 0
            m.atk = ATK_NONE
            m.atk_t = 0

    started = ATK_NONE
    # dodge cancels anything (favour the player)
    if buttons & BTN_DODGE and m.dodge == 0 and m.dodge_cd == 0 and m.st >= r.dodge_cost:
        if moving:
            dx, dy, _ = _unit(vx, vy)
        else:
            dx, dy = m.fx, m.fy
        m.dodge = r.dodge_ticks
        m.ddx = dx * r.dodge_step
        m.ddy = dy * r.dodge_step
        m.st -= r.dodge_cost
        m.st_delay = r.st_delay
        m.dodge_cd = r.dodge_cd
        m.atk = ATK_NONE
        m.atk_t = 0
    elif m.dodge == 0 and m.atk == ATK_NONE:
        if buttons & BTN_ABILITY and m.ab_cd == 0:
            started = ATK_ABILITY
            m.ab_cd = w.ability.cooldown
        elif buttons & BTN_HEAVY and m.st >= w.heavy.stamina:
            started = ATK_HEAVY
            m.st -= w.heavy.stamina
            m.st_delay = r.st_delay
        elif buttons & BTN_LIGHT:
            started = ATK_LIGHT
            m.atk_i = m.combo if m.combo_t > 0 else 0
            m.combo = (m.atk_i + 1) % len(w.light)
            m.combo_t = 0
        if started != ATK_NONE:
            m.atk = started
            m.atk_t = 0
            m.ax, m.ay = aux, auy
            m.fx, m.fy = aux, auy

    # velocity
    if m.dodge > 0:
        px, py = m.ddx, m.ddy
        m.dodge -= 1
    else:
        mv = current_move(m, w)
        if mv is not None and mv.dash_step > 0.0 and mv.windup <= m.atk_t < mv.windup + mv.active:
            px, py = m.ax * mv.dash_step, m.ay * mv.dash_step
        else:
            sp = r.speed_tick * (r.slow if m.atk != ATK_NONE else 1.0)
            px, py = (vx * sp, vy * sp) if moving else (0.0, 0.0)
            if moving and m.atk == ATK_NONE:
                m.fx, m.fy, _ = _unit(vx, vy)
    px += m.kbx
    py += m.kby
    m.kbx *= r.kb_decay
    m.kby *= r.kb_decay
    if m.kbx * m.kbx + m.kby * m.kby < 1e-6:
        m.kbx = 0.0
        m.kby = 0.0
    px = _clamp(px, r.max_step)
    py = _clamp(py, r.max_step)
    m.x = _slide_x(m.x, m.y, px, r, solid)
    m.y = _slide_y(m.x, m.y, py, r, solid)

    # stamina
    if m.st_delay > 0:
        m.st_delay -= 1
    elif m.st < m.st_max:
        m.st = min(m.st_max, m.st + r.st_regen)
    return started
