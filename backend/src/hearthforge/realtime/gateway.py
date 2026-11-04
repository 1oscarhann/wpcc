"""/ws gateway: one socket per tab, msgpack frames (docs/PROTOCOL.md)."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hearthforge.api.deps import SESSION_COOKIE
from hearthforge.clock import to_ms
from hearthforge.core.errors import GameError
from hearthforge.realtime.conn import Conn
from hearthforge.realtime.protocol import PROTOCOL_VERSION, decode, encode
from hearthforge.services import sessions
from hearthforge.state import AppState

log = logging.getLogger("hearthforge.ws")
router = APIRouter()

MAX_MSGS_PER_SEC = 30  # everything except INPUT (pings, subscriptions, actions)
MAX_STRIKES = 3
MAX_INPUT_STRIKES = 25


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
    rooms = st.rooms
    assert hub is not None and rooms is not None
    conn = Conn(ws, user_id)
    uid = uuid.UUID(user_id)
    player = None
    room = None
    window_start, count, strikes, input_strikes = time.monotonic(), 0, 0, 0
    try:
        while True:
            data = await ws.receive_bytes()
            try:
                op, fields = decode(data)
            except (ValueError, TypeError, Exception):  # noqa: BLE001
                strikes += 1
                if strikes >= MAX_STRIKES:
                    await conn.send_bytes(encode("KICK", 1))
                    await ws.close(code=4400)
                    return
                continue
            if op != "INPUT":  # inputs have their own burst-tolerant bucket in the room
                now_m = time.monotonic()
                if now_m - window_start >= 1.0:
                    window_start, count = now_m, 0
                count += 1
                if count > MAX_MSGS_PER_SEC:
                    continue
            if op == "INPUT":
                if player is None or room is None or room.players.get(player.eid) is not player:
                    continue
                if not room.on_input(player, fields):
                    input_strikes += 1
                    if input_strikes >= MAX_INPUT_STRIKES:
                        log.warning("kicking %s: bad inputs", user_id)
                        await conn.send_bytes(encode("KICK", 1))
                        await ws.close(code=4400)
                        return
                continue
            if op == "HELLO":
                await conn.send_bytes(
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
                tick = room.tick_no if room is not None else 0
                await conn.send_bytes(encode("PONG", fields[0] if fields else 0, to_ms(st.clock.now()), tick))
            elif op == "ENTER_AVATAR":
                try:
                    room, player = await rooms.enter(conn, uid)
                except GameError as e:
                    await conn.send_bytes(encode("ERROR", 409, f"err.{e.code}", {}))
            elif op == "LEAVE_AVATAR":
                try:
                    await rooms.leave(uid, conn)
                    room, player = None, None
                except GameError as e:
                    await conn.send_bytes(encode("ERROR", 409, f"err.{e.code}", {}))
            elif op == "SUB_VILLAGE":
                owner = str(fields[0]) if fields else user_id
                if owner != user_id:  # visiting friends arrives in Phase 15
                    await conn.send_bytes(encode("ERROR", 403, "err.not_allowed", {}))
                    continue
                hub.subscribe(owner, conn)
                await hub.publish(owner)
            elif op == "UNSUB_VILLAGE":
                hub.unsubscribe(str(fields[0]) if fields else user_id, conn)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("ws error for %s", user_id)
    finally:
        conn.closed = True
        hub.unsubscribe_all(conn)
        rooms.disconnected(conn)
