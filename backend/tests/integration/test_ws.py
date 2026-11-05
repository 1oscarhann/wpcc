from __future__ import annotations

import uuid
from typing import Any

import msgpack
from starlette.testclient import TestClient

from hearthforge.main import create_app
from hearthforge.realtime.protocol import C2S, S2C
from hearthforge.settings import Settings
from tests.conftest import DEFAULT_LOOK


def pack(op: str, *fields: Any) -> bytes:
    return msgpack.packb([C2S[op], *fields], use_bin_type=True)


def unpack(data: bytes) -> list[Any]:
    return msgpack.unpackb(data, raw=False)


def test_village_channel_pushes_state(settings: Settings, game_config: Any, database_url: str) -> None:
    s = settings.model_copy(update={"cookie_secure": False, "frontend_origins": ["http://testserver"]})
    app = create_app(settings=s, config=game_config)
    with TestClient(app, base_url="http://testserver") as client:
        r = client.post(
            "/api/auth/signup",
            json={"username": "Socket", "password": "longenough", "appearance": DEFAULT_LOOK},
        )
        assert r.status_code == 201, r.text
        csrf = r.json()["csrf_token"]
        with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            ws.send_bytes(pack("HELLO", 1, "test", False))
            welcome = unpack(ws.receive_bytes())
            assert welcome[0] == S2C["WELCOME"] and welcome[1] == r.json()["user_id"]
            ws.send_bytes(pack("PING", 123.0))
            assert unpack(ws.receive_bytes())[0] == S2C["PONG"]
            ws.send_bytes(pack("SUB_VILLAGE", r.json()["user_id"]))
            state = unpack(ws.receive_bytes())
            assert state[0] == S2C["VILLAGE_STATE"]
            v0 = state[2]
            # a REST change is pushed to the socket (pick a spot the random debris left free)
            spot = next(
                (x, y)
                for y in range(18, 30)
                for x in range(26, 34)
                if client.get(f"/api/village/preview?key=house&x={x}&y={y}").json()["valid"]
            )
            r2 = client.post(
                "/api/village/buildings",
                json={"key": "house", "x": spot[0], "y": spot[1], "rotation": 0},
                headers={"x-csrf-token": csrf, "idempotency-key": str(uuid.uuid4())},
            )
            assert r2.status_code == 200, r2.text
            pushed = unpack(ws.receive_bytes())
            assert pushed[0] == S2C["VILLAGE_STATE"] and pushed[2] > v0
            assert any(b["key"] == "house" and b["state"] == "constructing" for b in pushed[3]["buildings"])
            # someone else's village is refused (visits arrive in Phase 15)
            ws.send_bytes(pack("SUB_VILLAGE", "00000000-0000-0000-0000-000000000000"))
            assert unpack(ws.receive_bytes())[0] == S2C["ERROR"]


def test_ws_rejects_anonymous_and_foreign_origin(
    settings: Settings, game_config: Any, database_url: str
) -> None:
    import pytest
    from starlette.websockets import WebSocketDisconnect

    s = settings.model_copy(update={"cookie_secure": False, "frontend_origins": ["http://testserver"]})
    app = create_app(settings=s, config=game_config)
    with TestClient(app, base_url="http://testserver") as client:
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws") as ws:
            ws.receive_bytes()
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws,
        ):
            ws.receive_bytes()
