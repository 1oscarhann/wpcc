"""Phase 13: the five realm bosses, the village guard and the raider's sack.

Bosses are big (48–64 px) so they read as bosses at 16 px tiles. Each has the same frame set as the
bestiary (idle ×2, move ×4, windup, attack, hurt) so the client animates them like any monster.
"""

from __future__ import annotations

import math
from typing import Any

from artgen.bestiary import (
    VIOLET,
    BipedSpec,
    BlobSpec,
    _h,
    _o,
    _s,
    biped,
    blob_frame,
    ell,
    warden,
)
from artgen.canvas import Canvas, hash2
from artgen.palette import INK, ramp

GOLD = ramp("gold")
STONE = ramp("stone")
FIRE = ramp("fire")
LAVA = ramp("lava")
ICE = ramp("ice")
SNOW = ramp("snow")
GRASS = ramp("grass")
BOG = ramp("bog")
OBS = ramp("obsidian")
ASH = ramp("ash")
WHITE = ramp("flower_white")
VENOM = ramp("venom")
SAND = ramp("sand")
CLOTH = ramp("cloth_cream")
WOOD = ramp("wood")
Frames = dict[str, Canvas]


def _swap(c: Canvas, mapping: dict[tuple[int, int, int, int], Any]) -> Canvas:
    for y in range(c.h):
        for x in range(c.w):
            col = tuple(c.get(x, y))
            if col in mapping:
                c.put(x, y, mapping[col])
    return c


def _set(frames_fn: Any) -> Frames:
    return {
        "idle.0": frames_fn(0, "idle"),
        "idle.1": frames_fn(2, "idle"),
        **{f"move.{i}": frames_fn(i, "walk") for i in range(4)},
        "windup.0": frames_fn(0, "windup"),
        "attack.0": frames_fn(0, "attack"),
        "hurt.0": frames_fn(1, "hurt"),
    }


# ── Grubmaw the Slime King: a vast slime wearing a crown ─────────────────────
def grubmaw(phase: int, pose: str) -> Canvas:
    s = BlobSpec(56, 48, 24, 17, ramp("grass"), eye=INK)
    sx, sy, lift = {
        "idle": (1.0 + 0.04 * (phase % 2), 1.0 - 0.04 * (phase % 2), 0),
        "walk": ((0.92, 1.08, 2), (1.0, 1.0, 0), (1.08, 0.92, 0), (1.0, 1.0, 1))[phase % 4],
        "windup": (1.18, 0.74, 0),
        "attack": (0.86, 1.16, 4),
        "hurt": (1.12, 0.86, 0),
    }[pose]
    pose_b = {"walk": "move", "idle": "idle"}.get(pose, pose)
    c = blob_frame(s, sx, sy, lift=lift, pose=pose_b, phase=phase)
    # a mouthful of jelly-teeth grin
    cy = int(c.h - 2.5 - s.ry * sy - lift)
    for x in range(int(c.w / 2 - 7), int(c.w / 2 + 6)):
        c.put(x, cy + 5, INK if pose in ("windup", "attack") else GRASS[0])
    # the crown
    top = next((y for y in range(c.h) if any(c.filled(x, y) for x in range(c.w))), 4)
    cx = c.w // 2
    base = top + 2
    for x in range(cx - 7, cx + 8):
        c.put(x, base, GOLD[2])
        c.put(x, base + 1, GOLD[1])
    for k, dx in enumerate((-7, -3, 1, 5)):
        h = 4 if k in (1, 2) else 3
        for y in range(base - h, base):
            c.put(cx + dx, y, GOLD[3] if y > base - h else GOLD[4])
            c.put(cx + dx + 1, y, GOLD[2])
    c.put(cx - 1, base, ramp("roof_red")[3])
    c.put(cx + 3, base, ramp("water")[3])
    c.outline(INK)
    return c


# ── The Stone Colossus: the warden's big brother, with a molten core ─────────
def colossus(phase: int, pose: str) -> Canvas:
    c = warden(phase, pose)
    mapping = {OBS[i]: STONE[min(5, i + 1)] for i in range(4)}
    mapping.update({VIOLET[0]: LAVA[2], VIOLET[1]: FIRE[3], VIOLET[2]: GOLD[4]})
    _swap(c, mapping)
    big = Canvas(64, 62)
    big.img.paste(c.img.resize((60, 62), 0), (2, 0))  # a touch broader than the warden
    big.px = big.img.load()
    return big


# ── The Cinder Tyrant: an obsidian brute veined with lava, horned ────────────
def tyrant(phase: int, pose: str) -> Canvas:
    c = warden(phase, pose)
    mapping = {OBS[0]: ASH[0], OBS[1]: ASH[1], OBS[2]: OBS[1], OBS[3]: OBS[2]}
    mapping.update({VIOLET[0]: LAVA[1], VIOLET[1]: LAVA[3], VIOLET[2]: FIRE[4]})
    mapping.update({STONE[0]: ASH[1], STONE[1]: ASH[2], STONE[2]: ASH[3], STONE[3]: ASH[4], STONE[4]: LAVA[3]})
    _swap(c, mapping)
    # lava cracks over the chest and horns on the head
    for i in range(7):
        x = 20 + int(hash2(i, phase, 811) * 12)
        y = 24 + int(hash2(i, 3, 812) * 12)
        if c.filled(x, y):
            c.put(x, y, LAVA[3])
    top = next((y for y in range(c.h) if any(c.filled(x, y) for x in range(20, 32))), 8)
    for side in (-1, 1):
        hx = 26 + side * 6
        for k in range(5):
            c.put(hx + side * (k // 2), top - k + 1, SAND[2] if k < 3 else SAND[3])
            c.put(hx + side * (k // 2) + side, top - k + 2, SAND[1])
    c.outline(INK)
    return c


# ── The Swamp Hydra: a mossy hulk with three snapping heads ─────────────────
def hydra(phase: int, pose: str) -> Canvas:
    c = Canvas(64, 56)
    cx, base = 32, 52
    c.drop_shadow(cx, 53, 22, 2.5)
    bob = (0, 1, 0, -1)[phase % 4] if pose == "walk" else 0
    ell(c, cx, base - 10 + bob, 20, 11, BOG, flat_bottom=1.4)
    for x in range(cx - 16, cx + 17, 3):  # moss along the back
        top = min((y for y in range(c.h) if c.filled(x, y)), default=base)
        c.put(x, top, GRASS[2])
        c.put(x, top - 1, GRASS[3] if hash2(x, 2, 821) < 0.5 else GRASS[2])
    rear = -6 if pose == "windup" else 5 if pose == "attack" else 0
    sway = math.sin(phase * 1.57) * 1.5 if pose in ("idle", "walk") else 0
    heads = [(-17, 16), (0, 8), (17, 16)]
    for k, (dx, hy) in enumerate(heads):
        x0, y0 = cx + dx * 0.45, base - 16 + bob
        hx = cx + dx + (sway if k != 1 else -sway)
        hy2 = hy + rear + (2 if pose == "hurt" else 0)
        steps = 12
        for i in range(steps + 1):
            t = i / steps
            x = x0 + (hx - x0) * t + math.sin(t * math.pi) * dx * 0.15
            y = y0 + (hy2 + 6 - y0) * t
            r = 3.2 - t * 1.0
            ell(c, x, y, r, r, BOG[1:])
        # the head: a long snout with eyes and a jaw
        ell(c, hx, hy2 + 3, 5.5, 4.2, BOG[1:])
        snout = -1 if dx < 0 else 1 if dx > 0 else 0
        ell(c, hx + snout * 3, hy2 + 5, 4, 2.6, BOG[1:])
        for ex in (-2, 2):
            c.put(int(hx + ex), int(hy2 + 2), GOLD[3])
        if pose in ("windup", "attack"):
            c.hline(int(hx - 3 + snout * 3), int(hx + 3 + snout * 3), int(hy2 + 7), INK)
            c.put(int(hx + snout * 3), int(hy2 + 8), VENOM[2])
            c.put(int(hx - 2 + snout * 3), int(hy2 + 7), WHITE[1])
            c.put(int(hx + 2 + snout * 3), int(hy2 + 7), WHITE[1])
    c.outline(INK)
    return c


# ── The Frost Matriarch: a tall ice queen with a tiara and a long cloak ──────
def matriarch(phase: int, pose: str) -> Canvas:
    s = BipedSpec(ICE[1:] + [WHITE[2]], SNOW[0:4], w=52, h=66, scale=2.6, wide=0.9, head="plain",
                  held="staff", eye=_o("navy")[1], hair=_h("platinum"), accent=ICE)
    c = biped(s, phase, {"walk": "walk"}.get(pose, pose))
    cx = c.w // 2
    feet = c.h - 3
    # a long robe over the legs, flaring to the ground (it sways a little as she glides)
    hip = feet - 16
    sway = (0, 1, 0, -1)[phase % 4] if pose == "walk" else 0
    for y in range(hip, feet + 1):
        t = (y - hip) / (feet - hip)
        half = int(6 + t * 9)
        off = int(sway * t)
        for x in range(cx - half + off, cx + half + 1 + off):
            u = (x - (cx - half + off)) / (2 * half)
            col = SNOW[3] if u < 0.25 else SNOW[2] if u < 0.6 else SNOW[1]
            if y == feet:
                col = ICE[1]
            elif (x + y) % 7 == 0 and t > 0.5:
                col = ICE[2]
            c.put(x, y, col)
    # a tiara of ice points
    top = next((y for y in range(c.h) if any(c.filled(x, y) for x in range(cx - 5, cx + 6))), 6)
    for dx, h in ((-4, 3), (-2, 4), (0, 6), (2, 4), (4, 3)):
        for k in range(h):
            c.put(cx + dx, top - k, ICE[3] if k < h - 1 else WHITE[2])
    c.put(cx, top + 1, GOLD[3])
    c.outline(INK)
    return c


def guard(phase: int, pose: str) -> Canvas:
    """A village guard: blue tabard, spear, a steel cap."""
    s = BipedSpec(_s("honey"), _o("navy"), head="plain", held="staff", hair=_h("chestnut"), accent=GOLD)
    c = biped(s, phase, {"walk": "walk"}.get(pose, pose))
    cx = c.w // 2
    top = next((y for y in range(c.h) if any(c.filled(x, y) for x in range(cx - 4, cx + 5))), 4)
    for y in range(top, top + 3):
        for x in range(cx - 4, cx + 5):
            if c.filled(x, y) and tuple(c.get(x, y)) != tuple(INK):
                c.put(x, y, STONE[4] if y == top else STONE[3] if x < cx else STONE[2])
    c.hline(cx - 4, cx + 4, top + 3, STONE[1])
    return c


def sack() -> Canvas:
    c = Canvas(12, 12)
    ell(c, 6, 7.5, 4.5, 4, CLOTH[1:])
    c.rect(4, 2, 4, 2, CLOTH[2])
    c.hline(4, 7, 4, WOOD[1])
    c.put(5, 7, WOOD[2])
    c.put(7, 8, WOOD[2])
    c.outline(INK)
    return c


def generate() -> dict[str, Canvas]:
    out: dict[str, Canvas] = {}
    for key, fn in (
        ("grubmaw", grubmaw),
        ("stone_colossus", colossus),
        ("swamp_hydra", hydra),
        ("frost_matriarch", matriarch),
        ("cinder_tyrant", tyrant),
        ("guard", guard),
    ):
        for name, cv in _set(fn).items():
            out[f"mon.{key}.{name}"] = cv
    out["fx.sack"] = sack()
    return out
