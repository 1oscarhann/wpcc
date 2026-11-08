"""Phase 16b: pets (tokens or unlocks, perks, names), mounts (Town Hall, coins) and the Trophy Hall."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update

from hearthforge.db.models import Village, VillageBuilding, Wallet
from hearthforge.services import progress, stats
from tests.integration.test_crafting import give
from tests.integration.test_journal import bump, coins


async def test_pets(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    uid = player["user_id"]
    v = (await client.get("/api/companions")).json()
    fox = next(p for p in v["pets"] if p["key"] == "fox")
    assert not fox["owned"] and fox["cost"]["tokens"] == 3 and v["tokens"] == 0
    r = await client.post("/api/companions/pets/adopt", json={"key": "fox"})
    assert r.json()["error"]["code"] == "no_tokens"
    await give(st, uid, {"cosmetic_token": 4})
    r = await client.post("/api/companions/pets/adopt", json={"key": "fox"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["tokens"] == 1 and next(p for p in v["pets"] if p["key"] == "fox")["active"]
    async with st.sessionmaker() as s:
        perks = await progress.perks_of(s, st.config, uuid.UUID(uid))
    assert perks["gather_yield"] == 0.05  # the fox's perk joins your skills'
    # an unlock pet
    r = await client.post("/api/companions/pets/adopt", json={"key": "slime"})
    assert r.json()["error"]["code"] == "locked"
    await bump(st, uid, {"kill.slime": 300})
    r = await client.post("/api/companions/pets/adopt", json={"key": "slime"})
    assert r.status_code == 200 and next(p for p in r.json()["pets"] if p["key"] == "slime")["active"]
    # names
    r = await client.post("/api/companions/pets/rename", json={"key": "slime", "name": "x"})
    assert r.json()["error"]["code"] == "bad_name"
    r = await client.post("/api/companions/pets/rename", json={"key": "slime", "name": "  Sir   Wobble "})
    assert next(p for p in r.json()["pets"] if p["key"] == "slime")["nickname"] == "Sir Wobble"
    r = await client.post("/api/companions/pets/active", json={"key": None})
    assert not any(p["active"] for p in r.json()["pets"])
    r = await client.post("/api/companions/pets/active", json={"key": "owl"})
    assert r.status_code == 404


async def test_mounts(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    uid = uuid.UUID(player["user_id"])
    r = await client.post("/api/companions/mounts/buy", json={"key": "horse"})
    assert r.json()["error"]["code"] == "locked"  # a level 3 Town Hall first
    async with st.sessionmaker() as s, s.begin():
        vid = (await s.execute(Village.__table__.select().where(Village.user_id == uid))).first().id
        await s.execute(
            update(VillageBuilding)
            .where(VillageBuilding.village_id == vid, VillageBuilding.building_key == "town_hall")
            .values(level=3)
        )
        await s.execute(update(Wallet).where(Wallet.user_id == uid).values(coins=1000))
    r = await client.post("/api/companions/mounts/buy", json={"key": "horse"})
    assert r.json()["error"]["code"] == "insufficient_coins"
    async with st.sessionmaker() as s, s.begin():
        await s.execute(update(Wallet).where(Wallet.user_id == uid).values(coins=4000))
    r = await client.post("/api/companions/mounts/buy", json={"key": "horse"})
    assert r.status_code == 200, r.text
    assert next(m for m in r.json()["mounts"] if m["key"] == "horse")["active"]
    assert await coins(st, player["user_id"]) == 1500
    r = await client.post("/api/companions/mounts/buy", json={"key": "horse"})
    assert r.json()["error"]["code"] == "owned"


async def test_trophy_hall(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    uid = uuid.UUID(player["user_id"])
    async with st.sessionmaker() as s, s.begin():
        await stats.bump(s, uid, {"fish.trout": 3, "fish.any": 3})
        await stats.record(s, uid, {"best.fish.trout": 1200})
        await stats.record(s, uid, {"best.fish.trout": 800})  # a smaller one doesn't beat the record
    h = (await client.get("/api/companions/trophies")).json()
    trout = next(f for f in h["fish"] if f["key"] == "trout")
    assert trout["caught"] == 3 and trout["best_g"] == 1200 and h["totals"]["fish.any"] == 3
    assert len(h["bosses"]) == len(st.config.bosses.bosses)
