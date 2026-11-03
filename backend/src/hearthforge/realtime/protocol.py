"""WebSocket message ids (docs/PROTOCOL.md). Shared with the client via /shared/protocol.json."""

from __future__ import annotations

import json
from typing import Any

import msgpack

from hearthforge.settings import REPO_ROOT

_IDS = json.loads((REPO_ROOT / "shared" / "protocol.json").read_text())
C2S: dict[str, int] = {k: int(v, 16) for k, v in _IDS["client_to_server"].items()}
S2C: dict[str, int] = {k: int(v, 16) for k, v in _IDS["server_to_client"].items()}
PROTOCOL_VERSION: int = _IDS["version"]
C2S_NAME = {v: k for k, v in C2S.items()}


def encode(op: str, *fields: Any) -> bytes:
    return msgpack.packb([S2C[op], *fields], use_bin_type=True)


def decode(data: bytes) -> tuple[str, list[Any]]:
    msg = msgpack.unpackb(data, raw=False, strict_map_key=False)
    if not isinstance(msg, list) or not msg or not isinstance(msg[0], int):
        raise ValueError("bad frame")
    name = C2S_NAME.get(msg[0])
    if name is None:
        raise ValueError(f"unknown op {msg[0]}")
    return name, msg[1:]


__all__ = ["C2S", "PROTOCOL_VERSION", "S2C", "decode", "encode"]
