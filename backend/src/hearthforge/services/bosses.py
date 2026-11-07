"""Phase 13: realm bosses in the DB — which one wakes where and when, HP and damage saves, the kill."""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.clock import to_ms
from hearthforge.config.loader import GameConfig
from hearthforge.db.models import Avatar, BossDamage, RealmBoss, RealmMember, UserStat
from hearthforge.domain import mapgen
from hearthforge.domain.mapgen import rand01
from hearthforge.sim.bosses import BossRow

_next_check: dict[uuid.UUID, datetime] = {}


def lair(cfg: GameConfig, seed: int, key: str, n: int) -> tuple[float, float]:
    """A spot in the boss's ring, different each time it comes round (n = how many bosses so far)."""
    lay = mapgen.layout(cfg.mapgen)
    bc = cfg.bosses.bosses[key]
    a = rand01(seed, len(key) * 131 + n, n * 17 + 3, 401) * math.tau
    return lay.center + bc.lair_radius * math.cos(a), lay.center + bc.lair_radius * math.sin(a)


async def ensure(
    session: AsyncSession, cfg: GameConfig, realm_id: uuid.UUID, seed: int, now: datetime
) -> RealmBoss | None:
    """Expire the old one, and wake the next when it's time. Returns a boss that just got scheduled."""
    if _next_check.get(realm_id, now) > now:
        return None
    sp = cfg.bosses.spawn
    last = (
        await session.execute(
            select(RealmBoss)
            .where(RealmBoss.realm_id == realm_id)
            .order_by(RealmBoss.spawns_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is not None and last.status == "waiting" and last.expires_at <= now:
        last.status = "expired"
    if last is not None and last.spawns_at + timedelta(seconds=sp.every) > now:
        _next_check[realm_id] = min(last.spawns_at + timedelta(seconds=sp.every), now + timedelta(minutes=5))
        return None
    n = (await session.execute(select(func.count()).where(RealmBoss.realm_id == realm_id))).scalar_one()
    best = (
        await session.execute(
            select(func.max(Avatar.level))
            .join(RealmMember, RealmMember.user_id == Avatar.user_id)
            .where(RealmMember.realm_id == realm_id)
        )
    ).scalar_one_or_none() or 1
    pool = [k for k, b in cfg.bosses.bosses.items() if b.unlock_level <= best] or [
        next(iter(cfg.bosses.bosses))
    ]
    key = pool[n % len(pool)]
    at = now + timedelta(seconds=sp.first_after) if last is None else now
    x, y = lair(cfg, seed, key, n)
    row = RealmBoss(
        id=uuid.uuid4(),
        realm_id=realm_id,
        boss_key=key,
        lair_x=x,
        lair_y=y,
        status="waiting",
        spawns_at=at,
        expires_at=at + timedelta(seconds=sp.stays),
        hp_fraction=1.0,
    )
    session.add(row)
    _next_check[realm_id] = now + timedelta(minutes=5)
    return row


async def spawn_now(
    session: AsyncSession, cfg: GameConfig, realm_id: uuid.UUID, key: str, x: float, y: float, now: datetime
) -> RealmBoss:
    """Dev: a boss right here, right now (any waiting one is retired)."""
    for r in (
        await session.execute(
            select(RealmBoss).where(RealmBoss.realm_id == realm_id, RealmBoss.status == "waiting")
        )
    ).scalars():
        r.status = "expired"
    row = RealmBoss(
        id=uuid.uuid4(),
        realm_id=realm_id,
        boss_key=key,
        lair_x=x,
        lair_y=y,
        status="waiting",
        spawns_at=now,
        expires_at=now + timedelta(seconds=cfg.bosses.spawn.stays),
        hp_fraction=1.0,
    )
    session.add(row)
    return row


async def active_rows(
    session: AsyncSession, cfg: GameConfig, realm_id: uuid.UUID, now: datetime
) -> list[BossRow]:
    rows = list(
        (
            await session.execute(
                select(RealmBoss).where(
                    RealmBoss.realm_id == realm_id,
                    RealmBoss.status == "waiting",
                    RealmBoss.spawns_at <= now,
                    RealmBoss.expires_at > now,
                )
            )
        ).scalars()
    )
    out: list[BossRow] = []
    for r in rows:
        if r.boss_key not in cfg.bosses.bosses:
            continue
        dmg = {
            str(d.user_id): d.damage
            for d in (await session.execute(select(BossDamage).where(BossDamage.boss_id == r.id))).scalars()
        }
        enemy = cfg.bosses.bosses[r.boss_key].enemy
        kills = {
            str(u): v
            for u, v in (
                await session.execute(
                    select(UserStat.user_id, UserStat.value)
                    .join(RealmMember, RealmMember.user_id == UserStat.user_id)
                    .where(RealmMember.realm_id == realm_id, UserStat.stat_key == f"kill.{enemy}")
                )
            ).all()
        }
        out.append(
            BossRow(
                str(r.id), r.boss_key, r.lair_x, r.lair_y, r.hp_fraction, to_ms(r.expires_at) or 0, dmg, kills
            )
        )
    return out


async def save(
    session: AsyncSession,
    hp: list[dict[str, Any]],
    damage: dict[tuple[str, str], int],
    defeated: list[str],
    now: datetime,
) -> None:
    for h in hp:
        row = await session.get(RealmBoss, uuid.UUID(h["id"]))
        if row is not None and row.status == "waiting":
            row.hp_fraction = float(h["hp_fraction"])
    for (bid, uid), dmg in damage.items():
        stmt = insert(BossDamage).values(boss_id=uuid.UUID(bid), user_id=uuid.UUID(uid), damage=dmg)
        await session.execute(
            stmt.on_conflict_do_update(index_elements=["boss_id", "user_id"], set_={"damage": dmg})
        )
    for bid in defeated:
        row = await session.get(RealmBoss, uuid.UUID(bid))
        if row is not None:
            row.status, row.defeated_at, row.hp_fraction = "defeated", now, 0.0


async def view(session: AsyncSession, cfg: GameConfig, realm_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    """For the map: the waiting boss (or the next one's wake time)."""
    row = (
        await session.execute(
            select(RealmBoss)
            .where(RealmBoss.realm_id == realm_id)
            .order_by(RealmBoss.spawns_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or row.boss_key not in cfg.bosses.bosses:
        return {"boss": None}
    bc = cfg.bosses.bosses[row.boss_key]
    status = row.status
    if status == "waiting" and row.expires_at <= now:
        status = "expired"
    elif status == "waiting" and row.spawns_at > now:
        status = "sleeping"
    return {
        "boss": {
            "key": row.boss_key,
            "name": bc.name,
            "biome": bc.biome,
            "x": row.lair_x,
            "y": row.lair_y,
            "status": status,
            "spawns_at_ms": to_ms(row.spawns_at),
            "expires_at_ms": to_ms(row.expires_at),
            "hp_fraction": row.hp_fraction,
            "next_at_ms": to_ms(row.spawns_at + timedelta(seconds=cfg.bosses.spawn.every)),
        }
    }
