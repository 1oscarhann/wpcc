"""Combat inside a RealmRoom, driven tick by tick without a database or sockets."""

from __future__ import annotations

import random
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from hearthforge.sim import motion as mo
from hearthforge.sim.combat import Combat, Monster, SpawnPoint
from hearthforge.sim.room import Input, Player, RealmRoom
from hearthforge.sim.rules import BTN_DODGE, BTN_LIGHT
from hearthforge.sim.stats import stats_for

pytestmark = pytest.mark.nodb


class FakeConn:
    async def send_bytes(self, data: bytes) -> None:  # pragma: no cover - never awaited here
        return None


def make_room(cfg: Any) -> RealmRoom:
    st = SimpleNamespace(config=cfg, village_hub=None, rooms=None)
    room = RealmRoom(st, uuid.uuid4(), seed=5)  # type: ignore[arg-type]
    room.set_villages({}, set())
    room.combat = Combat(room)
    room.rng = random.Random(1)
    return room


def open_area(room: RealmRoom, biome: str = "meadow") -> tuple[float, float]:
    """The centre of an open 7×7 patch in the given biome."""
    g = room.grid
    c = room.cfg.mapgen.map_size // 2
    r0 = 60 if biome == "meadow" else room.cfg.mapgen.forest.radius + 15
    for r in range(r0, r0 + 60, 3):
        for k in range(0, 360, 7):
            import math

            x = int(c + r * math.cos(math.radians(k)))
            y = int(c + r * math.sin(math.radians(k)))
            if g.gen.biome(x, y) != biome:
                continue
            if all(not g.solid(x + i, y + j) for i in range(-3, 4) for j in range(-3, 4)):
                return x + 0.5, y + 0.5
    raise AssertionError("no open area")


def add_player(room: RealmRoom, x: float, y: float, level: int = 1) -> Player:
    st = stats_for(room.cfg, level)
    p = Player(
        eid=room.new_id(),
        user_id=uuid.uuid4(),
        name="P",
        appearance={},
        conn=FakeConn(),  # type: ignore[arg-type]
        m=mo.Motion(x=x, y=y, st=st.st_max, st_max=st.st_max),
        level=level,
        xp=0,
        hp=float(st.hp_max),
        stats=st,
        weapon={"key": "training_sword", "type": "sword", "tier": 1, "rarity": "common"},
        quick={4: ["small_healing_potion", 3]},
        inv=[],
        inv_cap=24,
        home_rect=(0, 0, 1, 1),
        home_door=(x, y),
    )
    p.stats = SimpleNamespace(**{**st.__dict__, "crit": 0.0})  # type: ignore[assignment]
    room.players[p.eid] = p
    room.by_user[p.user_id] = p
    return p


def spawn(
    room: RealmRoom, key: str, x: float, y: float, elite: bool = False, biome: str = "meadow"
) -> Monster:
    combat: Combat = room.combat
    sp = SpawnPoint(id=len(combat.spawns) + 1000, x=x, y=y, biome=biome, enemy=key, elite=elite, count=1)
    combat.spawns[sp.id] = sp
    combat._spawn(sp, room.tick_no)
    m = combat.monsters[next(iter(sp.alive))]
    m.x, m.y = x, y
    m.history.clear()
    return m


def press(
    room: RealmRoom, p: Player, ticks: int, mx: int = 0, my: int = 0, ax: int = 0, ay: int = 0, b: int = 0
) -> None:
    for _ in range(ticks):
        p.last_seq += 1
        p.inputs.append(Input(p.last_seq, p.last_seq, room.tick_no, mx, my, ax, ay, b))
        room.tick()


def quiet(room: RealmRoom) -> None:
    """No natural spawns: tests place their own monsters."""
    room.combat._wake = lambda t: None  # type: ignore[method-assign]


def test_starter_sword_deals_the_balance_numbers_and_slimes_die_in_two(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = add_player(room, x, y)
    m = spawn(room, "slime", x + 1.2, y)
    m.state = "recover"  # stand still for the test
    dmg, crit = room.combat.damage_out(p, room.rules.weapons["sword"].light[0], m)
    assert (dmg, crit) == (12, False)  # 10 × (1 + 10 × 0.02), slime has no defence
    swings = 0
    while m.id in room.combat.monsters and swings < 6:
        press(room, p, 1, ax=127, b=BTN_LIGHT)
        press(room, p, room.rules.weapons["sword"].light[0].length)
        swings += 1
    assert m.id not in room.combat.monsters
    assert swings == 2  # "feel powerful" (BALANCE §6.3)
    # loot and XP for the killer
    assert any(d.owner == p.eid for d in room.drops.values())
    assert p.xp == game_config.enemies.biomes["meadow"].xp


def test_every_helper_gets_their_own_loot(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    a = add_player(room, x - 1, y)
    b = add_player(room, x + 1, y)
    m = spawn(room, "slime", x, y)
    m.state = "recover"
    mv = room.rules.weapons["sword"].light[0]
    room.combat.hit_monster(a, m, mv, m.x, m.y)
    room.combat.hit_monster(b, m, mv, m.x, m.y)
    assert m.id not in room.combat.monsters
    owners = {d.owner for d in room.drops.values()}
    assert owners == {a.eid, b.eid}
    assert a.xp == b.xp > 0


def test_monster_telegraphs_then_hits_and_dodge_grace_cancels(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room, "forest")
    p = add_player(room, x, y, level=5)
    w = spawn(room, "wolf", x + 2.0, y, biome="forest")
    w.state, w.target = "chase", p.eid
    hp0 = p.hp
    telegraphed = False
    for _ in range(60):
        press(room, p, 1)
        telegraphed |= any(e[0] == 2 for e in p.ev)
        p.ev.clear()
        if p.hp < hp0:
            break
    assert telegraphed and p.hp < hp0, "a wolf next to you should bite after its wind-up"
    assert room.tick_no - p.last_combat < room.combat_lock

    # same again, but dodge the moment the bite lands: the grace window cancels the hit
    room2 = make_room(game_config)
    quiet(room2)
    p2 = add_player(room2, x, y, level=5)
    w2 = spawn(room2, "wolf", x + 2.0, y, biome="forest")
    w2.state, w2.target = "chase", p2.eid
    hp0 = p2.hp
    for _ in range(60):
        if room2.combat.pending:
            press(room2, p2, 1, mx=-127, b=BTN_DODGE)  # dodge input arrives inside the 100 ms grace
            press(room2, p2, 6)
            break
        press(room2, p2, 1)
    assert p2.hp == hp0
    assert any(e[0] == 1 and e[3] == 0 and e[5] == 2 for e in p2.ev)  # "dodged!"


def test_lag_compensation_hits_where_you_saw_it(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = add_player(room, x, y)
    m = spawn(room, "slime", x + 1.3, y)
    m.state = "recover"
    for _ in range(4):
        room.tick()
    # the slime slid away 2 tiles just now; on our screen (view_tick = 3 ticks ago) it was in reach
    seen_at = room.tick_no
    m.x += 2.0
    room.tick()
    mv = room.rules.weapons["sword"].light[0]
    p.m.ax, p.m.ay = 1.0, 0.0
    p.view_tick = seen_at
    p.atk_serial += 1
    assert room.combat.player_attack(p, mv)
    # but never further back than lag_comp_max (200 ms)
    m2 = spawn(room, "slime", x - 1.3, y)
    m2.state = "recover"
    for _ in range(3):
        room.tick()
    old = room.tick_no
    m2.x -= 2.0
    for _ in range(room.combat.lag_ticks + 3):
        room.tick()
    p.m.ax, p.m.ay = -1.0, 0.0
    p.view_tick = old
    p.atk_serial += 1
    assert not room.combat.player_attack(p, mv)


def test_knockout_loses_a_quarter_of_rare_materials(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = add_player(room, x, y)
    p.inv = [[0, "ironbark", 8, False], [1, "starstone", 2, False], [2, "wood", 50, False]]
    room.combat.damage_player(p, 10_000, 0, kind=0)
    assert p.ko > 0 and p.hp == 0
    assert {s[1]: s[2] for s in p.inv} == {"ironbark": 6, "starstone": 1, "wood": 50}
    assert p.pending.removed == {"ironbark": 2, "starstone": 1}
    dropped = {d.key: d.qty for d in room.drops.values() if d.owner == p.eid}
    assert dropped == {"ironbark": 2, "starstone": 1}
    for _ in range(room.combat.ko_ticks + 1):
        room.tick()
    assert p.ko == 0 and p.hp == p.stats.hp_max  # woke up at home, healed


def test_monsters_stay_out_of_villages(game_config) -> None:  # noqa: ANN001
    from hearthforge.domain import mapgen

    room = make_room(game_config)
    quiet(room)
    lay = mapgen.layout(game_config.mapgen)
    ox, oy = lay.plot_origins[0]
    p = add_player(room, ox + 24.5, oy + 24.5)
    m = spawn(room, "slime", ox - 4.5, oy + 24.5)
    m.state, m.target = "chase", p.eid
    for _ in range(200):
        room.tick()
        assert room.grid.gen.plot_at(int(m.x), int(m.y), 1) is None


def test_elites_are_tougher(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    normal = spawn(room, "slime", x, y)
    elite = spawn(room, "slime", x + 3, y, elite=True)
    assert elite.hp_max == normal.hp_max * game_config.enemies.elite.hp
    assert elite.dmg == pytest.approx(normal.dmg * game_config.enemies.elite.dmg)


def test_spear_throw_pierces(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = add_player(room, x - 2.5, y)
    p.weapon = {"key": "training_spear", "type": "spear", "tier": 1, "rarity": "common"}
    a = spawn(room, "slime", x, y)
    b = spawn(room, "slime", x + 1.2, y)
    a.state = b.state = "recover"
    from hearthforge.sim.rules import BTN_ABILITY

    press(room, p, 1, ax=127, b=BTN_ABILITY)
    press(room, p, 20)
    assert a.hp < a.hp_max or a.id not in room.combat.monsters
    assert b.hp < b.hp_max or b.id not in room.combat.monsters


def test_natural_spawns_wake_near_players(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    x, y = open_area(room, "forest")
    add_player(room, x, y, level=5)
    for _ in range(20):
        room.tick()
    ms = list(room.combat.monsters.values())
    assert any(m.key in ("wolf", "spider") for m in ms)
    for m in ms:  # each biome spawns its own roster
        assert m.key in game_config.enemies.biomes[m.biome].roster


def test_ability_spam_respects_the_cooldown(game_config) -> None:  # noqa: ANN001
    from hearthforge.sim.rules import BTN_ABILITY

    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = add_player(room, x, y)
    starts = 0
    for _ in range(200):
        before = p.atk_serial
        press(room, p, 1, ax=127, b=BTN_ABILITY)
        starts += p.atk_serial != before
    cd = room.rules.weapons["sword"].ability.cooldown
    assert starts == -(-200 // cd)  # once per cooldown, however hard you mash


def test_swings_out_of_reach_hit_nothing(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = add_player(room, x, y)
    m = spawn(room, "slime", x + 3.0, y)
    m.state, m.st_t = "recover", -10_000  # frozen in place
    for _ in range(40):
        press(room, p, 1, ax=127, b=BTN_LIGHT)
    assert m.hp == m.hp_max
