"""Placement rules for village buildings. Pure; coordinates are plot-frame tiles (D-033)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from hearthforge.config.loader import GameConfig


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def tiles(self) -> set[tuple[int, int]]:
        return {(self.x + dx, self.y + dy) for dx in range(self.w) for dy in range(self.h)}

    def overlaps(self, o: Rect) -> bool:
        return self.x < o.x + o.w and o.x < self.x + self.w and self.y < o.y + o.h and o.y < self.y + self.h


@dataclass(frozen=True)
class Placed:
    id: str
    key: str
    rect: Rect


def rotated_footprint(fp: tuple[int, int], rotation: int) -> tuple[int, int]:
    """Rotation 0..3. Odd rotations swap the footprint (P6); the client mirrors for 2 and 3."""
    w, h = fp
    return (h, w) if rotation % 2 else (w, h)


def usable_bounds(frame: int, size: int) -> tuple[int, int]:
    lo = (frame - size) // 2
    return lo, lo + size


def placement_errors(
    cfg: GameConfig,
    key: str,
    x: int,
    y: int,
    rotation: int,
    *,
    size: int,
    existing: Iterable[Placed],
    ignore_id: str | None = None,
    debris: Iterable[tuple[int, int]] = (),
) -> list[str]:
    """Empty list = valid. Otherwise codes: out_of_bounds | overlap | debris | on_water | needs_water."""
    if key not in cfg.buildings:
        return ["unknown_building"]
    if rotation not in (0, 1, 2, 3):
        return ["bad_rotation"]
    plot = cfg.mapgen.plot
    w, h = rotated_footprint(cfg.buildings[key].footprint, rotation)
    r = Rect(x, y, w, h)
    lo, hi = usable_bounds(plot.frame, size)
    errors: list[str] = []
    if x < lo or y < lo or x + w > hi or y + h > hi:
        errors.append("out_of_bounds")
    for p in existing:
        if p.id != ignore_id and p.rect.overlaps(r):
            errors.append("overlap")
            break
    if any(r.x <= dx < r.x + r.w and r.y <= dy < r.y + r.h for dx, dy in debris):
        errors.append("debris")
    pond = Rect(plot.pond.x, plot.pond.y, plot.pond.w, plot.pond.h)
    if r.overlaps(pond):
        errors.append("on_water")
    if cfg.buildings[key].cfg.requires_water and not touches(r, pond):
        errors.append("needs_water")
    return errors


def touches(r: Rect, other: Rect) -> bool:
    """Edge-adjacent (orthogonal) without overlapping."""
    if r.overlaps(other):
        return False
    tiles = r.tiles()
    other_tiles = other.tiles()
    return any(
        (tx + dx, ty + dy) in other_tiles for tx, ty in tiles for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
    )


def limit_errors(cfg: GameConfig, key: str, town_hall_level: int, count: int) -> list[str]:
    b = cfg.buildings[key]
    if b.cfg.unlock_town_hall > town_hall_level:
        return ["locked"]
    if count >= b.max_count(town_hall_level):
        return ["limit_reached"]
    return []


ERROR_TEXT = {
    "unknown_building": "That building doesn't exist.",
    "bad_rotation": "That rotation isn't valid.",
    "out_of_bounds": "That's outside your plot.",
    "overlap": "Something is already there.",
    "debris": "Clear the trees and rocks there first: tap them!",
    "on_water": "You can't build on the pond.",
    "needs_water": "This needs to touch the pond.",
    "locked": "Upgrade your Town Hall to unlock this.",
    "limit_reached": "You've built as many of these as your Town Hall allows.",
}
