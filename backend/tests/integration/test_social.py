"""Phase 15: friends, blocks, gifts through the mail (P4 gate), likes, visits and neighbour help."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from hearthforge.db.models import Avatar
from tests.conftest import signup
from tests.integration.test_crafting import give
from tests.integration.test_realms import login
from tests.integration.test_village import no_debris, set_resource


@pytest.fixture
async def pair(client: AsyncClient, st: Any) -> dict[str, Any]:
    """Ada and Bram (separate realms) become friends. The client ends logged in as Ada."""
    ada = await signup(client, "Ada")
    bram = await signup(client, "Bram")
    await no_debris(st)
    await login(client, "Ada")
    r = await client.post("/api/social/request", json={"name": "bram"})
    assert r.status_code == 200 and r.json()["result"] == "sent", r.text
    assert [f["name"] for f in r.json()["outgoing"]] == ["Bram"]
    await login(client, "Bram")
    view = (await client.get("/api/social")).json()
    assert [f["name"] for f in view["incoming"]] == ["Ada"]
    r = await client.post("/api/social/respond", json={"user_id": ada["user_id"], "accept": True})
    assert r.json()["result"] == "accepted" and [f["name"] for f in r.json()["friends"]] == ["Ada"]
    await login(client, "Ada")
    return {"ada": ada, "bram": bram}


async def level(st: Any, user_id: str, lv: int) -> None:
    async with st.sessionmaker() as s, s.begin():
        await s.execute(update(Avatar).where(Avatar.user_id == uuid.UUID(user_id)).values(level=lv))


async def test_friends_and_blocks(client: AsyncClient, pair: dict[str, Any], st: Any) -> None:
    view = (await client.get("/api/social")).json()
    assert [f["name"] for f in view["friends"]] == ["Bram"] and not view["incoming"]
    r = await client.post("/api/social/request", json={"name": "Bram"})
    assert r.json()["error"]["code"] == "already_friends"
    r = await client.post("/api/social/request", json={"name": "Nobody"})
    assert r.status_code == 404
    # blocking ends the friendship and stops requests both ways
    r = await client.post("/api/social/block", json={"user_id": pair["bram"]["user_id"]})
    assert r.status_code == 200 and not r.json()["friends"] and r.json()["blocked"][0]["name"] == "Bram"
    await login(client, "Bram")
    r = await client.post("/api/social/request", json={"name": "Ada"})
    assert r.json()["error"]["code"] == "blocked"
    r = await client.get(f"/api/social/visit/{pair['ada']['user_id']}")
    assert r.json()["error"]["code"] == "cant_visit"


async def test_gifts_need_the_gate_and_arrive_by_mail(
    client: AsyncClient, pair: dict[str, Any], st: Any, clock: Any
) -> None:
    await give(st, pair["ada"]["user_id"], {"slime_gel": 10})
    gift = {"to": pair["bram"]["user_id"], "items": {"slime_gel": 3}}
    r = await client.post("/api/social/gift", json=gift)
    assert r.json()["error"]["code"] == "too_new"  # P4: a fresh account can't send gifts
    await level(st, pair["ada"]["user_id"], st.config.social.gate.level)
    r = await client.post("/api/social/gift", json=gift)
    assert r.status_code == 200, r.text
    r = await client.post("/api/social/gift", json=gift)
    assert r.json()["error"]["code"] == "gift_today"  # one a day per friend
    await login(client, "Bram")
    mail = (await client.get("/api/social")).json()["mail"]
    assert len(mail) == 1 and mail[0]["kind"] == "gift" and mail[0]["items"] == {"slime_gel": 3}
    r = await client.post(f"/api/social/mail/{mail[0]['id']}/claim")
    assert r.status_code == 200 and r.json()["got"] == {"slime_gel": 3} and r.json()["mail"] == []
    inv = (await client.get("/api/inventory")).json()["inventory"]
    assert any(s["item"] == "slime_gel" and s["qty"] == 3 for s in inv["slots"])
    # gear can't be gifted, and big gifts are refused
    await login(client, "Ada")
    clock.advance(days=1)
    await give(st, pair["ada"]["user_id"], {"ironbark": 20})
    r = await client.post("/api/social/gift", json={"to": pair["bram"]["user_id"], "items": {"ironbark": 20}})
    assert r.json()["error"]["code"] == "gift_too_big"


async def test_visits_likes_and_help(client: AsyncClient, pair: dict[str, Any], st: Any, clock: Any) -> None:
    bram = pair["bram"]["user_id"]
    # Bram starts a long upgrade (the Town Hall to level 2)
    await login(client, "Bram")
    for k in ("wood", "stone"):
        await set_resource(st, k, 2000)
    async with st.sessionmaker() as s, s.begin():
        from hearthforge.db.models import Wallet

        await s.execute(update(Wallet).where(Wallet.user_id == uuid.UUID(bram)).values(coins=5000))
    v = (await client.get("/api/village")).json()["village"]
    th = next(b for b in v["buildings"] if b["key"] == "town_hall")
    r = await client.post(f"/api/village/buildings/{th['id']}/upgrade")
    assert r.status_code == 200, r.text
    done0 = r.json()["village"]["buildings"]
    done0 = next(b for b in done0 if b["id"] == th["id"])["completes_at_ms"]
    await login(client, "Ada")
    r = await client.get(f"/api/social/visit/{bram}")
    assert r.status_code == 200, r.text
    vis = r.json()
    assert vis["owner"]["name"] == "Bram" and not vis["liked"] and "coins" not in vis["village"]
    # a like from a brand-new account is recorded but doesn't count (P4)
    r = await client.post(f"/api/social/like/{bram}")
    assert r.json() == {"likes": 0, "counted": False}
    r = await client.post(f"/api/social/like/{bram}")
    assert r.json()["error"]["code"] == "already_liked"
    # help takes a quarter of the time left off
    r = await client.post("/api/social/help", json={"building_id": th["id"]})
    assert r.status_code == 200, r.text
    saved = r.json()["saved"]
    total = (done0 - clock.now().timestamp() * 1000) / 1000
    assert saved == pytest.approx(total * st.config.social.help.cut, abs=1.5)
    assert r.json()["completes_at_ms"] == pytest.approx(done0 - saved * 1000, abs=5)
    r = await client.post("/api/social/help", json={"building_id": th["id"]})
    assert r.json()["error"]["code"] == "helped_today"


async def test_counted_likes_after_the_gate(
    client: AsyncClient, pair: dict[str, Any], st: Any, clock: Any
) -> None:
    clock.advance(seconds=st.config.social.gate.account_age + 60)
    r = await client.post(f"/api/social/like/{pair['bram']['user_id']}")
    assert r.json() == {"likes": 1, "counted": True}
