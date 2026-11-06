"""Delve runs and the daily leaderboard (Phase 12)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.db.models import DungeonRun, Realm


async def record(session: AsyncSession, runs: list[dict[str, Any]]) -> None:
    for r in runs:
        session.add(
            DungeonRun(
                id=uuid.uuid4(),
                kind=r["kind"],
                key=r["key"],
                day=r["day"],
                realm_id=r["realm_id"],
                seed=r["seed"],
                biome=r["biome"],
                names=r["names"],
                user_ids=r["user_ids"],
                clear_ms=r["clear_ms"],
                deaths=r["deaths"],
                extra={},
            )
        )


async def daily_board(session: AsyncSession, cfg: GameConfig, day: str, user_id: uuid.UUID) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(DungeonRun, Realm.name)
            .join(Realm, Realm.id == DungeonRun.realm_id)
            .where(DungeonRun.kind == "daily", DungeonRun.day == day)
            .order_by(DungeonRun.clear_ms, DungeonRun.created_at)
            .limit(cfg.dungeons.leaderboard.size)
        )
    ).all()
    me = str(user_id)
    best = (
        await session.execute(
            select(DungeonRun.clear_ms)
            .where(DungeonRun.kind == "daily", DungeonRun.day == day, DungeonRun.user_ids.contains([me]))
            .order_by(DungeonRun.clear_ms)
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "day": day,
        "biome": cfg.dungeons.daily.biome,
        "board": [
            {
                "rank": i + 1,
                "names": run.names,
                "realm": realm_name,
                "clear_ms": run.clear_ms,
                "deaths": run.deaths,
                "you": me in run.user_ids,
            }
            for i, (run, realm_name) in enumerate(rows)
        ],
        "your_best_ms": best,
    }
