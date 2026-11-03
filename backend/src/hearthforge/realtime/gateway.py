"""/ws gateway: one socket per tab, msgpack frames (docs/PROTOCOL.md)."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hearthforge.api.deps import SESSION_COOKIE
from hearthforge.clock import to_ms
from hearthforge.realtime.protocol import PROTOCOL_VERSION, decode, encode
from hearthforge.services import sessions
from hearthforge.state import AppState

log = logging.getLogger("hearthforge.ws")
router = APIRouter()

MAX_MSGS_PER_SEC = 30
MAX_STRIKES = 3


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    st: AppState = ws.app.state.hf
    origin = ws.headers.get("origin")
    host_origin = f"{'https' if ws.url.scheme == 'wss' else 'http'}://{ws.headers.get('host', '')}"
    if origin and origin not in st.settings.frontend_origins and origin != host_origin:
        await ws.close(code=4403)
        return
    token = ws.cookies.get(SESSION_COOKIE)
    if not token:
        await ws.close(code=4401)
        return
    async with st.sessionmaker() as session:
        found = await sessions.lookup(session, token, st.clock.now())
    if found is None:
        await ws.close(code=4401)
        return
    _, user = found
    user_id = str(user.id)
    await ws.accept()
    hub = st.village_hub
    assert hub is not None
    window_start, count, strikes = time.monotonic(), 0, 0
    try:
        while True:
            data = await ws.receive_bytes()
            now_m = time.monotonic()
            if now_m - window_start >= 1.0:
                window_start, count = now_m, 0
            count += 1
            if count > MAX_MSGS_PER_SEC:
                continue
            try:
                op, fields = decode(data)
            except (ValueError, TypeError, Exception):  # noqa: BLE001
                strikes += 1
                if strikes >= MAX_STRIKES:
                    await ws.send_bytes(encode("KICK", 1))
                    await ws.close(code=4400)
                    return
                continue
            if op == "HELLO":
                await ws.send_bytes(
                    encode(
                        "WELCOME",
                        user_id,
                        to_ms(st.clock.now()),
                        st.config.game.tick_rate_hz,
                        PROTOCOL_VERSION,
                        st.config.hash,
                        False,
                    )
                )
            elif op == "PING":
                await ws.send_bytes(encode("PONG", fields[0] if fields else 0, to_ms(st.clock.now()), 0))
            elif op == "SUB_VILLAGE":
                owner = str(fields[0]) if fields else user_id
                if owner != user_id:  # visiting friends arrives in Phase 15
                    await ws.send_bytes(encode("ERROR", 403, "err.not_allowed", {}))
                    continue
                hub.subscribe(owner, ws)
                await hub.publish(owner)
            elif op == "UNSUB_VILLAGE":
                hub.unsubscribe(str(fields[0]) if fields else user_id, ws)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("ws error for %s", user_id)
    finally:
        hub.unsubscribe_all(ws)
