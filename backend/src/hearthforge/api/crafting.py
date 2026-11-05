"""Crafting (PROTOCOL §5): the recipe book, station options, and station jobs."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.services import crafting as svc
from hearthforge.services import idempotency
from hearthforge.services import village as village_svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api/crafting", tags=["crafting"])
act = rate_limit("crafting", "actions_per_min")


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    station_id: str = Field(max_length=40)
    recipe: str = Field(max_length=40)
    quantity: int = Field(default=1, ge=1, le=100)
    rares: list[str] = Field(default_factory=list, max_length=5)


async def _respond(
    st: AppState, ld: village_svc.Loaded, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    state = village_svc.village_state(st.config, ld, st.clock.now())
    if st.village_hub is not None:
        await st.village_hub.publish(state["owner_id"], state)
    return {"village": state, **(extra or {})}


@router.get("/book")
async def book(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await svc.book(db, st.config, auth.user.id)


@router.get("/stations/{station_id}")
async def station(
    station_id: str,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ld = await village_svc.load_locked(db, user_id=auth.user.id, with_wallet=True)
        village_svc.settle_village(db, st.config, ld, st.clock.now())
        return svc.station_options(st.config, ld, station_id)


@router.post("/jobs", dependencies=[Depends(act)])
async def start(
    body: StartIn,
    key: uuid.UUID = Depends(idempotency.require_key),
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    now = st.clock.now()
    async with db.begin():
        replay = await idempotency.claim(db, auth.user.id, key, "crafting.start", body.model_dump(), now)
        if replay is not None:
            return replay
        ld, job = await svc.start(
            db, st.config, auth.user.id, now, body.station_id, body.recipe, body.quantity, body.rares
        )
        out = {"village": village_svc.village_state(st.config, ld, now), "job": village_svc.job_view(job)}
        await idempotency.store(db, auth.user.id, key, out)
    if st.village_hub is not None:
        await st.village_hub.publish(out["village"]["owner_id"], out["village"])
    if body.rares and st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return out


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(act)])
async def cancel(
    job_id: str,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ld, refunded = await svc.cancel(db, st.config, auth.user.id, st.clock.now(), job_id)
    out = await _respond(st, ld, {"refunded": refunded})
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return out


@router.post("/jobs/{job_id}/collect", dependencies=[Depends(act)])
async def collect(
    job_id: str,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ld, item = await svc.collect(db, st.config, auth.user.id, st.clock.now(), job_id)
    out = await _respond(st, ld, {"item": item})
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return out
