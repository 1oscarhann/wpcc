"""Solid rectangles a village adds to the realm map in Avatar Mode: buildings, the fence (open at the gate)
and solid debris. Sent to clients in ROOM_JOINED / BLOCKS so both sides collide against the same tiles."""

from __future__ import annotations

from typing import Any

from hearthforge.domain.placement import rotated_footprint
from hearthforge.sim.rules import WORLD

Rect = tuple[int, int, int, int]
_SOLID_OBJ = tuple(WORLD["solid_objects"])


def solid_object(name: str) -> bool:
    return name.startswith(_SOLID_OBJ)


def village_blocks(cfg, state: dict[str, Any]) -> list[Rect]:  # noqa: ANN001 - GameConfig
    """`state` is a village_state() dict (frame coordinates + origin)."""
    ox, oy = state["origin"]
    frame, size = state["frame"], state["size"]
    lo = (frame - size) // 2
    hi = lo + size
    out: list[Rect] = []
    for b in state["buildings"]:
        w, h = rotated_footprint(cfg.buildings[b["key"]].footprint, b["rotation"])
        out.append((ox + b["x"], oy + b["y"], w, h))
    gx, gy, side = state["gate"]
    gap = {(gx, gy), (gx + 1, gy)} if side in ("N", "S") else {(gx, gy), (gx, gy + 1)}
    ring = [(x, y) for x in range(lo - 1, hi + 1) for y in (lo - 1, hi)]
    ring += [(x, y) for y in range(lo, hi) for x in (lo - 1, hi)]
    out.extend((ox + x, oy + y, 1, 1) for x, y in ring if (x, y) not in gap)
    for _id, kind, variant, x, y in state["debris"]:
        k = cfg.debris.kinds.get(kind)
        if k and solid_object(k.sprites[variant]):
            out.append((ox + x, oy + y, 1, 1))
    return out
