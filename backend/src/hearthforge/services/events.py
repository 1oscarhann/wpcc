"""scheduled_events helpers + cross-process notifications (D-004, D-008)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.db.models import EventStatus, ScheduledEvent

CHANNEL = "hf_events"


async def schedule(
    session: AsyncSession, kind: str, due_at: datetime, payload: dict[str, Any], dedupe_key: str
) -> None:
    """Idempotent: the same dedupe_key can never be scheduled twice."""
    stmt = (
        insert(ScheduledEvent)
        .values(kind=kind, due_at=due_at, payload=payload, dedupe_key=dedupe_key, status=EventStatus.pending)
        .on_conflict_do_nothing(index_elements=[ScheduledEvent.dedupe_key])
    )
    await session.execute(stmt)


async def cancel(session: AsyncSession, dedupe_key: str) -> None:
    """Cancel a pending event. If the worker holds it right now we skip: its handler is a no-op anyway."""
    ev = (
        await session.execute(
            select(ScheduledEvent)
            .where(ScheduledEvent.dedupe_key == dedupe_key, ScheduledEvent.status == EventStatus.pending)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if ev is not None:
        ev.status = EventStatus.cancelled


async def notify(session: AsyncSession, kind: str, **payload: Any) -> None:
    """Postgres NOTIFY, delivered to listeners when the surrounding transaction commits."""
    await session.execute(
        text("SELECT pg_notify(:ch, :p)"), {"ch": CHANNEL, "p": json.dumps({"kind": kind, **payload})}
    )


def building_event_key(building_id: str, target_level: int, started_ms: int) -> str:
    return f"building.complete:{building_id}:{target_level}:{started_ms}"
