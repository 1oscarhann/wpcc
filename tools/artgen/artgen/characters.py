"""Layered 16×24 characters, recoloured on the client.

Each layer (body, eyes, hair, outfit) is a strip of 18 frames:
  down: idle×2, walk×4 · up: idle×2, walk×4 · side (facing left): idle×2, walk×4
Recolourable pixels use the 4 grey SHADE_KEYS (dark → light); fixed colours (shoes, belts, shirts)
use real palette colours and pass through untouched. The client composes the layers and adds the
1 px silhouette outline (see frontend/src/game/avatarComposer.ts).
"""

from __future__ import annotations

from dataclasses import dataclass

from artgen.canvas import Canvas, Color
from artgen.palette import SHADE_KEYS, ramp

FW, FH = 16, 24
DIRS = ("down", "up", "side")
ANIMS = (("idle", 2), ("walk", 4))
FRAMES = [(d, a, i) for d in DIRS for a, n in ANIMS for i in range(n)]  # 18

K0, K1, K2, K3 = SHADE_KEYS
WOOD = ramp("wood")
CREAM = ramp("cloth_cream")
SHOE = WOOD[0]
SHOE_HI = WOOD[1]
PANTS = [WOOD[1], WOOD[2], WOOD[3]]


@dataclass(frozen=True)
class Pose:
    bob: int  # upper body y offset
    step: int  # 0 stand, 1 left foot forward, -1 right foot forward
    swing: int  # arm swing −1..1


def pose(anim: str, i: int) -> Pose:
    if anim == "idle":
        return Pose(bob=i, step=0, swing=0)
    return [Pose(0, 0, 0), Pose(1, 1, 1), Pose(0, 0, 0), Pose(1, -1, -1)][i]


@dataclass(frozen=True)
class Body:
    torso: tuple[int, int]  # x0, x1 inclusive (down/up view)
    arms: tuple[int, int]  # left arm x, right arm x
    legs: tuple[tuple[int, int], tuple[int, int]]


BODIES = {
    "slim": Body(torso=(5, 10), arms=(4, 11), legs=((5, 6), (9, 10))),
    "sturdy": Body(torso=(4, 11), arms=(3, 12), legs=((5, 7), (8, 10))),
}

HEAD_Y = 4  # top row of the head (before bob)


def head_rows(direction: str) -> dict[int, tuple[int, int]]:
    if direction == "side":
        return {0: (6, 10), 1: (5, 11), **{r: (4, 12) for r in range(2, 8)}, 8: (5, 11)}
    return {0: (5, 10), 1: (4, 11), **{r: (3, 12) for r in range(2, 8)}, 8: (4, 11)}


def shade(x: int, y: int, x0: int, x1: int, y0: int, y1: int) -> Color:
    if x == x1 or y == y1:
        return K1
    if x == x0 or y == y0:
        return K3
    return K2


# ── body (skin) ─────────────────────────────────────────────────────────────


def draw_legs(c: Canvas, body: Body, direction: str, p: Pose, color_fn) -> None:  # noqa: ANN001
    """Legs + shoes. color_fn(x, y) gives the leg colour (skin key or pants)."""
    if direction == "side":
        front = (6, 7)
        back = (8, 9)
        if p.step:
            front, back = (5, 6), (9, 10)
        for (x0, x1), lift in ((back, 1 if p.step else 0), (front, 0)):
            for y in range(20, 23 - lift):
                for x in range(x0, x1 + 1):
                    c.put(x, y, color_fn(x, y))
            c.hline(x0 - 1, x1, 23 - lift, SHOE)
            c.put(x0 - 1, 23 - lift, SHOE_HI)
        return
    (l0, l1), (r0, r1) = body.legs
    for (x0, x1), lift in (((l0, l1), 1 if p.step < 0 else 0), ((r0, r1), 1 if p.step > 0 else 0)):
        for y in range(20, 23 - lift):
            for x in range(x0, x1 + 1):
                c.put(x, y, color_fn(x, y))
        c.hline(x0, x1, 23 - lift, SHOE)


def body_layer(body_key: str, direction: str, p: Pose) -> Canvas:
    c = Canvas(FW, FH)
    body = BODIES[body_key]
    b = p.bob
    # head
    for r, (x0, x1) in head_rows(direction).items():
        y = HEAD_Y + r + b
        for x in range(x0, x1 + 1):
            c.put(x, y, shade(x, r, x0, x1, 0, 8))
    if direction == "side":
        c.put(3, HEAD_Y + 5 + b, K2)  # nose
        c.put(4, HEAD_Y + 6 + b, K1)
    elif direction == "down":
        c.put(4, HEAD_Y + 6 + b, K3)  # cheeks catch the light
    # neck
    c.hline(7, 8, HEAD_Y + 9 + b, K1)
    # torso (usually covered by the outfit)
    tx0, tx1 = (6, 10) if direction == "side" else body.torso
    for y in range(13 + b, 20):
        for x in range(tx0, tx1 + 1):
            c.put(x, y, K2 if x > tx0 else K3)
    # arms
    if direction == "side":
        ax = 7 - p.swing
        for y in range(13 + b, 19 + b):
            c.put(ax, y, K3 if y < 17 + b else K2)
            c.put(ax + 1, y, K2 if y < 17 + b else K1)
    else:
        la, ra = body.arms
        for x, sw in ((la, p.swing), (ra, -p.swing)):
            for y in range(13 + b + max(0, sw), 18 + b + max(0, sw)):
                c.put(x, y, K3 if x == la else K1)
    draw_legs(c, body, direction, p, lambda x, y: K2)
    return c


# ── eyes ───────────────────────────────────────────────────────────────────


def eyes_layer(style: str, direction: str, p: Pose) -> Canvas:
    c = Canvas(FW, FH)
    if direction == "up":
        return c
    y = HEAD_Y + 5 + p.bob
    xs = [4] if direction == "side" else [5, 9]
    for x in xs:
        if style == "round":
            c.put(x, y, K0)
            c.put(x + 1, y, K3)
            c.put(x, y + 1, K2)
            c.put(x + 1, y + 1, K0)
        elif style == "bright":
            c.put(x, y - 1, K0)
            c.put(x + 1, y - 1, K0)
            c.put(x, y, K3)
            c.put(x + 1, y, K2)
            c.put(x, y + 1, K2)
            c.put(x + 1, y + 1, K1)
        elif style == "sleepy":
            c.put(x, y + 1, K0)
            c.put(x + 1, y + 1, K0)
            c.put(x + (1 if x < 8 else 0), y, K1)
        elif style == "keen":
            c.put(x, y - 1, K0 if x < 8 else K1)
            c.put(x + 1, y - 1, K1 if x < 8 else K0)
            c.put(x, y, K2)
            c.put(x + 1, y, K0)
        if direction == "side":
            break
    return c


# ── hair ───────────────────────────────────────────────────────────────────


def hair_layer(style: str, direction: str, p: Pose) -> Canvas:
    c = Canvas(FW, FH)
    b = p.bob
    top = HEAD_Y + b
    if style == "shaved":
        rows = head_rows(direction)
        for r in (0, 1):
            x0, x1 = rows[r]
            for x in range(x0, x1 + 1):
                if (x + r) % 2 == 0 or direction == "up":
                    c.put(x, top + r, K1 if x > (x0 + x1) // 2 else K2)
        if direction == "up":
            for r in range(2, 6):
                x0, x1 = rows[r]
                for x in range(x0, x1 + 1):
                    if (x + r) % 2 == 0:
                        c.put(x, top + r, K1)
        return c

    def cap(depth: int, sides: int) -> None:
        """Hair cap covering `depth` rows of the head, plus side locks down to row `sides`."""
        rows = head_rows(direction)
        for r in range(-1, depth):
            x0, x1 = rows.get(r, (rows[0][0] + 1, rows[0][1] - 1))
            if r == -1:
                x0, x1 = x0 + 1, x1 - 1
            for x in range(x0, x1 + 1):
                col = K3 if (x < 7 and r < 2) else K2
                if x == x1 or r == depth - 1:
                    col = K1
                c.put(x, top + r, col)
        # jagged fringe
        if direction == "down":
            for x in range(4, 12, 2):
                c.put(x, top + depth, K1)
        if direction == "side":
            for r in range(depth, sides):
                for x in range(9, 13):
                    c.put(x, top + r, K2 if x < 12 else K1)
        else:
            for r in range(depth, sides):
                c.put(3, top + r, K2)
                c.put(12, top + r, K1)
        if direction == "up":
            for r in range(depth, 8):
                x0, x1 = rows[r]
                for x in range(x0, x1 + 1):
                    c.put(x, top + r, K2 if x < 8 else K1)

    if style == "crop":
        cap(4, 6)
    elif style == "bun":
        cap(4, 6)
        bx = 10.5 if direction == "side" else 8
        by = top - 1.0 if direction != "up" else top + 1.5
        for y in range(int(by) - 2, int(by) + 2):
            for x in range(int(bx) - 2, int(bx) + 2):
                if (x + 0.5 - bx) ** 2 + (y + 0.5 - by) ** 2 <= 4.2:
                    c.put(x, y, K1 if x >= bx else K2)
        c.put(int(bx) - 1, int(by) - 1, K3)
        c.hline(int(bx) - 1, int(bx), int(by) + 1, K0)
    elif style == "spiky":
        cap(4, 5)
        for i, x in enumerate(range(4, 13, 2)):
            h = 2 + (i % 2)
            for d in range(h):
                c.put(x, top - 1 - d, K2 if d < h - 1 else K3)
    elif style == "long":
        cap(4, 9)
        if direction == "down":
            for r in range(6, 14):
                c.put(2, top + r, K2)
                c.put(3, top + r, K1 if r > 9 else K2)
                c.put(12, top + r, K1)
                c.put(13, top + r, K1)
        elif direction == "up":
            for r in range(8, 13):
                for x in range(3, 13):
                    c.put(x, top + r, K2 if x < 8 else K1)
        else:
            for r in range(6, 13):
                for x in range(10, 14):
                    c.put(x, top + r, K2 if x < 12 else K1)
    elif style == "braids":
        cap(4, 7)
        if direction != "side":
            for x in (2, 13):
                for r in range(7, 15):
                    c.put(x, top + r, K2 if r % 2 else K1)
                c.put(x, top + 15, K0)
        else:
            for r in range(7, 15):
                c.put(12, top + r, K2 if r % 2 else K1)
            c.put(12, top + 15, K0)
    return c


# ── outfits ────────────────────────────────────────────────────────────────


def outfit_layer(style: str, body_key: str, direction: str, p: Pose) -> Canvas:
    c = Canvas(FW, FH)
    body = BODIES[body_key]
    b = p.bob
    tx0, tx1 = (6, 10) if direction == "side" else body.torso
    belt_y = 17 + b

    def torso(color_fn) -> None:  # noqa: ANN001
        for y in range(13 + b, 20):
            for x in range(tx0, tx1 + 1):
                c.put(x, y, color_fn(x, y))

    def key_shade(x: int, y: int) -> Color:
        if x == tx1:
            return K1
        if x == tx0 or y == 13 + b:
            return K3
        return K2

    def sleeves(color: Color | None) -> None:
        if direction == "side":
            ax = 7 - p.swing
            for y in range(13 + b, 16 + b):
                c.put(ax, y, color or K3)
                c.put(ax + 1, y, color or K2)
            return
        la, ra = body.arms
        for x, sw in ((la, p.swing), (ra, -p.swing)):
            for y in range(13 + b + max(0, sw), 16 + b + max(0, sw)):
                c.put(x, y, color or (K3 if x == la else K1))

    def pants(fn) -> None:  # noqa: ANN001
        draw_legs(c, body, direction, p, fn)

    pants_brown = lambda x, y: PANTS[1] if (x + y) % 5 else PANTS[0]  # noqa: E731

    if style == "tunic":
        torso(key_shade)
        sleeves(None)
        c.hline(tx0, tx1, belt_y, WOOD[1])
        c.put((tx0 + tx1) // 2, belt_y, ramp("gold")[2])
        for x in range(tx0, tx1 + 1):  # hem
            c.put(x, 20, K1 if x % 2 else K2)
        pants(pants_brown)
    elif style == "dress":
        torso(key_shade)
        sleeves(None)
        for y in range(19, 22):
            spread = y - 18
            for x in range(tx0 - spread // 2, tx1 + 1 + spread // 2):
                c.put(x, y, K1 if (x - tx0) % 3 == 2 or y == 21 else K2)
        c.hline(tx0, tx1, 16 + b, K1)
        pants(lambda x, y: K2 if y < 22 else None)  # stockings under the skirt
        for y in (20, 21):  # keep the skirt on top
            for x in range(tx0 - 1, tx1 + 2):
                if c.get(x, y)[3]:
                    c.put(x, y, K1 if (x - tx0) % 3 == 2 or y == 21 else K2)
    elif style == "overalls":
        torso(lambda x, y: CREAM[2] if x > tx0 else CREAM[3])
        sleeves(CREAM[2])
        for y in range(15 + b, 20):
            for x in range(tx0 + 1, tx1):
                c.put(x, y, K2 if x < tx1 - 1 else K1)
        c.vline(tx0 + 1, 13 + b, 15 + b, K1)
        c.vline(tx1 - 1, 13 + b, 15 + b, K1)
        c.put(tx0 + 1, 16 + b, ramp("gold")[2])
        pants(lambda x, y: K2 if (x + y) % 4 else K1)
    elif style == "robe":
        torso(key_shade)
        sleeves(None)
        c.hline(tx0, tx1, belt_y, K0)
        pants(lambda x, y: K2 if x % 3 else K1)
        if direction != "side":
            for y in range(20, 23):
                c.put(tx0 - 1 + (y < 21), y, K1)
                c.put(tx1 + 1 - (y < 21), y, K1)
                for x in range(tx0, tx1 + 1):
                    if not c.get(x, y)[3] or c.get(x, y) in (SHOE,):
                        c.put(x, y, K2 if y < 22 else c.get(x, y) if c.get(x, y)[3] else K1)
    elif style == "vest":
        torso(lambda x, y: CREAM[2] if x > tx0 else CREAM[3])
        sleeves(CREAM[3])
        for y in range(13 + b, 20):
            for x in (tx0, tx0 + 1, tx1 - 1, tx1):
                if direction == "side" and x < tx1 - 1:
                    continue
                c.put(x, y, K2 if x < tx1 else K1)
        for x in range(tx0 + 2, tx1 - 1):
            c.put(x, 13 + b, K3)
        pants(pants_brown)
    elif style == "cloak":
        torso(lambda x, y: CREAM[1] if x == tx1 else CREAM[2])
        sleeves(None)
        if direction == "up":
            for y in range(12 + b, 22):
                for x in range(tx0 - 1, tx1 + 2):
                    c.put(x, y, K2 if x < 9 else K1)
        elif direction == "down":
            for y in range(13 + b, 21):
                c.put(tx0 - 1, y, K2)
                c.put(tx1 + 1, y, K1)
            c.hline(tx0, tx1, 13 + b, K3)
            c.put((tx0 + tx1) // 2, 14 + b, ramp("gold")[3])
        else:
            for y in range(13 + b, 21):
                for x in range(tx1, tx1 + 3):
                    c.put(x, y, K2 if x < tx1 + 2 else K1)
        pants(pants_brown)
    return c


def strip(layer_fn) -> Canvas:  # noqa: ANN001
    out = Canvas(FW * len(FRAMES), FH)
    for i, (d, a, n) in enumerate(FRAMES):
        frame = layer_fn(d, pose(a, n))
        out.blit(frame, i * FW, 0)
    return out


def generate(creator: dict) -> dict[str, Canvas]:
    """One strip per layer option. `creator` is config/avatar.yaml → creator."""
    out: dict[str, Canvas] = {}
    for bk in creator["bodies"]:
        if bk not in BODIES:
            raise SystemExit(f"artgen: body '{bk}' from avatar.yaml has no art")
        out[f"char.body.{bk}"] = strip(lambda d, p, bk=bk: body_layer(bk, d, p))
    for es in creator["eye_styles"]:
        out[f"char.eyes.{es}"] = strip(lambda d, p, es=es: eyes_layer(es, d, p))
    for hs in creator["hair_styles"]:
        out[f"char.hair.{hs}"] = strip(lambda d, p, hs=hs: hair_layer(hs, d, p))
    for os_ in creator["outfits"]:
        for bk in creator["bodies"]:
            out[f"char.outfit.{os_}.{bk}"] = strip(lambda d, p, os_=os_, bk=bk: outfit_layer(os_, bk, d, p))
    return out
