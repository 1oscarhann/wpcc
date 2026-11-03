from __future__ import annotations

import json

import pytest

from hearthforge.config.loader import load_config
from hearthforge.domain import mapgen
from hearthforge.settings import REPO_ROOT

pytestmark = pytest.mark.nodb
CFG = load_config(REPO_ROOT / "config").mapgen


def test_same_seed_same_chunk() -> None:
    a = mapgen.Generator(CFG, 1234).chunk(20, 20)
    b = mapgen.Generator(CFG, 1234).chunk(20, 20)
    assert a == b


def test_different_seed_differs() -> None:
    a = mapgen.Generator(CFG, 1).chunk(18, 14)
    b = mapgen.Generator(CFG, 2).chunk(18, 14)
    assert a != b


def test_blob_masks_match_artgen() -> None:
    assert len(mapgen.BLOB_MASKS) == 47


def test_every_tile_and_object_has_art() -> None:
    """The server's tile/object tables must only name sprites the generator actually produced."""
    manifest = json.loads((REPO_ROOT / "frontend" / "src" / "assets" / "manifest.json").read_text())
    sprites = set(manifest["sprites"])
    missing = [n for n in mapgen.TILE_NAMES + mapgen.OBJECT_NAMES if n not in sprites]
    assert missing == []


def test_plots_fit_on_map_and_never_overlap() -> None:
    lay = mapgen.layout(CFG)
    f = lay.frame
    for i, (x, y) in enumerate(lay.plot_origins):
        assert x >= 0 and x + f <= lay.size and y >= 0 and y + f <= lay.size
        for j, (x2, y2) in enumerate(lay.plot_origins):
            if i < j:
                assert not (x < x2 + f and x2 < x + f and y < y2 + f and y2 < y + f)


def test_buildable_square_is_clear_and_has_a_pond() -> None:
    gen = mapgen.Generator(CFG, 99)
    lay = gen.lay
    ox, oy = lay.plot_origins[0]
    cs = CFG.chunk_size
    water_seen = 0
    for cy in range(oy // cs, (oy + lay.frame) // cs + 1):
        for cx in range(ox // cs, (ox + lay.frame) // cs + 1):
            ch = gen.chunk(cx, cy)
            lo = (lay.frame - CFG.plot.start_size) // 2 - 1
            hi = lo + CFG.plot.start_size + 2
            for lx, ly, _k, _v in ch["objects"]:
                x, y = cx * cs + lx, cy * cs + ly
                assert not (lo <= x - ox < hi and lo <= y - oy < hi), "object inside the buildable square"
            for t in ch["ground"]:
                if mapgen.TILE_NAMES[t].startswith("tile.water"):
                    water_seen += 1
    p = CFG.plot.pond
    assert water_seen == p.w * p.h


def test_hub_has_well_and_roads_reach_plots() -> None:
    gen = mapgen.Generator(CFG, 7)
    c = gen.lay.center
    cs = CFG.chunk_size
    ch = gen.chunk(c // cs, c // cs)
    assert any(mapgen.OBJECT_NAMES[k] == "obj.well.0" for _x, _y, k, _v in ch["objects"])
    # walk from the hub edge towards plot 0 (straight up) and expect road tiles on the way
    kinds = [gen.kind(c, y) for y in range(c - gen.lay.hub_radius - 30, c - gen.lay.hub_radius)]
    assert "path" in kinds
