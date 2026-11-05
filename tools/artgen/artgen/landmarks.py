"""Phase 10 points of interest: ruins and their chest, a shrine, a lore stone, a sealed cave, a trader's
stall and a lost villager. Anchor = bottom-centre, like every map object."""

from __future__ import annotations

from artgen.bestiary import _o, _s, ell
from artgen.canvas import Canvas, hash2
from artgen.palette import INK, ramp

STONE = ramp("stone")
WOOD = ramp("wood")
GOLD = ramp("gold")
LEAF = ramp("leaf")
GRASS = ramp("grass")
ICE = ramp("ice")
WATER = ramp("water")
FIRE = ramp("fire")
CREAM = ramp("cloth_cream")
RED = ramp("flower_red")
DIRT = ramp("dirt")


def _blocks(c: Canvas, x0: int, y0: int, x1: int, y1: int, seed: int, ragged: bool = True) -> None:
    """A wall of offset stone blocks, lit from the top-left, with a broken top edge."""
    for y in range(y0, y1):
        row = (y - y0) // 3
        for x in range(x0, x1):
            top = y0 + (int(hash2(x // 2, 0, seed) * 5) if ragged else 0)
            if y < top:
                continue
            seam_h = (y - y0) % 3 == 2
            seam_v = (x + (row % 2) * 2) % 5 == 0
            col = STONE[1] if seam_h or seam_v else STONE[3] if x < (x0 + x1) // 2 else STONE[2]
            if y == top:
                col = STONE[4]
            c.put(x, y, col)
    for x in range(x0, x1):  # moss creeping up from the ground
        if hash2(x, 1, seed + 3) < 0.55:
            c.put(x, y1 - 1, LEAF[2])
            if hash2(x, 2, seed + 4) < 0.4:
                c.put(x, y1 - 2, LEAF[3])


def ruins(variant: int) -> Canvas:
    if variant == 0:  # a broken wall with an arch gap
        c = Canvas(26, 22)
        c.drop_shadow(13, 20, 11, 2)
        _blocks(c, 2, 4, 24, 20, 61)
        for y in range(11, 20):  # the arch
            for x in range(10, 16):
                if y > 13 or (x - 12.5) ** 2 + (y - 13) ** 2 < 9:
                    c.put(x, y, None)
    else:  # a toppled pillar stump with a fallen drum
        c = Canvas(22, 26)
        c.drop_shadow(11, 24, 9, 2)
        _blocks(c, 5, 6, 13, 24, 71, ragged=True)
        ell(c, 16, 21, 4, 2.6, STONE[1:5])
        c.hline(13, 19, 21, STONE[1])
    c.outline(INK)
    return c


def chest(opened: bool) -> Canvas:
    c = Canvas(16, 15)
    c.drop_shadow(8, 13, 6.5, 1.6)
    # body
    for y in range(7, 13):
        for x in range(2, 14):
            c.put(x, y, WOOD[3] if y < 9 else WOOD[2] if x < 12 else WOOD[1])
    for x in (4, 11):
        c.vline(x, 7, 12, GOLD[2])
    if opened:
        for y in range(1, 6):  # lid tipped back
            c.hline(3, 12, y, WOOD[2] if y > 2 else WOOD[3])
        c.hline(2, 13, 6, WOOD[1])
        c.hline(3, 12, 7, INK)
        c.put(7, 8, GOLD[3])
    else:
        for y in range(4, 8):
            c.hline(2, 13, y, WOOD[4] if y == 4 else WOOD[3])
        c.hline(2, 13, 7, WOOD[1])
        c.rect(7, 7, 2, 2, GOLD[3])
        c.put(7, 8, GOLD[1])
    c.outline(INK)
    return c


def shrine() -> Canvas:
    c = Canvas(22, 28)
    c.drop_shadow(11, 26, 9, 2)
    # stepped plinth
    for y, (x0, x1) in zip(range(20, 26), [(4, 18), (4, 18), (3, 19), (3, 19), (2, 20), (2, 20)], strict=False):
        c.hline(x0, x1 - 1, y, STONE[3] if y % 2 == 0 else STONE[2])
    c.hline(2, 19, 25, STONE[1])
    # pillar
    for y in range(11, 20):
        c.hline(8, 13, y, STONE[3] if y < 13 else STONE[2])
        c.put(8, y, STONE[4])
    c.hline(6, 15, 10, STONE[4])
    c.hline(6, 15, 11, STONE[2])
    # the glowing orb in a little cradle
    ell(c, 10.5, 6.5, 3.4, 3.4, WATER[2:] + ICE[2:])
    c.put(9, 5, (255, 255, 255, 255))
    c.put(7, 9, GOLD[2])
    c.put(14, 9, GOLD[2])
    # candles either side
    for cx in (4, 17):
        c.vline(cx, 17, 19, CREAM[3])
        c.put(cx, 16, FIRE[3])
        c.put(cx, 15, FIRE[4])
    c.outline(INK)
    return c


def lore_stone() -> Canvas:
    c = Canvas(16, 30)
    c.drop_shadow(8, 28, 6, 1.8)
    for y in range(3, 27):
        w = 5 if y > 6 else 5 - (6 - y) // 2
        for x in range(8 - w, 8 + w):
            col = STONE[3] if x < 7 else STONE[2] if x < 11 else STONE[1]
            if y < 5:
                col = STONE[4]
            c.put(x, y, col)
    # carved, softly glowing runes
    rune = [(6, 8), (7, 9), (8, 8), (9, 10), (6, 13), (8, 13), (7, 14), (9, 15), (6, 18), (7, 19), (8, 18), (9, 20), (7, 23), (8, 22)]
    for x, y in rune:
        c.put(x, y, ICE[3] if (x + y) % 3 else ICE[2])
    for x in range(3, 13):  # grass at the foot
        if hash2(x, 0, 91) < 0.6:
            c.put(x, 26, GRASS[3])
    c.outline(INK)
    return c


def cave() -> Canvas:
    c = Canvas(36, 28)
    c.drop_shadow(18, 26, 15, 2)
    ell(c, 18, 18, 16, 10.5, STONE[1:5], flat_bottom=2.2)
    ell(c, 9, 20, 7, 6, STONE[1:5], flat_bottom=2.0)
    ell(c, 27, 20, 7, 5.5, STONE[1:5], flat_bottom=2.0)
    # the dark mouth
    for y in range(14, 26):
        for x in range(12, 25):
            if (x - 18) ** 2 / 36 + (y - 25) ** 2 / 121 < 1:
                c.put(x, y, _o("charcoal")[0])
    # boards across it and a rune seal
    for y in (17, 21):
        c.hline(11, 25, y, WOOD[3])
        c.hline(11, 25, y + 1, WOOD[1])
    c.put(17, 19, ICE[3])
    c.put(18, 19, ICE[2])
    c.put(17, 20, ICE[2])
    c.put(18, 20, ICE[3])
    for x in range(4, 33):  # moss on top
        if hash2(x, 3, 101) < 0.35:
            top = min((y for y in range(c.h) if c.filled(x, y)), default=None)
            if top is not None:
                c.put(x, top, LEAF[3])
    c.outline(INK)
    return c


def trader() -> Canvas:
    c = Canvas(32, 32)
    c.drop_shadow(16, 30, 13, 2)
    # back posts and awning
    for x in (4, 27):
        c.vline(x, 8, 28, WOOD[2])
    for x in range(2, 30):
        stripe = ((x - 2) // 4) % 2
        for y in range(5, 10):
            if y == 9 and x % 4 == 1:
                continue
            c.put(x, y, (RED[1] if y > 6 else RED[2]) if stripe else (CREAM[2] if y > 6 else CREAM[3]))
    c.hline(2, 29, 4, RED[0])
    # the trader behind the counter
    ell(c, 16, 14, 3, 3, _s("tan"))
    c.hline(13, 18, 11, _o("teal")[1])  # cap
    c.hline(14, 18, 10, _o("teal")[2])
    c.put(15, 14, INK)
    c.put(17, 14, INK)
    for y in range(17, 21):
        c.hline(12, 20, y, _o("teal")[2] if y < 19 else _o("teal")[1])
    # counter with goods
    for y in range(20, 28):
        c.hline(5, 26, y, WOOD[3] if y == 20 else WOOD[2] if y < 26 else WOOD[1])
    for gx, col in ((7, GOLD[3]), (10, ICE[2]), (21, RED[2]), (24, LEAF[3])):
        c.put(gx, 19, col)
        c.put(gx + 1, 19, col)
        c.put(gx, 18, col)
    ell(c, 27.5, 26, 3, 2.5, WOOD[1:5])  # a sack
    c.outline(INK)
    return c


def lost_villager() -> Canvas:
    c = Canvas(22, 20)
    c.drop_shadow(11, 18, 8, 1.6)
    # bundle on a stick
    c.line(15, 17, 19, 9, WOOD[2])
    ell(c, 19, 9, 2.6, 2.2, _o("rose"))
    # sitting body, knees up, hugging them
    for y in range(11, 18):
        c.hline(7, 12, y, _o("mustard")[2] if y < 15 else _o("mustard")[1])
    c.hline(5, 9, 15, _o("navy")[2])  # knees
    c.hline(5, 9, 16, _o("navy")[1])
    c.vline(5, 16, 17, DIRT[1])
    ell(c, 9.5, 8.5, 3, 3, _s("peach"))
    for x in range(7, 13):  # hair
        c.put(x, 6, ramp("dirt")[1])
    c.put(8, 9, INK)
    c.put(10, 9, INK)
    c.put(9, 11, _s("peach")[0])  # a little frown
    c.outline(INK)
    return c


def generate() -> dict[str, Canvas]:
    return {
        "obj.ruins.0": ruins(0),
        "obj.ruins.1": ruins(1),
        "obj.chest.0": chest(False),
        "obj.chest.1": chest(True),
        "obj.shrine.0": shrine(),
        "obj.lore_stone.0": lore_stone(),
        "obj.cave.0": cave(),
        "obj.trader.0": trader(),
        "obj.lost_villager.0": lost_villager(),
    }
