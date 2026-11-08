"""Phase 17: the global layer's heartbeat (in the API process, next to the wave director).

Every 15 s: send expired player-market listings home, open this weekend's world boss event if it isn't
open, close events that ran out of time, and pay out finished ones (then nudge the fighters' sockets so
their mailbox lights up)."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from hearthforge.db.models import WorldBossDamage
from hearthforge.services import pmarket, worldboss
from hearthforge.state import AppState

log = logging.getLogger(__name__)
EVERY = 15.0


async def global_tick(st: AppState) -> None:
    now = st.clock.now()
    async with st.sessionmaker() as s, s.begin():
        n = await pmarket.expire_due(s, st.config, now)
        if n:
            log.info("sent %d expired listings home", n)
    async with st.sessionmaker() as s, s.begin():
        opened = await worldboss.ensure(s, st.config, now)
        paid = await worldboss.finish_due(s, st.config, now)
        fighters: list[str] = []
        if paid:
            fighters = [
                str(u)
                for (u,) in (
                    await s.execute(select(WorldBossDamage.user_id).where(WorldBossDamage.event_id.in_(paid)))
                ).all()
            ]
    if (opened is not None or paid) and st.rooms is not None:
        st.rooms.world_reload()
    if fighters and st.village_hub is not None:
        await st.village_hub.notify(fighters, "social", {"kind": "mail"})


async def global_loop(st: AppState) -> None:
    while True:
        await asyncio.sleep(EVERY)
        try:
            await global_tick(st)
        except Exception:  # noqa: BLE001 - keep ticking
            log.exception("global tick failed")
