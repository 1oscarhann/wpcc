from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.services import village as svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api/village", tags=["village"])
act = rate_limit("village", "actions_per_min")


class PlaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=40)
    x: int = Field(ge=0, le=63)
    y: int = Field(ge=0, le=63)
    rotation: int = Field(default=0, ge=0, le=3)


class MoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = Field(ge=0, le=63)
    y: int = Field(ge=0, le=63)
    rotation: int = Field(default=0, ge=0, le=3)


async def _respond(st: AppState, ld: svc.Loaded, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    state = svc.village_state(st.config, ld, st.clock.now())
    if st.village_hub is not None:
        await st.village_hub.publish(state["owner_id"], state)
    return {"village": state, **(extra or {})}


@router.get("")
async def get_village(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return {"village": await svc.read_state(db, st.config, auth.user.id, st.clock.now())}


@router.get("/preview", dependencies=[Depends(rate_limit("preview", "preview_per_min"))])
async def preview(
    key: str,
    x: int,
    y: int,
    rotation: int = 0,
    move_id: str | None = None,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await svc.preview(db, st.config, auth.user.id, key, x, y, rotation, move_id)


@router.post("/buildings", dependencies=[Depends(act)])
async def place(
    body: PlaceIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ld = await svc.place(
            db, st.config, auth.user.id, st.clock.now(), body.key, body.x, body.y, body.rotation
        )
    return await _respond(st, ld)


@router.patch("/buildings/{building_id}", dependencies=[Depends(act)])
async def move(
    building_id: str,
    body: MoveIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ld = await svc.move(
            db, st.config, auth.user.id, st.clock.now(), building_id, body.x, body.y, body.rotation
        )
    return await _respond(st, ld)


@router.delete("/buildings/{building_id}", dependencies=[Depends(act)])
async def demolish(
    building_id: str,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ld, refunded = await svc.demolish(db, st.config, auth.user.id, st.clock.now(), building_id)
    return await _respond(st, ld, {"refunded": refunded})


@router.post("/buildings/{building_id}/upgrade", dependencies=[Depends(act)])
async def upgrade(
    building_id: str,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ld = await svc.upgrade(db, st.config, auth.user.id, st.clock.now(), building_id)
    return await _respond(st, ld)


@router.post("/buildings/{building_id}/cancel", dependencies=[Depends(act)])
async def cancel(
    building_id: str,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ld, refunded = await svc.cancel(db, st.config, auth.user.id, st.clock.now(), building_id)
    return await _respond(st, ld, {"refunded": refunded})


@router.post("/debris/{debris_id}/clear", dependencies=[Depends(act)])
async def clear_debris(
    debris_id: int,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ld, gained = await svc.clear_debris(db, st.config, auth.user.id, st.clock.now(), debris_id)
    return await _respond(st, ld, {"gained": gained})


@router.post("/undo", dependencies=[Depends(act)])
async def undo(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        ld = await svc.undo(db, st.config, auth.user.id, st.clock.now())
    return await _respond(st, ld)
