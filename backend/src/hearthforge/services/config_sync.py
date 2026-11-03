"""Mirror config item definitions into item_defs (never deleting; removed items become retired)."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.db.models import ConfigVersion, ItemDef


async def sync_config(session: AsyncSession, cfg: GameConfig) -> None:
    rows = [
        {
            "key": i.key,
            "category": i.category,
            "stackable": i.stackable,
            "max_stack": i.max_stack,
            "config_hash": cfg.hash,
            "retired": False,
        }
        for i in cfg.items.values()
    ]
    stmt = insert(ItemDef).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ItemDef.key],
        set_={c: stmt.excluded[c] for c in ("category", "stackable", "max_stack", "config_hash", "retired")},
    )
    await session.execute(stmt)
    await session.execute(update(ItemDef).where(ItemDef.key.not_in(list(cfg.items))).values(retired=True))
    exists = (await session.execute(select(ConfigVersion.hash).where(ConfigVersion.hash == cfg.hash))).first()
    if not exists:
        session.add(ConfigVersion(hash=cfg.hash, summary=cfg.summary()))
