"""Village production rates and storage caps from its buildings. Pure."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from hearthforge.config.loader import GameConfig
from hearthforge.domain.resources import MILLI


@dataclass(frozen=True)
class BuildingView:
    key: str
    level: int  # current finished level (0 while first construction runs)
    state: str  # active | constructing | upgrading


def town_hall_level(buildings: Iterable[BuildingView]) -> int:
    return max((b.level for b in buildings if b.key == "town_hall"), default=1) or 1


def rates_milli(cfg: GameConfig, buildings: Iterable[BuildingView], happiness: int = 50) -> dict[str, int]:
    """Milli-units per hour per resource. Buildings keep producing at their current level while upgrading."""
    bonus = 1.0 + 0.25 * max(0.0, (happiness - 50) / 50)
    staffing = 1.0  # villagers gate off → fully staffed (config game.gates.villagers_enabled)
    out = {k: 0 for k in cfg.resource_keys}
    for b in buildings:
        if b.level < 1:
            continue
        lv = cfg.buildings[b.key].level(b.level)
        for res, per_hour in lv.production.items():
            out[res] += round(per_hour * staffing * bonus * MILLI)
    return out


def caps_milli(cfg: GameConfig, buildings: Iterable[BuildingView]) -> dict[str, int]:
    bl = list(buildings)
    th = town_hall_level(bl)
    base = cfg.buildings["town_hall"].level(th).storage or 0
    bonus = 0
    for b in bl:
        if b.level < 1 or b.key == "town_hall":
            continue
        storage = cfg.buildings[b.key].level(b.level).storage
        if storage:
            bonus += storage
    total = base + bonus
    return {k: round(total * r.cap_fraction) * MILLI for k, r in cfg.resources.resources.items()}
