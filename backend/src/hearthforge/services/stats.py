"""Per-player counters (user_stats). Increments are upserts, so concurrent bumps never lose a count."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.db.models import UserStat


async def bump(session: AsyncSession, user_id: uuid.UUID, counts: Mapping[str, int]) -> None:
    rows = [{"user_id": user_id, "stat_key": k, "value": int(v)} for k, v in counts.items() if v]
    if not rows:
        return
    stmt = insert(UserStat).values(rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[UserStat.user_id, UserStat.stat_key],
            set_={"value": UserStat.value + stmt.excluded.value},
        )
    )


async def read(
    session: AsyncSession, user_id: uuid.UUID, keys: Iterable[str] | None = None
) -> dict[str, int]:
    q = select(UserStat.stat_key, UserStat.value).where(UserStat.user_id == user_id)
    if keys is not None:
        q = q.where(UserStat.stat_key.in_(list(keys)))
    return {k: int(v) for k, v in (await session.execute(q)).all()}
