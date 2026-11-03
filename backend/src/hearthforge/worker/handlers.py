"""Scheduled-event handlers. Each must be idempotent (D-008): running it twice changes nothing."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.db.models import ScheduledEvent
from hearthforge.services import events, village
from hearthforge.state import AppState

Handler = Callable[[AsyncSession, AppState, ScheduledEvent], Awaitable[None]]


async def building_complete(session: AsyncSession, st: AppState, ev: ScheduledEvent) -> None:
    ld = await village.load_locked(session, village_id=uuid.UUID(ev.payload["village_id"]))
    done = village.settle_village(session, st.config, ld, st.clock.now())
    if done:
        await events.notify(session, "village.changed", owner_id=str(ld.village.user_id))


HANDLERS: dict[str, Handler] = {
    "building.complete": building_complete,
}
