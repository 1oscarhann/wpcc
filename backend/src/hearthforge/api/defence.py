"""Waves and realm bosses (Phase 13): what's coming, what happened, and dev triggers for playtests."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state
from hearthforge.clock import to_ms
from hearthforge.services import waves as wave_svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api", tags=["defence"])


@router.get("/waves")
async def waves(auth: Auth = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await wave_svc.current(db, auth.user.id)


class DevWaveIn(BaseModel):
    warning: float = Field(default=5, ge=1, le=600)
    town_hall: int | None = Field(default=None, ge=2, le=5)


@router.post("/dev/wave")
async def dev_wave(
    body: DevWaveIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dev only (HF_ENV=dev): announce a wave on your village now, skipping the eligibility rules."""
    if not st.settings.is_dev or st.rooms is None:
        raise HTTPException(404)
    now = st.clock.now()
    cur = await wave_svc.current(db, auth.user.id)
    if cur["current"] is not None:
        raise HTTPException(409, "wave_live")
    _ok, _again, th = await wave_svc.eligible(db, st.config, auth.user.id, now)
    w = await wave_svc.announce(
        db, st.config, auth.user.id, body.town_hall or max(2, th), now, warning=body.warning
    )
    await db.commit()
    uid = str(auth.user.id)
    st.rooms.announced[uid] = to_ms(w.starts_at) or 0
    payload = {"status": "announced", "id": str(w.id), "starts_at_ms": to_ms(w.starts_at)}
    if st.village_hub is not None:
        await st.village_hub.notify([uid], "wave", payload)
    return payload


@router.get("/bosses")
async def bosses(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from sqlalchemy import select

    from hearthforge.db.models import RealmMember
    from hearthforge.services import bosses as boss_svc

    rid = (
        await db.execute(select(RealmMember.realm_id).where(RealmMember.user_id == auth.user.id))
    ).scalar_one()
    return await boss_svc.view(db, st.config, rid, st.clock.now())


class DevBossIn(BaseModel):
    key: str
    distance: float = Field(default=8, ge=0, le=60)


@router.post("/dev/boss")
async def dev_boss(
    body: DevBossIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dev only (HF_ENV=dev): wake a realm boss a few tiles from your avatar, now."""
    from hearthforge.services import bosses as boss_svc

    if not st.settings.is_dev or st.rooms is None:
        raise HTTPException(404)
    if body.key not in st.config.bosses.bosses:
        raise HTTPException(404, "unknown_boss")
    found = st.rooms.find(auth.user.id)
    if found is None:
        raise HTTPException(409, "not_in_world")
    room, p = found
    row = await boss_svc.spawn_now(
        db, st.config, room.realm_id, body.key, p.m.x + body.distance, p.m.y, st.clock.now()
    )
    await db.commit()
    if room.bosses is not None:
        room.bosses.reload = True
    return {"id": str(row.id), "x": row.lair_x, "y": row.lair_y}
