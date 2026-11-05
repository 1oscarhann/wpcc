"""Idempotency keys for spend/sell/buy requests (PROTOCOL §5).

The key row is inserted in the *same transaction* as the action, so it exists exactly when the
action committed:

- first request → the insert wins, the action runs, the response is stored, all commit together;
- replay after commit → the insert conflicts, we return the stored response (no second effect);
- concurrent replay → Postgres makes the second insert wait on the first transaction; it then
  conflicts (first committed → stored response) or goes ahead (first rolled back → nothing happened);
- a failed action rolls the key back too, so the client may retry with the same key;
- the same key with a different endpoint or body → 422.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import Header
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.core.errors import GameError
from hearthforge.db.models import IdempotencyKey

HEADER = "Idempotency-Key"
TTL = timedelta(hours=24)


def require_key(idempotency_key: str | None = Header(default=None, alias=HEADER)) -> uuid.UUID:
    """FastAPI dependency: a UUID `Idempotency-Key` header is mandatory on spend/sell/buy routes."""
    if not idempotency_key:
        raise GameError("idempotency_key_required", "Missing Idempotency-Key header.")
    try:
        return uuid.UUID(idempotency_key)
    except ValueError:
        raise GameError("idempotency_key_invalid", "Idempotency-Key must be a UUID.") from None


def request_hash(endpoint: str, body: Any) -> bytes:
    canonical = json.dumps({"e": endpoint, "b": body}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).digest()


async def claim(
    session: AsyncSession, user_id: uuid.UUID, key: uuid.UUID, endpoint: str, body: Any, now: datetime
) -> dict[str, Any] | None:
    """Call first thing inside the action's transaction. None → go ahead; a dict → replay it."""
    h = request_hash(endpoint, body)
    won = (
        await session.execute(
            insert(IdempotencyKey)
            .values(user_id=user_id, key=key, endpoint=endpoint, request_hash=h, created_at=now)
            .on_conflict_do_nothing(index_elements=[IdempotencyKey.user_id, IdempotencyKey.key])
            .returning(IdempotencyKey.key)
        )
    ).first()
    if won is not None:
        return None
    row = (
        await session.execute(
            select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
        )
    ).scalar_one()
    if row.endpoint != endpoint or row.request_hash != h:
        raise GameError(
            "idempotency_mismatch", "That request key was already used for something else.", status=422
        )
    if row.response is None:  # can't happen while claim+store share a transaction; be safe anyway
        raise GameError("in_progress", "That request is still being processed.", status=409)
    return row.response


async def store(
    session: AsyncSession, user_id: uuid.UUID, key: uuid.UUID, response: dict[str, Any], status: int = 200
) -> None:
    row = await session.get(IdempotencyKey, (user_id, key))
    assert row is not None, "store() without claim()"
    row.status_code = status
    row.response = json.loads(json.dumps(response, default=str))


async def prune(session: AsyncSession, now: datetime) -> int:
    res = await session.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < now - TTL))
    return res.rowcount or 0  # type: ignore[attr-defined]
