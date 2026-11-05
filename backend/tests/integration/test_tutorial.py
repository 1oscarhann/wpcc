"""Phase 8: the server-checked tutorial, its rewards, skipping, and the 'While you were away' card."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from hearthforge.db.models import Transaction
from hearthforge.services import away, stats
from tests.conftest import signup
from tests.integration.test_village import get_village, no_debris, place


@pytest.fixture
async def player(client: AsyncClient, st: Any) -> dict[str, Any]:
    data = await signup(client)
    await no_debris(st)
    return data


async def check(client: AsyncClient, confirm: str | None = None) -> dict[str, Any]:
    r = await client.post("/api/tutorial/check", json={"confirm": confirm})
    assert r.status_code == 200, r.text
    return r.json()


async def bump(st: Any, user_id: str, counts: dict[str, int]) -> None:
    async with st.sessionmaker() as s, s.begin():
        await stats.bump(s, uuid.UUID(user_id), counts)


async def test_tutorial_walkthrough(client: AsyncClient, player: dict[str, Any], st: Any, clock: Any) -> None:
    t = (await client.get("/api/tutorial")).json()
    assert t["active"] and t["index"] == 0 and t["step"]["key"] == "welcome"
    assert t["guide"]["name"] == "Juniper" and len(t["steps"]) == t["total"]

    # nothing happens until the button is pressed, and the wrong key does nothing either
    assert (await check(client))["tutorial"]["index"] == 0
    assert (await check(client, "production"))["tutorial"]["index"] == 0
    out = await check(client, "welcome")
    assert out["tutorial"]["step"]["key"] == "production" and out["completed"][0]["key"] == "welcome"
    assert out["tutorial"]["step"]["progress"] == [0, 2]

    stone0 = (await get_village(client))["resources"]["stone"]["amount"]
    assert (await place(client, "lumber_camp", 27, 20)).status_code == 200
    assert (await check(client))["tutorial"]["step"]["progress"] == [1, 2]
    assert (await place(client, "quarry", 27, 24)).status_code == 200  # constructing still counts
    out = await check(client)
    assert out["tutorial"]["step"]["key"] == "chop" and out["completed"][0]["reward"] == {"stone": 60}
    assert out["village"]["resources"]["stone"]["amount"] == stone0 - 20 + 60
    async with st.sessionmaker() as s:
        rows = (
            (await s.execute(select(Transaction).where(Transaction.reason == "tutorial.reward")))
            .scalars()
            .all()
        )
        assert [(r.item_key, r.delta) for r in rows] == [("stone", 60_000)]

    # counters drive the next steps; several met goals complete in one check
    await bump(st, player["user_id"], {"gather.wood": 5})
    assert (await check(client))["tutorial"]["step"]["progress"] == [5, 8]
    await bump(st, player["user_id"], {"gather.wood": 3, "kill.slime": 2})
    out = await check(client)
    assert [c["key"] for c in out["completed"]] == ["chop", "slimes"]
    assert out["tutorial"]["step"]["key"] == "market"
    assert out["village"]["coins"] == 200 + 50

    # skipping ends it for good
    r = await client.post("/api/tutorial/skip")
    assert r.json()["tutorial"]["active"] is False
    assert (await client.post("/api/tutorial/skip")).json()["error"]["code"] == "tutorial_over"
    assert (await client.get("/api/tutorial")).json()["active"] is False


async def test_counters_from_services(
    client: AsyncClient, player: dict[str, Any], st: Any, clock: Any
) -> None:
    assert (await place(client, "market", 26, 12)).status_code == 200
    clock.advance(11)
    await get_village(client)
    r = await client.post("/api/market/sell", json={"item": "wood", "quantity": 10})
    assert r.status_code == 200, r.text
    async with st.sessionmaker() as s:
        got = await stats.read(s, uuid.UUID(player["user_id"]))
    assert got["sell.any"] == 10 and got["sell.wood"] == 10 and got["sell.coins"] == r.json()["sale"]["coins"]


async def test_away_summary(client: AsyncClient, player: dict[str, Any], st: Any, clock: Any) -> None:
    assert (await client.get("/api/away-summary")).json()["show"] is False  # never left yet
    assert (await place(client, "lumber_camp", 27, 20)).status_code == 200
    uid = uuid.UUID(player["user_id"])
    async with st.sessionmaker() as s, s.begin():
        await away.snapshot(s, st.config, uid, clock.now())  # what the gateway does on the last disconnect
    clock.advance(300)
    assert (await client.get("/api/away-summary")).json()["show"] is False  # a short break: no card
    clock.advance(2 * 3600)
    card = (await client.get("/api/away-summary")).json()
    assert card["show"] and card["away_s"] == 2 * 3600 + 300
    assert {"key": "lumber_camp", "level": 1} in card["finished"]
    assert card["gained"]["wood"] >= 100  # a level 1 camp makes 60/h
    assert card["quip"] and card["guide"]["name"] == "Juniper"
    assert (await client.post("/api/away-summary/ack")).status_code == 200
    assert (await client.get("/api/away-summary")).json()["show"] is False
