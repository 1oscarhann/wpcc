"""Phase 7 end to end: selling, soft caps, recalc + trends, idempotency, ledger races, the merchant,
bag/bank expansion, and the admin economy view."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, insert, select, update

from hearthforge.db.models import (
    EconomySample,
    EventStatus,
    MarketPlayerDaily,
    MarketPriceHistory,
    MarketSalesBucket,
    ScheduledEvent,
    Transaction,
    User,
    UserRole,
    Wallet,
)
from hearthforge.domain import market as dom
from hearthforge.services import market as market_svc
from hearthforge.worker.poller import Worker
from tests.conftest import signup
from tests.integration.test_crafting import give
from tests.integration.test_village import get_village, no_debris, place, set_resource


@pytest.fixture
async def player(client: AsyncClient, st: Any) -> dict[str, Any]:
    data = await signup(client)
    await no_debris(st)
    return data


async def set_coins(st: Any, coins: int) -> None:
    async with st.sessionmaker() as s, s.begin():
        await s.execute(update(Wallet).values(coins=coins))


async def coins(st: Any) -> int:
    async with st.sessionmaker() as s:
        return int((await s.execute(select(Wallet.coins))).scalar_one())


async def build_market(client: AsyncClient, clock: Any) -> None:
    r = await place(client, "market", 26, 12)
    assert r.status_code == 200, r.text
    clock.advance(11)
    await get_village(client)


async def sell(client: AsyncClient, item: str, qty: int, key: str | None = None) -> Any:
    headers = {"idempotency-key": key} if key else {}
    return await client.post("/api/market/sell", json={"item": item, "quantity": qty}, headers=headers)


async def test_sell_resources_and_items(
    client: AsyncClient, player: dict[str, Any], st: Any, clock: Any
) -> None:
    r = await sell(client, "wood", 10)
    assert r.status_code == 400 and r.json()["error"]["code"] == "needs_market"
    await build_market(client, clock)
    m = (await client.get("/api/market")).json()
    assert m["has_market"] and m["market_level"] == 1 and m["bonus"] == 0
    wood = next(i for i in m["items"] if i["key"] == "wood")
    assert wood["source"] == "storage" and wood["have"] == 180  # 300 − 120 for the market
    assert wood["price"] == pytest.approx(2 * 1.822, abs=0.01)  # nothing sold yet → ×1.82

    before = await coins(st)
    r = await sell(client, "wood", 50)
    assert r.status_code == 200, r.text
    sale = r.json()["sale"]
    assert sale["coins"] == int(wood["price"] * 50) and sale["over_cap_units"] == 0
    assert r.json()["village"]["resources"]["wood"]["amount"] == 130
    assert await coins(st) == before + sale["coins"] == sale["balance"]

    async with st.sessionmaker() as s:
        tx = (await s.execute(select(Transaction).where(Transaction.reason == "market.sell"))).scalars().all()
        assert {(t.asset.value, t.delta) for t in tx} == {("resource", -50_000), ("coin", sale["coins"])}
        assert (await s.execute(select(MarketSalesBucket.units))).scalar_one() == 50
        assert (await s.execute(select(MarketPlayerDaily.units))).scalar_one() == 50

    # bag materials: inventory first, then the bank
    await give(st, player["user_id"], {"slime_gel": 5})
    r = await sell(client, "slime_gel", 5)
    assert r.status_code == 200, r.text
    assert "inventory" in r.json() and not any(
        s["item"] == "slime_gel" for s in r.json()["inventory"]["inventory"]["slots"]
    )
    r = await sell(client, "slime_gel", 1)
    assert r.json()["error"]["code"] == "insufficient_items"
    r = await sell(client, "spear", 1)
    assert r.json()["error"]["code"] == "not_sellable"


async def test_soft_cap_halves_your_price(
    client: AsyncClient, player: dict[str, Any], st: Any, clock: Any
) -> None:
    await build_market(client, clock)
    await give(st, player["user_id"], {"ironbark": 60})
    r = await sell(client, "ironbark", 50)
    assert r.status_code == 200, r.text
    sale = r.json()["sale"]
    cap = st.config.market.items["ironbark"].soft_cap
    assert sale["over_cap_units"] == 50 - cap and sale["sold_today"] == 50
    unit = dom.price(st.config.market, "ironbark", 0, 1)[0]
    assert sale["coins"] == dom.payout(unit, 0.0, 50, 0, cap, 0.5).coins
    m = (await client.get("/api/market")).json()
    ib = next(i for i in m["items"] if i["key"] == "ironbark")
    assert (
        ib["sold_today"] == 50
        and ib["soft_cap"] == cap
        and ib["over_price"] == pytest.approx(ib["price"] / 2)
    )
    clock.advance(86_400)  # a new UTC day resets the cap
    r = await sell(client, "ironbark", 10)
    assert r.json()["sale"]["over_cap_units"] == 0


async def test_recalc_reprices_and_trends(
    client: AsyncClient, player: dict[str, Any], st: Any, clock: Any
) -> None:
    await build_market(client, clock)
    async with st.sessionmaker() as s, s.begin():
        await market_svc.ensure_started(s, st.config, clock.now())
    first = (await client.get("/api/market")).json()
    wood0 = next(i for i in first["items"] if i["key"] == "wood")["raw_price"]

    # the whole realm dumps 2× the baseline of wood in the next ten minutes
    bucket = dom.bucket_start(clock.now(), st.config.market.recalc_interval)
    async with st.sessionmaker() as s, s.begin():
        await s.execute(insert(MarketSalesBucket).values(item_key="wood", bucket_start=bucket, units=16_000))
    clock.advance(st.config.market.recalc_interval + 1)
    assert await Worker(st).drain() >= 1  # the scheduled recalc ran and booked the next one
    async with st.sessionmaker() as s:
        pending = (
            await s.execute(
                select(func.count())
                .select_from(ScheduledEvent)
                .where(ScheduledEvent.kind == "market.recalc", ScheduledEvent.status == EventStatus.pending)
            )
        ).scalar_one()
        assert pending == 1
        assert (
            await s.execute(select(func.count()).select_from(MarketPriceHistory))
        ).scalar_one() >= 2 * len(st.config.market.items)
    m = (await client.get("/api/market")).json()
    wood = next(i for i in m["items"] if i["key"] == "wood")
    assert wood["raw_price"] == pytest.approx(2 * 0.549, abs=0.01) and wood["raw_price"] < wood0
    assert wood["trend"] == -1 and wood["change"] < -0.5 and wood["units_24h"] == 16_000
    assert len(wood["spark"]) == st.config.market.sparkline.points and wood["spark"][-1] == wood["raw_price"]
    stone = next(i for i in m["items"] if i["key"] == "stone")
    assert stone["trend"] == 0

    # 24 h later those sales have left the window and the price recovers
    clock.advance(86_400)
    async with st.sessionmaker() as s, s.begin():
        await market_svc.recalc(s, st.config, clock.now())
    m = (await client.get("/api/market")).json()
    assert next(i for i in m["items"] if i["key"] == "wood")["raw_price"] == pytest.approx(wood0)


async def test_idempotent_replay(client: AsyncClient, player: dict[str, Any], st: Any, clock: Any) -> None:
    await build_market(client, clock)
    key = str(uuid.uuid4())
    a = await sell(client, "wood", 20, key)
    b = await sell(client, "wood", 20, key)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert (await get_village(client))["resources"]["wood"]["amount"] == 160  # sold once
    c = await sell(client, "wood", 21, key)
    assert c.status_code == 422 and c.json()["error"]["code"] == "idempotency_mismatch"
    r = await client.post(
        "/api/market/sell", json={"item": "wood", "quantity": 1}, headers={"idempotency-key": "nope"}
    )
    assert r.json()["error"]["code"] == "idempotency_key_invalid"
    # a failed request doesn't burn its key
    key2 = str(uuid.uuid4())
    assert (await sell(client, "wood", 9999, key2)).status_code == 400
    assert (await sell(client, "wood", 10, key2)).status_code == 200  # the key is still free
    assert (await sell(client, "wood", 9999, key2)).json()["error"]["code"] == "idempotency_mismatch"


async def test_ledger_races(client: AsyncClient, player: dict[str, Any], st: Any, clock: Any) -> None:
    """Concurrent requests on one wallet/storehouse: no double spend, no overdraw, books balance."""
    await build_market(client, clock)
    # 1) ten parallel sells of 50 wood with 180 in storage → exactly three go through
    rs = await asyncio.gather(*(sell(client, "wood", 50) for _ in range(10)))
    ok = [r for r in rs if r.status_code == 200]
    assert len(ok) == 3 and all(
        r.json()["error"]["code"] == "insufficient_resources" for r in rs if r not in ok
    )
    assert (await get_village(client))["resources"]["wood"]["amount"] == 30
    earned = sum(r.json()["sale"]["coins"] for r in ok)
    async with st.sessionmaker() as s:
        assert (await s.execute(select(MarketSalesBucket.units))).scalar_one() == 150
        logged = (
            await s.execute(
                select(func.sum(Transaction.delta)).where(
                    Transaction.reason == "market.sell", Transaction.asset == "coin"
                )
            )
        ).scalar_one()
        assert logged == earned

    # 2) the same idempotency key fired five times at once → one effect, five identical answers
    key = str(uuid.uuid4())
    await set_resource(st, "stone", 100)
    rs = await asyncio.gather(*(sell(client, "stone", 40, key) for _ in range(5)))
    assert {r.status_code for r in rs} == {200}
    assert len({json.dumps(r.json(), sort_keys=True) for r in rs}) == 1
    assert (await get_village(client))["resources"]["stone"]["amount"] == 60

    # 3) parallel spends with coins for exactly one → one expansion, wallet never negative
    await set_coins(st, 300)
    rs = await asyncio.gather(
        *(client.post("/api/inventory/expand", json={"kind": "inventory"}) for _ in range(6))
    )
    assert sorted(r.status_code for r in rs) == [200] + [400] * 5
    assert await coins(st) == 0
    inv = (await client.get("/api/inventory")).json()["inventory"]
    assert inv["capacity"] == 30


async def test_expand_bag_and_bank(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    await set_coins(st, 100_000)
    caps = []
    for _ in range(4):
        r = await client.post("/api/inventory/expand", json={"kind": "inventory"})
        assert r.status_code == 200, r.text
        caps.append(r.json()["capacity"])
    assert caps == [30, 36, 42, 48]
    r = await client.post("/api/inventory/expand", json={"kind": "inventory"})
    assert r.json()["error"]["code"] == "max_size"
    r = await client.post("/api/inventory/expand", json={"kind": "bank"})
    assert r.json()["capacity"] == 80 and r.json()["paid"] == 400
    inv = r.json()["inventory"]
    assert inv["bank"]["expand"]["next_cost"] == 900 and inv["inventory"]["expand"]["next_cost"] is None
    assert await coins(st) == 100_000 - (300 + 800 + 1800 + 3500) - 400
    async with st.sessionmaker() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(Transaction).where(Transaction.reason == "container.expand")
            )
        ).scalar_one()
        assert n == 5
    await set_coins(st, 10)
    r = await client.post("/api/inventory/expand", json={"kind": "bank"})
    assert r.json()["error"]["code"] == "insufficient_coins"


def fake_room(st: Any, monkeypatch: pytest.MonkeyPatch, realm_id: str, x: float, y: float) -> None:
    """Pretend the player stands at (x, y) in Avatar Mode without running a socket."""
    player = SimpleNamespace(m=SimpleNamespace(x=x, y=y))
    monkeypatch.setattr(st.rooms, "find", lambda uid: (SimpleNamespace(realm_id=uuid.UUID(realm_id)), player))

    async def noop(uid: Any) -> None:
        return None

    monkeypatch.setattr(st.rooms, "reload_loadout", noop)


async def test_bank_only_at_home(
    client: AsyncClient, player: dict[str, Any], st: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    move = {"src": {"kind": "inventory", "slot": 0}, "dst": {"kind": "bank", "slot": 3}}
    r = await client.post("/api/inventory/move", json=move)
    assert r.status_code == 200, r.text
    assert r.json()["bank"]["slots"][0]["item"] == "training_spear" and r.json()["inventory"]["slots"] == []
    realm = (await client.get("/api/realm/map")).json()["realm_id"]
    fake_room(st, monkeypatch, realm, 0, 0)
    back = {"src": {"kind": "bank", "slot": 3}, "dst": {"kind": "inventory", "slot": 0}}
    r = await client.post("/api/inventory/move", json=back)
    assert r.json()["error"]["code"] == "bank_far"


async def test_merchant(
    client: AsyncClient, player: dict[str, Any], st: Any, clock: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = (await client.get("/api/merchant/hub")).json()
    assert view["name"] and len(view["slots"]) == st.config.merchant.slots and view["near"] is False
    realm = (await client.get("/api/realm/map")).json()["realm_id"]
    assert view["merchant_id"] == f"hub:{realm}"
    assert (await client.get("/api/merchant/hub:someone-else")).status_code == 404
    assert sum(s["deal"] for s in view["slots"]) == 1

    buy = {"slot": 0, "rotation": view["rotation"]}
    r = await client.post("/api/merchant/hub/buy", json=buy)
    assert r.json()["error"]["code"] == "too_far"

    # walk up to the cart (faked) with plenty of coins
    fake_room(st, monkeypatch, realm, view["pos"][0] + 1, view["pos"][1])
    await set_coins(st, 50_000)
    view = (await client.get("/api/merchant/hub")).json()
    assert view["near"] is True
    for sl in view["slots"]:
        before = await coins(st)
        r = await client.post(
            "/api/merchant/hub/buy", json={"slot": sl["slot"], "rotation": view["rotation"]}
        )
        if sl["sold_out"]:
            assert r.status_code == 400
            continue
        assert r.status_code == 200, (sl, r.text)
        got = r.json()["purchase"]["got"]
        assert await coins(st) == before - sl["price"]
        if sl["kind"] == "item":
            assert got == {"item": sl["item"], "qty": sl["qty"]}
            assert any(s["item"] == sl["item"] for s in r.json()["inventory"]["inventory"]["slots"])
        elif sl["kind"] == "resource":
            assert got == {"resource": sl["item"], "qty": sl["qty"]}
        else:
            book = (await client.get("/api/crafting/book")).json()
            revealed = [c for c in book["combos"] if c.get("revealed")]
            assert len(revealed) == 1 and revealed[0]["revealed"] == got["hint"]
    # limits are per player and per rotation
    lim = next(s for s in view["slots"] if s["kind"] != "hint")
    for _ in range(lim["limit"]):
        await client.post("/api/merchant/hub/buy", json={"slot": lim["slot"], "rotation": view["rotation"]})
    r = await client.post("/api/merchant/hub/buy", json={"slot": lim["slot"], "rotation": view["rotation"]})
    assert r.json()["error"]["code"] in ("sold_out", "storage_full")
    # a stale page after she moves on doesn't buy the wrong thing
    clock.advance(st.config.merchant.rotation)
    r = await client.post("/api/merchant/hub/buy", json={"slot": 0, "rotation": view["rotation"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "merchant_moved_on"
    nxt = (await client.get("/api/merchant/hub")).json()
    assert nxt["rotation"] == view["rotation"] + 1 and nxt["pos"] != view["pos"]
    assert all(s["bought"] == 0 for s in nxt["slots"])


async def test_merchant_checks_coins_and_space(
    client: AsyncClient, player: dict[str, Any], st: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    realm = (await client.get("/api/realm/map")).json()["realm_id"]
    view = (await client.get("/api/merchant/hub")).json()
    fake_room(st, monkeypatch, realm, *view["pos"])
    await set_coins(st, 0)
    r = await client.post("/api/merchant/hub/buy", json={"slot": 0, "rotation": view["rotation"]})
    assert r.json()["error"]["code"] == "insufficient_coins"
    assert all(s["bought"] == 0 for s in (await client.get("/api/merchant/hub")).json()["slots"])


async def test_admin_economy(client: AsyncClient, player: dict[str, Any], st: Any, clock: Any) -> None:
    r = await client.get("/api/admin/economy")
    assert r.status_code == 403
    async with st.sessionmaker() as s, s.begin():
        await s.execute(update(User).values(role=UserRole.admin))
    await build_market(client, clock)
    earned = (await sell(client, "wood", 100)).json()["sale"]["coins"]
    await set_coins(st, 1000)
    await client.post("/api/inventory/expand", json={"kind": "inventory"})
    async with st.sessionmaker() as s, s.begin():
        await market_svc.recalc(s, st.config, clock.now())
    rep = (await client.get("/api/admin/economy")).json()
    assert rep["coin_supply"] == 700 and rep["wallets"] == 1
    assert rep["day"]["faucets"]["market.sell"] == earned
    assert rep["day"]["sinks"]["container.expand"] == 300
    assert rep["series"] and rep["series"][-1]["supply"] == 700
    async with st.sessionmaker() as s:
        sample = (await s.execute(select(EconomySample))).scalar_one()
        assert sample.faucet >= earned and sample.sink >= 300
