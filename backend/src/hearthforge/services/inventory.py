"""Inventory and equipment (containers + slots, D-006). Every change goes through the ledger.

Lock order (PLAN §2.2): wallet → village → containers by id. Equipment slots: 0 weapon, 1 offhand,
2 armour, 3 trinket, 4–7 quick-slots (consumables).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError
from hearthforge.db.models import Container, ContainerKind, ContainerSlot, ItemInstance
from hearthforge.domain.resources import MILLI
from hearthforge.services import ledger

EQUIP_ACCEPTS: dict[int, set[str]] = {
    0: {"weapon"},
    1: {"offhand"},
    2: {"armour"},
    3: {"trinket"},
    **{i: {"consumable"} for i in range(4, 8)},
}
KINDS = ("inventory", "equipment")


class Bag:
    """A locked container and its slots."""

    def __init__(self, container: Container, slots: dict[int, ContainerSlot]) -> None:
        self.c = container
        self.slots = slots

    @property
    def free(self) -> list[int]:
        return [i for i in range(self.c.capacity) if i not in self.slots]


async def bags(
    session: AsyncSession, user_id: uuid.UUID, kinds: tuple[str, ...] = KINDS, *, lock: bool = True
) -> dict[str, Bag]:
    q = (
        select(Container)
        .where(Container.owner_user_id == user_id, Container.kind.in_([ContainerKind(k) for k in kinds]))
        .order_by(Container.id)
    )
    if lock:
        q = q.with_for_update()
    containers = list((await session.execute(q)).scalars())
    out: dict[str, Bag] = {}
    for c in containers:
        rows = (
            await session.execute(select(ContainerSlot).where(ContainerSlot.container_id == c.id))
        ).scalars()
        out[c.kind.value] = Bag(c, {s.slot: s for s in rows})
    return out


async def read(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> dict[str, Any]:
    bs = await bags(session, user_id, lock=False)
    inst_ids = [s.instance_id for b in bs.values() for s in b.slots.values() if s.instance_id]
    insts: dict[uuid.UUID, ItemInstance] = {}
    if inst_ids:
        insts = {
            i.id: i
            for i in (
                await session.execute(select(ItemInstance).where(ItemInstance.id.in_(inst_ids)))
            ).scalars()
        }
    out: dict[str, Any] = {}
    for kind, b in bs.items():
        slots = []
        for s in sorted(b.slots.values(), key=lambda s: s.slot):
            row: dict[str, Any] = {"slot": s.slot, "item": s.item_key, "qty": s.quantity}
            inst = insts.get(s.instance_id) if s.instance_id else None
            if inst is not None:
                row.update(
                    tier=inst.tier,
                    rarity=inst.rarity.value,
                    durability=inst.durability,
                    max_durability=inst.max_durability,
                    modifiers=inst.modifiers,
                )
            slots.append(row)
        out[kind] = {"capacity": b.c.capacity, "slots": slots}
    return out


def add_stack(cfg: GameConfig, session: AsyncSession, bag: Bag, key: str, qty: int) -> int:
    """Put `qty` of a stackable item in the bag (top up stacks, then free slots). Returns what didn't fit."""
    info = cfg.items[key]
    if not info.stackable:
        raise ValueError(f"{key} is not stackable")
    left = qty
    for s in sorted(bag.slots.values(), key=lambda s: s.slot):
        if left <= 0:
            break
        if s.item_key == key and s.instance_id is None and s.quantity < info.max_stack:
            n = min(left, info.max_stack - s.quantity)
            s.quantity += n
            left -= n
    for i in bag.free:
        if left <= 0:
            break
        n = min(left, info.max_stack)
        s = ContainerSlot(container_id=bag.c.id, slot=i, item_key=key, quantity=n)
        session.add(s)
        bag.slots[i] = s
        left -= n
    return left


async def take_stack(session: AsyncSession, bag: Bag, key: str, qty: int) -> int:
    """Remove up to `qty` of a stackable item (from the last stacks first). Returns how many were removed."""
    left = qty
    for s in sorted(bag.slots.values(), key=lambda s: -s.slot):
        if left <= 0:
            break
        if s.item_key == key and s.instance_id is None:
            n = min(left, s.quantity)
            s.quantity -= n
            left -= n
            if s.quantity == 0:
                await session.delete(s)
                del bag.slots[s.slot]
    return qty - left


async def grant(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    items: dict[str, int],
    reason: str,
    *,
    bag: Bag | None = None,
) -> dict[str, int]:
    """Add stackables to the inventory. Returns leftovers that didn't fit (caller decides what to do)."""
    if bag is None:
        bag = (await bags(session, user_id, ("inventory",)))["inventory"]
    leftovers: dict[str, int] = {}
    for key, qty in items.items():
        if qty <= 0:
            continue
        left = add_stack(cfg, session, bag, key, qty)
        if qty - left:
            ledger.log_item(session, user_id, key, qty - left, reason, container_id=bag.c.id)
        if left:
            leftovers[key] = left
    await session.flush()
    return leftovers


async def remove(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, items: dict[str, int], reason: str, kind: str
) -> dict[str, int]:
    bag = (await bags(session, user_id, (kind,)))[kind]
    out: dict[str, int] = {}
    for key, qty in items.items():
        n = await take_stack(session, bag, key, qty)
        if n:
            ledger.log_item(session, user_id, key, -n, reason, container_id=bag.c.id)
            out[key] = n
    await session.flush()
    return out


async def deposit(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime, ld: Any = None
) -> tuple[dict[str, int], Any]:
    """Move gathered resources from the inventory into village storage, up to each cap.
    Pass `ld` if the village is already locked (lock order wallet → village → containers).
    Returns (deposited, loaded village) — the caller publishes the village."""
    from hearthforge.services import village as village_svc

    if ld is None:
        ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
        village_svc.settle_village(session, cfg, ld, now)
    bag = (await bags(session, user_id, ("inventory",)))["inventory"]
    have: dict[str, int] = {}
    for s in bag.slots.values():
        if s.item_key in ld.resources and s.instance_id is None:
            have[s.item_key] = have.get(s.item_key, 0) + s.quantity
    moved: dict[str, int] = {}
    for key, qty in have.items():
        r = ld.resources[key]
        space = max(0, (r.cap_milli - r.amount_milli) // MILLI)
        n = min(qty, space)
        if n <= 0:
            continue
        await take_stack(session, bag, key, n)
        r.amount_milli += n * MILLI
        ledger.log_item(session, user_id, key, -n, ledger.AVATAR_DEPOSIT, container_id=bag.c.id)
        ledger.log_resource(session, user_id, ld.village.realm_id, key, n * MILLI, ledger.AVATAR_DEPOSIT)
        moved[key] = n
    if moved:
        village_svc.touch(ld, now)
    await session.flush()
    return moved, ld


async def move(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    src: tuple[str, int],
    dst: tuple[str, int],
) -> None:
    """Move, merge or swap between inventory and equipment slots (equipping is just a move)."""
    if src[0] not in KINDS or dst[0] not in KINDS:
        raise GameError("bad_container", "You can't move items there.")
    bs = await bags(session, user_id)
    sb, db = bs[src[0]], bs[dst[0]]
    for bag, slot in ((sb, src[1]), (db, dst[1])):
        if not 0 <= slot < bag.c.capacity:
            raise GameError("bad_slot", "That slot doesn't exist.")
    a = sb.slots.get(src[1])
    if a is None:
        raise GameError("empty_slot", "There's nothing there.")
    b = db.slots.get(dst[1])
    if a is b:
        return

    def accepts(bag: Bag, slot: int, key: str) -> bool:
        if bag.c.kind != ContainerKind.equipment:
            return True
        return cfg.items[key].category in EQUIP_ACCEPTS.get(slot, set())

    if not accepts(db, dst[1], a.item_key) or (b is not None and not accepts(sb, src[1], b.item_key)):
        raise GameError("cant_equip", "That item doesn't go in that slot.")
    info = cfg.items[a.item_key]
    cross = sb is not db
    if (
        b is not None
        and b.item_key == a.item_key
        and info.stackable
        and a.instance_id is None
        and b.instance_id is None
    ):
        n = min(a.quantity, info.max_stack - b.quantity)
        if n <= 0:
            raise GameError("stack_full", "That stack is full.")
        b.quantity += n
        a.quantity -= n
        if a.quantity == 0:
            await session.delete(a)
        if cross:
            ledger.log_item(session, user_id, a.item_key, -n, ledger.ITEM_MOVE, container_id=sb.c.id)
            ledger.log_item(session, user_id, a.item_key, n, ledger.ITEM_MOVE, container_id=db.c.id)
        await session.flush()
        return
    # swap (or plain move): delete + re-add so the composite primary keys never collide
    moves = [(a, db, dst[1])] + ([(b, sb, src[1])] if b is not None else [])
    rows = [(s.item_key, s.quantity, s.instance_id, bag, slot, s.container_id) for s, bag, slot in moves]
    for s, _bag, _slot in moves:
        await session.delete(s)
    await session.flush()
    for key, qty, inst, bag, slot, old_cid in rows:
        session.add(
            ContainerSlot(container_id=bag.c.id, slot=slot, item_key=key, quantity=qty, instance_id=inst)
        )
        if bag.c.id != old_cid:
            ledger.log_item(
                session, user_id, key, -qty, ledger.ITEM_MOVE, container_id=old_cid, instance_id=inst
            )
            ledger.log_item(
                session, user_id, key, qty, ledger.ITEM_MOVE, container_id=bag.c.id, instance_id=inst
            )
    await session.flush()


async def loadout(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> dict[str, Any]:
    """What the realm room needs: equipped weapon, quick-slot potions, and the inventory as stacks."""
    bs = await bags(session, user_id, lock=False)
    eq, inv = bs["equipment"], bs["inventory"]
    weapon: dict[str, Any] = {"key": None, "type": "sword", "tier": 1, "rarity": "common"}
    w = eq.slots.get(0)
    if w is not None:
        it = cfg.items_cfg.items.get(w.item_key)
        inst = await session.get(ItemInstance, w.instance_id) if w.instance_id else None
        weapon = {
            "key": w.item_key,
            "type": (it.weapon_type if it else None) or "sword",
            "tier": inst.tier if inst else 1,
            "rarity": inst.rarity.value if inst else "common",
        }
    quick = {s.slot: [s.item_key, s.quantity] for s in eq.slots.values() if 4 <= s.slot < 8}
    stacks = [[s.slot, s.item_key, s.quantity, s.instance_id is not None] for s in inv.slots.values()]
    return {"weapon": weapon, "quick": quick, "inv": stacks, "inv_capacity": inv.c.capacity}
