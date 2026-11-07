"""Phase 14: villagers, jobs, beauty and happiness. Pure functions over buildings (BALANCE §10, P10).

happiness = 100 × (0.35 × beauty_norm + 0.25 × housing + 0.25 × food + 0.15 × tavern)
beauty_norm = min(1, beauty / (usable plot tiles × 0.12))
housing = min(1, capacity / villagers)        food = min(1, gross food rate / (villagers × 4))
tavern = 1 if a Tavern is within 12 tiles of most homes
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from hearthforge.config.loader import GameConfig
from hearthforge.domain.placement import rotated_footprint

NATURE_DEBRIS = ("oak", "big_oak", "birch", "pine", "apple", "bush", "weeds")


@dataclass(frozen=True)
class B:
    """The bits of a building these rules look at."""

    id: str
    key: str
    x: int
    y: int
    rotation: int
    level: int


def job_slots(cfg: GameConfig, key: str, level: int) -> int:
    if level < 1:
        return 0
    b = cfg.buildings[key].cfg
    slots = b.jobs or cfg.villagers.jobs.by_category.get(b.category)
    if not slots:
        return 0
    return slots[min(level, len(slots)) - 1]


def housing(cfg: GameConfig, buildings: Iterable[B]) -> int:
    total = 0
    for b in buildings:
        if b.level >= 1:
            total += cfg.buildings[b.key].level(b.level).housing or 0
    return total


def _rect(cfg: GameConfig, b: B) -> tuple[int, int, int, int]:
    w, h = rotated_footprint(cfg.buildings[b.key].footprint, b.rotation)
    return b.x, b.y, w, h


def _ring(r: tuple[int, int, int, int]) -> set[tuple[int, int]]:
    x, y, w, h = r
    out = {(xx, y - 1) for xx in range(x, x + w)} | {(xx, y + h) for xx in range(x, x + w)}
    out |= {(x - 1, yy) for yy in range(y, y + h)} | {(x + w, yy) for yy in range(y, y + h)}
    return out


def beauty(cfg: GameConfig, buildings: list[B], debris: list[list[Any]]) -> dict[str, float]:
    """The beauty score and its parts: decorations, variety, path-linked buildings, nature left growing."""
    bc = cfg.villagers.beauty
    decor = 0.0
    kinds: set[str] = set()
    paths: set[tuple[int, int]] = set()
    for b in buildings:
        d = cfg.buildings[b.key].cfg
        if d.category != "decoration":
            continue
        decor += d.beauty
        if d.walkable and b.key.startswith("path"):
            paths.add((b.x, b.y))
        else:
            kinds.add(b.key)
    # buildings linked to the Town Hall by paths: walk the path network out from the Town Hall's edges
    connected = 0
    th = next((b for b in buildings if b.key == "town_hall"), None)
    if th is not None and paths:
        seen: set[tuple[int, int]] = set()
        q = deque(p for p in _ring(_rect(cfg, th)) if p in paths)
        seen.update(q)
        while q:
            cx, cy = q.popleft()
            for n in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if n in paths and n not in seen:
                    seen.add(n)
                    q.append(n)
        for b in buildings:
            if b.key == "town_hall" or cfg.buildings[b.key].cfg.category == "decoration" or b.level < 1:
                continue
            if _ring(_rect(cfg, b)) & seen:
                connected += 1
    nature = sum(1 for d in debris if d[1] in NATURE_DEBRIS)
    out = {
        "decor": round(decor, 1),
        "variety": len(kinds) * bc.variety,
        "connected": connected * bc.connected,
        "nature": nature * bc.nature,
    }
    out["score"] = round(sum(out.values()), 1)
    out["linked"] = connected
    return out


def tavern_ok(cfg: GameConfig, buildings: list[B]) -> bool:
    """A finished Tavern within reach (tiles, centre to centre) of most homes."""
    reach = cfg.villagers.happiness.tavern_reach
    taverns = [b for b in buildings if b.key == "tavern" and b.level >= 1]
    homes = [b for b in buildings if b.key == "house" and b.level >= 1]
    if not taverns or not homes:
        return False

    def centre(b: B) -> tuple[float, float]:
        x, y, w, h = _rect(cfg, b)
        return x + w / 2, y + h / 2

    near = sum(
        1
        for h in homes
        if any(abs(centre(h)[0] - centre(t)[0]) + abs(centre(h)[1] - centre(t)[1]) <= reach for t in taverns)
    )
    return near * 2 > len(homes)


def happiness(
    cfg: GameConfig,
    beauty_score: float,
    usable_tiles: int,
    capacity: int,
    villagers: int,
    food_rate: float,
    tavern: bool,
) -> dict[str, float]:
    """0–100 plus its four factors (each 0–1)."""
    hc = cfg.villagers.happiness
    w = hc.weights
    if villagers <= 0:
        return {
            "value": hc.empty,
            "beauty": 0.0,
            "housing": 1.0,
            "food": 1.0,
            "tavern": 1.0 if tavern else 0.0,
        }
    b_norm = min(1.0, beauty_score / max(1.0, usable_tiles * hc.beauty_per_tile))
    house = min(1.0, capacity / villagers)
    food = min(1.0, food_rate / max(1e-9, villagers * cfg.villagers.food_per_villager))
    tav = 1.0 if tavern else 0.0
    value = 100 * (w["beauty"] * b_norm + w["housing"] * house + w["food"] * food + w["tavern"] * tav)
    return {
        "value": round(value),
        "beauty": round(b_norm, 3),
        "housing": round(house, 3),
        "food": round(food, 3),
        "tavern": tav,
    }


def mood(cfg: GameConfig, h: dict[str, float]) -> str:
    """What villagers grumble (or sing) about: the weakest factor wins."""
    if h["value"] < cfg.villagers.leaving.below:
        return "leaving"
    worst = min(("food", "housing", "beauty", "tavern"), key=lambda k: h[k] + (0.3 if k == "tavern" else 0))
    if h[worst] >= 0.8:
        return "happy"
    return {"food": "hungry", "housing": "crowded", "beauty": "ugly", "tavern": "bored"}[worst]
