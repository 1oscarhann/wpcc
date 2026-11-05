"""Tutorial and the 'While you were away' card (Phase 8)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.services import away, tutorial
from hearthforge.services import village as village_svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api", tags=["progress"])
act = rate_limit("tutorial", "actions_per_min")


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str | None = Field(default=None, max_length=40)


@router.get("/tutorial")
async def get_tutorial(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await tutorial.view(db, st.config, auth.user.id, st.clock.now())


@router.post("/tutorial/check", dependencies=[Depends(act)])
async def check(
    body: CheckIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Advance through every step whose goal is met (rewards are paid as steps complete)."""
    now = st.clock.now()
    async with db.begin():
        view, done, ld = await tutorial.check(db, st.config, auth.user.id, now, body.confirm)
        state = village_svc.village_state(st.config, ld, now) if ld is not None else None
    if state is not None and st.village_hub is not None:
        await st.village_hub.publish(state["owner_id"], state)
    return {"tutorial": view, "completed": done, "village": state}


@router.post("/tutorial/skip", dependencies=[Depends(act)])
async def skip(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        return {"tutorial": await tutorial.skip(db, st.config, auth.user.id)}


@router.get("/away-summary")
async def away_summary(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        return await away.summary(db, st.config, auth.user.id, st.clock.now())


@router.post("/away-summary/ack")
async def away_ack(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        await away.ack(db, auth.user.id)
    return {"ok": True}
