"""Phase 17: the player market (escrow, fee, partial buys, cancel, expiry, races), leaderboards,
festivals and the world boss's shared HP pool."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from hearthforge.core.errors import GameError
from hearthforge.db.models import Listing, Mail, UserCosmetic, Wallet, WorldBossEvent
from hearthforge.services import festivals, leaderboards, pmarket, stats, worldboss
from tests.conftest import signup
from tests.integration.test_crafting import give
from tests.integration.test_journal import coins
from tests.integration.test_realms import login
from tests.integration.test_social import level


def idem() -> dict[str, str]:
    return {"idempotency-key": str(uuid.uuid4())}


async def bag_count(client: AsyncClient, item: str) -> int:
    inv = (await client.get("/api/inventory")).json()["inventory"]
    return sum(s["qty"] for s in inv["slots"] if s["item"] == item)


async def set_coins(st: Any, user_id: str, n: int) -> None:
    async with st.sessionmaker() as s, s.begin():
        await s.execute(update(Wallet).where(Wallet.user_id == uuid.UUID(user_id)).values(coins=n))


@pytest.fixture
async def traders(client: AsyncClient, st: Any) -> dict[str, Any]:
    ada = await signup(client, "Ada")
    bram = await signup(client, "Bram")
    for who in (ada, bram):
        await level(st, who["user_id"], 6)
    await give(st, ada["user_id"], {"slime_gel": 20})
    await set_coins(st, bram["user_id"], 1000)
    await login(client, "Ada")
    return {"ada": ada, "bram": bram}


async def test_list_buy_and_cancel(client: AsyncClient, traders: dict[str, Any], st: Any) -> None:
    ada, bram = traders["ada"], traders["bram"]
    lo, hi = pmarket.band(st.config, "slime_gel")
    r = await client.post(
        "/api/pmarket/listings",
        json={"item": "slime_gel", "quantity": 10, "unit_price": hi + 1},
        headers=idem(),
    )
    assert r.json()["error"]["code"] == "bad_price"
    r = await client.post(
        "/api/pmarket/listings",
        json={"item": "training_sword", "quantity": 1, "unit_price": 5},
        headers=idem(),
    )
    assert r.json()["error"]["code"] == "not_tradeable"
    price = max(lo, 3)
    r = await client.post(
        "/api/pmarket/listings",
        json={"item": "slime_gel", "quantity": 10, "unit_price": price},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    listing = r.json()["listing"]
    assert await bag_count(client, "slime_gel") == 10  # ten went into escrow
    view = (await client.get("/api/pmarket")).json()
    assert view["items"][0]["item"] == "slime_gel" and view["items"][0]["quantity"] == 10
    r = await client.post(f"/api/pmarket/listings/{listing}/buy", json={"quantity": 1}, headers=idem())
    assert r.json()["error"]["code"] == "own_listing"
    # Bram buys four
    ada_before = await coins(st, ada["user_id"])
    await login(client, "Bram")
    key = idem()
    r = await client.post(f"/api/pmarket/listings/{listing}/buy", json={"quantity": 4}, headers=key)
    assert r.status_code == 200, r.text
    cost, fee = 4 * price, r.json()["fee"]
    assert fee == max(1, int(cost * st.config.global_.pmarket.fee))
    again = await client.post(f"/api/pmarket/listings/{listing}/buy", json={"quantity": 4}, headers=key)
    assert again.json() == r.json()  # a retried request doesn't buy twice
    assert await coins(st, bram["user_id"]) == 1000 - cost
    assert await coins(st, ada["user_id"]) == ada_before + cost - fee  # the fee is a sink
    assert await bag_count(client, "slime_gel") == 4
    item = (await client.get("/api/pmarket/item/slime_gel")).json()
    assert item["listings"][0]["quantity"] == 6 and item["recent"][0]["qty"] == 4
    # Ada takes the rest down: it comes back by mail
    await login(client, "Ada")
    r = await client.post(f"/api/pmarket/listings/{listing}/cancel")
    assert r.status_code == 200
    mail = (await client.get("/api/social")).json()["mail"]
    assert any(m["items"] == {"slime_gel": 6} for m in mail)


async def test_gate_limits_and_expiry(
    client: AsyncClient, traders: dict[str, Any], st: Any, clock: Any
) -> None:
    ada = traders["ada"]
    await level(st, ada["user_id"], 1)  # back under the P4 gate (and the account is brand new)
    r = await client.post(
        "/api/pmarket/listings", json={"item": "slime_gel", "quantity": 2, "unit_price": 3}, headers=idem()
    )
    assert r.json()["error"]["code"] == "too_new"
    await level(st, ada["user_id"], 6)
    r = await client.post(
        "/api/pmarket/listings", json={"item": "slime_gel", "quantity": 99, "unit_price": 3}, headers=idem()
    )
    assert r.json()["error"]["code"] == "not_enough"
    r = await client.post(
        "/api/pmarket/listings", json={"item": "slime_gel", "quantity": 5, "unit_price": 3}, headers=idem()
    )
    assert r.status_code == 200
    clock.advance(hours=st.config.global_.pmarket.listing_hours + 1)
    async with st.sessionmaker() as s, s.begin():
        assert await pmarket.expire_due(s, st.config, clock.now()) == 1
    async with st.sessionmaker() as s:
        ls = (await s.execute(select(Listing))).scalar_one()
        mail = (
            (await s.execute(select(Mail).where(Mail.user_id == uuid.UUID(ada["user_id"])))).scalars().all()
        )
    assert ls.status == "expired" and ls.quantity == 0 and any(m.items == {"slime_gel": 5} for m in mail)


async def test_two_buyers_race_for_the_last_ones(
    client: AsyncClient, traders: dict[str, Any], st: Any
) -> None:
    """Both try to buy 3 of the last 3 at the same moment: exactly one gets them; no coins are lost."""
    bram = traders["bram"]
    cara = await signup(client, "Cara")
    await set_coins(st, cara["user_id"], 1000)
    await login(client, "Ada")
    r = await client.post(
        "/api/pmarket/listings", json={"item": "slime_gel", "quantity": 3, "unit_price": 4}, headers=idem()
    )
    listing = uuid.UUID(r.json()["listing"])
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    async def attempt(uid: str) -> str:
        try:
            async with st.sessionmaker() as s, s.begin():
                await pmarket.buy(s, st.config, uuid.UUID(uid), listing, 3, now)
            return "ok"
        except GameError as e:
            return e.code

    results = await asyncio.gather(attempt(bram["user_id"]), attempt(cara["user_id"]))
    assert sorted(results) == ["bad_quantity", "ok"] or sorted(results) == ["closed", "ok"]
    spent = (1000 - await coins(st, bram["user_id"])) + (1000 - await coins(st, cara["user_id"]))
    assert spent == 12


async def test_leaderboards(client: AsyncClient, traders: dict[str, Any], st: Any) -> None:
    ada, bram = traders["ada"], traders["bram"]
    async with st.sessionmaker() as s, s.begin():
        await stats.bump(s, uuid.UUID(ada["user_id"]), {"fish.any": 7})
        await stats.bump(s, uuid.UUID(bram["user_id"]), {"fish.any": 12})
    leaderboards.clear_cache()
    b = (await client.get("/api/leaderboards/fish.any")).json()
    assert [r["name"] for r in b["rows"]] == ["Bram", "Ada"] and b["me"] == {"rank": 2, "value": 7}
    assert (await client.get("/api/leaderboards/nope")).status_code == 404
    lv = (await client.get("/api/leaderboards/level")).json()
    assert lv["rows"][0]["value"] == 6


async def test_festival_shop(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    f = (await client.get("/api/festival")).json()["active"]  # the test clock is 1 January
    assert f["key"] == "winter_hearth" and f["have"] == 0
    title = next(e for e in f["shop"] if e["title"])
    r = await client.post("/api/festival/buy", json={"index": title["index"]}, headers=idem())
    assert r.json()["error"]["code"] == "no_tokens"
    await give(st, player["user_id"], {f["token"]: title["cost"] + 5})
    r = await client.post("/api/festival/buy", json={"index": title["index"]}, headers=idem())
    assert r.status_code == 200, r.text
    f = (await client.get("/api/festival")).json()["active"]
    assert f["have"] == 5 and next(e for e in f["shop"] if e["title"])["owned"]
    r = await client.post("/api/festival/buy", json={"index": title["index"]}, headers=idem())
    assert r.json()["error"]["code"] == "owned"


def test_festival_and_weekend_windows(game_config: Any) -> None:
    cfg = game_config
    assert festivals.active(cfg, datetime(2026, 11, 8, tzinfo=UTC))[0] == "harvest_moon"
    assert festivals.active(cfg, datetime(2027, 1, 5, 23, tzinfo=UTC))[0] == "winter_hearth"  # wraps the year
    assert festivals.active(cfg, datetime(2026, 8, 1, tzinfo=UTC)) is None
    assert festivals.upcoming(cfg, datetime(2026, 8, 1, tzinfo=UTC))[0] == "harvest_moon"
    sat = datetime(2026, 11, 7, 9, tzinfo=UTC)  # a Saturday
    assert worldboss.window_start(cfg, sat) == datetime(2026, 11, 7, tzinfo=UTC)
    assert worldboss.window_start(cfg, sat + timedelta(days=1, hours=14)) == datetime(2026, 11, 7, tzinfo=UTC)
    assert worldboss.window_start(cfg, datetime(2026, 11, 10, tzinfo=UTC)) is None


async def test_world_boss_pool_and_rewards(
    client: AsyncClient, traders: dict[str, Any], st: Any, clock: Any
) -> None:
    ada, bram = traders["ada"], traders["bram"]
    now = clock.now()
    async with st.sessionmaker() as s, s.begin():
        ev = await worldboss.start_now(s, st.config, now, hours=2, hp=30_000)
    r1, r2 = uuid.uuid4(), uuid.uuid4()  # two realms chipping at one pool
    async with st.sessionmaker() as s, s.begin():
        hp, status = await worldboss.apply_damage(s, ev.id, r1, {ada["user_id"]: 26_000}, now)
    assert (hp, status) == (4_000, "active")
    async with st.sessionmaker() as s, s.begin():
        hp, status = await worldboss.apply_damage(s, ev.id, r2, {bram["user_id"]: 6_000}, now)
    assert (hp, status) == (0, "defeated")  # never below zero
    async with st.sessionmaker() as s, s.begin():
        hp, status = await worldboss.apply_damage(s, ev.id, r2, {bram["user_id"]: 100}, now)
    assert status == "defeated"
    view = (await client.get("/api/worldboss")).json()["event"]
    assert view["status"] == "defeated" and view["me"]["tier"] == 3  # Ada: 26,000 reaches three tiers
    async with st.sessionmaker() as s, s.begin():
        assert await worldboss.finish_due(s, st.config, now) == [ev.id]
    async with st.sessionmaker() as s:
        mail = {m.user_id: m for m in (await s.execute(select(Mail).where(Mail.kind == "boss"))).scalars()}
        titled = (
            (
                await s.execute(
                    select(UserCosmetic.user_id).where(UserCosmetic.cosmetic_key == "title:Worldbreaker")
                )
            )
            .scalars()
            .all()
        )
        assert (await s.get(WorldBossEvent, ev.id)).rewarded
    wb = st.config.global_.world_boss
    want = round(sum(t.coins for t in wb.tiers[:3]) * wb.defeat_bonus)
    assert mail[uuid.UUID(ada["user_id"])].coins == want
    assert mail[uuid.UUID(bram["user_id"])].coins == round(
        sum(t.coins for t in wb.tiers[:2]) * wb.defeat_bonus
    )
    assert len(titled) == 2  # both realms are in the top ten
    async with st.sessionmaker() as s, s.begin():
        assert await worldboss.finish_due(s, st.config, now) == []  # paid once
