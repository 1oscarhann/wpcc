"""Phase 13: realm bosses in the room — scaling, phases, hazards, the vulnerable window, regen and loot."""

from __future__ import annotations

from typing import Any

import pytest

from hearthforge.realtime.protocol import EV
from hearthforge.sim.bosses import BossBrain, Bosses, BossRow
from hearthforge.sim.combat import Monster
from hearthforge.sim.room import Player, RealmRoom
from tests.unit.test_combat import add_player, make_room, open_area

pytestmark = pytest.mark.nodb


def boss_room(
    cfg: Any, key: str = "grubmaw", kills: dict[str, int] | None = None
) -> tuple[RealmRoom, Monster, float, float]:
    room = make_room(cfg)
    room.combat._wake = lambda t: None  # type: ignore[method-assign]
    room.bosses = Bosses(room)
    x, y = open_area(room)
    room.bosses.set_rows([BossRow("b1", key, x, y, 1.0, 0, {}, kills or {})])
    room.tick()
    m = room.bosses.live["b1"]
    return room, m, x, y


def brain(m: Monster) -> BossBrain:
    assert isinstance(m.brain, BossBrain)
    return m.brain


def ticks(room: RealmRoom, n: int) -> None:
    for _ in range(n):
        room.tick()


def test_a_boss_wakes_at_its_lair_and_scales_with_fighters(game_config) -> None:  # noqa: ANN001
    room, m, x, y = boss_room(game_config)
    cfg = game_config.bosses.bosses["grubmaw"]
    assert m.boss and m.hp_max == cfg.hp and m.state == "idle"
    a = add_player(room, x + 3, y, level=10)
    ticks(room, 3)
    assert brain(m).awake and any(e[0] == EV["BOSS"] and e[1] == "wake" for e in a.ev)
    m.hp = m.hp_max / 2
    add_player(room, x - 3, y, level=10)
    ticks(room, room.hz + 1)
    k = game_config.bosses.hp_per_fighter
    assert m.hp_max == round(cfg.hp * (1 + k))
    assert m.hp / m.hp_max == pytest.approx(0.5, abs=0.02)  # the share left is kept


def test_phases_bring_notes_and_adds(game_config) -> None:  # noqa: ANN001
    room, m, x, y = boss_room(game_config)
    p = add_player(room, x + 3, y, level=10)
    p.iframes = 10**6
    ticks(room, 2)
    m.hp = m.hp_max * 0.5
    ticks(room, 1)
    assert brain(m).phase == 1
    m.hp = m.hp_max * 0.2
    ticks(room, 1)
    assert brain(m).phase == 2
    adds = [mm for mm in room.combat.monsters.values() if mm.minion_of == m.id]
    assert len(adds) == game_config.bosses.bosses["grubmaw"].phases[2].summon.count
    notes = [e for e in p.ev if e[0] == EV["BOSS"] and e[1] == "phase"]
    assert notes and "Slimeling" in notes[-1][4]


def test_attacks_telegraph_and_land_unless_you_dodge(game_config) -> None:  # noqa: ANN001
    room, m, x, y = boss_room(game_config)
    p = add_player(room, x + 2, y, level=30)
    hp0 = p.hp
    shapes: set[int] = set()
    for _ in range(room.hz * 20):
        room.tick()
        for e in p.ev:
            if e[0] == EV["TELEGRAPH"] and e[1] != m.id:
                shapes.add(e[2])
        p.ev.clear()
        p.hp = max(p.hp, 50.0)
        p.ko = 0
    assert shapes, "it never attacked"
    assert p.hp != hp0 or any(h for h in room.combat.pending)  # something hit at some point
    # with endless i-frames nothing lands
    room2, m2, x2, y2 = boss_room(game_config)
    q = add_player(room2, x2 + 2, y2, level=30)
    q.iframes = 10**6
    hp1 = q.hp
    ticks(room2, room2.hz * 15)
    assert q.hp == hp1


def test_the_colossus_core_is_vulnerable_after_a_fist(game_config) -> None:  # noqa: ANN001
    room, m, x, y = boss_room(game_config, "stone_colossus")
    p = add_player(room, x + 4, y, level=30)
    p.iframes = 10**6
    b = brain(m)
    for _ in range(room.hz * 30):
        room.tick()
        if b.vuln_until > room.tick_no:
            break
    assert b.vuln_until > room.tick_no, "never opened up"
    assert m.brain.flags(m) & 256
    assert b.on_hit(p, 10) == 10 * game_config.bosses.bosses["stone_colossus"].vulnerable_mult


def test_the_hydra_regrows_unless_burning(game_config) -> None:  # noqa: ANN001
    room, m, x, y = boss_room(game_config, "swamp_hydra")
    p = add_player(room, x + 3, y, level=30)
    p.iframes = 10**6
    m.hp = m.hp_max * 0.9
    ticks(room, room.hz * 3)
    assert m.hp > m.hp_max * 0.9
    m.hp = m.hp_max * 0.9
    m.burn = (1.0, 10**6)
    ticks(room, room.hz * 3)
    assert m.hp <= m.hp_max * 0.9


def test_loot_needs_a_real_share_and_first_kills_get_the_trophy(game_config) -> None:  # noqa: ANN001
    room, m, x, y = boss_room(game_config)
    hero = add_player(room, x + 3, y, level=30)
    pal = add_player(room, x - 3, y, level=30)
    lurker = add_player(room, x, y + 3, level=30)
    b = brain(m)
    b.on_hit(hero, 900)
    b.on_hit(pal, 100)
    b.on_hit(lurker, 1)  # < 1%
    b.row.kills = {str(pal.user_id): 3}  # pal has beaten it before: no guaranteed trophy
    room.rng.seed(7)
    room.combat._kill(m, hero)

    def got(p: Player) -> set[str]:
        return {d.key for d in room.drops.values() if d.owner == p.eid}

    trophy = game_config.bosses.bosses["grubmaw"].loot.trophy
    assert {"coins", "moonpetal", trophy} <= got(hero)
    assert "coins" in got(pal)
    assert got(lurker) == set()
    assert room.bosses.done and room.bosses.done[0][0].id == "b1"
    assert "b1" not in room.bosses.live
    assert any(e[0] == EV["BOSS"] and e[1] == "down" for e in lurker.ev)  # everyone hears about it


def test_a_boss_with_nobody_around_goes_home_and_heals(game_config) -> None:  # noqa: ANN001
    room, m, x, y = boss_room(game_config)
    p = add_player(room, x + 3, y, level=30)
    p.iframes = 10**6
    ticks(room, 5)
    m.hp = m.hp_max * 0.8
    m.x += 6
    del room.players[p.eid]
    del room.by_user[p.user_id]
    ticks(room, room.hz * 12)
    assert m.hp == m.hp_max and m.state == "idle" and not brain(m).awake
