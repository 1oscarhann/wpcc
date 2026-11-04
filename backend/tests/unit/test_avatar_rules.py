from __future__ import annotations

import pytest

from hearthforge.domain import mapgen
from hearthforge.domain.blocks import village_blocks
from hearthforge.sim.grid import WorldGrid
from hearthforge.sim.stats import add_xp, stats_for, xp_to_next

pytestmark = pytest.mark.nodb


def test_xp_curve_matches_balance_table(game_config) -> None:  # noqa: ANN001
    assert [xp_to_next(game_config, lv) for lv in (1, 2, 5, 10, 15, 20, 25, 29)] == [
        100,
        254,
        989,
        2859,
        5341,
        8332,
        11766,
        14805,
    ]


def test_add_xp_levels_up_and_carries(game_config) -> None:  # noqa: ANN001
    level, xp, gained = add_xp(game_config, 1, 90, 30)
    assert (level, xp, gained) == (2, 20, 1)
    level, xp, gained = add_xp(game_config, 1, 0, 10_000)
    assert gained >= 4 and level == 1 + gained
    assert stats_for(game_config, 30).hp_max == 332


def test_fence_blocks_but_gate_is_open(game_config) -> None:  # noqa: ANN001
    from hearthforge.services import plots

    lay = mapgen.layout(game_config.mapgen)
    gate = plots.gate(game_config, 0)
    state = {
        "origin": list(lay.plot_origins[0]),
        "frame": game_config.mapgen.plot.frame,
        "size": 32,
        "buildings": [{"key": "town_hall", "x": 22, "y": 19, "rotation": 0}],
        "gate": list(gate),
        "debris": [[1, "oak", 0, 12, 12], [2, "weeds", 0, 13, 12]],
    }
    rects = village_blocks(game_config, state)
    tiles = {(x + i, y + j) for x, y, w, h in rects for i in range(w) for j in range(h)}
    ox, oy = lay.plot_origins[0]
    gx, gy, _side = gate
    assert (ox + gx, oy + gy) not in tiles  # the gate is walkable
    assert (ox + 22, oy + 19) in tiles and (ox + 25, oy + 22) in tiles  # town hall footprint
    assert (ox + 12, oy + 12) in tiles  # an oak is solid…
    assert (ox + 13, oy + 12) not in tiles  # …weeds are not
    lo = (game_config.mapgen.plot.frame - 32) // 2
    assert (ox + lo - 1, oy + lo + 3) in tiles  # fence


def test_grid_water_is_solid_and_trees_are_nodes(game_config) -> None:  # noqa: ANN001
    g = WorldGrid(game_config, 7)
    c = game_config.mapgen.map_size // 2
    assert g.solid(-1, 5) and g.solid(5, game_config.mapgen.map_size)
    assert not g.solid(c + 3, c + 3)  # the hub is open cobble
    found_tree = found_water = False
    for y in range(c + 180, c + 220):
        for x in range(c - 20, c + 20):
            oid = g.object_at(x, y)
            if oid is not None and mapgen.OBJECT_NAMES[oid].startswith("obj.pine"):
                assert g.solid(x, y)
                assert g.node_at(x, y) == "tree"
                found_tree = True
            if g.gen.kind(x, y) == "water":
                assert g.solid(x, y)
                found_water = True
    assert found_tree  # (ponds are random, so water is only checked when one turns up)
    del found_water


def test_forest_band_is_dense_and_walkable(game_config) -> None:  # noqa: ANN001
    g = WorldGrid(game_config, 11)
    c = game_config.mapgen.map_size // 2
    r = game_config.mapgen.forest.radius + 20
    solid = total = 0
    for y in range(c - 8, c + 8):
        for x in range(c + r, c + r + 16):
            total += 1
            solid += g.solid(x, y)
            assert g.gen.biome(x, y) == "forest"
    assert 0.04 < solid / total < 0.35
