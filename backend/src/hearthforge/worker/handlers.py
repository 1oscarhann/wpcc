"""Scheduled-event handlers. Each must be idempotent (D-008): running it twice changes nothing."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.db.models import ScheduledEvent
from hearthforge.services import events, market, village
from hearthforge.state import AppState

Handler = Callable[[AsyncSession, AppState, ScheduledEvent], Awaitable[None]]


async def building_complete(session: AsyncSession, st: AppState, ev: ScheduledEvent) -> None:
    ld = await village.load_locked(session, village_id=uuid.UUID(ev.payload["village_id"]))
    done = village.settle_village(session, st.config, ld, st.clock.now())
    if done:
        await events.notify(session, "village.changed", owner_id=str(ld.village.user_id))


async def market_recalc(session: AsyncSession, st: AppState, ev: ScheduledEvent) -> None:
    """Reprice the NPC market, sample the coin supply, prune old rows, and book the next run."""
    now = st.clock.now()
    await market.recalc(session, st.config, now)
    await market.schedule_next(session, st.config, now)


HANDLERS: dict[str, Handler] = {
    market.RECALC: market_recalc,
    "building.complete": building_complete,
    # a finished job only needs the village settled (intermediates land in storage) and a push
    "craft.complete": building_complete,
}
