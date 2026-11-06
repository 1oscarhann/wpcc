"""The sky over your realm (Phase 10): season and the weather forecast. The day/night phase is computed
on the client from the clock config in the bundle, so it needs no requests."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state
from hearthforge.db.models import Village
from hearthforge.domain import worldclock
from hearthforge.realtime.protocol import EV
from hearthforge.services import realm as realm_svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api", tags=["world"])


@router.get("/world")
async def world(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    realm, _ = await realm_svc.my_member(db, auth.user.id)
    wc = st.config.world_clock
    now = st.clock.now()
    ph = worldclock.day_phase(wc, now)
    weather = worldclock.weather_at(wc, realm.weather_seed, now)
    state = wc.weather.states[weather]
    return {
        "now_ms": int(now.timestamp() * 1000),
        "phase": ph.name,
        "season": worldclock.season(wc, now),
        "season_ends_ms": int(worldclock.season_ends(wc, now).timestamp() * 1000),
        "weather": weather,
        "effects": {"production": state.production, "aggro": state.aggro, "rare_node": state.rare_node},
        "forecast": worldclock.forecast(wc, realm.weather_seed, now, 4),
    }


class TeleportIn(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


@router.post("/dev/teleport")
async def dev_teleport(
    body: TeleportIn, auth: Auth = Depends(current_user), st: AppState = Depends(get_state)
) -> dict[str, Any]:
    """Dev only (HF_ENV=dev): hop your avatar to a tile, for screenshots and playtesting the far rings."""
    if not st.settings.is_dev or st.rooms is None:
        raise HTTPException(404)
    found = st.rooms.find(auth.user.id)
    if found is None:
        raise HTTPException(409, "not_in_world")
    room, p = found
    for r in range(0, 8):
        for dx, dy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r), (r, r), (-r, -r)):
            x, y = body.x + dx, body.y + dy
            if not room.grid.solid(x, y) and room.grid.gen.plot_at(x, y, 0) is None:
                p.m.x, p.m.y = x + 0.5, y + 0.5
                p.inputs.clear()
                p.ko = 0
                p.hp = float(p.stats.hp_max)
                p.iframes = room.hz * 10  # dev hop: a moment of grace to look around (and screenshot)
                p.pending.save_pos = True
                p.ev.append([EV["TELEPORT"], p.m.x, p.m.y, -1])
                biome = "delve" if p.dungeon else room.grid.gen.biome(x, y)
                return {"x": x, "y": y, "biome": biome}
    raise HTTPException(409, "no_open_tile")


class WeakenIn(BaseModel):
    frac: float = Field(default=0.3, gt=0, le=1)


@router.post("/dev/delve-weaken")
async def dev_delve_weaken(
    body: WeakenIn, auth: Auth = Depends(current_user), st: AppState = Depends(get_state)
) -> dict[str, Any]:
    """Dev only (HF_ENV=dev): knock every monster in your delve down to a fraction of its health, so a
    screenshot run can reach the boss's last phase and the portal without a ten-minute fight."""
    if not st.settings.is_dev or st.rooms is None:
        raise HTTPException(404)
    found = st.rooms.find(auth.user.id)
    if found is None:
        raise HTTPException(409, "not_in_world")
    room, p = found
    if room.combat is None or not p.dungeon:
        raise HTTPException(409, "not_in_delve")
    n = 0
    for m in room.combat.monsters.values():
        if m.dungeon == p.dungeon:
            m.hp = min(m.hp, max(1.0, m.hp_max * body.frac))
            n += 1
    return {"weakened": n}


class KitIn(BaseModel):
    town_hall: int = Field(default=3, ge=1, le=5)
    tier: int = Field(default=2, ge=1, le=5)


@router.post("/dev/kit")
async def dev_kit(
    body: KitIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dev only (HF_ENV=dev): a playtest kit. Town Hall level, full storage, one of every weapon and offhand
    (rare, with a modifier), plate armour, potions and food in the bag."""
    import secrets as _secrets
    import uuid as _uuid

    from sqlalchemy import update as _update

    from hearthforge.db.models import (
        ContainerSlot,
        ItemInstance,
        ItemOrigin,
        Rarity,
        Resource,
        VillageBuilding,
    )
    from hearthforge.services import inventory

    if not st.settings.is_dev:
        raise HTTPException(404)
    cfg = st.config
    async with db.begin():
        vid = (await db.execute(select(Village.id).where(Village.user_id == auth.user.id))).scalar_one()
        await db.execute(
            _update(VillageBuilding)
            .where(VillageBuilding.village_id == vid, VillageBuilding.building_key == "town_hall")
            .values(level=body.town_hall)
        )
        await db.execute(_update(Resource).where(Resource.village_id == vid).values(amount_milli=1_500_000))
        bag = (await inventory.bags(db, auth.user.id, ("inventory",)))["inventory"]
        bag.c.capacity = max(bag.c.capacity, 48)
        free = bag.free
        keys = [
            k
            for k, it in cfg.items_cfg.items.items()
            if it.category in ("weapon", "offhand") and k in cfg.recipes.gear
        ]
        keys.append("plate_armour")
        tier = body.tier
        mods = {"elemental_tome": [{"key": "frost", "name": "Frost", "effect": "frost", "value": 0.3}]}
        for k in keys:
            if not free:
                break
            dur = cfg.forging.tiers[tier - 1].durability
            inst = ItemInstance(
                id=_uuid.uuid4(),
                item_key=k,
                tier=tier,
                rarity=Rarity.rare,
                modifiers=mods.get(k, []),
                durability=dur,
                max_durability=dur,
                origin=ItemOrigin.reward,
                roll_seed=_secrets.randbits(62),
            )
            db.add(inst)
            await db.flush()
            db.add(
                ContainerSlot(
                    container_id=bag.c.id, slot=free.pop(0), item_key=k, quantity=1, instance_id=inst.id
                )
            )
        await inventory.grant(
            db,
            cfg,
            auth.user.id,
            {
                "healing_potion": 5,
                "stamina_potion": 3,
                "warrior_stew": 2,
                "swift_tart": 2,
                "small_healing_potion": 5,
            },
            "admin.grant",
        )
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return {"ok": True, "gear": keys}
