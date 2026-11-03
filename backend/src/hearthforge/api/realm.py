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
