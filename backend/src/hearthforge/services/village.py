"""Build Mode: everything that changes a village (PLAN §2.3, BALANCE §2–3).

Every mutation runs in one transaction with row locks taken in the fixed order wallet → village →
resources, settles due timers and resources first, then validates, then pays through the ledger.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.clock import to_ms
from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError, NotFound
from hearthforge.db.base import new_id
from hearthforge.db.models import (
    BuildingState,
    Notification,
    RealmMember,
    Resource,
    Village,
    VillageBuilding,
    Wallet,
)
from hearthforge.domain import mapgen
from hearthforge.domain.economy import BuildingView, caps_milli, rates_milli, town_hall_level
from hearthforge.domain.placement import (
    ERROR_TEXT,
    Placed,
    Rect,
    limit_errors,
    placement_errors,
    rotated_footprint,
)
from hearthforge.domain.resources import MILLI, ResState, settle
from hearthforge.services import events, ledger


@dataclass
class Loaded:
    village: Village
    buildings: list[VillageBuilding]
    resources: dict[str, Resource]
    wallet: Wallet | None
    plot_index: int


# ── loading & settling ──────────────────────────────────────────────────────


async def load_locked(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    village_id: uuid.UUID | None = None,
    with_wallet: bool = False,
) -> Loaded:
    """Lock (wallet →) village → resources for update. Exactly one of user_id / village_id."""
    if user_id is None:
        assert village_id is not None
        uid = (
            await session.execute(select(Village.user_id).where(Village.id == village_id))
        ).scalar_one_or_none()
        if uid is None:
            raise NotFound("no_village", "Village not found.")
        user_id = uid
    wallet = None
    if with_wallet:
        wallet = (
            await session.execute(select(Wallet).where(Wallet.user_id == user_id).with_for_update())
        ).scalar_one()
    village = (
        await session.execute(select(Village).where(Village.user_id == user_id).with_for_update())
    ).scalar_one_or_none()
    if village is None:
        raise NotFound("no_village", "Village not found.")
    buildings = list(
        (
            await session.execute(select(VillageBuilding).where(VillageBuilding.village_id == village.id))
        ).scalars()
    )
    resources = {
        r.resource_key: r
        for r in (
            await session.execute(select(Resource).where(Resource.village_id == village.id).with_for_update())
        ).scalars()
    }
    plot_index = (
        await session.execute(select(RealmMember.plot_index).where(RealmMember.user_id == user_id))
    ).scalar_one()
    return Loaded(village, buildings, resources, wallet, plot_index)


def _views(buildings: list[VillageBuilding]) -> list[BuildingView]:
    return [BuildingView(b.building_key, b.level, b.state.value) for b in buildings]


def _settle_resources(res: dict[str, Resource], at: datetime) -> None:
    for r in res.values():
        s = settle(ResState(r.amount_milli, r.base_rate_milli, r.cap_milli, r.last_updated_at), at)
        r.amount_milli, r.last_updated_at = s.amount, s.at


def _apply_rates(cfg: GameConfig, ld: Loaded) -> None:
    rates = rates_milli(cfg, _views(ld.buildings), ld.village.happiness)
    caps = caps_milli(cfg, _views(ld.buildings))
    for key, r in ld.resources.items():
        r.base_rate_milli = rates.get(key, 0)
        r.cap_milli = caps.get(key, r.cap_milli)


def settle_village(
    session: AsyncSession, cfg: GameConfig, ld: Loaded, now: datetime
) -> list[VillageBuilding]:
    """Complete every timer that is due (oldest first, with rates changing at each completion), then
    bring resources up to `now`. Idempotent: a second call finds nothing due."""
    due = sorted(
        (
            b
            for b in ld.buildings
            if b.state != BuildingState.active and b.work_completes_at and b.work_completes_at <= now
        ),
        key=lambda b: b.work_completes_at,  # type: ignore[arg-type,return-value]
    )
    for b in due:
        at = b.work_completes_at
        assert at is not None
        _settle_resources(ld.resources, at)
        b.level += 1
        b.state = BuildingState.active
        b.work_started_at = None
        b.work_completes_at = None
        b.work_paid = None
        b.helped_seconds = 0
        _apply_rates(cfg, ld)
        session.add(
            Notification(
                user_id=ld.village.user_id,
                kind="building.done",
                payload={"building_id": str(b.id), "key": b.building_key, "level": b.level},
            )
        )
    _settle_resources(ld.resources, now)
    if due:
        ld.village.version += 1
        ld.village.updated_at = now
    return due


# ── state for the client ────────────────────────────────────────────────────


def village_state(cfg: GameConfig, ld: Loaded, now: datetime) -> dict[str, Any]:
    plot = cfg.mapgen.plot
    origin = mapgen.layout(cfg.mapgen).plot_origins[ld.plot_index]
    th = town_hall_level(_views(ld.buildings))
    undo = None
    la = ld.village.last_action
    if la and la.get("expires_at_ms", 0) > to_ms(now):  # type: ignore[operator]
        undo = {"op": la["op"], "expires_at_ms": la["expires_at_ms"]}
    return {
        "owner_id": str(ld.village.user_id),
        "village_id": str(ld.village.id),
        "name": ld.village.name,
        "version": ld.village.version,
        "size": ld.village.size,
        "frame": plot.frame,
        "origin": list(origin),
        "town_hall_level": th,
        "queue": {"slots": cfg.build_queue_slots(th), "used": _queue_used(ld)},
        "buildings": [
            {
                "id": str(b.id),
                "key": b.building_key,
                "x": b.x,
                "y": b.y,
                "rotation": b.rotation,
                "level": b.level,
                "state": b.state.value,
                "started_at_ms": to_ms(b.work_started_at),
                "completes_at_ms": to_ms(b.work_completes_at),
            }
            for b in sorted(ld.buildings, key=lambda b: (b.y, b.x))
        ],
        "resources": {
            k: {
                "amount": r.amount_milli / MILLI,
                "rate": r.base_rate_milli / MILLI,
                "cap": r.cap_milli / MILLI,
            }
            for k, r in ld.resources.items()
        },
        "coins": ld.wallet.coins if ld.wallet else None,
        "at_ms": to_ms(now),
        "undo": undo,
        "blocked": [[plot.pond.x, plot.pond.y, plot.pond.w, plot.pond.h]],
        "water": [[plot.pond.x, plot.pond.y, plot.pond.w, plot.pond.h]],
    }


async def read_state(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime
) -> dict[str, Any]:
    """Lazy path: settle anything due, then return the state."""
    async with session.begin():
        ld = await load_locked(session, user_id=user_id, with_wallet=True)
        settle_village(session, cfg, ld, now)
        return village_state(cfg, ld, now)


# ── helpers ─────────────────────────────────────────────────────────────────


def _queue_used(ld: Loaded) -> int:
    return sum(1 for b in ld.buildings if b.state != BuildingState.active)


def _placed(ld: Loaded, cfg: GameConfig) -> list[Placed]:
    out = []
    for b in ld.buildings:
        w, h = rotated_footprint(cfg.buildings[b.building_key].footprint, b.rotation)
        out.append(Placed(str(b.id), b.building_key, Rect(b.x, b.y, w, h)))
    return out


def _find(ld: Loaded, building_id: str) -> VillageBuilding:
    for b in ld.buildings:
        if str(b.id) == building_id:
            return b
    raise NotFound("no_building", "That building isn't in your village.")


def _raise_placement(errors: list[str]) -> None:
    if errors:
        raise GameError(errors[0], ERROR_TEXT.get(errors[0], "You can't build there."), errors=errors)


async def _pay(
    session: AsyncSession, cfg: GameConfig, ld: Loaded, cost: dict[str, int], reason: str, ref_id: str
) -> dict[str, int]:
    """Check and spend a cost dict (resources + coins). Rare item costs are not wired until Phase 4."""
    missing = {}
    for key, qty in cost.items():
        if key == "coins":
            assert ld.wallet is not None
            if ld.wallet.coins < qty:
                missing[key] = qty - ld.wallet.coins
        elif key in ld.resources:
            have = ld.resources[key].amount_milli
            if have < qty * MILLI:
                missing[key] = math.ceil((qty * MILLI - have) / MILLI)
        else:
            raise GameError("unsupported_cost", f"'{key}' costs arrive in a later update.")
    if missing:
        names = ", ".join(f"{v} {k}" for k, v in missing.items())
        raise GameError("insufficient_resources", f"You need {names} more.", missing=missing)
    for key, qty in cost.items():
        if key == "coins":
            assert ld.wallet is not None
            await ledger.change_coins(session, ld.wallet, -qty, reason, ref_type="building", ref_id=ref_id)
        else:
            ld.resources[key].amount_milli -= qty * MILLI
            ledger.log_resource(
                session,
                ld.village.user_id,
                ld.village.realm_id,
                key,
                -qty * MILLI,
                reason,
                ref_type="building",
                ref_id=ref_id,
            )
    return dict(cost)


async def _refund(
    session: AsyncSession, ld: Loaded, paid: dict[str, int], fraction: float, reason: str, ref_id: str
) -> dict[str, int]:
    out = {}
    for key, qty in paid.items():
        amount = math.floor(qty * fraction)
        if amount <= 0:
            continue
        out[key] = amount
        if key == "coins":
            assert ld.wallet is not None
            await ledger.change_coins(session, ld.wallet, amount, reason, ref_type="building", ref_id=ref_id)
        elif key in ld.resources:
            ld.resources[key].amount_milli += amount * MILLI  # refunds may exceed the cap; never lost
            ledger.log_resource(
                session,
                ld.village.user_id,
                ld.village.realm_id,
                key,
                amount * MILLI,
                reason,
                ref_type="building",
                ref_id=ref_id,
            )
    return out


def _remember(ld: Loaded, cfg: GameConfig, now: datetime, op: str, **data: Any) -> None:
    ld.village.last_action = {
        "op": op,
        "at_ms": to_ms(now),
        "expires_at_ms": to_ms(now + timedelta(seconds=cfg.game.refunds.undo_window)),
        **data,
    }


def _touch(ld: Loaded, now: datetime) -> None:
    ld.village.version += 1
    ld.village.updated_at = now


async def _start_work(
    session: AsyncSession,
    cfg: GameConfig,
    ld: Loaded,
    b: VillageBuilding,
    now: datetime,
    paid: dict[str, int],
    state: BuildingState,
) -> None:
    target = b.level + 1
    secs = cfg.buildings[b.building_key].level(target).time_s
    b.state = state
    b.work_started_at = now
    b.work_completes_at = now + timedelta(seconds=secs)
    b.work_paid = paid
    await session.flush()
    await events.schedule(
        session,
        "building.complete",
        b.work_completes_at,
        {"village_id": str(ld.village.id)},
        events.building_event_key(str(b.id), target, to_ms(now) or 0),
    )


async def _cancel_event(session: AsyncSession, b: VillageBuilding) -> None:
    if b.work_started_at is not None:
        await events.cancel(
            session, events.building_event_key(str(b.id), b.level + 1, to_ms(b.work_started_at) or 0)
        )


# ── actions ─────────────────────────────────────────────────────────────────


async def place(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    now: datetime,
    key: str,
    x: int,
    y: int,
    rotation: int,
) -> Loaded:
    ld = await load_locked(session, user_id=user_id, with_wallet=True)
    settle_village(session, cfg, ld, now)
    if key not in cfg.buildings:
        raise GameError("unknown_building", ERROR_TEXT["unknown_building"])
    th = town_hall_level(_views(ld.buildings))
    count = sum(1 for b in ld.buildings if b.building_key == key)
    _raise_placement(limit_errors(cfg, key, th, count))
    _raise_placement(
        placement_errors(cfg, key, x, y, rotation, size=ld.village.size, existing=_placed(ld, cfg))
    )
    if _queue_used(ld) >= cfg.build_queue_slots(th):
        raise GameError("queue_full", "All your builders are busy. Wait for one to finish.")
    b = VillageBuilding(
        id=new_id(),
        village_id=ld.village.id,
        building_key=key,
        x=x,
        y=y,
        rotation=rotation,
        level=0,
        state=BuildingState.constructing,
        created_at=now,
    )
    paid = await _pay(session, cfg, ld, cfg.buildings[key].level(1).cost, ledger.BUILD_PLACE, str(b.id))
    session.add(b)
    ld.buildings.append(b)
    await _start_work(session, cfg, ld, b, now, paid, BuildingState.constructing)
    _remember(ld, cfg, now, "place", building_id=str(b.id))
    _touch(ld, now)
    return ld


async def move(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    now: datetime,
    building_id: str,
    x: int,
    y: int,
    rotation: int,
) -> Loaded:
    ld = await load_locked(session, user_id=user_id, with_wallet=True)
    settle_village(session, cfg, ld, now)
    b = _find(ld, building_id)
    _raise_placement(
        placement_errors(
            cfg,
            b.building_key,
            x,
            y,
            rotation,
            size=ld.village.size,
            existing=_placed(ld, cfg),
            ignore_id=building_id,
        )
    )
    prev = {"x": b.x, "y": b.y, "rotation": b.rotation}
    b.x, b.y, b.rotation = x, y, rotation
    _remember(ld, cfg, now, "move", building_id=building_id, prev=prev)
    _touch(ld, now)
    return ld


async def demolish(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime, building_id: str
) -> tuple[Loaded, dict[str, int]]:
    ld = await load_locked(session, user_id=user_id, with_wallet=True)
    settle_village(session, cfg, ld, now)
    b = _find(ld, building_id)
    bdef = cfg.buildings[b.building_key]
    if not bdef.cfg.demolishable:
        raise GameError("not_demolishable", f"The {bdef.cfg.name} can't be demolished.")
    if b.state != BuildingState.active:
        await _cancel_event(session, b)
        refunded = await _refund(
            session, ld, b.work_paid or {}, cfg.game.refunds.cancel, ledger.BUILD_CANCEL_REFUND, str(b.id)
        )
        undoable = False
    else:
        refunded = await _refund(
            session,
            ld,
            bdef.level(1).cost,
            cfg.game.refunds.demolish,
            ledger.BUILD_DEMOLISH_REFUND,
            str(b.id),
        )
        undoable = True
    snapshot = {
        "id": str(b.id),
        "key": b.building_key,
        "x": b.x,
        "y": b.y,
        "rotation": b.rotation,
        "level": b.level,
        "refunded": refunded,
    }
    await session.delete(b)
    ld.buildings.remove(b)
    if undoable:
        _remember(ld, cfg, now, "demolish", building=snapshot)
    else:
        ld.village.last_action = None
    _apply_rates(cfg, ld)
    _touch(ld, now)
    return ld, refunded


async def upgrade(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime, building_id: str
) -> Loaded:
    ld = await load_locked(session, user_id=user_id, with_wallet=True)
    settle_village(session, cfg, ld, now)
    b = _find(ld, building_id)
    bdef = cfg.buildings[b.building_key]
    if b.state != BuildingState.active:
        raise GameError("busy", "This building is already being worked on.")
    if b.level >= bdef.cfg.max_level:
        raise GameError("max_level", f"The {bdef.cfg.name} is already at its highest level.")
    th = town_hall_level(_views(ld.buildings))
    if b.building_key != "town_hall" and b.level + 1 > th:
        raise GameError("town_hall_cap", "Upgrade your Town Hall first: buildings can't outgrow it.")
    if _queue_used(ld) >= cfg.build_queue_slots(th):
        raise GameError("queue_full", "All your builders are busy. Wait for one to finish.")
    paid = await _pay(session, cfg, ld, bdef.level(b.level + 1).cost, ledger.BUILD_UPGRADE, str(b.id))
    await _start_work(session, cfg, ld, b, now, paid, BuildingState.upgrading)
    _remember(ld, cfg, now, "upgrade", building_id=building_id)
    _touch(ld, now)
    return ld


async def cancel(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    now: datetime,
    building_id: str,
    fraction: float | None = None,
) -> tuple[Loaded, dict[str, int]]:
    ld = await load_locked(session, user_id=user_id, with_wallet=True)
    settle_village(session, cfg, ld, now)
    b = _find(ld, building_id)
    if b.state == BuildingState.active:
        raise GameError("not_busy", "Nothing to cancel: that work already finished.")
    await _cancel_event(session, b)
    refunded = await _refund(
        session,
        ld,
        b.work_paid or {},
        cfg.game.refunds.cancel if fraction is None else fraction,
        ledger.BUILD_CANCEL_REFUND if fraction is None else ledger.BUILD_UNDO_REFUND,
        str(b.id),
    )
    if b.state == BuildingState.constructing:
        await session.delete(b)
        ld.buildings.remove(b)
    else:
        b.state = BuildingState.active
        b.work_started_at = b.work_completes_at = None
        b.work_paid = None
    ld.village.last_action = None
    _apply_rates(cfg, ld)
    _touch(ld, now)
    return ld, refunded


async def undo(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime) -> Loaded:
    ld = await load_locked(session, user_id=user_id, with_wallet=True)
    la = ld.village.last_action
    if not la or la.get("expires_at_ms", 0) <= (to_ms(now) or 0):
        raise GameError("nothing_to_undo", "There's nothing to undo.")
    settle_village(session, cfg, ld, now)
    op = la["op"]
    if op == "move":
        b = _find(ld, la["building_id"])
        p = la["prev"]
        _raise_placement(
            placement_errors(
                cfg,
                b.building_key,
                p["x"],
                p["y"],
                p["rotation"],
                size=ld.village.size,
                existing=_placed(ld, cfg),
                ignore_id=str(b.id),
            )
        )
        b.x, b.y, b.rotation = p["x"], p["y"], p["rotation"]
    elif op in ("place", "upgrade"):
        b = _find(ld, la["building_id"])
        if b.state != BuildingState.active:
            # full refund, then remove (place) or roll back (upgrade)
            await _cancel_event(session, b)
            await _refund(session, ld, b.work_paid or {}, 1.0, ledger.BUILD_UNDO_REFUND, str(b.id))
            if b.state == BuildingState.constructing:
                await session.delete(b)
                ld.buildings.remove(b)
            else:
                b.state = BuildingState.active
                b.work_started_at = b.work_completes_at = None
                b.work_paid = None
        elif op == "place":
            # already finished building (short timers): remove it, refund its level-1 cost in full
            await _refund(
                session,
                ld,
                cfg.buildings[b.building_key].level(1).cost,
                1.0,
                ledger.BUILD_UNDO_REFUND,
                str(b.id),
            )
            await session.delete(b)
            ld.buildings.remove(b)
        else:
            raise GameError("too_late", "That upgrade already finished.")
    elif op == "demolish":
        snap = la["building"]
        _raise_placement(
            placement_errors(
                cfg,
                snap["key"],
                snap["x"],
                snap["y"],
                snap["rotation"],
                size=ld.village.size,
                existing=_placed(ld, cfg),
            )
        )
        for key, qty in snap["refunded"].items():  # take the demolish refund back
            if key == "coins":
                assert ld.wallet is not None
                await ledger.change_coins(
                    session, ld.wallet, -qty, ledger.BUILD_UNDO_REPAY, ref_id=snap["id"]
                )
            else:
                if ld.resources[key].amount_milli < qty * MILLI:
                    raise GameError(
                        "insufficient_resources", "You already spent the refund, so this can't be undone."
                    )
                ld.resources[key].amount_milli -= qty * MILLI
                ledger.log_resource(
                    session,
                    ld.village.user_id,
                    ld.village.realm_id,
                    key,
                    -qty * MILLI,
                    ledger.BUILD_UNDO_REPAY,
                    ref_type="building",
                    ref_id=snap["id"],
                )
        b = VillageBuilding(
            id=uuid.UUID(snap["id"]),
            village_id=ld.village.id,
            building_key=snap["key"],
            x=snap["x"],
            y=snap["y"],
            rotation=snap["rotation"],
            level=snap["level"],
            state=BuildingState.active,
            created_at=now,
        )
        session.add(b)
        ld.buildings.append(b)
    else:
        raise GameError("nothing_to_undo", "There's nothing to undo.")
    ld.village.last_action = None
    _apply_rates(cfg, ld)
    _touch(ld, now)
    return ld


async def preview(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    key: str,
    x: int,
    y: int,
    rotation: int,
    move_id: str | None,
) -> dict[str, Any]:
    """Read-only placement check for the ghost (D-013). Combos join in Phase 6."""
    village = (await session.execute(select(Village).where(Village.user_id == user_id))).scalar_one()
    buildings = list(
        (
            await session.execute(select(VillageBuilding).where(VillageBuilding.village_id == village.id))
        ).scalars()
    )
    ld = Loaded(village, buildings, {}, None, 0)
    errors = placement_errors(
        cfg, key, x, y, rotation, size=village.size, existing=_placed(ld, cfg), ignore_id=move_id
    )
    if move_id is None and key in cfg.buildings:
        th = town_hall_level(_views(buildings))
        errors += limit_errors(cfg, key, th, sum(1 for b in buildings if b.building_key == key))
    return {
        "valid": not errors,
        "errors": errors,
        "reason": ERROR_TEXT.get(errors[0]) if errors else None,
        "combos": [],
        "mystery": 0,
    }


async def fast_forward(session: AsyncSession, user_id: uuid.UUID, seconds: float) -> None:
    """Admin/test tool (D-014): shift this village's timestamps into the past."""
    from sqlalchemy import update

    from hearthforge.db.models import ScheduledEvent

    delta = timedelta(seconds=seconds)
    village = (
        await session.execute(select(Village).where(Village.user_id == user_id).with_for_update())
    ).scalar_one()
    await session.execute(
        update(Resource)
        .where(Resource.village_id == village.id)
        .values(last_updated_at=Resource.last_updated_at - delta)
    )
    await session.execute(
        update(VillageBuilding)
        .where(VillageBuilding.village_id == village.id, VillageBuilding.work_started_at.is_not(None))
        .values(
            work_started_at=VillageBuilding.work_started_at - delta,
            work_completes_at=VillageBuilding.work_completes_at - delta,
        )
    )
    await session.execute(
        update(ScheduledEvent)
        .where(
            ScheduledEvent.payload["village_id"].astext == str(village.id), ScheduledEvent.status == "pending"
        )
        .values(due_at=ScheduledEvent.due_at - delta)
    )
