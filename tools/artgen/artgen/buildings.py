"""Buildings, one function each, drawn per level (1–5) and per footprint orientation.

Sprite layout: width = footprint_w × 16, height = footprint_h × 16 + `top` (roof/chimney overhang).
The footprint's top-left sits at (0, top) inside the sprite; the client anchors on that point.

Level adornments (BALANCE §2, ART §3): L2 pennant · L3 stone foundation + flower boxes ·
L4 banners + lantern · L5 gold trim + finial sparkle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from artgen.canvas import Canvas, Color, hash2
from artgen.palette import INK, ramp

WOOD = ramp("wood")
STONE = ramp("stone")
PLASTER = ramp("plaster")
THATCH = ramp("thatch")
RED = ramp("roof_red")
BLUE = ramp("roof_blue")
TEAL = ramp("roof_teal")
GOLD = ramp("gold")
FIRE = ramp("fire")
WATER = ramp("water")
DIRT = ramp("dirt")
GRASS = ramp("grass")
LEAF = ramp("leaf")
CROP = ramp("crop")
CLOTH = ramp("cloth_cream")
ACCENT = ramp("accent")
T = 16
HEAD = 12  # headroom above every sprite for pennants and sparkles


@dataclass
class Geom:
    """Where the adornments go, filled in by each building function."""

    roof_top: tuple[int, int] = (0, 0)  # point on the roof peak / top edge for the pennant
    eave: tuple[int, int, int] | None = None  # (x0, x1, y) roof bottom edge for gold trim
    wall: tuple[int, int, int, int] | None = None  # x, y, w, h
    windows: list[tuple[int, int, int]] = field(default_factory=list)  # x, y_bottom, w
    door_cx: int | None = None
    door_bottom: int | None = None


# ── parts ───────────────────────────────────────────────────────────────────


def base_shadow(c: Canvas, x: int, y: int, w: int, h: int) -> None:
    for yy in range(y + 2, y + h + 2):
        for xx in range(x + 2, x + w + 2):
            if not c.filled(xx, yy):
                c.put(xx, yy, (INK[0], INK[1], INK[2], 60))


def wall_plaster(c: Canvas, x: int, y: int, w: int, h: int, timber: bool = True) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            col = PLASTER[3]
            if xx == x:
                col = PLASTER[4]
            elif xx == x + w - 1:
                col = PLASTER[2]
            if yy < y + 2:
                col = PLASTER[1]  # eave shadow
            c.put(xx, yy, col)
    if timber:
        for xx in range(x, x + w, 9):
            c.vline(xx, y + 2, y + h - 1, WOOD[1])
        c.vline(x + w - 1, y + 2, y + h - 1, WOOD[1])
        c.hline(x, x + w - 1, y + 2, WOOD[2])
        c.hline(x, x + w - 1, y + h - 1, WOOD[1])


def wall_planks(c: Canvas, x: int, y: int, w: int, h: int, r: list[Color] = WOOD) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            k = (xx - x) % 4
            col = r[1] if k == 3 else (r[3] if (xx - x) // 4 % 2 else r[4])
            if xx >= x + w - 2:
                col = r[2] if k != 3 else r[1]
            if yy < y + 2:
                col = r[1]
            c.put(xx, yy, col)
        if (yy - y) % 7 == 6:
            for xx in range(x, x + w):
                if hash2(xx // 4, yy, 9) < 0.5:
                    c.put(xx, yy, r[2])


def wall_stone(c: Canvas, x: int, y: int, w: int, h: int) -> None:
    for yy in range(y, y + h):
        row = (yy - y) // 3
        for xx in range(x, x + w):
            off = (row % 2) * 3
            if (yy - y) % 3 == 2 or (xx - x + off) % 6 == 5:
                col = STONE[1]
            else:
                col = STONE[3] if hash2((xx - x + off) // 6, row, 3) < 0.6 else STONE[2]
                if xx == x:
                    col = STONE[4]
            if yy < y + 2:
                col = STONE[1]
            c.put(xx, yy, col)


def roof_hip(c: Canvas, x: int, y: int, w: int, h: int, r: list[Color], style: str = "shingle") -> None:
    """A roof plane facing the viewer, with a slightly rounded top and an overhanging eave."""
    for yy in range(y, y + h):
        inset = 2 if yy == y else 1 if yy == y + 1 else 0
        for xx in range(x + inset, x + w - inset):
            rel = (xx - x) / max(1, w - 1)
            i = 3 if rel < 0.33 else 2 if rel < 0.72 else 1
            row = yy - y
            if style == "shingle":
                if row % 3 == 2:
                    i -= 1
                elif (xx + (row // 3) * 2) % 5 == 0 and row % 3 == 1:
                    i -= 1
            elif style == "slate":
                if row % 3 == 2 or (xx + (row // 3) * 3) % 6 == 0:
                    i -= 1
            elif style == "thatch":
                if hash2(xx, yy // 2, 77) < 0.28:
                    i -= 1
                elif hash2(xx, yy, 78) > 0.9:
                    i += 1
            if yy == y:
                i = 4 if rel < 0.5 else 3
            if yy >= y + h - 1:
                i = 0
            c.put(xx, yy, r[max(0, min(len(r) - 1, i))])
    if style == "thatch":  # bumpy straw fringe
        for xx in range(x, x + w):
            if xx % 3 == 1:
                c.put(xx, y + h, r[1])


def roof_gable(c: Canvas, x: int, y: int, w: int, h: int, r: list[Color], style: str = "shingle") -> int:
    """Front-facing peaked roof (Λ). Left slope lit, right slope shaded. Returns the peak x."""
    peak = x + w // 2
    slope_rows = max(4, int(h * 0.55))
    for yy in range(y, y + h):
        row = yy - y
        half = w // 2 if row >= slope_rows else max(2, int((w // 2) * (row + 2) / (slope_rows + 2)))
        for xx in range(peak - half, peak + half + (w % 2)):
            left = xx < peak
            i = 3 if left else 2
            if style == "thatch":
                if hash2(xx, yy // 2, 81) < 0.3:
                    i -= 1
            elif style == "shingle":
                if row % 3 == 2:
                    i -= 1
                elif (xx + (row // 3) * 2) % 5 == 0 and row % 3 == 1:
                    i -= 1
            if row < slope_rows and (xx == peak - half or xx == peak + half - 1 + (w % 2)):
                i = 4 if left else 1  # lit / shaded rake edges
            if xx == peak and row < slope_rows:
                i = 4  # ridge
            if yy >= y + h - 1:
                i = 0
            c.put(xx, yy, r[max(0, min(len(r) - 1, i))])
    if style == "thatch":
        for xx in range(x, x + w):
            if xx % 3 == 1:
                c.put(xx, y + h, r[1])
    return peak


def door(c: Canvas, cx: int, bottom: int, w: int = 6, h: int = 9, double: bool = False) -> None:
    x0 = cx - w // 2
    for yy in range(bottom - h, bottom):
        for xx in range(x0, x0 + w):
            arch = yy == bottom - h and (xx == x0 or xx == x0 + w - 1)
            if arch:
                continue
            edge = xx in (x0, x0 + w - 1) or yy == bottom - h or (yy == bottom - h + 1 and xx in (x0 + 1, x0 + w - 2))
            col = WOOD[1] if edge else (WOOD[3] if (xx - x0) % 2 else WOOD[2])
            if double and xx == cx:
                col = WOOD[1]
            c.put(xx, yy, col)
    knob_x = cx + 1 if not double else cx - 2
    c.put(knob_x, bottom - h // 2, GOLD[3])
    if double:
        c.put(cx + 1, bottom - h // 2, GOLD[3])


def window(c: Canvas, x: int, y: int, w: int = 5, h: int = 5) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            frame = xx in (x, x + w - 1) or yy in (y, y + h - 1)
            col = WOOD[1] if frame else WATER[3]
            if not frame and (xx == x + w // 2 or yy == y + h // 2):
                col = WOOD[2]
            c.put(xx, yy, col)
    c.put(x + 1, y + 1, WATER[5])
    c.hline(x - 1, x + w, y + h, WOOD[3])


def chimney(c: Canvas, x: int, y: int, h: int, smoke: bool = True) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + 5):
            c.put(xx, yy, STONE[4] if xx == x else STONE[2] if xx == x + 4 else STONE[3])
        if (yy - y) % 3 == 2:
            c.hline(x, x + 4, yy, STONE[1])
    c.hline(x - 1, x + 5, y, STONE[1])


def flower_box(c: Canvas, x: int, y: int, w: int) -> None:
    c.hline(x - 1, x + w, y, WOOD[2])
    c.hline(x - 1, x + w, y + 1, WOOD[1])
    pinks = ramp("flower_pink")
    for i, xx in enumerate(range(x, x + w)):
        c.put(xx, y - 1, LEAF[3] if i % 2 else pinks[1] if i % 4 == 0 else ramp("flower_yellow")[1])


def banner(c: Canvas, x: int, y: int, r: list[Color]) -> None:
    c.hline(x - 1, x + 4, y, WOOD[1])
    for yy in range(y + 1, y + 9):
        for xx in range(x, x + 4):
            if yy >= y + 7 and xx in (x + 1, x + 2) and yy == y + 8:
                continue
            c.put(xx, yy, r[2] if xx < x + 2 else r[1])
    c.put(x + 1, y + 4, GOLD[3])
    c.put(x + 2, y + 4, GOLD[2])


def pennant(c: Canvas, x: int, y: int, r: list[Color]) -> None:
    c.vline(x, y - 9, y, WOOD[1])
    c.put(x, y - 10, GOLD[3])
    for i in range(5):
        for j in range(3 - i // 2):
            c.put(x + 1 + i, y - 9 + j + i // 2 // 2, r[2] if j == 0 else r[1])


def lantern(c: Canvas, x: int, y: int) -> None:
    c.vline(x + 1, y - 2, y, WOOD[1])
    c.rect(x, y + 1, 3, 3, FIRE[3])
    c.put(x + 1, y + 2, FIRE[4])
    c.hline(x, x + 2, y + 4, WOOD[1])


def foundation(c: Canvas, x: int, y: int, w: int) -> None:
    for yy in range(y, y + 3):
        for xx in range(x - 1, x + w + 1):
            col = STONE[3] if (xx + (yy - y) * 2) % 5 else STONE[1]
            if yy == y:
                col = STONE[4] if (xx - x) % 5 else STONE[2]
            if yy == y + 2:
                col = STONE[1]
            c.put(xx, yy, col)


def sparkle(c: Canvas, x: int, y: int) -> None:
    c.put(x, y, GOLD[4])
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        c.put(x + dx, y + dy, GOLD[3])


def adorn(c: Canvas, lv: int, g: Geom, banner_ramp: list[Color] = RED) -> None:
    if lv >= 3 and g.wall is not None:
        x, y, w, h = g.wall
        foundation(c, x, y + h - 3, w)
        for wx, wy, ww in g.windows:
            flower_box(c, wx, wy + 1, ww)
    if lv >= 4 and g.wall is not None:
        x, y, w, h = g.wall
        banner(c, x + 1, y + 3, banner_ramp)
        banner(c, x + w - 5, y + 3, banner_ramp)
        if g.door_cx is not None and g.door_bottom is not None:
            lantern(c, g.door_cx + 5, g.door_bottom - 9)
    if lv >= 5 and g.eave is not None:
        x0, x1, ey = g.eave
        for xx in range(x0, x1 + 1):
            c.put(xx, ey, GOLD[2] if xx % 2 else GOLD[3])
    if lv >= 2:
        px, py = g.roof_top
        pennant(c, px, py, banner_ramp if lv < 5 else GOLD)
    if lv >= 5:
        px, py = g.roof_top
        sparkle(c, px - 4, py - 6)


# ── buildings ───────────────────────────────────────────────────────────────


def town_hall(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 22
    c = Canvas(48, 48 + top)
    base_shadow(c, 2, top + 18, 44, 28)
    g = Geom()
    # main hall
    wall_plaster(c, 3, top + 22, 42, 24)
    roof_hip(c, 1, top + 2, 46, 22, RED)
    g.eave = (1, 46, top + 23)
    # tower
    wall_plaster(c, 17, top - 8, 14, 18, timber=False)
    c.vline(17, top - 6, top + 9, WOOD[1])
    c.vline(30, top - 6, top + 9, WOOD[1])
    for yy in range(top - 4, top + 3):  # bell opening
        for xx in range(21, 27):
            c.put(xx, yy, INK if yy > top - 4 or xx not in (21, 26) else PLASTER[3])
    c.rect(23, top - 2, 2, 3, GOLD[2])
    c.put(23, top - 2, GOLD[3])
    peak = roof_gable(c, 15, top - 22, 18, 15, RED)
    g.roof_top = (peak, top - 21)
    # front
    door(c, 24, top + 46, w=10, h=13, double=True)
    g.door_cx, g.door_bottom = 24, top + 46
    for wx in (7, 34):
        window(c, wx, top + 31, 6, 6)
        g.windows.append((wx, top + 37, 6))
    c.hline(18, 30, top + 47, STONE[3])  # step
    c.hline(19, 29, top + 46, STONE[4])
    g.wall = (3, top + 22, 42, 24)
    adorn(c, lv, g, RED)
    c.outline(INK)
    return c, top


def house(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 12
    c = Canvas(32, 32 + top)
    base_shadow(c, 3, top + 10, 26, 20)
    g = Geom()
    wall_plaster(c, 4, top + 13, 24, 17)
    chimney(c, 21, top - 9, 12)
    peak = roof_gable(c, 2, top - 6, 28, 21, THATCH, "thatch")
    g.roof_top = (peak, top - 6)
    g.eave = (2, 29, top + 14)
    door(c, 20, top + 30, 6, 10)
    g.door_cx, g.door_bottom = 20, top + 30
    window(c, 8, top + 19, 5, 5)
    g.windows.append((8, top + 24, 5))
    g.wall = (4, top + 13, 24, 17)
    adorn(c, lv, g, ramp("roof_teal"))
    c.outline(INK)
    return c, top


def storehouse(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 12
    c = Canvas(32, 32 + top)
    base_shadow(c, 2, top + 8, 28, 22)
    g = Geom()
    wall_planks(c, 3, top + 12, 26, 18)
    roof_hip(c, 1, top - 8, 30, 21, BLUE, "slate")
    g.roof_top = (16, top - 8)
    g.eave = (1, 30, top + 12)
    # barn door with X brace
    x0, y0, w, h = 10, top + 17, 12, 13
    c.rect(x0, y0, w, h, WOOD[2])
    c.rect(x0, y0, w, 1, WOOD[1])
    c.vline(x0, y0, y0 + h - 1, WOOD[1])
    c.vline(x0 + w - 1, y0, y0 + h - 1, WOOD[1])
    c.vline(x0 + w // 2, y0, y0 + h - 1, WOOD[1])
    c.line(x0 + 1, y0 + 1, x0 + w // 2 - 1, y0 + h - 2, WOOD[4])
    c.line(x0 + w // 2 + 1, y0 + h - 2, x0 + w - 2, y0 + 1, WOOD[4])
    g.door_cx, g.door_bottom = 16, top + 30
    # crate + barrel outside
    c.rect(24, top + 24, 7, 6, WOOD[3])
    c.line(24, top + 24, 30, top + 29, WOOD[1])
    c.hline(24, 30, top + 24, WOOD[4])
    c.rect(1, top + 23, 6, 7, WOOD[2])
    c.hline(1, 6, top + 25, STONE[2])
    c.hline(1, 6, top + 28, STONE[2])
    c.vline(2, top + 23, top + 29, WOOD[4])
    g.wall = (3, top + 12, 26, 18)
    adorn(c, lv, g, ramp("roof_blue"))
    c.outline(INK)
    return c, top


def market(lv: int, fw: int = 3, fh: int = 2) -> tuple[Canvas, int]:
    top = HEAD + 12
    W, H = fw * T, fh * T
    c = Canvas(W, H + top)
    base_shadow(c, 2, top + H - 18, W - 4, 16)
    g = Geom()
    # back wall
    wall_planks(c, 4, top + 2, W - 8, H - 10)
    # posts
    for px in (3, W - 5):
        c.rect(px, top - 4, 2, H, WOOD[1])
        c.vline(px, top - 4, top + H - 5, WOOD[3])
    # counter
    cy = top + H - 12
    c.rect(2, cy, W - 4, 9, WOOD[3])
    c.hline(2, W - 3, cy, WOOD[5])
    c.hline(2, W - 3, cy + 8, WOOD[1])
    for xx in range(4, W - 4, 6):
        c.vline(xx, cy + 2, cy + 7, WOOD[2])
    # goods on the counter
    goods = [ramp("flower_red"), ramp("flower_yellow"), LEAF, ramp("flower_purple"), ramp("crop")]
    for i, xx in enumerate(range(5, W - 6, 5)):
        r = goods[i % len(goods)]
        c.rect(xx, cy - 3, 4, 3, r[1])
        c.put(xx, cy - 3, r[2])
        c.put(xx + 1, cy - 4, r[2])
        c.put(xx + 2, cy - 3, r[2])
    # striped awning with scalloped edge
    ay, ah = top - 10, 15
    for yy in range(ay, ay + ah):
        for xx in range(1, W - 1):
            stripe = (xx // 4) % 2
            col = (RED[3] if stripe else CLOTH[3]) if yy < ay + ah - 2 else (RED[1] if stripe else CLOTH[1])
            if yy == ay:
                col = RED[4] if stripe else CLOTH[3]
            c.put(xx, yy, col)
    for xx in range(1, W - 1):
        if xx % 4 in (1, 2):
            c.put(xx, ay + ah, RED[2] if (xx // 4) % 2 else CLOTH[2])
    g.roof_top = (W - 4, ay)
    g.eave = (1, W - 2, ay + ah - 1)
    g.wall = (4, top + 2, W - 8, H - 10)
    adorn(c, min(lv, 2) if lv < 3 else lv, g, RED)
    c.outline(INK)
    return c, top


def log_end(c: Canvas, cx: int, cy: int) -> None:
    c.ellipse(cx, cy, 3.2, 3.2, WOOD[1])
    c.ellipse(cx, cy, 2.4, 2.4, WOOD[5])
    c.ellipse(cx, cy, 1.4, 1.4, WOOD[4])
    c.put(int(cx) - 1 + 1, int(cy) - 1 + 1, WOOD[3])


def lumber_camp(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 8
    c = Canvas(32, 32 + top)
    base_shadow(c, 2, top + 2, 28, 28)
    g = Geom()
    # open shed: back wall + posts + lean-to roof
    wall_planks(c, 4, top + 2, 24, 15)
    for px in (3, 27):
        c.rect(px, top + 4, 2, 14, WOOD[1])
    roof_hip(c, 2, top - 8, 28, 13, TEAL)
    g.roof_top = (25, top - 8)
    g.eave = (2, 29, top + 4)
    # log pile (end-on), stacked 3 + 2 + 1
    for cx, cy in ((7, 27), (13, 27), (19, 27), (10, 22), (16, 22), (13, 17)):
        log_end(c, cx, top + cy)
    # chopping stump + axe (front-right)
    c.rect(23, top + 25, 7, 5, WOOD[2])
    c.vline(23, top + 25, top + 29, WOOD[3])
    c.ellipse(26.5, top + 25, 3.5, 1.5, WOOD[4])
    c.line(27, top + 18, 25, top + 24, WOOD[1])
    c.rect(27, top + 17, 3, 3, STONE[4])
    c.put(29, top + 18, STONE[2])
    g.wall = (4, top + 2, 24, 15)
    if lv >= 3:
        foundation(c, 4, top + 14, 24)
    if lv >= 4:
        lantern(c, 5, top + 5)
        banner(c, 22, top + 5, LEAF)
    if lv >= 5:
        for xx in range(2, 30):
            c.put(xx, top + 4, GOLD[2] if xx % 2 else GOLD[3])
        sparkle(c, 8, top - 10)
    if lv >= 2:
        pennant(c, 25, top - 8, LEAF if lv < 5 else GOLD)
    c.outline(INK)
    return c, top


def quarry(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 6
    c = Canvas(32, 32 + top)
    # dusty ground
    for yy in range(top + 6, top + 31):
        for xx in range(1, 31):
            d = ((xx - 16) / 15) ** 2 + ((yy - top - 18) / 13) ** 2
            if d <= 1:
                c.put(xx, yy, DIRT[3] if hash2(xx, yy, 5) < 0.85 else DIRT[2])
    # rock face at the back
    from artgen.canvas import blob

    rc = Canvas(32, 32 + top)
    blob(rc, [(9, top + 6, 7), (19, top + 4, 8), (26, top + 8, 5)], STONE[1:5], seed=91)
    for x in range(32):
        for y in range(rc.h):
            if rc.filled(x, y) and y < top + 13:
                c.put(x, y, rc.get(x, y))
    # cut blocks in front
    for bx, by in ((6, top + 20), (13, top + 21), (9, top + 15)):
        c.rect(bx, by, 6, 5, STONE[3])
        c.hline(bx, bx + 5, by, STONE[5])
        c.vline(bx + 5, by, by + 4, STONE[2])
        c.hline(bx, bx + 5, by + 4, STONE[1])
    # pickaxe
    c.line(22, top + 14, 26, top + 26, WOOD[2])
    c.line(19, top + 15, 25, top + 13, STONE[4])
    if lv >= 2:
        c.rect(24, top + 20, 6, 6, WOOD[2])  # cart
        c.rect(25, top + 18, 4, 2, STONE[3])
    if lv >= 3:
        for bx in (16, 3):
            c.rect(bx, top + 25, 5, 4, STONE[4])
    if lv >= 4:
        lantern(c, 2, top + 10)
    if lv >= 5:
        sparkle(c, 20, top + 4)
        c.put(13, top + 7, GOLD[3])
    c.outline(INK)
    return c, top


def farm(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 8
    W = H = 48
    c = Canvas(W, H + top)
    # tilled field
    for yy in range(top + 4, top + H - 2):
        for xx in range(2, W - 2):
            row = (yy - top - 4) % 5
            c.put(xx, yy, DIRT[2] if row < 3 else DIRT[1])
    # crops
    for yy in range(top + 5, top + H - 3, 5):
        for xx in range(4, W - 4, 3):
            ripe = lv >= 2 or (xx // 3) % 2
            r = CROP if ripe else LEAF
            c.put(xx, yy, r[2])
            c.put(xx, yy - 1, r[3])
            c.put(xx + 1, yy, r[1])
            if ripe and lv >= 3:
                c.put(xx, yy - 2, r[3])
    # fence
    for xx in range(1, W - 1, 4):
        c.rect(xx, top + H - 5, 2, 5, WOOD[3])
        c.put(xx, top + H - 6, WOOD[4])
    c.hline(1, W - 2, top + H - 3, WOOD[2])
    for yy in range(top + 2, top + H - 2, 4):
        c.rect(0, yy, 2, 3, WOOD[3])
        c.rect(W - 2, yy, 2, 3, WOOD[2])
    # scarecrow
    sx, sy = 38, top + 6
    c.vline(sx, sy - 6, sy + 10, WOOD[1])
    c.hline(sx - 5, sx + 5, sy, WOOD[2])
    c.rect(sx - 2, sy - 1, 5, 6, ramp("roof_blue")[2])
    c.rect(sx - 2, sy - 6, 5, 4, CROP[3])
    c.rect(sx - 3, sy - 8, 7, 2, THATCH[1])
    c.put(sx - 1, sy - 4, INK)
    c.put(sx + 1, sy - 4, INK)
    if lv >= 2:  # hay bale (animals → hide)
        c.rect(5, top + 6, 9, 6, THATCH[3])
        c.hline(5, 13, top + 6, THATCH[4])
        c.hline(5, 13, top + 9, THATCH[1])
    if lv >= 4:
        lantern(c, 2, top - 4)
    g = Geom(roof_top=(sx, sy - 8))
    if lv >= 2:
        pennant(c, sx, sy - 8, RED if lv < 5 else GOLD)
    if lv >= 5:
        sparkle(c, 24, top + 2)
    c.outline(INK)
    return c, top


def mine(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 8
    c = Canvas(32, 32 + top)
    from artgen.canvas import blob

    blob(c, [(9, top + 10, 9), (21, top + 8, 10), (16, top + 14, 10)], STONE[1:5], seed=101)
    for x, y in ((6, top + 6), (20, top + 2), (24, top + 11)):
        c.put(x, y, GRASS[2])
        c.put(x + 1, y, GRASS[3])
    # timber-framed tunnel
    tx, ty, tw, th = 9, top + 13, 13, 14
    for yy in range(ty, ty + th):
        for xx in range(tx, tx + tw):
            c.put(xx, yy, INK)
    c.rect(tx - 1, ty - 2, tw + 2, 3, WOOD[3])
    c.hline(tx - 1, tx + tw, ty - 2, WOOD[4])
    c.rect(tx - 1, ty, 2, th, WOOD[2])
    c.rect(tx + tw - 1, ty, 2, th, WOOD[1])
    # rails + cart
    c.hline(tx + 1, tx + tw - 2, ty + th - 1, STONE[3])
    c.rect(22, top + 24, 8, 5, WOOD[2])
    c.hline(22, 29, top + 24, WOOD[4])
    for ox in (23, 26):
        c.rect(ox, top + 21, 3, 3, ramp("flower_red")[1] if lv >= 3 else STONE[2])
        c.put(ox + 1, top + 21, STONE[4])
    c.put(23, top + 29, INK)
    c.put(28, top + 29, INK)
    g = Geom(roof_top=(21, top - 1))
    if lv >= 2:
        pennant(c, 21, top - 1, RED if lv < 5 else GOLD)
    if lv >= 4:
        lantern(c, tx + tw + 1, ty - 1)
    if lv >= 5:
        c.hline(tx - 1, tx + tw, ty - 2, GOLD[3])
        sparkle(c, 6, top + 2)
    del g
    c.outline(INK)
    return c, top


def fishing_dock(lv: int, fw: int = 2, fh: int = 3) -> tuple[Canvas, int]:
    top = HEAD + 10
    W, H = fw * T, fh * T
    c = Canvas(W, H + top)
    base_shadow(c, 1, top + 2, W - 2, H - 4)
    # deck planks
    vertical = fh >= fw
    for yy in range(top + 2, top + H - 1):
        for xx in range(1, W - 1):
            k = ((xx - 1) % 4) if vertical else ((yy - top - 2) % 4)
            c.put(xx, yy, WOOD[1] if k == 3 else WOOD[4] if k == 0 else WOOD[3])
    # rails along the long sides, posts at the corners
    if vertical:
        for xx in (1, W - 2):
            c.vline(xx, top + 2, top + H - 2, WOOD[5] if xx == 1 else WOOD[2])
        for yy in range(top + 6, top + H - 2, 8):
            c.rect(0, yy, 2, 3, WOOD[1])
            c.rect(W - 2, yy, 2, 3, WOOD[1])
    else:
        for yy in (top + H - 2,):
            c.hline(1, W - 2, yy, WOOD[2])
        for xx in range(4, W - 2, 8):
            c.rect(xx, top + H - 3, 3, 3, WOOD[1])
    for px, py in ((1, top + H - 4), (W - 3, top + H - 4)):
        c.rect(px, py, 2, 4, WOOD[1])
    # little hut at the back
    hw = min(W - 6, 20)
    hx = 3
    wall_planks(c, hx, top + 2, hw, 10)
    roof_hip(c, hx - 2, top - 8, hw + 4, 11, THATCH, "thatch")
    door(c, hx + hw // 2, top + 12, 5, 7)
    # barrel of fish + rod
    bx, by = W - 9, top + H - 13
    c.rect(bx, by, 6, 7, WOOD[2])
    c.hline(bx, bx + 5, by + 2, STONE[2])
    c.hline(bx, bx + 5, by + 5, STONE[2])
    c.rect(bx + 1, by - 1, 4, 1, WATER[3])
    c.put(bx + 2, by - 2, STONE[4])
    c.line(5, top + H - 6, 12, top + 14, WOOD[2])
    c.line(12, top + 14, 14, top + H - 3, STONE[4])
    if lv >= 3:
        c.rect(4, top + H - 10, 4, 4, ramp("cloth_cream")[2])  # rope coil
        c.put(5, top + H - 9, ramp("cloth_cream")[0])
    if lv >= 4:
        lantern(c, W - 5, top + 2)
    g_top = (hx + hw - 2, top - 8)
    if lv >= 2:
        pennant(c, g_top[0], g_top[1], ramp("roof_blue") if lv < 5 else GOLD)
    if lv >= 5:
        sparkle(c, hx + 2, top - 10)
        c.hline(hx - 2, hx + hw + 1, top + 2, GOLD[3])
    c.outline(INK)
    return c, top


def herb_garden(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 6
    c = Canvas(32, 32 + top)
    base_shadow(c, 2, top + 4, 28, 26)
    herbs = [LEAF, ramp("flower_purple"), GRASS, ramp("flower_pink")]
    for bi, (bx, by) in enumerate(((2, top + 4), (2, top + 18))):
        c.rect(bx, by, 28, 11, WOOD[2])
        c.hline(bx, bx + 27, by, WOOD[4])
        c.hline(bx, bx + 27, by + 10, WOOD[1])
        c.rect(bx + 2, by + 2, 24, 7, DIRT[1])
        for i, xx in enumerate(range(bx + 3, bx + 26, 4)):
            r = herbs[(i + bi) % len(herbs)]
            c.put(xx, by + 5, LEAF[2])
            c.put(xx + 1, by + 4, r[1] if len(r) > 3 else r[1])
            c.put(xx - 1, by + 4, LEAF[3])
            c.put(xx, by + 3, r[2] if lv >= 2 or i % 2 else LEAF[3])
            if lv >= 3:
                c.put(xx + 1, by + 6, LEAF[1])
    # watering can
    c.rect(24, top - 2, 5, 4, STONE[3])
    c.line(28, top - 1, 30, top - 3, STONE[2])
    if lv >= 4:
        lantern(c, 1, top - 4)
    if lv >= 2:
        pennant(c, 15, top + 3, ramp("flower_purple") if lv < 5 else GOLD)
    if lv >= 5:
        sparkle(c, 8, top)
    c.outline(INK)
    return c, top


def forge(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 16
    c = Canvas(32, 32 + top)
    base_shadow(c, 2, top + 8, 28, 22)
    g = Geom()
    wall_stone(c, 3, top + 12, 26, 18)
    chimney(c, 21, top - 16, 18)
    c.put(22, top - 17, FIRE[3])
    c.put(23, top - 18, FIRE[4])
    c.put(24, top - 17, FIRE[2])
    roof_hip(c, 1, top - 6, 30, 19, ramp("stone")[0:5], "slate")
    g.roof_top = (8, top - 6)
    g.eave = (1, 30, top + 12)
    # glowing hearth
    hx, hy = 6, top + 18
    for yy in range(hy, hy + 9):
        for xx in range(hx, hx + 10):
            arch = yy == hy and xx in (hx, hx + 9)
            if arch:
                continue
            d = abs(xx - hx - 4.5) + (hy + 8 - yy) * 0.6
            c.put(xx, yy, FIRE[4] if d < 2.5 else FIRE[3] if d < 4.5 else FIRE[2] if d < 6 else FIRE[0])
    c.hline(hx - 1, hx + 10, hy - 1, STONE[1])
    # anvil on a stump
    ax, ay = 20, top + 22
    c.rect(ax + 1, ay + 4, 5, 4, WOOD[2])
    c.rect(ax, ay, 8, 3, STONE[1])
    c.hline(ax, ax + 7, ay, STONE[3])
    c.put(ax - 1, ay, STONE[2])
    c.rect(ax + 2, ay + 3, 3, 1, STONE[1])
    g.wall = (3, top + 12, 26, 18)
    g.door_cx, g.door_bottom = 11, top + 30
    adorn(c, lv, g, ramp("fire"))
    c.outline(INK)
    return c, top


def workshop(lv: int) -> tuple[Canvas, int]:
    top = HEAD + 12
    c = Canvas(32, 32 + top)
    base_shadow(c, 2, top + 8, 28, 22)
    g = Geom()
    wall_planks(c, 3, top + 12, 26, 18)
    roof_hip(c, 1, top - 8, 30, 21, RED)
    g.roof_top = (26, top - 8)
    g.eave = (1, 30, top + 12)
    window(c, 6, top + 17, 8, 5)
    g.windows.append((6, top + 22, 8))
    door(c, 22, top + 30, 6, 10)
    g.door_cx, g.door_bottom = 22, top + 30
    # sawhorse with plank
    c.line(6, top + 30, 8, top + 25, WOOD[1])
    c.line(12, top + 30, 10, top + 25, WOOD[1])
    c.rect(3, top + 24, 14, 2, WOOD[4])
    c.hline(3, 16, top + 25, WOOD[3])
    # tool board
    c.rect(16, top + 15, 3, 1, STONE[4])
    c.vline(17, top + 16, top + 18, WOOD[1])
    g.wall = (3, top + 12, 26, 18)
    adorn(c, lv, g, ramp("roof_teal"))
    c.outline(INK)
    return c, top


def scaffold(fw: int, fh: int) -> tuple[Canvas, int]:
    top = HEAD + 10
    W, H = fw * T, fh * T
    c = Canvas(W, H + top)
    for yy in range(top + 2, top + H - 1):
        for xx in range(1, W - 1):
            c.put(xx, yy, DIRT[2] if hash2(xx, yy, 120) < 0.85 else DIRT[1])
    # low stone course
    for xx in range(3, W - 3):
        c.put(xx, top + H - 7, STONE[4] if xx % 4 else STONE[2])
        c.put(xx, top + H - 6, STONE[3] if (xx + 2) % 4 else STONE[1])
        c.put(xx, top + H - 5, STONE[2])
    # poles and planks
    for px in (2, W - 4):
        c.rect(px, top - 6, 2, H + 2, WOOD[3])
        c.vline(px + 1, top - 6, top + H - 5, WOOD[2])
    c.vline(W // 2, top, top + H - 6, WOOD[2])
    for py in (top - 2, top + H // 2 - 2):
        c.rect(1, py, W - 2, 2, WOOD[4])
        c.hline(1, W - 2, py + 1, WOOD[2])
    c.line(4, top + H - 7, W - 5, top, WOOD[2])
    # tarp
    for yy in range(top + 1, top + H // 2 - 2):
        for xx in range(W // 2 + 1, W - 4):
            c.put(xx, yy, CLOTH[2] if (xx + yy) % 5 else CLOTH[1])
    # plank pile
    c.rect(4, top + H - 4, 10, 2, WOOD[4])
    c.rect(5, top + H - 6, 9, 2, WOOD[3])
    c.outline(INK)
    return c, top


@dataclass
class BuildingArt:
    fn: Callable[..., tuple[Canvas, int]]
    footprint: tuple[int, int]
    rotatable: bool = False  # non-square: also drawn for the swapped footprint


BUILDINGS: dict[str, BuildingArt] = {
    "town_hall": BuildingArt(town_hall, (3, 3)),
    "house": BuildingArt(house, (2, 2)),
    "storehouse": BuildingArt(storehouse, (2, 2)),
    "market": BuildingArt(market, (3, 2), rotatable=True),
    "lumber_camp": BuildingArt(lumber_camp, (2, 2)),
    "quarry": BuildingArt(quarry, (2, 2)),
    "farm": BuildingArt(farm, (3, 3)),
    "mine": BuildingArt(mine, (2, 2)),
    "fishing_dock": BuildingArt(fishing_dock, (2, 3), rotatable=True),
    "herb_garden": BuildingArt(herb_garden, (2, 2)),
    "forge": BuildingArt(forge, (2, 2)),
    "workshop": BuildingArt(workshop, (2, 2)),
}


def generate() -> tuple[dict[str, Canvas], dict[str, dict]]:
    """Returns sprites and per-sprite metadata (footprint + anchor)."""
    sprites: dict[str, Canvas] = {}
    meta: dict[str, dict] = {}
    for key, art in BUILDINGS.items():
        variants = [("a", art.footprint)]
        if art.rotatable:
            variants.append(("b", (art.footprint[1], art.footprint[0])))
        for vname, (fw, fh) in variants:
            for lv in range(1, 6):
                if art.rotatable:
                    canvas, top = art.fn(lv, fw, fh)
                else:
                    canvas, top = art.fn(lv)
                name = f"building.{key}.{vname}.l{lv}"
                sprites[name] = canvas
                meta[name] = {"footprint": [fw, fh], "anchor": [0, top]}
    for fw, fh in ((2, 2), (3, 3), (3, 2), (2, 3)):
        canvas, top = scaffold(fw, fh)
        name = f"building.scaffold.{fw}x{fh}"
        sprites[name] = canvas
        meta[name] = {"footprint": [fw, fh], "anchor": [0, top]}
    return sprites, meta
