"""Phase 16: the journal — skills, quests, achievements and titles, the login calendar, the collection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.services import progress as svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api/journal", tags=["journal"])
act = rate_limit("village", "actions_per_min")


class KeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=40)


class QuestIn(KeyIn):
    period: str = Field(pattern="^(daily|weekly|main)$")


class TitleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=40)


@router.get("")
async def journal(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    now = st.clock.now()
    async with db.begin():
        return {
            "quests": await svc.quests_view(db, st.config, auth.user.id, now),
            "achievements": await svc.achievements_view(db, st.config, auth.user.id, now),
            "skills": await svc.skills_view(db, st.config, auth.user.id),
            "calendar": await svc.calendar_view(db, st.config, auth.user.id, now),
        }


@router.get("/collection")
async def collection(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await svc.collection(db, st.config, auth.user.id)


@router.post("/quests/claim", dependencies=[Depends(act)])
async def claim_quest(
    body: QuestIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        got = await svc.claim_quest(st, db, auth.user.id, body.period, body.key, st.clock.now())
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)  # a token may have landed in the bag
    return {"got": got}


@router.post("/achievements/claim", dependencies=[Depends(act)])
async def claim_achievement(
    body: KeyIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        return {"got": await svc.claim_achievement(st, db, auth.user.id, body.key, st.clock.now())}


@router.post("/title", dependencies=[Depends(act)])
async def set_title(
    body: TitleIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.set_title(db, auth.user.id, body.title)
    if st.rooms is not None:
        await st.rooms.reload_progress(auth.user.id)
    return {"title": body.title}


@router.post("/skills/learn", dependencies=[Depends(act)])
async def learn(
    body: KeyIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.learn(db, st.config, auth.user.id, body.key)
    if st.rooms is not None:
        await st.rooms.reload_progress(auth.user.id)
    async with db.begin():
        return await svc.skills_view(db, st.config, auth.user.id)


@router.post("/skills/respec", dependencies=[Depends(act)])
async def respec(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        cost = await svc.respec(db, st.config, auth.user.id)
    if st.rooms is not None:
        await st.rooms.reload_progress(auth.user.id)
    async with db.begin():
        return {"cost": cost, **(await svc.skills_view(db, st.config, auth.user.id))}


@router.post("/calendar/claim", dependencies=[Depends(act)])
async def claim_calendar(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        got = await svc.claim_calendar(st, db, auth.user.id, st.clock.now())
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    if st.village_hub is not None:
        await st.village_hub.publish(str(auth.user.id))
    return {"got": got}
