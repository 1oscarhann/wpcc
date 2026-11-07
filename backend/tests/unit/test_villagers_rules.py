"""Phase 14: the pure villager rules — happiness formula (BALANCE §10), beauty parts, tavern reach, moods."""

from __future__ import annotations

import pytest

from hearthforge.domain import villagers as dom

pytestmark = pytest.mark.nodb


def test_happiness_formula(game_config) -> None:  # noqa: ANN001
    cfg = game_config
    tiles = 32 * 32
    full_beauty = tiles * cfg.villagers.happiness.beauty_per_tile
    h = dom.happiness(cfg, full_beauty, tiles, capacity=4, villagers=4, food_rate=16, tavern=True)
    assert h["value"] == 100
    h = dom.happiness(cfg, 0, tiles, capacity=2, villagers=4, food_rate=8, tavern=False)
    # 0.35·0 + 0.25·0.5 + 0.25·0.5 + 0.15·0 = 0.25
    assert h["value"] == 25 and h["housing"] == 0.5 and h["food"] == 0.5
    empty = dom.happiness(cfg, 0, tiles, 0, 0, 0, False)
    assert empty["value"] == cfg.villagers.happiness.empty


def test_moods_name_the_weakest_factor(game_config) -> None:  # noqa: ANN001
    cfg = game_config
    base = {"value": 60, "beauty": 1.0, "housing": 1.0, "food": 1.0, "tavern": 1.0}
    assert dom.mood(cfg, base) == "happy"
    assert dom.mood(cfg, {**base, "food": 0.3}) == "hungry"
    assert dom.mood(cfg, {**base, "housing": 0.5}) == "crowded"
    assert dom.mood(cfg, {**base, "beauty": 0.2}) == "ugly"
    assert dom.mood(cfg, {**base, "value": 10}) == "leaving"


def test_beauty_counts_decor_variety_paths_and_nature(game_config) -> None:  # noqa: ANN001
    cfg = game_config
    th = dom.B("th", "town_hall", 22, 19, 0, 1)
    house = dom.B("h", "house", 17, 20, 0, 1)
    bed = dom.B("f1", "flower_bed", 12, 12, 0, 1)
    bed2 = dom.B("f2", "flower_bed", 13, 12, 0, 1)
    paths = [dom.B(f"p{x}", "path_dirt", x, 21, 0, 1) for x in (20, 21)]
    debris = [[1, "oak", 0, 30, 30], [2, "rock", 0, 31, 30]]
    b = dom.beauty(cfg, [th, house, bed, bed2, *paths], debris)
    assert b["decor"] == 2 * cfg.buildings["flower_bed"].cfg.beauty
    assert b["variety"] == cfg.villagers.beauty.variety  # two flower beds are one kind; paths don't count
    assert b["linked"] == 1 and b["connected"] == cfg.villagers.beauty.connected
    assert b["nature"] == cfg.villagers.beauty.nature  # the oak counts, the rock doesn't
    assert b["score"] == pytest.approx(b["decor"] + b["variety"] + b["connected"] + b["nature"])


def test_tavern_reach_needs_most_homes(game_config) -> None:  # noqa: ANN001
    cfg = game_config
    tav = dom.B("t", "tavern", 20, 20, 0, 1)
    near = [dom.B(f"h{i}", "house", 20 + i * 3, 24, 0, 1) for i in range(2)]
    far = dom.B("hf", "house", 2, 2, 0, 1)
    assert dom.tavern_ok(cfg, [tav, *near, far])
    assert not dom.tavern_ok(cfg, [tav, near[0], far, dom.B("hg", "house", 2, 6, 0, 1)])
    assert not dom.tavern_ok(cfg, [dom.B("t0", "tavern", 20, 20, 0, 0), *near])  # still being built


def test_job_slots(game_config) -> None:  # noqa: ANN001
    cfg = game_config
    assert dom.job_slots(cfg, "lumber_camp", 1) == 1 and dom.job_slots(cfg, "lumber_camp", 5) == 3
    assert dom.job_slots(cfg, "guard_post", 3) == 2
    assert dom.job_slots(cfg, "house", 3) == 0 and dom.job_slots(cfg, "lumber_camp", 0) == 0
