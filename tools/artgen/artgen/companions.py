"""Phase 16b: pets (small enough to trot at your heels) and mounts (big enough to ride).

Pets and mounts reuse the bestiary body plans: side views facing left, frames idle.0/1 and
move.0..3 (the slime and owl have two move frames). Names: pet.<key>.<frame>, mount.<key>.<frame>.
"""

from __future__ import annotations

from artgen.bestiary import BlobSpec, QuadSpec, blob_frames, ell, quad
from artgen.canvas import Canvas
from artgen.palette import INK, ramp

GOLD = ramp("gold")
WHITE = ramp("flower_white")


def _quad_frames(s: QuadSpec) -> dict[str, Canvas]:
    return {
        "idle.0": quad(s, 0, "idle"),
        "idle.1": quad(s, 1, "idle"),
        **{f"move.{i}": quad(s, i, "run") for i in range(4)},
    }


def owl(phase: int, pose: str) -> Canvas:
    """A round little owl: big eyes, ear tufts, wings that flap when it follows you."""
    c = Canvas(16, 18)
    lift = 3 if pose == "move" and phase % 2 else 1 if pose == "move" else 0
    bob = 1 if pose == "idle" and phase else 0
    c.drop_shadow(8, 16, 4, 1.4, alpha=60 if lift else 80)
    body = ramp("wood")[1:5]
    cy = 10 - lift + bob
    ell(c, 8, cy, 4.6, 5.2, body)
    ell(c, 8, cy + 1.5, 2.8, 3.2, ramp("cloth_cream"))
    for x, y in ((4, cy - 5), (12, cy - 5)):  # ear tufts
        c.put(x, int(y), body[2])
        c.put(x + (1 if x < 8 else -1), int(y) + 1, body[2])
    for ex in (6, 10):  # big round eyes
        c.put(ex - 1, int(cy) - 2, WHITE[2])
        c.put(ex, int(cy) - 2, WHITE[2])
        c.put(ex - 1, int(cy) - 1, WHITE[2])
        c.put(ex, int(cy) - 1, INK if pose != "idle" or phase == 0 else WHITE[1])
    c.put(8, int(cy), GOLD[2])  # beak
    if pose == "move":  # wings out
        wy = int(cy) - (1 if phase % 2 else -1)
        for k in range(3):
            c.put(2 - k // 2, wy + k, body[1])
            c.put(14 + k // 2, wy + k, body[1])
    c.put(7, 15 - lift + bob, GOLD[1])
    c.put(9, 15 - lift + bob, GOLD[1])
    c.outline(INK)
    return c


def pets() -> dict[str, dict[str, Canvas]]:
    fox = QuadSpec(ramp("pumpkin"), ramp("cloth_cream"), head="wolf", w=20, h=16, length=9, depth=4, leg=3, tail="up")
    pup = QuadSpec(ramp("snow")[0:4] + [WHITE[2]], ramp("snow"), head="wolf", w=20, h=16, length=8, depth=4, leg=3,
                   tail="up", eye=ramp("ice")[0], extra="frost")
    sal = QuadSpec(ramp("fire")[0:4], ramp("lava")[2:], head="croc", w=22, h=12, length=9, depth=3, leg=2,
                   tail="long", eye=GOLD[3])
    slime = blob_frames(BlobSpec(14, 12, 4.6, 3.6, ramp("grass")[1:]))
    return {
        "fox": _quad_frames(fox),
        "frost_pup": _quad_frames(pup),
        "salamander": _quad_frames(sal),
        "slime": {k: v for k, v in slime.items() if k.split(".")[0] in ("idle", "move")},
        "owl": {"idle.0": owl(0, "idle"), "idle.1": owl(1, "idle"), "move.0": owl(0, "move"), "move.1": owl(1, "move")},
    }


def mounts() -> dict[str, dict[str, Canvas]]:
    horse = QuadSpec(ramp("wood")[1:5], ramp("dirt"), head="horse", w=34, h=28, length=17, depth=6, leg=8,
                     tail="long", horn=ramp("wood")[0:3], eye=INK)
    ram = QuadSpec(ramp("cloth_cream"), ramp("flower_white"), head="goat", w=30, h=24, length=14, depth=6, leg=6,
                   tail="stub", horn=ramp("sand"))
    return {"horse": _quad_frames(horse), "ram": _quad_frames(ram)}


def generate() -> dict[str, Canvas]:
    out: dict[str, Canvas] = {}
    for kind, frames in pets().items():
        for name, cv in frames.items():
            out[f"pet.{kind}.{name}"] = cv
    for kind, frames in mounts().items():
        for name, cv in frames.items():
            out[f"mount.{kind}.{name}"] = cv
    return out
