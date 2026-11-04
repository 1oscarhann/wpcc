"""Per-realm collision and resource-node lookup over the generated map (shared/world.json rules)."""

from __future__ import annotations

from hearthforge.domain import mapgen
from hearthforge.sim.rules import WORLD

_SOLID_TILES = tuple(WORLD["solid_tiles"])
_SOLID_OBJS = tuple(WORLD["solid_objects"])
SOLID_TILE_IDS = frozenset(i for i, n in enumerate(mapgen.TILE_NAMES) if n.startswith(_SOLID_TILES))
SOLID_OBJ_IDS = frozenset(i for i, n in enumerate(mapgen.OBJECT_NAMES) if n.startswith(_SOLID_OBJS))


class WorldGrid:
    def __init__(self, cfg, seed: int) -> None:  # noqa: ANN001 - GameConfig
        self.cfg = cfg
        self.gen = mapgen.generator(cfg, seed)
        self.cs = cfg.mapgen.chunk_size
        self.size = cfg.mapgen.map_size
        self.blocks: set[tuple[int, int]] = set()
        self.block_rects: list[tuple[int, int, int, int]] = []
        self.claimed: frozenset[int] = frozenset()
        self._solid: dict[tuple[int, int], bytearray] = {}
        self._objs: dict[tuple[int, int], dict[int, int]] = {}
        # node kind per object id; biome-specific kinds win over generic ones
        self._node_generic: dict[int, str] = {}
        self._node_biome: dict[tuple[int, str], str] = {}
        for key, n in cfg.nodes.nodes.items():
            for i, name in enumerate(mapgen.OBJECT_NAMES):
                if any(name == p or name.startswith(p + ".") for p in n.objects):
                    if n.biome:
                        self._node_biome[(i, n.biome)] = key
                    else:
                        self._node_generic.setdefault(i, key)

    def set_blocks(self, rects: list[tuple[int, int, int, int]], claimed: set[int] | frozenset[int]) -> None:
        self.block_rects = list(rects)
        self.blocks = {(x + i, y + j) for x, y, w, h in rects for i in range(w) for j in range(h)}
        if frozenset(claimed) != self.claimed:
            self.claimed = frozenset(claimed)
            self._solid.clear()
            self._objs.clear()

    def _load(self, cx: int, cy: int) -> tuple[bytearray, dict[int, int]]:
        ch = self.gen.chunk(cx, cy)
        cs = self.cs
        solid = bytearray(cs * cs)
        objs: dict[int, int] = {}
        for i, t in enumerate(ch["ground"]):
            if t in SOLID_TILE_IDS:
                solid[i] = 1
        for lx, ly, oid, flag in ch["objects"]:
            if flag & mapgen.FLAG_WILD_PLOT:
                plot = self.gen.plot_at(cx * cs + lx, cy * cs + ly)
                if plot is not None and plot in self.claimed:
                    continue  # a claimed village's own debris replaces the wild growth
            idx = ly * cs + lx
            objs[idx] = oid
            if oid in SOLID_OBJ_IDS:
                solid[idx] = 1
        self._solid[(cx, cy)] = solid
        self._objs[(cx, cy)] = objs
        if len(self._solid) > 2048:
            self._solid.clear()
            self._objs.clear()
            self._solid[(cx, cy)] = solid
            self._objs[(cx, cy)] = objs
        return solid, objs

    def solid(self, x: int, y: int) -> bool:
        if x < 0 or y < 0 or x >= self.size or y >= self.size:
            return True
        if (x, y) in self.blocks:
            return True
        cs = self.cs
        cx, cy = x // cs, y // cs
        arr = self._solid.get((cx, cy))
        if arr is None:
            arr = self._load(cx, cy)[0]
        return arr[(y - cy * cs) * cs + (x - cx * cs)] == 1

    def object_at(self, x: int, y: int) -> int | None:
        if x < 0 or y < 0 or x >= self.size or y >= self.size or (x, y) in self.blocks:
            return None
        cs = self.cs
        cx, cy = x // cs, y // cs
        objs = self._objs.get((cx, cy))
        if objs is None:
            objs = self._load(cx, cy)[1]
        return objs.get((y - cy * cs) * cs + (x - cx * cs))

    def node_at(self, x: int, y: int) -> str | None:
        oid = self.object_at(x, y)
        if oid is None:
            return None
        biome = self.gen.biome(x, y)
        return self._node_biome.get((oid, biome)) or self._node_generic.get(oid)

    def node_id(self, x: int, y: int) -> int:
        return y * self.size + x

    def node_xy(self, node_id: int) -> tuple[int, int]:
        return node_id % self.size, node_id // self.size
