"""Phase 17: festivals. Each runs between two dates every year (MM-DD, UTC, may wrap the new year).
While one runs, monsters drop its token and its shop takes them (titles, tokens, food, potions)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.config.schemas import FestivalCfg
from hearthforge.core.errors import GameError, NotFound
from hearthforge.db.models import UserCosmetic
from hearthforge.services import inventory, social, stats

BUY = "festival.buy"


def _window(fe: FestivalCfg, year: int) -> tuple[datetime, datetime]:
    sm, sd = (int(x) for x in fe.start.split("-"))
    em, ed = (int(x) for x in fe.end.split("-"))
    start = datetime(year, sm, sd, tzinfo=UTC)
    end = datetime(year + (1 if (em, ed) < (sm, sd) else 0), em, ed, tzinfo=UTC) + timedelta(days=1)
    return start, end


def active(cfg: GameConfig, now: datetime) -> tuple[str, FestivalCfg, datetime, datetime] | None:
    for key, fe in cfg.global_.festivals.items():
        for year in (now.year - 1, now.year):
            start, end = _window(fe, year)
            if start <= now < end:
                return key, fe, start, end
    return None


def upcoming(cfg: GameConfig, now: datetime) -> tuple[str, FestivalCfg, datetime] | None:
    best: tuple[str, FestivalCfg, datetime] | None = None
    for key, fe in cfg.global_.festivals.items():
        for year in (now.year, now.year + 1):
            start, _ = _window(fe, year)
            if start > now and (best is None or start < best[2]):
                best = (key, fe, start)
    return best


async def _token_count(session: AsyncSession, user_id: uuid.UUID, token: str) -> int:
    b = await inventory.bags(session, user_id, ("inventory", "bank"), lock=False)
    return sum(s.quantity for bag in b.values() for s in bag.slots.values() if s.item_key == token)


async def view(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    act = active(cfg, now)
    nxt = upcoming(cfg, now)
    out: dict[str, Any] = {"active": None, "next": None}
    if nxt is not None:
        out["next"] = {"key": nxt[0], "name": nxt[1].name, "starts_ms": int(nxt[2].timestamp() * 1000)}
    if act is None:
        return out
    key, fe, start, end = act
    titles = {
        k.removeprefix("title:")
        for k in (
            await session.execute(select(UserCosmetic.cosmetic_key).where(UserCosmetic.user_id == user_id))
        ).scalars()
    }
    out["active"] = {
        "key": key,
        "name": fe.name,
        "desc": fe.desc,
        "color": fe.color,
        "token": fe.token,
        "token_name": cfg.items[fe.token].name,
        "have": await _token_count(session, user_id, fe.token),
        "starts_ms": int(start.timestamp() * 1000),
        "ends_ms": int(end.timestamp() * 1000),
        "drop_chance": fe.drop_chance,
        "shop": [
            {
                "index": i,
                "item": e.item,
                "name": cfg.items[e.item].name if e.item else f"Title: “{e.title}”",
                "title": e.title,
                "qty": e.qty,
                "cost": e.cost,
                "owned": e.title is not None and e.title in titles,
            }
            for i, e in enumerate(fe.shop)
        ],
    }
    return out


async def buy(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, index: int, now: datetime
) -> dict[str, Any]:
    act = active(cfg, now)
    if act is None:
        raise GameError("no_festival", "There's no festival on right now.")
    _, fe, _, _ = act
    if not 0 <= index < len(fe.shop):
        raise NotFound("no_entry", "That isn't in the shop.")
    e = fe.shop[index]
    if e.title is not None and await session.get(UserCosmetic, (user_id, f"title:{e.title}")) is not None:
        raise GameError("owned", "You already have that title.")
    b = await inventory.bags(session, user_id, ("inventory", "bank"))
    have = sum(s.quantity for bag in b.values() for s in bag.slots.values() if s.item_key == fe.token)
    if have < e.cost:
        raise GameError("no_tokens", f"You need {e.cost} {cfg.items[fe.token].name}s (you have {have}).")
    left = e.cost
    for kind in ("inventory", "bank"):
        if left and kind in b:
            left -= await inventory.take_stack(session, b[kind], fe.token, left)
    if e.title is not None:
        session.add(
            UserCosmetic(user_id=user_id, cosmetic_key=f"title:{e.title}", source=f"festival:{fe.name}")
        )
    else:
        assert e.item is not None
        rest = await inventory.grant(session, cfg, user_id, {e.item: e.qty}, BUY)
        if rest:
            social.send_mail(session, user_id, "system", fe.name, rest, note="Your bag was full")
    await stats.bump(session, user_id, {"festival.bought": 1})
    return {"item": e.item, "qty": e.qty, "title": e.title}
