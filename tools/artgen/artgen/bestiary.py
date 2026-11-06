"""Phase 10 monsters from five body plans: blob, quadruped, biped, flyer and plant.

Each creature is a body plan plus a spec (size, ramps, head/limb options, extras), so the roster stays
consistent and new monsters are cheap. Side views face left (the client mirrors them). Frames follow
creatures.py: idle.0/1, move.0..n, windup.0, attack.0, hurt.0. Also the monster projectiles
(fx.shot.<kind>, pointing right).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from artgen.canvas import Canvas, hash2
from artgen.palette import HAIR, INK, OUTFIT, SKIN, hx, ramp

Ramp = list[tuple[int, int, int, int]]


def _o(name: str) -> Ramp:
    return [hx(c) for c in OUTFIT[name]]


def _h(name: str) -> Ramp:
    return [hx(c) for c in HAIR[name]]


def _s(name: str) -> Ramp:
    return [hx(c) for c in SKIN[name]]


WHITE = ramp("flower_white")
RED = ramp("flower_red")
GOLD = ramp("gold")
FIRE = ramp("fire")
LAVA = ramp("lava")
ICE = ramp("ice")
SNOW = ramp("snow")
STONE = ramp("stone")
WOOD = ramp("wood")
LEAF = ramp("leaf")
GRASS = ramp("grass")
VENOM = ramp("venom")
VIOLET = ramp("flower_purple")
WATER = ramp("water")
YELLOW = ramp("flower_yellow")


def ell(c: Canvas, cx: float, cy: float, rx: float, ry: float, rp: Ramp, flat_bottom: float = 1.0) -> set[tuple[int, int]]:
    """A shaded ellipse lit from the top-left; flat_bottom > 1 squashes the lower half (sitting blobs)."""
    pts: set[tuple[int, int]] = set()
    for y in range(c.h):
        for x in range(c.w):
            dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
            if dy > 0:
                dy *= flat_bottom
            if dx * dx + dy * dy <= 1:
                pts.add((x, y))
    n = len(rp)
    for x, y in pts:
        dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
        light = -(dx * 0.6 + dy * 0.8)
        i = max(0, min(n - 1, int((light + 1) / 2 * (n - 1) + 0.35)))
        c.put(x, y, rp[i])
    return pts


def eyes(c: Canvas, pts: list[tuple[int, int]], col: Any, shine: Any = None, shut: bool = False) -> None:
    for x, y in pts:
        if shut:
            c.put(x, y, INK)
            c.put(x + 1, y, INK)
        else:
            c.put(x, y, col)
            if shine is not None:
                c.put(x, y - 1, shine)


# ── blob ──────────────────────────────────────────────────────────────────────
@dataclass
class BlobSpec:
    w: int
    h: int
    rx: float
    ry: float
    body: Ramp
    eye: Any = INK
    extra: str = ""  # pebbles | mouth | toad | lurker
    eye_n: int = 2


def blob_frame(s: BlobSpec, sx: float, sy: float, lift: int = 0, pose: str = "idle", phase: int = 0) -> Canvas:
    c = Canvas(s.w, s.h)
    cx = s.w / 2
    c.drop_shadow(cx, s.h - 2, s.rx * 0.95 * min(1.2, sx), 1.8, alpha=80)
    rx, ry = s.rx * sx, s.ry * sy
    cy = s.h - 2.5 - ry - lift
    if s.extra == "toad":  # little legs under the body
        for lx in (cx - rx * 0.6, cx + rx * 0.45):
            leg_y = s.h - 3 - (lift if pose != "attack" else 0)
            c.rect(int(lx) - 1, int(cy + ry * 0.4), 3, max(1, int(leg_y - (cy + ry * 0.4))), s.body[1])
            c.hline(int(lx) - 2, int(lx) + 1, leg_y, s.body[2])
    pts = ell(c, cx, cy, rx, ry, s.body, flat_bottom=1.35)
    hl = s.body[-1]
    c.put(int(cx - rx * 0.45), int(cy - ry * 0.5), hl)
    c.put(int(cx - rx * 0.45) + 1, int(cy - ry * 0.5), hl)
    shut = pose == "hurt"
    angry = pose in ("windup", "attack")
    ey = int(cy + (0.5 if s.extra != "toad" else -ry * 0.55))
    if s.extra == "pebbles":
        for k in range(7):
            px = int(cx + (hash2(k, 3, 91) - 0.5) * rx * 1.5)
            py = int(cy + (hash2(k, 5, 92) - 0.3) * ry * 1.2)
            if (px, py) in pts:
                c.put(px, py, s.body[0] if k % 2 else s.body[-1])
    if s.extra == "lurker":  # mossy hump with reeds
        for x in range(int(cx - rx * 0.8), int(cx + rx * 0.8)):
            top = min((y for (px, y) in pts if px == x), default=None)
            if top is not None and hash2(x, 1, 7) < 0.7:
                c.put(x, top, GRASS[2] if x % 2 else GRASS[3])
                if hash2(x, 2, 8) < 0.3:
                    c.put(x, top - 1, GRASS[3])
                    c.put(x, top - 2, GRASS[4])
    if s.extra == "mouth":  # a round sucker of teeth
        mx, my = int(cx - rx * 0.55), int(cy + ry * 0.15)
        c.put(mx, my, INK)
        c.put(mx + 1, my, RED[0])
        c.put(mx, my + 1, WHITE[1])
        c.put(mx, my - 1, WHITE[1])
    if s.eye_n == 4:
        ex = [int(cx - rx * 0.45), int(cx - rx * 0.15), int(cx + rx * 0.15), int(cx + rx * 0.4)]
        eyes(c, [(e, ey - (k % 2)) for k, e in enumerate(ex)], s.eye, shut=shut)
    else:
        ex = [int(cx - rx * 0.32), int(cx + rx * 0.2)]
        eyes(c, [(e, ey) for e in ex], s.eye, None if angry else WHITE[2], shut=shut)
        if s.extra == "toad":
            for e in ex:  # bulging eye domes
                c.put(e - 1, ey - 1, s.body[2])
                c.put(e, ey - 2, s.body[3])
                c.put(e + 1, ey - 1, s.body[2])
    if angry:
        c.put(int(cx - rx * 0.32) - 1, ey - 2, INK)
        c.put(int(cx + rx * 0.2) + 1, ey - 2, INK)
    if s.extra == "toad" and pose in ("windup", "attack"):
        mx, my = int(cx - rx * 0.75), int(cy + ry * 0.1)
        c.hline(mx, mx + 3, my, INK)
        if pose == "attack":
            c.put(mx - 1, my, VENOM[2])
            c.put(mx - 2, my, VENOM[3])
    c.outline(INK)
    return c


def blob_frames(s: BlobSpec) -> dict[str, Canvas]:
    return {
        "idle.0": blob_frame(s, 1.0, 1.0),
        "idle.1": blob_frame(s, 1.07, 0.92, pose="idle", phase=1),
        "move.0": blob_frame(s, 0.88, 1.15, lift=2, pose="move"),
        "move.1": blob_frame(s, 1.1, 0.88, pose="move", phase=1),
        "windup.0": blob_frame(s, 1.25, 0.66, pose="windup"),
        "attack.0": blob_frame(s, 0.84, 1.2, lift=3, pose="attack"),
        "hurt.0": blob_frame(s, 1.18, 0.82, pose="hurt"),
    }


# ── quadruped (side view, facing left) ───────────────────────────────────────
@dataclass
class QuadSpec:
    body: Ramp
    belly: Ramp
    head: str = "wolf"  # wolf | hare | goat | croc | cat
    w: int = 28
    h: int = 20
    length: int = 13
    depth: int = 5
    leg: int = 4
    eye: Any = INK
    tail: str = "up"  # up | long | stub | none
    extra: str = ""  # thorns | cracks | frost | spines
    horn: Ramp = field(default_factory=lambda: ramp("sand"))


def quad(s: QuadSpec, phase: int, pose: str = "run") -> Canvas:
    c = Canvas(s.w, s.h)
    feet = s.h - 3
    c.drop_shadow(s.w / 2, s.h - 2, s.length * 0.8, 2)
    low = 2 if pose == "windup" else 0
    stretch = 3 if pose == "attack" else 0
    x0 = (s.w - s.length) // 2 + 2 - stretch
    x1 = x0 + s.length + stretch
    by = feet - s.leg - s.depth + low
    if s.head == "croc":
        by += 1
    hump = s.depth // 3 if s.head in ("goat", "wolf") else 0
    for x in range(x0, x1):
        top = by - (1 if x0 + 3 < x < x1 - 2 else 0) - (hump if x0 + 4 < x < x0 + 8 else 0)
        for y in range(top, by + s.depth):
            sh = s.body[3] if y < by + 1 else s.body[2] if y < by + s.depth - 1 else s.body[1]
            c.put(x, y, sh)
    c.hline(x0 + 3, x1 - 3, by + s.depth - 1, s.belly[2])
    # tail
    if s.tail == "up":
        for k in range(5):
            c.put(x1 + k // 2, by - k // 2 + (phase % 2 if pose == "run" else 0), s.body[3])
            c.put(x1 + k // 2, by + 1 - k // 2, s.body[2])
    elif s.tail == "long":
        for k in range(8):
            c.put(x1 + k, by + 2 - int(math.sin(k * 0.6 + phase) * 1.5), s.body[2] if k < 6 else s.body[3])
    elif s.tail == "stub":
        c.put(x1, by, s.belly[-1])
        c.put(x1, by + 1, s.belly[-2])
    # legs
    swing = [(0, 2), (1, 1), (2, 0), (1, 1)][phase % 4] if pose == "run" else (0, 0)
    if pose == "attack":
        swing = (3, -3)
    legs = [(x0 + 1, swing[0]), (x0 + 4, -swing[0]), (x1 - 4, swing[1]), (x1 - 1, -swing[1])]
    for lx, off in legs:
        for y in range(by + s.depth, feet + 1):
            c.put(lx + (off if y > feet - 2 else 0), y, s.body[1] if lx % 2 else s.body[2])
        if s.head == "goat":
            c.put(lx + off, feet, INK)
    # head
    hy = by - 3 + (2 if pose == "windup" else 0)
    hx0 = x0 - 5
    if s.head == "croc":  # long flat head with a big jaw
        hy = by
        jaw = 2 if pose in ("windup", "attack") else 0
        for x in range(hx0 - 2, x0 + 1):
            c.put(x, hy, s.body[3])
            c.put(x, hy + 1, s.body[2])
            c.put(x, hy + 2 + jaw, s.belly[2])
            c.put(x, hy + 3 + jaw, s.body[1])
        if jaw:
            for x in range(hx0 - 1, x0, 2):
                c.put(x, hy + 2, WHITE[2])
                c.put(x, hy + 3, INK)
        c.put(hx0 + 2, hy - 1, s.body[3])
        c.put(hx0 + 2, hy - 1, s.eye)
    else:
        hw = 6 if s.head != "hare" else 5
        for y in range(hy, hy + 5):
            for x in range(hx0 + 2, hx0 + 2 + hw):
                c.put(x, y, s.body[3] if y < hy + 2 else s.body[2])
        if s.head in ("wolf", "cat"):
            sn = 3 if s.head == "wolf" else 2
            for y in range(hy + 2, hy + 5):
                for x in range(hx0 + 2 - sn, hx0 + 2):
                    c.put(x, y, s.body[3] if y == hy + 2 else s.belly[2])
            c.put(hx0 + 2 - sn, hy + 2, INK)
            for ex in (hx0 + 4, hx0 + 6):
                c.put(ex, hy - 1, s.body[3])
                c.put(ex, hy - 2 if s.head == "wolf" else hy - 1, s.body[2])
        elif s.head == "hare":
            c.put(hx0 + 1, hy + 3, s.belly[2])
            c.put(hx0 + 1, hy + 2, RED[2])
            for k in range(6):  # tall ears, laid back when charging
                lean = k // 2 if pose in ("windup", "attack", "run") else 0
                c.put(hx0 + 4 + lean, hy - 1 - k, s.body[3])
                c.put(hx0 + 5 + lean, hy - 1 - k, s.body[2])
        elif s.head == "goat":
            c.put(hx0 + 1, hy + 3, s.belly[2])
            c.put(hx0 + 1, hy + 4, s.belly[1])
            c.put(hx0 + 3, hy + 5, s.belly[-1])  # beard
            for k in range(5):  # curled horns
                ang = k * 0.9
                c.put(int(hx0 + 6 + math.cos(ang) * 2.2), int(hy - 1 + math.sin(ang) * 2.2 - 1), s.horn[min(3, k)])
        c.put(hx0 + 4, hy + 1, s.eye if pose != "hurt" else INK)
        if pose in ("windup", "attack") and s.head in ("wolf", "cat"):
            c.put(hx0, hy + 4, WHITE[2])
            c.put(hx0 + 1, hy + 4, WHITE[2])
    # extras
    if s.extra == "thorns":
        for x in range(x0 + 1, x1, 3):
            c.put(x, by - 1, LEAF[3])
            c.put(x, by - 2, LEAF[4])
    elif s.extra == "cracks":
        for x in range(x0 + 1, x1 - 1):
            if hash2(x, by, 33) < 0.45:
                c.put(x, by + 1 + int(hash2(x, 2, 34) * (s.depth - 2)), LAVA[3] if x % 3 else LAVA[4])
        c.put(hx0 + 4, hy + 1, LAVA[4])
    elif s.extra == "frost":
        for x in range(x0, x1, 2):
            c.put(x, by - 1, SNOW[4])
    elif s.extra == "spines":
        for x in range(x0 + 2, x1 - 1, 2):
            c.put(x, by - 1, s.body[1])
    c.outline(INK)
    return c


def quad_frames(s: QuadSpec) -> dict[str, Canvas]:
    return {
        "idle.0": quad(s, 0, "idle"),
        "idle.1": quad(s, 1, "idle"),
        **{f"move.{i}": quad(s, i, "run") for i in range(4)},
        "windup.0": quad(s, 0, "windup"),
        "attack.0": quad(s, 0, "attack"),
        "hurt.0": quad(s, 2, "hurt"),
    }


# ── biped (three-quarter view) ───────────────────────────────────────────────
@dataclass
class BipedSpec:
    skin: Ramp
    cloth: Ramp
    w: int = 20
    h: int = 26
    scale: float = 1.0  # 1 = person-sized; 1.5 = brute; 0.65 = imp
    head: str = "plain"  # plain | hood | hat | mask | horns | golem | fur | beak
    held: str = ""  # bow | club | staff | claws
    eye: Any = INK
    extra: str = ""  # cracks | fur | stone | flame
    wide: float = 1.0
    hair: Ramp | None = None
    accent: Ramp = field(default_factory=lambda: ramp("gold"))


def biped(s: BipedSpec, phase: int, pose: str = "walk") -> Canvas:
    c = Canvas(s.w, s.h)
    k = s.scale
    cx = s.w / 2
    feet = s.h - 3
    c.drop_shadow(cx, s.h - 2, 4.5 * k * s.wide, 1.6)
    crouch = int(2 * k) if pose == "windup" else 0
    lean = -int(2 * k) if pose == "attack" else 0
    leg_h = int(6 * k)
    torso_h = int(7 * k)
    hip_y = feet - leg_h + crouch
    sh_y = hip_y - torso_h
    tw = int(4 * k * s.wide)
    # legs
    step = [(1, -1), (0, 0), (-1, 1), (0, 0)][phase % 4] if pose == "walk" else (0, 0)
    for side, off in ((-1, step[0]), (1, step[1])):
        lx = int(cx + side * max(1, tw // 2 - 1))
        for y in range(hip_y, feet + 1):
            dx = off if y > hip_y + leg_h // 2 else 0
            col = s.cloth[1] if s.extra not in ("stone", "fur") else s.skin[1 if side > 0 else 2]
            c.put(lx + dx, y, col)
            if k >= 1.3:
                c.put(lx + dx + side, y, col)
        c.put(lx + off - 1, feet, INK if s.extra != "fur" else s.skin[2])
    # torso
    for y in range(sh_y, hip_y + 1):
        half = tw if y > sh_y + 1 else tw - 1
        for x in range(int(cx - half + lean), int(cx + half + lean) + 1):
            t = (x - (cx - half + lean)) / max(1, 2 * half)
            col = s.cloth[3] if t < 0.3 else s.cloth[2] if t < 0.75 else s.cloth[1]
            c.put(x, y, col)
    if s.extra in ("", "flame"):
        c.hline(int(cx - tw + lean), int(cx + tw + lean), hip_y - 1, s.accent[1])  # belt
    if s.extra == "fur":
        for y in range(sh_y, hip_y + 1):
            for x in range(int(cx - tw + lean), int(cx + tw + lean) + 1):
                if hash2(x, y, 51) < 0.22:
                    c.put(x, y, s.cloth[3] if hash2(x, y, 52) < 0.6 else s.cloth[0])
    if s.extra in ("stone", "cracks"):
        for y in range(sh_y + 1, hip_y):
            for x in range(int(cx - tw + lean), int(cx + tw + lean) + 1):
                if hash2(x, y, 41) < 0.12:
                    c.put(x, y, s.cloth[0])
                elif s.extra == "cracks" and hash2(x, y, 42) < 0.1:
                    c.put(x, y, LAVA[3])
    # arms
    arm_up = pose in ("windup",)
    for side in (-1, 1):
        ax = int(cx + side * (tw + 1) + lean)
        if arm_up:
            for y in range(sh_y - int(3 * k), sh_y + 2):
                c.put(ax, y, s.skin[2])
        else:
            swing = (step[0] if side < 0 else step[1]) if pose == "walk" else 0
            for y in range(sh_y + 1, sh_y + int(6 * k)):
                c.put(ax + (swing if y > sh_y + 3 else 0) + (lean if pose == "attack" and side < 0 else 0), y, s.skin[2] if side < 0 else s.skin[1])
            if k >= 1.3:
                for y in range(sh_y + 1, sh_y + int(6 * k)):
                    c.put(ax + side, y, s.skin[1])
    # head
    hr = 3.2 * min(1.25, k) if s.head != "golem" else 2.0 * k
    hy = sh_y - hr + 0.5 + (1 if pose == "windup" else 0)
    if s.head in ("golem", "fur"):
        hy += hr * 0.55  # hunched: the head sits down between the shoulders
    hcx = cx + lean - 0.5
    if s.head == "golem":
        for side in (-1, 1):  # boulder shoulders
            ell(c, cx + lean + side * (tw - 0.5), sh_y + 1.5, 2.6 * k * 0.8, 2.2 * k * 0.8, s.skin)
        ell(c, hcx, hy, hr * 1.05, hr * 0.9, s.skin)
        c.hline(int(hcx - hr + 1), int(hcx + hr - 1), int(hy - hr * 0.2), s.skin[0])  # brow ridge
    else:
        ell(c, hcx, hy, hr, hr * 0.95, s.skin)
    if s.head == "fur":  # a darker face under the fur
        ell(c, hcx - 0.5, hy + hr * 0.25, hr * 0.62, hr * 0.5, s.cloth[0:3])
    ey = int(hy + 0.5) + (1 if s.head == "golem" else 0)
    shut = pose == "hurt"
    eyes(c, [(int(hcx - hr * 0.45), ey), (int(hcx + hr * 0.2), ey)], s.eye, shut=shut)
    if s.head == "hood":
        for y in range(int(hy - hr - 1), int(hy + 1)):
            for x in range(int(hcx - hr - 1), int(hcx + hr + 2)):
                inside = (x + 0.5 - hcx) ** 2 / (hr + 1.2) ** 2 + (y + 0.5 - hy) ** 2 / (hr + 1.2) ** 2 <= 1
                face = (x + 0.5 - hcx) ** 2 + (y + 0.5 - hy - 1) ** 2 < (hr * 0.75) ** 2
                if inside and not face:
                    c.put(x, y, s.cloth[2] if y < hy - hr / 2 else s.cloth[1])
        c.put(int(hcx + hr + 1), int(hy + 1), s.cloth[1])
    elif s.head == "hat":
        c.hline(int(hcx - hr - 2), int(hcx + hr + 2), int(hy - hr + 1), s.cloth[1])
        for i in range(int(4 * k) + 2):
            w = max(0, int(hr - i * 0.6))
            c.hline(int(hcx - w + i * 0.3), int(hcx + w + i * 0.3), int(hy - hr - i), s.cloth[2 if i % 3 else 3])
        c.put(int(hcx + 2), int(hy - hr - int(4 * k) - 2), s.accent[3])
    elif s.head == "mask":
        for y in range(int(hy - 1), int(hy + 2)):
            c.hline(int(hcx - hr + 1), int(hcx + hr - 1), y, ramp("sand")[3])
        eyes(c, [(int(hcx - hr * 0.45), ey), (int(hcx + hr * 0.2), ey)], s.eye, shut=shut)
        for i in range(3):  # feathers
            c.vline(int(hcx - 2 + i * 2), int(hy - hr - 3), int(hy - hr), (RED, LEAF, GOLD)[i][2])
    elif s.head == "horns":
        for side in (-1, 1):
            c.put(int(hcx + side * hr), int(hy - hr + 1), s.accent[2])
            c.put(int(hcx + side * (hr + 1)), int(hy - hr), s.accent[3])
    elif s.head == "fur":
        for x in range(int(hcx - hr), int(hcx + hr) + 1, 2):
            c.put(x, int(hy - hr), s.skin[3])
        c.hline(int(hcx - hr * 0.6), int(hcx + hr * 0.4), int(hy + hr * 0.55), s.cloth[0])
        if pose in ("windup", "attack"):
            c.put(int(hcx - 1), int(hy + hr * 0.55), WHITE[2])
            c.put(int(hcx + 1), int(hy + hr * 0.55), WHITE[2])
    if s.hair is not None and s.head == "plain":
        for x in range(int(hcx - hr), int(hcx + hr) + 1):
            c.put(x, int(hy - hr + 0.5), s.hair[2])
            if x < hcx:
                c.put(x, int(hy - hr + 1.5), s.hair[1])
    # held things (in the left/front hand)
    hx_ = int(cx - tw - 1 + lean)
    hy_ = sh_y + int(5 * k) if not arm_up else sh_y - int(3 * k)
    if s.held == "bow":
        draw = 2 if pose in ("windup", "attack") else 0
        for i in range(-4, 5):
            c.put(hx_ - 1 - int((1 - (i / 4) ** 2) * 2), hy_ - 4 + i, WOOD[3])
        c.vline(hx_ + draw - 1, hy_ - 8, hy_, WHITE[1])
        if pose == "windup":
            c.hline(hx_ - 4, hx_ + 1, hy_ - 4, WOOD[4])
            c.put(hx_ - 5, hy_ - 4, s.accent[3])
    elif s.held == "club":
        top = hy_ - int(6 * k) if pose != "attack" else hy_ - 2
        x = hx_ if pose != "attack" else hx_ - 3
        c.vline(x, top, hy_, WOOD[2])
        c.rect(x - 1, top - 2, 3, 3, WOOD[3])
        c.put(x - 1, top - 2, STONE[4])
    elif s.held == "staff":
        top = hy_ - int(10 * k)
        c.vline(hx_, top, hy_ + 2, WOOD[2])
        orb = s.accent
        c.put(hx_, top - 1, orb[2])
        c.put(hx_ - 1, top - 1, orb[3])
        c.put(hx_, top - 2, orb[3])
        if pose in ("windup", "attack"):
            c.put(hx_ + 1, top - 2, orb[3])
            c.put(hx_ - 1, top - 3, orb[min(len(orb) - 1, 4)])
    elif s.held == "claws":
        for i in range(3):
            c.put(hx_ - 1, hy_ + i - 1, WHITE[1])
    if s.extra == "flame":  # a flickering flame crest
        for i in range(3):
            fx_ = int(hcx - 1 + i)
            fh = 2 + (phase + i) % 2
            for j in range(fh):
                c.put(fx_, int(hy - hr - j), FIRE[3 - min(2, j)] if j else FIRE[2])
    c.outline(INK)
    return c


def biped_frames(s: BipedSpec) -> dict[str, Canvas]:
    return {
        "idle.0": biped(s, 0, "idle"),
        "idle.1": biped(s, 2, "idle"),
        **{f"move.{i}": biped(s, i, "walk") for i in range(4)},
        "windup.0": biped(s, 0, "windup"),
        "attack.0": biped(s, 0, "attack"),
        "hurt.0": biped(s, 1, "hurt"),
    }


# ── flyer (hovers; its shadow stays on the ground) ───────────────────────────
@dataclass
class FlyerSpec:
    body: Ramp
    wing: Ramp
    kind: str  # bee | harpy | wraith | cloud | crystal
    w: int = 22
    h: int = 26
    r: float = 4.0
    eye: Any = INK


def flyer(s: FlyerSpec, phase: int, pose: str = "fly") -> Canvas:
    c = Canvas(s.w, s.h)
    cx = s.w / 2
    c.drop_shadow(cx, s.h - 2, s.r * 1.1, 1.5, alpha=60)
    bob = [0, -1, -2, -1][phase % 4]
    if pose == "windup":
        bob = -3
    if pose == "attack":
        bob = 0
    cy = s.h - 9 - s.r + bob
    flap = phase % 2 == 0 if pose != "windup" else True
    if s.kind in ("bee", "harpy", "crystal"):
        for side in (-1, 1):
            wx = cx + side * s.r * 0.6
            wy = cy - s.r * (0.9 if flap else 0.1)
            span = s.r * (1.3 if s.kind == "harpy" else 0.9)
            ell(c, wx + side * span * 0.5, wy, span * 0.75, s.r * (0.55 if flap else 0.4), s.wing)
    if s.kind == "wraith":  # a tapering wisp tail
        for i in range(8):
            r = s.r * (1 - i / 9)
            ell(c, cx + math.sin(i * 0.8 + phase) * 1.2, cy + s.r * 0.6 + i * 0.9, r, r * 0.6, s.body[:3])
    if s.kind == "cloud":
        for ox, oy, rr in ((-s.r * 0.7, 0.5, 0.75), (s.r * 0.7, 0.8, 0.7), (0, -s.r * 0.35, 0.85)):
            ell(c, cx + ox, cy + oy, s.r * rr, s.r * rr * 0.8, s.body)
    if s.kind == "crystal":
        pts = [(cx, cy - s.r * 1.5), (cx + s.r * 0.9, cy), (cx, cy + s.r * 1.4), (cx - s.r * 0.9, cy)]
        c.poly(pts, lambda x, y: s.body[3] if x < cx - 0.5 and y < cy else s.body[2] if x < cx + 0.5 else s.body[1])
        c.vline(int(cx), int(cy - s.r * 1.2), int(cy + s.r), s.body[-1])
    else:
        ell(c, cx, cy, s.r, s.r * (0.85 if s.kind != "bee" else 0.75), s.body)
    if s.kind == "bee":
        for x in range(int(cx - s.r), int(cx + s.r) + 1):
            if x % 3 == 0:
                for y in range(int(cy - s.r), int(cy + s.r) + 1):
                    if c.filled(x, y):
                        c.put(x, y, _o("charcoal")[1])
        c.put(int(cx + s.r), int(cy + 1), _o("charcoal")[0])  # stinger
        c.put(int(cx + s.r + 1), int(cy + 1), _o("charcoal")[0])
    if s.kind == "harpy":  # a little face and a crest
        ell(c, cx - s.r * 0.35, cy - s.r * 0.4, s.r * 0.55, s.r * 0.55, _s("tan"))
        c.put(int(cx - s.r * 0.85), int(cy - s.r * 0.3), GOLD[2])  # beak
        for i in range(3):
            c.put(int(cx - 1 + i), int(cy - s.r * 1.05 - (i % 2)), s.wing[3])
        legs_y = int(cy + s.r * 0.8)
        c.vline(int(cx - 1), legs_y, legs_y + 2, GOLD[1])
        c.vline(int(cx + 1), legs_y, legs_y + 2, GOLD[1])
    ex = int(cx - s.r * (0.65 if s.kind == "harpy" else 0.4))
    ey = int(cy - (s.r * 0.4 if s.kind == "harpy" else 0))
    shut = pose == "hurt"
    if s.kind == "crystal":
        eyes(c, [(int(cx - 1), int(cy - 1)), (int(cx + 1), int(cy - 1))], s.eye, shut=shut)
    elif s.kind == "harpy":
        eyes(c, [(ex, ey)], s.eye, shut=shut)
    else:
        eyes(c, [(ex, ey), (ex + max(2, int(s.r * 0.6)), ey)], s.eye, shut=shut)
    if s.kind == "cloud":  # a bolt underneath, brighter when it winds up
        bolt = [(0, 0), (-1, 1), (0, 2), (-1, 3), (0, 4)]
        col = YELLOW[2] if pose in ("windup", "attack") or phase % 2 else YELLOW[1]
        for bx, by in bolt:
            c.put(int(cx + 1 + bx), int(cy + s.r * 0.7 + by), col)
    c.outline(INK)
    return c


def flyer_frames(s: FlyerSpec) -> dict[str, Canvas]:
    return {
        "idle.0": flyer(s, 0, "fly"),
        "idle.1": flyer(s, 1, "fly"),
        **{f"move.{i}": flyer(s, i, "fly") for i in range(4)},
        "windup.0": flyer(s, 1, "windup"),
        "attack.0": flyer(s, 0, "attack"),
        "hurt.0": flyer(s, 2, "hurt"),
    }


# ── plants ────────────────────────────────────────────────────────────────────
def sapling(phase: int, pose: str = "walk", tiny: bool = False) -> Canvas:
    c = Canvas(14, 14) if tiny else Canvas(24, 30)
    cx = c.w / 2
    feet = c.h - 3
    c.drop_shadow(cx, c.h - 2, 3 if tiny else 6, 1.5)
    if tiny:  # a sprout on a bulb, two leaves
        bob = phase % 2
        ell(c, cx, feet - 2 - bob, 2.6, 2.2, ramp("dirt")[1:])
        c.vline(int(cx), feet - 7 - bob, feet - 4 - bob, LEAF[2])
        ell(c, cx - 2, feet - 7 - bob, 2, 1.2, LEAF)
        ell(c, cx + 2, feet - 8 - bob, 2, 1.2, LEAF)
        eyes(c, [(int(cx - 1), feet - 3 - bob), (int(cx + 1), feet - 3 - bob)], INK, shut=pose == "hurt")
        c.outline(INK)
        return c
    sway = [0, 1, 0, -1][phase % 4] if pose == "walk" else (2 if pose == "windup" else -2 if pose == "attack" else 0)
    # root legs
    for i, lx in enumerate((cx - 3, cx - 1, cx + 2)):
        lift = (phase + i) % 2 if pose == "walk" else 0
        c.line(int(cx), feet - 5, int(lx + (i - 1) * 1.5), feet - lift, WOOD[2])
    # trunk
    for y in range(feet - 14, feet - 4):
        c.hline(int(cx - 2 + sway * (feet - y) / 14), int(cx + 1 + sway * (feet - y) / 14), y, WOOD[3] if y % 3 else WOOD[2])
    eyes(c, [(int(cx - 2 + sway * 0.6), feet - 10), (int(cx + sway * 0.6), feet - 10)], GOLD[3] if pose in ("windup", "attack") else INK, shut=pose == "hurt")
    # canopy
    top = feet - 15
    for ox, oy, r in ((-3, 0, 4.5), (3, -1, 4.2), (0, -4, 5.0)):
        ell(c, cx + ox + sway * 1.2, top + oy, r, r * 0.85, LEAF)
    if pose == "windup":  # glowing seeds
        for i in range(3):
            c.put(int(cx - 3 + i * 3 + sway), top - 2 + i % 2, GOLD[3])
    c.outline(INK)
    return c


def sapling_frames(tiny: bool = False) -> dict[str, Canvas]:
    return {
        "idle.0": sapling(0, "idle", tiny),
        "idle.1": sapling(1, "idle", tiny),
        "move.0": sapling(0, "walk", tiny),
        "move.1": sapling(1, "walk", tiny),
        "windup.0": sapling(0, "windup", tiny),
        "attack.0": sapling(0, "attack", tiny),
        "hurt.0": sapling(0, "hurt", tiny),
    }


# ── the roster ────────────────────────────────────────────────────────────────
# ── the Delve Warden (Phase 12 boss): a hulking obsidian guardian, built by hand ──
def _slab(c: Canvas, x0: int, y0: int, x1: int, y1: int, rp: Ramp) -> None:
    """A block lit from the top-left: bright left edge and top row, dark right side."""
    n = len(rp)
    w = max(1, x1 - x0)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            u = (x - x0) / w
            i = n - 1 if u < 0.2 else n - 2 if u < 0.6 else max(0, n - 3)
            if y == y0:
                i = min(n - 1, i + 1)
            c.put(x, y, rp[i])


def warden(phase: int, pose: str) -> Canvas:
    ob = ramp("obsidian")
    hot = (255, 255, 255, 255)
    c = Canvas(52, 54)
    cx = 26
    feet = 51
    c.drop_shadow(cx, 52, 17, 2.4)
    crouch = 3 if pose == "windup" else 1 if pose == "attack" else 0
    rock = -1 if pose == "hurt" else 0
    step = [(1, -1), (0, 0), (-1, 1), (0, 0)][phase % 4] if pose == "walk" else (0, 0)
    hip = feet - 11 + crouch
    sh = hip - 17 + rock
    # legs: thick stone columns; a stepping foot lifts
    for side, off in ((-1, step[0]), (1, step[1])):
        lx = cx + side * 7
        lift = 2 if off > 0 else 0
        _slab(c, lx - 3, hip, lx + 3, feet - 2 - lift, ob)
        _slab(c, lx - 4, feet - 2 - lift, lx + 4, feet - lift, STONE[0:3])
    # torso: a broad wedge of obsidian plates with a glowing rune
    for y in range(sh, hip + 1):
        half = round(14 - 4 * (y - sh) / max(1, hip - sh))
        for x in range(cx - half, cx + half + 1):
            u = (x - (cx - half)) / (2 * half)
            c.put(x, y, ob[3] if u < 0.18 else ob[2] if u < 0.55 else ob[1] if u < 0.85 else ob[0])
    c.hline(cx - 11, cx + 11, sh + 6, ob[0])
    c.hline(cx - 9, cx + 9, sh + 12, ob[0])
    glow = VIOLET[2] if pose in ("windup", "attack") else VIOLET[1]
    for i in range(5):
        c.put(cx - 5 + i, sh + 2 + i, glow)
        c.put(cx + 5 - i, sh + 2 + i, glow)
    for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
        c.put(cx + dx, sh + 9 + dy, VIOLET[2])
    c.put(cx, sh + 9, hot)
    # head, sunk between the shoulders
    _slab(c, cx - 5, sh - 7, cx + 5, sh + 1, ob[1:])
    c.hline(cx - 5, cx + 5, sh - 4, ob[0])
    for ex in (cx - 4, cx + 2):
        c.hline(ex, ex + 2, sh - 3, VIOLET[2])
        c.put(ex + 1, sh - 3, hot)
        c.put(ex + 1, sh - 2, VIOLET[1])
    if pose in ("windup", "attack"):
        c.hline(cx - 4, cx + 4, sh - 3, VIOLET[2])
        c.put(cx - 3, sh - 3, hot)
        c.put(cx + 3, sh - 3, hot)
    # arms and fists
    def fist(x: float, y: float) -> None:
        ell(c, x, y, 4.6, 3.9, STONE[0:4])

    if pose == "windup":
        for side in (-1, 1):
            for y in range(sh - 10, sh + 4):
                ax = cx + side * (12 + (y - (sh - 10)) // 4)
                _slab(c, ax - 2, y, ax + 2, y, STONE[0:3])
            fist(cx + side * 9, sh - 12)
    elif pose == "attack":
        for side in (-1, 1):
            c.line(cx + side * 15, sh + 3, cx + side * 15, feet - 4, STONE[1])
            for w in range(-2, 3):
                c.line(cx + side * 15 + w, sh + 3, cx + side * 15 + w, feet - 4, STONE[1 if w > 0 else 2])
            fist(cx + side * 15, feet - 3)
            for k in range(3):  # cracked stone kicked up by the slam
                c.put(cx + side * (20 + k), feet - 1 - k * 2, STONE[3])
    else:
        for side, swing in ((-1, -step[0]), (1, -step[1])):
            ax = cx + side * 16
            for y in range(sh + 3, hip + 3):
                sx = swing if y > sh + 9 else 0
                _slab(c, ax - 2 + sx, y, ax + 2 + sx, y, STONE[0:3] if side > 0 else STONE[1:4])
            fist(ax + swing, hip + 5)
    # pauldrons with violet crystal shards
    for side in (-1, 1):
        ell(c, cx + side * 13, sh + 1, 6.5, 5, STONE[1:5])
        sx = cx + side * 14
        c.vline(sx, sh - 6, sh - 3, VIOLET[1])
        c.put(sx, sh - 7, VIOLET[2])
        c.vline(sx - side, sh - 4, sh - 3, VIOLET[0])
    c.outline(INK)
    return c


def warden_frames() -> dict[str, Canvas]:
    return {
        "idle.0": warden(0, "idle"),
        "idle.1": warden(2, "idle"),
        **{f"move.{i}": warden(i, "walk") for i in range(4)},
        "windup.0": warden(0, "windup"),
        "attack.0": warden(0, "attack"),
        "hurt.0": warden(1, "hurt"),
    }


def roster() -> dict[str, dict[str, Canvas]]:
    return {
        "big_slime": blob_frames(BlobSpec(30, 26, 11, 8.5, ramp("grass"))),
        "thornhare": quad_frames(QuadSpec(ramp("dirt")[1:], ramp("cloth_cream"), head="hare", w=24, h=18, length=10, depth=4, leg=3, tail="stub", extra="thorns")),
        "buzzling": flyer_frames(FlyerSpec(YELLOW + [GOLD[4]], ramp("water")[3:], "bee", w=18, h=20, r=3.4)),
        "bandit_archer": biped_frames(BipedSpec(_s("tan"), _o("forest"), head="hood", held="bow", accent=ramp("gold"))),
        "bandit_brute": biped_frames(BipedSpec(_s("honey"), _o("red"), w=28, h=34, scale=1.45, wide=1.15, head="plain", held="club", hair=_h("chestnut"))),
        "sapling": sapling_frames(),
        "seedling": sapling_frames(tiny=True),
        "rock_golem": biped_frames(BipedSpec(STONE[1:5], STONE[0:4], w=30, h=34, scale=1.5, wide=1.3, head="golem", eye=GOLD[3], extra="stone")),
        "ram_goat": quad_frames(QuadSpec(ramp("cloth_cream"), ramp("flower_white"), head="goat", length=12, depth=5, leg=4, tail="stub", horn=ramp("sand"))),
        "harpy": flyer_frames(FlyerSpec(_o("rose")[1:] + [WHITE[1]], _o("rose"), "harpy", r=4.2, eye=INK)),
        "crystal_sprite": flyer_frames(FlyerSpec(_h("violet") + [WHITE[2]], ICE, "crystal", w=20, h=24, r=3.6, eye=WHITE[2])),
        "pebbling": blob_frames(BlobSpec(16, 14, 5, 4.2, STONE[1:5], extra="pebbles")),
        "bog_lurker": blob_frames(BlobSpec(26, 18, 9, 5.5, ramp("bog"), eye=GOLD[3], extra="lurker", eye_n=4)),
        "toad_spitter": blob_frames(BlobSpec(22, 18, 7, 5, ramp("bog")[1:] + [GRASS[3]], eye=GOLD[2], extra="toad")),
        "leechling": blob_frames(BlobSpec(16, 13, 5, 3.6, _o("red"), extra="mouth")),
        "mire_shaman": biped_frames(BipedSpec(ramp("bog")[1:], ramp("mud"), head="mask", held="staff", eye=GOLD[3], accent=VENOM, extra="fur")),
        "snapjaw": quad_frames(QuadSpec(ramp("bog"), ramp("sand"), head="croc", w=30, h=16, length=15, depth=4, leg=2, tail="long", eye=GOLD[3], extra="spines")),
        "ice_wraith": flyer_frames(FlyerSpec(ICE + [WHITE[2]], ICE, "wraith", r=4.0, eye=_o("navy")[1])),
        "frost_wolf": quad_frames(QuadSpec(SNOW[0:4] + [WHITE[2]], SNOW, head="wolf", eye=_o("sky")[3], extra="frost")),
        "yeti": biped_frames(BipedSpec(SNOW[1:], SNOW[0:4], w=30, h=34, scale=1.5, wide=1.3, head="fur", eye=_o("navy")[1], extra="fur", held="claws")),
        "snow_imp": biped_frames(BipedSpec(ICE, _o("sky"), w=16, h=18, scale=0.65, head="horns", eye=WHITE[2], accent=SNOW)),
        "rime_stalker": quad_frames(QuadSpec(_o("navy"), ICE, head="cat", length=13, depth=4, leg=4, tail="long", eye=ICE[3], extra="frost")),
        "fire_imp": biped_frames(BipedSpec(FIRE[0:4], ramp("ash")[1:], w=16, h=18, scale=0.65, head="horns", eye=FIRE[4], accent=ramp("ash"), extra="flame")),
        "magma_hound": quad_frames(QuadSpec(ramp("ash"), ramp("ash")[1:], head="wolf", eye=LAVA[4], extra="cracks")),
        "ash_golem": biped_frames(BipedSpec(ramp("obsidian"), ramp("ash"), w=30, h=34, scale=1.5, wide=1.3, head="golem", eye=LAVA[4], extra="cracks")),
        "cinder_witch": biped_frames(BipedSpec(_s("porcelain"), ramp("obsidian"), head="hat", held="staff", eye=FIRE[3], accent=FIRE, hair=_h("auburn"))),
        "ember_archer": biped_frames(BipedSpec(_s("umber"), _o("charcoal"), head="hood", held="bow", eye=FIRE[3], accent=FIRE)),
        "delve_warden": warden_frames(),
        "storm_elemental": flyer_frames(FlyerSpec(_o("navy") + [STONE[4]], _o("navy"), "cloud", w=26, h=26, r=5.0, eye=YELLOW[2])),
    }


# ── monster projectiles (pointing right) ─────────────────────────────────────
def shot(kind: str) -> Canvas:
    c = Canvas(14, 7)
    if kind == "arrow":
        c.hline(1, 10, 3, WOOD[3])
        c.put(11, 3, STONE[4])
        c.put(12, 3, STONE[5])
        c.put(11, 2, STONE[3])
        c.put(11, 4, STONE[3])
        for x in (1, 2):
            c.put(x, 2, WHITE[1])
            c.put(x, 4, WHITE[1])
    elif kind == "sting":
        c.hline(4, 10, 3, _o("charcoal")[2])
        c.put(11, 3, _o("charcoal")[3])
        c.put(3, 3, YELLOW[2])
    elif kind in ("spit", "ice", "fire", "rock"):
        rp = {"spit": VENOM, "ice": ICE, "fire": FIRE, "rock": STONE[1:5]}[kind]
        ell(c, 9, 3.5, 2.6, 2.2, rp)
        for i in range(3):  # trail
            c.put(5 - i * 2, 3 + (i % 2), rp[1 + (i == 0)])
        if kind == "ice":
            c.put(11, 3, WHITE[2])
    elif kind in ("crystal", "orb", "arcane", "tome_burn", "tome_slow", "tome_poison"):
        rp = {"crystal": ICE, "orb": VIOLET + [ICE[3]], "arcane": VIOLET + [GOLD[4]], "tome_burn": FIRE,
              "tome_slow": ICE, "tome_poison": VENOM}[kind]
        big = kind in ("orb",)
        ell(c, 9, 3.5, 3.3 if big else 2.4, 3.0 if big else 2.0, rp)
        for i in range(3):
            c.put(5 - i * 2, 3 + (i % 2), rp[min(len(rp) - 1, 2 - (i > 0))])
        c.put(9, 2, WHITE[2])
    elif kind == "wave":
        for y in range(7):
            x = 11 - abs(3 - y)
            c.put(x, y, VIOLET[2])
            c.put(x - 1, y, ICE[3])
            c.put(x - 3, y, VIOLET[1])
    elif kind == "bolt":
        pts = [(1, 3), (4, 1), (6, 4), (9, 2), (12, 4)]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
            c.line(x0, y0, x1, y1, YELLOW[2])
        c.put(12, 4, WHITE[2])
    c.outline(INK)
    return c


SHOTS = ("arrow", "spit", "sting", "ice", "fire", "bolt", "rock", "crystal", "orb", "arcane", "wave",
         "tome_burn", "tome_slow", "tome_poison")


def generate() -> dict[str, Canvas]:
    out: dict[str, Canvas] = {}
    for kind, frames in roster().items():
        for name, cv in frames.items():
            out[f"mon.{kind}.{name}"] = cv
    for k in SHOTS:
        out[f"fx.shot.{k}"] = shot(k)
    return out
