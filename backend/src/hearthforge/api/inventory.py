"""Inventory and equipment (PROTOCOL §5). Deposits happen in Avatar Mode when you walk home."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.core.errors import GameError
from hearthforge.services import idempotency
from hearthforge.services import inventory as svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api/inventory", tags=["inventory"])
act = rate_limit("inventory", "actions_per_min")


class SlotRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["inventory", "equipment", "bank"]
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
    """Move, merge or swap. Equipping is a move into an equipment slot (0 weapon, 4–7 quick-slots).
    The bank lives at home: it only opens while you're in Build Mode."""
    if "bank" in (body.src.kind, body.dst.kind) and st.rooms is not None and st.rooms.find(auth.user.id):
        raise GameError("bank_far", "Your bank is at home. Head back to the village to use it.")
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
    key: uuid.UUID = Depends(idempotency.require_key),
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Restore a weapon's durability at your Forge (coins + ingots)."""
    now = st.clock.now()
    async with db.begin():
        replay = await idempotency.claim(db, auth.user.id, key, "inventory.repair", body.model_dump(), now)
        if replay is not None:
            return replay
        ld, paid = await svc.repair(db, st.config, auth.user.id, now, body.kind, body.slot)
        out = {"paid": paid, "inventory": await svc.read(db, st.config, auth.user.id)}
        await idempotency.store(db, auth.user.id, key, out)
    await _push_village(st, ld)
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return out


class ExpandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["inventory", "bank"]


@router.post("/expand", dependencies=[Depends(act)])
async def expand(
    body: ExpandIn,
    key: uuid.UUID = Depends(idempotency.require_key),
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Buy the next size step for your bag (24 → 48) or bank (60 → 200)."""
    now = st.clock.now()
    async with db.begin():
        replay = await idempotency.claim(db, auth.user.id, key, "inventory.expand", body.model_dump(), now)
        if replay is not None:
            return replay
        ld, capacity, cost = await svc.expand(db, st.config, auth.user.id, now, body.kind)
        out = {"capacity": capacity, "paid": cost, "inventory": await svc.read(db, st.config, auth.user.id)}
        await idempotency.store(db, auth.user.id, key, out)
    await _push_village(st, ld)
    if body.kind == "inventory" and st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return out


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
