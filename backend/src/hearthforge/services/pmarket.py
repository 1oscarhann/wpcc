"""Phase 17: the player market. Sell stackable goods to other players across every realm.

Listing moves the goods from your bag into escrow (the listing row). A buyer takes some or all of a
listing: their coins go to the seller at once, less the fee (a coin sink), and the goods go to the
buyer's bag (any overflow by mail). Cancelled or expired listings send what's left back by mail.

Races: the listing row is locked (`FOR UPDATE`) for every buy and cancel, and both wallets are locked in
user-id order so two crossing trades can't deadlock. Every request also carries an idempotency key.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError, NotFound
from hearthforge.db.models import Listing, Notification, Trade, User
from hearthforge.services import inventory, ledger, social, stats
from hearthforge.services.stash import unit_value

LIST = "pmarket.list"
BUY = "pmarket.buy"
SALE = "pmarket.sale"
RETURN = "pmarket.return"


def reference(cfg: GameConfig, key: str) -> int:
    """What the item is 'worth': the NPC market's base price, or the stash's value for the rest."""
    return max(1, unit_value(cfg, key))


def band(cfg: GameConfig, key: str) -> tuple[int, int]:
    lo, hi = cfg.global_.pmarket.price_band
    ref = reference(cfg, key)
    return max(1, math.floor(ref * lo)), max(1, math.ceil(ref * hi))


def sellable(cfg: GameConfig, key: str) -> bool:
    it = cfg.items.get(key)
    return it is not None and it.stackable and it.category in cfg.global_.pmarket.categories


def _row(cfg: GameConfig, ls: Listing, me: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "id": str(ls.id),
        "item": ls.item_key,
        "quantity": ls.quantity,
        "listed": ls.listed,
        "unit_price": ls.unit_price,
        "seller": ls.seller_name,
        "mine": me is not None and ls.seller_id == me,
        "status": ls.status,
        "expires_ms": int(ls.expires_at.timestamp() * 1000),
    }


# ── selling ──────────────────────────────────────────────────────────────────
async def create(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    key: str,
    qty: int,
    unit_price: int,
    now: datetime,
) -> Listing:
    pm = cfg.global_.pmarket
    if not sellable(cfg, key):
        raise GameError("not_tradeable", "That can't go on the market (gear and tools stay with you).")
    if not 1 <= qty <= pm.max_quantity:
        raise GameError("bad_quantity", f"List between 1 and {pm.max_quantity}.")
    lo, hi = band(cfg, key)
    if not lo <= unit_price <= hi:
        raise GameError("bad_price", f"Price it between {lo} and {hi} coins each.", low=lo, high=hi)
    if not await social.passes_gate(session, cfg, user_id, now):
        raise GameError("too_new", "New accounts can list once they reach level 5 or are a day old.")
    active = (
        await session.execute(
            select(func.count()).where(Listing.seller_id == user_id, Listing.status == "active")
        )
    ).scalar_one()
    if active >= pm.max_listings:
        raise GameError("too_many", f"You can have {pm.max_listings} listings up at once.")
    bag = (await inventory.bags(session, user_id, ("inventory",)))["inventory"]
    have = sum(s.quantity for s in bag.slots.values() if s.item_key == key and s.instance_id is None)
    if have < qty:
        raise GameError("not_enough", f"You only have {have}.", have=have)
    await inventory.take_stack(session, bag, key, qty)
    name = (await session.execute(select(User.username).where(User.id == user_id))).scalar_one()
    ls = Listing(
        id=uuid.uuid4(),
        seller_id=user_id,
        seller_name=name,
        item_key=key,
        quantity=qty,
        listed=qty,
        unit_price=unit_price,
        status="active",
        expires_at=now + timedelta(hours=pm.listing_hours),
    )
    session.add(ls)
    ledger.log_item(session, user_id, key, -qty, LIST)
    return ls


async def _give_back(session: AsyncSession, cfg: GameConfig, ls: Listing, why: str) -> None:
    if ls.quantity > 0:
        # by mail; the ledger logs the goods again when the parcel is claimed into a bag
        social.send_mail(session, ls.seller_id, "system", "The market", {ls.item_key: ls.quantity}, note=why)
    ls.quantity = 0


async def cancel(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, listing_id: uuid.UUID, now: datetime
) -> None:
    ls = (
        await session.execute(select(Listing).where(Listing.id == listing_id).with_for_update())
    ).scalar_one_or_none()
    if ls is None or ls.seller_id != user_id:
        raise NotFound("no_listing", "That listing isn't yours.")
    if ls.status != "active":
        raise GameError("closed", "That listing has already closed.")
    ls.status = "cancelled"
    ls.closed_at = now
    await _give_back(session, cfg, ls, "Your listing was taken down. Here's what didn't sell.")


async def expire_due(session: AsyncSession, cfg: GameConfig, now: datetime, limit: int = 200) -> int:
    """The sweep: listings past their time go home by mail."""
    rows = list(
        (
            await session.execute(
                select(Listing)
                .where(Listing.status == "active", Listing.expires_at <= now)
                .order_by(Listing.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for ls in rows:
        ls.status = "expired"
        ls.closed_at = now
        await _give_back(session, cfg, ls, "Your listing expired. Here's what didn't sell.")
    return len(rows)


# ── buying ───────────────────────────────────────────────────────────────────
async def buy(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, listing_id: uuid.UUID, qty: int, now: datetime
) -> dict[str, Any]:
    ls = (
        await session.execute(select(Listing).where(Listing.id == listing_id).with_for_update())
    ).scalar_one_or_none()
    if ls is None:
        raise NotFound("no_listing", "That listing is gone.")
    if ls.status != "active" or ls.expires_at <= now:
        raise GameError("closed", "That listing has closed.")
    if ls.seller_id == user_id:
        raise GameError("own_listing", "That's your own listing.")
    if qty < 1 or qty > ls.quantity:
        raise GameError("bad_quantity", f"Only {ls.quantity} left.", left=ls.quantity)
    if await social.blocked_between(session, user_id, ls.seller_id):
        raise GameError("blocked", "You can't trade with this player.")
    cost = ls.unit_price * qty
    fee = max(1, math.floor(cost * cfg.global_.pmarket.fee))
    # lock both wallets in a fixed order so two crossing trades can't deadlock
    wallets = {}
    for uid in sorted((user_id, ls.seller_id), key=str):
        wallets[uid] = await ledger.lock_wallet(session, uid)
    await ledger.change_coins(session, wallets[user_id], -cost, BUY, ref_type="listing", ref_id=str(ls.id))
    await ledger.change_coins(
        session, wallets[ls.seller_id], cost - fee, SALE, ref_type="listing", ref_id=str(ls.id)
    )
    left = await inventory.grant(session, cfg, user_id, {ls.item_key: qty}, BUY)
    if left:
        social.send_mail(
            session,
            user_id,
            "system",
            "The market",
            left,
            note="Your bag was full: the rest of your purchase",
        )
    ls.quantity -= qty
    if ls.quantity == 0:
        ls.status = "sold"
        ls.closed_at = now
    session.add(
        Trade(
            listing_id=ls.id,
            seller_id=ls.seller_id,
            buyer_id=user_id,
            item_key=ls.item_key,
            quantity=qty,
            unit_price=ls.unit_price,
            fee=fee,
        )
    )
    item = cfg.items[ls.item_key].name
    session.add(
        Notification(
            user_id=ls.seller_id,
            kind="pmarket.sold",
            payload={"item": ls.item_key, "name": item, "qty": qty, "coins": cost - fee},
        )
    )
    await stats.bump(session, ls.seller_id, {"pmarket.sold": qty, "pmarket.earned": cost - fee})
    await stats.bump(session, user_id, {"pmarket.bought": qty})
    return {
        "item": ls.item_key,
        "quantity": qty,
        "cost": cost,
        "fee": fee,
        "seller": str(ls.seller_id),
        "mailed": left,
    }


# ── browsing ─────────────────────────────────────────────────────────────────
async def summary(session: AsyncSession, cfg: GameConfig, now: datetime) -> list[dict[str, Any]]:
    """One row per item on sale: the cheapest price, how many, and the last trade."""
    rows = (
        await session.execute(
            select(Listing.item_key, func.min(Listing.unit_price), func.sum(Listing.quantity), func.count())
            .where(Listing.status == "active", Listing.expires_at > now)
            .group_by(Listing.item_key)
        )
    ).all()
    last: dict[str, int] = {}
    recent = await session.execute(
        select(Trade.item_key, Trade.unit_price).order_by(Trade.created_at.desc()).limit(500)
    )
    for k, p in recent.all():
        last.setdefault(k, p)  # newest first, so the first one seen is the last trade
    out = [
        {
            "item": k,
            "name": cfg.items[k].name if k in cfg.items else k,
            "category": cfg.items[k].category if k in cfg.items else "",
            "lowest": int(lo),
            "quantity": int(q),
            "listings": int(n),
            "last": last.get(k),
            "reference": reference(cfg, k),
        }
        for k, lo, q, n in rows
    ]
    out.sort(key=lambda r: r["name"])
    return out


async def item_view(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, key: str, now: datetime
) -> dict[str, Any]:
    if key not in cfg.items:
        raise NotFound("no_item", "No such item.")
    listings = list(
        (
            await session.execute(
                select(Listing)
                .where(Listing.item_key == key, Listing.status == "active", Listing.expires_at > now)
                .order_by(Listing.unit_price, Listing.created_at)
                .limit(50)
            )
        ).scalars()
    )
    since = now - timedelta(days=cfg.global_.pmarket.history_days)
    trades = list(
        (
            await session.execute(
                select(Trade)
                .where(Trade.item_key == key, Trade.created_at >= since)
                .order_by(Trade.created_at.desc())
                .limit(200)
            )
        ).scalars()
    )
    days: dict[str, list[int]] = {}
    for t in trades:
        d = t.created_at.date().isoformat()
        days.setdefault(d, [0, 0])
        days[d][0] += t.unit_price * t.quantity
        days[d][1] += t.quantity
    history = [{"day": d, "avg": round(v / q, 1), "volume": q} for d, (v, q) in sorted(days.items())]
    lo, hi = band(cfg, key)
    return {
        "item": key,
        "name": cfg.items[key].name,
        "reference": reference(cfg, key),
        "band": [lo, hi],
        "listings": [_row(cfg, ls, user_id) for ls in listings],
        "history": history,
        "recent": [
            {"qty": t.quantity, "price": t.unit_price, "at_ms": int(t.created_at.timestamp() * 1000)}
            for t in trades[:12]
        ],
    }


async def mine(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    """Your listings (active and recently closed), and what in your bag you could list."""
    rows = list(
        (
            await session.execute(
                select(Listing)
                .where(Listing.seller_id == user_id)
                .order_by(Listing.status != "active", Listing.created_at.desc())
                .limit(30)
            )
        ).scalars()
    )
    bag = (await inventory.bags(session, user_id, ("inventory",), lock=False))["inventory"]
    have: dict[str, int] = {}
    for s in bag.slots.values():
        if s.instance_id is None and sellable(cfg, s.item_key):
            have[s.item_key] = have.get(s.item_key, 0) + s.quantity
    lowest = {
        k: int(p)
        for k, p in (
            await session.execute(
                select(Listing.item_key, func.min(Listing.unit_price))
                .where(Listing.status == "active", Listing.item_key.in_(list(have) or [""]))
                .group_by(Listing.item_key)
            )
        ).all()
    }
    sell = [
        {
            "item": k,
            "name": cfg.items[k].name,
            "have": n,
            "reference": reference(cfg, k),
            "band": list(band(cfg, k)),
            "lowest": lowest.get(k),
        }
        for k, n in sorted(have.items(), key=lambda kv: cfg.items[kv[0]].name)
    ]
    pm = cfg.global_.pmarket
    return {
        "listings": [_row(cfg, ls, user_id) for ls in rows],
        "sellable": sell,
        "fee": pm.fee,
        "max_listings": pm.max_listings,
        "hours": pm.listing_hours,
        "gate_ok": await social.passes_gate(session, cfg, user_id, now),
    }
