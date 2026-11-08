"""Station jobs (Phase 6): intermediates into storage, gear forged at combo stations, the recipe book.

Lock order as everywhere: wallet → village (+ resources, running jobs) → containers.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError, NotFound
from hearthforge.db.models import (
    ContainerSlot,
    CraftJob,
    Discovery,
    DiscoveryKind,
    ItemInstance,
    ItemOrigin,
    JobStatus,
    Rarity,
    VillageBuilding,
)
from hearthforge.domain import combos as combos_dom
from hearthforge.domain import forging
from hearthforge.services import events, inventory, ledger
from hearthforge.services import village as village_svc

Loaded = village_svc.Loaded


def job_slots(cfg: GameConfig, key: str, level: int) -> int:
    table = cfg.recipes.job_slots.get(key) or cfg.recipes.job_slots["default"]
    return table[max(1, min(5, level)) - 1]


def _station(ld: Loaded, station_id: str) -> VillageBuilding:
    b = next((b for b in ld.buildings if str(b.id) == station_id), None)
    if b is None:
        raise NotFound("no_building", "That building isn't in your village.")
    if b.level < 1:
        raise GameError("not_built", "Finish building it first.")
    return b


def _active(cfg: GameConfig, ld: Loaded) -> list[combos_dom.ActiveCombo]:
    return combos_dom.active_combos(cfg.combos.combos, village_svc.combo_nodes(cfg, ld.buildings))


def station_options(cfg: GameConfig, ld: Loaded, station_id: str) -> dict[str, Any]:
    """What this station can make right now, with exact bills (the client never recomputes them)."""
    st = _station(ld, station_id)
    active = _active(cfg, ld)
    inter = [
        {
            "recipe": k,
            "inputs": r.inputs,
            "seconds_per_unit": r.time,
            "max_batch": r.max_batch,
        }
        for k, r in cfg.recipes.intermediates.items()
        if r.station == st.building_key
    ]
    gear = []
    for gk, g in cfg.recipes.gear.items():
        if g.station != st.building_key:
            continue
        found = combos_dom.station_tier(active, cfg.combos.combos, station_id, gk)
        if found is None:
            continue  # locked: the recipe book shows hints instead
        tier, ck = found
        eligible = cfg.combos.combos[ck].legendary_eligible
        gear.append(
            {
                "recipe": gk,
                "name": forging.item_name(cfg, gk, tier),
                "tier": tier,
                "combo": ck,
                "combo_name": cfg.combos.combos[ck].name,
                "bill": forging.bill(cfg, gk, tier),
                "seconds": forging.forge_seconds(cfg, tier),
                "legendary_eligible": eligible,
                "odds": [
                    forging.rarity_odds(cfg, luck, eligible)
                    for luck in range(cfg.forging.max_rare_inputs + 1)
                ],
            }
        )
    brews = []
    for ck, cr in cfg.recipes.consumables.items():
        if cr.station != st.building_key:
            continue
        found = combos_dom.station_tier(active, cfg.combos.combos, station_id, ck)
        if found is None:
            continue
        tier, combo = found
        brews.append(
            {
                "recipe": ck,
                "name": cfg.items_cfg.items[ck].name,
                "inputs": cr.inputs,
                "makes": cr.makes,
                "seconds_per_unit": cr.time,
                "max_batch": cr.max_batch,
                "combo": combo,
                "combo_name": cfg.combos.combos[combo].name,
                "needs_tier": cr.min_tier if tier < cr.min_tier else None,
            }
        )
    jobs = [village_svc.job_view(j) for j in ld.jobs if j.station_building_id == st.id]
    return {
        "station_id": station_id,
        "key": st.building_key,
        "slots": job_slots(cfg, st.building_key, st.level),
        "intermediates": inter,
        "gear": gear,
        "consumables": brews,
        "rare_materials": {
            k: {"modifier": m.name, "range": list(m.range)} for k, m in cfg.forging.modifiers.items()
        },
        "jobs": jobs,
    }


async def start(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    now: datetime,
    station_id: str,
    recipe: str,
    quantity: int = 1,
    rares: list[str] | None = None,
) -> tuple[Loaded, CraftJob]:
    ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    st = _station(ld, station_id)
    busy = sum(1 for j in ld.jobs if j.station_building_id == st.id)
    if busy >= job_slots(cfg, st.building_key, st.level):
        raise GameError("station_busy", "This station is already working. Wait for it or cancel the job.")
    rares = list(rares or [])
    from hearthforge.services import progress as progress_svc

    perks = await progress_svc.perks_of(session, cfg, user_id)  # Phase 16: the crafting branch
    max_rares = cfg.forging.max_rare_inputs + int(perks.get("extra_slot", 0))
    tier: int | None = None
    combo_key: str | None = None
    eligible = False
    if recipe in cfg.recipes.intermediates:
        rec = cfg.recipes.intermediates[recipe]
        if rec.station != st.building_key:
            raise GameError("wrong_station", "This station can't make that.")
        if not 1 <= quantity <= rec.max_batch:
            raise GameError("bad_quantity", f"Make between 1 and {rec.max_batch} at a time.")
        if rares:
            raise GameError("bad_rares", "Rare materials only go into gear.")
        cost = {k: v * quantity for k, v in rec.inputs.items()}
        seconds = rec.time * quantity
        kind = "intermediate"
    elif recipe in cfg.recipes.consumables:
        cr = cfg.recipes.consumables[recipe]
        if cr.station != st.building_key:
            raise GameError("wrong_station", "This station can't brew that.")
        found = combos_dom.station_tier(_active(cfg, ld), cfg.combos.combos, station_id, recipe)
        if found is None:
            raise GameError("combo_needed", "This station needs the right neighbours to make that.")
        ctier, combo_key = found
        if ctier < cr.min_tier:
            raise GameError("tier_too_low", f"Upgrade this combo's buildings to level {cr.min_tier} first.")
        if not 1 <= quantity <= cr.max_batch:
            raise GameError("bad_quantity", f"Make between 1 and {cr.max_batch} at a time.")
        if rares:
            raise GameError("bad_rares", "Rare materials only go into gear.")
        cost = {k: v * quantity for k, v in cr.inputs.items()}
        seconds = cr.time * quantity
        kind = "consumable"
    elif recipe in cfg.recipes.gear:
        g = cfg.recipes.gear[recipe]
        if g.station != st.building_key:
            raise GameError("wrong_station", "This station can't forge that.")
        found = combos_dom.station_tier(_active(cfg, ld), cfg.combos.combos, station_id, recipe)
        if found is None:
            raise GameError("combo_needed", "This station needs the right neighbours to make that.")
        tier, combo_key = found
        eligible = cfg.combos.combos[combo_key].legendary_eligible
        if len(rares) > max_rares:
            raise GameError("bad_rares", f"At most {max_rares} rare materials.")
        for r in rares:
            if r not in cfg.forging.modifiers:
                raise GameError("bad_rares", f"{r} doesn't go into gear.")
        quantity = 1
        cost = forging.bill(cfg, recipe, tier)
        seconds = forging.forge_seconds(cfg, tier)
        kind = "gear"
    else:
        raise GameError("unknown_recipe", "Unknown recipe.")
    if kind in ("gear", "consumable") and perks.get("forge_time"):
        seconds = max(1, int(seconds * max(0.3, 1 - perks["forge_time"])))  # Quick Forge
    staff = sum(
        1 for v in ld.villagers if v.job_building_id == st.id
    )  # Phase 14: staffed stations are quicker
    if staff:
        seconds = max(1, int(seconds * max(0.5, 1 - cfg.villagers.jobs.crafting_speed * staff)))
    job = CraftJob(
        id=uuid.uuid4(),
        user_id=user_id,
        station_building_id=st.id,
        kind=kind,
        recipe_key=recipe,
        combo_key=combo_key,
        tier=tier,
        quantity=quantity,
        inputs={},
        rare_inputs=rares,
        luck=forging.luck_for(cfg, rares) + int(perks.get("forge_luck", 0)),
        legendary_eligible=eligible,
        roll_seed=secrets.randbits(62),
        started_at=now,
        completes_at=now + timedelta(seconds=seconds),
        status=JobStatus.running,
    )
    job.inputs = await village_svc.pay(session, cfg, ld, cost, ledger.CRAFT_START, str(job.id), "craft_job")
    if rares:
        need: dict[str, int] = {}
        for r in rares:
            need[r] = need.get(r, 0) + 1
        taken = await inventory.remove(session, cfg, user_id, need, ledger.CRAFT_START, "inventory")
        if taken != need:
            raise GameError("missing_rares", "You don't have those rare materials in your bag.")
    session.add(job)
    ld.jobs.append(job)
    await session.flush()
    await events.schedule(
        session,
        "craft.complete",
        job.completes_at,
        {"village_id": str(ld.village.id)},
        f"craft:{job.id}",
    )
    village_svc.touch(ld, now)
    return ld, job


def _job(ld: Loaded, job_id: str) -> CraftJob:
    j = next((j for j in ld.jobs if str(j.id) == job_id), None)
    if j is None:
        raise NotFound("no_job", "That job isn't running.")
    return j


async def cancel(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime, job_id: str
) -> tuple[Loaded, dict[str, int]]:
    ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    j = _job(ld, job_id)
    if j.kind in ("gear", "consumable") and j.completes_at <= now:
        raise GameError("job_done", "It's finished: collect it instead!")
    if j.rare_inputs:
        back: dict[str, int] = {}
        for r in j.rare_inputs:
            back[r] = back.get(r, 0) + 1
        left = await inventory.grant(session, cfg, user_id, back, ledger.CRAFT_CANCEL_REFUND)
        if left:
            raise GameError("bag_full", "Make room in your bag for the rare materials first.")
    refunded = await village_svc.refund(
        session, ld, j.inputs, cfg.game.refunds.cancel, ledger.CRAFT_CANCEL_REFUND, str(j.id), "craft_job"
    )
    j.status = JobStatus.cancelled
    ld.jobs.remove(j)
    await events.cancel(session, f"craft:{j.id}")
    village_svc.touch(ld, now)
    return ld, refunded


def item_view(cfg: GameConfig, inst: ItemInstance) -> dict[str, Any]:
    return {
        "instance_id": str(inst.id),
        "item": inst.item_key,
        "name": forging.item_name(cfg, inst.item_key, inst.tier),
        "tier": inst.tier,
        "rarity": inst.rarity.value,
        "modifiers": inst.modifiers,
        "durability": inst.durability,
        "max_durability": inst.max_durability,
    }


async def collect(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime, job_id: str
) -> tuple[Loaded, dict[str, Any]]:
    ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    j = _job(ld, job_id)
    if j.kind == "consumable":
        return await _collect_brew(session, cfg, user_id, now, ld, j)
    if j.kind != "gear":
        raise GameError("auto_collect", "Goods go into storage by themselves.")
    if j.completes_at > now:
        raise GameError("not_ready", "Still on the anvil!")
    bag = (await inventory.bags(session, user_id, ("inventory",)))["inventory"]
    free = bag.free
    if not free:
        raise GameError("bag_full", "Your bag is full. Make some room first.")
    assert j.tier is not None
    f = forging.roll(cfg, j.roll_seed, j.tier, j.luck, list(j.rare_inputs or []), j.legendary_eligible)
    inst = ItemInstance(
        id=uuid.uuid4(),
        item_key=j.recipe_key,
        tier=j.tier,
        rarity=Rarity(f.rarity),
        modifiers=f.modifiers,
        durability=f.durability,
        max_durability=f.durability,
        origin=ItemOrigin.forged,
        crafted_by=user_id,
        roll_seed=j.roll_seed,
    )
    session.add(inst)
    await session.flush()
    session.add(
        ContainerSlot(
            container_id=bag.c.id, slot=free[0], item_key=j.recipe_key, quantity=1, instance_id=inst.id
        )
    )
    ledger.log_item(
        session, user_id, j.recipe_key, 1, ledger.CRAFT_COLLECT, container_id=bag.c.id, instance_id=inst.id
    )
    j.status = JobStatus.collected
    j.result_instance_id = inst.id
    j.collected_at = now
    ld.jobs.remove(j)
    key = f"{j.recipe_key}:{f.rarity}"
    found = await session.get(Discovery, (user_id, DiscoveryKind.recipe, key))
    if found is None:
        session.add(Discovery(user_id=user_id, kind=DiscoveryKind.recipe, key=key, data={}))
    else:
        found.count += 1
    from hearthforge.services import stats

    epic = 1 if f.rarity in ("epic", "legendary") else 0
    await stats.bump(
        session,
        user_id,
        {f"forge.{j.recipe_key}": 1, "forge.any": 1, f"forge.{f.rarity}": 1, "forge.epic_plus": epic},
    )
    village_svc.touch(ld, now)
    await session.flush()
    return ld, item_view(cfg, inst)


async def _collect_brew(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime, ld: Loaded, j: CraftJob
) -> tuple[Loaded, dict[str, Any]]:
    """Potions and food go into your bag as stacks (Phase 11)."""
    if j.completes_at > now:
        raise GameError("not_ready", "Still bubbling!")
    qty = j.quantity * cfg.recipes.consumables[j.recipe_key].makes
    left = await inventory.grant(session, cfg, user_id, {j.recipe_key: qty}, ledger.CRAFT_COLLECT)
    if left:
        raise GameError("bag_full", "Your bag is too full for all of that. Make some room first.")
    j.status = JobStatus.collected
    j.collected_at = now
    ld.jobs.remove(j)
    from hearthforge.services import stats

    await stats.bump(session, user_id, {f"brew.{j.recipe_key}": qty, "brew.any": qty})
    village_svc.touch(ld, now)
    await session.flush()
    return ld, {"item": j.recipe_key, "name": cfg.items_cfg.items[j.recipe_key].name, "quantity": qty}


async def book(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> dict[str, Any]:
    """The recipe book: discovered combos in full, undiscovered ones as '???' with their hint (P17)."""
    rows = (
        await session.execute(
            select(Discovery.kind, Discovery.key).where(
                Discovery.user_id == user_id, Discovery.kind.in_([DiscoveryKind.combo, DiscoveryKind.hint])
            )
        )
    ).all()
    discovered = {k for kind, k in rows if kind == DiscoveryKind.combo}
    hinted = {k for kind, k in rows if kind == DiscoveryKind.hint}  # bought from the merchant (Phase 7)
    combos = []
    for i, (ck, c) in enumerate(cfg.combos.combos.items()):
        if ck in discovered:
            combos.append(
                {
                    "id": ck,
                    "discovered": True,
                    "name": c.name,
                    "buildings": c.buildings,
                    "unlocks": c.unlocks,
                    "hint": c.hint,
                    "legendary_eligible": c.legendary_eligible,
                }
            )
        else:
            entry: dict[str, Any] = {
                "id": f"secret-{i}",
                "discovered": False,
                "size": len(c.buildings),
                "hint": c.hint,
            }
            if ck in hinted:
                entry["revealed"] = c.buildings  # which buildings, but still not what they make
            combos.append(entry)
    return {
        "combos": combos,
        "found": len(discovered & set(cfg.combos.combos)),
        "total": len(cfg.combos.combos),
    }
