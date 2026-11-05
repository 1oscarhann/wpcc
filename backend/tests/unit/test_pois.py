"""Phase 10 points of interest: placement and what each one does when you use it."""

from __future__ import annotations

from collections import Counter

import pytest

from hearthforge.domain import mapgen
from hearthforge.realtime.protocol import EV
from hearthforge.sim.room import Player, RealmRoom
from tests.unit.test_combat import add_player, make_room, quiet, spawn

pytestmark = pytest.mark.nodb


def at_poi(room: RealmRoom, kind: str, biome: str | None = None) -> tuple[mapgen.Poi, Player]:
    poi = next(p for p in room.grid.gen.pois if p.kind == kind and (biome is None or p.biome == biome))
    p = add_player(room, poi.x + 0.5, poi.y + 1.6)
    return poi, p


def poi_events(p: Player) -> list[list]:
    return [e for e in p.ev if e[0] == EV["POI"]]


def test_every_ring_gets_its_pois_on_dry_land(game_config) -> None:  # noqa: ANN001
    want = Counter({(b, k): n for b, counts in game_config.pois.bands.items() for k, n in counts.items()})
    for seed in (1, 77, 4242):
        gen = mapgen.Generator(game_config, seed)
        got = Counter((p.biome, p.kind) for p in gen.pois)
        assert got == want
        for p in gen.pois:
            assert gen.kind(p.x, p.y) in {"grass", "forest", "rock", "mud", "snow", "ash"}
            assert gen.trail_dist(p.x, p.y) >= game_config.pois.trail_clearance
        spacing = game_config.pois.min_spacing
        for a in gen.pois:
            for b in gen.pois:
                if a.index < b.index:
                    assert (a.x - b.x) ** 2 + (a.y - b.y) ** 2 >= spacing**2


def test_pois_show_up_in_chunks_with_a_clearing(game_config) -> None:  # noqa: ANN001
    gen = mapgen.Generator(game_config, 5)
    cs = game_config.mapgen.chunk_size
    for poi in gen.pois[:12]:
        ch = gen.chunk(poi.x // cs, poi.y // cs)
        objs = {
            (poi.x // cs * cs + o[0], poi.y // cs * cs + o[1]): mapgen.OBJECT_NAMES[o[2]]
            for o in ch["objects"]
        }
        assert objs.get((poi.x, poi.y)) == mapgen.POI_OBJECT[poi.kind]
        # nothing else crowds it (ruins keep their two broken walls)
        crowd = [
            n
            for (x, y), n in objs.items()
            if (x - poi.x) ** 2 + (y - poi.y) ** 2 <= 4
            and (x, y) != (poi.x, poi.y)
            and not n.startswith("obj.ruins")
        ]
        assert crowd == []


def test_chest_gives_loot_once(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    poi, p = at_poi(room, "ruins", "forest")
    room.interact(p, poi.index)
    ev = poi_events(p)
    assert ev and ev[0][2] == "ruins" and ev[0][3]["coins"] >= game_config.pois.chests["forest"].coins[0]
    keys = {d.key for d in room.drops.values() if d.owner == p.eid}
    assert "coins" in keys and len(keys) >= 2
    assert poi.key in p.pending.pois
    n = len(room.drops)
    p.ev.clear()
    room.interact(p, poi.index)
    assert not poi_events(p) and len(room.drops) == n
    assert any(e[0] == EV["TOAST"] and e[1] == "chest_empty" for e in p.ev)


def test_too_far_does_nothing(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    poi = next(q for q in room.grid.gen.pois if q.kind == "ruins")
    p = add_player(room, poi.x + 0.5, poi.y + 6.5)
    room.interact(p, poi.index)
    assert not poi_events(p) and not room.drops


def test_shrine_blessing_boosts_combat_then_rests(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    shrines = [q for q in room.grid.gen.pois if q.kind == "shrine"]
    keys = list(game_config.pois.shrines.blessings)
    might = next(q for q in shrines if keys[q.variant % len(keys)] == "might")
    p = add_player(room, might.x + 0.5, might.y + 1.6)
    m = spawn(room, "slime", p.m.x + 1.2, p.m.y)
    mv = room.rules.weapons["sword"].light[0]
    before, _ = room.combat.damage_out(p, mv, m)
    room.interact(p, might.index)
    ev = poi_events(p)
    assert ev and ev[0][3]["blessing"] == "might"
    after, _ = room.combat.damage_out(p, mv, m)
    assert after > before
    p.ev.clear()
    room.interact(p, might.index)  # resting
    assert not poi_events(p)
    assert any(e[0] == EV["TOAST"] and e[1] == "shrine_resting" for e in p.ev)
    # it wears off
    room.tick_no = p.blessing[1] + 1  # type: ignore[index]
    assert room.blessing(p, "damage") == 0.0


def test_lore_stone_gives_xp_the_first_time_only(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    poi, p = at_poi(room, "lore_stone")
    xp0 = p.xp
    room.interact(p, poi.index)
    first = poi_events(p)[0][3]
    assert first["first"] and first["title"] and p.xp > xp0
    assert p.pending.lore and p.pending.stats["lore.read"] == 1
    xp1 = p.xp
    p.ev.clear()
    room.interact(p, poi.index)
    again = poi_events(p)[0][3]
    assert not again["first"] and again["text"] == first["text"] and p.xp == xp1


def test_lost_villager_goes_home_once(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    poi, p = at_poi(room, "lost_villager")
    room.interact(p, poi.index)
    d = poi_events(p)[0][3]
    assert d["name"] in game_config.pois.lost_villager.names and d["coins"] > 0
    assert p.pending.stats["villagers.found"] == 1
    p.ev.clear()
    room.interact(p, poi.index)
    assert not poi_events(p)


def test_trader_and_cave(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    poi, p = at_poi(room, "merchant")
    room.interact(p, poi.index)
    assert poi_events(p)[0][3] == {"merchant_id": f"wild:{poi.index}"}
    cave, p2 = at_poi(room, "cave")
    room.interact(p2, cave.index)
    assert poi_events(p2)[0][2] == "cave" and cave.key in p2.pending.pois
