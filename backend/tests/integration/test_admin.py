"""Phase 18: the admin panel's API. Only admins get in; grants, bans and world boss starts are audited."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update

from hearthforge.db.models import User, UserRole
from tests.conftest import signup
from tests.integration.test_realms import login


async def make_admin(st: Any, user_id: str) -> None:
    async with st.sessionmaker() as s, s.begin():
        await s.execute(update(User).where(User.id == uuid.UUID(user_id)).values(role=UserRole.admin))


async def test_admin_panel(client: AsyncClient, st: Any) -> None:
    boss = await signup(client, "Boss")
    pip = await signup(client, "Pip")
    await login(client, "Boss")
    assert (await client.get("/api/admin/overview")).status_code == 403  # not an admin yet
    await make_admin(st, boss["user_id"])
    o = (await client.get("/api/admin/overview")).json()
    assert o["players"] == 2 and o["coin_supply"] > 0 and "rooms" in o
    found = (await client.get("/api/admin/players", params={"q": "pi"})).json()["players"]
    assert [p["username"] for p in found] == ["Pip"]
    r = await client.post(
        "/api/admin/grant", json={"user_id": pip["user_id"], "coins": 250, "items": {"slime_gel": 3}}
    )
    assert r.status_code == 200, r.text
    d = (await client.get(f"/api/admin/players/{pip['user_id']}")).json()
    assert any(t["reason"] == "admin.grant" and t["delta"] == 250 for t in d["ledger"])
    assert any(s["item"] == "slime_gel" and s["qty"] == 3 for s in d["bag"])
    r = await client.post("/api/admin/grant", json={"user_id": pip["user_id"], "items": {"nope": 1}})
    assert r.json()["error"]["code"] == "unknown_item"
    assert (
        await client.post("/api/admin/ban", json={"user_id": pip["user_id"], "enable": True})
    ).status_code == 200
    r = await client.post("/api/auth/login", json={"username": "Pip", "password": "correct horse"})
    assert r.status_code != 200  # banned players can't log in
    await login(client, "Boss")
    r = await client.post("/api/admin/worldboss", json={"hours": 1, "hp": 5000})
    assert r.status_code == 200
    log = (await client.get("/api/admin/audit")).json()["entries"]
    assert [e["action"] for e in log][:3] == ["worldboss.start", "ban", "grant"] and log[0]["actor"] == "Boss"
