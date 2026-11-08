from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state
from hearthforge.clock import to_ms
from hearthforge.config.client_bundle import client_bundle
from hearthforge.db.models import Avatar, Realm, RealmMember, UserSettings, Village
from hearthforge.services.signup import validate_appearance
from hearthforge.state import AppState

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/config")
async def get_config(request: Request, response: Response, st: AppState = Depends(get_state)) -> Any:
    etag = f'"{st.config.hash}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return client_bundle(st.config)


@router.get("/me")
async def me(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    user = auth.user
    avatar = (await db.execute(select(Avatar).where(Avatar.user_id == user.id))).scalar_one()
    member, realm = (
        await db.execute(
            select(RealmMember, Realm)
            .join(Realm, Realm.id == RealmMember.realm_id)
            .where(RealmMember.user_id == user.id)
        )
    ).one()
    village = (await db.execute(select(Village).where(Village.user_id == user.id))).scalar_one()
    settings = (await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))).scalar_one()
    return {
        "user": {
            "id": str(user.id),
            "username": user.username,
            "role": user.role.value,
            "created_at_ms": to_ms(user.created_at),
            "tutorial_step": user.tutorial_step,
        },
        "avatar": {"appearance": avatar.appearance, "level": avatar.level, "xp": avatar.xp, "hp": avatar.hp},
        "realm": {
            "id": str(realm.id),
            "name": realm.name,
            "is_solo": realm.is_solo,
            "plot_index": member.plot_index,
            "role": member.role.value,
        },
        "village": {"id": str(village.id), "name": village.name},
        "settings": {"audio": settings.audio, "graphics": settings.graphics, "keybinds": settings.keybinds},
        "csrf_token": auth.session.csrf_token,
        "server_time_ms": to_ms(st.clock.now()),
        "config_hash": st.config.hash,
    }


class AudioSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    master: float = Field(ge=0, le=1)
    music: float = Field(ge=0, le=1)
    sfx: float = Field(ge=0, le=1)
    muted: bool


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio: AudioSettings | None = None
    graphics: dict[str, bool | int | float | str] | None = None
    # Phase 18: rebound keys, action → up to three KeyboardEvent.key values (only the ones you changed)
    keybinds: dict[str, list[str]] | None = Field(default=None, max_length=40)


@router.put("/me/settings")
async def put_settings(
    body: SettingsIn, auth: Auth = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        row = (
            await db.execute(
                select(UserSettings).where(UserSettings.user_id == auth.user.id).with_for_update()
            )
        ).scalar_one()
        if body.audio is not None:
            row.audio = body.audio.model_dump()
        if body.graphics is not None:
            if len(body.graphics) > 32:
                body.graphics = dict(list(body.graphics.items())[:32])
            row.graphics = body.graphics
        if body.keybinds is not None:
            row.keybinds = {
                a: [k[:12] for k in keys[:3]] for a, keys in body.keybinds.items() if len(a) <= 20 and keys
            }
    return {"audio": row.audio, "graphics": row.graphics, "keybinds": row.keybinds}


class AppearanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appearance: dict[str, Any]


@router.put("/avatar/appearance")
async def put_appearance(
    body: AppearanceIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    look = validate_appearance(st.config, body.appearance)
    async with db.begin():
        avatar = (
            await db.execute(select(Avatar).where(Avatar.user_id == auth.user.id).with_for_update())
        ).scalar_one()
        avatar.appearance = look
    return {"appearance": look}
