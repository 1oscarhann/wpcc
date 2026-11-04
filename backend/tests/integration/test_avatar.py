"""Avatar Mode end to end over a real socket: join, move, chop a tree, pick up, walk home, deposit."""

from __future__ import annotations

import time
import uuid
from typing import Any

import msgpack
from starlette.testclient import TestClient

from hearthforge.main import create_app
from hearthforge.realtime.protocol import C2S, EV, S2C
from hearthforge.settings import Settings
from hearthforge.sim.rules import BTN_LIGHT
from tests.conftest import DEFAULT_LOOK


def pack(op: str, *fields: Any) -> bytes:
    return msgpack.packb([C2S[op], *fields], use_bin_type=True)


def unpack(data: bytes) -> list[Any]:
    return msgpack.unpackb(data, raw=False, strict_map_key=False)


class Bot:
    """Drives one socket like the client does: one INPUT per SNAPSHOT received."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.seq = 0
        self.events: list[list[Any]] = []
        self.last: list[Any] | None = None

    def recv_until(self, op: str, limit: int = 200) -> list[Any]:
        for _ in range(limit):
            msg = unpack(self.ws.receive_bytes())
            if msg[0] == S2C["SNAPSHOT"]:
                self.last = msg
                self.events.extend(msg[5])
            if msg[0] == S2C[op]:
                return msg
        raise AssertionError(f"no {op}")

    def step(self, mx: int = 0, my: int = 0, ax: int = 0, ay: int = 0, buttons: int = 0) -> list[Any]:
        self.seq += 1
        self.ws.send_bytes(pack("INPUT", self.seq, self.seq, 0, mx, my, ax, ay, buttons))
        return self.recv_until("SNAPSHOT")

    def events_of(self, kind: str) -> list[list[Any]]:
        return [e for e in self.events if e[0] == EV[kind]]


def make_app(settings: Settings, game_config: Any) -> Any:
    s = settings.model_copy(update={"cookie_secure": False, "frontend_origins": ["http://testserver"]})
    return create_app(settings=s, config=game_config)


def signup(client: TestClient, name: str) -> dict[str, Any]:
    r = client.post(
        "/api/auth/signup", json={"username": name, "password": "longenough", "appearance": DEFAULT_LOOK}
    )
    assert r.status_code == 201, r.text
    return r.json()


def find_tree(room: Any, p: Any) -> tuple[int, int]:
    """A tree just outside the village fence with open ground on its left."""
    hx, hy, hw, hh = p.home_rect
    for y in range(hy - 6, hy + hh + 6):
        for x in range(hx - 8, hx + hw + 8):
            if room.grid.node_at(x, y) == "tree" and not room.grid.solid(x - 1, y):
                return x, y
    raise AssertionError("no tree near home")


def test_enter_move_gather_pickup_deposit(settings: Settings, game_config: Any, database_url: str) -> None:
    app = make_app(settings, game_config)
    with TestClient(app, base_url="http://testserver") as client:
        me = signup(client, "Lumberjack")
        st = app.state.hf
        with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            bot = Bot(ws)
            ws.send_bytes(pack("ENTER_AVATAR"))
            joined = bot.recv_until("ROOM_JOINED")
            _realm, _tick, eid, self_state, info, blocks, _claimed, _depleted, roster = joined[1:]
            assert roster[0][0] == eid and roster[0][2] == "Lumberjack"
            assert blocks, "the fence and buildings collide"
            door = info["home"]["door"]
            assert self_state[0] == door[0] and self_state[1] == door[1]
            assert info["weapon"]["type"] == "sword"

            # walking: the server moves us and acks our inputs
            y0 = self_state[1]
            for _ in range(8):
                snap = bot.step(my=127)
            assert bot.seq - 2 <= snap[2] <= bot.seq  # acks trail by a tick or so (snapshots are async)
            assert snap[3][1] > y0 + 1.0

            # chop a tree: three swings deplete it for us, and the wood drops and flies into the bag
            room, p = st.rooms.find(uuid.UUID(me["user_id"]))
            tx, ty = find_tree(room, p)
            p.m.x, p.m.y = tx - 0.4, ty + 0.5
            for _ in range(40):
                bot.step(ax=127, buttons=BTN_LIGHT)
                if any(e[4] == 1 for e in bot.events_of("NODE")):
                    break
            node_ev = bot.events_of("NODE")
            assert [e[2] for e in node_ev] == [1, 2, 3] and node_ev[-1][4] == 1
            for _ in range(12):
                bot.step()
            picked = bot.events_of("PICKUP")
            assert picked and picked[0][2] == "wood"
            wood = sum(e[3] for e in picked if e[2] == "wood")
            assert 6 <= wood <= 10
            assert bot.events_of("XP")[0][1] == game_config.nodes.nodes["tree"].xp
            # the depleted tree ignores more swings (a neighbouring tree may take them instead)
            nid = node_ev[-1][1]
            n_before = len([e for e in bot.events_of("NODE") if e[1] == nid])
            for _ in range(10):
                bot.step(ax=127, buttons=BTN_LIGHT)
            assert len([e for e in bot.events_of("NODE") if e[1] == nid]) == n_before

            # the write-behind flush puts it in the real inventory
            deadline = time.time() + 5
            inv: dict[str, Any] = {}
            while time.time() < deadline:
                bot.step()
                inv = client.get("/api/inventory").json()
                if any(s["item"] == "wood" for s in inv["inventory"]["slots"]):
                    break
            assert sum(s["qty"] for s in inv["inventory"]["slots"] if s["item"] == "wood") >= wood
            before = client.get("/api/village").json()["village"]["resources"]["wood"]["amount"]

            # walk home: resources deposit into village storage by themselves
            p.m.x, p.m.y = door
            deadline = time.time() + 6
            while time.time() < deadline and not bot.events_of("DEPOSIT"):
                bot.step()
            deposited = bot.events_of("DEPOSIT")[0][1]
            assert deposited["wood"] >= wood  # plus whatever the neighbouring tree gave
            after = client.get("/api/village").json()["village"]["resources"]["wood"]["amount"]
            assert after >= before + deposited["wood"] - 1  # production may tick in between
            inv = client.get("/api/inventory").json()
            assert not any(s["item"] == "wood" for s in inv["inventory"]["slots"])

            ws.send_bytes(pack("LEAVE_AVATAR"))
            left = bot.recv_until("ROOM_LEFT")
            assert left[1] == 0
            assert st.rooms.find(uuid.UUID(me["user_id"])) is None


def test_bad_inputs_are_rejected_and_speed_is_capped(
    settings: Settings, game_config: Any, database_url: str
) -> None:
    app = make_app(settings, game_config)
    with TestClient(app, base_url="http://testserver") as client:
        me = signup(client, "Speedy")
        with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            bot = Bot(ws)
            ws.send_bytes(pack("ENTER_AVATAR"))
            joined = bot.recv_until("ROOM_JOINED")
            x0 = joined[4][0]
            room, p = app.state.hf.rooms.find(uuid.UUID(me["user_id"]))
            # out-of-range stick, wrong arity and replayed seqs are dropped
            assert not room.on_input(p, [1, 1, 0, 9000, 0, 0, 0, 0])
            assert not room.on_input(p, [1, 1, 0])
            assert room.on_input(p, [5, 5, 0, 0, 0, 0, 0, 0])
            assert not room.on_input(p, [5, 5, 0, 0, 0, 0, 0, 0])
            bot.seq = 5
            p.m.x, p.m.y = p.home_door
            n = 20
            for _ in range(n):
                bot.step(mx=-127)
            moved = abs(bot.last[3][0] - p.home_door[0])
            assert moved <= (n + 2) * room.rules.speed_tick + 1e-6
            assert x0 == p.home_door[0]


def test_reconnect_resumes_the_same_avatar(settings: Settings, game_config: Any, database_url: str) -> None:
    app = make_app(settings, game_config)
    with TestClient(app, base_url="http://testserver") as client:
        me = signup(client, "Comeback")
        with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            bot = Bot(ws)
            ws.send_bytes(pack("ENTER_AVATAR"))
            first = bot.recv_until("ROOM_JOINED")
            for _ in range(6):
                bot.step(mx=127)
            x_at_drop = bot.last[3][0]
        room, p = app.state.hf.rooms.find(uuid.UUID(me["user_id"]))
        assert p.linkdead > 0
        with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            bot = Bot(ws)
            ws.send_bytes(pack("ENTER_AVATAR"))
            again = bot.recv_until("ROOM_JOINED")
            assert again[3] == first[3]  # same entity
            assert abs(again[4][0] - x_at_drop) < 0.6
