"""Phase 16b: pets and mounts, and the Trophy Hall."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.services import companions as svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api/companions", tags=["companions"])
act = rate_limit("village", "actions_per_min")


class KeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=40)


class MaybeKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str | None = Field(default=None, max_length=40)


class RenameIn(KeyIn):
    name: str | None = Field(default=None, max_length=40)


async def _after(st: AppState, db: AsyncSession, auth: Auth) -> dict[str, Any]:
    if st.rooms is not None:
        await st.rooms.reload_progress(auth.user.id)  # new perks, a new pet trotting after you
    async with db.begin():
        return await svc.view(db, st.config, auth.user.id)


@router.get("")
async def companions(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        return await svc.view(db, st.config, auth.user.id)


@router.get("/trophies")
async def trophies(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        return await svc.trophy_hall(db, st.config, auth.user.id)


@router.post("/pets/adopt", dependencies=[Depends(act)])
async def adopt(
    body: KeyIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.adopt(db, st.config, auth.user.id, body.key)
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)  # tokens left the bag
    return await _after(st, db, auth)


@router.post("/pets/active", dependencies=[Depends(act)])
async def set_pet(
    body: MaybeKeyIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.set_pet(db, st.config, auth.user.id, body.key)
    return await _after(st, db, auth)


@router.post("/pets/rename", dependencies=[Depends(act)])
async def rename(
    body: RenameIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.rename(db, st.config, auth.user.id, body.key, body.name)
    return await _after(st, db, auth)


@router.post("/mounts/buy", dependencies=[Depends(act)])
async def buy_mount(
    body: KeyIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.buy_mount(db, st.config, auth.user.id, body.key)
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    if st.village_hub is not None:
        await st.village_hub.publish(str(auth.user.id))  # the purse changed
    return await _after(st, db, auth)


@router.post("/mounts/active", dependencies=[Depends(act)])
async def set_mount(
    body: MaybeKeyIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.set_mount(db, st.config, auth.user.id, body.key)
    return await _after(st, db, auth)
