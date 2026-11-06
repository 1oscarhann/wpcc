"""Phase 12 delves: a dark stone tileset and its props, plus the Delve Gate that stands in the hub.

Tiles: `tile.dfloor.{0-3}` flagstones, `tile.dwall.face` (a wall seen from the front, above a floor),
`tile.dwall.top` (the dark top of a wall). Props are ordinary objects (anchor bottom-centre).
"""

from __future__ import annotations

import math

from artgen.bestiary import ell
from artgen.canvas import Canvas, hash2
from artgen.palette import INK, ramp

T = 16
STONE = ramp("stone")
ASH = ramp("ash")
OBS = ramp("obsidian")
WOOD = ramp("wood")
FIRE = ramp("fire")
GOLD = ramp("gold")
ICE = ramp("ice")
VIOLET = ramp("flower_purple")
CREAM = ramp("cloth_cream")
RED = ramp("roof_red")
WHITE = ramp("flower_white")
LEAF = ramp("leaf")


def floor(v: int) -> Canvas:
    c = Canvas(T, T)
    for y in range(T):
        for x in range(T):
            # big flagstones with dark seams, a little noise, the odd crack
            bx, by = (x + (v * 5) % 8) // 8, (y + (v * 3) % 8) // 8
            seam = (x + (v * 5) % 8) % 8 == 0 or (y + (v * 3) % 8) % 8 == 0
            n = hash2(x, y, 700 + v)
            shade = 2 if hash2(bx, by, 710 + v) > 0.5 else 1
            col = ASH[0] if seam else ASH[shade + (1 if n > 0.9 else 0)]
            c.put(x, y, col)
    if v == 3:
        for i in range(5):
            c.put(4 + i, 9 + (i % 2), ASH[0])
    if v == 2:
        c.put(11, 4, LEAF[1])
        c.put(12, 4, LEAF[0])
    return c


def wall_face() -> Canvas:
    c = Canvas(T, T)
    for y in range(T):
        for x in range(T):
            row = y // 4
            seam = y % 4 == 3 or (x + (row % 2) * 4) % 8 == 7
            col = STONE[0] if seam else (STONE[2] if y < 6 else STONE[1])
            if y < 2:
                col = STONE[3]
            c.put(x, y, col)
    for x in range(T):
        c.put(x, T - 1, INK)
    return c


def wall_top() -> Canvas:
    c = Canvas(T, T)
    for y in range(T):
        for x in range(T):
            c.put(x, y, OBS[0] if hash2(x, y, 720) > 0.2 else OBS[1])
    return c


def gate(open_: bool) -> Canvas:
    """A portcullis filling one door tile; doors are three of these side by side."""
    c = Canvas(T, 22)
    c.rect(0, 0, T, 3, STONE[1])
    c.hline(0, T - 1, 0, STONE[3])
    if open_:
        for x in range(1, T, 3):
            c.vline(x, 3, 5, STONE[2])
            c.put(x, 6, STONE[3])
    else:
        for x in range(1, T, 3):
            c.vline(x, 3, 21, STONE[2])
            c.vline(x + 1, 3, 21, STONE[1])
        for y in (8, 15):
            c.hline(0, T - 1, y, STONE[1])
        for x in range(1, T, 3):
            c.put(x, 21, STONE[3])
    c.outline(INK)
    return c


def torch(frame: int) -> Canvas:
    c = Canvas(8, 14)
    c.rect(3, 7, 2, 6, WOOD[2])
    c.rect(2, 6, 4, 2, STONE[2])
    flick = [(3, 5), (4, 4), (3, 3), (4, 2)] if frame == 0 else [(4, 5), (3, 4), (4, 3), (3, 2)]
    for i, (x, y) in enumerate(flick):
        c.put(x, y, FIRE[3 - min(2, i // 2)])
        c.put(x + (1 if i % 2 else -1), y + 1, FIRE[2])
    c.put(flick[-1][0], 1, FIRE[4])
    c.outline(INK)
    return c


def pillar() -> Canvas:
    c = Canvas(T, 30)
    c.drop_shadow(8, 28, 6.5, 1.6)
    for y in range(3, 27):
        for x in range(3, 13):
            c.put(x, y, STONE[3] if x < 6 else STONE[2] if x < 10 else STONE[1])
    c.rect(1, 1, 14, 3, STONE[3])
    c.rect(1, 25, 14, 3, STONE[2])
    for y in range(6, 24, 6):
        c.hline(3, 12, y, STONE[1])
    c.outline(INK)
    return c


def rubble(v: int) -> Canvas:
    c = Canvas(14, 10)
    for i in range(4 + v):
        ell(c, 3 + hash2(i, v, 731) * 8, 6 + hash2(v, i, 732) * 2, 1.6 + hash2(i, i, 733), 1.3, STONE[1:4])
    c.outline(INK)
    return c


def bones(v: int) -> Canvas:
    c = Canvas(14, 9)
    c.line(2, 6, 11, 4 - v, CREAM[3])
    c.line(3, 7, 11, 5 - v, CREAM[2])
    ell(c, 4 + v * 5, 4, 2.2, 1.8, CREAM[1:])
    c.put(3 + v * 5, 4, INK)
    c.outline(INK)
    return c


def crystal(v: int) -> Canvas:
    c = Canvas(12, 14)
    for i, (dx, h) in enumerate(((3, 9), (6, 12), (9, 7))):
        for y in range(13 - h, 13):
            w = max(0, 1 - (13 - y) // max(1, h - 2))
            for x in range(dx - 1 - w, dx + 1 + w):
                c.put(x, y, (VIOLET if v else ICE)[2 if x < dx else 1])
        c.put(dx, 13 - h, (VIOLET if v else ICE)[-1])
        _ = i
    c.outline(INK)
    return c


def plate(lit: bool) -> Canvas:
    c = Canvas(T, 10)
    ell(c, 8, 5, 7, 4, STONE[0:3] if not lit else [STONE[1], STONE[2], ICE[1], ICE[2]])
    rune = [(6, 4), (7, 3), (8, 4), (9, 5), (10, 4)]
    for x, y in rune:
        c.put(x, y, ICE[3] if lit else STONE[0])
    c.outline(INK)
    return c


def lever(right: bool) -> Canvas:
    c = Canvas(12, 14)
    c.rect(2, 9, 8, 4, STONE[1])
    c.hline(2, 9, 9, STONE[3])
    tip = (9, 2) if right else (2, 2)
    c.line(6, 9, tip[0], tip[1], WOOD[3])
    ell(c, tip[0], tip[1], 1.6, 1.6, RED[1:4])
    c.outline(INK)
    return c


def lamp(lit: bool) -> Canvas:
    c = Canvas(12, 18)
    c.drop_shadow(6, 16, 4, 1.3)
    c.rect(5, 6, 2, 9, STONE[2])
    c.rect(2, 3, 8, 3, STONE[3])
    c.rect(3, 14, 6, 2, STONE[1])
    if lit:
        for i, (x, y) in enumerate(((5, 2), (6, 1), (4, 2), (7, 2), (6, 0))):
            c.put(x, y, ICE[3] if i < 4 else (255, 255, 255, 255))
    c.outline(INK)
    return c


def banner() -> Canvas:
    c = Canvas(10, 18)
    c.hline(0, 9, 0, WOOD[2])
    for y in range(1, 16):
        for x in range(1, 9):
            if y > 12 and (x + y) % 3 == 0:
                continue  # tattered hem
            c.put(x, y, VIOLET[1] if x < 5 else VIOLET[0])
    c.put(4, 6, GOLD[3])
    c.put(5, 7, GOLD[3])
    c.put(4, 8, GOLD[3])
    c.outline(INK)
    return c


def portal(frame: int) -> Canvas:
    c = Canvas(24, 28)
    c.drop_shadow(12, 26, 9, 2)
    for y in range(c.h - 4):
        for x in range(c.w):
            dx, dy = (x + 0.5 - 12) / 9, (y + 0.5 - 13) / 12
            r = math.hypot(dx, dy)
            if r > 1:
                continue
            a = math.atan2(dy, dx) + r * 4 - frame * 0.8
            band = (math.sin(a * 3) + 1) / 2
            col = VIOLET[2] if band > 0.6 else VIOLET[1] if band > 0.3 else ICE[2]
            if r < 0.25:
                col = (255, 255, 255, 255)
            c.put(x, y, col)
    c.outline(INK)
    return c


def delve_gate() -> Canvas:
    """The hub's Delve Gate: a stone arch around a swirling doorway, a rune on the keystone."""
    c = Canvas(40, 46)
    c.drop_shadow(20, 43, 17, 2.5)
    for side in (4, 29):  # the two legs
        for y in range(12, 42):
            for x in range(side, side + 7):
                c.put(x, y, STONE[3] if x < side + 3 else STONE[2])
        for y in range(16, 42, 7):
            c.hline(side, side + 6, y, STONE[1])
    for y in range(4, 16):  # the arch
        for x in range(4, 36):
            dx = (x + 0.5 - 20) / 16
            dy = (y + 0.5 - 16) / 12
            inner = (x + 0.5 - 20) ** 2 / 9.5**2 + (y + 0.5 - 16) ** 2 / 8**2 <= 1
            if dx * dx + dy * dy <= 1 and not inner:
                c.put(x, y, STONE[3] if y < 9 else STONE[2])
    c.rect(17, 2, 7, 6, STONE[4])
    for x, y in ((19, 4), (20, 3), (21, 4), (20, 5)):
        c.put(x, y, VIOLET[2])
    # the doorway: a slow violet swirl
    for y in range(9, 42):
        for x in range(11, 29):
            inside = (x + 0.5 - 20) ** 2 / 9**2 + (y + 0.5 - 16) ** 2 / 8**2 <= 1 or y >= 16
            if not inside:
                continue
            a = math.atan2(y - 24, x - 20) + math.hypot(x - 20, y - 24) * 0.35
            band = (math.sin(a * 3) + 1) / 2
            c.put(x, y, VIOLET[1] if band > 0.55 else VIOLET[0] if band > 0.25 else ICE[1])
    c.hline(3, 37, 42, STONE[1])
    c.outline(INK)
    return c


def generate() -> dict[str, Canvas]:
    out: dict[str, Canvas] = {}
    for v in range(4):
        out[f"tile.dfloor.{v}"] = floor(v)
    out["tile.dwall.face"] = wall_face()
    out["tile.dwall.top"] = wall_top()
    out["obj.dgate.0"] = gate(False)
    out["obj.dgate.1"] = gate(True)
    out["obj.dtorch.0"] = torch(0)
    out["obj.dtorch.1"] = torch(1)
    out["obj.dpillar.0"] = pillar()
    for v in range(2):
        out[f"obj.drubble.{v}"] = rubble(v)
        out[f"obj.dbones.{v}"] = bones(v)
        out[f"obj.dcrystal.{v}"] = crystal(v)
    out["obj.dplate.0"] = plate(False)
    out["obj.dplate.1"] = plate(True)
    out["obj.dlever.0"] = lever(False)
    out["obj.dlever.1"] = lever(True)
    out["obj.dlamp.0"] = lamp(False)
    out["obj.dlamp.1"] = lamp(True)
    out["obj.dbanner.0"] = banner()
    for f in range(4):
        out[f"obj.dportal.{f}"] = portal(f)
    out["obj.delve_gate.0"] = delve_gate()
    return out
