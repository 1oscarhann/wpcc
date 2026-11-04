"""One WebSocket per tab. Sends are serialised so the village hub and the realm room never interleave."""

from __future__ import annotations

import asyncio

from fastapi import WebSocket


class Conn:
    def __init__(self, ws: WebSocket, user_id: str) -> None:
        self.ws = ws
        self.user_id = user_id
        self._lock = asyncio.Lock()
        self.closed = False

    async def send_bytes(self, data: bytes) -> None:
        if self.closed:
            raise ConnectionError("closed")
        async with self._lock:
            await self.ws.send_bytes(data)

    def __hash__(self) -> int:
        return id(self)
