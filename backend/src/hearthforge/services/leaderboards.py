"""Phase 17: global leaderboards. Lifetime boards over every realm: village likes, levels, and any
user_stats counter (monsters, fish, delves, helps). The top rows are cached for a minute; your own rank
is computed fresh (one count query)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import NotFound
from hearthforge.db.models import Avatar, Realm, RealmMember, User, UserStat, Village

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _value_query(key: str) -> tuple[Any, Any]:
    """(the score column, the base select of user id + score) for a board."""
    if key == "likes":
        return Village.likes_count, select(Village.user_id, Village.likes_count.label("v"))
    if key == "level":
        score = cast(Avatar.level, BigInteger) * 1_000_000 + Avatar.xp  # level first, then XP within it
        return score, select(Avatar.user_id, score.label("v"))
    return UserStat.value, select(UserStat.user_id, UserStat.value.label("v")).where(UserStat.stat_key == key)


async def board(session: AsyncSession, cfg: GameConfig, key: str, user_id: uuid.UUID) -> dict[str, Any]:
    lb = cfg.global_.leaderboards
    meta = lb.boards.get(key)
    if meta is None:
        raise NotFound("no_board", "No such leaderboard.")
    col, base = _value_query(key)
    hit = _cache.get(key)
    if hit is None or hit[0] < time.monotonic():
        sub = base.subquery()
        rows = (
            await session.execute(
                select(sub.c[0], sub.c.v, User.username, Realm.name, Avatar.level, Avatar.title)
                .join(User, User.id == sub.c[0])
                .join(Avatar, Avatar.user_id == sub.c[0])
                .join(RealmMember, RealmMember.user_id == sub.c[0], isouter=True)
                .join(Realm, Realm.id == RealmMember.realm_id, isouter=True)
                .where(sub.c.v > 0)
                .order_by(sub.c.v.desc(), User.username)
                .limit(lb.size)
            )
        ).all()
        top = [
            {
                "rank": i + 1,
                "user_id": str(uid),
                "name": name,
                "realm": realm,
                "level": lvl,
                "title": title,
                "value": int(v // 1_000_000) if key == "level" else int(v),
            }
            for i, (uid, v, name, realm, lvl, title) in enumerate(rows)
        ]
        _cache[key] = (time.monotonic() + lb.cache, top)
    else:
        top = hit[1]
    mine_v = (await session.execute(base.where(base.selected_columns[0] == user_id))).first()
    me: dict[str, Any] | None = None
    if mine_v is not None and mine_v[1] > 0:
        sub = base.subquery()
        ahead = (
            await session.execute(select(func.count()).select_from(sub).where(sub.c.v > mine_v[1]))
        ).scalar_one()
        me = {
            "rank": int(ahead) + 1,
            "value": int(mine_v[1] // 1_000_000) if key == "level" else int(mine_v[1]),
        }
    return {"key": key, "name": meta.name, "unit": meta.unit, "rows": top, "me": me}


def boards(cfg: GameConfig) -> list[dict[str, str]]:
    return [{"key": k, "name": b.name, "unit": b.unit} for k, b in cfg.global_.leaderboards.boards.items()]


def clear_cache() -> None:
    _cache.clear()
