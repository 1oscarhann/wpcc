"""Realm map generation from (seed, version) (PLAN §2.6, D-020). Pure and deterministic.

Generated server-side only; the client fetches chunks. v1 terrain:
- a cobbled hub with a well, and lamp-lit dirt roads to every plot's gate;
- ten plot frames on a ring; each is a forest clearing around a fenced, buildable square with a pond and a
  path from the gate to the Town Hall. Unclaimed plots are overgrown (their wild growth is flagged so the
  client hides it once someone moves in and their own village debris takes over);
- a meadow everywhere else with forest groves, rock outcrops, flower meadows and natural ponds with reeds
  and lily pads.
- the Whispering Forest from `forest.radius` outward (Phase 4): dark forest floor, dense old trees with
  ferns and webs, sunny clearings, and dirt trails leading out from the meadow between the plots.
- Phase 10 (v4): rings past the forest. Stonepeak (rocky ground, boulders, crags, star veins), Murkwater
  Swamp (mud, many murky pools, dead trees, venom blooms), the Frozen North (snow, ice lakes, snowy pines,
  frost spires) and the Ashen Wastes (ash, lava pools, charred trees, obsidian, lava vents). Ring edges
  are warped by noise and dithered so they blend. Moonpetals hide past the meadow (night only).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from hearthforge.config.schemas import MapgenCfg

N, NE, E, SE, S, SW, W, NW = 1, 2, 4, 8, 16, 32, 64, 128
_NBRS = ((N, 0, -1), (NE, 1, -1), (E, 1, 0), (SE, 1, 1), (S, 0, 1), (SW, -1, 1), (W, -1, 0), (NW, -1, -1))
FLAG_WILD_PLOT = 1  # object belongs to an unclaimed plot's wild growth


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
CARDINAL_MASKS = sorted({m & (N | E | S | W) for m in range(256)})  # 16: ice and lava (tile ids are a byte)
_CARDINAL_KINDS = {"ice", "lava"}
TILE_NAMES: list[str] = (
    [f"tile.grass.{v}" for v in range(4)]
    + [f"tile.flowers.{v}" for v in range(3)]
    + [f"tile.path.{m}" for m in BLOB_MASKS]
    + [f"tile.water.{m}" for m in BLOB_MASKS]
    + [f"tile.cobble.{m}" for m in BLOB_MASKS]
    + [f"tile.forest.{v}" for v in range(4)]
    # Phase 10 (append only: ids are part of the chunk format)
    + [f"tile.{k}.{v}" for k in ("rock", "mud", "snow", "ash") for v in range(4)]
    + [f"tile.ice.{m}" for m in CARDINAL_MASKS]
    + [f"tile.lava.{m}" for m in CARDINAL_MASKS]
)
TILE_ID = {n: i for i, n in enumerate(TILE_NAMES)}
OBJECT_NAMES: list[str] = [
    "obj.oak.0",
    "obj.oak.1",
    "obj.oak.2",
    "obj.big_oak.0",
    "obj.big_oak.1",
    "obj.birch.0",
    "obj.birch.1",
    "obj.pine.0",
    "obj.pine.1",
    "obj.apple.0",
    "obj.apple.1",
    "obj.bush.0",
    "obj.bush.1",
    "obj.flower_bush.0",
    "obj.flower_bush.1",
    "obj.flower_bush.2",
    "obj.flower_bush.3",
    "obj.rock.0",
    "obj.rock.1",
    "obj.rock_big.0",
    "obj.rock_big.1",
    "obj.mossy_rock.0",
    "obj.mossy_rock.1",
    "obj.pebbles.0",
    "obj.pebbles.1",
    "obj.tall_grass.0",
    "obj.tall_grass.1",
    "obj.mushrooms.0",
    "obj.mushrooms.1",
    "obj.stump.0",
    "obj.log.0",
    "obj.reeds.0",
    "obj.reeds.1",
    "obj.lilypad.0",
    "obj.lilypad.1",
    "obj.flowers.0",
    "obj.flowers.1",
    "obj.flowers.2",
    "obj.flowers.3",
    "obj.flowers.4",
    "obj.lamp.0",
    "obj.signpost.0",
    "obj.well.0",
    "obj.fern.0",
    "obj.fern.1",
    "obj.web.0",
    "obj.waystone.0",  # Phase 9 (P12): append only, ids are part of the chunk format
    # Phase 10 biomes
    "obj.boulder.0",
    "obj.boulder.1",
    "obj.crag.0",
    "obj.crag.1",
    "obj.star_vein.0",
    "obj.ore_vein.0",
    "obj.dead_tree.0",
    "obj.dead_tree.1",
    "obj.willow.0",
    "obj.venom_bloom.0",
    "obj.snow_pine.0",
    "obj.snow_pine.1",
    "obj.ice_rock.0",
    "obj.ice_rock.1",
    "obj.frost_spire.0",
    "obj.snowdrift.0",
    "obj.charred_tree.0",
    "obj.charred_tree.1",
    "obj.obsidian.0",
    "obj.obsidian.1",
    "obj.lava_vent.0",
    "obj.ember_rock.0",
    "obj.moonpetal.0",
    # Phase 10 points of interest
    "obj.ruins.0",
    "obj.ruins.1",
    "obj.chest.0",
    "obj.chest.1",
    "obj.shrine.0",
    "obj.lore_stone.0",
    "obj.cave.0",
    "obj.trader.0",
    "obj.lost_villager.0",
    # Phase 12
    "obj.delve_gate.0",
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


@dataclass(frozen=True)
class Waystone:
    index: int
    x: int
    y: int
    name: str


@dataclass(frozen=True)
class Poi:
    """A point of interest (Phase 10). `key` ("x,y") is what a player's use of it is saved under, so
    changing how many there are per ring never mixes up who opened which chest."""

    index: int
    kind: str
    x: int
    y: int
    biome: str
    variant: int

    @property
    def key(self) -> str:
        return f"{self.x},{self.y}"


POI_OBJECT = {
    "ruins": "obj.chest.0",
    "shrine": "obj.shrine.0",
    "lore_stone": "obj.lore_stone.0",
    "cave": "obj.cave.0",
    "merchant": "obj.trader.0",
    "lost_villager": "obj.lost_villager.0",
    "delve": "obj.delve_gate.0",
}
_POI_LAND = {"grass", "forest", "rock", "mud", "snow", "ash"}


_COMPASS = ["North", "Northeast", "East", "Southeast", "South", "Southwest", "West", "Northwest"]


def waystones(cfg: MapgenCfg) -> list[Waystone]:
    """Fast-travel stones (P12): one by the well, then a meadow stone and a forest stone beside each
    forest trail. Pure layout maths, no seed: every realm has them in the same places."""
    lay = layout(cfg)
    c = lay.center
    out = [Waystone(0, c + 3, c + 9, "Wellside")]
    n_trails = max(1, cfg.plot.count // 2)

    def stone(i: int, r: float, label: str) -> Waystone:
        a = -math.pi / 2 + 2 * math.pi * (2 * i + 0.5) / cfg.plot.count
        # two tiles to the side of the trail so it never blocks the path
        px, py = -math.sin(a), math.cos(a)
        x = round(c + r * math.cos(a) + 2.5 * px)
        y = round(c + r * math.sin(a) + 2.5 * py)
        deg = (math.degrees(a) + 90) % 360
        return Waystone(len(out), x, y, f"{_COMPASS[round(deg / 45) % 8]} {label}")

    for r, label in ((150, "Meadow"), (cfg.forest.radius + 30, "Forest")):
        for i in range(n_trails):
            out.append(stone(i, r, label))
    # Phase 10: three stones per outer ring, on alternating trails (indices stay stable: append only)
    labels = {"stonepeak": "Stonepeak", "swamp": "Murkwater", "frozen": "Frostfall", "ashen": "Ashfall"}
    for k, b in enumerate(cfg.bands[1:]):
        for j in range(3):
            out.append(stone((k + 2 * j) % n_trails, b.radius + 20, labels.get(b.biome, b.biome.title())))
    return out


_GROUND = {"forest": "forest", "stonepeak": "rock", "swamp": "mud", "frozen": "snow", "ashen": "ash"}
_BAND_OF_GROUND = {"rock": "stonepeak", "mud": "swamp", "snow": "frozen", "ash": "ashen"}
_POOLS = {  # band → (pool kind, noise threshold): lower threshold = more pools
    "stonepeak": ("water", 0.84),
    "swamp": ("water", 0.62),
    "frozen": ("ice", 0.72),
    "ashen": ("lava", 0.76),
}


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / (vx * vx + vy * vy)))
    return math.hypot(wx - t * vx, wy - t * vy)


class Generator:
    def __init__(self, cfg, seed: int) -> None:  # noqa: ANN001 - GameConfig
        from hearthforge.domain import debris as debris_mod
        from hearthforge.domain import plotlayout

        self.game = cfg
        self.cfg: MapgenCfg = cfg.mapgen
        self.seed = seed
        self.lay = layout(self.cfg)
        self.margin = self.cfg.plot.clear_margin
        self.tpl = plotlayout.template(cfg)
        hub = (self.lay.center, self.lay.center)
        self.gates = [plotlayout.gate(self.tpl, o, hub) for o in self.lay.plot_origins]
        self.paths = [plotlayout.village_path(self.tpl, g) for g in self.gates]
        self.roads = [
            (self.lay.center + 0.5, self.lay.center + 0.5, o[0] + g[0] + 0.5, o[1] + g[1] + 0.5)
            for o, g in zip(self.lay.plot_origins, self.gates, strict=True)
        ]
        # unclaimed plots grow wild; the same generator makes a claimed village's debris
        self.wild: list[dict[tuple[int, int], tuple[str, int]]] = []
        for i in range(len(self.lay.plot_origins)):
            items = debris_mod.generate(
                cfg.debris, self.tpl, _mix(seed, i, 99) & 0x7FFFFFFF, self.paths[i], 1.6
            )
            self.wild.append({(x, y): (cfg.debris.kinds[k].sprites[v], 0) for _id, k, v, x, y in items})
        # trails into the forest leave the meadow in every other gap between plots
        c = self.lay.center
        r0, r1 = self.lay.hub_radius + 24, self.cfg.bands[-1].radius + 34
        self.trails = []
        for i in range(max(1, self.cfg.plot.count // 2)):
            a = -math.pi / 2 + 2 * math.pi * (2 * i + 0.5) / self.cfg.plot.count
            self.trails.append(
                (c + r0 * math.cos(a), c + r0 * math.sin(a), c + r1 * math.cos(a), c + r1 * math.sin(a))
            )
        self._chunks: dict[tuple[int, int], dict] = {}
        self.waystones = waystones(self.cfg)
        self.waystone_at = {(w.x, w.y): w for w in self.waystones}
        self.pois = self._place_pois()
        self.poi_at = {(p.x, p.y): p for p in self.pois}
        self.poi_deco: dict[tuple[int, int], str] = {}
        for p in self.pois:
            if p.kind == "ruins":  # broken walls either side of the chest
                self.poi_deco[(p.x - 2, p.y - 1)] = "obj.ruins.0"
                self.poi_deco[(p.x + 2, p.y - 1)] = "obj.ruins.1"

    # ── points of interest (Phase 10) ────────────────────────────────────────
    def _place_pois(self) -> list[Poi]:
        pc = getattr(self.game, "pois", None)
        if pc is None:
            return []
        c = self.lay.center
        edge = self.cfg.map_size // 2 - 6
        rings = [("meadow", self.lay.hub_radius + 26.0, float(self.cfg.bands[0].radius))]
        for i, b in enumerate(self.cfg.bands):
            outer = self.cfg.bands[i + 1].radius if i + 1 < len(self.cfg.bands) else edge
            rings.append((b.biome, float(b.radius), float(outer)))
        out: list[Poi] = []
        sp2 = pc.min_spacing**2
        for bi, (biome, r0, r1) in enumerate(rings):
            kinds = [k for k, n in pc.bands.get(biome, {}).items() for _ in range(n)]
            span = max(1.0, r1 - r0 - 2 * pc.edge_margin)
            for j, kind in enumerate(kinds):
                for attempt in range(60):
                    a = 2 * math.pi * rand01(self.seed, bi * 101 + j, attempt, 701)
                    r = r0 + pc.edge_margin + rand01(self.seed, bi * 103 + j, attempt, 702) * span
                    x, y = round(c + r * math.cos(a)), round(c + r * math.sin(a))
                    if not (8 <= x < self.cfg.map_size - 8 and 8 <= y < self.cfg.map_size - 8):
                        continue
                    if self.biome(x, y) != biome or self.plot_at(x, y, self.margin + 4) is not None:
                        continue
                    if self.trail_dist(x, y) < pc.trail_clearance or self.road_dist(x, y) < 5:
                        continue
                    if self.near_waystone(x, y, 7) or any((p.x - x) ** 2 + (p.y - y) ** 2 < sp2 for p in out):
                        continue
                    if any(
                        self.kind(x + dx, y + dy) not in _POI_LAND
                        for dx in range(-2, 3)
                        for dy in range(-2, 3)
                    ):
                        continue
                    variant = int(rand01(self.seed, x, y, 703) * 1_000_000)
                    out.append(Poi(len(out), kind, x, y, biome, variant))
                    break
        dg = getattr(self.game, "dungeons", None)
        if (
            dg is not None
        ):  # Phase 12: the Delve Gate by the well (appended, so older indices keep their meaning)
            gx, gy = c + dg.daily.place[0], c + dg.daily.place[1]
            out.append(Poi(len(out), "delve", gx, gy, dg.daily.biome, 0))
        return out

    def near_poi(self, x: int, y: int, r: float) -> bool:
        return any((p.x - x) ** 2 + (p.y - y) ** 2 <= r * r for p in self.pois)

    def near_waystone(self, x: int, y: int, r: float) -> bool:
        return any((w.x - x) ** 2 + (w.y - y) ** 2 <= r * r for w in self.waystones)

    # ── classification ─────────────────────────────────────────────────────
    def plot_at(self, x: int, y: int, margin: int = 0) -> int | None:
        f = self.lay.frame
        for i, (ox, oy) in enumerate(self.lay.plot_origins):
            if ox - margin <= x < ox + f + margin and oy - margin <= y < oy + f + margin:
                return i
        return None

    def road_dist(self, x: int, y: int) -> float:
        return min(_seg_dist(x + 0.5, y + 0.5, *r) for r in self.roads)

    def in_start_square(self, i: int, x: int, y: int, pad: int = 0) -> bool:
        ox, oy = self.lay.plot_origins[i]
        fx, fy = x - ox, y - oy
        return self.tpl.lo - pad <= fx < self.tpl.hi + pad and self.tpl.lo - pad <= fy < self.tpl.hi + pad

    def trail_dist(self, x: int, y: int) -> float:
        return min(_seg_dist(x + 0.5, y + 0.5, *t) for t in self.trails)

    def forest_depth(self, x: int, y: int) -> float:
        """Tiles past the (noise-warped) forest edge; negative = still meadow."""
        c = self.lay.center
        warp = (value_noise(self.seed, x, y, 14, 71) - 0.5) * 18
        return math.hypot(x + 0.5 - c, y + 0.5 - c) + warp - self.cfg.forest.radius

    def band(self, x: int, y: int, dither: bool = True) -> str | None:
        """Which outer ring a tile is in (None = meadow). Edges are noise-warped like the forest's and
        dithered over a few tiles so neighbouring rings blend instead of meeting in a line."""
        c = self.lay.center
        warp = (value_noise(self.seed, x, y, 14, 71) - 0.5) * 18
        r = math.hypot(x + 0.5 - c, y + 0.5 - c) + warp
        if dither:
            r += (rand01(self.seed, x, y, 72) - 0.5) * 6
        found = None
        for b in self.cfg.bands:
            if r >= b.radius:
                found = b.biome
        return found

    def biome(self, x: int, y: int) -> str:
        """Gameplay biome for spawns and nodes: 'hub', 'plot', 'meadow' or a ring ('forest', 'stonepeak'…)."""
        if self.plot_at(x, y, 6) is not None:
            return "plot"
        c = self.lay.center
        if math.hypot(x - c, y - c) < self.lay.hub_radius + 6:
            return "hub"
        return self.band(x, y, dither=False) or "meadow"

    def is_hub(self, x: int, y: int) -> bool:
        c = self.lay.center
        wobble = (value_noise(self.seed, x, y, 6, 17) - 0.5) * 2.0
        return math.hypot(x + 0.5 - c, y + 0.5 - c) <= self.lay.hub_radius + wobble

    def kind(self, x: int, y: int) -> str:
        i = self.plot_at(x, y)
        if i is not None:
            ox, oy = self.lay.plot_origins[i]
            fx, fy = x - ox, y - oy
            px, py, pw, ph = self.lay.pond
            if px <= fx < px + pw and py <= fy < py + ph:
                return "water"
            if (fx, fy) in self.paths[i]:
                return "path"
            if not self.in_start_square(i, x, y) and self.road_dist(x, y) <= 1.15:
                return "path"
            return "grass"
        if self.is_hub(x, y):
            return "cobble"
        rd = self.road_dist(x, y)
        wiggle = (value_noise(self.seed, x, y, 9, 23) - 0.5) * 0.6
        if rd <= 1.15 + wiggle:
            return "path"
        if self.trail_dist(x, y) <= 0.75 + wiggle * 0.5:
            return "path"
        band = self.band(x, y)
        pool = self._natural_pond(x, y, rd, band)
        if pool:
            return pool
        return _GROUND.get(band or "", "grass")

    def _natural_pond(self, x: int, y: int, rd: float, band: str | None = None) -> str | None:
        """Water in the meadow, forest and stonepeak; lots of murky pools in the swamp; frozen lakes
        (walkable ice) in the north; lava pools in the Ashen Wastes."""
        if rd < 4 or self.plot_at(x, y, 4) is not None or self.near_waystone(x, y, 6):
            return None
        c = self.lay.center
        if math.hypot(x - c, y - c) < self.lay.hub_radius + 8:
            return None
        if self.trail_dist(x, y) < 2.2:
            return None
        kind, threshold = _POOLS.get(band or "", ("water", 0.80))
        return kind if value_noise(self.seed, x, y, 11, 61) > threshold else None

    def _mask(self, x: int, y: int, k: str, kinds: dict[tuple[int, int], str]) -> int:
        m = 0
        for bit, dx, dy in _NBRS:
            p = (x + dx, y + dy)
            kk = kinds.get(p)
            if kk is None:
                kk = self.kind(*p)
            if kk == k or (k == "path" and kk == "cobble"):
                m |= bit
        if k in _CARDINAL_KINDS:
            return m & (N | E | S | W)
        return reduce_mask(m)

    # ── chunks ─────────────────────────────────────────────────────────────
    def chunk(self, cx: int, cy: int) -> dict:
        hit = self._chunks.get((cx, cy))
        if hit is not None:
            return hit
        cs = self.cfg.chunk_size
        x0, y0 = cx * cs, cy * cs
        kinds = {
            (x, y): self.kind(x, y) for y in range(y0 - 1, y0 + cs + 1) for x in range(x0 - 1, x0 + cs + 1)
        }
        ground = bytearray(cs * cs)
        objects: list[list[int]] = []
        md = self.cfg.meadow
        for ly in range(cs):
            for lx in range(cs):
                x, y = x0 + lx, y0 + ly
                k = kinds[(x, y)]
                if k == "grass":
                    flowers = value_noise(self.seed, x, y, 7, 31) > md.flower_patch_threshold
                    r = rand01(self.seed, x, y, 1)
                    if flowers and r < 0.55:
                        name = f"tile.flowers.{int(r * 3 / 0.55) % 3}"
                    else:
                        name = f"tile.grass.{int(r * 4) % 4}"
                elif k == "forest" or k in _BAND_OF_GROUND:
                    name = f"tile.{k}.{int(rand01(self.seed, x, y, 1) * 4) % 4}"
                else:
                    name = f"tile.{k}.{self._mask(x, y, k, kinds)}"
                ground[ly * cs + lx] = TILE_ID[name]
                obj = self._object(x, y, k, kinds)
                if obj is not None:
                    objects.append([lx, ly, OBJECT_ID[obj[0]], obj[1]])
        out = {"cx": cx, "cy": cy, "ground": bytes(ground), "objects": objects}
        if len(self._chunks) > 4096:
            self._chunks.clear()
        self._chunks[(cx, cy)] = out
        return out

    def _object(self, x: int, y: int, k: str, kinds: dict[tuple[int, int], str]) -> tuple[str, int] | None:
        c = self.lay.center
        s = self.seed
        if (x, y) == (c, c):
            return ("obj.well.0", 0)
        poi = self.poi_at.get((x, y))
        if poi is not None:
            return (POI_OBJECT[poi.kind], 0)
        deco = self.poi_deco.get((x, y))
        if deco is not None:
            return (deco, 0)
        if self.pois and self.near_poi(x, y, self.game.pois.clear_radius):
            return None  # a clearing around every point of interest
        if (x, y) in self.waystone_at:
            return ("obj.waystone.0", 0)
        if self.near_waystone(x, y, 2.3):
            return None  # a little clearing around every waystone
        if k == "water":
            # lily pads on open water (not on the bank)
            if rand01(s, x, y, 21) < 0.08 and all(
                kinds.get((x + dx, y + dy), "water") == "water"
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ):
                return (f"obj.lilypad.{int(rand01(s, x, y, 22) * 2)}", 0)
            return None
        if k == "forest":
            return self._forest(x, y, kinds)
        if k in _BAND_OF_GROUND:
            return self._band_object(_BAND_OF_GROUND[k], x, y, kinds)
        if k != "grass":
            return None
        i = self.plot_at(x, y)
        if i is not None:
            return self._plot_object(i, x, y, kinds)
        if self.plot_at(x, y, self.margin) is not None:
            return None
        dist = math.hypot(x - c, y - c)
        if dist <= self.lay.hub_radius + 2:
            return None
        near_water = any(
            kinds.get((x + dx, y + dy)) == "water" for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )
        if near_water and rand01(s, x, y, 23) < 0.45:
            return (f"obj.reeds.{int(rand01(s, x, y, 24) * 2)}", 0)
        rd = self.road_dist(x, y)
        if self.trail_dist(x, y) < 1.6:
            return None
        if 1.4 < rd < 2.3 and rand01(s, x, y, 25) < 0.035:
            return ("obj.lamp.0", 0)
        if rd < 2.5:
            return (f"obj.flowers.{int(rand01(s, x, y, 26) * 5)}", 0) if rand01(s, x, y, 27) < 0.06 else None
        return self._nature(x, y, dist)

    def _nature(self, x: int, y: int, dist: float, forest_boost: float = 0.0) -> tuple[str, int] | None:
        s = self.seed
        md = self.cfg.meadow
        grove = min(1.0, value_noise(s, x, y, 12, 41) + forest_boost)
        outcrop = value_noise(s, x, y, 9, 47)
        flowers = value_noise(s, x, y, 7, 31) > md.flower_patch_threshold
        far = max(0.0, min(1.0, (dist - 140) / 160))
        r = rand01(s, x, y, 2)
        if grove > 0.62:
            p_tree, p_bush, p_mush, p_log = 0.24, 0.05, 0.03, 0.008
        elif grove > 0.52:
            p_tree, p_bush, p_mush, p_log = 0.06, 0.07, 0.015, 0.006
        else:
            p_tree, p_bush, p_mush, p_log = (
                md.tree_density_near * 0.5 + far * 0.02,
                md.bush_density * 0.6,
                0.0,
                0.002,
            )
        if r < p_tree:
            pick = rand01(s, x, y, 3)
            if pick < 0.18:
                return (f"obj.big_oak.{int(pick * 100) % 2}", 0)
            if pick < 0.30 + far * 0.25:
                return (f"obj.pine.{int(pick * 100) % 2}", 0)
            if pick < 0.48 + far * 0.1:
                return (f"obj.birch.{int(pick * 100) % 2}", 0)
            if pick < 0.53:
                return (f"obj.apple.{int(pick * 100) % 2}", 0)
            return (f"obj.oak.{int(pick * 100) % 3}", 0)
        r -= p_tree
        if 0 <= r < p_bush:
            v = int(rand01(s, x, y, 4) * 6)
            return (f"obj.bush.{v}", 0) if v < 2 else (f"obj.flower_bush.{v - 2}", 0)
        r -= p_bush
        if 0 <= r < p_mush:
            return (f"obj.mushrooms.{int(rand01(s, x, y, 5) * 2)}", 0)
        r -= p_mush
        if 0 <= r < p_log:
            return ("obj.log.0", 0)
        r -= p_log
        if outcrop > 0.74:
            q = rand01(s, x, y, 6)
            if q < 0.07:
                return (f"obj.rock_big.{int(q * 100) % 2}", 0)
            if q < 0.11:
                return (f"obj.mossy_rock.{int(q * 100) % 2}", 0)
            if q < 0.19:
                return (f"obj.rock.{int(q * 100) % 2}", 0)
            if q < 0.26:
                return (f"obj.pebbles.{int(q * 100) % 2}", 0)
        if flowers and r < 0.14:
            return (f"obj.flowers.{int(rand01(s, x, y, 7) * 5)}", 0)
        if 0 <= r - 0.14 < md.tall_grass_density:
            return (f"obj.tall_grass.{int(rand01(s, x, y, 8) * 2)}", 0)
        if 0 <= r - 0.14 - md.tall_grass_density < md.rock_density:
            return (f"obj.rock.{int(rand01(s, x, y, 9) * 2)}", 0)
        if r > 0.995:
            return ("obj.stump.0", 0)
        return None

    def _forest(self, x: int, y: int, kinds: dict[tuple[int, int], str]) -> tuple[str, int] | None:
        s = self.seed
        fc = self.cfg.forest
        if self.trail_dist(x, y) < 1.7:
            return (f"obj.fern.{int(rand01(s, x, y, 81) * 2)}", 0) if rand01(s, x, y, 82) < 0.05 else None
        near_water = any(
            kinds.get((x + dx, y + dy)) == "water" for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )
        if near_water:
            return (f"obj.reeds.{int(rand01(s, x, y, 24) * 2)}", 0) if rand01(s, x, y, 23) < 0.4 else None
        clearing = value_noise(s, x, y, 10, 83) > fc.clearing_threshold
        r = rand01(s, x, y, 84)
        # trees never touch diagonally-adjacent trees on the same row parity, which keeps lanes open
        lattice_ok = (x + 2 * y) % 5 != 0
        if not clearing and lattice_ok and r < fc.tree_density:
            pick = rand01(s, x, y, 85)
            if pick < 0.22:
                return (f"obj.big_oak.{int(pick * 100) % 2}", 0)
            if pick < 0.62:
                return (f"obj.pine.{int(pick * 100) % 2}", 0)
            if pick < 0.82:
                return (f"obj.oak.{int(pick * 100) % 3}", 0)
            return (f"obj.birch.{int(pick * 100) % 2}", 0)
        r -= fc.tree_density
        if clearing:
            if 0 <= r < 0.10:
                return (f"obj.flowers.{int(rand01(s, x, y, 86) * 5)}", 0)
            if 0.10 <= r < 0.13:
                return (f"obj.tall_grass.{int(rand01(s, x, y, 87) * 2)}", 0)
            if 0.13 <= r < 0.145:
                return (f"obj.flower_bush.{int(rand01(s, x, y, 88) * 4)}", 0)
            return None
        if 0 <= r < 0.07:
            return (f"obj.fern.{int(rand01(s, x, y, 89) * 2)}", 0)
        if 0.07 <= r < 0.095:
            return (f"obj.mushrooms.{int(rand01(s, x, y, 90) * 2)}", 0)
        if 0.095 <= r < 0.11:
            return (f"obj.bush.{int(rand01(s, x, y, 91) * 2)}", 0)
        if 0.11 <= r < 0.118:
            return ("obj.log.0", 0)
        if 0.118 <= r < 0.124:
            return ("obj.web.0", 0)
        if 0.124 <= r < 0.134:
            return (f"obj.mossy_rock.{int(rand01(s, x, y, 92) * 2)}", 0)
        if 0.134 <= r < 0.14:
            return ("obj.stump.0", 0)
        return None

    def _band_object(
        self, band: str, x: int, y: int, kinds: dict[tuple[int, int], str]
    ) -> tuple[str, int] | None:
        """Props and nodes for the outer rings (Phase 10). Trails stay clear; a lattice keeps lanes open."""
        s = self.seed
        if self.trail_dist(x, y) < 1.8:
            return None
        r = rand01(s, x, y, 301)
        pick = rand01(s, x, y, 302)
        lattice_ok = (x + 2 * y) % 5 != 0
        if r < 0.004:
            return ("obj.moonpetal.0", 0)  # night-only rare node, any ring past the meadow
        r -= 0.004
        near = {kinds.get((x + dx, y + dy)) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))}
        if band == "stonepeak":
            if lattice_ok and r < 0.06:
                return (f"obj.boulder.{int(pick * 2)}", 0)
            if lattice_ok and r < 0.085:
                return (f"obj.crag.{int(pick * 2)}", 0)
            if r < 0.105:
                return (f"obj.pine.{int(pick * 2)}", 0)
            if r < 0.112:
                return ("obj.star_vein.0", 0)
            if r < 0.122:
                return ("obj.ore_vein.0", 0)
            if r < 0.14:
                return (f"obj.pebbles.{int(pick * 2)}", 0)
            return None
        if band == "swamp":
            if "water" in near:
                return (f"obj.reeds.{int(pick * 2)}", 0) if r < 0.45 else None
            if lattice_ok and r < 0.07:
                return (f"obj.dead_tree.{int(pick * 2)}", 0)
            if lattice_ok and r < 0.095:
                return ("obj.willow.0", 0)
            if r < 0.105:
                return ("obj.venom_bloom.0", 0)
            if r < 0.14:
                return (f"obj.mushrooms.{int(pick * 2)}", 0)
            if r < 0.15:
                return ("obj.log.0", 0)
            return None
        if band == "frozen":
            if lattice_ok and r < 0.09:
                return (f"obj.snow_pine.{int(pick * 2)}", 0)
            if lattice_ok and r < 0.11:
                return (f"obj.ice_rock.{int(pick * 2)}", 0)
            if r < 0.117:
                return ("obj.frost_spire.0", 0)
            if r < 0.14:
                return ("obj.snowdrift.0", 0)
            return None
        if band == "ashen":
            if "lava" in near:
                return None
            if lattice_ok and r < 0.05:
                return (f"obj.charred_tree.{int(pick * 2)}", 0)
            if lattice_ok and r < 0.08:
                return (f"obj.obsidian.{int(pick * 2)}", 0)
            if r < 0.086:
                return ("obj.lava_vent.0", 0)
            if r < 0.11:
                return ("obj.ember_rock.0", 0)
            return None
        return None

    def _plot_object(
        self, i: int, x: int, y: int, kinds: dict[tuple[int, int], str]
    ) -> tuple[str, int] | None:
        ox, oy = self.lay.plot_origins[i]
        fx, fy = x - ox, y - oy
        gx, gy, side = self.gates[i]
        # signpost beside the gate, just outside the fence
        out_dx, out_dy = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}[side]
        sign = (gx + out_dx + (2 if out_dy else 0), gy + out_dy + (2 if out_dx else 0))
        if (fx, fy) == sign:
            return ("obj.signpost.0", 0)
        if self.in_start_square(i, x, y):
            wild = self.wild[i].get((fx, fy))
            return (wild[0], FLAG_WILD_PLOT) if wild else None
        # the ring between the fence and the frame edge is a forest clearing
        if self.in_start_square(i, x, y, pad=2) or self.road_dist(x, y) < 3.2:
            if rand01(self.seed, x, y, 31) < 0.08:
                return (f"obj.flowers.{int(rand01(self.seed, x, y, 32) * 5)}", 0)
            return None
        return self._nature(x, y, 200, forest_boost=0.25)


_cache: dict[tuple[str, int], Generator] = {}


def generator(cfg, seed: int) -> Generator:  # noqa: ANN001 - GameConfig
    key = (cfg.hash, seed)
    g = _cache.get(key)
    if g is None:
        if len(_cache) > 32:
            _cache.clear()
        g = _cache[key] = Generator(cfg, seed)
    return g
