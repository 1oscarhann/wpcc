"""The wandering merchant (BALANCE §8.2). Stock is derived from (merchant id, rotation) by
domain/market.py; this module only checks presence, limits and coins, and hands over the goods.

Lock order: wallet → village (+ resources, jobs) → the purchase row → containers.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError, NotFound
from hearthforge.db.models import Discovery, DiscoveryKind, MerchantPurchase, RealmMember
from hearthforge.domain import mapgen
from hearthforge.domain import market as dom
from hearthforge.domain.resources import MILLI
from hearthforge.services import inventory, ledger
from hearthforge.services import village as village_svc

if TYPE_CHECKING:
    from hearthforge.sim.manager import RoomManager

PRESENCE_SLACK = 0.75  # tiles of forgiveness for client-side interpolation


async def resolve(session: AsyncSession, user_id: uuid.UUID, merchant_id: str) -> tuple[str, uuid.UUID]:
    """'hub' or 'hub:<your realm>' → ('hub:<realm id>', realm id). Other realms' carts are off limits."""
    realm_id = (
        await session.execute(select(RealmMember.realm_id).where(RealmMember.user_id == user_id))
    ).scalar_one_or_none()
    if realm_id is None:
        raise NotFound("no_realm", "You're not in a realm.")
    if merchant_id not in ("hub", f"hub:{realm_id}"):
        raise NotFound("no_merchant", "There's no merchant here.")
    return f"hub:{realm_id}", realm_id


def cart_pos(cfg: GameConfig, rot: dom.Rotation) -> tuple[float, float]:
    c = mapgen.layout(cfg.mapgen).center
    return c + rot.spot[0] + 0.5, c + rot.spot[1] + 0.5


def is_near(
    cfg: GameConfig, rooms: RoomManager | None, user_id: uuid.UUID, realm_id: uuid.UUID, rot: dom.Rotation
) -> bool:
    found = rooms.find(user_id) if rooms is not None else None
    if found is None:
        return False
    room, p = found
    if room.realm_id != realm_id:
        return False
    x, y = cart_pos(cfg, rot)
    return math.hypot(p.m.x - x, p.m.y - y) <= cfg.merchant.interact_radius + PRESENCE_SLACK


async def _hint_candidates(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> list[str]:
    known = set(
        (
            await session.execute(
                select(Discovery.key).where(
                    Discovery.user_id == user_id,
                    Discovery.kind.in_([DiscoveryKind.combo, DiscoveryKind.hint]),
                )
            )
        ).scalars()
    )
    return [k for k in cfg.combos.combos if k not in known]


def _stock_view(cfg: GameConfig, slot: dom.Slot) -> dict[str, Any]:
    s = cfg.merchant.stock[slot.stock_key]
    if s.kind == "hint":
        name, icon = s.name or "Recipe Hint", "icon.book"
    else:
        assert s.key is not None
        info = cfg.items[s.key]
        name = s.name or (f"{info.name} ×{s.qty}" if s.qty > 1 else info.name)
        icon = info.icon
    return {
        "slot": slot.slot,
        "key": slot.stock_key,
        "kind": s.kind,
        "item": s.key,
        "qty": s.qty,
        "name": name,
        "blurb": s.blurb,
        "icon": icon,
        "price": slot.price,
        "list_price": s.price,
        "deal": slot.deal,
        "limit": s.limit,
    }


async def view(
    session: AsyncSession,
    cfg: GameConfig,
    rooms: RoomManager | None,
    user_id: uuid.UUID,
    merchant_id: str,
    now: datetime,
) -> dict[str, Any]:
    mid, realm_id = await resolve(session, user_id, merchant_id)
    idx = dom.rotation_index(cfg.merchant, now)
    rot = dom.rotation(cfg.merchant, mid, idx)
    bought = {
        r.slot: r.quantity
        for r in (
            await session.execute(
                select(MerchantPurchase).where(
                    MerchantPurchase.user_id == user_id,
                    MerchantPurchase.merchant_id == mid,
                    MerchantPurchase.rotation == idx,
                )
            )
        ).scalars()
    }
    hintable = bool(await _hint_candidates(session, cfg, user_id))
    slots = []
    for sl in rot.slots:
        v = _stock_view(cfg, sl)
        v["bought"] = bought.get(sl.slot, 0)
        v["sold_out"] = v["bought"] >= v["limit"] or (v["kind"] == "hint" and not hintable)
        slots.append(v)
    x, y = cart_pos(cfg, rot)
    await session.commit()
    return {
        "merchant_id": mid,
        "name": cfg.merchant.name,
        "greeting": rot.greeting,
        "rotation": idx,
        "ends_at_ms": int(rot.ends_at.timestamp() * 1000),
        "pos": [x, y],
        "radius": cfg.merchant.interact_radius,
        "near": is_near(cfg, rooms, user_id, realm_id, rot),
        "slots": slots,
    }


async def buy(
    session: AsyncSession,
    cfg: GameConfig,
    rooms: RoomManager | None,
    user_id: uuid.UUID,
    merchant_id: str,
    now: datetime,
    slot: int,
    rotation: int,
) -> tuple[village_svc.Loaded, dict[str, Any], bool]:
    """Buy one lot from a slot. Returns (village, result, whether the bag changed)."""
    mid, realm_id = await resolve(session, user_id, merchant_id)
    idx = dom.rotation_index(cfg.merchant, now)
    if rotation != idx:
        raise GameError("merchant_moved_on", "She's packed up and restocked. Have a fresh look!", status=409)
    rot = dom.rotation(cfg.merchant, mid, idx)
    if not 0 <= slot < len(rot.slots):
        raise GameError("bad_slot", "That's not on the cart.")
    if not is_near(cfg, rooms, user_id, realm_id, rot):
        raise GameError("too_far", "Walk up to the merchant's cart in the hub to trade.")
    sl = rot.slots[slot]
    stock = cfg.merchant.stock[sl.stock_key]

    ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    assert ld.wallet is not None
    await session.execute(
        insert(MerchantPurchase)
        .values(user_id=user_id, merchant_id=mid, rotation=idx, slot=slot, quantity=0)
        .on_conflict_do_nothing(index_elements=["user_id", "merchant_id", "rotation", "slot"])
    )
    row = (
        await session.execute(
            select(MerchantPurchase)
            .where(
                MerchantPurchase.user_id == user_id,
                MerchantPurchase.merchant_id == mid,
                MerchantPurchase.rotation == idx,
                MerchantPurchase.slot == slot,
            )
            .with_for_update()
        )
    ).scalar_one()
    if row.quantity >= stock.limit:
        raise GameError("sold_out", "You've bought all she'll sell you of that today.")
    ref = f"{mid}:{idx}:{slot}"
    await ledger.change_coins(
        session, ld.wallet, -sl.price, ledger.MERCHANT_BUY, ref_type="merchant", ref_id=ref
    )
    got: dict[str, Any] = {}
    bag_changed = False
    if stock.kind == "item":
        assert stock.key is not None
        left = await inventory.grant(session, cfg, user_id, {stock.key: stock.qty}, ledger.MERCHANT_BUY)
        if left:
            raise GameError("bag_full", "Your bag is too full to carry that.")
        got = {"item": stock.key, "qty": stock.qty}
        bag_changed = True
    elif stock.kind == "resource":
        assert stock.key is not None
        r = ld.resources[stock.key]
        if r.cap_milli - r.amount_milli < stock.qty * MILLI:
            raise GameError("storage_full", "Your storehouse has no room for that.")
        r.amount_milli += stock.qty * MILLI
        ledger.log_resource(
            session,
            user_id,
            ld.village.realm_id,
            stock.key,
            stock.qty * MILLI,
            ledger.MERCHANT_BUY,
            ref_type="merchant",
            ref_id=ref,
        )
        got = {"resource": stock.key, "qty": stock.qty}
    else:
        candidates = await _hint_candidates(session, cfg, user_id)
        if not candidates:
            raise GameError("nothing_to_hint", "You already know every combo she could tell you about.")
        combo = dom.hint_pick(candidates, str(user_id), idx)
        session.add(
            Discovery(
                user_id=user_id, kind=DiscoveryKind.hint, key=combo, data={"from": mid, "rotation": idx}
            )
        )
        got = {"hint": cfg.combos.combos[combo].buildings}
    row.quantity += 1
    village_svc.touch(ld, now)
    await session.flush()
    return (
        ld,
        {"slot": slot, "price": sl.price, "got": got, "bought": row.quantity, "balance": ld.wallet.coins},
        bag_changed,
    )
