"""Phase 15: friends, blocks, mail, gifts, visits, likes and neighbour help."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state, rate_limit
from hearthforge.core.errors import GameError
from hearthforge.services import social as svc
from hearthforge.services import village as village_svc
from hearthforge.state import AppState

router = APIRouter(prefix="/api/social", tags=["social"])
act = rate_limit("village", "actions_per_min")


class NameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)


class UserIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID


class RespondIn(UserIn):
    accept: bool


class GiftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: uuid.UUID
    items: dict[str, int] = Field(min_length=1, max_length=10)


class HelpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    building_id: uuid.UUID


async def _view(st: AppState, db: AsyncSession, uid: uuid.UUID) -> dict[str, Any]:
    online = st.village_hub.online() if st.village_hub is not None else set()
    return await svc.friends_view(db, st.config, uid, online)


async def _refresh_rooms(st: AppState, *uids: uuid.UUID) -> None:
    if st.rooms is not None:
        for u in uids:
            await st.rooms.reload_progress(u)


@router.get("")
async def social(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    out = await _view(st, db, auth.user.id)
    out["mail"] = await svc.mailbox(db, st.config, auth.user.id, st.clock.now())
    return out


@router.post("/request", dependencies=[Depends(act)])
async def request(
    body: NameIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        result = await svc.request(db, st.config, auth.user.id, body.name, st.clock.now())
        target = await svc.user_named(db, body.name)
    if st.village_hub is not None:
        await st.village_hub.notify([str(target.id)], "social", {"kind": f"friend_{result}"})
    return {"result": result, **(await _view(st, db, auth.user.id))}


@router.post("/respond", dependencies=[Depends(act)])
async def respond(
    body: RespondIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        result = await svc.respond(db, auth.user.id, body.user_id, body.accept, st.clock.now())
    if st.village_hub is not None:
        await st.village_hub.notify([str(body.user_id)], "social", {"kind": f"friend_{result}"})
    return {"result": result, **(await _view(st, db, auth.user.id))}


@router.post("/remove", dependencies=[Depends(act)])
async def remove(
    body: UserIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.remove(db, auth.user.id, body.user_id)
    return await _view(st, db, auth.user.id)


@router.post("/block", dependencies=[Depends(act)])
async def block(
    body: UserIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.block(db, auth.user.id, body.user_id)
    await _refresh_rooms(st, auth.user.id, body.user_id)
    return await _view(st, db, auth.user.id)


@router.post("/unblock", dependencies=[Depends(act)])
async def unblock(
    body: UserIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.unblock(db, auth.user.id, body.user_id)
    await _refresh_rooms(st, auth.user.id, body.user_id)
    return await _view(st, db, auth.user.id)


@router.post("/mail/{mail_id}/claim", dependencies=[Depends(act)])
async def claim_mail(
    mail_id: uuid.UUID,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        got = await svc.claim_mail(db, st.config, auth.user.id, str(mail_id), st.clock.now())
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    return {"got": got, "mail": await svc.mailbox(db, st.config, auth.user.id, st.clock.now())}


@router.post("/gift", dependencies=[Depends(act)])
async def gift(
    body: GiftIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await svc.send_gift(db, st.config, auth.user.id, body.to, body.items, st.clock.now())
    if st.rooms is not None:
        await st.rooms.reload_loadout(auth.user.id)
    if st.village_hub is not None:
        await st.village_hub.notify([str(body.to)], "social", {"kind": "mail"})
    return {"sent": True}


@router.get("/visit/{owner_id}")
async def visit(
    owner_id: uuid.UUID,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        if not await svc.can_visit(db, auth.user.id, owner_id):
            raise GameError("cant_visit", "You can only visit friends and realm-mates.")
    state = await village_svc.read_state(db, st.config, owner_id, st.clock.now())
    async with db.begin():
        return await svc.visit(db, st.config, auth.user.id, owner_id, state, st.clock.now())


@router.post("/like/{owner_id}", dependencies=[Depends(act)])
async def like(
    owner_id: uuid.UUID,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        return await svc.like(db, st.config, auth.user.id, owner_id, st.clock.now())


@router.post("/help", dependencies=[Depends(act)])
async def help_building(
    body: HelpIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        out = await svc.help_building(db, st.config, auth.user.id, str(body.building_id), st.clock.now())
    if st.village_hub is not None:
        await st.village_hub.publish(out["owner"])  # the owner sees the timer drop
        await st.village_hub.notify([out["owner"]], "social", {"kind": "helped"})
    return out
