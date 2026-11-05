"""NPC market and the wandering merchant (PROTOCOL §5, Phase 7). Sell and buy need an Idempotency-Key."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.services import idempotency
from hearthforge.services import inventory as inv_svc
from hearthforge.services import market as market_svc
from hearthforge.services import merchant as merchant_svc
from hearthforge.services import village as village_svc
from hearthforge.state import AppState

router = APIRouter(tags=["market"])
act = rate_limit("market", "actions_per_min")


class SellIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str = Field(max_length=40)
    quantity: int = Field(ge=1, le=100_000)


class BuyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: int = Field(ge=0, le=20)
    rotation: int = Field(ge=0)


async def _publish(st: AppState, state: dict[str, Any]) -> None:
    if st.village_hub is not None:
        await st.village_hub.publish(state["owner_id"], state)


@router.get("/api/market")
async def market(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Prices (with your Market bonus), sparklines, trends, and your soft-cap usage today."""
    return await market_svc.view(db, st.config, auth.user.id, st.clock.now())


@router.post("/api/market/sell", dependencies=[Depends(act)])
async def sell(
    body: SellIn,
    key: uuid.UUID = Depends(idempotency.require_key),
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    now = st.clock.now()
    async with db.begin():
        replay = await idempotency.claim(db, auth.user.id, key, "market.sell", body.model_dump(), now)
        if replay is not None:
            return replay
        ld, result, bag_changed = await market_svc.sell(
            db, st.config, auth.user.id, now, body.item, body.quantity
        )
        out: dict[str, Any] = {"village": village_svc.village_state(st.config, ld, now), "sale": result}
        if bag_changed or result["item"] not in ld.resources:
            out["inventory"] = await inv_svc.read(db, st.config, auth.user.id)
        await idempotency.store(db, auth.user.id, key, out)
    await _publish(st, out["village"])
    if "inventory" in out and st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return out


@router.get("/api/merchant/{merchant_id}")
async def merchant(
    merchant_id: str,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Today's cart. `merchant_id` is `hub` (your realm's hub) or `hub:<realm id>`."""
    return await merchant_svc.view(db, st.config, st.rooms, auth.user.id, merchant_id, st.clock.now())


@router.post("/api/merchant/{merchant_id}/buy", dependencies=[Depends(act)])
async def buy(
    merchant_id: str,
    body: BuyIn,
    key: uuid.UUID = Depends(idempotency.require_key),
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    now = st.clock.now()
    async with db.begin():
        replay = await idempotency.claim(
            db, auth.user.id, key, "merchant.buy", {"merchant": merchant_id, **body.model_dump()}, now
        )
        if replay is not None:
            return replay
        ld, result, bag_changed = await merchant_svc.buy(
            db, st.config, st.rooms, auth.user.id, merchant_id, now, body.slot, body.rotation
        )
        out: dict[str, Any] = {"village": village_svc.village_state(st.config, ld, now), "purchase": result}
        if bag_changed:
            out["inventory"] = await inv_svc.read(db, st.config, auth.user.id)
        await idempotency.store(db, auth.user.id, key, out)
    await _publish(st, out["village"])
    if bag_changed and st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return out
