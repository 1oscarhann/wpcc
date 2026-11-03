"""UI textures for the DOM (CSS border-image 9-slices) plus FX frames and the title scene."""

from __future__ import annotations

from artgen.canvas import Canvas, Color, hash2
from artgen.palette import INK, ramp

PAPER = ramp("ui_paper")
UWOOD = ramp("ui_wood")
GOLD = ramp("gold")
LEAF = ramp("leaf")
RED = ramp("roof_red")
STONE = ramp("stone")
WATER = ramp("water")


def framed(w: int, h: int, frame: list[Color], fill_fn, border: int = 4, rivets: bool = True) -> Canvas:  # noqa: ANN001
    c = Canvas(w, h)
    for y in range(h):
        for x in range(w):
            edge = min(x, y, w - 1 - x, h - 1 - y)
            if edge == 0:
                col = INK
            elif edge < border:
                # lit from the top-left: top/left bevel light, bottom/right dark
                if x - 0 < border and y < h - border or y < border and x < w - border:
                    col = frame[3] if edge == 1 else frame[2]
                else:
                    col = frame[1] if edge == 1 else frame[2]
                if edge == border - 1:
                    col = frame[0]
            else:
                col = fill_fn(x, y)
            c.put(x, y, col)
    if rivets:
        for x, y in ((border // 2 + 1, border // 2 + 1), (w - border // 2 - 2, border // 2 + 1),
                     (border // 2 + 1, h - border // 2 - 2), (w - border // 2 - 2, h - border // 2 - 2)):
            c.put(x, y, GOLD[3])
    return c


def paper_fill(x: int, y: int) -> Color:
    # flat: anything in a 9-slice edge or centre gets stretched, so no speckles
    return PAPER[3]


def button(fill: list[Color], state: str) -> Canvas:
    w, h = 24, 16
    c = Canvas(w, h)
    pressed = state == "pressed"
    hover = state == "hover"
    disabled = state == "disabled"
    if disabled:
        fill = [STONE[1], STONE[2], STONE[2], STONE[3], STONE[3]]
    top_i = 4 if hover else 3
    for y in range(h):
        for x in range(w):
            edge = min(x, y, w - 1 - x, h - 1 - y)
            corner = (x in (0, w - 1)) and (y in (0, h - 1))
            if corner:
                continue
            if edge == 0:
                col = INK
            elif not pressed and y >= h - 3:
                col = fill[0]  # 3D lip
            elif pressed and y == 1:
                col = fill[0]  # inner shadow
            elif y <= 2 + (1 if pressed else 0):
                col = fill[top_i]
            else:
                col = fill[2] if not hover else fill[3]
            c.put(x, y, col)
    return c


def slot() -> Canvas:
    w = 20
    c = Canvas(w, w)
    for y in range(w):
        for x in range(w):
            edge = min(x, y, w - 1 - x, w - 1 - y)
            if edge == 0:
                col = UWOOD[1]
            elif edge == 1 and (x == 1 or y == 1):
                col = PAPER[0]  # inner shadow top-left
            elif edge == 1:
                col = PAPER[3]
            else:
                col = PAPER[2]
            c.put(x, y, col)
    return c


def tooltip() -> Canvas:
    return framed(16, 16, [INK, PAPER[1], PAPER[2], PAPER[3]], lambda x, y: (INK[0], INK[1], INK[2], 235),
                  border=2, rivets=False)


def ribbon() -> Canvas:
    w, h = 32, 16
    c = Canvas(w, h)
    for y in range(h):
        for x in range(w):
            notch_l = x < 4 and abs(y - 7.5) < (4 - x) * 1.1
            notch_r = x > w - 5 and abs(y - 7.5) < (x - (w - 5)) * 1.1
            if notch_l or notch_r:
                continue
            edge = y in (0, h - 1)
            col = INK if edge else RED[3] if y < 5 else RED[2] if y < 12 else RED[1]
            if y == 2:
                col = RED[4]
            c.put(x, y, col)
    c.outline(INK)
    return c


def bar() -> Canvas:
    return framed(12, 10, [INK, UWOOD[1], UWOOD[2], UWOOD[3]], lambda x, y: INK, border=2, rivets=False)


def tab(active: bool) -> Canvas:
    w, h = 20, 14
    c = Canvas(w, h)
    for y in range(h):
        for x in range(w):
            edge = min(x, y, w - 1 - x)
            if (x in (0, w - 1)) and y == 0:
                continue
            col = INK if edge == 0 else (PAPER[3] if active else PAPER[1])
            if edge == 1 and y > 0 and active:
                col = PAPER[4]
            c.put(x, y, col)
    return c


def dust_frames() -> list[Canvas]:
    frames = []
    for f in range(5):
        c = Canvas(16, 16)
        r = 2 + f * 1.4
        for i in range(6):
            import math

            a = i / 6 * math.tau + f * 0.3
            cx, cy = 8 + math.cos(a) * r, 10 + math.sin(a) * r * 0.5
            rr = max(0.8, 2.6 - f * 0.45)
            c.ellipse(cx, cy, rr, rr, ramp("cloth_cream")[2] if i % 2 else ramp("cloth_cream")[1])
        frames.append(c)
    return frames


def sparkle_frames() -> list[Canvas]:
    out = []
    for f, size in enumerate((1, 2, 3, 2)):
        c = Canvas(9, 9)
        for d in range(size + 1):
            col = GOLD[4] if d < size else GOLD[2]
            for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d)):
                c.put(4 + dx, 4 + dy, col)
        del f
        out.append(c)
    return out


def title_scene(world: dict[str, Canvas]) -> Canvas:
    """320×180 pixel-art backdrop for the login screen, built from the real world sprites."""
    w, h = 320, 180
    c = Canvas(w, h)
    for y in range(h):
        for x in range(w):
            # banded sky, lighter towards the horizon (no noise)
            col = WATER[4] if y < 74 else WATER[5]
            c.put(x, y, col)
    for cx, cy, s in ((60, 30, 1.0), (210, 22, 1.3), (285, 55, 0.8), (130, 60, 0.7)):
        for dx, dy, r in ((0, 0, 9), (10, 2, 7), (-10, 3, 6), (5, -5, 7)):
            c.ellipse(cx + dx * s, cy + dy * s, r * s, r * s * 0.7, (255, 255, 255, 255))
        c.hline(int(cx - 14 * s), int(cx + 14 * s), int(cy + 5 * s), WATER[5])
    hills = ramp("leaf")
    for x in range(w):
        import math

        far = int(98 + 10 * math.sin(x / 37) + 5 * math.sin(x / 13))
        near = int(118 + 8 * math.sin(x / 51 + 2) + 3 * math.sin(x / 9))
        for y in range(far, h):
            c.put(x, y, hills[2] if y < near else c.get(x, y))
        for y in range(near, h):
            c.put(x, y, hills[3] if y < near + 2 else ramp("grass")[2])
    for y in range(128, h, 16):
        for x in range(0, w, 16):
            c.blit(world[f"tile.grass.{(x // 16 + y // 16) % 4}"], x, y)
    for x in range(0, w, 16):
        c.blit(world["tile.path.68"], x, 156)  # E|W: a straight east-west road
    placements = [
        ("obj.pine.0", 14, 128), ("obj.oak.1", 40, 136), ("building.house.a.l3", 68, 150),
        ("building.town_hall.a.l4", 126, 152), ("building.lumber_camp.a.l2", 190, 150),
        ("building.forge.a.l3", 232, 152), ("obj.oak.0", 280, 140), ("obj.pine.1", 304, 132),
        ("building.market.a.l2", 70, 182), ("obj.bush.1", 176, 176), ("obj.well.0", 285, 182),
    ]
    for name, x, by in placements:
        s = world[name]
        c.blit(s, x, by - s.h)
    return c


def generate() -> dict[str, Canvas]:
    out = {
        "ui.panel": framed(24, 24, UWOOD[1:], paper_fill, border=5),
        "ui.panel_dark": framed(24, 24, UWOOD[1:], lambda x, y: UWOOD[2] if (y // 4) % 2 else UWOOD[1], border=4,
                                rivets=True),
        "ui.slot": slot(),
        "ui.tooltip": tooltip(),
        "ui.ribbon": ribbon(),
        "ui.bar": bar(),
        "ui.tab_active": tab(True),
        "ui.tab": tab(False),
    }
    fills = {
        "primary": [LEAF[0], LEAF[1], LEAF[2], LEAF[3], LEAF[4]],
        "secondary": [UWOOD[0], UWOOD[1], UWOOD[2], UWOOD[3], UWOOD[4]],
        "danger": [RED[0], RED[1], RED[2], RED[3], RED[4]],
        "gold": [GOLD[0], GOLD[1], GOLD[2], GOLD[3], GOLD[4]],
    }
    for name, fill in fills.items():
        for state in ("normal", "hover", "pressed", "disabled"):
            out[f"ui.button_{name}_{state}"] = button(fill, state)
    return out


def fx() -> dict[str, Canvas]:
    out = {}
    for i, f in enumerate(dust_frames()):
        out[f"fx.dust.{i}"] = f
    for i, f in enumerate(sparkle_frames()):
        out[f"fx.sparkle.{i}"] = f
    return out
