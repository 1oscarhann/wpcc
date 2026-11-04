"""Combos (adjacency graph) and forging maths: pure, no DB."""

from __future__ import annotations

import pytest

from hearthforge.domain import combos as cd
from hearthforge.domain import forging

pytestmark = pytest.mark.nodb


def node(i: str, key: str, x: int, y: int, level: int = 1, w: int = 3, h: int = 3) -> cd.Node:
    return cd.Node(i, key, level, (x, y, w, h))


def test_edge_adjacency_counts_but_corners_dont() -> None:
    a = (0, 0, 3, 3)
    assert cd.adjacent(a, (3, 0, 3, 3))  # right side
    assert cd.adjacent(a, (1, 3, 3, 3))  # below, partly overlapping in x
    assert not cd.adjacent(a, (3, 3, 3, 3))  # corner only
    assert not cd.adjacent(a, (4, 0, 3, 3))  # a gap
    assert cd.adjacent((0, 0, 4, 4), (4, 3, 3, 3))  # a single shared tile edge is enough


def test_two_building_combo_needs_touching_and_built(game_config) -> None:  # noqa: ANN001
    combos = game_config.combos.combos
    touching = [node("f", "forge", 0, 0, level=2), node("l", "lumber_camp", 3, 0, level=3)]
    active = cd.active_combos(combos, touching)
    assert [(a.key, a.tier) for a in active] == [("forge_lumber", 2)]  # tier = lowest level
    apart = [node("f", "forge", 0, 0), node("l", "lumber_camp", 4, 0)]
    assert cd.active_combos(combos, apart) == []
    unbuilt = [node("f", "forge", 0, 0), node("l", "lumber_camp", 3, 0, level=0)]
    assert cd.active_combos(combos, unbuilt) == []


def test_three_building_combo_is_a_connected_group(game_config) -> None:  # noqa: ANN001
    combos = game_config.combos.combos
    # a chain: forge – mine – tannery (forge and tannery don't touch each other)
    chain = [node("f", "forge", 0, 0), node("m", "mine", 3, 0), node("t", "tannery", 6, 0)]
    keys = sorted(a.key for a in cd.active_combos(combos, chain))
    assert keys == ["forge_mine", "forge_mine_tannery"]  # overlapping combos both count
    broken = [node("f", "forge", 0, 0), node("m", "mine", 3, 0), node("t", "tannery", 10, 0)]
    assert [a.key for a in cd.active_combos(combos, broken)] == ["forge_mine"]


def test_copies_and_best_station_tier(game_config) -> None:  # noqa: ANN001
    combos = game_config.combos.combos
    nodes = [
        node("f", "forge", 3, 3, level=3),
        node("l1", "lumber_camp", 0, 3, level=1),
        node("l2", "lumber_camp", 6, 3, level=2),
    ]
    active = cd.active_combos(combos, nodes)
    assert len(active) == 2
    assert cd.station_tier(active, combos, "f", "spear") == (2, "forge_lumber")
    assert cd.station_tier(active, combos, "f", "sword") is None
    assert cd.station_tier(active, combos, "l1", "spear") == (1, "forge_lumber")  # not a station, but in it


def test_new_combo_keys_for_the_preview(game_config) -> None:  # noqa: ANN001
    combos = game_config.combos.combos
    before = [node("f", "forge", 0, 0)]
    after = before + [node("ghost", "mine", 0, 3)]
    assert cd.new_combo_keys(combos, before, after) == ["forge_mine"]
    assert cd.new_combo_keys(combos, after, after) == []


def test_bills_by_tier(game_config) -> None:  # noqa: ANN001
    assert forging.bill(game_config, "spear", 1) == {"wood": 20, "ore": 10}
    assert forging.bill(game_config, "spear", 2) == {"planks": 4, "ingots": 3, "coins": 30}
    assert forging.bill(game_config, "sword", 4) == {"planks": 7, "ingots": 18, "coins": 400, "crystal": 10}
    assert forging.forge_seconds(game_config, 5) == 60


def test_rarity_odds_match_balance_table(game_config) -> None:  # noqa: ANN001
    odds0 = forging.rarity_odds(game_config, 0, True)
    assert [round(p * 100, 1) for p in odds0] == [60.0, 26.0, 10.0, 3.5, 0.5]
    odds3 = forging.rarity_odds(game_config, 3, True)
    assert [round(p * 100, 1) for p in odds3] == [48.5, 28.4, 14.7, 7.0, 1.3]
    capped = forging.rarity_odds(game_config, 0, False)
    assert capped[4] == 0 and round(capped[3] * 100, 1) == 4.0  # legendary folds into epic (P8)


def test_rolls_are_seeded_and_rares_guarantee_modifiers(game_config) -> None:  # noqa: ANN001
    a = forging.roll(game_config, 1234, 3, 2, ["ironbark", "starstone"], True)
    b = forging.roll(game_config, 1234, 3, 2, ["ironbark", "starstone"], True)
    assert a == b
    assert a.durability == game_config.forging.tiers[2].durability
    slots = next(r.slots for r in game_config.forging.rarities if r.key == a.rarity)
    assert len(a.modifiers) == slots
    expected = ["heavy", "keen"][:slots]
    assert [m["key"] for m in a.modifiers[: len(expected)]] == expected
    # find an epic roll: two slots, two guaranteed modifiers with values inside their ranges
    for seed in range(5000):
        f = forging.roll(game_config, seed, 2, 3, ["ironbark", "starstone"], False)
        if f.rarity == "epic":
            heavy, keen = f.modifiers
            assert 0.4 + 0.4 * 0.4 - 1e-9 <= heavy["value"] <= 0.8  # epic raises the floor
            assert 0.04 <= keen["value"] <= 0.10
            break
    else:
        raise AssertionError("no epic in 5000 seeds")


def test_empty_slots_are_polished_and_dull_turns_mods_off(game_config) -> None:  # noqa: ANN001
    for seed in range(2000):
        f = forging.roll(game_config, seed, 1, 0, [], True)
        if f.rarity == "rare":
            assert [m["key"] for m in f.modifiers] == ["polished"]
            eff = forging.weapon_effects(f.modifiers, dull=False)
            assert eff["damage"] == pytest.approx(0.03)
            assert forging.weapon_effects(f.modifiers, dull=True)["damage"] == 0
            break
    else:
        raise AssertionError


def test_repair_and_salvage_maths(game_config) -> None:  # noqa: ANN001
    assert forging.repair_cost(game_config, 1, 0) == {}
    assert forging.repair_cost(game_config, 2, 100) == {"coins": 60, "ingots": 3}
    back, rares = forging.salvage_returns(game_config, {"planks": 4, "ingots": 3, "coins": 30}, [], 9)
    assert back == {"planks": 1, "ingots": 1}
    assert rares == []
    assert forging.item_name(game_config, "sword", 3) == "Steel Sword"
    assert forging.item_name(game_config, "training_sword", 1) == "Training Sword"


def test_a_rare_material_always_gets_a_slot(game_config) -> None:  # noqa: ANN001
    odds = forging.rarity_odds(game_config, 1, False, rares=1)
    assert odds[0] == 0 and abs(sum(odds) - 1) < 1e-9
    for seed in range(300):
        f = forging.roll(game_config, seed, 1, 1, ["ironbark"], False)
        assert f.rarity != "common" and f.modifiers[0]["key"] == "heavy"
