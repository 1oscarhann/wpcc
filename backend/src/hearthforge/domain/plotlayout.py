"""The shape of a village plot inside its 48×48 frame: buildable square, pond, starter buildings, the gate
facing the hub, and the dirt path from the gate to the Town Hall door. Pure and deterministic."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import lru_cache

from hearthforge.domain.placement import rotated_footprint

Rect = tuple[int, int, int, int]  # x, y, w, h (frame tiles)


@dataclass(frozen=True)
class PlotTemplate:
    frame: int
    lo: int
    hi: int  # buildable square is [lo, hi) on both axes at the starting size
    pond: Rect
    starter_rects: tuple[Rect, ...]
    door: tuple[int, int]  # tile in front of the Town Hall door


def _in(r: Rect, x: int, y: int) -> bool:
    return r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]


@lru_cache(maxsize=8)
def _template(
    frame: int, start: int, pond: Rect, starters: tuple[tuple[str, int, int, int, int], ...]
) -> PlotTemplate:
    lo = (frame - start) // 2
    rects = tuple((x, y, w, h) for _k, x, y, w, h in starters)
    th = next(((x, y, w, h) for k, x, y, w, h in starters if k == "town_hall"), rects[0])
    door = (th[0] + th[2] // 2, th[1] + th[3])
    return PlotTemplate(frame, lo, lo + start, pond, rects, door)


def template(cfg) -> PlotTemplate:  # noqa: ANN001 - GameConfig (avoid an import cycle)
    p = cfg.mapgen.plot
    starters = tuple(
        (b.key, b.x, b.y, *rotated_footprint(cfg.buildings[b.key].footprint, 0))
        for b in cfg.starter.buildings
    )
    return _template(p.frame, p.start_size, (p.pond.x, p.pond.y, p.pond.w, p.pond.h), starters)


def gate(t: PlotTemplate, plot_origin: tuple[int, int], hub: tuple[int, int]) -> tuple[int, int, str]:
    """Gate tile on the fence line (just outside the buildable square), on the side that faces the hub."""
    cx = plot_origin[0] + t.frame / 2
    cy = plot_origin[1] + t.frame / 2
    dx, dy = hub[0] - cx, hub[1] - cy
    mid = (t.lo + t.hi) // 2
    if abs(dy) >= abs(dx):
        return (mid, t.lo - 1, "N") if dy < 0 else (mid, t.hi, "S")
    return (t.lo - 1, mid, "W") if dx < 0 else (t.hi, mid, "E")


@lru_cache(maxsize=64)
def village_path(t: PlotTemplate, g: tuple[int, int, str]) -> frozenset[tuple[int, int]]:
    """A 2-wide dirt path from the gate to the Town Hall door, routed around buildings and the pond."""
    blocked = set()
    for r in (*t.starter_rects, t.pond):
        for x in range(r[0] - 1, r[0] + r[2] + 1):
            for y in range(r[1], r[1] + r[3] + (0 if r is t.pond else 0)):
                if _in(r, x, y):
                    blocked.add((x, y))
    start = (g[0], g[1])
    goal = t.door
    lo, hi = t.lo - 1, t.hi
    # BFS that prefers going straight (fewer turns → tidy L-shaped paths)
    prev: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    dirs = [(0, 1), (0, -1), (1, 0), (-1, 0)]
    q = deque([(start, (0, 0))])
    while q:
        (x, y), d = q.popleft()
        if (x, y) == goal:
            break
        order = sorted(dirs, key=lambda v: v != d)
        for dx, dy in order:
            n = (x + dx, y + dy)
            if n in prev or not (lo <= n[0] <= hi and lo <= n[1] <= hi) or n in blocked:
                continue
            prev[n] = (x, y)
            q.append((n, (dx, dy)))
    if goal not in prev:
        return frozenset()
    tiles = []
    cur: tuple[int, int] | None = goal
    while cur is not None:
        tiles.append(cur)
        cur = prev[cur]
    wide = set(tiles)
    for i, (x, y) in enumerate(tiles):
        nxt = tiles[i + 1] if i + 1 < len(tiles) else tiles[i - 1]
        horizontal = nxt[1] == y
        extra = (x, y + 1) if horizontal else (x + 1, y)
        if extra not in blocked:
            wide.add(extra)
    return frozenset(wide)
