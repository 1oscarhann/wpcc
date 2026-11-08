"""Phase 17: the Plaza. The player market, global leaderboards, world boss weekends and festivals."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.services import festivals as fest_svc
from hearthforge.services import idempotency
from hearthforge.services import leaderboards as lb_svc
from hearthforge.services import pmarket as pm_svc
from hearthforge.services import worldboss as wb_svc
from hearthforge.state import AppState

router = APIRouter(tags=["plaza"])
act = rate_limit("village", "actions_per_min")


class ListIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str = Field(min_length=1, max_length=40)
    quantity: int = Field(ge=1, le=10_000)
    unit_price: int = Field(ge=1, le=1_000_000)


class BuyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: int = Field(ge=1, le=10_000)


class ShopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0, le=50)


class WorldDevIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: float = Field(default=2.0, gt=0, le=72)
    hp: int | None = Field(default=None, ge=100)


async def _reload(st: AppState, *uids: uuid.UUID) -> None:
    if st.rooms is not None:
        for u in uids:
            await st.rooms.reload_loadout(u)


# ── the player market ────────────────────────────────────────────────────────
@router.get("/api/pmarket")
async def pmarket(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    now = st.clock.now()
    async with db.begin():
        return {
            "items": await pm_svc.summary(db, st.config, now),
            **(await pm_svc.mine(db, st.config, auth.user.id, now)),
        }


@router.get("/api/pmarket/item/{key}")
async def pmarket_item(
    key: str,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        return await pm_svc.item_view(db, st.config, auth.user.id, key, st.clock.now())


@router.post("/api/pmarket/listings", dependencies=[Depends(act)])
async def create_listing(
    body: ListIn,
    key: uuid.UUID = Depends(idempotency.require_key),
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    now = st.clock.now()
    async with db.begin():
        replay = await idempotency.claim(db, auth.user.id, key, "pmarket.list", body.model_dump(), now)
        if replay is not None:
            return replay
        ls = await pm_svc.create(db, st.config, auth.user.id, body.item, body.quantity, body.unit_price, now)
        out = {"listing": str(ls.id)}
        await idempotency.store(db, auth.user.id, key, out)
    await _reload(st, auth.user.id)
    return out


@router.post("/api/pmarket/listings/{listing_id}/buy", dependencies=[Depends(act)])
async def buy_listing(
    listing_id: uuid.UUID,
    body: BuyIn,
    key: uuid.UUID = Depends(idempotency.require_key),
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    now = st.clock.now()
    async with db.begin():
        replay = await idempotency.claim(
            db, auth.user.id, key, "pmarket.buy", {"listing": str(listing_id), **body.model_dump()}, now
        )
        if replay is not None:
            return replay
        out = await pm_svc.buy(db, st.config, auth.user.id, listing_id, body.quantity, now)
        await idempotency.store(db, auth.user.id, key, out)
    await _reload(st, auth.user.id)
    if st.village_hub is not None:
        await st.village_hub.publish(str(auth.user.id))  # purses changed
        await st.village_hub.publish(out["seller"])
        await st.village_hub.notify([out["seller"]], "pmarket", {"item": out["item"], "qty": out["quantity"]})
    return out


@router.post("/api/pmarket/listings/{listing_id}/cancel", dependencies=[Depends(act)])
async def cancel_listing(
    listing_id: uuid.UUID,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await pm_svc.cancel(db, st.config, auth.user.id, listing_id, st.clock.now())
    return {"cancelled": True}


# ── leaderboards ─────────────────────────────────────────────────────────────
@router.get("/api/leaderboards")
async def leaderboards(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state)
) -> dict[str, Any]:
    return {"boards": lb_svc.boards(st.config)}


@router.get("/api/leaderboards/{board}")
async def leaderboard(
    board: str,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await lb_svc.board(db, st.config, board, auth.user.id)


# ── world boss weekends ──────────────────────────────────────────────────────
@router.get("/api/worldboss")
async def worldboss(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        return await wb_svc.view(db, st.config, auth.user.id, st.clock.now())


@router.post("/api/dev/worldboss")
async def dev_worldboss(
    body: WorldDevIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dev only (HF_ENV=dev): a world boss starting now, so it can be tried any day of the week."""
    if not st.settings.is_dev:
        raise HTTPException(404)
    async with db.begin():
        ev = await wb_svc.start_now(db, st.config, st.clock.now(), body.hours, body.hp)
    if st.rooms is not None:
        st.rooms.world_reload()
    return {"event": str(ev.id)}


# ── festivals ────────────────────────────────────────────────────────────────
@router.get("/api/festival")
async def festival(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        return await fest_svc.view(db, st.config, auth.user.id, st.clock.now())


@router.post("/api/festival/buy", dependencies=[Depends(act)])
async def festival_buy(
    body: ShopIn,
    key: uuid.UUID = Depends(idempotency.require_key),
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    now = st.clock.now()
    async with db.begin():
        replay = await idempotency.claim(db, auth.user.id, key, "festival.buy", body.model_dump(), now)
        if replay is not None:
            return replay
        out = {"got": await fest_svc.buy(db, st.config, auth.user.id, body.index, now)}
        await idempotency.store(db, auth.user.id, key, out)
    await _reload(st, auth.user.id)
    return out
