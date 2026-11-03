"""Realm map generation from (seed, version) (PLAN §2.6, D-020). Pure and deterministic.

Generated server-side only; the client fetches chunks. v1 terrain: a cobbled hub with a well, ten
plot frames on a ring (kept clear, with a pond each), dirt roads from the hub to every plot, and
meadow everywhere else with flowers, trees (denser further out), bushes, rocks and tall grass.
Biome rings beyond the meadow arrive in Phase 4/10 (bump `version` in mapgen.yaml then).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from hearthforge.config.schemas import MapgenCfg

N, NE, E, SE, S, SW, W, NW = 1, 2, 4, 8, 16, 32, 64, 128
_NBRS = ((N, 0, -1), (NE, 1, -1), (E, 1, 0), (SE, 1, 1), (S, 0, 1), (SW, -1, 1), (W, -1, 0), (NW, -1, -1))


def reduce_mask(m: int) -> int:
    """Same rule as tools/artgen terrain.reduce_mask: corners only count when both cardinals are set."""
    if not (m & N and m & E):
        m &= ~NE
    if not (m & S and m & E):
        m &= ~SE
    if not (m & S and m & W):
        m &= ~SW
    if not (m & N and m & W):
        m &= ~NW
    return m


BLOB_MASKS = sorted({reduce_mask(m) for m in range(256)})
TILE_NAMES: list[str] = (
    [f"tile.grass.{v}" for v in range(4)]
    + [f"tile.flowers.{v}" for v in range(3)]
    + [f"tile.path.{m}" for m in BLOB_MASKS]
    + [f"tile.water.{m}" for m in BLOB_MASKS]
    + [f"tile.cobble.{m}" for m in BLOB_MASKS]
)
TILE_ID = {n: i for i, n in enumerate(TILE_NAMES)}
OBJECT_NAMES: list[str] = [
    "obj.oak.0",
    "obj.oak.1",
    "obj.oak.2",
    "obj.pine.0",
    "obj.pine.1",
    "obj.bush.0",
    "obj.bush.1",
    "obj.rock.0",
    "obj.rock.1",
    "obj.rock_big.0",
    "obj.rock_big.1",
    "obj.tall_grass.0",
    "obj.tall_grass.1",
    "obj.stump.0",
    "obj.well.0",
]
OBJECT_ID = {n: i for i, n in enumerate(OBJECT_NAMES)}
assert len(TILE_NAMES) < 256


def _mix(*vals: int) -> int:
    """splitmix64 over a tuple of ints → 64-bit hash."""
    h = 0x9E3779B97F4A7C15
    for v in vals:
        h = (h ^ (v & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
        h = (h + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = h
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        h = z ^ (z >> 31)
    return h


def rand01(seed: int, x: int, y: int, salt: int) -> float:
    return (_mix(seed, x, y, salt) >> 11) / float(1 << 53)


def value_noise(seed: int, x: float, y: float, cell: float, salt: int) -> float:
    gx, gy = x / cell, y / cell
    x0, y0 = math.floor(gx), math.floor(gy)
    fx, fy = gx - x0, gy - y0
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = rand01(seed, x0, y0, salt)
    b = rand01(seed, x0 + 1, y0, salt)
    c = rand01(seed, x0, y0 + 1, salt)
    d = rand01(seed, x0 + 1, y0 + 1, salt)
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy


@dataclass(frozen=True)
class Layout:
    size: int
    center: int
    hub_radius: int
    frame: int
    plot_origins: tuple[tuple[int, int], ...]
    pond: tuple[int, int, int, int]  # frame-local x, y, w, h


def layout(cfg: MapgenCfg) -> Layout:
    c = cfg.map_size // 2
    p = cfg.plot
    origins = []
    for i in range(p.count):
        a = -math.pi / 2 + 2 * math.pi * i / p.count
        cx = c + p.ring_radius * math.cos(a)
        cy = c + p.ring_radius * math.sin(a)
        origins.append((round(cx - p.frame / 2), round(cy - p.frame / 2)))
    return Layout(
        cfg.map_size, c, cfg.hub_radius, p.frame, tuple(origins), (p.pond.x, p.pond.y, p.pond.w, p.pond.h)
    )


class Generator:
    def __init__(self, cfg: MapgenCfg, seed: int) -> None:
        self.cfg = cfg
        self.seed = seed
        self.lay = layout(cfg)
        self.margin = cfg.plot.clear_margin

    # ── classification ─────────────────────────────────────────────────────
    def plot_at(self, x: int, y: int, margin: int = 0) -> int | None:
        f = self.lay.frame
        for i, (ox, oy) in enumerate(self.lay.plot_origins):
            if ox - margin <= x < ox + f + margin and oy - margin <= y < oy + f + margin:
                return i
        return None

    def is_water(self, x: int, y: int) -> bool:
        i = self.plot_at(x, y)
        if i is None:
            return False
        ox, oy = self.lay.plot_origins[i]
        px, py, pw, ph = self.lay.pond
        return ox + px <= x < ox + px + pw and oy + py <= y < oy + py + ph

    def is_hub(self, x: int, y: int) -> bool:
        c = self.lay.center
        wobble = (value_noise(self.seed, x, y, 6, 17) - 0.5) * 2.0
        return math.hypot(x + 0.5 - c, y + 0.5 - c) <= self.lay.hub_radius + wobble

    def is_path(self, x: int, y: int) -> bool:
        if self.is_hub(x, y) or self.plot_at(x, y) is not None:
            return False
        c = self.lay.center
        half = self.lay.frame / 2
        for ox, oy in self.lay.plot_origins:
            tx, ty = ox + half, oy + half
            # distance from tile centre to the hub→plot segment
            vx, vy = tx - c, ty - c
            wx, wy = x + 0.5 - c, y + 0.5 - c
            t = max(0.0, min(1.0, (wx * vx + wy * vy) / (vx * vx + vy * vy)))
            dx, dy = wx - t * vx, wy - t * vy
            wiggle = (value_noise(self.seed, x, y, 9, 23) - 0.5) * 1.2
            if math.hypot(dx, dy) <= 1.0 + wiggle * 0.5 and t > 0.05:
                return True
        return False

    def kind(self, x: int, y: int) -> str:
        if self.is_water(x, y):
            return "water"
        if self.is_hub(x, y):
            return "cobble"
        if self.is_path(x, y):
            return "path"
        return "grass"

    def _mask(self, x: int, y: int, k: str, kinds: dict[tuple[int, int], str]) -> int:
        m = 0
        for bit, dx, dy in _NBRS:
            p = (x + dx, y + dy)
            kk = kinds.get(p)
            if kk is None:
                kk = self.kind(*p)
            if kk == k or (k == "path" and kk == "cobble"):
                m |= bit
        return reduce_mask(m)

    # ── chunks ─────────────────────────────────────────────────────────────
    def chunk(self, cx: int, cy: int) -> dict:
        cs = self.cfg.chunk_size
        x0, y0 = cx * cs, cy * cs
        kinds = {
            (x, y): self.kind(x, y) for y in range(y0 - 1, y0 + cs + 1) for x in range(x0 - 1, x0 + cs + 1)
        }
        ground = bytearray(cs * cs)
        objects: list[list[int]] = []
        md = self.cfg.meadow
        c = self.lay.center
        for ly in range(cs):
            for lx in range(cs):
                x, y = x0 + lx, y0 + ly
                k = kinds[(x, y)]
                if k == "grass":
                    flowers = value_noise(self.seed, x, y, 7, 31) > md.flower_patch_threshold
                    r = rand01(self.seed, x, y, 1)
                    name = (
                        f"tile.flowers.{int(r * 3)}"
                        if flowers and r < 0.55
                        else f"tile.grass.{int(r * 4) % 4}"
                    )
                else:
                    name = f"tile.{k}.{self._mask(x, y, k, kinds)}"
                ground[ly * cs + lx] = TILE_ID[name]
                obj = self._object(x, y, k, c, md)
                if obj is not None:
                    objects.append([lx, ly, OBJECT_ID[obj], 0])
        return {"cx": cx, "cy": cy, "ground": bytes(ground), "objects": objects}

    def _object(self, x: int, y: int, k: str, c: int, md) -> str | None:  # noqa: ANN001
        if (x, y) == (c, c):
            return "obj.well.0"
        if k != "grass":
            return None
        i = self.plot_at(x, y)
        if i is not None:
            # inside a plot frame: keep the buildable starting square (+1 tile) clear; the reserved ring
            # around it grows nature until the owner expands (the client hides objects inside the plot)
            ox, oy = self.lay.plot_origins[i]
            lo = (self.lay.frame - self.cfg.plot.start_size) // 2 - 1
            hi = lo + self.cfg.plot.start_size + 2
            if lo <= x - ox < hi and lo <= y - oy < hi:
                return None
        elif self.plot_at(x, y, self.margin) is not None:
            return None
        dist = math.hypot(x - c, y - c)
        if dist <= self.lay.hub_radius + 2:
            return None
        # trees thicken towards the meadow's outer edge, and cluster into groves
        ring = self.cfg.plot.ring_radius + self.lay.frame
        t = max(0.0, min(1.0, (dist - ring * 0.6) / (ring * 1.2)))
        grove = value_noise(self.seed, x, y, 11, 41)
        density = (md.tree_density_near + (md.tree_density_far - md.tree_density_near) * t) * (
            0.4 + grove * 1.6
        )
        r = rand01(self.seed, x, y, 2)
        if r < density and (x + y) % 2 == 0:
            pick = rand01(self.seed, x, y, 3)
            if t > 0.5 and pick < 0.45:
                return f"obj.pine.{int(pick * 4) % 2}"
            return f"obj.oak.{int(pick * 9) % 3}"
        r -= density
        if 0 <= r < md.bush_density:
            return f"obj.bush.{int(rand01(self.seed, x, y, 4) * 2)}"
        r -= md.bush_density
        if 0 <= r < md.rock_density:
            big = rand01(self.seed, x, y, 5) < 0.3
            return (
                f"obj.rock_big.{int(rand01(self.seed, x, y, 6) * 2)}"
                if big
                else f"obj.rock.{int(rand01(self.seed, x, y, 6) * 2)}"
            )
        r -= md.rock_density
        if 0 <= r < md.tall_grass_density:
            return f"obj.tall_grass.{int(rand01(self.seed, x, y, 7) * 2)}"
        if 0 <= r - md.tall_grass_density < 0.002:
            return "obj.stump.0"
        return None


@lru_cache(maxsize=64)
def generator(cfg: MapgenCfg, seed: int) -> Generator:
    return Generator(cfg, seed)
