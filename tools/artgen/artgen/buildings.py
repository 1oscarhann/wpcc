"""Buildings, drawn per level (1–5) and per footprint orientation, at village scale (3×3 / 4×4 tiles).

Sprite layout: width = footprint_w × 16, height = footprint_h × 16 + `top`. The footprint's top-left sits at
(0, top) inside the sprite; the client anchors on that point. `meta["smoke"]` lists chimney tops (sprite px)
for the client's smoke particles.

Level adornments: L2 pennant · L3 stone plinth + flower boxes · L4 banners + lanterns · L5 gold trim + sparkle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from artgen.canvas import Canvas, Color, blob, hash2
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
BARN = ramp("barn")
CABBAGE = ramp("cabbage")
PUMPKIN = ramp("pumpkin")
PURPLE = ramp("flower_purple")
PINK = ramp("flower_pink")
YELLOW = ramp("flower_yellow")
FRED = ramp("flower_red")
T = 16
HEAD = 14  # transparent headroom above every sprite for pennants and sparkles
SHADOW = (INK[0], INK[1], INK[2], 70)


@dataclass
class Art:
    canvas: Canvas
    top: int
    smoke: list[tuple[int, int]] = field(default_factory=list)


def new(fw: int, fh: int, visual_h: int) -> tuple[Canvas, int]:
    """Canvas for a footprint whose drawing reaches `visual_h` px above the footprint's bottom edge."""
    top = HEAD + max(0, visual_h - fh * T)
    return Canvas(fw * T, fh * T + top), top


# ── generic parts ───────────────────────────────────────────────────────────


def ground_shadow(c: Canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    """Soft shadow cast to the bottom-right (light from the top-left)."""
    for y in range(y0 + 2, y1 + 3):
        for x in range(x0 + 2, x1 + 4):
            if 0 <= x < c.w and 0 <= y < c.h and not c.filled(x, y):
                c.put(x, y, SHADOW)


def wall_plaster(c: Canvas, x: int, y: int, w: int, h: int, braces: bool = True) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            col = PLASTER[3]
            if hash2(xx, yy, 7) < 0.05:
                col = PLASTER[2]
            if xx == x:
                col = PLASTER[4]
            if xx >= x + w - 2:
                col = PLASTER[2]
            if yy < y + 3:
                col = PLASTER[1] if yy < y + 2 else PLASTER[2]  # shade under the eave
            c.put(xx, yy, col)
    # timber frame
    posts = list(range(x, x + w, 12)) + [x + w - 2]
    for px in posts:
        c.rect(px, y + 2, 2, h - 2, WOOD[1])
        c.vline(px, y + 2, y + h - 1, WOOD[2])
    c.rect(x, y + 2, w, 2, WOOD[1])
    c.hline(x, x + w - 1, y + 2, WOOD[3])
    c.rect(x, y + h - 2, w, 2, WOOD[1])
    if braces:
        for a, b in zip(posts, posts[1:], strict=False):
            if b - a >= 10:
                c.line(a + 2, y + h - 3, b - 1, y + 5, WOOD[2])


def wall_planks(c: Canvas, x: int, y: int, w: int, h: int, r: list[Color] = WOOD, trim: Color | None = None) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            k = (xx - x) % 5
            col = r[1] if k == 4 else (r[3] if ((xx - x) // 5) % 2 else r[2] if k == 0 else r[3])
            if k == 1:
                col = r[min(len(r) - 1, 4)] if (xx - x) // 5 % 2 == 0 else r[3]
            if xx >= x + w - 3 and k != 4:
                col = r[2]
            if yy < y + 3:
                col = r[0] if yy < y + 2 else r[1]
            if yy >= y + h - 2:
                col = r[1]
            c.put(xx, yy, col)
            if k == 2 and (yy - y) % 9 == 4:
                c.put(xx, yy, r[0])  # nails
    if trim is not None:
        c.vline(x, y, y + h - 1, trim)
        c.vline(x + w - 1, y, y + h - 1, trim)


def wall_logs(c: Canvas, x: int, y: int, w: int, h: int) -> None:
    """Horizontal logs with rounded shading and log ends at both corners."""
    for yy in range(y, y + h):
        k = (yy - y) % 4
        for xx in range(x, x + w):
            col = [WOOD[4], WOOD[3], WOOD[2], WOOD[1]][k]
            if hash2(xx // 3, yy, 11) < 0.12 and k in (1, 2):
                col = WOOD[2]
            if yy < y + 2:
                col = WOOD[1]
            c.put(xx, yy, col)
    for yy in range(y + 2, y + h - 1, 4):
        for ex in (x - 1, x + w - 2):
            c.rect(ex, yy, 3, 3, WOOD[5])
            c.put(ex + 1, yy + 1, WOOD[3])


def wall_stone(c: Canvas, x: int, y: int, w: int, h: int, seed: int = 0) -> None:
    for yy in range(y, y + h):
        row = (yy - y) // 4
        for xx in range(x, x + w):
            off = (row % 2) * 4 + int(hash2(row, seed, 3) * 3)
            bx = (xx - x + off) // 7
            mortar = (yy - y) % 4 == 3 or (xx - x + off) % 7 == 6
            if mortar:
                col = STONE[1]
            else:
                tone = 3 if hash2(bx, row, 5 + seed) < 0.55 else 2
                if (yy - y) % 4 == 0:
                    tone += 1
                col = STONE[tone]
            if yy < y + 2:
                col = STONE[1]
            c.put(xx, yy, col)
    c.vline(x, y + 2, y + h - 1, STONE[4])


def plinth(c: Canvas, x: int, y: int, w: int, h: int = 4) -> None:
    for yy in range(y, y + h):
        for xx in range(x - 1, x + w + 1):
            top = yy == y
            col = STONE[4] if top else STONE[3] if (xx + (yy - y) * 3) % 6 else STONE[1]
            if yy == y + h - 1:
                col = STONE[1]
            c.put(xx, yy, col)


def roof_plane(c: Canvas, x0: int, y0: int, x1: int, y1: int, r: list[Color], style: str = "tiles",
               curve: int = 2) -> None:
    """Roof surface seen from the front-above, ridge along the top. `curve` rounds the top corners."""
    n = len(r)
    for y in range(y0, y1 + 1):
        row = y - y0
        inset = max(0, curve - row) if style != "thatch" else max(0, curve * 2 - row * 2)
        for x in range(x0 + inset, x1 - inset + 1):
            rel = (x - x0) / max(1, x1 - x0)
            i = 3 if rel < 0.3 else 2 if rel < 0.75 else 1
            if style == "tiles":
                course = row % 4
                if course == 0:
                    i += 1
                elif course == 3:
                    i -= 1
                elif (x + (row // 4) * 3) % 6 == 0:
                    i -= 1
            elif style == "slate":
                if row % 3 == 2 or (x + (row // 3) * 4) % 7 == 0:
                    i -= 1
                elif row % 3 == 0:
                    i += 1
            elif style == "thatch":
                h = hash2(x, row // 3, 77)
                if h < 0.25:
                    i -= 1
                elif h > 0.85:
                    i += 1
                if row % 5 == 4 and hash2(x, row, 78) < 0.5:
                    i -= 1
            elif style == "planks":
                if (x - x0) % 5 == 4:
                    i -= 1
            if row == 0:
                i = n - 1 if rel < 0.6 else n - 2  # ridge catches the light
            if y >= y1 - 1:
                i = 0 if y == y1 else 1  # eave
            c.put(x, y, r[max(0, min(n - 1, i))])
    if style == "thatch":
        for x in range(x0, x1 + 1):  # straw fringe
            if hash2(x, 0, 79) < 0.6:
                c.put(x, y1 + 1, r[1])
            if hash2(x, 1, 79) < 0.25:
                c.put(x, y1 + 2, r[0])


def roof_gable(c: Canvas, cx: int, y0: int, half: int, h: int, r: list[Color], style: str = "tiles",
               trim: Color | None = WOOD[1]) -> None:
    """Front-facing peaked roof (Λ). Left slope lit, right slope shaded, with bargeboards."""
    for y in range(y0, y0 + h):
        row = y - y0
        w = max(1, int(half * (row + 1.5) / h))
        for x in range(cx - w, cx + w + 1):
            left = x < cx
            i = 3 if left else 2
            if style == "tiles" and row % 4 == 3:
                i -= 1
            if style == "tiles" and row % 4 == 0 and (x + row) % 5 == 0:
                i -= 1
            if style == "thatch" and hash2(x, row // 2, 81) < 0.28:
                i -= 1
            if style == "slate" and (row % 3 == 2 or (x + row // 3 * 2) % 5 == 0):
                i -= 1
            if x == cx:
                i = 4
            if y == y0 + h - 1:
                i = 0
            c.put(x, y, r[max(0, min(len(r) - 1, i))])
        if trim is not None:
            c.put(cx - w, y, trim)
            c.put(cx + w, y, trim)
            if row > 1:
                c.put(cx - w + 1, y, WOOD[3])


def door(c: Canvas, cx: int, base: int, w: int = 8, h: int = 12, double: bool = False,
         r: list[Color] = WOOD) -> None:
    x0 = cx - w // 2
    for y in range(base - h, base):
        row = y - (base - h)
        for x in range(x0, x0 + w):
            rx = x - x0
            if row < 2 and (rx < 2 - row or rx > w - 3 + row):  # arch
                continue
            frame = rx in (0, w - 1) or row == 0 or (row == 1 and rx in (1, w - 2))
            col = r[1] if frame else (r[3] if rx % 3 else r[2])
            if double and rx in (w // 2 - 1, w // 2):
                col = r[1]
            if row in (3, h - 4) and not frame:
                col = STONE[2]  # iron hinges
            c.put(x, y, col)
    c.put(cx + (w // 2 - 3 if not double else 1), base - h // 2, GOLD[3])
    if double:
        c.put(cx - 2, base - h // 2, GOLD[3])
    # step
    c.hline(x0 - 1, x0 + w, base, STONE[3])
    c.hline(x0, x0 + w - 1, base + 1, STONE[1])


def window(c: Canvas, x: int, y: int, w: int = 7, h: int = 7, shutters: bool = True, arch: bool = False) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            if arch and yy == y and xx in (x, x + w - 1):
                continue
            frame = xx in (x, x + w - 1) or yy in (y, y + h - 1)
            col = WOOD[1] if frame else WATER[3]
            if not frame and (xx == x + w // 2 or yy == y + h // 2):
                col = WOOD[3]
            if not frame and yy == y + h - 2 and xx > x + w // 2:
                col = WATER[2]
            c.put(xx, yy, col)
    c.put(x + 1, y + 1, WATER[5])
    c.put(x + 2, y + 1, WATER[4])
    c.hline(x - 1, x + w, y + h, WOOD[4])
    if shutters:
        for sx in (x - 3, x + w):
            c.rect(sx, y, 3, h, TEAL[2])
            c.vline(sx + 1, y, y + h - 1, TEAL[3])
            c.hline(sx, sx + 2, y + h // 2, TEAL[1])


def flower_box(c: Canvas, x: int, y: int, w: int) -> None:
    c.hline(x - 1, x + w, y, WOOD[3])
    c.hline(x - 1, x + w, y + 1, WOOD[1])
    for i, xx in enumerate(range(x - 1, x + w + 1)):
        c.put(xx, y - 1, LEAF[3] if i % 2 else (PINK[1] if i % 4 == 0 else YELLOW[1]))
        if i % 3 == 0:
            c.put(xx, y - 2, PINK[2] if i % 2 else YELLOW[2])


def chimney(c: Canvas, x: int, y: int, h: int) -> tuple[int, int]:
    for yy in range(y, y + h):
        for xx in range(x, x + 6):
            col = STONE[4] if xx == x else STONE[2] if xx >= x + 4 else STONE[3]
            if (yy - y) % 3 == 2:
                col = STONE[1]
            c.put(xx, yy, col)
    c.rect(x - 1, y - 2, 8, 2, STONE[1])
    c.hline(x - 1, x + 6, y - 2, STONE[3])
    return (x + 3, y - 3)


def banner(c: Canvas, x: int, y: int, r: list[Color], length: int = 10) -> None:
    c.hline(x - 1, x + 5, y, WOOD[1])
    for yy in range(y + 1, y + length):
        for xx in range(x, x + 5):
            if yy >= y + length - 2 and xx == x + 2 and yy == y + length - 1:
                continue
            if yy == y + length - 1 and xx in (x + 1, x + 3):
                continue
            c.put(xx, yy, r[min(3, len(r) - 1)] if xx < x + 2 else r[min(2, len(r) - 2)])
    c.put(x + 2, y + length // 2, GOLD[3])
    c.put(x + 1, y + length // 2, GOLD[2])


def pennant(c: Canvas, x: int, y: int, r: list[Color]) -> None:
    c.vline(x, y - 11, y, WOOD[1])
    c.put(x, y - 12, GOLD[3])
    for i in range(7):
        for j in range(max(1, 3 - i // 2)):
            c.put(x + 1 + i, y - 11 + j + i // 3, r[min(3, len(r) - 1)] if j == 0 else r[min(2, len(r) - 2)])


def lantern(c: Canvas, x: int, y: int) -> None:
    c.hline(x, x + 3, y, WOOD[1])
    c.vline(x + 1, y, y + 2, WOOD[1])
    c.rect(x, y + 3, 3, 4, FIRE[3])
    c.put(x + 1, y + 4, FIRE[4])
    c.hline(x, x + 2, y + 7, WOOD[1])


def sparkle(c: Canvas, x: int, y: int) -> None:
    c.put(x, y, GOLD[4])
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        c.put(x + dx, y + dy, GOLD[3])


def barrel(c: Canvas, x: int, y: int) -> None:
    c.rect(x, y, 7, 8, WOOD[3])
    c.vline(x, y, y + 7, WOOD[4])
    c.vline(x + 5, y, y + 7, WOOD[2])
    c.vline(x + 6, y, y + 7, WOOD[1])
    for yy in (y + 1, y + 6):
        c.hline(x, x + 6, yy, STONE[2])
    c.ellipse(x + 3.5, y, 3.5, 1.2, WOOD[2])


def crate(c: Canvas, x: int, y: int, s: int = 8) -> None:
    c.rect(x, y, s, s, WOOD[4])
    c.hline(x, x + s - 1, y, WOOD[5])
    c.vline(x + s - 1, y, y + s - 1, WOOD[2])
    c.hline(x, x + s - 1, y + s - 1, WOOD[2])
    c.line(x + 1, y + s - 2, x + s - 2, y + 1, WOOD[2])


def sack(c: Canvas, x: int, y: int) -> None:
    c.ellipse(x + 3.5, y + 4, 3.5, 4, CLOTH[2])
    c.rect(x + 2, y - 1, 3, 2, CLOTH[1])
    c.put(x + 2, y + 2, CLOTH[3])


def hay(c: Canvas, x: int, y: int, w: int = 12) -> None:
    c.rect(x, y, w, 7, THATCH[3])
    for xx in range(x, x + w):
        c.put(xx, y + (1 if hash2(xx, 0, 3) > 0.5 else 0), THATCH[4])
        if hash2(xx, 1, 3) < 0.3:
            c.put(xx, y + 3, THATCH[2])
    c.hline(x, x + w - 1, y + 6, THATCH[1])
    c.vline(x + w // 3, y, y + 6, THATCH[1])
    c.vline(x + 2 * w // 3, y, y + 6, THATCH[1])


def log_end(c: Canvas, cx: float, cy: float, r: float = 3.2) -> None:
    c.ellipse(cx, cy, r, r, WOOD[1])
    c.ellipse(cx, cy, r - 0.8, r - 0.8, WOOD[5])
    c.ellipse(cx, cy, r - 1.8, r - 1.8, WOOD[4])
    c.put(int(cx), int(cy), WOOD[3])


def sign(c: Canvas, x: int, y: int, icon: Callable[[Canvas, int, int], None]) -> None:
    c.rect(x, y, 12, 9, WOOD[4])
    c.hline(x, x + 11, y, WOOD[5])
    c.hline(x, x + 11, y + 8, WOOD[2])
    icon(c, x + 3, y + 2)


def adorn(c: Canvas, lv: int, *, pennant_at: tuple[int, int], plinth_at: tuple[int, int, int] | None = None,
          boxes: list[tuple[int, int, int]] = (), banners: list[tuple[int, int]] = (),
          lanterns: list[tuple[int, int]] = (), trim: tuple[int, int, int] | None = None,
          color: list[Color] = RED) -> None:
    if lv >= 3 and plinth_at:
        x, y, w = plinth_at
        plinth(c, x, y, w)
    if lv >= 3:
        for x, y, w in boxes:
            flower_box(c, x, y, w)
    if lv >= 4:
        for x, y in banners:
            banner(c, x, y, color)
        for x, y in lanterns:
            lantern(c, x, y)
    if lv >= 5 and trim:
        x0, x1, y = trim
        for xx in range(x0, x1 + 1):
            c.put(xx, y, GOLD[2] if xx % 2 else GOLD[3])
    if lv >= 2:
        pennant(c, pennant_at[0], pennant_at[1], color if lv < 5 else GOLD)
    if lv >= 5:
        sparkle(c, pennant_at[0] - 6, pennant_at[1] - 8)
        sparkle(c, pennant_at[0] + 10, pennant_at[1] - 2)


# ── the buildings ───────────────────────────────────────────────────────────


def town_hall(lv: int) -> Art:
    c, top = new(4, 4, 108)
    B = c.h - 3  # ground line
    ground_shadow(c, 3, B - 40, 60, B)
    # ground floor: stone · upper floor: timber frame
    wall_stone(c, 4, B - 16, 56, 16, seed=1)
    wall_plaster(c, 4, B - 32, 56, 17)
    roof_plane(c, 1, B - 62, 62, B - 30, RED, "tiles", curve=3)
    # dormers
    for dx in (10, 46):
        roof_gable(c, dx, B - 52, 6, 9, RED, "tiles")
        window(c, dx - 3, B - 46, 7, 5, shutters=False)
    # clock tower
    wall_plaster(c, 24, B - 82, 16, 26, braces=False)
    c.ellipse(32, B - 72, 5, 5, CLOTH[3])
    c.ellipse(32, B - 72, 5, 5, CLOTH[3])
    for a in range(0, 360, 30):
        import math

        c.put(int(32 + 4 * math.cos(math.radians(a))), int(B - 72 + 4 * math.sin(math.radians(a))), WOOD[1])
    c.line(32, B - 72, 32, B - 75, INK)
    c.line(32, B - 72, 34, B - 71, INK)
    window(c, 29, B - 64, 7, 6, shutters=False, arch=True)
    roof_gable(c, 32, B - 102, 11, 22, RED, "tiles")
    # door + steps + windows
    door(c, 32, B, 14, 15, double=True)
    c.hline(23, 41, B + 1, STONE[4])
    for wx in (9, 18, 41, 50):
        window(c, wx, B - 29, 6, 7, shutters=False)
    for wx in (10, 47):
        window(c, wx, B - 13, 7, 8, shutters=True, arch=True)
    adorn(c, lv, pennant_at=(32, B - 103), plinth_at=(4, B - 3, 56), boxes=[(9, B - 21, 6), (18, B - 21, 6),
          (41, B - 21, 6), (50, B - 21, 6)], banners=[(19, B - 15), (40, B - 15)], lanterns=[(22, B - 13), (42, B - 13)],
          trim=(1, 62, B - 31), color=RED)
    c.outline(INK)
    return Art(c, top)


def house(lv: int) -> Art:
    c, top = new(3, 3, 64)
    B = c.h - 3
    ground_shadow(c, 4, B - 24, 44, B)
    wall_plaster(c, 5, B - 20, 38, 20)
    smoke = chimney(c, 32, B - 52, 16)
    roof_plane(c, 2, B - 46, 45, B - 18, THATCH, "thatch", curve=4)
    # dormer window in the thatch
    roof_gable(c, 16, B - 41, 6, 9, THATCH, "thatch", trim=None)
    window(c, 13, B - 36, 6, 5, shutters=False)
    door(c, 31, B, 8, 13)
    window(c, 11, B - 15, 7, 7)
    # porch pot + little fence
    c.ellipse(40, B - 2, 2.5, 2, ramp("roof_red")[2])
    c.put(40, B - 4, LEAF[3])
    c.put(39, B - 5, LEAF[4])
    c.put(41, B - 5, FRED[2])
    adorn(c, lv, pennant_at=(10, B - 46), plinth_at=(5, B - 3, 38), boxes=[(11, B - 7, 7)],
          banners=[(20, B - 15)], lanterns=[(25, B - 15)], trim=(2, 45, B - 19), color=TEAL)
    c.outline(INK)
    return Art(c, top, [smoke])


def storehouse(lv: int) -> Art:
    c, top = new(3, 3, 64)
    B = c.h - 3
    ground_shadow(c, 3, B - 26, 44, B)
    wall_planks(c, 4, B - 24, 40, 24, BARN, trim=CLOTH[3])
    # gambrel roof: steep lower band + shallow upper band
    roof_plane(c, 7, B - 54, 40, B - 41, STONE[0:5], "slate", curve=3)
    roof_plane(c, 1, B - 42, 46, B - 22, STONE[0:5], "slate", curve=0)
    c.hline(1, 46, B - 42, STONE[4])
    # hayloft opening with hay spilling out
    c.rect(18, B - 36, 12, 10, CLOTH[3])
    c.rect(19, B - 35, 10, 8, INK)
    c.rect(19, B - 31, 10, 4, THATCH[3])
    for xx in range(19, 29):
        c.put(xx, B - 32, THATCH[4] if xx % 2 else THATCH[2])
    c.put(29, B - 30, THATCH[3])
    # barn door with X brace
    x0, y0, w, h = 15, B - 17, 18, 17
    c.rect(x0, y0, w, h, BARN[2])
    c.rect(x0, y0, w, 1, CLOTH[3])
    for xx in (x0, x0 + w - 1, x0 + w // 2):
        c.vline(xx, y0, y0 + h - 1, CLOTH[3])
    c.line(x0 + 1, y0 + 1, x0 + w // 2 - 1, y0 + h - 1, CLOTH[2])
    c.line(x0 + w // 2 + 1, y0 + h - 1, x0 + w - 2, y0 + 1, CLOTH[2])
    c.line(x0 + w // 2 - 1, y0 + 1, x0 + 1, y0 + h - 1, CLOTH[2])
    c.line(x0 + w - 2, y0 + h - 1, x0 + w // 2 + 1, y0 + 1, CLOTH[2])
    sack(c, 5, B - 8)
    sack(c, 9, B - 7)
    crate(c, 37, B - 9)
    crate(c, 38, B - 16, 6)
    adorn(c, lv, pennant_at=(38, B - 54), plinth_at=(4, B - 3, 40), banners=[(6, B - 21)],
          lanterns=[(35, B - 21)], trim=(1, 46, B - 22), color=BLUE)
    c.outline(INK)
    return Art(c, top)


def market(lv: int, fw: int = 4, fh: int = 3) -> Art:
    W = fw * T
    c, top = new(fw, fh, 50)
    B = c.h - 3
    ground_shadow(c, 2, B - 20, W - 3, B)
    stalls = 2 if W >= 60 else 1
    sw = (W - 4) // stalls
    awnings = [(RED, CLOTH), (BLUE, CLOTH)]
    for s in range(stalls):
        x0 = 2 + s * sw
        aw, cl = awnings[s % 2]
        # back boards + posts
        wall_planks(c, x0 + 2, B - 30, sw - 4, 18)
        for px in (x0 + 1, x0 + sw - 3):
            c.rect(px, B - 38, 2, 38, WOOD[1])
            c.vline(px, B - 38, B - 1, WOOD[3])
        # counter
        c.rect(x0, B - 12, sw, 11, WOOD[3])
        c.hline(x0, x0 + sw - 1, B - 12, WOOD[5])
        c.hline(x0, x0 + sw - 1, B - 2, WOOD[1])
        for xx in range(x0 + 2, x0 + sw - 2, 5):
            c.vline(xx, B - 10, B - 3, WOOD[2])
        # produce
        goods = [(FRED, 3), (PUMPKIN, 4), (CABBAGE, 4), (YELLOW, 3), (PURPLE, 3)]
        gx = x0 + 2
        i = s * 2
        while gx < x0 + sw - 5:
            gr, gs = goods[i % len(goods)]
            for k in range(3):
                c.ellipse(gx + 2 + (k % 2) * 2, B - 14 - (k // 2) * 2, gs / 2, gs / 2.4, gr[2])
            c.put(gx + 1, B - 16, gr[3] if len(gr) > 3 else gr[2])
            gx += 7
            i += 1
        # striped awning with scalloped edge
        ay = B - 44
        for y in range(ay, ay + 13):
            for x in range(x0, x0 + sw):
                stripe = ((x - x0) // 5) % 2
                base = aw if stripe else cl
                col = base[3] if y < ay + 10 else base[1]
                if y == ay:
                    col = base[min(len(base) - 1, 4)] if stripe else base[3]
                c.put(x, y, col)
        for x in range(x0, x0 + sw):
            if (x - x0) % 5 in (1, 2, 3):
                c.put(x, ay + 13, (aw if ((x - x0) // 5) % 2 else cl)[2])
    crate(c, 3, B - 8, 7)
    barrel(c, W - 11, B - 9)
    adorn(c, lv, pennant_at=(W - 6, B - 44), boxes=[], banners=[(W // 2 - 3, B - 30)],
          lanterns=[(4, B - 34), (W - 8, B - 34)], trim=(2, W - 3, B - 44), color=RED)
    c.outline(INK)
    return Art(c, top)


def lumber_camp(lv: int) -> Art:
    c, top = new(3, 3, 60)
    B = c.h - 3
    ground_shadow(c, 3, B - 22, 44, B)
    # sawdust yard
    for y in range(B - 8, B + 1):
        for x in range(2, 46):
            if hash2(x, y, 31) < 0.15:
                c.put(x, y, DIRT[4])
    wall_logs(c, 5, B - 22, 26, 22)
    roof_plane(c, 2, B - 44, 34, B - 20, TEAL, "tiles", curve=2)
    door(c, 18, B, 8, 12)
    window(c, 7, B - 15, 6, 6)
    # open lean-to with the log pile
    c.rect(33, B - 30, 2, 30, WOOD[1])
    c.rect(44, B - 26, 2, 26, WOOD[1])
    roof_plane(c, 31, B - 34, 47, B - 26, TEAL, "planks", curve=0)
    for cx, cy in ((36, B - 3), (41, B - 3), (38.5, B - 8), (43.5, B - 8), (41, B - 13)):
        log_end(c, cx, cy, 3)
    # chopping block + axe
    c.rect(24, B - 6, 6, 5, WOOD[2])
    c.ellipse(27, B - 6, 3, 1.2, WOOD[5])
    c.line(28, B - 13, 26, B - 7, WOOD[1])
    c.rect(28, B - 14, 3, 3, STONE[4])
    adorn(c, lv, pennant_at=(28, B - 44), plinth_at=(5, B - 3, 26), boxes=[(7, B - 8, 6)],
          banners=[], lanterns=[(13, B - 18)], trim=(2, 34, B - 21), color=LEAF)
    c.outline(INK)
    return Art(c, top)


def quarry(lv: int) -> Art:
    c, top = new(3, 3, 56)
    B = c.h - 3
    # gravel floor
    for y in range(B - 24, B + 1):
        for x in range(1, 47):
            d = ((x - 24) / 23) ** 2 + ((y - (B - 12)) / 13) ** 2
            if d <= 1:
                c.put(x, y, STONE[3] if hash2(x, y, 41) < 0.2 else DIRT[3] if hash2(x, y, 42) < 0.5 else DIRT[4])
    # terraced cliff
    for i, (y0, x0, x1) in enumerate(((B - 52, 6, 42), (B - 42, 3, 45), (B - 32, 2, 46))):
        for y in range(y0, y0 + 11):
            for x in range(x0, x1):
                face = y > y0 + 3
                col = (STONE[2] if (x + y) % 7 else STONE[1]) if face else STONE[4] if y == y0 else STONE[3]
                if face and hash2(x, y // 3, 43 + i) < 0.18:
                    col = STONE[1]
                if x < x0 + 2 and face:
                    col = STONE[3]
                c.put(x, y, col)
        c.hline(x0, x1 - 1, y0, GRASS[3] if i == 0 else STONE[5])
    # cut blocks
    for bx, by in ((6, B - 9), (14, B - 8), (9, B - 15)):
        c.rect(bx, by, 7, 6, STONE[3])
        c.hline(bx, bx + 6, by, STONE[5])
        c.vline(bx + 6, by, by + 5, STONE[2])
        c.hline(bx, bx + 6, by + 5, STONE[1])
    # wooden hoist
    c.line(30, B - 2, 36, B - 30, WOOD[2])
    c.line(42, B - 2, 36, B - 30, WOOD[1])
    c.hline(32, 46, B - 30, WOOD[3])
    c.vline(45, B - 29, B - 14, CLOTH[1])
    c.rect(43, B - 14, 5, 4, STONE[3])
    # cart
    c.rect(22, B - 8, 9, 5, WOOD[2])
    c.rect(23, B - 11, 7, 3, STONE[3])
    c.put(23, B - 2, INK)
    c.put(29, B - 2, INK)
    adorn(c, lv, pennant_at=(36, B - 31), banners=[], lanterns=[(3, B - 24)] if lv >= 4 else [],
          trim=(6, 41, B - 52), color=BLUE)
    if lv >= 3:
        crate(c, 33, B - 8, 6)
    c.outline(INK)
    return Art(c, top)


def farm(lv: int) -> Art:
    c, top = new(4, 4, 70)
    W, H = 64, 64
    B = c.h - 1
    y0 = B - H + 4
    # tilled field with furrows
    for y in range(y0 + 10, B - 2):
        for x in range(3, W - 3):
            furrow = (y - y0) % 6 >= 4
            c.put(x, y, DIRT[1] if furrow else DIRT[2] if hash2(x, y, 5) < 0.2 else DIRT[3])
    # crop rows: wheat in front rows, cabbages + pumpkins further back
    for row, y in enumerate(range(y0 + 13, B - 4, 6)):
        kind = row % 3
        for x in range(6, W - 6, 4 if kind else 3):
            if kind == 0:  # wheat
                tall = 3 + (lv >= 3)
                for d in range(tall):
                    c.put(x, y - d, CROP[1 + min(2, d)])
                c.put(x - 1, y - tall + 1, CROP[3])
                c.put(x + 1, y - tall + 1, CROP[2])
            elif kind == 1:  # cabbages
                c.ellipse(x + 1, y - 1, 2, 1.6, CABBAGE[2])
                c.put(x + 1, y - 2, CABBAGE[3])
            else:  # pumpkins on vines
                c.put(x, y - 1, LEAF[3])
                if (x // 4) % 2:
                    c.ellipse(x + 1.5, y - 1, 1.8, 1.4, PUMPKIN[2])
                    c.put(x + 1, y - 2, PUMPKIN[3])
    # fence around three sides, open at the front
    for x in range(1, W - 1, 5):
        c.rect(x, y0 + 4, 2, 6, WOOD[3])
        c.put(x, y0 + 3, WOOD[4])
    c.hline(1, W - 2, y0 + 6, WOOD[2])
    for y in range(y0 + 8, B - 2, 5):
        c.rect(0, y, 2, 4, WOOD[3])
        c.rect(W - 2, y, 2, 4, WOOD[2])
    # little shed at the back-left
    wall_planks(c, 4, y0 - 6, 14, 10)
    roof_plane(c, 2, y0 - 16, 19, y0 - 5, RED, "tiles", curve=1)
    # scarecrow
    sx, sy = 46, y0 + 16
    c.vline(sx, sy - 8, sy + 10, WOOD[1])
    c.hline(sx - 6, sx + 6, sy - 2, WOOD[2])
    c.rect(sx - 2, sy - 3, 5, 7, BLUE[2])
    c.rect(sx - 2, sy - 9, 5, 5, CROP[3])
    c.rect(sx - 4, sy - 11, 9, 2, THATCH[1])
    c.rect(sx - 2, sy - 13, 5, 2, THATCH[2])
    c.put(sx - 1, sy - 7, INK)
    c.put(sx + 1, sy - 7, INK)
    if lv >= 2:
        hay(c, 30, y0 - 4, 12)
    if lv >= 4:
        lantern(c, 21, y0 - 12)
    if lv >= 2:
        pennant(c, sx, sy - 13, RED if lv < 5 else GOLD)
    if lv >= 5:
        sparkle(c, 30, y0 + 2)
        sparkle(c, 54, y0 + 10)
    c.outline(INK)
    return Art(c, top)


def mine(lv: int) -> Art:
    c, top = new(3, 3, 54)
    B = c.h - 3
    blob(c, [(12, B - 26, 13), (32, B - 30, 15), (24, B - 18, 14), (40, B - 16, 8)], STONE[1:5], seed=101)
    # grassy top
    for x in range(c.w):
        for y in range(c.h):
            if c.filled(x, y) and not c.filled(x, y - 2) and y < B - 26:
                c.put(x, y, GRASS[3])
                c.put(x, y + 1, GRASS[2])
    # timber-framed tunnel
    tx, ty, tw, th = 14, B - 22, 18, 20
    for y in range(ty, ty + th):
        for x in range(tx, tx + tw):
            c.put(x, y, INK if y > ty + 2 else WOOD[0])
    c.rect(tx - 2, ty - 3, tw + 4, 4, WOOD[3])
    c.hline(tx - 2, tx + tw + 1, ty - 3, WOOD[5])
    c.rect(tx - 2, ty, 3, th, WOOD[2])
    c.vline(tx - 2, ty, ty + th - 1, WOOD[4])
    c.rect(tx + tw - 1, ty, 3, th, WOOD[1])
    # rails
    for x in range(tx, tx + tw + 12):
        c.put(x, B - 1, STONE[4])
        c.put(x, B - 4, STONE[3])
        if x % 3 == 0:
            c.vline(x, B - 4, B - 1, WOOD[1])
    # cart with ore
    c.rect(33, B - 11, 11, 6, WOOD[2])
    c.hline(33, 43, B - 11, WOOD[4])
    ore_col = FIRE[2] if lv >= 3 else STONE[2]
    for ox in (34, 37, 40):
        c.ellipse(ox + 1.5, B - 12, 1.8, 1.5, STONE[3])
        c.put(ox + 1, B - 13, ore_col)
    c.put(34, B - 5, INK)
    c.put(42, B - 5, INK)
    if lv >= 4:
        lantern(c, tx + tw + 2, ty - 2)
    if lv >= 2:
        pennant(c, 32, B - 44, RED if lv < 5 else GOLD)
    if lv >= 5:
        c.hline(tx - 2, tx + tw + 1, ty - 3, GOLD[3])
        sparkle(c, 10, B - 40)
    c.outline(INK)
    return Art(c, top)


def fishing_dock(lv: int, fw: int = 3, fh: int = 4) -> Art:
    W, H = fw * T, fh * T
    c, top = new(fw, fh, H + 12)
    B = c.h - 1
    y0 = B - H + 1
    vertical = fh >= fw
    # pier deck
    for y in range(y0 + 4, B - 1):
        for x in range(2, W - 2):
            k = ((y - y0) % 5) if vertical else ((x - 2) % 5)
            c.put(x, y, WOOD[1] if k == 4 else WOOD[5] if k == 0 else WOOD[4] if hash2(x, y, 9) < 0.3 else WOOD[3])
    for px, py in ((1, B - 6), (W - 4, B - 6), (1, y0 + 4), (W - 4, y0 + 4), (1, (y0 + B) // 2),
                   (W - 4, (y0 + B) // 2)):
        c.rect(px, py, 3, 6, WOOD[1])
        c.hline(px, px + 2, py, WOOD[3])
    # fishing hut
    hw = min(W - 8, 26)
    wall_planks(c, 4, y0 + 2, hw, 14)
    roof_plane(c, 2, y0 - 10, hw + 6, y0 + 4, THATCH, "thatch", curve=3)
    door(c, 4 + hw // 2, y0 + 16, 6, 9)
    # nets drying on a rack
    nx = 4 + hw + 2
    if nx + 8 < W:
        c.vline(nx, y0 + 2, y0 + 16, WOOD[1])
        c.vline(nx + 8, y0 + 2, y0 + 16, WOOD[1])
        for y in range(y0 + 4, y0 + 14):
            for x in range(nx + 1, nx + 8):
                if (x + y) % 3 == 0 or (x - y) % 3 == 0:
                    c.put(x, y, CLOTH[1])
    barrel(c, W - 12, B - 14)
    c.rect(W - 11, B - 15, 5, 1, WATER[3])
    c.line(6, B - 6, 14, y0 + 20, WOOD[2])
    c.line(14, y0 + 20, 17, B - 3, STONE[4])
    if lv >= 3:
        c.ellipse(8, B - 14, 3, 2.2, CLOTH[2])
        c.ellipse(8, B - 14, 1.5, 1, CLOTH[0])
    if lv >= 4:
        lantern(c, W - 6, y0 + 4)
    if lv >= 2:
        pennant(c, hw, y0 - 10, BLUE if lv < 5 else GOLD)
    if lv >= 5:
        sparkle(c, 8, y0 - 12)
    c.outline(INK)
    return Art(c, top)


def herb_garden(lv: int) -> Art:
    c, top = new(3, 3, 52)
    B = c.h - 3
    ground_shadow(c, 2, B - 40, 45, B)
    herbs = [(PURPLE, "lavender"), (LEAF, "mint"), (FRED, "poppy"), (YELLOW, "marigold")]
    beds = [(3, B - 38, 20), (25, B - 38, 20), (3, B - 18, 20), (25, B - 18, 20)]
    for i, (bx, by, bw) in enumerate(beds):
        c.rect(bx, by, bw, 14, WOOD[3])
        c.hline(bx, bx + bw - 1, by, WOOD[5])
        c.hline(bx, bx + bw - 1, by + 13, WOOD[1])
        c.vline(bx + bw - 1, by, by + 13, WOOD[2])
        c.rect(bx + 2, by + 2, bw - 4, 10, DIRT[1])
        r, kind = herbs[i % len(herbs)]
        for x in range(bx + 3, bx + bw - 3, 3):
            for y in range(by + 4, by + 12, 4):
                c.put(x, y + 1, LEAF[2])
                c.put(x - 1, y, LEAF[3])
                c.put(x + 1, y, LEAF[1])
                if kind != "mint" and (lv >= 2 or (x + y) % 2):
                    c.put(x, y - 1, r[2] if len(r) > 2 else r[1])
                    c.put(x, y - 2, r[1])
                else:
                    c.put(x, y - 1, LEAF[4])
    # stepping stones
    for sy in range(B - 22, B, 5):
        c.ellipse(24, sy + 2, 2, 1.4, STONE[3])
    # cold frame (little glass box)
    c.rect(36, B - 48, 10, 8, WOOD[2])
    c.rect(37, B - 47, 8, 6, WATER[4])
    c.put(38, B - 46, WATER[5])
    # watering can
    c.rect(5, B - 46, 6, 5, STONE[3])
    c.line(10, B - 45, 13, B - 48, STONE[2])
    c.hline(6, 9, B - 47, STONE[4])
    if lv >= 4:
        lantern(c, 22, B - 48)
    if lv >= 2:
        pennant(c, 24, B - 40, PURPLE if lv < 5 else GOLD)
    if lv >= 5:
        sparkle(c, 14, B - 44)
    c.outline(INK)
    return Art(c, top)


def forge(lv: int) -> Art:
    c, top = new(3, 3, 72)
    B = c.h - 3
    ground_shadow(c, 3, B - 26, 44, B)
    wall_stone(c, 4, B - 24, 40, 24, seed=3)
    smoke = chimney(c, 33, B - 62, 34)
    c.rect(34, B - 65, 4, 2, FIRE[3])
    c.put(35, B - 66, FIRE[4])
    roof_plane(c, 2, B - 46, 45, B - 22, STONE[0:5], "slate", curve=2)
    # open forge arch with the glowing hearth
    hx, hy, hw, hh = 8, B - 18, 18, 18
    for y in range(hy, hy + hh):
        for x in range(hx, hx + hw):
            rx = x - hx
            if y - hy < 3 and (rx < 3 - (y - hy) or rx > hw - 4 + (y - hy)):
                continue
            d = abs(rx - hw / 2) + (hy + hh - y) * 0.7
            col = FIRE[4] if d < 3 else FIRE[3] if d < 6 else FIRE[2] if d < 9 else FIRE[0] if d < 12 else INK
            c.put(x, y, col)
    c.hline(hx - 1, hx + hw, hy - 1, STONE[1])
    # anvil on a stump + quench barrel + sword rack
    ax, ay = 30, B - 10
    c.rect(ax + 2, ay + 4, 6, 6, WOOD[2])
    c.rect(ax, ay, 10, 3, STONE[1])
    c.hline(ax, ax + 9, ay, STONE[3])
    c.put(ax - 1, ay, STONE[2])
    c.rect(ax + 3, ay + 3, 4, 1, STONE[1])
    barrel(c, 39, B - 11)
    c.rect(40, B - 12, 5, 1, WATER[3])
    adorn(c, lv, pennant_at=(10, B - 46), boxes=[], banners=[(36, B - 22)],
          lanterns=[(4, B - 22)], trim=(2, 45, B - 23), color=FIRE)
    if lv >= 3:
        plinth(c, 4, B - 3, 40)
    c.outline(INK)
    return Art(c, top, [smoke])


def workshop(lv: int) -> Art:
    c, top = new(3, 3, 62)
    B = c.h - 3
    ground_shadow(c, 3, B - 24, 44, B)
    wall_planks(c, 4, B - 22, 40, 22)
    roof_plane(c, 2, B - 46, 45, B - 20, RED, "tiles", curve=3)
    roof_gable(c, 24, B - 46, 9, 14, RED, "tiles")
    window(c, 21, B - 40, 7, 5, shutters=False)
    # wide open doors showing a dim interior
    c.rect(18, B - 16, 14, 16, WOOD[0])
    c.rect(18, B - 16, 14, 2, INK)
    c.rect(14, B - 16, 4, 16, WOOD[3])
    c.rect(32, B - 16, 4, 16, WOOD[2])
    c.hline(19, 30, B - 6, WOOD[4])  # workbench inside
    window(c, 6, B - 16, 7, 7)
    # sawhorse + planks + tool board
    c.line(38, B - 1, 40, B - 7, WOOD[1])
    c.line(46, B - 1, 44, B - 7, WOOD[1])
    c.rect(36, B - 8, 11, 2, WOOD[5])
    for py in (B - 4, B - 2):
        c.rect(2, py, 10, 2, WOOD[4])
        c.hline(2, 11, py + 1, WOOD[2])
    adorn(c, lv, pennant_at=(39, B - 46), boxes=[(6, B - 8, 7)], banners=[],
          lanterns=[(37, B - 20)], trim=(2, 45, B - 21), color=TEAL)
    if lv >= 3:
        plinth(c, 4, B - 3, 40)
    c.outline(INK)
    return Art(c, top)


def scaffold(fw: int, fh: int) -> Art:
    """A building going up: dug foundation, stone course, timber skeleton, scaffolding, ladder, materials."""
    W, H = fw * T, fh * T
    c, top = new(fw, fh, 44)
    B = c.h - 3
    x0, x1 = 4, W - 5
    ground_shadow(c, x0, B - 30, x1, B)
    for y in range(B - 6, B + 2):  # dug earth
        for x in range(x0 - 2, x1 + 3):
            c.put(x, y, DIRT[2] if hash2(x, y, 120) < 0.75 else DIRT[1])
    plinth(c, x0, B - 5, x1 - x0, 4)
    # timber skeleton: posts, top beam, rafters forming a roof outline
    posts = list(range(x0, x1, 10)) + [x1 - 1]
    for px in posts:
        c.rect(px, B - 26, 2, 21, WOOD[3])
        c.vline(px + 1, B - 26, B - 6, WOOD[2])
    c.rect(x0, B - 27, x1 - x0 + 1, 2, WOOD[4])
    c.hline(x0, x1, B - 26, WOOD[2])
    mid = (x0 + x1) // 2
    c.line(x0, B - 27, mid, B - 40, WOOD[3])
    c.line(x1, B - 27, mid, B - 40, WOOD[2])
    c.line(x0 + 1, B - 27, mid, B - 39, WOOD[4])
    c.line(mid, B - 40, mid, B - 27, WOOD[2])
    # scaffolding platform + ladder on the right
    c.rect(x0 - 2, B - 16, x1 - x0 + 5, 2, WOOD[5])
    c.hline(x0 - 2, x1 + 2, B - 15, WOOD[2])
    for y in range(B - 15, B - 5, 3):
        c.hline(x1 + 1, x1 + 3, y, WOOD[4])
    c.vline(x1 + 1, B - 17, B - 5, WOOD[1])
    c.vline(x1 + 4, B - 17, B - 5, WOOD[1])
    # half a wall of planks and a tarp
    for y in range(B - 15, B - 5):
        for x in range(x0 + 2, x0 + (x1 - x0) // 2):
            c.put(x, y, WOOD[3] if (x - x0) % 4 else WOOD[1])
    for y in range(B - 25, B - 17):
        for x in range(mid + 2, x1 - 2):
            c.put(x, y, CLOTH[2] if (x + y) % 7 else CLOTH[1])
    # materials
    for py in (B - 1, B + 1):
        c.rect(x0 - 2, py, 12, 2, WOOD[4])
        c.hline(x0 - 2, x0 + 9, py + 1, WOOD[2])
    for bx in (x1 - 10, x1 - 5):
        c.rect(bx, B - 1, 4, 3, STONE[3])
        c.hline(bx, bx + 3, B - 1, STONE[5])
    c.outline(INK)
    return Art(c, top)


@dataclass
class BuildingArt:
    fn: Callable[..., Art]
    footprint: tuple[int, int]
    rotatable: bool = False


BUILDINGS: dict[str, BuildingArt] = {
    "town_hall": BuildingArt(town_hall, (4, 4)),
    "house": BuildingArt(house, (3, 3)),
    "storehouse": BuildingArt(storehouse, (3, 3)),
    "market": BuildingArt(market, (4, 3), rotatable=True),
    "lumber_camp": BuildingArt(lumber_camp, (3, 3)),
    "quarry": BuildingArt(quarry, (3, 3)),
    "farm": BuildingArt(farm, (4, 4)),
    "mine": BuildingArt(mine, (3, 3)),
    "fishing_dock": BuildingArt(fishing_dock, (3, 4), rotatable=True),
    "herb_garden": BuildingArt(herb_garden, (3, 3)),
    "forge": BuildingArt(forge, (3, 3)),
    "workshop": BuildingArt(workshop, (3, 3)),
}


def generate() -> tuple[dict[str, Canvas], dict[str, dict]]:
    """Returns sprites and per-sprite metadata (footprint, anchor, smoke points)."""
    sprites: dict[str, Canvas] = {}
    meta: dict[str, dict] = {}
    for key, art in BUILDINGS.items():
        variants = [("a", art.footprint)]
        if art.rotatable:
            variants.append(("b", (art.footprint[1], art.footprint[0])))
        for vname, (fw, fh) in variants:
            for lv in range(1, 6):
                a = art.fn(lv, fw, fh) if art.rotatable else art.fn(lv)
                name = f"building.{key}.{vname}.l{lv}"
                sprites[name] = a.canvas
                meta[name] = {"footprint": [fw, fh], "anchor": [0, a.top], "smoke": [list(p) for p in a.smoke]}
    fps = {tuple(a.footprint) for a in BUILDINGS.values()} | {
        (a.footprint[1], a.footprint[0]) for a in BUILDINGS.values() if a.rotatable
    }
    for fw, fh in sorted(fps):
        a = scaffold(fw, fh)
        name = f"building.scaffold.{fw}x{fh}"
        sprites[name] = a.canvas
        meta[name] = {"footprint": [fw, fh], "anchor": [0, a.top], "smoke": []}
    return sprites, meta
