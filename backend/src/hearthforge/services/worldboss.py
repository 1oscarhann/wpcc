"""Phase 17: world boss weekends. One boss, one HP pool, every realm at once (D-120).

Each realm's room spawns the boss at its hub and, every second, subtracts the damage its players dealt
from the shared pool here (`apply_damage`), then takes the pool's new value as the boss's HP. So every
realm sees everyone's progress within a second or two. The pool can't go below zero; whichever room's
update empties it marks the event defeated. When an event ends (defeated or out of time) the global
loop pays every fighter by damage tier, by mail, and titles the fighters of the top realms.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.db.models import Realm, RealmMember, User, UserCosmetic, WorldBossDamage, WorldBossEvent
from hearthforge.services import social, stats


def window_start(cfg: GameConfig, now: datetime) -> datetime | None:
    """The start of the weekend window we're in, if any (00:00 UTC on the first listed weekday)."""
    wb = cfg.global_.world_boss
    first = wb.weekdays[0]
    for back in range(7):
        day = (now - timedelta(days=back)).date()
        if day.weekday() != first:
            continue
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        if start <= now < start + timedelta(hours=wb.hours):
            return start
    return None


async def active_realms(session: AsyncSession, now: datetime) -> int:
    since = now - timedelta(days=7)
    n = (
        await session.execute(
            select(func.count(func.distinct(RealmMember.realm_id)))
            .join(User, User.id == RealmMember.user_id)
            .where(User.last_seen_at >= since)
        )
    ).scalar_one()
    return max(1, int(n))


async def _create(
    session: AsyncSession, cfg: GameConfig, start: datetime, end: datetime, hp: int
) -> WorldBossEvent:
    wb = cfg.global_.world_boss
    ev = WorldBossEvent(
        id=uuid.uuid4(),
        boss_key=wb.boss,
        name=wb.name,
        starts_at=start,
        ends_at=end,
        hp_max=hp,
        hp_remaining=hp,
        status="active",
    )
    session.add(ev)
    await session.flush()
    return ev


async def ensure(session: AsyncSession, cfg: GameConfig, now: datetime) -> WorldBossEvent | None:
    """Open this weekend's event if it isn't open yet."""
    start = window_start(cfg, now)
    if start is None:
        return None
    ev = (
        await session.execute(select(WorldBossEvent).where(WorldBossEvent.starts_at == start))
    ).scalar_one_or_none()
    if ev is not None:
        return ev
    wb = cfg.global_.world_boss
    hp = max(wb.min_hp, wb.hp_per_realm * await active_realms(session, now))
    return await _create(session, cfg, start, start + timedelta(hours=wb.hours), hp)


async def start_now(
    session: AsyncSession, cfg: GameConfig, now: datetime, hours: float = 2.0, hp: int | None = None
) -> WorldBossEvent:
    """Dev and admin: an event starting right now (ends any that's running)."""
    await session.execute(
        update(WorldBossEvent)
        .where(WorldBossEvent.status == "active")
        .values(status="expired", ends_at=now, finished_at=now)
    )
    wb = cfg.global_.world_boss
    return await _create(session, cfg, now, now + timedelta(hours=hours), hp or wb.min_hp)


async def current(session: AsyncSession, now: datetime) -> WorldBossEvent | None:
    """The live event, or the one that just ended (for a day, to show the results)."""
    return (
        await session.execute(
            select(WorldBossEvent)
            .where(WorldBossEvent.starts_at <= now, WorldBossEvent.ends_at > now - timedelta(days=1))
            .order_by(WorldBossEvent.starts_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def apply_damage(
    session: AsyncSession, event_id: uuid.UUID, realm_id: uuid.UUID, per_user: dict[str, int], now: datetime
) -> tuple[int, str]:
    """Take a room's damage off the shared pool; returns (hp left, status)."""
    total = sum(per_user.values())
    row = (
        await session.execute(
            update(WorldBossEvent)
            .where(WorldBossEvent.id == event_id, WorldBossEvent.status == "active")
            .values(hp_remaining=func.greatest(0, WorldBossEvent.hp_remaining - total))
            .returning(WorldBossEvent.hp_remaining, WorldBossEvent.status)
        )
    ).first()
    if per_user:
        stmt = insert(WorldBossDamage).values(
            [
                {"event_id": event_id, "user_id": uuid.UUID(u), "realm_id": realm_id, "damage": d}
                for u, d in per_user.items()
            ]
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[WorldBossDamage.event_id, WorldBossDamage.user_id],
                set_={
                    "damage": WorldBossDamage.damage + stmt.excluded.damage,
                    "realm_id": stmt.excluded.realm_id,
                },
            )
        )
    if row is None:  # already over
        ev = await session.get(WorldBossEvent, event_id)
        return (ev.hp_remaining, ev.status) if ev else (0, "expired")
    hp, status = int(row[0]), row[1]
    if hp == 0:
        await session.execute(
            update(WorldBossEvent)
            .where(WorldBossEvent.id == event_id, WorldBossEvent.status == "active")
            .values(status="defeated", finished_at=now)
        )
        status = "defeated"
    return hp, status


def tiers_reached(cfg: GameConfig, damage: int) -> int:
    return sum(1 for t in cfg.global_.world_boss.tiers if damage >= t.damage)


async def realm_board(session: AsyncSession, event_id: uuid.UUID, limit: int = 10) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(WorldBossDamage.realm_id, Realm.name, func.sum(WorldBossDamage.damage), func.count())
            .join(Realm, Realm.id == WorldBossDamage.realm_id, isouter=True)
            .where(WorldBossDamage.event_id == event_id)
            .group_by(WorldBossDamage.realm_id, Realm.name)
            .order_by(func.sum(WorldBossDamage.damage).desc())
            .limit(limit)
        )
    ).all()
    return [
        {"realm_id": str(r), "name": n or "A lone village", "damage": int(d), "fighters": int(c)}
        for r, n, d, c in rows
    ]


async def finish_due(session: AsyncSession, cfg: GameConfig, now: datetime) -> list[uuid.UUID]:
    """Close events whose time ran out, then pay every finished event that hasn't paid yet."""
    await session.execute(
        update(WorldBossEvent)
        .where(WorldBossEvent.status == "active", WorldBossEvent.ends_at <= now)
        .values(status="expired", finished_at=now)
    )
    due = list(
        (
            await session.execute(
                select(WorldBossEvent)
                .where(WorldBossEvent.status.in_(("defeated", "expired")), WorldBossEvent.rewarded.is_(False))
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for ev in due:
        await _reward(session, cfg, ev)
        ev.rewarded = True
    return [ev.id for ev in due]


async def _reward(session: AsyncSession, cfg: GameConfig, ev: WorldBossEvent) -> None:
    wb = cfg.global_.world_boss
    won = ev.status == "defeated"
    rows = list(
        (await session.execute(select(WorldBossDamage).where(WorldBossDamage.event_id == ev.id))).scalars()
    )
    top = {r["realm_id"] for r in await realm_board(session, ev.id, wb.top_realms)}
    for r in rows:
        if r.damage <= 0:
            continue
        coins = 0
        items: dict[str, int] = {}
        for t in wb.tiers:
            if r.damage >= t.damage:
                coins += t.coins
                for k, q in t.items.items():
                    items[k] = items.get(k, 0) + q
        if won:
            coins = round(coins * wb.defeat_bonus)
        note = (
            f"The world brought down {ev.name}! You dealt {r.damage:,} damage."
            if won
            else f"{ev.name} slipped away, but you dealt {r.damage:,} damage."
        )
        social.send_mail(session, r.user_id, "boss", ev.name, items, coins, note=note)
        await stats.bump(session, r.user_id, {"worldboss.fought": 1, "worldboss.won": 1 if won else 0})
        await stats.record(session, r.user_id, {"best.worldboss.damage": int(r.damage)})
        if (
            str(r.realm_id) in top
            and await session.get(UserCosmetic, (r.user_id, f"title:{wb.title}")) is None
        ):
            session.add(
                UserCosmetic(user_id=r.user_id, cosmetic_key=f"title:{wb.title}", source=f"worldboss:{ev.id}")
            )


async def view(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    wb = cfg.global_.world_boss
    ev = await current(session, now)
    nxt = None
    if ev is None or ev.status != "active":
        for d in range(1, 8):
            cand = window_start(cfg, now + timedelta(days=d))
            if cand is not None and cand > now:
                nxt = int(cand.timestamp() * 1000)
                break
    out: dict[str, Any] = {
        "name": wb.name,
        "boss": wb.boss,
        "event": None,
        "next_ms": nxt,
        "tiers": [t.model_dump() for t in wb.tiers],
        "top_realms": wb.top_realms,
        "title": wb.title,
    }
    if ev is None:
        return out
    mine = await session.get(WorldBossDamage, (ev.id, user_id))
    dmg = int(mine.damage) if mine else 0
    players = (
        await session.execute(
            select(User.username, WorldBossDamage.damage)
            .join(User, User.id == WorldBossDamage.user_id)
            .where(WorldBossDamage.event_id == ev.id)
            .order_by(WorldBossDamage.damage.desc())
            .limit(10)
        )
    ).all()
    out["event"] = {
        "id": str(ev.id),
        "status": ev.status,
        "hp_max": int(ev.hp_max),
        "hp_remaining": int(ev.hp_remaining),
        "starts_ms": int(ev.starts_at.timestamp() * 1000),
        "ends_ms": int(ev.ends_at.timestamp() * 1000),
        "realms": await realm_board(session, ev.id, wb.top_realms),
        "players": [{"name": n, "damage": int(d)} for n, d in players],
        "me": {"damage": dmg, "tier": tiers_reached(cfg, dmg)},
    }
    return out
