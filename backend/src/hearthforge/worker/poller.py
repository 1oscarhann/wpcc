"""The timer worker: claims due scheduled_events oldest-first with SKIP LOCKED (PLAN §2.3).

If the worker was down, overdue events are processed in due_at order when it comes back.
Failures retry with exponential backoff; after 5 attempts an event is marked failed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from hearthforge.db.models import EventStatus, ScheduledEvent
from hearthforge.state import AppState
from hearthforge.worker.handlers import HANDLERS

log = logging.getLogger("hearthforge.worker")
MAX_ATTEMPTS = 5


class Worker:
    def __init__(self, st: AppState, poll_interval: float = 1.0) -> None:
        self.st = st
        self.poll_interval = poll_interval

    async def run_once(self) -> bool:
        """Process at most one due event. Returns True if one was claimed."""
        now = self.st.clock.now()
        async with self.st.sessionmaker() as session, session.begin():
            ev = (
                await session.execute(
                    select(ScheduledEvent)
                    .where(ScheduledEvent.status == EventStatus.pending, ScheduledEvent.due_at <= now)
                    .order_by(ScheduledEvent.due_at, ScheduledEvent.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if ev is None:
                return False
            handler = HANDLERS.get(ev.kind)
            try:
                if handler is None:
                    raise RuntimeError(f"no handler for {ev.kind}")
                async with session.begin_nested():
                    await handler(session, self.st, ev)
                ev.status = EventStatus.done
                ev.processed_at = now
            except Exception as e:  # noqa: BLE001 - one bad event must never stop the worker
                ev.attempts += 1
                ev.last_error = f"{type(e).__name__}: {e}"[:500]
                if ev.attempts >= MAX_ATTEMPTS:
                    ev.status = EventStatus.failed
                    log.error("event %s (%s) failed permanently: %s", ev.id, ev.kind, ev.last_error)
                else:
                    ev.due_at = now + timedelta(seconds=2**ev.attempts)
                    log.warning("event %s (%s) failed, retrying: %s", ev.id, ev.kind, ev.last_error)
            return True

    async def drain(self, limit: int = 10_000) -> int:
        n = 0
        while n < limit and await self.run_once():
            n += 1
        return n

    async def run_forever(self) -> None:
        log.info("worker started")
        while True:
            try:
                processed = await self.drain(500)
                if processed:
                    log.info("processed %d events", processed)
            except Exception:  # noqa: BLE001
                log.exception("worker loop error")
            await asyncio.sleep(self.poll_interval)
