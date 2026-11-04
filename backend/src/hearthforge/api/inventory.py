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
