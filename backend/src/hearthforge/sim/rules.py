"""Config → tick-based rules for the shared step (PLAN §2.5). The client gets these exact numbers in the
config bundle (`sim`), so the TypeScript predictor never converts milliseconds itself (no rounding drift)."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from typing import Any

from hearthforge.settings import REPO_ROOT

WORLD: dict[str, Any] = json.loads((REPO_ROOT / "shared" / "world.json").read_text())
BTN_LIGHT = WORLD["buttons"]["light"]
BTN_HEAVY = WORLD["buttons"]["heavy"]
BTN_ABILITY = WORLD["buttons"]["ability"]
BTN_DODGE = WORLD["buttons"]["dodge"]
BTN_POTION = WORLD["buttons"]["potion"]
BTN_OFFHAND = WORLD["buttons"]["offhand"]

ATK_NONE, ATK_LIGHT, ATK_HEAVY, ATK_ABILITY = 0, 1, 2, 3


def ticks(seconds: float, hz: int, *, min1: bool = True) -> int:
    t = int(seconds * hz + 0.5)
    return max(1, t) if min1 and seconds > 0 else t


@dataclass(frozen=True)
class MoveRule:
    dmg: float
    windup: int
    active: int
    recover: int
    shape: str  # arc | line | spin | throw | circle | shot | starfall | barrier
    range: float
    arc: float  # degrees (arc)
    width: float  # tiles (line)
    knockback: float
    stamina: float
    dash_step: float  # tiles per tick during the active phase
    hits: int = 1  # spin
    interval: int = 1  # spin, ticks between hits
    cooldown: int = 0  # ability
    speed: float = 0.0  # throw/shot, tiles per tick
    # Phase 11, server-side only (the predictor only needs the timings, dash and costs above)
    pierce: bool = False
    aoe: float = 0.0
    homing: float = 0.0
    count: int = 1
    spread: float = 0.0
    stun: int = 0  # ticks
    pull: float = 0.0
    status: str = ""
    proc: float = 0.0
    duration: int = 0  # ticks (barrier)
    sprite: str = ""
    impact: str = ""

    @property
    def length(self) -> int:
        return self.windup + self.active + self.recover


@dataclass(frozen=True)
class WeaponRule:
    light: tuple[MoveRule, ...]
    combo_window: int
    heavy: MoveRule
    ability: MoveRule


@dataclass(frozen=True)
class Rules:
    hz: int
    dt: float
    speed_tick: float
    slow: float
    st_regen: float
    st_delay: int
    dodge_ticks: int
    dodge_step: float
    dodge_cost: float
    dodge_cd: int
    dodge_iframes: int
    kb_decay: float
    hw: float
    hh: float
    max_step: float
    skin: float
    deadzone2: float
    input_max: int
    weapons: dict[str, WeaponRule]

    def bundle(self) -> dict[str, Any]:
        return asdict(self)


def resolve(cfg) -> Rules:  # noqa: ANN001 - GameConfig
    hz = cfg.game.tick_rate_hz
    c = cfg.combat
    dt = 1.0 / hz

    def extras(m) -> dict[str, Any]:  # noqa: ANN001
        return {
            "pierce": m.pierce,
            "aoe": m.aoe,
            "homing": m.homing,
            "count": m.count,
            "spread": m.spread,
            "stun": ticks(m.stun, hz, min1=False),
            "pull": m.pull,
            "status": m.status,
            "proc": m.proc,
            "duration": ticks(m.duration, hz, min1=False),
            "sprite": m.sprite or ("spear" if getattr(m, "kind", "") == "throw" else ""),
            "impact": m.impact,
        }

    def move(m) -> MoveRule:  # noqa: ANN001
        interval = ticks(m.interval, hz)
        active = max(ticks(m.active, hz), interval * m.hits if m.hits > 1 else 0)
        return MoveRule(
            dmg=m.dmg,
            windup=ticks(m.windup, hz),
            active=active,
            recover=ticks(m.recover, hz),
            shape=m.shape,
            range=m.range,
            arc=m.arc,
            width=m.width,
            knockback=m.knockback,
            stamina=m.stamina,
            dash_step=m.dash / active if m.dash else 0.0,
            hits=m.hits,
            interval=interval,
            speed=m.speed * dt,
            **extras(m),
        )

    def ability(a) -> MoveRule:  # noqa: ANN001
        interval = ticks(a.interval, hz)
        active = interval * a.hits if a.hits > 1 or a.kind == "spin" else 1
        return MoveRule(
            dmg=a.dmg,
            windup=ticks(a.windup, hz),
            active=active,
            recover=ticks(a.recover, hz),
            shape=a.kind,
            range=a.range,
            arc=360.0,
            width=a.width if a.kind == "barrier" else 0.6,
            knockback=a.knockback,
            stamina=0.0,
            dash_step=0.0,
            hits=a.hits,
            interval=interval,
            cooldown=ticks(a.cooldown, hz),
            speed=a.speed * dt,
            **extras(a),
        )

    weapons = {
        k: WeaponRule(
            light=tuple(move(m) for m in w.light),
            combo_window=ticks(w.combo_window, hz, min1=False),
            heavy=move(w.heavy),
            ability=ability(w.ability),
        )
        for k, w in c.weapons.items()
    }
    dodge_ticks = ticks(c.dodge.duration, hz)
    decay_ticks = max(1, ticks(c.knockback.decay, hz))
    return Rules(
        hz=hz,
        dt=dt,
        speed_tick=cfg.avatar.base_stats.move_speed * dt,
        slow=c.attack_move_slow,
        st_regen=c.stamina.regen_per_s * dt,
        st_delay=ticks(c.stamina.regen_delay, hz),
        dodge_ticks=dodge_ticks,
        dodge_step=c.dodge.distance / dodge_ticks,
        dodge_cost=c.dodge.stamina,
        dodge_cd=dodge_ticks + ticks(c.dodge.cooldown, hz),
        dodge_iframes=ticks(c.dodge.iframes, hz),
        # 95% of a knockback's distance is covered within `decay`
        kb_decay=math.pow(0.05, 1.0 / decay_ticks),
        hw=WORLD["player_box"]["hw"],
        hh=WORLD["player_box"]["hh"],
        max_step=WORLD["max_step"],
        skin=WORLD["skin"],
        deadzone2=WORLD["deadzone2"],
        input_max=WORLD["input_max"],
        weapons=weapons,
    )


def scaled(base: Rules, speed: float = 1.0, dodge: float = 1.0, regen: float = 1.0) -> Rules:
    """Per-player movement rules (plate armour, swift food, stamina potions). The client builds the
    same object from the MOVE_MODS event with the same three multiplications, so prediction stays exact."""
    if speed == 1.0 and dodge == 1.0 and regen == 1.0:
        return base
    return replace(
        base,
        speed_tick=base.speed_tick * speed,
        dodge_step=base.dodge_step * dodge,
        st_regen=base.st_regen * regen,
    )


def rules_from_dict(d: dict[str, Any]) -> Rules:
    """Inverse of Rules.bundle() (used by golden vectors)."""

    def mv(m: dict[str, Any]) -> MoveRule:
        return MoveRule(**m)

    weapons = {
        k: WeaponRule(
            light=tuple(mv(m) for m in w["light"]),
            combo_window=w["combo_window"],
            heavy=mv(w["heavy"]),
            ability=mv(w["ability"]),
        )
        for k, w in d["weapons"].items()
    }
    return Rules(**{**d, "weapons": weapons})
