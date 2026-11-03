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


# ── richer props (art pass 2) ───────────────────────────────────────────────
BIRCH = ramp("birch")
LILY = ramp("lilypad")
MUSH = ramp("mushroom")
WATER_R = ramp("water")
FRED = ramp("flower_red")
FPINK = ramp("flower_pink")
FYEL = ramp("flower_yellow")
FPUR = ramp("flower_purple")
FWHITE = ramp("flower_white")
GOLD_R = ramp("gold")
FIRE_R = ramp("fire")


def big_oak(variant: int) -> Canvas:
    c = Canvas(46, 54)
    c.drop_shadow(24, 50, 16, 4)
    for y in range(34, 51):  # trunk with roots
        for x in range(19, 27):
            c.put(x, y, WOOD[3] if x < 21 else WOOD[1] if x > 24 else WOOD[2])
    for dx in (-3, -2, 7, 8):
        c.put(19 + dx if dx < 0 else 19 + dx, 50, WOOD[2])
    c.put(17, 50, WOOD[2])
    c.put(28, 50, WOOD[1])
    s = variant % 2
    circles = [(12, 24, 10), (34 - s, 22, 10.5), (23, 13, 11.5), (23, 28, 11), (15 + s, 12, 7.5), (31, 12, 7.5),
               (8, 30, 6), (38, 30, 6)]
    blob(c, circles, LEAF, seed=50 + variant)
    for i in range(22):
        x = int(6 + hash2(i, variant, 53) * 34)
        y = int(4 + hash2(variant, i, 54) * 30)
        if c.filled(x, y) and c.filled(x + 1, y + 1) and c.filled(x - 1, y - 1):
            c.put(x, y, LEAF[4] if y < 18 and x < 26 else LEAF[1])
            c.put(x + 1, y, LEAF[3] if y < 18 else LEAF[1])
    c.outline(INK)
    return c


def birch(variant: int) -> Canvas:
    c = Canvas(26, 42)
    c.drop_shadow(13, 39, 8, 2.5)
    for y in range(18, 40):
        for x in range(11, 15):
            col = BIRCH[3] if x < 13 else BIRCH[2]
            if hash2(x, y // 2, 61 + variant) < 0.22:
                col = BIRCH[0]
            c.put(x, y, col)
    blob(c, [(8, 15, 7), (18, 14, 7.5), (13, 8, 7), (13, 19, 6)], ramp("grass")[1:], seed=60 + variant)
    c.outline(INK)
    return c


def apple_tree(variant: int) -> Canvas:
    c = oak(variant)
    for i in range(9):
        x = int(6 + hash2(i, variant, 71) * 18)
        y = int(5 + hash2(variant, i, 72) * 16)
        if c.solid(x, y) and c.get(x, y) != INK and c.solid(x + 1, y + 1):
            c.put(x, y, FRED[1])
            c.put(x + 1, y, FRED[2])
            c.put(x, y + 1, FRED[0])
    return c


def flower_bush(variant: int) -> Canvas:
    c = bush(0)
    petals = [FPINK, FYEL, FWHITE, FPUR][variant % 4]
    for i in range(10):
        x = int(3 + hash2(i, variant, 81) * 12)
        y = int(3 + hash2(variant, i, 82) * 8)
        if c.solid(x, y) and c.get(x, y) != INK:
            c.put(x, y, petals[2])
            if c.solid(x + 1, y) and c.get(x + 1, y) != INK:
                c.put(x + 1, y, petals[1])
    return c


def mossy_rock(variant: int) -> Canvas:
    c = rock(True, variant)
    for x in range(c.w):
        for y in range(c.h):
            if c.solid(x, y) and c.get(x, y) != INK and not c.solid(x, y - 1) and hash2(x, y, 91) < 0.8:
                c.put(x, y, GRASS[3])
                if c.solid(x, y + 1) and c.get(x, y + 1) != INK:
                    c.put(x, y + 1, GRASS[2])
    return c


def log() -> Canvas:
    c = Canvas(28, 12)
    c.drop_shadow(14, 10, 12, 2)
    for y in range(2, 9):
        for x in range(4, 25):
            k = y - 2
            c.put(x, y, [WOOD[4], WOOD[3], WOOD[3], WOOD[2], WOOD[2], WOOD[1], WOOD[1]][k])
            if hash2(x // 2, y, 93) < 0.15:
                c.put(x, y, WOOD[1])
    c.ellipse(4.5, 5.5, 3, 3.6, WOOD[5])
    c.ellipse(4.5, 5.5, 1.6, 2, WOOD[4])
    c.put(4, 5, WOOD[3])
    for x in (9, 15, 20):  # moss
        c.put(x, 2, GRASS[3])
        c.put(x + 1, 2, GRASS[2])
    c.outline(INK)
    return c


def mushrooms(variant: int) -> Canvas:
    c = Canvas(14, 11)
    caps = [(4, 6, 3), (9, 5, 2.5), (7, 8, 2)] if variant == 0 else [(5, 5, 3.4), (10, 7, 2.2)]
    for cx, cy, r in caps:
        c.vline(int(cx), int(cy), int(cy + r + 1), MUSH[3])
        c.ellipse(cx, cy, r, r * 0.7, MUSH[2])
        c.hline(int(cx - r + 1), int(cx + r - 1), int(cy + r * 0.5), MUSH[1])
        c.put(int(cx) - 1, int(cy) - 1, MUSH[3])
        c.put(int(cx) + 1, int(cy), MUSH[3])
    c.outline(INK)
    return c


def reeds(variant: int) -> Canvas:
    c = Canvas(14, 20)
    for i in range(5):
        x = 2 + i * 2 + (i + variant) % 2
        h = 10 + int(hash2(i, variant, 101) * 7)
        for d in range(h):
            c.put(x + (d > h - 4 and i % 2), 19 - d, GRASS[3] if d > h // 2 else GRASS[1])
        if i % 2 == 0:  # cattail heads
            c.rect(x, 19 - h, 2, 4, WOOD[1])
            c.put(x, 19 - h, WOOD[2])
    c.outline(INK)
    return c


def lilypad(variant: int) -> Canvas:
    c = Canvas(12, 9)
    c.ellipse(6, 5, 5, 3.4, LILY[1])
    c.ellipse(5.5, 4.5, 4, 2.6, LILY[2])
    for x in range(6, 11):  # notch
        c.put(x, 5, (0, 0, 0, 0))
    if variant == 1:
        c.put(4, 3, FPINK[2])
        c.put(5, 3, FPINK[1])
        c.put(4, 2, FWHITE[2])
    c.outline(INK)
    return c


def pebbles(variant: int) -> Canvas:
    c = Canvas(12, 7)
    for i, (x, y, r) in enumerate(((3, 4, 1.8), (7, 3, 2.2), (9.5, 5, 1.4), (5.5, 5.5, 1.2))[: 3 + variant]):
        c.ellipse(x, y, r, r * 0.75, STONE[3])
        c.put(int(x) - 1 + (i % 2), int(y) - 1, STONE[4])
    c.outline(INK)
    return c


def flower_clump(variant: int) -> Canvas:
    c = Canvas(14, 10)
    petals = [FPINK, FYEL, FWHITE, FPUR, FRED][variant % 5]
    for i in range(7):
        x = 2 + int(hash2(i, variant, 111) * 10)
        y = 3 + int(hash2(variant, i, 112) * 5)
        c.vline(x, y, 9, GRASS[1])
        c.put(x - 1, y, petals[1])
        c.put(x + 1, y, petals[1])
        c.put(x, y - 1, petals[2])
        c.put(x, y, FYEL[2] if petals is not FYEL else FRED[1])
    for x in range(1, 13, 2):
        c.put(x, 9, GRASS[2])
    return c


def fence(kind: str) -> Canvas:
    """Fence pieces for the plot boundary: horizontal rail (16 wide), vertical rail, post, gate posts."""
    if kind == "h":
        c = Canvas(16, 14)
        for y in (5, 9):
            c.hline(0, 15, y, WOOD[4])
            c.hline(0, 15, y + 1, WOOD[2])
        for px in (0, 15):
            c.rect(px - 1 if px else 0, 2, 2, 11, WOOD[3])
    elif kind == "v":
        # seen from above: two rails running down the tile, with a post at the bottom
        c = Canvas(8, 22)
        for x in (1, 5):
            c.vline(x, 0, 17, WOOD[4] if x == 1 else WOOD[3])
            c.vline(x + 1, 0, 17, WOOD[2])
        c.rect(2, 12, 4, 9, WOOD[3])
        c.vline(5, 12, 20, WOOD[2])
        c.hline(2, 5, 11, WOOD[5])
    elif kind == "post":
        c = Canvas(6, 14)
        c.rect(2, 2, 3, 11, WOOD[3])
        c.vline(4, 2, 12, WOOD[2])
        c.hline(2, 4, 1, WOOD[5])
    else:  # gate post with a lantern
        c = Canvas(8, 24)
        c.rect(2, 4, 4, 19, WOOD[3])
        c.vline(5, 4, 22, WOOD[2])
        c.hline(1, 6, 3, WOOD[5])
        c.rect(2, 0, 4, 3, FIRE_R[3])
        c.put(3, 1, FIRE_R[4])
    c.outline(INK)
    return c


def lamp_post() -> Canvas:
    c = Canvas(10, 30)
    c.drop_shadow(5, 28, 3, 1.2)
    c.rect(4, 8, 2, 20, WOOD[1])
    c.hline(2, 7, 27, STONE[3])
    c.rect(2, 2, 6, 6, FIRE_R[3])
    c.rect(3, 3, 4, 4, FIRE_R[4])
    c.hline(1, 8, 1, WOOD[1])
    c.hline(2, 7, 8, WOOD[1])
    c.outline(INK)
    return c


def signpost() -> Canvas:
    c = Canvas(18, 22)
    c.drop_shadow(9, 20, 4, 1.4)
    c.rect(8, 6, 2, 15, WOOD[2])
    c.rect(2, 3, 14, 6, WOOD[4])
    c.hline(2, 15, 3, WOOD[5])
    c.hline(2, 15, 8, WOOD[2])
    for x in range(4, 14, 3):
        c.put(x, 5, WOOD[1])
        c.put(x + 1, 6, WOOD[1])
    c.outline(INK)
    return c


# ── ambient animation frames ────────────────────────────────────────────────


def duck_frames() -> list[Canvas]:
    out = []
    for f in range(2):
        c = Canvas(12, 10)
        c.ellipse(5.5, 6.5, 4.5, 2.6, FWHITE[2])  # body
        c.hline(2, 9, 8, FWHITE[0])
        c.ellipse(3, 3.5 + (f == 1) * 0.5, 2, 2, LEAF[2])  # green head
        c.put(2, 3, INK)
        c.rect(0, 4, 2, 1, FYEL[1])  # beak
        c.put(9, 5 - f, FWHITE[1])  # tail
        c.hline(3, 8, 9, WATER_R[4])  # ripple
        c.outline(INK)
        out.append(c)
    return out


def butterfly_frames(color: int) -> list[Canvas]:
    wing = [FPINK, FYEL, FWHITE, FPUR][color]
    out = []
    for f in range(2):
        c = Canvas(7, 6)
        c.vline(3, 1, 4, INK)
        if f == 0:
            for x, y in ((1, 1), (2, 1), (1, 2), (2, 2), (4, 1), (5, 1), (4, 2), (5, 2), (2, 3), (4, 3)):
                c.put(x, y, wing[1] if y > 1 else wing[2])
        else:
            for x, y in ((2, 1), (2, 2), (4, 1), (4, 2), (2, 3), (4, 3)):
                c.put(x, y, wing[1])
        out.append(c)
    return out


def smoke_frames() -> list[Canvas]:
    out = []
    for f in range(5):
        c = Canvas(10, 10)
        r = 1.6 + f * 0.7
        a = 210 - f * 40
        col = (230, 226, 232, a)
        c.ellipse(5, 5, r, r * 0.9, col)
        c.ellipse(4.3, 4.3, r * 0.5, r * 0.45, (250, 248, 250, a))
        out.append(c)
    return out


def glint_frames() -> list[Canvas]:
    out = []
    for size in (0, 1, 2, 1):
        c = Canvas(5, 5)
        c.put(2, 2, WATER_R[5])
        for d in range(1, size + 1):
            for dx, dy in ((d, 0), (-d, 0)):
                c.put(2 + dx, 2 + dy, WATER_R[4])
        out.append(c)
    return out


def leaf_frames() -> list[Canvas]:
    out = []
    for f in range(2):
        c = Canvas(4, 4)
        if f == 0:
            c.put(0, 1, LEAF[3])
            c.put(1, 1, LEAF[4])
            c.put(2, 2, LEAF[3])
        else:
            c.put(1, 0, LEAF[3])
            c.put(1, 1, LEAF[4])
            c.put(2, 2, LEAF[2])
        out.append(c)
    return out


def bird_frames() -> list[Canvas]:
    out = []
    for f in range(2):
        c = Canvas(9, 5)
        if f == 0:
            for x, y in ((0, 0), (1, 1), (2, 2), (3, 2), (4, 3), (5, 2), (6, 2), (7, 1), (8, 0)):
                c.put(x, y, INK)
        else:
            for x, y in ((0, 3), (1, 2), (2, 2), (3, 2), (4, 3), (5, 2), (6, 2), (7, 2), (8, 3)):
                c.put(x, y, INK)
        out.append(c)
    return out


def generate_extra() -> dict[str, Canvas]:
    out: dict[str, Canvas] = {}
    for v in range(2):
        out[f"obj.big_oak.{v}"] = big_oak(v)
        out[f"obj.birch.{v}"] = birch(v)
        out[f"obj.apple.{v}"] = apple_tree(v)
        out[f"obj.mossy_rock.{v}"] = mossy_rock(v)
        out[f"obj.mushrooms.{v}"] = mushrooms(v)
        out[f"obj.reeds.{v}"] = reeds(v)
        out[f"obj.lilypad.{v}"] = lilypad(v)
        out[f"obj.pebbles.{v}"] = pebbles(v)
    for v in range(4):
        out[f"obj.flower_bush.{v}"] = flower_bush(v)
    for v in range(5):
        out[f"obj.flowers.{v}"] = flower_clump(v)
    out["obj.log.0"] = log()
    out["obj.lamp.0"] = lamp_post()
    out["obj.signpost.0"] = signpost()
    for k in ("h", "v", "post", "gate"):
        out[f"obj.fence.{k}"] = fence(k)
    for name, frames in (("duck", duck_frames()), ("smoke", smoke_frames()), ("glint", glint_frames()),
                         ("leaf", leaf_frames()), ("bird", bird_frames())):
        for i, f in enumerate(frames):
            out[f"fx.{name}.{i}"] = f
    for col in range(4):
        for i, f in enumerate(butterfly_frames(col)):
            out[f"fx.butterfly{col}.{i}"] = f
    return out
