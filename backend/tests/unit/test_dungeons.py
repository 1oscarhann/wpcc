"""Phase 12: delve layouts and the instance flow (rooms, doors, puzzles, chests, boss, portal, runs)."""

from __future__ import annotations

import itertools

import pytest

from hearthforge.domain import dungeon as dom
from hearthforge.realtime.protocol import EV
from hearthforge.sim.dungeon import DungeonSpace, Instance
from hearthforge.sim.room import Player, RealmRoom
from tests.unit.test_combat import add_player, make_room

pytestmark = pytest.mark.nodb


def test_layouts_are_deterministic_connected_and_well_formed() -> None:
    for s in range(30):
        seed = dom.seed_for("t", s)
        a, b = dom.generate(seed), dom.generate(seed)
        assert bytes(a.tiles) == bytes(b.tiles) and [r.kind for r in a.rooms] == [r.kind for r in b.rooms]
        kinds = [r.kind for r in a.rooms]
        assert kinds.count("entrance") == 1 and kinds.count("boss") == 1 and kinds.count("miniboss") == 1
        assert dom.reachable(a) == {r.id for r in a.rooms}
        boss = next(r for r in a.rooms if r.kind == "boss")
        assert boss.depth == max(r.depth for r in a.rooms)
        for d in a.doors:
            assert all(a.at(x, y) == dom.DOOR for x, y in d.tiles)
        for r in a.rooms:
            if r.kind == "puzzle":
                assert r.puzzle in ("plates", "levers")
    assert bytes(dom.generate(1).tiles) != bytes(dom.generate(2).tiles)


def enter_cave(room: RealmRoom) -> tuple[Player, Instance]:
    cave = next(q for q in room.grid.gen.pois if q.kind == "cave")
    p = add_player(room, cave.x + 0.5, cave.y + 1.6, level=20)
    room.interact(p, cave.index)
    inst = room.dungeons.of(p)
    assert inst is not None
    return p, inst


def goto(room: RealmRoom, p: Player, inst: Instance, r: dom.Room) -> None:
    p.m.x, p.m.y = inst.world(r.cx, r.cy)
    room.dungeons.tick(room.tick_no)


def test_entering_a_cave_puts_you_in_your_own_instance(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    room.combat._wake = lambda t: None  # type: ignore[method-assign]
    p, inst = enter_cave(room)
    assert p.dungeon == inst.id and p.m.x >= game_config.dungeons.space.x0
    assert any(e[0] == EV["DUNGEON_ENTER"] for e in p.ev)
    # walls are solid, the start tile isn't, and the wild map is untouched
    assert not room.grid.solid(int(p.m.x), int(p.m.y))
    assert room.grid.solid(inst.ox, inst.oy)  # the corner is void
    assert room.grid.solid(game_config.dungeons.space.x0 + 50 * game_config.dungeons.space.slot, 20)
    # a second player gets a different instance (no party), far enough away that they never meet
    p2, inst2 = enter_cave(room)
    assert inst2.id != inst.id and abs(inst2.ox - inst.ox) >= game_config.dungeons.space.slot
    # leaving puts you back at the cave
    room.dungeons.leave(p)
    assert p.dungeon == 0 and p.m.x < game_config.mapgen.map_size


def test_combat_room_locks_until_the_pack_is_dead(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    room.combat._wake = lambda t: None  # type: ignore[method-assign]
    p, inst = enter_cave(room)
    r = next(r for r in inst.layout.rooms if r.kind == "combat")
    goto(room, p, inst, r)
    assert r.id in inst.visited and set(r.doors) <= inst.locked
    d = inst.layout.doors[r.doors[0]]
    assert room.grid.solid(*map(int, inst.world(*d.tiles[0])))
    pack = [room.combat.monsters[i] for i in inst.pack[r.id]]
    assert len(pack) >= game_config.dungeons.combat.monsters[0] and all(m.dungeon == inst.id for m in pack)
    xp = p.xp
    for m in pack:
        room.combat._remove(m, killed=True)
    room.dungeons.tick(room.tick_no - room.tick_no % 5)
    assert r.id in inst.cleared and not set(r.doors) & inst.locked
    assert not room.grid.solid(*map(int, inst.world(*d.tiles[0])))
    assert p.xp > xp


def find_puzzle(game_config, kind: str) -> tuple[RealmRoom, Player, Instance, dom.Room]:  # noqa: ANN001
    for i in range(60):
        room = make_room(game_config)
        room.seed = 1000 + i  # each try reseeds the delve (the overworld stays the same)
        room.combat._wake = lambda t: None  # type: ignore[method-assign]
        p, inst = enter_cave(room)
        r = next((r for r in inst.layout.rooms if r.kind == "puzzle" and r.puzzle == kind), None)
        if r is not None:
            return room, p, inst, r
    raise AssertionError(f"no {kind} puzzle found")


def test_rune_plates_in_order_open_the_way(game_config) -> None:  # noqa: ANN001
    room, p, inst, r = find_puzzle(game_config, "plates")
    goto(room, p, inst, r)
    gates = {d.id for d in inst.layout.doors if d.gate and d.rooms[0] == r.id}
    assert gates <= inst.locked
    plates = sorted(
        (pr for pr in inst.layout.props if pr.kind == "plate" and pr.room == r.id), key=lambda q: q.data
    )
    # the wrong one first resets
    wrong = plates[1]
    p.m.x, p.m.y = inst.world(wrong.x + 0.5, wrong.y + 0.5)
    room.dungeons.tick(room.tick_no)
    assert not inst.plates_on
    for pr in plates:
        p.m.x, p.m.y = inst.world(pr.x + 0.5, pr.y + 0.5)
        room.dungeons.tick(room.tick_no)
    assert r.id in inst.solved and not gates & inst.locked


def test_levers_light_the_lamps(game_config) -> None:  # noqa: ANN001
    room, p, inst, r = find_puzzle(game_config, "levers")
    goto(room, p, inst, r)
    levers = [(i, pr) for i, pr in enumerate(inst.layout.props) if pr.kind == "lever" and pr.room == r.id]
    assert inst.lamps != 0b111
    for combo in itertools.product([0, 1], repeat=3):  # some subset of pulls solves it
        start = inst.lamps
        for k, pull in enumerate(combo):
            if pull and r.id not in inst.solved:
                i, pr = levers[k]
                p.m.x, p.m.y = inst.world(pr.x + 0.5, pr.y - 0.5)
                room.dungeons.use(p, i)
        if r.id in inst.solved:
            break
        # undo and try the next subset
        for k, pull in enumerate(combo):
            if pull:
                i, pr = levers[k]
                room.dungeons.use(p, i)
        assert inst.lamps == start
    assert r.id in inst.solved and inst.lamps == 0b111


def test_treasure_chest_once_per_player(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    room.combat._wake = lambda t: None  # type: ignore[method-assign]
    p, inst = enter_cave(room)
    i, pr = next((i, pr) for i, pr in enumerate(inst.layout.props) if pr.kind == "chest")
    p.m.x, p.m.y = inst.world(pr.x + 0.5, pr.y + 1.6)
    room.dungeons.use(p, i)
    n = len(room.drops)
    assert n >= 1 and any(d.key == "coins" for d in room.drops.values())
    room.dungeons.use(p, i)
    assert len(room.drops) == n


def test_boss_calls_adds_dies_opens_a_portal_and_records_the_run(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    room.combat._wake = lambda t: None  # type: ignore[method-assign]
    p, inst = enter_cave(room)
    r = next(r for r in inst.layout.rooms if r.kind == "boss")
    goto(room, p, inst, r)
    boss = room.combat.monsters[inst.boss_id]  # type: ignore[index]
    assert boss.boss and boss.key == game_config.dungeons.boss.enemy
    flags = {e[0]: e[10] for e in room.combat.entities(p, 0, 1e9, 0, 1e9)}
    assert flags[boss.id] & 64
    n0 = len(inst.pack[r.id])
    boss.hp = boss.hp_max * 0.5
    room.dungeons._boss(inst)
    assert len(inst.pack[r.id]) == n0 + game_config.dungeons.boss.adds and inst.boss_phase == 1
    boss.hp = boss.hp_max * 0.2
    room.dungeons._boss(inst)
    assert inst.enraged
    for mid in list(inst.pack[r.id]):
        m = room.combat.monsters.get(mid)
        if m is not None:
            room.combat._remove(m, killed=True)
    room.dungeons._check_packs(inst)
    assert inst.boss_dead and inst.clear_ms is not None
    assert room.dungeons.runs and room.dungeons.runs[0]["names"] == [p.name]
    assert any(d.key == "ancient_rune" for d in room.drops.values() if d.owner == p.eid)
    # step into the portal
    at = room.dungeons.portal_at(inst)
    assert at is not None
    p.m.x, p.m.y = at
    assert room.dungeons.try_portal(p) and p.dungeon == 0


def test_daily_delve_is_the_same_everywhere_and_ko_drops_you_out(game_config) -> None:  # noqa: ANN001
    layouts = []
    for seed in (5, 99):
        room = make_room(game_config)
        room.seed = seed
        room.combat._wake = lambda t: None  # type: ignore[method-assign]
        gate = next(q for q in room.grid.gen.pois if q.kind == "delve")
        p = add_player(room, gate.x + 0.5, gate.y + 1.6)
        room.interact(p, gate.index)
        inst = room.dungeons.of(p)
        assert inst is not None and inst.kind == "daily"
        layouts.append(bytes(inst.layout.tiles))
        p.ko = 5
        room.respawn(p)
        assert p.dungeon == 0 and inst.deaths == 1
    assert layouts[0] == layouts[1]


def test_wild_spawner_ignores_players_in_delves(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    p, inst = enter_cave(room)
    before = set(room.combat.monsters)
    room.combat._wake(room.tick_no)
    assert set(room.combat.monsters) == before
    assert isinstance(room.dungeons, DungeonSpace)
