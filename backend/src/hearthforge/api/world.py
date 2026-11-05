"""The sky over your realm (Phase 10): season and the weather forecast. The day/night phase is computed
on the client from the clock config in the bundle, so it needs no requests."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state
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
                return {"x": x, "y": y, "biome": room.grid.gen.biome(x, y)}
    raise HTTPException(409, "no_open_tile")
