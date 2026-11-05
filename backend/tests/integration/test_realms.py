"""Phase 9: found/join/leave/kick/transfer with village relocation, the stash's trust rules (P3),
the activity feed, mates' villages and the map overview."""

from __future__ import annotations

import base64
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from hearthforge.db.models import Realm, RealmMember, Village
from hearthforge.services import inventory
from tests.conftest import signup
from tests.integration.test_village import no_debris


async def login(client: AsyncClient, name: str, password: str = "correct horse") -> None:
    r = await client.post("/api/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    client.headers["x-csrf-token"] = r.json()["csrf_token"]


async def realm(client: AsyncClient) -> dict[str, Any]:
    r = await client.get("/api/realm")
    assert r.status_code == 200, r.text
    return r.json()["realm"]


@pytest.fixture
async def duo(client: AsyncClient, st: Any) -> dict[str, Any]:
    """Ada founds a realm; Bram joins it with the code. The client ends logged in as Ada."""
    ada = await signup(client, "Ada")
    r = await client.post("/api/realms", json={"name": "Hearth Hollow"})
    assert r.status_code == 200, r.text
    code = r.json()["realm"]["invite_code"]
    assert len(code) == 6 and all(c in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" for c in code)
    bo = await signup(client, "Bram")
    await no_debris(st)
    solo = (await realm(client))["id"]
    r = await client.post("/api/realms/join", json={"code": code.lower()})
    assert r.status_code == 200, r.text
    await login(client, "Ada")
    return {"ada": ada, "bo": bo, "code": code, "bo_solo": solo}


async def test_found_and_join(client: AsyncClient, duo: dict[str, Any], st: Any) -> None:
    rv = await realm(client)
    assert rv["name"] == "Hearth Hollow" and not rv["solo"] and rv["me"]["role"] == "owner"
    assert [(m["username"], m["plot"], m["role"]) for m in rv["members"]] == [
        ("Ada", 0, "owner"),
        ("Bram", 1, "member"),
    ]
    bo = next(m for m in rv["members"] if m["username"] == "Bram")
    assert bo["newcomer"] and not bo["trusted"]
    async with st.sessionmaker() as s:
        village = (
            await s.execute(select(Village).where(Village.user_id == uuid.UUID(duo["bo"]["user_id"])))
        ).scalar_one()
        assert str(village.realm_id) == rv["id"]  # the whole village moved
        old = await s.get(Realm, uuid.UUID(duo["bo_solo"]))
        assert old is not None and old.archived_at is not None
    feed = (await client.get("/api/realm/activity")).json()["items"]
    assert [i["kind"] for i in feed] == ["member_joined", "realm_founded"] and feed[0]["actor"] == "Bram"
    mates = (await client.get("/api/realm/villages")).json()["villages"]
    assert [v["owner_id"] for v in mates] == [duo["bo"]["user_id"]] and mates[0]["buildings"]
    map_ = (await client.get("/api/realm/map")).json()
    assert {p["owner"] for p in map_["plots"] if p["owner"]} == {"Ada", "Bram"}


async def test_join_rules(client: AsyncClient, duo: dict[str, Any]) -> None:
    await signup(client, "Cyra")
    assert (await client.post("/api/realms/join", json={"code": "ZZZZZZ"})).status_code == 404
    await login(client, "Bram")
    r = await client.post("/api/realms/join", json={"code": duo["code"]})
    assert r.json()["error"]["code"] == "already_member"
    await login(client, "Ada")
    r = await client.post("/api/realm/leave")
    assert r.json()["error"]["code"] == "owner_leaving"
    r = await client.post("/api/realms", json={"name": "Again"})
    assert r.json()["error"]["code"] == "already_shared"


async def test_leave_kick_transfer(client: AsyncClient, duo: dict[str, Any], st: Any) -> None:
    bo_id = duo["bo"]["user_id"]
    # Bram leaves and wakes up in their old solo realm, same plot 0
    await login(client, "Bram")
    r = await client.post("/api/realm/leave")
    assert r.status_code == 200, r.text
    assert r.json()["realm"]["id"] == duo["bo_solo"] and r.json()["realm"]["solo"]
    async with st.sessionmaker() as s:
        assert (await s.get(Realm, uuid.UUID(duo["bo_solo"]))).archived_at is None  # type: ignore[union-attr]
    # back in with the code, then handed the realm
    assert (await client.post("/api/realms/join", json={"code": duo["code"]})).status_code == 200
    await login(client, "Ada")
    r = await client.post("/api/realm/transfer", json={"user_id": bo_id})
    assert r.status_code == 200 and r.json()["realm"]["me"]["role"] == "member"
    assert r.json()["realm"]["owner_id"] == bo_id
    assert (await client.post("/api/realm/kick", json={"user_id": bo_id})).status_code == 403
    # the new owner kicks Ada, who gets a fresh solo realm (hers was never archived: she founded this one)
    await login(client, "Bram")
    r = await client.post("/api/realm/kick", json={"user_id": duo["ada"]["user_id"]})
    assert r.status_code == 200 and [m["username"] for m in r.json()["realm"]["members"]] == ["Bram"]
    await login(client, "Ada")
    me = await realm(client)
    assert me["solo"] and me["me"]["role"] == "owner" and me["me"]["plot"] == 0
    # last one out: Bram leaving an otherwise empty realm just makes it solo again
    await login(client, "Bram")
    r = await client.post("/api/realm/leave")
    assert r.json()["realm"]["solo"] and r.json()["realm"]["invite_code"] is None


async def test_stash_trust_rules(client: AsyncClient, duo: dict[str, Any], st: Any, clock: Any) -> None:
    async with st.sessionmaker() as s, s.begin():
        await inventory.grant(s, st.config, uuid.UUID(duo["ada"]["user_id"]), {"ironbark": 20}, "admin.grant")
        await inventory.grant(s, st.config, uuid.UUID(duo["bo"]["user_id"]), {"slime_gel": 5}, "admin.grant")
    inv = (await client.get("/api/inventory")).json()["inventory"]
    slot = next(s["slot"] for s in inv["slots"] if s["item"] == "ironbark")
    r = await client.post("/api/realm/stash/deposit", json={"slot": slot, "quantity": 20})
    assert r.status_code == 200, r.text
    stash = r.json()["stash"]
    assert stash["slots"][0]["item"] == "ironbark" and stash["slots"][0]["qty"] == 20
    assert stash["rules"]["trusted"] is True  # the owner

    # Bram is a newcomer: deposit only
    await login(client, "Bram")
    inv = (await client.get("/api/inventory")).json()["inventory"]
    gel = next(s["slot"] for s in inv["slots"] if s["item"] == "slime_gel")
    assert (
        await client.post("/api/realm/stash/deposit", json={"slot": gel, "quantity": 5})
    ).status_code == 200
    r = await client.post("/api/realm/stash/withdraw", json={"slot": 0, "quantity": 1})
    assert r.status_code == 403 and r.json()["error"]["code"] == "newcomer"
    view = (await client.get("/api/realm/stash")).json()
    assert (
        view["rules"]["newcomer"]
        and view["rules"]["daily_cap"] == st.config.social.stash.untrusted_daily_value
    )

    # two days later: up to the daily value cap (ironbark is worth 25 each, cap 400 → 16 max)
    clock.advance(49 * 3600)
    r = await client.post("/api/realm/stash/withdraw", json={"slot": 0, "quantity": 10})
    assert r.status_code == 200, r.text
    assert r.json()["stash"]["rules"]["used_today"] == 250
    r = await client.post("/api/realm/stash/withdraw", json={"slot": 0, "quantity": 7})
    assert r.status_code == 403 and r.json()["error"]["code"] == "daily_cap"
    assert (
        await client.post("/api/realm/stash/withdraw", json={"slot": 0, "quantity": 6})
    ).status_code == 200

    # trusted: no cap
    await login(client, "Ada")
    assert (
        await client.post("/api/realm/trust", json={"user_id": duo["bo"]["user_id"], "trusted": True})
    ).status_code == 200
    await login(client, "Bram")
    assert (
        await client.post("/api/realm/stash/withdraw", json={"slot": 0, "quantity": 4})
    ).status_code == 200
    kinds = [i["kind"] for i in (await client.get("/api/realm/activity")).json()["items"]]
    assert (
        kinds.count("stash_withdraw") == 3 and kinds.count("stash_deposit") == 2 and "trust_changed" in kinds
    )


async def test_solo_has_no_stash_and_overview(client: AsyncClient, st: Any) -> None:
    await signup(client, "Loner")
    assert (await client.get("/api/realm/stash")).json() == {"available": False}
    ov = (await client.get("/api/realm/overview")).json()
    n = ov["n"]
    assert n == st.config.mapgen.map_size // st.config.mapgen.chunk_size
    assert len(base64.b64decode(ov["data"])) == n * n and len(base64.b64decode(ov["fog"])) == (n * n + 7) // 8
    assert len(ov["waystones"]) == 23 and ov["waystones"][0]["name"] == "Wellside" and ov["attuned"] == []
    async with st.sessionmaker() as s:
        m = (await s.execute(select(RealmMember))).scalar_one()
        assert m.plot_index == 0
