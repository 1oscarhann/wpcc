from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.core.security import hash_token, new_csrf_token, new_session_token
from hearthforge.db.models import Session, User


async def create_session(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, ttl_s: float
) -> tuple[str, str]:
    token = new_session_token()
    csrf = new_csrf_token()
    session.add(
        Session(
            token_hash=hash_token(token),
            user_id=user_id,
            csrf_token=csrf,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_s),
            last_used_at=now,
        )
    )
    return token, csrf


async def lookup(session: AsyncSession, token: str, now: datetime) -> tuple[Session, User] | None:
    row = (
        await session.execute(
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(Session.token_hash == hash_token(token), Session.expires_at > now)
        )
    ).first()
    if row is None:
        return None
    sess, user = row
    if user.banned_at is not None:
        return None
    return sess, user


async def revoke(session: AsyncSession, token: str) -> None:
    await session.execute(delete(Session).where(Session.token_hash == hash_token(token)))


async def revoke_all(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(delete(Session).where(Session.user_id == user_id))
