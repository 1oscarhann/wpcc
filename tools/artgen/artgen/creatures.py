"""Avatar Mode art: monsters (slime, wolf, spider), held weapons, swing and impact FX.

Monsters face left in their side frames (the client mirrors for right). Anchor = bottom-centre.
Frame names: mon.<kind>.<anim>.<i> with anims idle(2) move(2-4) windup(1) attack(1) hurt(1).
"""

from __future__ import annotations

import math

from artgen.canvas import Canvas, blob, hash2
from artgen.palette import INK, OUTFIT, hx, ramp

GRASS = ramp("grass")
LEAF = ramp("leaf")
STONE = ramp("stone")
WOOD = ramp("wood")
GOLD = ramp("gold")
FIRE = ramp("fire")
RED = ramp("flower_red")
CREAM = ramp("cloth_cream")
PLUM = [hx(c) for c in OUTFIT["plum"]]
CHAR = [hx(c) for c in OUTFIT["charcoal"]]
WHITE = ramp("flower_white")


# ── slime ──────────────────────────────────────────────────────────────────
def slime(sx: float, sy: float, lift: int = 0, blink: bool = False, angry: bool = False) -> Canvas:
    """sx/sy squash-and-stretch (1 = rest); lift raises the body for hops (the shadow stays put)."""
    c = Canvas(20, 18)
    c.drop_shadow(10, 16, 6.5 * min(1.2, sx), 1.8, alpha=80)
    rx, ry = 7 * sx, 5.6 * sy
    cy = 15.5 - ry - lift
    pts = set()
    for y in range(c.h):
        for x in range(c.w):
            dx, dy = (x + 0.5 - 10) / rx, (y + 0.5 - cy) / ry
            # flatter bottom, domed top
            if dy > 0:
                dy *= 1.35
            if dx * dx + dy * dy <= 1:
                pts.add((x, y))
    for x, y in pts:
        dx, dy = (x + 0.5 - 10) / rx, (y + 0.5 - cy) / ry
        light = -(dx * 0.6 + dy * 0.8)
        i = 1 if light < -0.35 else 2 if light < 0.25 else 3
        c.put(x, y, GRASS[i])
    # glossy highlight + inner bubble
    hx0, hy0 = int(10 - rx * 0.45), int(cy - ry * 0.45)
    c.put(hx0, hy0, GRASS[4])
    c.put(hx0 + 1, hy0, GRASS[4])
    c.put(hx0, hy0 + 1, GRASS[4])
    c.put(int(10 + rx * 0.35), int(cy + ry * 0.35), GRASS[3])
    # face
    ey = int(cy + 0.5)
    for ex in (int(10 - rx * 0.3), int(10 + rx * 0.2)):
        if blink:
            c.put(ex, ey, INK)
            c.put(ex + 1, ey, INK)
        else:
            c.put(ex, ey, INK)
            c.put(ex, ey - 1, INK if angry else WHITE[2])
    if angry:
        c.put(int(10 - rx * 0.3) - 1, ey - 2, INK)
        c.put(int(10 + rx * 0.2) + 1, ey - 2, INK)
    c.outline(INK)
    return c


def slime_frames() -> dict[str, Canvas]:
    return {
        "idle.0": slime(1.0, 1.0),
        "idle.1": slime(1.08, 0.9, blink=True),
        "move.0": slime(0.86, 1.18, lift=3),
        "move.1": slime(1.12, 0.86),
        "windup.0": slime(1.3, 0.62, angry=True),
        "attack.0": slime(0.82, 1.25, lift=4, angry=True),
        "hurt.0": slime(1.2, 0.8, blink=True),
    }


def crown() -> Canvas:
    c = Canvas(11, 7)
    for x in range(1, 10):
        c.put(x, 5, GOLD[2])
        c.put(x, 4, GOLD[3])
    for px in (1, 5, 9):
        for y in range(1, 4):
            c.put(px, y, GOLD[3] if px < 5 else GOLD[2])
        c.put(px, 0, GOLD[4])
    c.put(5, 3, RED[1])
    c.put(3, 4, ramp("water")[3])
    c.put(7, 4, ramp("water")[3])
    c.outline(INK)
    return c


# ── wolf (side view, facing left) ─────────────────────────────────────────
def wolf(phase: int, pose: str = "run") -> Canvas:
    c = Canvas(28, 20)
    c.drop_shadow(14, 18, 10, 2)
    low = 2 if pose == "windup" else 0
    stretch = 3 if pose == "attack" else 0
    body_y = 9 + low
    # body
    for x in range(8 - stretch, 21):
        top = body_y - (1 if 11 < x < 18 else 0)
        for y in range(top, body_y + 5):
            shade = STONE[3] if y < body_y + 1 else STONE[2] if y < body_y + 4 else STONE[1]
            c.put(x, y, shade)
    # belly lighter
    c.hline(11 - stretch, 18, body_y + 4, CREAM[2])
    # tail (up and curved)
    for k in range(6):
        c.put(21 + k // 2 + (k > 3), body_y - 1 - k // 2 + (phase % 2 if pose == "run" else 0), STONE[3] if k < 4 else STONE[4])
        c.put(21 + k // 2, body_y - k // 2, STONE[2])
    # head
    hx0 = 3 - stretch
    hy0 = body_y - 4 + (2 if pose == "windup" else 0)
    for y in range(hy0, hy0 + 6):
        for x in range(hx0 + 2, hx0 + 9):
            c.put(x, y, STONE[3] if y < hy0 + 2 else STONE[2])
    for y in range(hy0 + 3, hy0 + 6):  # snout
        for x in range(hx0, hx0 + 3):
            c.put(x, y, STONE[3] if y == hy0 + 3 else CREAM[2])
    c.put(hx0, hy0 + 3, INK)  # nose
    c.put(hx0 + 4, hy0 + 2, INK if pose != "windup" else RED[1])  # eye
    if pose in ("windup", "attack"):
        c.put(hx0 + 1, hy0 + 5, WHITE[2])  # teeth
        c.put(hx0 + 2, hy0 + 5, WHITE[2])
    for ex in (hx0 + 5, hx0 + 7):  # ears
        c.put(ex, hy0 - 1, STONE[3])
        c.put(ex, hy0 - 2, STONE[2])
    # legs: 4, alternating
    swing = [(0, 2), (1, 1), (2, 0), (1, 1)][phase % 4] if pose == "run" else (0, 0)
    if pose == "attack":
        swing = (3, -3)
    legs = [(9 - stretch, swing[0]), (12 - stretch, -swing[0]), (17, swing[1]), (20, -swing[1])]
    for lx, off in legs:
        for y in range(body_y + 5, 17):
            c.put(lx + (off if y > 14 else 0), y, STONE[2] if lx % 2 else STONE[1])
        c.put(lx + off, 17, STONE[1])
    c.outline(INK)
    return c


def wolf_frames() -> dict[str, Canvas]:
    return {
        "idle.0": wolf(0, "idle"),
        "idle.1": wolf(1, "idle"),
        **{f"move.{i}": wolf(i, "run") for i in range(4)},
        "windup.0": wolf(0, "windup"),
        "attack.0": wolf(0, "attack"),
        "hurt.0": wolf(2, "idle"),
    }


# ── spider (three-quarter view) ───────────────────────────────────────────
def spider(phase: int, pose: str = "walk") -> Canvas:
    c = Canvas(26, 20)
    c.drop_shadow(13, 17, 8, 2)
    rise = 2 if pose == "windup" else 0
    by = 11 - rise
    # 4 thin legs per side: hip → knee (raised) → foot, alternating as it walks
    for i in range(4):
        lift = (i + phase) % 2 if pose in ("walk", "idle") else 0
        for sgn in (-1, 1):
            hip = (13 + sgn * 2, by - 2 + i * 1.5)
            knee = (13 + sgn * (6 + i * 0.7), by - 5 + i * 2.2 - lift)
            foot = (13 + sgn * (9 + i * 0.6), by + 1 + i * 2.0 - lift)
            if pose == "windup" and i == 0:
                knee = (13 + sgn * 5, by - 8)
                foot = (13 + sgn * 7, by - 10)
            if pose == "attack" and i == 0:
                foot = (13 + sgn * 6, by - 8)
            c.line(int(hip[0]), int(hip[1]), int(knee[0]), int(knee[1]), CHAR[2])
            c.line(int(knee[0]), int(knee[1]), int(foot[0]), int(min(18, foot[1])), CHAR[1])
    # abdomen + head
    blob(c, [(13, by + 2, 4.6)], PLUM, seed=7, dither=False)
    blob(c, [(13, by - 3, 2.8)], CHAR[1:], seed=8, dither=False)
    # markings
    c.put(13, by + 1, RED[1])
    c.put(12, by + 3, RED[1])
    c.put(14, by + 3, RED[1])
    # eyes
    for ex in (12, 14):
        c.put(ex, by - 4, RED[2] if pose != "idle" or phase % 2 == 0 else RED[1])
    c.put(13, by - 5, RED[2])
    if pose == "attack":
        c.put(12, by - 1, WHITE[2])
        c.put(14, by - 1, WHITE[2])
    c.outline(INK)
    return c


def spider_frames() -> dict[str, Canvas]:
    return {
        "idle.0": spider(0, "idle"),
        "idle.1": spider(1, "idle"),
        "move.0": spider(0, "walk"),
        "move.1": spider(1, "walk"),
        "windup.0": spider(0, "windup"),
        "attack.0": spider(1, "attack"),
        "hurt.0": spider(0, "idle"),
    }


# ── weapons (pointing right; the client rotates them) ─────────────────────
def sword(blade: list | None = None, guard: list | None = None) -> Canvas:  # noqa: ANN001
    b = blade or [STONE[2], STONE[3], STONE[4], STONE[5]]
    g = guard or [GOLD[1], GOLD[2]]
    c = Canvas(18, 7)
    for x in range(5, 17):
        c.put(x, 2, b[3] if x < 15 else b[2])
        c.put(x, 3, b[2])
        c.put(x, 4, b[0])
    c.put(17, 3, b[1])
    c.vline(4, 0, 6, g[1])
    c.vline(3, 1, 5, g[0])
    c.hline(0, 2, 3, WOOD[2])
    c.put(0, 2, WOOD[3])
    c.outline(INK)
    return c


def spear(blade: list | None = None, trim=None) -> Canvas:  # noqa: ANN001
    b = blade or [STONE[2], STONE[3], STONE[4], STONE[5]]
    c = Canvas(28, 7)
    c.hline(0, 20, 3, WOOD[3])
    c.hline(0, 20, 4, WOOD[1])
    for x in range(21, 27):
        w = 2 - abs(x - 23) // 2 if x < 25 else 0
        for y in range(3 - w, 4 + w + (x < 25)):
            c.put(x, y, b[2] if y <= 3 else b[0])
    c.put(27, 3, b[3])
    c.vline(20, 2, 5, trim or GOLD[2])
    c.outline(INK)
    return c


# ── FX ─────────────────────────────────────────────────────────────────────
def slash(frame: int, wide: bool = False) -> Canvas:
    """A crescent swoosh opening to the right; frames 0 (thin) → 2 (fading)."""
    size = 34 if wide else 28
    c = Canvas(size, size)
    cx = cy = size / 2
    r_out = size / 2 - 1
    thick = (3.2, 5.0, 3.6)[frame]
    span = math.radians((70, 120, 140)[frame] if not wide else (110, 180, 200)[frame])
    for y in range(size):
        for x in range(size):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            d = math.hypot(dx, dy)
            a = math.atan2(dy, dx)
            if abs(a) > span / 2 or not (r_out - thick <= d <= r_out):
                continue
            edge = abs(a) / (span / 2)
            t = (d - (r_out - thick)) / thick
            if frame == 2 and hash2(x, y, 300) < 0.45:
                continue
            col = WHITE[2] if t > 0.55 and edge < 0.7 else CREAM[3] if edge < 0.85 else STONE[4]
            c.put(x, y, col)
    return c


def hit(frame: int) -> Canvas:
    c = Canvas(16, 16)
    r = (3, 6, 7)[frame]
    for k in range(8):
        a = k / 8 * 2 * math.pi + (0.3 if frame == 1 else 0)
        ln = r if k % 2 == 0 else r * 0.55
        for s in range(int(ln) + 1):
            x, y = 8 + math.cos(a) * s, 8 + math.sin(a) * s
            col = WHITE[2] if s < ln * 0.5 else GOLD[3] if frame < 2 else FIRE[3]
            if frame == 2 and s < 2:
                continue
            c.put(int(x), int(y), col)
    if frame == 0:
        c.ellipse(8, 8, 2.5, 2.5, WHITE[2])
    return c


def poof(frame: int) -> Canvas:
    c = Canvas(24, 20)
    n = 5
    for k in range(n):
        a = k / n * 2 * math.pi + frame * 0.4
        d = 3 + frame * 2.2
        r = (3.6, 4.2, 3.4, 2.2)[frame]
        bx, by = 12 + math.cos(a) * d, 11 + math.sin(a) * d * 0.7 - frame
        blob(c, [(bx, by, r)], [STONE[2], STONE[3], STONE[4], STONE[5]], seed=k + frame * 10, dither=False)
    return c


def generate() -> dict[str, Canvas]:
    out: dict[str, Canvas] = {}
    for kind, frames in (("slime", slime_frames()), ("wolf", wolf_frames()), ("spider", spider_frames())):
        for name, cv in frames.items():
            out[f"mon.{kind}.{name}"] = cv
    out["mon.crown"] = crown()
    out["wpn.sword"] = sword()
    out["wpn.spear"] = spear()
    from artgen.icons import TIER_RAMPS, TIER_TRIM

    for t in range(5):
        out[f"wpn.sword.t{t + 1}"] = sword(TIER_RAMPS[t], [WOOD[2], TIER_TRIM[t]])
        out[f"wpn.spear.t{t + 1}"] = spear(TIER_RAMPS[t], TIER_TRIM[t])
    for i in range(3):
        out[f"fx.slash.{i}"] = slash(i)
        out[f"fx.slash_wide.{i}"] = slash(i, wide=True)
        out[f"fx.hit.{i}"] = hit(i)
    for i in range(4):
        out[f"fx.poof.{i}"] = poof(i)
    return out
