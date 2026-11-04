"""The shared step: golden vectors (the TS twin replays the same file) and behaviour checks."""

from __future__ import annotations

import json

import pytest

from hearthforge.settings import REPO_ROOT
from hearthforge.sim import motion as mo
from hearthforge.sim import rules as rl
from hearthforge.sim.rules import BTN_DODGE, BTN_HEAVY, BTN_LIGHT

pytestmark = pytest.mark.nodb

GOLDEN = json.loads((REPO_ROOT / "shared" / "golden" / "movement.json").read_text())


@pytest.fixture(scope="module")
def r(game_config) -> rl.Rules:  # noqa: ANN001
    return rl.resolve(game_config)


def open_world(walls: set[tuple[int, int]] | None = None) -> mo.Solid:
    walls = walls or set()
    return lambda x, y: (x, y) in walls


def fresh(x: float = 10.5, y: float = 10.5) -> mo.Motion:
    return mo.Motion(x=x, y=y, st=100.0, st_max=100.0)


def test_golden_vectors_replay_exactly() -> None:
    r = rl.rules_from_dict(GOLDEN["rules"])
    assert GOLDEN["fields"] == mo.MOTION_FIELDS
    for case in GOLDEN["cases"]:
        solid = {tuple(t) for t in case["solid"]}
        w = r.weapons[case["weapon"]]
        m = mo.Motion.from_list(case["start"])
        for i, (step, want) in enumerate(zip(case["steps"], case["expect"], strict=True)):
            if "kb" in step:
                m.kbx, m.kby = step["kb"]
            started = mo.step(m, *step["in"], r, w, lambda x, y, s=solid: (x, y) in s)
            assert [*m.to_list(), started] == want, f"{case['weapon']} diverged at step {i}"


def test_walls_stop_you_flush(r: rl.Rules) -> None:
    m = fresh(2.5, 2.5)
    wall = {(4, y) for y in range(0, 6)}
    for _ in range(20):
        mo.step(m, 127, 0, 0, 0, 0, r, r.weapons["sword"], open_world(wall))
    assert m.x == pytest.approx(4 - r.hw - r.skin)
    assert m.x + r.hw < 4


def test_diagonal_is_not_faster(r: rl.Rules) -> None:
    a, b = fresh(), fresh()
    for _ in range(10):
        mo.step(a, 127, 0, 0, 0, 0, r, r.weapons["sword"], open_world())
        mo.step(b, 127, 127, 0, 0, 0, r, r.weapons["sword"], open_world())
    da = a.x - 10.5
    db = ((b.x - 10.5) ** 2 + (b.y - 10.5) ** 2) ** 0.5
    assert db == pytest.approx(da, rel=1e-9)
    assert da == pytest.approx(10 * r.speed_tick)


def test_dodge_costs_stamina_and_covers_its_distance(r: rl.Rules, game_config) -> None:  # noqa: ANN001
    m = fresh()
    mo.step(m, 127, 0, 0, 0, BTN_DODGE, r, r.weapons["sword"], open_world())
    assert m.st == 100 - r.dodge_cost
    for _ in range(r.dodge_ticks - 1):
        mo.step(m, 127, 0, 0, 0, 0, r, r.weapons["sword"], open_world())
    assert m.x - 10.5 == pytest.approx(game_config.combat.dodge.distance)
    # cooldown: an immediate second dodge does nothing
    st = m.st
    mo.step(m, 127, 0, 0, 0, BTN_DODGE, r, r.weapons["sword"], open_world())
    assert m.dodge == 0 and m.st >= st


def test_sword_combo_cycles_then_resets(r: rl.Rules) -> None:
    w = r.weapons["sword"]
    m = fresh()
    seen = []
    for _ in range(80):
        started = mo.step(m, 0, 0, 127, 0, BTN_LIGHT, r, w, open_world())
        if started:
            seen.append(m.atk_i)
    assert seen[:4] == [0, 1, 2, 0]
    # wait out the combo window → the next swing is the opener again
    for _ in range(w.combo_window + w.light[0].length + 2):
        mo.step(m, 0, 0, 0, 0, 0, r, w, open_world())
    mo.step(m, 0, 0, 127, 0, BTN_LIGHT, r, w, open_world())
    assert m.atk_i == 0


def test_spear_heavy_lunges_along_the_aim(r: rl.Rules, game_config) -> None:  # noqa: ANN001
    w = r.weapons["spear"]
    m = fresh()
    mo.step(m, 0, 0, 0, 127, BTN_HEAVY, r, w, open_world())
    assert m.atk == rl.ATK_HEAVY and m.st == 100 - w.heavy.stamina
    for _ in range(w.heavy.length):
        mo.step(m, 0, 0, 0, 127, 0, r, w, open_world())
    assert m.y - 10.5 == pytest.approx(game_config.combat.weapons["spear"].heavy.dash)
    assert m.x == 10.5


def test_heavy_needs_stamina(r: rl.Rules) -> None:
    w = r.weapons["sword"]
    m = fresh()
    m.st = w.heavy.stamina - 1
    assert mo.step(m, 0, 0, 127, 0, BTN_HEAVY, r, w, open_world()) == rl.ATK_NONE
