"""Phase 15/16 in the room: emotes, quick messages and pings (range, rate, blocks), and skill perks."""

from __future__ import annotations

import pytest

from hearthforge.domain import skills as skills_dom
from hearthforge.realtime.protocol import EV
from hearthforge.sim.stats import stats_for
from tests.unit.test_combat import add_player, make_room, open_area, spawn

pytestmark = pytest.mark.nodb


def chats(p) -> list:  # noqa: ANN001
    return [e for e in p.ev if e[0] in (EV["CHAT"], EV["PING"])]


def test_chat_reaches_neighbours_but_not_blocked_or_far(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    x, y = open_area(room)
    a, b, far, rude = (
        add_player(room, x, y),
        add_player(room, x + 3, y),
        add_player(room, x + 200, y),
        add_player(room, x - 2, y),
    )
    rude.blocked.add(a.user_id)  # blocks are symmetric in effect
    assert room.chat(a, "emote", "wave") is None
    assert [e[2:] for e in chats(b)] == [["emote", "wave"]]
    assert chats(far) == [] and chats(rude) == []
    assert room.chat(a, "say", 0) == "slow"  # one per second
    room.tick_no += room.hz
    assert room.chat(a, "say", 99) == "bad" and room.chat(a, "emote", "rude_gesture") == "bad"
    assert room.chat(a, "say", 1) is None
    assert room.ping(a, x + 50, y) is None
    assert any(e[0] == EV["PING"] for e in far.ev)  # pings reach the whole realm
    assert room.ping(a, x, y) == "slow"


def test_perks_add_up_and_change_stats(game_config) -> None:  # noqa: ANN001
    cfg = game_config
    perks = skills_dom.perks(cfg, {"power": 3, "toughness": 2, "guard": 1})
    assert (
        perks["damage"] == pytest.approx(0.09)
        and perks["hp"] == pytest.approx(0.10)
        and perks["defence"] == 3
    )
    base = stats_for(cfg, 10)
    boosted = stats_for(cfg, 10, perks)
    assert boosted.hp_max == round(base.hp_max * 1.1) and boosted.defence == base.defence + 3
    # learning rules
    assert skills_dom.learn_error(cfg, {}, 1, "power") == "no_points"
    assert skills_dom.learn_error(cfg, {}, 5, "precision") == "locked"
    assert skills_dom.learn_error(cfg, {"power": 5}, 10, "power") == "maxed"
    assert skills_dom.learn_error(cfg, {}, 5, "nope") == "unknown_skill"


def test_power_hits_harder(game_config) -> None:  # noqa: ANN001
    room = make_room(game_config)
    room.combat._wake = lambda t: None  # type: ignore[method-assign]
    x, y = open_area(room)
    p = add_player(room, x, y, level=10)
    m = spawn(room, "big_slime", x + 1, y)
    mv = room.rules.weapons["sword"].moves[0] if hasattr(room.rules.weapons["sword"], "moves") else None
    if mv is None:
        mv = next(iter(room.rules.weapons["sword"].light))  # type: ignore[attr-defined]
    room.rng.seed(3)
    plain, _ = room.combat.damage_out(p, mv, m)
    p.perks = {"damage": 0.5}
    room.rng.seed(3)
    strong, _ = room.combat.damage_out(p, mv, m)
    assert strong > plain
