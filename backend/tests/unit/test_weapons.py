"""Phase 11: the full weapon roster, statuses, offhands (shield, bombs, tome), consumables and armour."""

from __future__ import annotations

import pytest

from hearthforge.realtime.protocol import EV
from hearthforge.sim import motion as mo
from hearthforge.sim.combat import Combat, Monster
from hearthforge.sim.room import Player, RealmRoom
from hearthforge.sim.rules import (
    ATK_ABILITY,
    ATK_HEAVY,
    ATK_LIGHT,
    BTN_ABILITY,
    BTN_HEAVY,
    BTN_LIGHT,
    BTN_OFFHAND,
)
from tests.unit.test_combat import add_player, make_room, open_area, press, quiet, spawn

pytestmark = pytest.mark.nodb

WEAPONS = ["warhammer", "mace", "bow", "crystal_staff", "enchanted_sword", "harpoon", "arcane_bow"]


def armed(room: RealmRoom, kind: str, x: float, y: float, level: int = 10) -> Player:
    p = add_player(room, x, y, level=level)
    p.weapon = {"key": kind, "type": kind, "tier": 1, "rarity": "common"}
    p.m.ax, p.m.ay, p.m.fx, p.m.fy = 1.0, 0.0, 1.0, 0.0
    return p


def tank(room: RealmRoom, x: float, y: float, hp: float = 9999) -> Monster:
    m = spawn(room, "slime", x, y)
    m.hp = m.hp_max = hp
    m.state = "recover"
    m.speed = 0.0
    return m


def swing(room: RealmRoom, p: Player, button: int, ticks: int = 40) -> None:
    press(room, p, 1, ax=127, b=button)
    press(room, p, ticks, ax=127)


def test_every_new_moveset_is_complete(game_config) -> None:  # noqa: ANN001
    rules = make_room(game_config).rules
    for k in WEAPONS:
        w = rules.weapons[k]
        assert w.light and w.heavy.stamina > 0 and w.ability.cooldown > 0, k
        assert game_config.items_cfg.items[k].weapon_type == k


@pytest.mark.parametrize("kind", WEAPONS)
def test_each_weapon_lands_light_heavy_and_ability(game_config, kind: str) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, kind, x, y)
    dist = 2.2 if kind in ("bow", "crystal_staff", "arcane_bow") else 1.1
    m = tank(room, x + dist, y)
    for button in (BTN_LIGHT, BTN_HEAVY, BTN_ABILITY):
        m.x, m.y, m.kbx, m.kby = x + dist, y, 0.0, 0.0  # knockback pushed it away last time
        m.history.clear()
        p.m.x, p.m.y = x, y
        before = m.hp
        p.m.st = p.m.st_max
        if kind == "crystal_staff" and button == BTN_ABILITY:
            swing(room, p, button)
            assert room.combat.barriers, "the staff's ability raises a barrier"
            continue
        swing(room, p, button, 60)
        assert m.hp < before, f"{kind} {button} should hurt"


def test_hammer_slam_hits_all_around_and_quake_stuns(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "warhammer", x, y)
    around = [tank(room, x + dx, y + dy) for dx, dy in ((1.5, 0), (-1.5, 0), (0, 1.4), (0, -1.4))]
    swing(room, p, BTN_HEAVY)
    assert all(m.hp < m.hp_max for m in around)
    assert any(e[0] == EV["IMPACT"] for e in p.ev)
    swing(room, p, BTN_ABILITY, 12)
    assert all(m.stun > 0 for m in around)


def test_bow_volley_fans_and_heavy_pierces(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "bow", x, y)
    press(room, p, 1, ax=127, b=BTN_ABILITY)
    press(room, p, 5, ax=127)
    assert len(room.combat.projectiles) == game_config.combat.weapons["bow"].ability.count
    press(room, p, 40, ax=127)
    a, b = tank(room, x + 2.0, y), tank(room, x + 3.5, y)
    p.m.st = p.m.st_max
    swing(room, p, BTN_HEAVY, 40)
    assert a.hp < a.hp_max and b.hp < b.hp_max


def test_staff_orb_bursts_and_barrier_eats_shots(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "crystal_staff", x, y)
    hit, beside = tank(room, x + 3.0, y), tank(room, x + 3.0, y + 1.0)
    swing(room, p, BTN_HEAVY)
    assert hit.hp < hit.hp_max and beside.hp < beside.hp_max
    # a barrier between you and an archer
    for m in (hit, beside):
        room.combat._remove(m, killed=False)
    archer = spawn(room, "bandit_archer", x + 6.0, y, biome="forest")
    swing(room, p, BTN_ABILITY, 6)
    assert room.combat.barriers
    archer.state, archer.target = "chase", p.eid
    hp0 = p.hp
    for _ in range(50):
        press(room, p, 1)
    assert p.hp == hp0


def test_harpoon_pulls_it_in(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "harpoon", x, y)
    m = tank(room, x + 3.5, y)
    m.speed = 0.0
    swing(room, p, BTN_HEAVY, 20)
    assert m.x < x + 3.0


def test_burn_ticks_and_credits_the_kill(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "enchanted_sword", x, y)
    m = tank(room, x + 1.5, y, hp=500)
    swing(room, p, BTN_ABILITY, 10)  # elemental burst always burns
    assert m.burn[1] > 0
    hp = m.hp
    press(room, p, room.hz * 2)
    assert m.hp < hp
    m.hp = 1
    xp0 = p.xp
    press(room, p, room.hz + 1)
    assert m.id not in room.combat.monsters and p.xp > xp0


def test_shield_blocks_from_the_front_only(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "sword", x, y)
    room.set_offhand(
        p, {"key": "shield", "type": "shield", "tier": 1, "rarity": "common", "instance_id": "s"}
    )
    press(room, p, 1, b=BTN_OFFHAND)
    assert p.blocking
    p.hp = 100.0
    room.combat.damage_player(p, 40, 0, 0, frm=(x + 3, y))  # in front
    front = 100 - p.hp
    p.hp = 100.0
    room.combat.damage_player(p, 40, 0, 0, frm=(x - 3, y))  # behind
    back = 100 - p.hp
    assert front < back * 0.6
    assert p.m.st < p.m.st_max


def test_bombs_have_charges_a_fuse_and_recharge(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "sword", x, y)
    room.set_offhand(
        p, {"key": "barrel_bombs", "type": "bombs", "tier": 1, "rarity": "common", "instance_id": "b"}
    )
    m = tank(room, x + 3.5, y)
    full = game_config.combat.offhands.bombs.charges
    assert p.charges == full
    press(room, p, 1, ax=127, b=BTN_OFFHAND)
    press(room, p, 1, ax=127)
    assert p.charges == full - 1 and room.combat.bombs
    press(room, p, int(game_config.combat.offhands.bombs.fuse * room.hz) + 2)
    assert not room.combat.bombs and m.hp < m.hp_max
    press(room, p, int(game_config.combat.offhands.bombs.recharge * room.hz) + room.hz)
    assert p.charges == full


def test_tome_element_follows_its_modifier(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "sword", x, y)
    tome = {
        "key": "elemental_tome",
        "type": "tome",
        "tier": 1,
        "rarity": "uncommon",
        "instance_id": "t",
        "modifiers": [{"key": "frost", "effect": "frost", "value": 0.3}],
    }
    room.set_offhand(p, tome)
    m = tank(room, x + 3.0, y)
    press(room, p, 1, ax=127, b=BTN_OFFHAND)
    press(room, p, 30, ax=127)
    assert m.hp < m.hp_max and m.slow > 0
    press(room, p, 1, ax=127, b=BTN_OFFHAND)  # cooling down
    assert not room.combat.projectiles


def give_quick(p: Player, slot: int, key: str, qty: int = 3) -> None:
    p.quick[4 + slot] = [key, qty]


def test_potions_food_and_stamina(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "sword", x, y)
    give_quick(p, 0, "healing_potion")
    p.hp = 10.0
    room.use_quick(p, 0)
    assert p.hp == pytest.approx(10 + round(p.stats.hp_max * 0.6))
    assert p.quick[4][1] == 2 and p.pending.consumed["healing_potion"] == 1
    room.use_quick(p, 0)  # shared potion cooldown
    assert p.quick[4][1] == 2
    # stamina potion: full stamina and faster regen, through your own movement rules
    give_quick(p, 1, "stamina_potion")
    p.m.st = 0
    room.use_quick(p, 1)
    assert p.m.st == p.m.st_max and p.mods[2] == 1.5 and p.rules is not None
    assert p.rules.st_regen == room.rules.st_regen * 1.5
    # food: +10% damage for 5 minutes
    give_quick(p, 2, "warrior_stew")
    m = tank(room, x + 1.2, y)
    mv = room.rules.weapons["sword"].light[0]
    before, _ = room.combat.damage_out(p, mv, m)
    room.use_quick(p, 2)
    after, _ = room.combat.damage_out(p, mv, m)
    assert after > before
    assert any(e[0] == EV["BUFF"] for e in p.ev)
    # it wears off
    room.tick_no = p.food[2] + 1  # type: ignore[index]
    room.tick_buffs(p, room.tick_no)
    assert room.food(p, "damage") == 0.0


def test_swift_food_and_plate_change_movement_exactly(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    base = armed(room, "sword", x, y)
    plate = armed(room, "sword", x, y + 2)
    plate.armour_key = "plate_armour"
    room.recompute_mods(plate)
    assert plate.mods == (0.95, 0.9, 1.0)
    assert plate.rules is not None and plate.rules.speed_tick == room.rules.speed_tick * 0.95
    assert any(e[0] == EV["MOVE_MODS"] for e in plate.ev)
    for p in (base, plate):
        for _ in range(10):
            p.last_seq += 1
            p.inputs.append(
                __import__("hearthforge.sim.room", fromlist=["Input"]).Input(
                    p.last_seq, p.last_seq, 0, 127, 0, 0, 0, 0
                )
            )
    for _ in range(10):
        room.tick()
    assert plate.m.x - x < base.m.x - x


def test_modifier_procs_poison_and_lifesteal(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    quiet(room)
    x, y = open_area(room)
    p = armed(room, "sword", x, y)
    p.weapon["modifiers"] = [{"effect": "venom", "value": 1.0}, {"effect": "lifesteal", "value": 0.5}]
    p.weapon["instance_id"] = "w"
    p.weapon["durability"] = 50
    m = tank(room, x + 1.2, y)
    p.hp = 50.0
    room.combat.hit_monster(p, m, room.rules.weapons["sword"].light[0], m.x, m.y)
    assert m.poison[1] > 0 and p.hp > 50.0


def test_combat_starts_attacks_with_the_right_kinds() -> None:
    assert (ATK_LIGHT, ATK_HEAVY, ATK_ABILITY) == (1, 2, 3)
    assert mo.Motion is not None and Combat is not None
