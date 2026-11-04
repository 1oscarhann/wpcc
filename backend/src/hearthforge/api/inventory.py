"""Inventory and equipment (PROTOCOL §5). Deposits happen in Avatar Mode when you walk home."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.services import inventory as svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api/inventory", tags=["inventory"])
act = rate_limit("inventory", "actions_per_min")


class SlotRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["inventory", "equipment"]
    slot: int = Field(ge=0, le=199)


class MoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    src: SlotRef
    dst: SlotRef


@router.get("")
async def get_inventory(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await svc.read(db, st.config, auth.user.id)


@router.post("/move", dependencies=[Depends(act)])
async def move(
    body: MoveIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Move, merge or swap. Equipping is a move into an equipment slot (0 weapon, 4–7 quick-slots)."""
    async with db.begin():
        await svc.move(
            db, st.config, auth.user.id, (body.src.kind, body.src.slot), (body.dst.kind, body.dst.slot)
        )
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return await svc.read(db, st.config, auth.user.id)


class GearRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["inventory", "equipment"] = "inventory"
    slot: int = Field(ge=0, le=199)


async def _push_village(st: AppState, ld: Any) -> None:
    from hearthforge.services import village as village_svc

    if st.village_hub is not None:
        state = village_svc.village_state(st.config, ld, st.clock.now())
        await st.village_hub.publish(state["owner_id"], state)


@router.post("/repair", dependencies=[Depends(act)])
async def repair(
    body: GearRef,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Restore a weapon's durability at your Forge (coins + ingots)."""
    async with db.begin():
        ld, paid = await svc.repair(db, st.config, auth.user.id, st.clock.now(), body.kind, body.slot)
    await _push_village(st, ld)
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return {"paid": paid, "inventory": await svc.read(db, st.config, auth.user.id)}


@router.post("/salvage", dependencies=[Depends(act)])
async def salvage(
    body: GearRef,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Break forged gear from your bag back into materials."""
    async with db.begin():
        ld, back, rares = await svc.salvage(db, st.config, auth.user.id, st.clock.now(), body.slot)
    await _push_village(st, ld)
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return {"returned": back, "rares": rares, "inventory": await svc.read(db, st.config, auth.user.id)}
