"""The first-session tutorial (Phase 8). `users.tutorial_step` is the index of the current step;
-1 means finished or skipped. The server checks every goal, so the client can only ask, never claim."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.config.schemas import TutorialStep
from hearthforge.core.errors import GameError
from hearthforge.db.models import User
from hearthforge.services import ledger, stats
from hearthforge.services import village as village_svc

OVER = -1


def _progress(step: TutorialStep, ld: village_svc.Loaded, counters: dict[str, int]) -> tuple[int, int]:
    g = step.goal
    if g.kind == "buildings":
        have = {b.building_key for b in ld.buildings}
        return sum(1 for k in g.all if k in have), len(g.all)
    if g.kind == "stat":
        assert g.key is not None
        return min(counters.get(g.key, 0), g.at_least), g.at_least
    if g.kind == "discovery":
        return (1 if g.combo in ld.discovered else 0), 1
    return 0, 1  # confirm


def _view(cfg: GameConfig, index: int, progress: tuple[int, int] | None) -> dict[str, Any]:
    steps = cfg.tutorial.steps
    out: dict[str, Any] = {
        "active": 0 <= index < len(steps),
        "index": index,
        "total": len(steps),
        "guide": {"name": cfg.tutorial.guide.name, "look": cfg.tutorial.guide.look.model_dump()},
        "steps": [{"key": s.key, "title": s.title} for s in steps],
    }
    if out["active"]:
        s = steps[index]
        out["step"] = {
            "key": s.key,
            "title": s.title,
            "lines": s.lines,
            "kind": s.goal.kind,
            "button": s.button,
            "highlight": s.highlight,
            "reward": s.reward,
            "progress": list(progress) if progress else [0, 1],
        }
    return out


async def _lock_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    return (await session.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()


async def check(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime, confirm: str | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]], village_svc.Loaded | None]:
    """Advance through every step whose goal is met. `confirm` = the key of a confirm step whose button
    was pressed. Returns (view, completed steps with their rewards, village if anything was paid)."""
    # lock order: wallet → village → user row (rewards touch the first two)
    ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    user = await _lock_user(session, user_id)
    steps = cfg.tutorial.steps
    done: list[dict[str, Any]] = []
    paid = False
    counters = await stats.read(session, user_id, [s.goal.key for s in steps if s.goal.key])
    while 0 <= user.tutorial_step < len(steps):
        s = steps[user.tutorial_step]
        have, need = _progress(s, ld, counters)
        met = (confirm == s.key) if s.goal.kind == "confirm" else have >= need
        if not met:
            return _view(cfg, user.tutorial_step, (have, need)), done, ld if paid else None
        if s.reward:
            await village_svc.refund(
                session, ld, dict(s.reward), 1.0, ledger.TUTORIAL_REWARD, s.key, ref_type="tutorial"
            )
            village_svc.touch(ld, now)
            paid = True
        done.append({"key": s.key, "title": s.title, "reward": s.reward})
        user.tutorial_step += 1
        confirm = None  # one press confirms one step
    if user.tutorial_step >= len(steps):
        user.tutorial_step = OVER
    return _view(cfg, user.tutorial_step, None), done, ld if paid else None


async def view(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    async with session.begin():
        out, _done, _ld = await check(session, cfg, user_id, now)
        return out


async def skip(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> dict[str, Any]:
    user = await _lock_user(session, user_id)
    if user.tutorial_step == OVER:
        raise GameError("tutorial_over", "The tutorial is already over.")
    user.tutorial_step = OVER
    return _view(cfg, OVER, None)


def in_tutorial(user: User) -> bool:
    return user.tutorial_step != OVER
