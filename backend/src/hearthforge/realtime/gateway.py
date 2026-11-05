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
LIVE: dict[str, int] = {}  # user id → open sockets in this process


async def _same_realm(st: AppState, uid: uuid.UUID, other: str) -> bool:
    from sqlalchemy import select

    from hearthforge.db.models import RealmMember

    try:
        oid = uuid.UUID(other)
    except ValueError:
        return False
    async with st.sessionmaker() as s:
        rows = (
            (await s.execute(select(RealmMember.realm_id).where(RealmMember.user_id.in_([uid, oid]))))
            .scalars()
            .all()
        )
    return len(rows) == 2 and rows[0] == rows[1]


async def _last_socket_closed(st: AppState, uid: uuid.UUID) -> None:
    """Snapshot the village for the 'While you were away' card (Phase 8)."""
    from hearthforge.services import away

    try:
        async with st.sessionmaker() as s, s.begin():
            await away.snapshot(s, st.config, uid, st.clock.now())
    except Exception:  # noqa: BLE001 - a missed snapshot only means no away card next time
        log.exception("away snapshot failed for %s", uid)


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
    LIVE[user_id] = LIVE.get(user_id, 0) + 1
    hub.register(conn)
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
                # your own village, or a realm-mate's (Phase 9); visiting friends arrives in Phase 15
                if owner != user_id and not await _same_realm(st, uid, owner):
                    await conn.send_bytes(encode("ERROR", 403, "err.not_allowed", {}))
                    continue
                hub.subscribe(owner, conn)
                await hub.publish(owner)
            elif op == "PARTY":
                if player is None or room is None:
                    continue
                action = fields[0] if fields else None
                err = None
                if action == "invite" and len(fields) > 1 and isinstance(fields[1], int):
                    err = rooms.invite(room, player, fields[1])
                elif action == "accept" and len(fields) > 1 and isinstance(fields[1], str):
                    err = rooms.accept(room, player, fields[1])
                elif action == "leave":
                    rooms.leave_party(player.user_id)
                if err:
                    room.toast(player, f"party_{err}")
            elif op == "TRAVEL":
                if player is None or room is None or not fields or not isinstance(fields[0], int):
                    continue
                err = room.travel(player, fields[0])
                if err:
                    room.toast(player, f"travel_{err}")
            elif op == "INTERACT":
                if player is None or room is None or not fields or not isinstance(fields[0], int):
                    continue
                room.interact(player, fields[0])
            elif op == "UNSUB_VILLAGE":
                hub.unsubscribe(str(fields[0]) if fields else user_id, conn)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("ws error for %s", user_id)
    finally:
        conn.closed = True
        hub.unsubscribe_all(conn)
        hub.unregister(conn)
        rooms.disconnected(conn)
        LIVE[user_id] = LIVE.get(user_id, 1) - 1
        if LIVE[user_id] <= 0:
            LIVE.pop(user_id, None)
            await _last_socket_closed(st, uid)
