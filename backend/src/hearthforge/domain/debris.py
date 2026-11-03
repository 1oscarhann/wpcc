"""Wild growth on a new village plot (D-040): generated once at signup, stored on the village, tapped away
by the player for resources. Pure and deterministic for a given seed."""

from __future__ import annotations

import math

from hearthforge.config.schemas import DebrisCfg
from hearthforge.domain.mapgen import rand01, value_noise
from hearthforge.domain.plotlayout import PlotTemplate

Debris = list  # [id, kind, variant, x, y]


def generate(
    cfg: DebrisCfg, t: PlotTemplate, seed: int, path: frozenset[tuple[int, int]], density_scale: float = 1.0
) -> list[Debris]:
    kinds = list(cfg.kinds.items())
    total = sum(k.weight for _, k in kinds)
    blocked = set(path)
    for x0, y0, w, h in t.starter_rects:
        m = cfg.avoid_buildings
        for x in range(x0 - m, x0 + w + m):
            for y in range(y0 - m, y0 + h + m + 1):  # plus a row in front of the door side
                blocked.add((x, y))
    px, py, pw, ph = t.pond
    for x in range(px - 1, px + pw + 1):
        for y in range(py - 1, py + ph + 1):
            blocked.add((x, y))
    out: list[Debris] = []
    for y in range(t.lo, t.hi):
        for x in range(t.lo, t.hi):
            if (x, y) in blocked:
                continue
            if math.hypot(x + 0.5 - t.door[0], y + 0.5 - (t.door[1] - 2)) < cfg.keep_clear_radius:
                continue
            clump = 0.35 + 1.5 * value_noise(seed, x, y, 5, 3)  # debris clusters into thickets
            if rand01(seed, x, y, 1) >= cfg.density * clump * density_scale:
                continue
            r = rand01(seed, x, y, 2) * total
            name, k = kinds[-1]
            for kname, kind in kinds:
                r -= kind.weight
                if r <= 0:
                    name, k = kname, kind
                    break
            variant = int(rand01(seed, x, y, 3) * len(k.sprites)) % len(k.sprites)
            out.append([len(out), name, variant, x, y])
    return out


def roll_yields(cfg: DebrisCfg, kind: str, seed: int, debris_id: int) -> dict[str, int]:
    k = cfg.kinds[kind]
    out = dict(k.yields)
    for res, b in k.bonus.items():
        if rand01(seed, debris_id, 0, 77) < b.chance:
            out[res] = out.get(res, 0) + b.qty
    return out
