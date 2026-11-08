"""Phase 16b in the room: riding (speed through MOVE_MODS, thrown off in a fight) and fishing (cast,
bite, the server-timed bar, catches, misses and walking away)."""

from __future__ import annotations

import math

import pytest

from hearthforge.realtime.protocol import EV
from tests.unit.test_combat import add_player, make_room, open_area

pytestmark = pytest.mark.nodb


def fish_events(p) -> list:  # noqa: ANN001
    return [e[1:] for e in p.ev if e[0] == EV["FISH"]]


def shore(room) -> tuple[float, float]:  # noqa: ANN001
    """A walkable tile right next to fishable water, in a biome that has fish."""
    g = room.grid
    c = room.cfg.mapgen.map_size // 2
    for r in range(30, c - 4, 2):
        for k in range(0, 360, 3):
            x = int(c + r * math.cos(math.radians(k)))
            y = int(c + r * math.sin(math.radians(k)))
            if g.fluid(x, y) != "water" or g.solid(x - 1, y) or g.fluid(x - 1, y):
                continue
            p = (x - 1 + 0.5, y + 0.5)
            probe = add_player(room, *p)
            ok = room.fish_spot(probe) is not None
            room.players.pop(probe.eid, None)
            if ok:
                return p
    raise AssertionError("no shore on this map")


def test_riding_is_faster_and_a_fight_throws_you_off(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    x, y = open_area(room)
    p = add_player(room, x, y)
    assert room.set_mounted(p, True) == "no_mount"
    p.mount = "horse"
    assert room.set_mounted(p, True) is None
    assert p.mounted and p.mods[0] == pytest.approx(1.6) and p.rules is not None
    assert any(e[0] == EV["MOVE_MODS"] for e in p.ev)
    assert room.roster_entry(p)[-1] == "horse"  # others see you riding
    p.last_combat = room.tick_no + 1  # something hits you
    room.tick()
    assert not p.mounted and p.mods == (1.0, 1.0, 1.0) and room.roster_entry(p)[-1] is None
    assert room.set_mounted(p, True) == "in_combat"


def test_a_catch_on_time_and_a_miss(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    x, y = shore(room)
    p = add_player(room, x, y)
    assert room.cast(p) is None and p.fishing is not None
    assert fish_events(p)[0][0] == "cast"
    f = p.fishing
    room.tick_no = f.bite_tick
    room.tick_fishing(p, room.tick_no)
    bite = next(e for e in fish_events(p) if e[0] == "bite")
    _, fid, bar_ms, center, window, rarity = bite
    assert window == int(game_config.fishing.windows[rarity] * 1000) and 0 < center < bar_ms
    room.tick_no += round(center / 50)  # wait until the marker is in the zone, then press
    room.reel(p, fid, center)
    catch = next(e for e in fish_events(p) if e[0] == "catch")
    species, grams = catch[2], catch[3]
    lo, hi = game_config.fishing.species[species].kg
    assert lo * 1000 <= grams <= hi * 1000
    assert any(s[1] == species for s in p.inv) and p.pending.stats["fish.any"] == 1
    assert p.pending.records[f"best.fish.{species}"] == grams and p.fishing is None
    # a press way off the zone is a miss
    room.tick_no += room.hz * 2
    assert room.cast(p) is None
    room.tick_no = p.fishing.bite_tick
    room.tick_fishing(p, room.tick_no)
    fid = p.fishing.id
    room.reel(p, fid, 0)
    assert fish_events(p)[-1][:2] == ["miss", fid]


def test_late_presses_and_walking_off(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    x, y = shore(room)
    p = add_player(room, x, y)
    room.cast(p)
    room.tick_no = p.fishing.bite_tick
    room.tick_fishing(p, room.tick_no)
    f = p.fishing
    # claiming the zone long after it passed doesn't count (the press must be near real time)
    room.tick_no += round((f.center_ms + 2000) / 50)
    room.reel(p, f.id, f.center_ms)
    assert fish_events(p)[-1][0] == "miss"
    # walking away reels the line in
    room.tick_no += room.hz * 2
    room.cast(p)
    p.m.x += 1.0
    room.tick_fishing(p, room.tick_no)
    assert fish_events(p)[-1][0] == "cancel" and p.fishing is None
    # nowhere near water
    far = add_player(room, *open_area(room))
    if room.fish_spot(far) is None:
        assert room.cast(far) == "no_water"


def test_casting_gets_you_off_your_horse(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    p = add_player(room, *shore(room))
    p.mount = "ram"
    room.set_mounted(p, True)
    assert room.cast(p) is None and not p.mounted
