"""Phase 10 monsters: night scaling, fog aggro, storm spawns, kiters, summoners, roots, splitting slimes,
and night-only gathering."""

from __future__ import annotations

from datetime import timedelta

import pytest

from hearthforge.sim.combat import Combat
from hearthforge.sim.room import RealmRoom
from tests.unit.test_combat import add_player, make_room, open_area, press, quiet, spawn

pytestmark = pytest.mark.nodb


def world(room: RealmRoom, night: bool, weather: str = "clear") -> Combat:
    room.world_now = lambda: (night, weather)  # type: ignore[method-assign]
    c: Combat = room.combat
    c._world(room.tick_no)
    return c


def test_night_spawns_are_tougher_and_flagged(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    day = spawn(room, "slime", x, y)
    world(room, night=True)
    night = spawn(room, "slime", x + 2, y)
    wc = game_config.world_clock.night
    assert night.hp_max == round(day.hp_max * wc.hp)
    assert night.dmg == pytest.approx(day.dmg * wc.dmg)
    p = add_player(room, x, y + 2)
    flags = {e[0]: e[10] for e in room.combat.entities(p, 0, 1e9, 0, 1e9)}
    assert flags[night.id] & 16 and not flags[day.id] & 16


def test_night_only_groups_wake_after_dark_and_fade_at_dawn(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    c = world(room, night=False)
    cs = room.grid.cs
    n = room.grid.size // cs
    # find a chunk that has a night-only spawn point
    for cy in range(n):
        for cx in range(n):
            pts = [c.spawns[s] for s in c._chunk_points(cx, cy)]
            night_pts = [sp for sp in pts if sp.night_only]
            if night_pts:
                break
        else:
            continue
        break
    sp = night_pts[0]
    add_player(room, sp.x, sp.y + 30)  # near enough to wake it, far enough not to aggro
    c._wake(room.tick_no)
    assert not sp.alive
    world(room, night=True)
    c._wake(room.tick_no)
    assert sp.alive
    world(room, night=False)  # dawn
    assert not sp.alive


def test_fog_shrinks_aggro(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    c = world(room, night=False, weather="fog")
    assert c.aggro == pytest.approx(game_config.enemies.aggro_radius * 0.7)
    m = spawn(room, "slime", x, y)
    add_player(room, x + c.aggro + 0.6, y)  # inside clear-weather aggro, outside fog aggro
    for _ in range(8):
        room.tick()
    assert m.state in ("idle", "return")


def test_storms_bring_storm_elementals(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    c = world(room, night=False, weather="storm")
    x, y = open_area(room)
    add_player(room, x, y)
    c._wake(room.tick_no)
    storm = [m for m in c.monsters.values() if m.key == "storm_elemental"]
    assert storm, "a storm near a player should call at least one Storm Elemental"
    c.block += 1  # the storm block ends
    world(room, night=False, weather="clear")
    assert not [m for m in c.monsters.values() if m.key == "storm_elemental" and m.state == "idle"]


def test_kiter_shoots_along_the_telegraph_and_dodging_passes_through(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room, "forest")
    p = add_player(room, x, y, level=5)
    k = spawn(room, "bandit_archer", x + 5.5, y, biome="forest")
    k.state, k.target = "chase", p.eid
    hp0 = p.hp
    shot_seen = False
    for _ in range(60):
        press(room, p, 1)
        shot_seen |= bool(room.combat.shots)
        if p.hp < hp0:
            break
    assert shot_seen and p.hp < hp0
    # same again, but dodge as the shot arrives
    p.hp = hp0
    k.state, k.st_t = "chase", 0
    dodged = False
    for _ in range(80):
        s = next(iter(room.combat.shots.values()), None)
        close = s is not None and abs(s.x - p.m.x) < 1.6
        press(room, p, 1, b=8 if close and not dodged else 0)
        dodged |= close
        if dodged and not room.combat.shots:
            break
    assert dodged and p.hp == hp0


def test_kiter_backs_off_when_you_close_in(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room, "forest")
    p = add_player(room, x, y)
    k = spawn(room, "bandit_archer", x + 1.5, y, biome="forest")
    k.state, k.target = "chase", p.eid
    for _ in range(10):
        press(room, p, 1)
    assert k.x > x + 1.6


def test_summoner_calls_minions_roots_you_and_takes_them_along(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room, "forest")
    p = add_player(room, x, y, level=8)
    s = spawn(room, "sapling", x + 4.5, y, biome="forest")
    s.state, s.target, s.next_summon = "chase", p.eid, room.tick_no + 1
    rooted = False
    for _ in range(120):
        press(room, p, 1)
        rooted |= p.rooted > 0
    minions = [m for m in room.combat.monsters.values() if m.minion_of == s.id]
    assert minions and len(minions) <= game_config.enemies.enemies["sapling"].summon.max_alive
    assert rooted
    # rooted means no walking
    p.rooted = 40
    x0 = p.m.x
    press(room, p, 5, mx=127)
    assert p.m.x == pytest.approx(x0, abs=0.05)
    p.rooted = 0
    # kill the summoner: its minions go too, and they never drop loot
    s.hp = 1
    s.state = "recover"
    room.combat.hit_monster(p, s, room.rules.weapons["sword"].light[0], s.x, s.y)
    assert not [m for m in room.combat.monsters.values() if m.minion_of == s.id]


def test_big_slime_splits_into_two(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = add_player(room, x, y)
    b = spawn(room, "big_slime", x + 1.2, y)
    b.hp = 1
    b.state = "recover"
    room.combat.hit_monster(p, b, room.rules.weapons["sword"].light[0], b.x, b.y)
    kids = [m for m in room.combat.monsters.values() if m.key == "slime"]
    assert len(kids) == 2 and all(k.state == "chase" and k.target == p.eid for k in kids)


def test_night_loot_is_richer(game_config) -> None:  # noqa: ANN001
    totals = []
    for night in (False, True):
        room = make_room(game_config)
        quiet(room)
        world(room, night=night)
        x, y = open_area(room)
        p = add_player(room, x, y)
        n = 0
        for _ in range(150):
            m = spawn(room, "slime", x + 1, y)
            m.hp, m.state = 1, "recover"
            room.combat.hit_monster(p, m, room.rules.weapons["sword"].light[0], m.x, m.y)
        n = sum(d.qty for d in room.drops.values() if d.key == "slime_gel")
        totals.append(n)
    assert totals[1] > totals[0] * 1.25


def test_moonpetals_only_open_at_night(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    # find a moonpetal anywhere on the map
    g = room.grid
    found = None
    for cy in range(g.size // g.cs):
        for cx in range(g.size // g.cs):
            ch = g.gen.chunk(cx, cy)
            for lx, ly, _oid, _v in ch["objects"]:
                tx, ty = cx * g.cs + lx, cy * g.cs + ly
                if g.node_at(tx, ty) == "moonpetal":
                    found = (tx, ty)
                    break
            if found:
                break
        if found:
            break
    assert found, "mapgen should place some moonpetals"
    tx, ty = found
    p = add_player(room, tx + 0.5 - 0.9, ty + 0.5)
    p.m.ax, p.m.ay = 1.0, 0.0
    mv = room.rules.weapons["sword"].light[0]
    room.world_now = lambda: (False, "clear")  # type: ignore[method-assign]
    room.gather(p, mv)
    assert not [d for d in room.drops.values() if d.key == "moonpetal"]
    room.world_now = lambda: (True, "clear")  # type: ignore[method-assign]
    room.gather(p, mv)
    assert [d for d in room.drops.values() if d.key == "moonpetal"]
    _ = timedelta
