from __future__ import annotations

from typing import Any

import msgpack
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, current_user, get_db, get_state
from hearthforge.core.errors import Forbidden, GameError
from hearthforge.db.models import Realm, RealmMember, User
from hearthforge.domain import mapgen
from hearthforge.services import plots
from hearthforge.state import AppState

router = APIRouter(prefix="/api", tags=["realm"])
MAX_CHUNKS = 64


async def _my_realm(db: AsyncSession, auth: Auth) -> tuple[Realm, RealmMember]:
    row = (
        await db.execute(
            select(Realm, RealmMember)
            .join(RealmMember, RealmMember.realm_id == Realm.id)
            .where(RealmMember.user_id == auth.user.id)
        )
    ).one()
    return row[0], row[1]


@router.get("/realm/map")
async def realm_map(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    realm, me = await _my_realm(db, auth)
    lay = mapgen.layout(st.config.mapgen)
    members = {
        m.plot_index: name
        for m, name in (
            await db.execute(
                select(RealmMember, User.username)
                .join(User, User.id == RealmMember.user_id)
                .where(RealmMember.realm_id == realm.id)
            )
        ).all()
    }
    return {
        "realm_id": str(realm.id),
        "version": realm.mapgen_version,
        "size": lay.size,
        "chunk_size": st.config.mapgen.chunk_size,
        "tile_names": mapgen.TILE_NAMES,
        "object_names": mapgen.OBJECT_NAMES,
        "hub": {"center": lay.center, "radius": lay.hub_radius},
        "plots": [
            {"index": i, "origin": list(o), "owner": members.get(i), "gate": list(plots.gate(st.config, i))}
            for i, o in enumerate(lay.plot_origins)
        ],
        "start_size": st.config.mapgen.plot.start_size,
        "my_plot": me.plot_index,
    }


@router.get("/realms/{realm_id}/chunks")
async def chunks(
    realm_id: str,
    ids: str = Query(max_length=2000, description="cx_cy;cx_cy;…"),
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> Response:
    realm, _ = await _my_realm(db, auth)
    if str(realm.id) != realm_id:
        raise Forbidden("not_member", "You can only load your own realm.")
    if realm.mapgen_version != st.config.mapgen.version:
        raise GameError("mapgen_version", "This realm was made with a different map generator version.")
    gen = mapgen.generator(st.config, realm.seed)
    n = st.config.mapgen.map_size // st.config.mapgen.chunk_size
    out = []
    for part in ids.split(";")[:MAX_CHUNKS]:
        try:
            cx, cy = (int(v) for v in part.split("_"))
        except ValueError:
            continue
        if 0 <= cx < n and 0 <= cy < n:
            out.append(gen.chunk(cx, cy))
    body = msgpack.packb({"v": realm.mapgen_version, "chunks": out}, use_bin_type=True)
    return Response(
        content=body, media_type="application/msgpack", headers={"Cache-Control": "private, max-age=86400"}
    )


# ── Phase 9: realms, stash, activity, exploration ────────────────────────────

import base64  # noqa: E402
import uuid  # noqa: E402

from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

from hearthforge.api.deps import rate_limit  # noqa: E402
from hearthforge.services import activity as activity_svc  # noqa: E402
from hearthforge.services import realm as realm_svc  # noqa: E402
from hearthforge.services import stash as stash_svc  # noqa: E402
from hearthforge.services import village as village_svc  # noqa: E402
from hearthforge.services import world as world_svc  # noqa: E402

act = rate_limit("realm", "actions_per_min")


class NameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=60)


class CodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=4, max_length=10)


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID


class TrustIn(MemberIn):
    trusted: bool


class StashMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: int = Field(ge=0, le=254)
    quantity: int = Field(default=1, ge=1, le=9999)


async def _realm_view(db: AsyncSession, st: AppState, user_id: uuid.UUID) -> dict[str, Any]:
    realm, me = await realm_svc.my_member(db, user_id)
    rows = await realm_svc.members(db, realm.id)
    online = st.village_hub.online() if st.village_hub is not None else set()
    return realm_svc.view(st.config, realm, me, rows, online, st.clock.now())


async def _after_change(
    st: AppState, realm_ids: list[uuid.UUID], moved: list[uuid.UUID], notify: set[str]
) -> None:
    """Rooms reload their villages, moved players drop back to Build Mode, everyone refetches."""
    if st.rooms is not None:
        for uid in moved:
            await st.rooms.evict(uid)
        for rid in realm_ids:
            await st.rooms.refresh_realm(rid)
    if st.village_hub is not None:
        await st.village_hub.notify(notify, "realm")


async def _member_ids(db: AsyncSession, realm_id: uuid.UUID) -> set[str]:
    return {
        str(u)
        for u in (
            await db.execute(select(RealmMember.user_id).where(RealmMember.realm_id == realm_id))
        ).scalars()
    }


@router.get("/realm")
async def get_realm(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return {"realm": await _realm_view(db, st, auth.user.id)}


@router.post("/realms", dependencies=[Depends(act)])
async def found_realm(
    body: NameIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Open your solo realm to friends: it gets a name and an invite code."""
    async with db.begin():
        realm = await realm_svc.found(db, st.config, auth.user.id, body.name, st.clock.now())
        out = {"realm": await _realm_view(db, st, auth.user.id)}
    await _after_change(st, [], [], {str(auth.user.id)})
    _ = realm
    return out


@router.post("/realms/join", dependencies=[Depends(act)])
async def join_realm(
    body: CodeIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        target = await realm_svc.join(db, st.config, auth.user.id, body.code, st.clock.now())
        out = {"realm": await _realm_view(db, st, auth.user.id)}
        notify = await _member_ids(db, target.id)
    await _after_change(st, [target.id], [auth.user.id], notify)
    return out


@router.post("/realm/leave", dependencies=[Depends(act)])
async def leave_realm(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        old, new = await realm_svc.leave(db, st.config, auth.user.id, st.clock.now())
        out = {"realm": await _realm_view(db, st, auth.user.id)}
        notify = await _member_ids(db, old.id) | {str(auth.user.id)}
    moved = [auth.user.id] if new.id != old.id else []
    await _after_change(st, [old.id], moved, notify)
    return out


@router.post("/realm/kick", dependencies=[Depends(act)])
async def kick(
    body: MemberIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        realm, _ = await realm_svc.my_member(db, auth.user.id)
        await realm_svc.kick(db, st.config, auth.user.id, body.user_id, st.clock.now())
        out = {"realm": await _realm_view(db, st, auth.user.id)}
        notify = await _member_ids(db, realm.id) | {str(body.user_id)}
    await _after_change(st, [realm.id], [body.user_id], notify)
    return out


@router.post("/realm/transfer", dependencies=[Depends(act)])
async def transfer(
    body: MemberIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        realm, _ = await realm_svc.my_member(db, auth.user.id)
        await realm_svc.transfer(db, auth.user.id, body.user_id, st.clock.now())
        out = {"realm": await _realm_view(db, st, auth.user.id)}
        notify = await _member_ids(db, realm.id)
    await _after_change(st, [], [], notify)
    return out


@router.post("/realm/trust", dependencies=[Depends(act)])
async def trust(
    body: TrustIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        realm, _ = await realm_svc.my_member(db, auth.user.id)
        await realm_svc.trust(db, auth.user.id, body.user_id, body.trusted, st.clock.now())
        out = {"realm": await _realm_view(db, st, auth.user.id)}
        notify = await _member_ids(db, realm.id)
    await _after_change(st, [], [], notify)
    return out


@router.patch("/realm", dependencies=[Depends(act)])
async def rename(
    body: NameIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        realm, _ = await realm_svc.my_member(db, auth.user.id)
        await realm_svc.rename(db, st.config, auth.user.id, body.name, st.clock.now())
        out = {"realm": await _realm_view(db, st, auth.user.id)}
        notify = await _member_ids(db, realm.id)
    await _after_change(st, [], [], notify)
    return out


@router.post("/realm/invite-code", dependencies=[Depends(act)])
async def invite_code(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        code = await realm_svc.new_invite_code(db, auth.user.id)
    return {"invite_code": code}


@router.get("/realm/activity")
async def realm_activity(
    before: int | None = None,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    realm, _ = await realm_svc.my_member(db, auth.user.id)
    return {"items": await activity_svc.feed(db, realm.id, before)}


@router.get("/realm/stash")
async def get_stash(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    async with db.begin():
        return await stash_svc.view(db, st.config, auth.user.id, st.clock.now())


def _home_only(st: AppState, auth: Auth) -> None:
    if st.rooms is not None and st.rooms.find(auth.user.id):
        raise GameError("stash_far", "The stash is back in your village. Head home to use it.")


@router.post("/realm/stash/deposit", dependencies=[Depends(act)])
async def stash_deposit(
    body: StashMoveIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _home_only(st, auth)
    async with db.begin():
        moved = await stash_svc.deposit(db, st.config, auth.user.id, body.slot, body.quantity, st.clock.now())
    async with db.begin():
        out = {"moved": moved, "stash": await stash_svc.view(db, st.config, auth.user.id, st.clock.now())}
    return out


@router.post("/realm/stash/withdraw", dependencies=[Depends(act)])
async def stash_withdraw(
    body: StashMoveIn,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _home_only(st, auth)
    async with db.begin():
        moved = await stash_svc.withdraw(
            db, st.config, auth.user.id, body.slot, body.quantity, st.clock.now()
        )
    async with db.begin():
        out = {"moved": moved, "stash": await stash_svc.view(db, st.config, auth.user.id, st.clock.now())}
    return out


@router.get("/realm/villages")
async def mate_villages(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Your realm-mates' villages, so you can see them in the world (read only)."""
    realm, _ = await realm_svc.my_member(db, auth.user.id)
    ids = [
        u
        for u in (
            await db.execute(select(RealmMember.user_id).where(RealmMember.realm_id == realm.id))
        ).scalars()
        if u != auth.user.id
    ]
    await db.commit()
    out = []
    for uid in ids:
        state = await village_svc.read_state(db, st.config, uid, st.clock.now())
        out.append(
            {
                k: state[k]
                for k in (
                    "owner_id",
                    "name",
                    "version",
                    "size",
                    "frame",
                    "origin",
                    "buildings",
                    "debris",
                    "gate",
                )
            }
        )
    return {"villages": out}


@router.get("/realm/overview")
async def overview(
    auth: Auth = Depends(current_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Everything the mini-map and full map need: a byte per chunk, your fog, and the waystones."""
    realm, _ = await realm_svc.my_member(db, auth.user.id)
    fog = await world_svc.load_fog(db, st.config, auth.user.id, realm.id)
    attuned = await world_svc.attuned(db, auth.user.id)
    uses = await world_svc.poi_uses(db, auth.user.id)
    return {
        "n": world_svc.chunks_per_side(st.config),
        "chunk_size": st.config.mapgen.chunk_size,
        "data": base64.b64encode(world_svc.overview(st.config, realm.seed)).decode(),
        "fog": base64.b64encode(bytes(fog)).decode(),
        "reveal_radius": st.config.social.fog.reveal_radius,
        "waystones": world_svc.waystone_list(st.config),
        "attuned": sorted(attuned),
        "use_radius": st.config.social.waystone.use_radius,
        "pois": world_svc.poi_list(st.config, realm.seed, uses),
        "poi_radius": st.config.pois.interact_radius,
    }
