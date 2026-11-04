from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from hearthforge.config.loader import ConfigError, load_config
from hearthforge.config.schemas import parse_duration
from hearthforge.settings import REPO_ROOT

pytestmark = pytest.mark.nodb


@pytest.fixture
def cfg_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", d)
    return d


def edit(d: Path, name: str, fn) -> None:  # noqa: ANN001
    p = d / f"{name}.yaml"
    data = yaml.safe_load(p.read_text())
    fn(data)
    p.write_text(yaml.safe_dump(data))


def test_real_config_loads_strict() -> None:
    cfg = load_config(REPO_ROOT / "config", strict=True)
    assert "town_hall" in cfg.buildings
    assert cfg.buildings["lumber_camp"].level(1).production == {"wood": 60.0}
    assert len(cfg.hash) == 16


def test_hash_is_stable(cfg_dir: Path) -> None:
    assert load_config(cfg_dir).hash == load_config(REPO_ROOT / "config").hash


def test_level_curve_derives_costs() -> None:
    cfg = load_config(REPO_ROOT / "config")
    lc = cfg.buildings["lumber_camp"]
    assert lc.level(1).cost == {"wood": 40, "stone": 20}
    assert lc.level(2).cost == {"wood": 100, "stone": 50}
    assert lc.level(3).cost["coins"] == 100
    assert lc.level(5).time_s == 2400


def test_gates_convert_intermediates_and_drop_rares() -> None:
    cfg = load_config(REPO_ROOT / "config")
    th4 = cfg.buildings["town_hall"].level(4).cost
    assert "planks" not in th4 and "ironbark" not in th4
    assert th4["wood"] == 1600 and th4["stone"] == 1400


def test_gates_on_keeps_intermediates(cfg_dir: Path) -> None:
    edit(cfg_dir, "game", lambda d: d["gates"].update(intermediates_enabled=True, rare_costs_enabled=True))
    cfg = load_config(cfg_dir)
    lc3 = cfg.buildings["lumber_camp"].level(3).cost
    assert lc3["planks"] == 60 and lc3["wood"] == 120 and lc3["bricks"] == 30
    assert cfg.buildings["lumber_camp"].level(5).cost["ironbark"] == 4
    assert cfg.buildings["forge"].level(5).cost["starstone"] == 4


def test_unknown_key_fails_with_path(cfg_dir: Path) -> None:
    edit(cfg_dir, "buildings", lambda d: d["buildings"]["house"].update(colour="red"))
    with pytest.raises(ConfigError) as e:
        load_config(cfg_dir)
    assert any("buildings.yaml:buildings.house.colour" in x for x in e.value.errors)


def test_unknown_cost_key_fails(cfg_dir: Path) -> None:
    edit(cfg_dir, "buildings", lambda d: d["buildings"]["house"]["base_cost"].update(unobtainium=5))
    with pytest.raises(ConfigError, match="unobtainium"):
        load_config(cfg_dir)


def test_timer_over_one_hour_fails(cfg_dir: Path) -> None:
    edit(cfg_dir, "buildings", lambda d: d["buildings"]["town_hall"]["levels"][4].update(time="2h"))
    with pytest.raises(ConfigError, match="max_timer_seconds"):
        load_config(cfg_dir)


def test_bad_default_appearance_fails(cfg_dir: Path) -> None:
    edit(cfg_dir, "avatar", lambda d: d["default_appearance"].update(hair_color="plaid"))
    with pytest.raises(ConfigError, match="hair_color"):
        load_config(cfg_dir)


def test_overlapping_starter_buildings_fail(cfg_dir: Path) -> None:
    edit(cfg_dir, "starter", lambda d: d["buildings"][1].update(x=22, y=20))
    with pytest.raises(ConfigError, match="overlap"):
        load_config(cfg_dir)


def test_missing_file_fails(cfg_dir: Path) -> None:
    (cfg_dir / "items.yaml").unlink()
    with pytest.raises(ConfigError, match="items.yaml: file missing"):
        load_config(cfg_dir)


@pytest.mark.parametrize(
    ("raw", "secs"), [("45s", 45), ("5m", 300), ("1h", 3600), ("30d", 2_592_000), (12, 12)]
)
def test_durations(raw: object, secs: float) -> None:
    assert parse_duration(raw) == secs


def test_bad_duration() -> None:
    with pytest.raises(ValueError):
        parse_duration("soon")


def test_avatar_mode_config_is_wired() -> None:
    cfg = load_config(REPO_ROOT / "config")
    assert cfg.nodes.nodes["tree"].hits == 3
    assert set(cfg.combat.weapons) >= {"sword", "spear"}
    assert cfg.enemies.biomes["forest"].roster.keys() == {"wolf", "spider"}
    assert cfg.avatar.ko.rare_loss == 0.25


def test_node_yielding_unknown_item_fails(cfg_dir: Path) -> None:
    edit(cfg_dir, "nodes", lambda d: d["nodes"]["tree"]["yields"].update(unobtainium=[1, 2]))
    with pytest.raises(ConfigError, match="unobtainium"):
        load_config(cfg_dir)


def test_node_for_missing_map_object_fails(cfg_dir: Path) -> None:
    edit(cfg_dir, "nodes", lambda d: d["nodes"]["rock"]["objects"].append("obj.volcano"))
    with pytest.raises(ConfigError, match="obj.volcano"):
        load_config(cfg_dir)


def test_weapon_without_moveset_fails(cfg_dir: Path) -> None:
    edit(cfg_dir, "items", lambda d: d["items"]["training_spear"].update(weapon_type="bow"))
    with pytest.raises(ConfigError, match="bow"):
        load_config(cfg_dir)


def test_enemy_loot_and_roster_are_checked(cfg_dir: Path) -> None:
    def bad(d: dict) -> None:
        d["enemies"]["slime"]["loot"][0]["item"] = "dragon_scale"
        d["biomes"]["meadow"]["roster"]["goblin"] = 1.0

    edit(cfg_dir, "enemies", bad)
    with pytest.raises(ConfigError) as e:
        load_config(cfg_dir)
    assert "dragon_scale" in str(e.value) and "goblin" in str(e.value)


def test_bad_move_range_is_rejected(cfg_dir: Path) -> None:
    edit(cfg_dir, "combat", lambda d: d["weapons"]["sword"]["light"][0].update(range=40))
    with pytest.raises(ConfigError, match="range"):
        load_config(cfg_dir)
