"""Phase 13: monster waves in the room (march, guards, towers, theft) without a database."""

from __future__ import annotations

from typing import Any

import pytest

from hearthforge.domain import mapgen
from hearthforge.realtime.protocol import EV
from hearthforge.services import plots
from hearthforge.sim.room import RealmRoom
from tests.unit.test_combat import add_player, make_room

pytestmark = pytest.mark.nodb

OWNER = "00000000-0000-0000-0000-0000000000aa"


def village(
    cfg: Any, extra: list[dict[str, Any]] | None = None, villagers: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    origin = mapgen.layout(cfg.mapgen).plot_origins[0]
    b = [
        {"id": "th", "key": "town_hall", "x": 22, "y": 19, "rotation": 0, "level": 2, "state": "active"},
        {"id": "sh", "key": "storehouse", "x": 28, "y": 20, "rotation": 0, "level": 1, "state": "active"},
        *(extra or []),
    ]
    out = {
        "owner_id": OWNER,
        "origin": list(origin),
        "frame": cfg.mapgen.plot.frame,
        "size": 32,
        "buildings": b,
        "debris": [],
        "gate": list(plots.gate(cfg, 0)),
    }
    if villagers is not None:
        out["villagers"] = villagers
    return out


def run(room: RealmRoom, max_ticks: int = 20 * 60 * 7) -> dict[str, Any]:
    for _ in range(max_ticks):
        room.tick()
        if room.defence.results:
            return room.defence.results[0]
    raise AssertionError("the wave never ended")


def setup(cfg: Any, **kw: Any) -> RealmRoom:
    room = make_room(cfg)
    room.combat._wake = lambda t: None  # type: ignore[method-assign]
    room.set_villages({OWNER: village(cfg, **kw)}, {0})
    return room


def test_an_undefended_village_gets_raided(game_config) -> None:  # noqa: ANN001
    room = setup(game_config)
    assert room.defence.start("w1", OWNER, 2) is None
    assert room.defence.start("w2", OWNER, 2) == "already_running"
    res = run(room)
    comp = game_config.waves.composition[2]
    assert res["spawned"] == comp.subwaves * comp.size
    # nobody stood in the way: every one of them walked in through the gate and reached the storehouse
    assert res["through"] == res["spawned"] and res["killed"] == 0
    assert res["through_frac"] == 1.0 and not res["won"]
    assert not room.defence.busy() and not room.combat.monsters


def test_guards_and_towers_hold_the_line(game_config) -> None:  # noqa: ANN001
    extra = [
        {"id": "gp", "key": "guard_post", "x": 30, "y": 25, "rotation": 0, "level": 5, "state": "active"},
        {"id": "w1", "key": "watchtower", "x": 26, "y": 25, "rotation": 0, "level": 5, "state": "active"},
        {"id": "w2", "key": "watchtower", "x": 33, "y": 22, "rotation": 0, "level": 5, "state": "active"},
    ]
    room = setup(game_config, extra=extra)
    assert room.defence.start("w1", OWNER, 2) is None
    r = room.defence.runs[OWNER]
    assert r.guards_total == game_config.buildings["guard_post"].cfg.jobs[4]  # no villagers yet: every slot
    assert len(r.towers) == 2
    res = run(room)
    assert res["killed"] > 0 and res["killed"] + res["through"] <= res["spawned"]


def test_guards_are_the_villagers_posted_there(game_config) -> None:  # noqa: ANN001
    extra = [
        {"id": "gp", "key": "guard_post", "x": 30, "y": 25, "rotation": 0, "level": 3, "state": "active"}
    ]
    vs = [{"id": "v1", "name": "Bertha", "job": "gp"}, {"id": "v2", "name": "Odo", "job": None}]
    room = setup(game_config, extra=extra, villagers=vs)
    room.defence.start("w1", OWNER, 2)
    guards = list(room.defence.runs[OWNER].guards.values())
    assert [g.name for g in guards] == ["Bertha"]
    lv3 = 1 + game_config.waves.guards.per_level * 2
    assert guards[0].hp_max == pytest.approx(game_config.waves.guards.hp * lv3)
    # guards show up on the wire as friendly monster entities
    p = add_player(room, guards[0].x, guards[0].y + 1)
    ents = room.combat.entities(p, p.m.x - 10, p.m.x + 10, p.m.y - 10, p.m.y + 10)
    g = next(e for e in ents if e[2] == "guard")
    assert g[10] & 128


def test_players_fight_raiders_for_xp_but_no_loot(game_config) -> None:  # noqa: ANN001
    room = setup(game_config)
    room.defence.start("w1", OWNER, 2)
    for _ in range(80):
        room.tick()
    m = next(iter(room.combat.monsters.values()))
    assert m.wave == OWNER
    p = add_player(room, m.x, m.y + 1, level=10)
    p.user_id = __import__("uuid").UUID(OWNER)
    xp = p.xp
    m.damagers[p.eid] = m.hp_max
    room.combat._kill(m, p)
    assert p.xp > xp and not room.drops  # no loot from raiders
    assert room.defence.runs[OWNER].killed == 1


def test_defend_hops_you_home_only_when_a_wave_is_on(game_config) -> None:  # noqa: ANN001
    room = setup(game_config)
    p = add_player(room, 10.5, 10.5)
    p.user_id = __import__("uuid").UUID(OWNER)
    room.by_user[p.user_id] = p
    assert room.go_home(p) == "no_wave"
    room.defence.start("w1", OWNER, 2)
    assert room.go_home(p) is None
    st = room.villages[OWNER]
    ox, oy = st["origin"]
    assert ox <= p.m.x <= ox + st["frame"] and oy <= p.m.y <= oy + st["frame"]
    assert any(e[0] == EV["TELEPORT"] for e in p.ev)
