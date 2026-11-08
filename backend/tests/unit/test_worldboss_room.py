"""Phase 17 in the room: the world boss spawns at the hub with the pool's HP, tallies damage for the
next flush, takes the pool's value when other realms chip at it, and leaves when the event ends."""

from __future__ import annotations

import uuid

import pytest

from hearthforge.sim.worldboss import WORLD, WorldBoss, WorldEvent
from tests.unit.test_combat import add_player, make_room

pytestmark = pytest.mark.nodb


def event(hp: int, status: str = "active", eid: uuid.UUID | None = None) -> WorldEvent:
    return WorldEvent(eid or uuid.uuid4(), "stone_colossus", "The Elder Colossus", 100_000, hp, status, 0)


def test_world_boss_shares_one_pool(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    room.world = w = WorldBoss(room)
    ev = event(80_000)
    w.set_event(ev)
    w.tick(room.tick_no)
    m = w.m
    assert m is not None and m.boss and m.hp == 80_000 and m.hp_max == 100_000
    assert m.brain.flags(m) & WORLD
    p = add_player(room, m.x + 1, m.y)
    dealt = m.brain.on_hit(p, 500)
    m.hp -= dealt
    assert w.pending[str(p.user_id)] == 500 and p.pending.stats["worldboss.damage"] == 500
    m.brain.scale(m, 8)  # eight fighters around it: no rescaling, the pool is shared
    assert m.hp_max == 100_000
    # the flush sends our 500; meanwhile other realms took 9,500 more off the pool
    assert w.take_pending() == {str(p.user_id): 500} and not w.pending
    w.set_event(event(70_000, eid=ev.id))
    assert m.hp == 70_000
    # it's over: the boss leaves this realm too
    w.set_event(event(0, "defeated", eid=ev.id))
    assert w.m is None and m.id not in room.combat.monsters or room.combat.monsters[m.id].state == "fade"
    w.tick(room.tick_no)
    assert w.m is None  # no respawn once it's down
