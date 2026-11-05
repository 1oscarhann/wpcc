"""The realm stash with trust rules (P3). Anyone can put things in. Taking things out:

- the owner and trusted members: no limit;
- other members: up to `untrusted_daily_value` coins' worth per UTC day;
- members in their first `newcomer_deposit_only`: deposit only.

Every move is in the ledger (container = the stash) and the activity feed.
Lock order: user's containers and the stash container, by id (one SELECT … FOR UPDATE).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import Forbidden, GameError
from hearthforge.db.models import (
    Container,
    ContainerKind,
    ContainerSlot,
    ItemInstance,
    RealmRole,
    Transaction,
)
from hearthforge.services import activity, inventory, ledger
from hearthforge.services import realm as realm_svc
from hearthforge.services.inventory import Bag


def unit_value(cfg: GameConfig, key: str, tier: int | None = None) -> int:
    if tier:
        return tier * cfg.social.stash.gear_value_per_tier
    mi = cfg.market.items.get(key)
    return round(mi.base) if mi else cfg.social.stash.default_item_value


async def _bags(session: AsyncSession, user_id: uuid.UUID, stash_id: uuid.UUID) -> tuple[Bag, Bag]:
    rows = list(
        (
            await session.execute(
                select(Container)
                .where(
                    (Container.id == stash_id)
                    | ((Container.owner_user_id == user_id) & (Container.kind == ContainerKind.inventory))
                )
                .order_by(Container.id)
                .with_for_update()
            )
        ).scalars()
    )
    out: dict[str, Bag] = {}
    for c in rows:
        slots = (
            await session.execute(select(ContainerSlot).where(ContainerSlot.container_id == c.id))
        ).scalars()
        out[c.kind.value] = Bag(c, {s.slot: s for s in slots})
    return out["inventory"], out["realm_stash"]


async def withdrawn_today(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, stash_id: uuid.UUID, now: datetime
) -> int:
    day = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    rows = await session.execute(
        select(Transaction.item_key, func.sum(-Transaction.delta), ItemInstance.tier)
        .outerjoin(ItemInstance, ItemInstance.id == Transaction.instance_id)
        .where(
            Transaction.user_id == user_id,
            Transaction.container_id == stash_id,
            Transaction.reason == ledger.STASH_WITHDRAW,
            Transaction.delta < 0,
            Transaction.created_at >= day,
        )
        .group_by(Transaction.item_key, ItemInstance.tier)
    )
    return sum(unit_value(cfg, k or "", t) * int(q) for k, q, t in rows.all())


async def view(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    realm, me = await realm_svc.my_member(session, user_id)
    if realm.is_solo:
        return {"available": False}
    stash = await realm_svc.ensure_stash(session, cfg, realm.id)
    slots = list(
        (await session.execute(select(ContainerSlot).where(ContainerSlot.container_id == stash.id))).scalars()
    )
    insts = {
        i.id: i
        for i in (
            await session.execute(
                select(ItemInstance).where(
                    ItemInstance.id.in_([s.instance_id for s in slots if s.instance_id])
                )
            )
        ).scalars()
    }
    rules = cfg.social.stash
    trusted = me.role == RealmRole.owner or me.stash_trusted
    newcomer = not trusted and now - me.joined_at < timedelta(seconds=rules.newcomer_deposit_only)
    used = await withdrawn_today(session, cfg, user_id, stash.id, now)
    out_slots = []
    for s in sorted(slots, key=lambda s: s.slot):
        inst = insts.get(s.instance_id) if s.instance_id else None
        row: dict[str, Any] = {"slot": s.slot, "item": s.item_key, "qty": s.quantity}
        if inst is not None:
            from hearthforge.domain.forging import item_name

            row.update(
                name=item_name(cfg, inst.item_key, inst.tier), tier=inst.tier, rarity=inst.rarity.value
            )
        row["value"] = unit_value(cfg, s.item_key, inst.tier if inst else None)
        out_slots.append(row)
    return {
        "available": True,
        "capacity": stash.capacity,
        "slots": out_slots,
        "rules": {
            "trusted": trusted,
            "newcomer": newcomer,
            "newcomer_until_ms": int(
                (me.joined_at + timedelta(seconds=rules.newcomer_deposit_only)).timestamp() * 1000
            )
            if newcomer
            else None,
            "daily_cap": None if trusted else rules.untrusted_daily_value,
            "used_today": used,
        },
    }


async def _move(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    src: Bag,
    dst: Bag,
    slot: int,
    qty: int,
    reason: str,
) -> tuple[str, int, int | None]:
    s = src.slots.get(slot)
    if s is None:
        raise GameError("empty_slot", "There's nothing there.")
    if s.instance_id is not None:
        if not dst.free:
            raise GameError("full", "No room for that.")
        key, inst_id = s.item_key, s.instance_id
        await session.delete(s)
        del src.slots[slot]
        await session.flush()
        free = dst.free[0]
        dst.slots[free] = ContainerSlot(
            container_id=dst.c.id, slot=free, item_key=key, quantity=1, instance_id=inst_id
        )
        session.add(dst.slots[free])
        inst = await session.get(ItemInstance, inst_id)
        ledger.log_item(session, user_id, key, -1, reason, container_id=src.c.id, instance_id=inst_id)
        ledger.log_item(session, user_id, key, 1, reason, container_id=dst.c.id, instance_id=inst_id)
        return key, 1, inst.tier if inst else None
    qty = min(qty, s.quantity)
    if qty <= 0:
        raise GameError("bad_quantity", "Pick how many.")
    key = s.item_key
    left = inventory.add_stack(cfg, session, dst, key, qty)
    moved = qty - left
    if moved <= 0:
        raise GameError("full", "No room for that.")
    s.quantity -= moved
    if s.quantity == 0:
        await session.delete(s)
        del src.slots[slot]
    ledger.log_item(session, user_id, key, -moved, reason, container_id=src.c.id)
    ledger.log_item(session, user_id, key, moved, reason, container_id=dst.c.id)
    return key, moved, None


async def deposit(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, slot: int, qty: int, now: datetime
) -> dict[str, Any]:
    realm, _me = await realm_svc.my_member(session, user_id)
    if realm.is_solo:
        raise GameError("solo", "Found or join a realm to share a stash.")
    stash = await realm_svc.ensure_stash(session, cfg, realm.id)
    inv, st = await _bags(session, user_id, stash.id)
    key, moved, tier = await _move(session, cfg, user_id, inv, st, slot, qty, ledger.STASH_DEPOSIT)
    activity.log(session, realm.id, user_id, "stash_deposit", {"item": key, "qty": moved, "tier": tier}, now)
    await session.flush()
    return {"item": key, "qty": moved}


async def withdraw(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, slot: int, qty: int, now: datetime
) -> dict[str, Any]:
    realm, me = await realm_svc.my_member(session, user_id)
    if realm.is_solo:
        raise GameError("solo", "Found or join a realm to share a stash.")
    rules = cfg.social.stash
    trusted = me.role == RealmRole.owner or me.stash_trusted
    if not trusted and now - me.joined_at < timedelta(seconds=rules.newcomer_deposit_only):
        raise Forbidden("newcomer", "New members can only put things in for their first two days.")
    stash = await realm_svc.ensure_stash(session, cfg, realm.id)
    inv, st = await _bags(session, user_id, stash.id)
    s = st.slots.get(slot)
    if s is None:
        raise GameError("empty_slot", "There's nothing there.")
    if not trusted:
        tier = None
        if s.instance_id is not None:
            inst = await session.get(ItemInstance, s.instance_id)
            tier = inst.tier if inst else None
        want = unit_value(cfg, s.item_key, tier) * (1 if s.instance_id else min(qty, s.quantity))
        used = await withdrawn_today(session, cfg, user_id, stash.id, now)
        if used + want > rules.untrusted_daily_value:
            raise Forbidden(
                "daily_cap",
                f"That's over your daily stash limit "
                f"({rules.untrusted_daily_value - used} coins' worth left). Ask the owner to trust you.",
            )
    key, moved, tier = await _move(session, cfg, user_id, st, inv, slot, qty, ledger.STASH_WITHDRAW)
    activity.log(session, realm.id, user_id, "stash_withdraw", {"item": key, "qty": moved, "tier": tier}, now)
    await session.flush()
    return {"item": key, "qty": moved}
