from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select

from hearthforge.db.models import (
    Avatar,
    Container,
    ContainerSlot,
    Realm,
    RealmMember,
    RecoveryCode,
    Resource,
    Transaction,
    Village,
    VillageBuilding,
    Wallet,
)
from tests.conftest import DEFAULT_LOOK, signup


async def count(st: Any, model: type, *where: Any) -> int:
    async with st.sessionmaker() as s:
        return (await s.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def test_signup_creates_the_whole_world(client: AsyncClient, st: Any) -> None:
    data = await signup(client, "Hearthling")
    assert len(data["recovery_codes"]) == st.config.game.auth.recovery_codes
    assert "hf_session" in client.cookies and "hf_csrf" in client.cookies

    assert await count(st, Realm) == 1
    assert await count(st, RealmMember) == 1
    assert await count(st, Village) == 1
    assert await count(st, VillageBuilding) == len(st.config.starter.buildings)
    assert await count(st, Resource) == len(st.config.resource_keys)
    assert await count(st, Container) == 4
    assert await count(st, ContainerSlot) == 3  # sword, potions, spear
    assert await count(st, Avatar) == 1
    assert await count(st, RecoveryCode) == st.config.game.auth.recovery_codes
    async with st.sessionmaker() as s:
        wallet = (await s.execute(select(Wallet))).scalar_one()
        assert wallet.coins == st.config.starter.coins
        coin_sum = (
            await s.execute(select(func.sum(Transaction.delta)).where(Transaction.asset == "coin"))
        ).scalar_one()
        assert coin_sum == wallet.coins  # ledger invariant (SCHEMA §12.4)
        realm = (await s.execute(select(Realm))).scalar_one()
        assert realm.is_solo and realm.invite_code is None


async def test_me(client: AsyncClient, player: dict[str, Any]) -> None:
    r = await client.get("/api/me")
    assert r.status_code == 200
    me = r.json()
    assert me["user"]["username"] == "Tester"
    assert me["avatar"]["appearance"] == DEFAULT_LOOK
    assert me["realm"]["is_solo"] is True
    assert me["csrf_token"] == player["csrf_token"]


async def test_me_requires_login(client: AsyncClient) -> None:
    r = await client.get("/api/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_logged_in"


async def test_username_taken_case_insensitive(client: AsyncClient) -> None:
    await signup(client, "Robin")
    client.cookies.clear()
    r = await client.post(
        "/api/auth/signup", json={"username": "ROBIN", "password": "longenough", "appearance": DEFAULT_LOOK}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "username_taken"


async def test_signup_rejects_profanity_short_password_and_bad_look(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/signup",
        json={"username": "sh1tlord", "password": "longenough", "appearance": DEFAULT_LOOK},
    )
    assert r.json()["error"]["code"] == "bad_username"
    r = await client.post(
        "/api/auth/signup", json={"username": "Fine", "password": "short", "appearance": DEFAULT_LOOK}
    )
    assert r.json()["error"]["code"] == "weak_password"
    r = await client.post(
        "/api/auth/signup",
        json={
            "username": "Fine",
            "password": "longenough",
            "appearance": {**DEFAULT_LOOK, "hair_color": "plaid"},
        },
    )
    assert r.json()["error"]["code"] == "bad_appearance"


async def test_username_available(client: AsyncClient) -> None:
    await signup(client, "Taken")
    assert (await client.get("/api/auth/username-available", params={"name": "taken"})).json()["ok"] is False
    assert (await client.get("/api/auth/username-available", params={"name": "Free_Name"})).json()[
        "ok"
    ] is True
    bad = (await client.get("/api/auth/username-available", params={"name": "a"})).json()
    assert bad["ok"] is False and bad["reason"]


async def test_login_logout_cycle(client: AsyncClient) -> None:
    await signup(client, "Cycler", "a good password")
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert (await client.get("/api/me")).status_code == 401

    r = await client.post("/api/auth/login", json={"username": "cycler", "password": "wrong password"})
    assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"username": "cycler", "password": "a good password"})
    assert r.status_code == 200
    client.headers["x-csrf-token"] = r.json()["csrf_token"]
    assert (await client.get("/api/me")).status_code == 200


async def test_csrf_required_on_mutations(client: AsyncClient, player: dict[str, Any]) -> None:
    del client.headers["x-csrf-token"]
    r = await client.put(
        "/api/me/settings", json={"audio": {"master": 0.5, "music": 0.5, "sfx": 0.5, "muted": False}}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
    client.headers["x-csrf-token"] = player["csrf_token"]
    r = await client.put(
        "/api/me/settings", json={"audio": {"master": 0.5, "music": 0.5, "sfx": 0.5, "muted": True}}
    )
    assert r.status_code == 200 and r.json()["audio"]["muted"] is True


async def test_foreign_origin_rejected(client: AsyncClient, player: dict[str, Any]) -> None:
    r = await client.post("/api/auth/logout", headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"


async def test_recovery_code_resets_password_once(client: AsyncClient) -> None:
    data = await signup(client, "Forgetful", "original password")
    code = data["recovery_codes"][0]
    client.cookies.clear()
    r = await client.post(
        "/api/auth/recover",
        json={
            "username": "Forgetful",
            "code": code.lower().replace("-", " "),
            "new_password": "brand new password",
        },
    )
    assert r.status_code == 200 and r.json()["codes_left"] == 7
    r = await client.post(
        "/api/auth/recover", json={"username": "Forgetful", "code": code, "new_password": "another password"}
    )
    assert r.status_code == 401  # each code works once
    r = await client.post("/api/auth/login", json={"username": "Forgetful", "password": "brand new password"})
    assert r.status_code == 200


async def test_auth_rate_limited(client: AsyncClient) -> None:
    await signup(client, "Target")
    codes = []
    for _ in range(12):
        r = await client.post("/api/auth/login", json={"username": "Target", "password": "nope nope"})
        codes.append(r.status_code)
    assert 429 in codes


async def test_change_appearance(client: AsyncClient, player: dict[str, Any]) -> None:
    look = {**DEFAULT_LOOK, "hair_style": "braids", "hair_color": "teal"}
    r = await client.put("/api/avatar/appearance", json={"appearance": look})
    assert r.status_code == 200
    assert (await client.get("/api/me")).json()["avatar"]["appearance"]["hair_color"] == "teal"


async def test_config_bundle_and_etag(client: AsyncClient) -> None:
    r = await client.get("/api/config")
    assert r.status_code == 200
    bundle = r.json()
    assert "town_hall" in bundle["buildings"]
    assert "combos" not in bundle  # secret sections never leave the server
    r2 = await client.get("/api/config", headers={"if-none-match": r.headers["etag"]})
    assert r2.status_code == 304


async def test_ledger_is_append_only(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    import pytest
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError

    async with st.sessionmaker() as s:
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(update(Transaction).values(delta=999))
