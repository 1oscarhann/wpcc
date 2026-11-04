"""Building combos (PLAN §2.2, P8, P17). Pure.

Two buildings are linked when their footprints share an edge (at least one full tile side; corners
don't count). A combo is active when one building of each required key forms a connected group in
that graph. A building can take part in several combos at once, and a village can hold several
copies of the same combo. Gear tier = the lowest level in the group.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

Rect = tuple[int, int, int, int]  # x, y, w, h


@dataclass(frozen=True)
class Node:
    id: str
    key: str
    level: int
    rect: Rect


@dataclass(frozen=True)
class ActiveCombo:
    key: str
    building_ids: tuple[str, ...]
    tier: int


def adjacent(a: Rect, b: Rect) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if ax + aw == bx or bx + bw == ax:
        return min(ay + ah, by + bh) - max(ay, by) > 0
    if ay + ah == by or by + bh == ay:
        return min(ax + aw, bx + bw) - max(ax, bx) > 0
    return False


def _connected(group: tuple[Node, ...]) -> bool:
    seen = {0}
    stack = [0]
    while stack:
        i = stack.pop()
        for j in range(len(group)):
            if j not in seen and adjacent(group[i].rect, group[j].rect):
                seen.add(j)
                stack.append(j)
    return len(seen) == len(group)


def active_combos(combos: dict, nodes: list[Node]) -> list[ActiveCombo]:  # noqa: ANN001 - {key: ComboCfg}
    """Every active combo instance. Only built buildings (level ≥ 1) count."""
    built = [n for n in nodes if n.level >= 1]
    by_key: dict[str, list[Node]] = {}
    for n in built:
        by_key.setdefault(n.key, []).append(n)
    out: list[ActiveCombo] = []
    for ck, combo in combos.items():
        pools = [by_key.get(k, []) for k in combo.buildings]
        if any(not p for p in pools):
            continue
        seen: set[tuple[str, ...]] = set()
        for group in product(*pools):
            ids = tuple(sorted(n.id for n in group))
            if len(set(ids)) != len(ids) or ids in seen:
                continue
            if _connected(group):
                seen.add(ids)
                out.append(ActiveCombo(ck, ids, min(n.level for n in group)))
    return out


def station_tier(
    active: list[ActiveCombo], combos: dict, station_id: str, gear: str
) -> tuple[int, str] | None:  # noqa: ANN001
    """Best tier this station can forge `gear` at, and the combo providing it (None = not unlocked here)."""
    best: tuple[int, str] | None = None
    for a in active:
        unlocked = station_id in a.building_ids and gear in combos[a.key].unlocks
        if unlocked and (best is None or a.tier > best[0]):
            best = (a.tier, a.key)
    return best


def new_combo_keys(combos: dict, before: list[Node], after: list[Node]) -> list[str]:  # noqa: ANN001
    """Combo keys active in `after` that weren't active in `before` (for the placement preview)."""
    had = {a.key for a in active_combos(combos, before)}
    return sorted({a.key for a in active_combos(combos, after)} - had)
