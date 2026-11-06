"""Delves (Phase 12): today's daily delve leaderboard (global: every realm runs the same layout)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state
from hearthforge.services import dungeons as svc
from hearthforge.sim.dungeon import utc_day
from hearthforge.state import AppState

router = APIRouter(prefix="/api/dungeons", tags=["dungeons"])


@router.get("/daily")
async def daily(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await svc.daily_board(db, st.config, utc_day(st.clock.now()), auth.user.id)
