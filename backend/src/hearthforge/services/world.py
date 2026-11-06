"""Exploration state (Phase 9): fog of war (one bit per chunk per player per realm), attuned
waystones (P12), and the coarse realm overview the mini-map and full map draw from."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.db.models import Discovery, DiscoveryKind, FogReveal
from hearthforge.domain import mapgen

if TYPE_CHECKING:
    from hearthforge.sim.room import Pending, Player, RealmRoom

# overview colour codes (the client owns the palette)
OV = {"water": 0, "grass": 1, "forest": 2, "path": 3, "cobble": 4, "plot": 5}


def chunks_per_side(cfg: GameConfig) -> int:
    return cfg.mapgen.map_size // cfg.mapgen.chunk_size


def empty_fog(cfg: GameConfig) -> bytearray:
    n = chunks_per_side(cfg)
    return bytearray((n * n + 7) // 8)


def reveal(cfg: GameConfig, bits: bytearray, cx: int, cy: int, radius: int) -> bool:
    """Set the bits for chunks within `radius` of (cx, cy). Returns True if anything was new."""
    n = chunks_per_side(cfg)
    new = False
    for y in range(max(0, cy - radius), min(n, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(n, cx + radius + 1)):
            i = y * n + x
            if not bits[i >> 3] & (1 << (i & 7)):
                bits[i >> 3] |= 1 << (i & 7)
                new = True
    return new


async def load_fog(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, realm_id: uuid.UUID
) -> bytearray:
    row = await session.get(FogReveal, (user_id, realm_id))
    bits = empty_fog(cfg)
    if row is not None and len(row.bits) == len(bits):
        bits[:] = row.bits
    return bits


async def attuned(session: AsyncSession, user_id: uuid.UUID) -> set[int]:
    keys = (
        await session.execute(
            select(Discovery.key).where(
                Discovery.user_id == user_id, Discovery.kind == DiscoveryKind.waystone
            )
        )
    ).scalars()
    return {int(k) for k in keys}


async def poi_uses(session: AsyncSession, user_id: uuid.UUID) -> dict[str, float]:
    """POIs this player has used (Phase 10): "x,y" → when, epoch seconds."""
    rows = (
        await session.execute(
            select(Discovery.key, Discovery.data).where(
                Discovery.user_id == user_id, Discovery.kind == DiscoveryKind.poi
            )
        )
    ).all()
    return {k: float((d or {}).get("at", 0)) for k, d in rows}


async def persist_room_progress(session: AsyncSession, room: RealmRoom, p: Player, ops: Pending) -> None:
    now = room.st.clock.now()
    if ops.fog and p.fog is not None:
        stmt = insert(FogReveal).values(
            user_id=p.user_id, realm_id=room.realm_id, bits=bytes(p.fog), updated_at=now
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[FogReveal.user_id, FogReveal.realm_id],
                set_={"bits": stmt.excluded.bits, "updated_at": stmt.excluded.updated_at},
            )
        )
    for key, at in ops.pois.items():
        stmt = insert(Discovery).values(
            user_id=p.user_id, kind=DiscoveryKind.poi, key=key, count=1, data={"at": at}
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "kind", "key"],
                set_={"data": stmt.excluded.data, "count": Discovery.count + 1},
            )
        )
    for lk in ops.lore:
        await session.execute(
            insert(Discovery)
            .values(user_id=p.user_id, kind=DiscoveryKind.lore, key=lk, count=1, data={})
            .on_conflict_do_nothing(index_elements=["user_id", "kind", "key"])
        )
    for w in ops.waystones:
        await session.execute(
            insert(Discovery)
            .values(user_id=p.user_id, kind=DiscoveryKind.waystone, key=str(w), count=1, data={})
            .on_conflict_do_nothing(index_elements=["user_id", "kind", "key"])
        )


_OVERVIEWS: dict[tuple[str, int], bytes] = {}


def _overview(cfg: Any, seed: int) -> bytes:
    gen = mapgen.generator(cfg, seed)
    n = chunks_per_side(cfg)
    cs = cfg.mapgen.chunk_size
    out = bytearray(n * n)
    for cy in range(n):
        for cx in range(n):
            x, y = cx * cs + cs // 2, cy * cs + cs // 2
            if gen.plot_at(x, y) is not None:
                out[cy * n + cx] = OV["plot"]
                continue
            out[cy * n + cx] = OV.get(gen.kind(x, y), 1)
    return bytes(out)


def overview(cfg: GameConfig, seed: int) -> bytes:
    """One byte per chunk: what the middle of the chunk is (water, grass, forest, path, hub, plot)."""
    key = (cfg.hash, seed)
    hit = _OVERVIEWS.get(key)
    if hit is None:
        if len(_OVERVIEWS) > 32:
            _OVERVIEWS.clear()
        hit = _OVERVIEWS[key] = _overview(cfg, seed)
    return hit


POI_NAMES = {
    "ruins": "Old Ruins",
    "shrine": "Shrine",
    "lore_stone": "Lore Stone",
    "cave": "Sealed Cave",
    "merchant": "Wandering Trader",
    "lost_villager": "Lost Villager",
    "delve": "Delve Gate",
}


def poi_list(cfg: GameConfig, seed: int, uses: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {
            "index": p.index,
            "kind": p.kind,
            "x": p.x,
            "y": p.y,
            "name": POI_NAMES[p.kind],
            "used": p.key in uses,
        }
        for p in mapgen.generator(cfg, seed).pois
    ]


def waystone_list(cfg: GameConfig) -> list[dict[str, Any]]:
    return [{"index": w.index, "x": w.x, "y": w.y, "name": w.name} for w in mapgen.waystones(cfg.mapgen)]
