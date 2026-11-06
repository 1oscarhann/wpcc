"""Write-behind persistence for a RealmRoom: one transaction per player per flush (PLAN §2.4)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from hearthforge.db.models import Avatar, AvatarLocation, DeathDrop, ItemInstance, NodeHarvest
from hearthforge.realtime.protocol import EV
from hearthforge.services import inventory, ledger, stats
from hearthforge.services import village as village_svc

if TYPE_CHECKING:
    from hearthforge.sim.room import Pending, Player, RealmRoom

log = logging.getLogger("hearthforge.persist")


@dataclass
class FlushResult:
    leftovers: dict[str, int] = field(default_factory=dict)
    deposited: dict[str, int] = field(default_factory=dict)
    deposit_capped: bool = False
    village_state: dict[str, Any] | None = None
    coins: int | None = None


async def flush_player(room: RealmRoom, p: Player, ops: Pending) -> FlushResult:
    st, cfg = room.st, room.cfg
    now = st.clock.now()
    res = FlushResult()
    async with st.sessionmaker() as s, s.begin():
        # lock order: wallet → village → containers (PLAN §2.2)
        ld = None
        wallet = None
        if ops.deposit:
            ld = await village_svc.load_locked(s, user_id=p.user_id, with_wallet=True)
            village_svc.settle_village(s, cfg, ld, now)
            wallet = ld.wallet
        elif ops.coins:
            wallet = await ledger.lock_wallet(s, p.user_id)
        if ops.coins and wallet is not None:
            res.coins = await ledger.change_coins(
                s, wallet, ops.coins, ledger.LOOT_COINS, ref_type="realm", ref_id=str(room.realm_id)
            )
        if ops.grants:
            res.leftovers = await inventory.grant(s, cfg, p.user_id, dict(ops.grants), ledger.AVATAR_GATHER)
        if ops.recovered:
            left = await inventory.grant(s, cfg, p.user_id, dict(ops.recovered), ledger.KO_RECOVER)
            for k, q in left.items():
                res.leftovers[k] = res.leftovers.get(k, 0) + q
        if ops.removed:
            await inventory.remove(s, cfg, p.user_id, dict(ops.removed), ledger.KO_LOSS, "inventory")
        for death_id, x, y, items, expires in ops.death_drops:
            s.add(
                DeathDrop(
                    id=death_id,
                    realm_id=room.realm_id,
                    user_id=p.user_id,
                    x=x,
                    y=y,
                    items=[{"item_key": k, "qty": q} for k, q in items.items()],
                    expires_at=datetime.fromtimestamp(expires, UTC),
                )
            )
        if ops.recovered_ids:
            await s.flush()
            await s.execute(
                update(DeathDrop)
                .where(DeathDrop.id.in_(list(ops.recovered_ids)), DeathDrop.recovered_at.is_(None))
                .values(recovered_at=now, recovered_by=p.user_id)
            )
        if ops.consumed:
            await inventory.remove(s, cfg, p.user_id, dict(ops.consumed), ledger.ITEM_CONSUME, "equipment")
        if ops.deposit and ld is not None:
            moved, ld = await inventory.deposit(s, cfg, p.user_id, now, ld)
            res.deposited = moved
            res.deposit_capped = any(
                r.amount_milli >= r.cap_milli for k, r in ld.resources.items() if k in moved or _has(p, k)
            )
            if moved:
                res.village_state = village_svc.village_state(cfg, ld, now)
        if ops.durability and p.weapon.get("instance_id"):
            await s.execute(
                update(ItemInstance)
                .where(ItemInstance.id == uuid.UUID(p.weapon["instance_id"]))
                .values(durability=max(0, int(p.weapon.get("durability", 0))))
            )
        if ops.xp or ops.save_pos:
            av = (
                await s.execute(select(Avatar).where(Avatar.user_id == p.user_id).with_for_update())
            ).scalar_one()
            av.level, av.xp = p.level, p.xp
            av.hp = max(1, round(p.hp))
            if ops.save_pos:
                # in a delve you're saved at its entrance: instances don't outlive the room (Phase 12)
                av.pos_x, av.pos_y = p.dungeon_return if p.dungeon and p.dungeon_return else (p.m.x, p.m.y)
                av.realm_id = room.realm_id
                av.location = AvatarLocation.wild
                av.updated_at = now
        if ops.stats:
            await stats.bump(s, p.user_id, ops.stats)
        if ops.fog or ops.waystones:
            from hearthforge.services import world as world_svc

            await world_svc.persist_room_progress(s, room, p, ops)
        if ops.harvests:
            rows = [
                {
                    "user_id": p.user_id,
                    "realm_id": room.realm_id,
                    "node_id": nid,
                    "respawn_at": datetime.fromtimestamp(at, UTC),
                }
                for nid, at in ops.harvests
            ]
            stmt = insert(NodeHarvest).values(rows)
            await s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["user_id", "realm_id", "node_id"],
                    set_={"respawn_at": stmt.excluded.respawn_at},
                )
            )
            await s.execute(
                delete(NodeHarvest).where(
                    NodeHarvest.user_id == p.user_id,
                    NodeHarvest.realm_id == room.realm_id,
                    NodeHarvest.respawn_at < now,
                )
            )
    if st.village_hub is not None:
        if res.village_state is not None:
            await st.village_hub.publish(str(p.user_id), res.village_state)
        elif ops.coins:
            await st.village_hub.publish(str(p.user_id))  # the coin counter lives in the village HUD
    return res


def _has(p: Player, key: str) -> bool:
    return any(s[1] == key for s in p.inv)


def apply_result(room: RealmRoom, p: Player, r: FlushResult) -> None:
    """Back on the room's side: fix the inventory mirror and tell the player what happened."""
    if r.leftovers:
        # the bag changed under us (e.g. REST moved things): put what didn't fit back on the ground
        for key, qty in r.leftovers.items():
            room.inv_remove(p, key, qty)
            room.spawn_drop(p, key, qty, p.m.x, p.m.y)
        room.toast(p, "bag_full")
        p.ev.append([EV["INVENTORY"], p.inv])
    if r.deposited:
        for key, qty in r.deposited.items():
            room.inv_remove(p, key, qty)
        p.ev.append([EV["DEPOSIT"], r.deposited])
        p.ev.append([EV["INVENTORY"], p.inv])
    if r.deposit_capped and room.has_resources(p):
        room.toast(p, "storage_full")
        p.deposit_wait = room.hz * 20
