"""'While you were away' (Phase 8). When a player's last socket closes we snapshot their village;
when they come back after `away.min_absence`, the summary is the difference, settled exactly."""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.clock import to_ms
from hearthforge.config.loader import GameConfig
from hearthforge.db.models import CraftJob, JobStatus, User
from hearthforge.domain import market as market_dom
from hearthforge.domain.resources import MILLI
from hearthforge.services import village as village_svc


def _snap(ld: village_svc.Loaded, now: datetime) -> dict[str, Any]:
    return {
        "at_ms": to_ms(now),
        "resources": {k: r.amount_milli for k, r in ld.resources.items()},
        "coins": ld.wallet.coins if ld.wallet else 0,
        "buildings": {str(b.id): [b.building_key, b.level] for b in ld.buildings},
    }


async def snapshot(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime) -> None:
    ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    user = (await session.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
    user.away_snapshot = _snap(ld, now)


async def summary(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime
) -> dict[str, Any]:
    ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    snap = user.away_snapshot
    if not snap:
        return {"show": False}
    away_s = (to_ms(now) - int(snap["at_ms"])) / 1000
    if away_s < cfg.tutorial.away.min_absence:
        return {"show": False, "away_s": away_s}
    gained: dict[str, float] = {}
    full: list[str] = []
    for k, r in ld.resources.items():
        d = (r.amount_milli - int(snap["resources"].get(k, r.amount_milli))) / MILLI
        if d >= 1:
            gained[k] = round(d)
        if r.cap_milli and r.amount_milli >= r.cap_milli and r.base_rate_milli > 0:
            full.append(k)
    finished = []
    for b in ld.buildings:
        old = snap["buildings"].get(str(b.id))
        if b.level >= 1 and (old is None or b.level > int(old[1])):
            finished.append({"key": b.building_key, "level": b.level})
    since = datetime.fromtimestamp(int(snap["at_ms"]) / 1000, tz=now.tzinfo)
    jobs = list(
        (
            await session.execute(
                select(CraftJob).where(
                    CraftJob.user_id == user_id,
                    CraftJob.completes_at > since,
                    CraftJob.completes_at <= now,
                    CraftJob.status.in_([JobStatus.collected, JobStatus.running]),
                )
            )
        ).scalars()
    )
    goods: dict[str, int] = {}
    gear_ready = 0
    for j in jobs:
        if j.kind == "gear":
            gear_ready += 1 if j.status == JobStatus.running else 0
        else:
            goods[j.recipe_key] = goods.get(j.recipe_key, 0) + j.quantity
    coins = (ld.wallet.coins if ld.wallet else 0) - int(snap.get("coins", 0))
    mc = cfg.merchant
    moved = market_dom.rotation_index(mc, now) != market_dom.rotation_index(mc, since)
    rng = random.Random(int(snap["at_ms"]))
    return {
        "show": True,
        "away_s": round(away_s),
        "gained": gained,
        "full": full,
        "finished": finished,
        "crafted": goods,
        "gear_ready": gear_ready,
        "coins": coins,
        "merchant_moved": moved,
        "quip": rng.choice(cfg.tutorial.away.quips),
        "guide": {"name": cfg.tutorial.guide.name, "look": cfg.tutorial.guide.look.model_dump()},
    }


async def ack(session: AsyncSession, user_id: uuid.UUID) -> None:
    user = (await session.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
    user.away_snapshot = None
