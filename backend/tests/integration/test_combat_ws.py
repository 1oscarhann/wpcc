"""Combat over a real socket: kill → coins in the wallet; KO → marker persisted → recovered later."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from starlette.testclient import TestClient

from hearthforge.db.models import DeathDrop, Transaction
from hearthforge.sim.rules import BTN_LIGHT
from tests.integration.test_avatar import Bot, make_app, pack, signup


def test_kill_loot_and_ko_marker(settings, game_config, database_url) -> None:  # noqa: ANN001
    s = settings.model_copy(update={"monsters_enabled": True})
    app = make_app(s, game_config)
    with TestClient(app, base_url="http://testserver") as client:
        me = signup(client, "Brawler")
        st = app.state.hf
        uid = uuid.UUID(me["user_id"])
        with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            bot = Bot(ws)
            ws.send_bytes(pack("ENTER_AVATAR"))
            bot.recv_until("ROOM_JOINED")
            room, p = st.rooms.find(uid)
            assert room.combat is not None
            room.combat._wake = lambda t: None  # only our test slime

            # a slime right in front of us, standing still
            from tests.unit.test_combat import spawn

            hx, hy, hw, hh = p.home_rect  # fight just outside the west fence (villages are monster-free)
            x, y = hx - 6.5, hy + hh / 2
            for dx in range(0, 12):
                if not room.grid.solid(int(x - dx), int(y)) and not room.grid.solid(int(x - dx) - 1, int(y)):
                    x = int(x - dx) + 0.5
                    break
            p.m.x, p.m.y = x, y
            m = spawn(room, "slime", x + 1.2, y)
            m.state = "recover"
            m.st_t = -10_000
            for _ in range(60):
                bot.step(ax=127, buttons=BTN_LIGHT)
                if bot.events_of("DEATH"):
                    break
            assert bot.events_of("HIT") and bot.events_of("DEATH")
            for _ in range(100):  # generous: under a loaded test run ticks can bunch up
                bot.step()
                if any(e[2] == "coins" for e in bot.events_of("PICKUP")):
                    break
            assert any(e[2] == "coins" for e in bot.events_of("PICKUP"))
            assert bot.events_of("XP")

            # KO with rare materials in the bag: a share drops as a marker and is written down
            room.inv_add(p, "ironbark", 8)
            p.pending.grants["ironbark"] += 8
            deadline = time.time() + 4
            while time.time() < deadline and p.pending.grants:
                bot.step()
            room.combat.damage_player(p, 100_000, 0, kind=0)
            ko = None
            for _ in range(10):
                bot.step()
                if bot.events_of("KO"):
                    ko = bot.events_of("KO")[0]
                    break
            assert ko is not None and ko[2] == {"ironbark": 2}
            deadline = time.time() + 5
            rows: list[Any] = []
            while time.time() < deadline and not rows:
                bot.step()
                rows = run_sql(client, st, select(DeathDrop).where(DeathDrop.user_id == uid))
            assert rows and rows[0].items == [{"item_key": "ironbark", "qty": 2}]
            marker = (rows[0].x, rows[0].y)

        # come back later (new room): the marker is still there, walk onto it to get the rares back
        room, p = st.rooms.find(uid)
        client.portal.call(room.remove_player, p, 0)
        with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            bot = Bot(ws)
            ws.send_bytes(pack("ENTER_AVATAR"))
            bot.recv_until("ROOM_JOINED")
            room, p = st.rooms.find(uid)
            assert any(d.death_id == rows[0].id for d in room.drops.values())
            p.ko = 0
            p.m.x, p.m.y = marker
            for _ in range(20):
                bot.step()
                if any(e[2] == "ironbark" for e in bot.events_of("PICKUP")):
                    break
            assert any(e[2] == "ironbark" and e[3] == 2 for e in bot.events_of("PICKUP"))
            deadline = time.time() + 5
            done: list[Any] = []
            while time.time() < deadline and not done:
                bot.step()
                done = run_sql(client, st, select(DeathDrop).where(DeathDrop.recovered_at.is_not(None)))
            assert done
            reasons = {
                t.reason for t in run_sql(client, st, select(Transaction).where(Transaction.user_id == uid))
            }
            assert {"loot.coins", "ko.loss", "ko.recover"} <= reasons


def run_sql(client: TestClient, st: Any, stmt: Any) -> list[Any]:
    """Query on the app's own event loop (the TestClient portal)."""

    async def go() -> list[Any]:
        async with st.sessionmaker() as s:
            return list((await s.execute(stmt)).scalars())

    return client.portal.call(go)  # type: ignore[union-attr]


def test_merchant_needs_you_at_the_cart(settings, game_config, database_url) -> None:  # noqa: ANN001
    """Presence is checked against the real room: from Build Mode you can look, at the cart you can buy."""
    app = make_app(settings, game_config)
    with TestClient(app, base_url="http://testserver") as client:
        me = signup(client, "Shopper")
        st = app.state.hf
        uid = uuid.UUID(me["user_id"])
        headers = {"x-csrf-token": me["csrf_token"]}
        view = client.get("/api/merchant/hub").json()
        hint_or_cheap = min(view["slots"], key=lambda s: s["price"])
        body = {"slot": hint_or_cheap["slot"], "rotation": view["rotation"]}
        r = client.post(
            "/api/merchant/hub/buy", json=body, headers={**headers, "idempotency-key": str(uuid.uuid4())}
        )
        assert r.json()["error"]["code"] == "too_far"
        with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            bot = Bot(ws)
            ws.send_bytes(pack("ENTER_AVATAR"))
            bot.recv_until("ROOM_JOINED")
            _room, p = st.rooms.find(uid)
            p.m.x, p.m.y = view["pos"][0] + 1.0, view["pos"][1] + 1.0  # stroll over to the cart
            assert client.get("/api/merchant/hub").json()["near"] is True
            r = client.post(
                "/api/merchant/hub/buy", json=body, headers={**headers, "idempotency-key": str(uuid.uuid4())}
            )
            # 200 unless that slot is a hint with nothing left to hint or more than the starter coins
            assert r.status_code == 200 or r.json()["error"]["code"] in (
                "insufficient_coins",
                "nothing_to_hint",
            ), r.text
