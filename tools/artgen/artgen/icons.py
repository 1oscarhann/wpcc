"""16×16 icons for resources, items and UI actions. Same light/outline rules as world sprites."""

from __future__ import annotations

from collections.abc import Callable

from artgen.canvas import Canvas, blob
from artgen.palette import INK, ramp

WOOD = ramp("wood")
STONE = ramp("stone")
GOLD = ramp("gold")
LEAF = ramp("leaf")
WATER = ramp("water")
RED = ramp("roof_red")
FIRE = ramp("fire")
CROP = ramp("crop")
DIRT = ramp("dirt")
PAPER = ramp("ui_paper")
CLOTH = ramp("cloth_cream")
PURPLE = ramp("flower_purple")
TEAL = ramp("roof_teal")


def log(c: Canvas, x: int, y: int, w: int) -> None:
    c.rect(x, y, w, 4, WOOD[3])
    c.hline(x, x + w - 1, y, WOOD[4])
    c.hline(x, x + w - 1, y + 3, WOOD[1])
    c.rect(x + w - 2, y, 2, 4, WOOD[5])
    c.put(x + w - 1, y + 1, WOOD[3])


def i_wood(c: Canvas) -> None:
    log(c, 2, 9, 12)
    log(c, 3, 5, 10)
    c.put(5, 7, WOOD[2])
    c.put(9, 11, WOOD[2])


def i_stone(c: Canvas) -> None:
    blob(c, [(6, 10, 4.5), (11, 9, 4), (8.5, 6.5, 3.5)], STONE[1:5], seed=7)


def i_ore(c: Canvas) -> None:
    blob(c, [(7.5, 9, 5.5), (10, 7, 4)], STONE[0:4], seed=8)
    for x, y in ((6, 8), (9, 6), (10, 10), (5, 11)):
        c.put(x, y, FIRE[2])
        c.put(x + 1, y, FIRE[3])


def i_food(c: Canvas) -> None:
    for i, x in enumerate((5, 8, 11)):
        c.vline(x, 6, 14, CROP[1])
        for y in range(2 + i % 2, 7):
            c.put(x - 1, y, CROP[2])
            c.put(x, y, CROP[3])
    c.hline(4, 12, 10, WOOD[2])
    c.hline(4, 12, 11, WOOD[1])


def i_herbs(c: Canvas) -> None:
    c.line(8, 14, 8, 6, LEAF[1])
    for (x, y), r in (((5, 8), LEAF), ((11, 7), LEAF), ((6, 4), LEAF), ((10, 3), LEAF)):
        c.ellipse(x, y, 2.4, 1.6, r[3])
        c.put(int(x) - 1, int(y) - 1, r[4])
    c.put(8, 5, PURPLE[1])
    c.put(8, 4, PURPLE[2])


def i_fish(c: Canvas) -> None:
    c.ellipse(7, 8, 5, 3, WATER[3])
    for x in range(3, 11):
        c.put(x, 10, WATER[2])
    c.hline(3, 9, 6, WATER[4])
    for d in range(4):
        c.vline(12 + d, 8 - d, 8 + d, WATER[2])
    c.put(4, 7, INK)


def i_hide(c: Canvas) -> None:
    pts = [(4, 3), (11, 3), (13, 6), (12, 12), (8, 14), (3, 12), (2, 6)]
    c.shape(lambda x, y: _in_poly(x + 0.5, y + 0.5, pts), lambda x, y: DIRT[3] if x + y < 14 else DIRT[2])
    for x, y in ((6, 7), (9, 9), (7, 11)):
        c.put(x, y, DIRT[1])


def _in_poly(x: float, y: float, pts: list[tuple[int, int]]) -> bool:
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def gem(c: Canvas, r: list) -> None:  # noqa: ANN001
    pts = [(8, 1), (14, 6), (8, 15), (2, 6)]
    c.shape(lambda x, y: _in_poly(x + 0.5, y + 0.5, pts),
            lambda x, y: r[3] if x < 8 and y < 8 else r[2] if x < 8 or y < 7 else r[1])
    c.hline(4, 12, 6, r[3])
    c.put(5, 4, r[-1])
    c.put(6, 3, r[-1])


def i_crystal(c: Canvas) -> None:
    gem(c, WATER[1:])


def i_planks(c: Canvas) -> None:
    for i, y in enumerate((4, 8, 12)):
        c.rect(2 + i % 2, y, 12, 3, WOOD[4])
        c.hline(2 + i % 2, 13 + i % 2, y + 2, WOOD[2])
        c.put(4 + i * 3, y + 1, WOOD[3])


def i_bricks(c: Canvas) -> None:
    for row, y in enumerate((4, 8, 12)):
        off = 3 if row % 2 else 0
        for bx in range(1 - off, 14, 6):
            c.rect(max(1, bx), y, min(5, 15 - bx) - max(0, 1 - bx), 3, RED[3])
            c.hline(max(1, bx), max(1, bx) + 3, y, RED[4])


def i_ingots(c: Canvas) -> None:
    for x, y in ((2, 9), (8, 9), (5, 5)):
        c.rect(x, y, 6, 4, STONE[3])
        c.hline(x + 1, x + 5, y, STONE[5])
        c.hline(x, x + 5, y + 3, STONE[1])


def i_leather(c: Canvas) -> None:
    c.rect(2, 5, 12, 7, DIRT[2])
    c.hline(2, 13, 5, DIRT[3])
    c.ellipse(12.5, 8.5, 2, 3.5, DIRT[1])
    c.vline(6, 5, 11, WOOD[1])


def i_bread(c: Canvas) -> None:
    c.ellipse(8, 9, 6.5, 4, CROP[2])
    c.ellipse(7, 8, 5, 2.6, CROP[3])
    for x in (5, 8, 11):
        c.put(x, 7, CROP[1])
        c.put(x - 1, 8, CROP[1])


def flask(c: Canvas, r: list) -> None:  # noqa: ANN001
    c.rect(6, 2, 4, 2, WOOD[2])
    c.rect(7, 4, 2, 2, STONE[4])
    c.ellipse(8, 10, 5, 4.5, STONE[4])
    c.ellipse(8, 11, 4, 3, r[2])
    c.hline(5, 11, 9, r[3])
    c.put(6, 8, STONE[5])


def i_potion_base(c: Canvas) -> None:
    flask(c, LEAF)


def i_potion_red(c: Canvas) -> None:
    flask(c, RED)


def i_coins(c: Canvas) -> None:
    for i, y in enumerate((11, 8, 5)):
        c.ellipse(8 - (i == 1), y, 5, 2.4, GOLD[2])
        c.hline(4 - (i == 1), 11 - (i == 1), y, GOLD[3])
        c.hline(4, 11, y + 2, GOLD[1])
    c.put(7, 4, GOLD[4])


def i_sword(c: Canvas) -> None:
    c.line(4, 12, 12, 4, STONE[4])
    c.line(5, 12, 12, 5, STONE[2])
    c.put(12, 3, STONE[5])
    c.line(3, 9, 7, 13, GOLD[2])
    c.line(2, 14, 4, 12, WOOD[2])


def i_ironbark(c: Canvas) -> None:
    c.rect(3, 4, 10, 9, WOOD[1])
    for x in range(3, 13, 2):
        c.vline(x, 4, 12, WOOD[2])
    c.vline(4, 4, 12, STONE[3])
    c.vline(10, 5, 11, STONE[4])


def i_starstone(c: Canvas) -> None:
    pts = [(8, 1), (10, 6), (15, 6), (11, 9), (13, 15), (8, 11), (3, 15), (5, 9), (1, 6), (6, 6)]
    c.shape(lambda x, y: _in_poly(x + 0.5, y + 0.5, pts), lambda x, y: PURPLE[2] if x + y < 15 else PURPLE[1])
    c.put(7, 5, GOLD[4])


# ── UI icons ───────────────────────────────────────────────────────────────


def u_build(c: Canvas) -> None:  # hammer
    c.line(4, 13, 10, 7, WOOD[3])
    c.line(5, 13, 11, 7, WOOD[2])
    c.rect(8, 2, 6, 4, STONE[3])
    c.hline(8, 13, 2, STONE[5])
    c.rect(11, 5, 2, 3, STONE[2])


def u_upgrade(c: Canvas) -> None:
    pts = [(8, 1), (14, 8), (10, 8), (10, 14), (6, 14), (6, 8), (2, 8)]
    c.shape(lambda x, y: _in_poly(x + 0.5, y + 0.5, pts), lambda x, y: LEAF[4] if x < 8 else LEAF[3])


def u_move(c: Canvas) -> None:
    for (x0, y0, x1, y1) in ((8, 2, 8, 14), (2, 8, 14, 8)):
        c.line(x0, y0, x1, y1, PAPER[4])
    for x, y, dx, dy in ((8, 1, 0, 1), (8, 15, 0, -1), (1, 8, 1, 0), (15, 8, -1, 0)):
        for k in range(3):
            c.put(x + dx * k + dy * k, y + dy * k + dx * k, PAPER[4])
            c.put(x + dx * k - dy * k, y + dy * k - dx * k, PAPER[4])


def u_rotate(c: Canvas) -> None:
    for a in range(0, 300, 12):
        import math

        x = 8 + 5 * math.cos(math.radians(a - 60))
        y = 8 + 5 * math.sin(math.radians(a - 60))
        c.put(int(x), int(y), PAPER[4])
        c.put(int(x) + 1, int(y), PAPER[3])
    c.rect(10, 1, 4, 2, PAPER[4])
    c.rect(12, 1, 2, 4, PAPER[4])


def u_undo(c: Canvas) -> None:
    import math

    for a in range(-90, 120, 10):
        x = 9 + 5 * math.cos(math.radians(a))
        y = 9 + 4 * math.sin(math.radians(a))
        c.put(int(x), int(y), PAPER[4])
        c.put(int(x), int(y) + 1, PAPER[3])
    c.hline(3, 9, 5, PAPER[4])
    for k in range(3):
        c.put(3 + k, 5 - k, PAPER[4])
        c.put(3 + k, 5 + k, PAPER[4])


def u_close(c: Canvas) -> None:
    for d in range(-1, 1):
        c.line(3, 3 + d, 12, 12 + d, RED[4])
        c.line(12, 3 + d, 3, 12 + d, RED[3])


def u_demolish(c: Canvas) -> None:  # pickaxe
    c.line(4, 13, 11, 6, WOOD[3])
    import math

    for a in range(200, 341, 8):
        x = 9 + 6 * math.cos(math.radians(a))
        y = 9 + 6 * math.sin(math.radians(a))
        c.put(int(x), int(y), STONE[4])
        c.put(int(x), int(y) + 1, STONE[2])


def u_settings(c: Canvas) -> None:
    import math

    c.ellipse(8, 8, 5, 5, STONE[3])
    for a in range(0, 360, 45):
        x = 8 + 6 * math.cos(math.radians(a))
        y = 8 + 6 * math.sin(math.radians(a))
        c.rect(int(x) - 1, int(y) - 1, 2, 2, STONE[3])
    c.ellipse(8, 8, 2, 2, STONE[1])
    c.put(6, 5, STONE[5])


def u_sound(c: Canvas) -> None:
    c.rect(2, 6, 3, 4, PAPER[4])
    for i in range(4):
        c.vline(5 + i, 6 - i, 9 + i, PAPER[4])
    for y in (5, 8, 11):
        c.put(11, y, PAPER[3])
    c.vline(12, 6, 10, PAPER[3])
    c.vline(14, 4, 12, PAPER[2])


def u_mute(c: Canvas) -> None:
    c.rect(2, 6, 3, 4, PAPER[4])
    for i in range(4):
        c.vline(5 + i, 6 - i, 9 + i, PAPER[4])
    c.line(10, 5, 14, 11, RED[3])
    c.line(14, 5, 10, 11, RED[3])


def u_timer(c: Canvas) -> None:
    c.hline(3, 12, 1, WOOD[3])
    c.hline(3, 12, 14, WOOD[3])
    for y in range(2, 14):
        w = abs(7.5 - y) * 0.7 + 0.5
        c.put(int(7.5 - w), y, STONE[4])
        c.put(int(7.5 + w), y, STONE[4])
    for y in range(3, 7):
        c.hline(int(8 - (7 - y) * 0.6), int(8 + (7 - y) * 0.6) - 1, y, CROP[3])
    for y in range(10, 13):
        c.hline(int(8 - (y - 8) * 0.7), int(8 + (y - 8) * 0.7) - 1, y, CROP[3])


def u_lock(c: Canvas) -> None:
    c.rect(3, 7, 10, 7, GOLD[2])
    c.hline(3, 12, 7, GOLD[3])
    for y in range(2, 8):
        c.put(5, y, STONE[3])
        c.put(10, y, STONE[2])
    c.hline(5, 10, 2, STONE[4])
    c.rect(7, 9, 2, 3, GOLD[0])


def u_check(c: Canvas) -> None:
    c.line(3, 8, 6, 11, LEAF[4])
    c.line(3, 9, 6, 12, LEAF[3])
    c.line(6, 11, 13, 4, LEAF[4])
    c.line(6, 12, 13, 5, LEAF[3])


def u_info(c: Canvas) -> None:
    c.ellipse(8, 8, 6.5, 6.5, WATER[2])
    c.rect(7, 7, 2, 5, PAPER[4])
    c.rect(7, 4, 2, 2, PAPER[4])


def u_star(c: Canvas) -> None:
    pts = [(8, 1), (10, 6), (15, 6), (11, 9), (13, 15), (8, 11), (3, 15), (5, 9), (1, 6), (6, 6)]
    c.shape(lambda x, y: _in_poly(x + 0.5, y + 0.5, pts), lambda x, y: GOLD[3] if x + y < 15 else GOLD[2])


def u_home(c: Canvas) -> None:
    pts = [(8, 1), (15, 8), (1, 8)]
    c.shape(lambda x, y: _in_poly(x + 0.5, y + 0.5, pts), lambda x, y: RED[3] if x < 8 else RED[2])
    c.rect(3, 8, 10, 6, ramp("plaster")[3])
    c.rect(7, 10, 3, 4, WOOD[2])


def u_avatar(c: Canvas) -> None:  # sword + shield = adventure mode
    c.ellipse(9, 9, 5, 5.5, ramp("roof_blue")[3])
    c.ellipse(9, 9, 3, 3.5, ramp("roof_blue")[2])
    c.line(2, 13, 10, 5, STONE[4])
    c.line(2, 10, 5, 13, GOLD[2])


def u_queue(c: Canvas) -> None:
    for y in (3, 7, 11):
        c.rect(2, y, 2, 2, GOLD[3])
        c.rect(5, y, 9, 2, PAPER[4])


def u_plus(c: Canvas) -> None:
    c.rect(7, 2, 3, 12, LEAF[4])
    c.rect(2, 7, 12, 3, LEAF[4])


def u_map(c: Canvas) -> None:
    c.rect(2, 3, 12, 10, PAPER[3])
    c.vline(6, 3, 12, PAPER[1])
    c.vline(10, 3, 12, PAPER[1])
    c.line(3, 10, 12, 5, RED[3])
    c.put(12, 5, RED[4])


ICONS: dict[str, Callable[[Canvas], None]] = {
    "wood": i_wood, "stone": i_stone, "ore": i_ore, "food": i_food, "herbs": i_herbs, "fish": i_fish,
    "hide": i_hide, "crystal": i_crystal, "planks": i_planks, "bricks": i_bricks, "ingots": i_ingots,
    "leather": i_leather, "bread": i_bread, "potion_base": i_potion_base, "coins": i_coins, "sword": i_sword,
    "potion_red": i_potion_red, "ironbark": i_ironbark, "starstone": i_starstone,
    "build": u_build, "upgrade": u_upgrade, "move": u_move, "rotate": u_rotate, "undo": u_undo,
    "close": u_close, "demolish": u_demolish, "settings": u_settings, "sound": u_sound, "mute": u_mute,
    "timer": u_timer, "lock": u_lock, "check": u_check, "info": u_info, "star": u_star, "home": u_home,
    "avatar": u_avatar, "queue": u_queue, "plus": u_plus, "map": u_map,
}


def generate() -> dict[str, Canvas]:
    out = {}
    for name, fn in ICONS.items():
        c = Canvas(16, 16)
        fn(c)
        c.outline(INK)
        out[f"icon.{name}"] = c
    return out
