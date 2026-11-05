"""The sky over your realm (Phase 10): season and the weather forecast. The day/night phase is computed
on the client from the clock config in the bundle, so it needs no requests."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state
from hearthforge.domain import worldclock
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
