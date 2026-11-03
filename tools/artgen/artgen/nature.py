"""Trees, bushes, rocks and other world props. Anchor = bottom-centre of the base tile."""

from __future__ import annotations

from artgen.canvas import Canvas, blob, hash2
from artgen.palette import INK, ramp

LEAF = ramp("leaf")
PINE = ramp("pine")
WOOD = ramp("wood")
STONE = ramp("stone")
GRASS = ramp("grass")


def oak(variant: int) -> Canvas:
    c = Canvas(30, 34)
    c.drop_shadow(15, 31, 10, 3)
    # trunk
    for y in range(20, 32):
        for x in range(13, 18):
            c.put(x, y, WOOD[3] if x == 13 else WOOD[1] if x == 17 else WOOD[2])
    c.put(12, 31, WOOD[2])
    c.put(18, 31, WOOD[1])
    s = variant % 3
    circles = [(9.5, 14, 7.5), (20.5 - s, 13.5, 7.5), (15, 8.5, 8), (15, 16.5, 8.5), (11 + s, 8, 5.5),
               (19, 8.5, 5.5)]
    if variant == 1:
        circles.append((6.5, 18, 4.5))
    if variant == 2:
        circles.append((23, 18, 4.5))
    blob(c, circles, LEAF, seed=variant)
    # a few leaf clusters for texture
    for i in range(10):
        x = int(6 + hash2(i, variant, 3) * 18)
        y = int(4 + hash2(variant, i, 4) * 16)
        if c.filled(x, y) and c.filled(x + 1, y + 1):
            c.put(x, y, LEAF[4] if y < 11 and x < 16 else LEAF[1])
    c.outline(INK)
    return c


def pine(variant: int) -> Canvas:
    c = Canvas(22, 36)
    c.drop_shadow(11, 33, 7, 2.5)
    for y in range(28, 34):
        for x in range(10, 13):
            c.put(x, y, WOOD[2] if x < 12 else WOOD[1])
    tiers = [(11, 4, 4, 7), (11, 10, 6, 8), (11, 17, 8, 9), (11, 23, 9, 7)]
    pts = set()
    for cx, top, half, h in tiers:
        for dy in range(h):
            w = max(1, int(half * (dy + 1) / h))
            for x in range(cx - w, cx + w + 1):
                pts.add((x, top + dy))
    for x, y in pts:
        lit = x < 11 - (y % 3 == 0)
        bottom = (x, y + 1) not in pts
        i = 3 if lit else 2
        if bottom:
            i -= 1
        if hash2(x, y, variant + 9) < 0.15:
            i -= 1
        c.put(x, y, PINE[max(0, i)])
    c.outline(INK)
    return c


def bush(variant: int) -> Canvas:
    c = Canvas(18, 15)
    c.drop_shadow(9, 13, 7, 2)
    blob(c, [(6, 9, 4.5), (11, 8, 5), (9, 6, 4)], LEAF, seed=20 + variant)
    if variant == 1:  # berries
        for x, y in ((6, 8), (11, 6), (12, 10), (8, 11)):
            c.put(x, y, ramp("flower_red")[1])
            c.put(x, y - 1, ramp("flower_red")[2])
    c.outline(INK)
    return c


def rock(big: bool, variant: int) -> Canvas:
    w, h = (24, 18) if big else (15, 12)
    c = Canvas(w, h)
    c.drop_shadow(w / 2, h - 2.5, w / 2 - 2, 2.2)
    circles = (
        [(9, 10, 6), (15, 9, 6.5), (12, 6, 5)] if big else [(6, 7, 4.5), (9, 6.5, 4)]
    )
    pts = blob(c, circles, STONE[1:5], seed=40 + variant)
    for x, y in pts:  # cracks
        if hash2(x, y, 44 + variant) < 0.04 and (x + 1, y + 1) in pts:
            c.put(x, y, STONE[1])
    if big and variant == 1:
        for x, y in ((8, 9), (9, 9), (14, 11)):  # moss
            c.put(x, y, GRASS[2])
    c.outline(INK)
    return c


def stump() -> Canvas:
    c = Canvas(14, 11)
    c.drop_shadow(7, 9, 6, 2)
    for y in range(4, 9):
        for x in range(3, 11):
            c.put(x, y, WOOD[3] if x < 5 else WOOD[1] if x > 8 else WOOD[2])
    c.ellipse(7, 4, 4, 2, WOOD[4])
    c.put(6, 4, WOOD[3])
    c.put(8, 4, WOOD[3])
    c.put(7, 4, WOOD[2])
    c.outline(INK)
    return c


def tall_grass(variant: int) -> Canvas:
    c = Canvas(12, 10)
    for i in range(5):
        x = 2 + i * 2 + (variant + i) % 2
        h = 4 + int(hash2(i, variant, 70) * 4)
        for dy in range(h):
            c.put(x - (dy > h - 2 and i % 2), 9 - dy, GRASS[3] if dy > h - 3 else GRASS[1] if dy < 2 else GRASS[2])
    return c


def fence_post() -> Canvas:
    c = Canvas(6, 12)
    c.rect(2, 2, 2, 9, WOOD[3])
    c.vline(3, 2, 10, WOOD[2])
    c.put(2, 1, WOOD[4])
    c.put(3, 1, WOOD[3])
    c.outline(INK)
    return c


def well() -> Canvas:
    c = Canvas(28, 32)
    c.drop_shadow(14, 29, 11, 3)
    # stone ring
    for y in range(18, 29):
        for x in range(5, 23):
            row = (y - 18) // 3
            brick = ((x + (row % 2) * 2) // 4 + row) % 2
            c.put(x, y, STONE[3] if brick else STONE[2])
            if (y - 18) % 3 == 2:
                c.put(x, y, STONE[1])
    c.ellipse(14, 18, 9, 3, STONE[4])
    c.ellipse(14, 18, 6.5, 2, ramp("water")[1])
    # posts + roof
    c.rect(6, 6, 2, 13, WOOD[2])
    c.rect(20, 6, 2, 13, WOOD[1])
    for y in range(2, 9):
        half = 4 + (y - 2) * 2
        for x in range(14 - half, 14 + half):
            c.put(x, y, ramp("roof_red")[3] if x < 14 else ramp("roof_red")[2])
    c.hline(4, 23, 8, ramp("roof_red")[1])
    c.outline(INK)
    return c


def generate() -> dict[str, Canvas]:
    out: dict[str, Canvas] = {}
    for v in range(3):
        out[f"obj.oak.{v}"] = oak(v)
    for v in range(2):
        out[f"obj.pine.{v}"] = pine(v)
        out[f"obj.bush.{v}"] = bush(v)
        out[f"obj.rock.{v}"] = rock(False, v)
        out[f"obj.rock_big.{v}"] = rock(True, v)
        out[f"obj.tall_grass.{v}"] = tall_grass(v)
    out["obj.stump.0"] = stump()
    out["obj.fence_post.0"] = fence_post()
    out["obj.well.0"] = well()
    return out
