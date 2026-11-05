"""The realm activity feed (Phase 9): joins, leaves, stash moves, discoveries, great forgings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.db.models import RealmActivity, User


def log(
    session: AsyncSession,
    realm_id: uuid.UUID,
    actor: uuid.UUID | None,
    kind: str,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    session.add(
        RealmActivity(realm_id=realm_id, actor_user_id=actor, kind=kind, payload=payload, created_at=now)
    )


async def feed(
    session: AsyncSession, realm_id: uuid.UUID, before: int | None = None, limit: int = 30
) -> list[dict[str, Any]]:
    q = (
        select(RealmActivity, User.username)
        .outerjoin(User, User.id == RealmActivity.actor_user_id)
        .where(RealmActivity.realm_id == realm_id)
        .order_by(RealmActivity.id.desc())
        .limit(limit)
    )
    if before is not None:
        q = q.where(RealmActivity.id < before)
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "actor": name,
            "actor_id": str(a.actor_user_id) if a.actor_user_id else None,
            "payload": a.payload,
            "at_ms": int(a.created_at.timestamp() * 1000),
        }
        for a, name in (await session.execute(q)).all()
    ]
