"""Admin endpoints (role=admin). Phase 7: the economy view. Phase 18: the admin panel — an overview of
the live server, player search and detail, grants, bans, test accounts, world boss events and the audit log.
Every write is logged to admin_audit_log with who did it."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, admin_user, get_db, get_state
from hearthforge.core.errors import GameError, NotFound
from hearthforge.db.models import (
    AdminAuditLog,
    Avatar,
    Listing,
    Realm,
    RealmMember,
    Trade,
    Transaction,
    User,
    Wallet,
)
from hearthforge.services import economy, festivals, inventory, ledger, stats, worldboss
from hearthforge.state import AppState

router = APIRouter(prefix="/api/admin", tags=["admin"])


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    coins: int = Field(default=0, ge=0, le=1_000_000)
    items: dict[str, int] = Field(default_factory=dict, max_length=20)
    note: str = Field(default="", max_length=200)


class FlagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    enable: bool


class WorldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: float = Field(default=2.0, gt=0, le=72)
    hp: int | None = Field(default=None, ge=1000)


def _ms(dt: Any) -> int | None:
    return int(dt.timestamp() * 1000) if dt is not None else None


async def _audit(
    db: AsyncSession, auth: Auth, action: str, target: str | None, payload: dict[str, Any]
) -> None:
    db.add(AdminAuditLog(actor_id=auth.user.id, action=action, target=target, payload=payload))


@router.get("/economy")
async def economy_view(
    _: Auth = Depends(admin_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Coin supply now and over 7 days (one sample per market recalc), faucets vs sinks by reason."""
    async with db.begin():
        return await economy.report(db, st.clock.now())


@router.get("/overview")
async def overview(
    _: Auth = Depends(admin_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """The live server at a glance."""
    now = st.clock.now()
    async with db.begin():
        players = (await db.execute(select(func.count()).select_from(User))).scalar_one()
        active = (
            await db.execute(select(func.count()).where(User.last_seen_at >= now - timedelta(days=7)))
        ).scalar_one()
        realms = (await db.execute(select(func.count()).select_from(Realm))).scalar_one()
        supply = (await db.execute(select(func.coalesce(func.sum(Wallet.coins), 0)))).scalar_one()
        listings = (await db.execute(select(func.count()).where(Listing.status == "active"))).scalar_one()
        trades = (
            await db.execute(select(func.count()).where(Trade.created_at >= now - timedelta(days=1)))
        ).scalar_one()
        ev = await worldboss.current(db, now)
    rooms = []
    if st.rooms is not None:
        for room in st.rooms.rooms.values():
            rooms.append(
                {
                    "realm_id": str(room.realm_id),
                    "players": len(room.players),
                    "monsters": len(room.combat.monsters) if room.combat else 0,
                    "tick_ms": room.bench_stats(),
                }
            )
    fest = festivals.active(st.config, now)
    return {
        "players": players,
        "online": len(st.village_hub.online()) if st.village_hub is not None else 0,
        "active_7d": active,
        "realms": realms,
        "coin_supply": int(supply),
        "listings": listings,
        "trades_24h": trades,
        "rooms": rooms,
        "world_boss": None
        if ev is None
        else {
            "name": ev.name,
            "status": ev.status,
            "hp": int(ev.hp_remaining),
            "hp_max": int(ev.hp_max),
            "ends_ms": _ms(ev.ends_at),
        },
        "festival": fest[1].name if fest else None,
        "config_hash": st.config.hash,
    }


@router.get("/players")
async def players(
    q: str = Query(default="", max_length=40),
    _: Auth = Depends(admin_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    online = st.village_hub.online() if st.village_hub is not None else set()
    stmt = (
        select(User, Avatar.level, Wallet.coins, Realm.name)
        .join(Avatar, Avatar.user_id == User.id, isouter=True)
        .join(Wallet, Wallet.user_id == User.id, isouter=True)
        .join(RealmMember, RealmMember.user_id == User.id, isouter=True)
        .join(Realm, Realm.id == RealmMember.realm_id, isouter=True)
        .order_by(User.last_seen_at.desc().nulls_last())
        .limit(50)
    )
    if q:
        stmt = stmt.where(User.username.ilike(f"%{q}%"))
    async with db.begin():
        rows = (await db.execute(stmt)).all()
    return {
        "players": [
            {
                "id": str(u.id),
                "username": u.username,
                "role": u.role.value if hasattr(u.role, "value") else str(u.role),
                "level": lvl or 1,
                "coins": coins or 0,
                "realm": realm,
                "created_ms": _ms(u.created_at),
                "last_seen_ms": _ms(u.last_seen_at),
                "online": str(u.id) in online,
                "test": u.is_test_account,
                "banned": u.banned_at is not None,
            }
            for u, lvl, coins, realm in rows
        ]
    }


@router.get("/players/{user_id}")
async def player(
    user_id: uuid.UUID,
    _: Auth = Depends(admin_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        u = await db.get(User, user_id)
        if u is None:
            raise NotFound("no_player", "No such player.")
        av = (await db.execute(select(Avatar).where(Avatar.user_id == user_id))).scalar_one_or_none()
        coins = (await db.execute(select(Wallet.coins).where(Wallet.user_id == user_id))).scalar_one_or_none()
        counters = await stats.read(db, user_id)
        txs = list(
            (
                await db.execute(
                    select(Transaction)
                    .where(Transaction.user_id == user_id)
                    .order_by(Transaction.id.desc())
                    .limit(25)
                )
            ).scalars()
        )
        bag = await inventory.read(db, st.config, user_id)
    top = sorted(((k, v) for k, v in counters.items() if not k.startswith("best.")), key=lambda kv: -kv[1])[
        :16
    ]
    return {
        "id": str(u.id),
        "username": u.username,
        "level": av.level if av else 1,
        "xp": av.xp if av else 0,
        "title": av.title if av else None,
        "coins": coins or 0,
        "test": u.is_test_account,
        "banned": u.banned_at is not None,
        "created_ms": _ms(u.created_at),
        "last_seen_ms": _ms(u.last_seen_at),
        "stats": dict(top),
        "ledger": [
            {
                "at_ms": _ms(t.created_at),
                "reason": t.reason,
                "asset": str(t.asset.value if hasattr(t.asset, "value") else t.asset),
                "item": t.item_key,
                "delta": int(t.delta),
                "actor": t.actor,
            }
            for t in txs
        ],
        "bag": [{"item": s["item"], "qty": s["qty"]} for s in bag["inventory"]["slots"]],
    }


@router.post("/grant")
async def grant(
    body: GrantIn,
    auth: Auth = Depends(admin_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    for k in body.items:
        if k not in st.config.items:
            raise GameError("unknown_item", f"No item called {k}.")
    async with db.begin():
        if await db.get(User, body.user_id) is None:
            raise NotFound("no_player", "No such player.")
        if body.coins:
            wallet = await ledger.lock_wallet(db, body.user_id)
            await ledger.change_coins(db, wallet, body.coins, ledger.ADMIN_GRANT, actor="admin")
        left = (
            await inventory.grant(db, st.config, body.user_id, body.items, ledger.ADMIN_GRANT)
            if body.items
            else {}
        )
        await _audit(db, auth, "grant", str(body.user_id), body.model_dump(mode="json") | {"left": left})
    if st.rooms is not None:
        await st.rooms.reload_loadout(body.user_id)
    if st.village_hub is not None:
        await st.village_hub.publish(str(body.user_id))
    return {"granted": True, "left": left}


@router.post("/ban")
async def ban(
    body: FlagIn,
    auth: Auth = Depends(admin_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        u = await db.get(User, body.user_id, with_for_update=True)
        if u is None:
            raise NotFound("no_player", "No such player.")
        if u.id == auth.user.id:
            raise GameError("self", "You can't ban yourself.")
        u.banned_at = st.clock.now() if body.enable else None
        await _audit(db, auth, "ban" if body.enable else "unban", str(u.id), {})
    if body.enable and st.rooms is not None:
        found = st.rooms.find(body.user_id)
        if found is not None:
            await st.rooms.leave(body.user_id)
    return {"banned": body.enable}


@router.post("/test-account")
async def test_account(
    body: FlagIn,
    auth: Auth = Depends(admin_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        u = await db.get(User, body.user_id, with_for_update=True)
        if u is None:
            raise NotFound("no_player", "No such player.")
        u.is_test_account = body.enable
        await _audit(db, auth, "test_account", str(u.id), {"enable": body.enable})
    return {"test": body.enable}


@router.post("/worldboss")
async def start_world_boss(
    body: WorldIn,
    auth: Auth = Depends(admin_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        ev = await worldboss.start_now(db, st.config, st.clock.now(), body.hours, body.hp)
        await _audit(db, auth, "worldboss.start", str(ev.id), body.model_dump())
    if st.rooms is not None:
        st.rooms.world_reload()
    return {"event": str(ev.id)}


@router.get("/audit")
async def audit(_: Auth = Depends(admin_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    async with db.begin():
        rows = (
            await db.execute(
                select(AdminAuditLog, User.username)
                .join(User, User.id == AdminAuditLog.actor_id, isouter=True)
                .order_by(AdminAuditLog.id.desc())
                .limit(50)
            )
        ).all()
    return {
        "entries": [
            {
                "at_ms": _ms(a.created_at),
                "actor": name or "cli",
                "action": a.action,
                "target": a.target,
                "payload": a.payload,
            }
            for a, name in rows
        ]
    }
