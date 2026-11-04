"""Regenerate /shared/golden/movement.json from the Python sim (run after changing sim/motion.py on purpose).

    cd backend && uv run python scripts/gen_golden.py

Both pytest and vitest replay the file and require exact equality, so the TS predictor can't drift.
"""

from __future__ import annotations

import json
import random

from hearthforge.config.loader import load_config
from hearthforge.settings import REPO_ROOT
from hearthforge.sim import motion, rules
from hearthforge.sim.rules import BTN_ABILITY, BTN_DODGE, BTN_HEAVY, BTN_LIGHT

OUT = REPO_ROOT / "shared" / "golden" / "movement.json"


def arena() -> list[list[int]]:
    """A 24×16 room with walls, a pillar row and a gap: corners, sliding and squeezing all happen."""
    solid = [[x, y] for x in range(24) for y in (0, 15)] + [[x, y] for y in range(16) for x in (0, 23)]
    solid += [[x, 6] for x in range(4, 18) if x not in (10, 11)]
    solid += [[15, y] for y in range(9, 13)] + [[6, 11], [7, 11], [19, 3]]
    return solid


def script(seed: int, n: int) -> list[dict]:
    rnd = random.Random(seed)
    out: list[dict] = []
    mx = my = 0
    for t in range(n):
        if t % 9 == 0:
            mx, my = rnd.choice(
                [(127, 0), (-127, 0), (0, 127), (0, -127), (90, 90), (-90, 90), (60, -20), (0, 0)]
            )
        ax, ay = rnd.choice([(0, 0), (127, 0), (-64, 100), (30, -127)])
        b = 0
        roll = rnd.random()
        if roll < 0.05:
            b |= BTN_DODGE
        elif roll < 0.18:
            b |= BTN_LIGHT
        elif roll < 0.22:
            b |= BTN_HEAVY
        elif roll < 0.24:
            b |= BTN_ABILITY
        step: dict = {"in": [mx, my, ax, ay, b]}
        if t % 37 == 20:
            step["kb"] = [rnd.uniform(-0.4, 0.4), rnd.uniform(-0.4, 0.4)]
        out.append(step)
    return out


def run(case: dict, r: rules.Rules) -> list[list]:
    solid = {(x, y) for x, y in case["solid"]}
    w = r.weapons[case["weapon"]]
    m = motion.Motion.from_list(case["start"])
    states = []
    for st in case["steps"]:
        if "kb" in st:
            m.kbx, m.kby = st["kb"]
        started = motion.step(m, *st["in"], r, w, lambda x, y: (x, y) in solid)
        states.append([*m.to_list(), started])
    return states


def main() -> None:
    cfg = load_config(REPO_ROOT / "config")
    r = rules.resolve(cfg)
    cases = []
    for i, weapon in enumerate(["sword", "spear"]):
        start = motion.Motion(x=3.5, y=3.5, st=100.0, st_max=100.0).to_list()
        case = {"weapon": weapon, "solid": arena(), "start": start, "steps": script(100 + i, 400)}
        case["expect"] = run(case, r)
        cases.append(case)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"fields": motion.MOTION_FIELDS, "rules": r.bundle(), "cases": cases}))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
