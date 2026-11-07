"""Phase 14: decorations. One look each (no levels), drawn like buildings: the footprint's top-left sits at
(0, top) inside the sprite. Paths are flat tiles the client draws on the ground layer.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from artgen.buildings import (
    BLUE,
    CLOTH,
    FRED,
    GOLD,
    LEAF,
    PINK,
    PUMPKIN,
    PURPLE,
    RED,
    STONE,
    TEAL,
    WATER,
    WOOD,
    YELLOW,
    Art,
    banner,
    ground_shadow,
    new,
    roof_gable,
)
from artgen.canvas import Canvas, hash2
from artgen.palette import INK, ramp

DIRT = ramp("dirt")
GRASS = ramp("grass")
ICE = ramp("ice")
VIOLET = ramp("flower_purple")
WHITE = ramp("flower_white")


def _blob(c: Canvas, cx: float, cy: float, rx: float, ry: float, rp: list) -> None:
    n = len(rp)
    for y in range(c.h):
        for x in range(c.w):
            dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
            if dx * dx + dy * dy <= 1:
                light = -(dx * 0.6 + dy * 0.8)
                c.put(x, y, rp[max(0, min(n - 1, int((light + 1) / 2 * (n - 1) + 0.35)))])


def path_dirt() -> Art:
    c = Canvas(16, 16)
    for y in range(16):
        for x in range(16):
            n = hash2(x, y, 901)
            c.put(x, y, DIRT[2] if n > 0.25 else DIRT[1] if n > 0.08 else DIRT[3])
    for k in range(3):
        c.put(int(hash2(k, 1, 902) * 14) + 1, int(hash2(k, 2, 903) * 14) + 1, STONE[3])
    return Art(c, 0)


def path_stone() -> Art:
    c = Canvas(16, 16)
    for y in range(16):
        for x in range(16):
            seam = (x % 8 == 0) or (y % 8 == 0) if (y // 8) % 2 == 0 else ((x + 4) % 8 == 0) or (y % 8 == 0)
            c.put(x, y, STONE[1] if seam else STONE[3] if hash2(x // 8, y // 8, 904) > 0.5 else STONE[2])
    return Art(c, 0)


def flower_bed() -> Art:
    c, top = new(1, 1, 12)
    B = c.h - 2
    c.rect(1, B - 5, 14, 5, WOOD[2])
    c.hline(1, 14, B - 5, WOOD[3])
    c.rect(2, B - 4, 12, 3, DIRT[1])
    cols = [FRED, YELLOW, PINK, PURPLE]
    for i in range(6):
        x = 2 + i * 2 + (i % 2)
        y = B - 6 - (i % 3)
        c.vline(x, y + 1, B - 4, LEAF[2])
        col = cols[i % 4]
        c.put(x, y, col[2])
        c.put(x - 1, y, col[1])
        c.put(x + 1, y, col[1])
        c.put(x, y - 1, col[1])
        c.put(x, y + 1, col[1])
        c.put(x, y, YELLOW[2] if col is not YELLOW else WHITE[2])
    c.outline(INK)
    return Art(c, top)


def hedge() -> Art:
    c, top = new(1, 1, 15)
    B = c.h - 2
    ground_shadow(c, 1, B - 10, 14, B)
    for y in range(B - 12, B):
        for x in range(1, 15):
            u = (x - 1) / 13
            i = 3 if u < 0.3 else 2 if u < 0.75 else 1
            if y < B - 10:
                i = min(4, i + 1)
            if hash2(x, y, 905) < 0.15:
                i = max(0, i - 1)
            c.put(x, y, LEAF[i])
    c.outline(INK)
    return Art(c, top)


def bench() -> Art:
    c, top = new(1, 1, 11)
    B = c.h - 2
    ground_shadow(c, 1, B - 4, 14, B)
    c.rect(1, B - 7, 14, 2, WOOD[3])
    c.hline(1, 14, B - 7, WOOD[4])
    c.rect(1, B - 11, 14, 2, WOOD[2])
    for x in (2, 13):
        c.vline(x, B - 11, B, WOOD[1])
    c.outline(INK)
    return Art(c, top)


def lantern() -> Art:
    c, top = new(1, 1, 24)
    B = c.h - 2
    c.vline(8, B - 18, B, WOOD[1])
    c.vline(7, B - 18, B, WOOD[3])
    c.hline(7, 12, B - 18, WOOD[1])
    c.rect(10, B - 17, 4, 5, STONE[1])
    c.rect(11, B - 16, 2, 3, YELLOW[2])
    c.put(11, B - 16, WHITE[2])
    c.hline(5, 10, B, STONE[2])
    c.outline(INK)
    return Art(c, top)


def young_tree() -> Art:
    c, top = new(1, 1, 28)
    B = c.h - 2
    ground_shadow(c, 3, B - 4, 12, B)
    c.vline(7, B - 12, B, WOOD[2])
    c.vline(8, B - 12, B, WOOD[1])
    _blob(c, 8, B - 17, 7, 7, LEAF[1:])
    _blob(c, 5, B - 14, 4, 3.5, LEAF[1:])
    _blob(c, 11, B - 14, 4, 3.5, LEAF[1:])
    c.put(6, B - 20, LEAF[4])
    c.put(10, B - 18, FRED[2])
    c.outline(INK)
    return Art(c, top)


def well() -> Art:
    c, top = new(2, 2, 34)
    B = c.h - 3
    ground_shadow(c, 3, B - 12, 28, B)
    for y in range(B - 12, B):
        for x in range(5, 27):
            seam = y % 4 == 0 or (x + (y // 4) * 3) % 6 == 0
            c.put(x, y, STONE[1] if seam else STONE[3] if x < 12 else STONE[2])
    c.rect(7, B - 14, 18, 2, WATER[1])
    c.hline(5, 26, B - 12, STONE[4])
    for x in (6, 25):
        c.vline(x, B - 28, B - 12, WOOD[1])
    roof_gable(c, 16, B - 36, 13, 10, RED, "tiles")
    c.hline(7, 24, B - 23, WOOD[2])
    c.vline(16, B - 23, B - 17, WOOD[0])
    c.rect(14, B - 18, 4, 3, WOOD[3])
    c.outline(INK)
    return Art(c, top)


def banner_deco() -> Art:
    c, top = new(1, 1, 30)
    B = c.h - 2
    c.vline(4, B - 26, B, WOOD[1])
    c.put(4, B - 27, GOLD[3])
    banner(c, 5, B - 25, TEAL, length=14)
    c.hline(2, 6, B, STONE[2])
    c.outline(INK)
    return Art(c, top)


def market_stall() -> Art:
    c, top = new(2, 1, 28)
    B = c.h - 2
    ground_shadow(c, 2, B - 10, 29, B)
    c.rect(3, B - 10, 26, 8, WOOD[3])
    c.hline(3, 28, B - 10, WOOD[4])
    for x in (4, 27):
        c.vline(x, B - 24, B, WOOD[1])
    for y in range(B - 26, B - 20):  # striped awning
        for x in range(1, 31):
            c.put(x, y, RED[2] if (x // 4) % 2 == 0 else CLOTH[3])
    for x in range(1, 31, 4):
        c.put(x + 1, B - 20, RED[2])
    for i, col in enumerate((PUMPKIN, ramp("cabbage"), YELLOW, FRED)):
        _blob(c, 8 + i * 5.5, B - 12, 2.4, 2, col[1:] if len(col) > 2 else col)
    c.outline(INK)
    return Art(c, top)


def pumpkins() -> Art:
    c, top = new(1, 1, 12)
    B = c.h - 2
    ground_shadow(c, 1, B - 5, 14, B)
    for cx, cy, r in ((5, B - 3, 3.6), (11, B - 3, 3.2), (8, B - 7, 3.0)):
        _blob(c, cx, cy, r, r * 0.8, PUMPKIN[1:])
        c.put(int(cx), int(cy - r * 0.8), LEAF[2])
        c.vline(int(cx), int(cy - r * 0.5), int(cy + r * 0.5), PUMPKIN[1])
    c.outline(INK)
    return Art(c, top)


def fountain(runic: bool = False) -> Art:
    c, top = new(2, 2, 30 if not runic else 34)
    B = c.h - 3
    ground_shadow(c, 2, B - 12, 29, B)
    stone = STONE if not runic else ramp("obsidian") + [STONE[4]]
    water = WATER if not runic else [VIOLET[0], VIOLET[1], ICE[2], ICE[3]]
    _blob(c, 16, B - 6, 14, 7, stone[1:])
    _blob(c, 16, B - 7, 11, 5, water[1:])
    c.rect(14, B - 22, 4, 15, stone[2])
    c.rect(13, B - 23, 6, 2, stone[3])
    _blob(c, 16, B - 25, 5, 2.5, stone[1:])
    for k, (dx, dy) in enumerate(((-3, -27), (3, -27), (0, -29), (-5, -24), (5, -24))):
        c.put(16 + dx, B + dy, water[-1] if k % 2 else WHITE[2])
    if runic:
        for x, y in ((9, -6), (23, -6), (16, -16)):
            c.put(x, B + y, VIOLET[2])
    c.outline(INK)
    return Art(c, top)


def statue() -> Art:
    c, top = new(1, 1, 36)
    B = c.h - 2
    ground_shadow(c, 1, B - 6, 14, B)
    c.rect(2, B - 7, 12, 7, STONE[2])
    c.hline(2, 13, B - 7, STONE[4])
    c.rect(5, B - 26, 6, 19, STONE[3])  # the figure
    _blob(c, 8, B - 29, 3.2, 3.2, STONE[2:])
    c.vline(12, B - 32, B - 14, STONE[4])  # sword raised
    c.put(12, B - 33, STONE[5])
    c.hline(10, 13, B - 21, STONE[1])
    c.vline(5, B - 24, B - 12, STONE[1])
    c.outline(INK)
    return Art(c, top)


def lantern_post() -> Art:
    c, top = new(1, 1, 36)
    B = c.h - 2
    c.rect(6, B - 3, 4, 3, STONE[1])
    c.vline(7, B - 30, B - 3, STONE[1])
    c.vline(8, B - 30, B - 3, STONE[0])
    for side in (-1, 1):
        c.line(8, B - 28, 8 + side * 5, B - 30, STONE[1])
        x = 8 + side * 5
        c.rect(x - 1, B - 29, 3, 4, YELLOW[2])
        c.put(x, B - 28, WHITE[2])
        c.hline(x - 1, x + 1, B - 30, STONE[0])
    c.put(8, B - 32, GOLD[3])
    c.outline(INK)
    return Art(c, top)


def hedge_arch() -> Art:
    c, top = new(1, 1, 28)
    B = c.h - 2
    for y in range(B - 26, B):
        for x in range(16):
            inner = (x + 0.5 - 8) ** 2 / 4.5**2 + (y + 0.5 - (B - 12)) ** 2 / 10**2 <= 1 or (y > B - 12 and 4 <= x <= 11)
            outer = (x + 0.5 - 8) ** 2 / 8**2 + (y + 0.5 - (B - 12)) ** 2 / 14**2 <= 1 or (y > B - 12)
            if outer and not inner:
                u = x / 15
                i = 3 if u < 0.3 else 2 if u < 0.75 else 1
                if hash2(x, y, 906) < 0.15:
                    i -= 1
                c.put(x, y, LEAF[max(0, i)])
    for x, y in ((3, -20), (12, -18), (8, -25)):
        c.put(x, B + y, PINK[2])
    c.outline(INK)
    return Art(c, top)


def banner_pole() -> Art:
    c, top = new(1, 1, 44)
    B = c.h - 2
    c.vline(7, B - 40, B, WOOD[1])
    c.vline(8, B - 40, B, WOOD[3])
    c.put(7, B - 41, GOLD[3])
    c.put(8, B - 41, GOLD[4])
    for y in range(B - 38, B - 18):
        for x in range(9, 15):
            if y > B - 21 and x in (11, 12):
                continue
            c.put(x, y, BLUE[3] if x < 11 else BLUE[2])
    for y in (B - 34, B - 30):
        c.hline(10, 13, y, GOLD[3])
    c.hline(5, 10, B, STONE[2])
    c.outline(INK)
    return Art(c, top)


DECOR: dict[str, tuple[Callable[[], Art], tuple[int, int]]] = {
    "path_dirt": (path_dirt, (1, 1)),
    "path_stone": (path_stone, (1, 1)),
    "flower_bed": (flower_bed, (1, 1)),
    "hedge": (hedge, (1, 1)),
    "bench": (bench, (1, 1)),
    "lantern": (lantern, (1, 1)),
    "young_tree": (young_tree, (1, 1)),
    "well": (well, (2, 2)),
    "banner": (banner_deco, (1, 1)),
    "market_stall": (market_stall, (2, 1)),
    "pumpkins": (pumpkins, (1, 1)),
    "fountain": (fountain, (2, 2)),
    "statue": (statue, (1, 1)),
    "lantern_post": (lantern_post, (1, 1)),
    "stone_fountain": (lambda: fountain(runic=True), (2, 2)),
    "hedge_arch": (hedge_arch, (1, 1)),
    "banner_pole": (banner_pole, (1, 1)),
}


def generate() -> tuple[dict[str, Canvas], dict[str, dict]]:
    sprites: dict[str, Canvas] = {}
    meta: dict[str, dict] = {}
    for key, (fn, (fw, fh)) in DECOR.items():
        a = fn()
        name = f"building.{key}.a.l1"
        sprites[name] = a.canvas
        meta[name] = {"footprint": [fw, fh], "anchor": [0, a.top], "smoke": []}
    _ = math  # (kept for future curved pieces)
    return sprites, meta
