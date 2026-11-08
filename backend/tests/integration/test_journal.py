"""Phase 16: skills (learn, prerequisites, respec), quests, achievements and titles, the login calendar."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from hearthforge.db.models import Wallet
from hearthforge.services import stats
from tests.integration.test_social import level


async def bump(st: Any, user_id: str, counts: dict[str, int]) -> None:
    async with st.sessionmaker() as s, s.begin():
        await stats.bump(s, uuid.UUID(user_id), counts)


async def coins(st: Any, user_id: str) -> int:
    async with st.sessionmaker() as s:
        return (
            await s.execute(select(Wallet.coins).where(Wallet.user_id == uuid.UUID(user_id)))
        ).scalar_one()


async def test_skills(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    j = (await client.get("/api/journal")).json()["skills"]
    assert j["points"] == 0 and j["can"]["power"] == "no_points"
    await level(st, player["user_id"], 6)  # 5 points
    r = await client.post("/api/journal/skills/learn", json={"key": "precision"})
    assert r.json()["error"]["code"] == "locked"  # needs Power first
    for key in ("power", "power", "precision"):
        r = await client.post("/api/journal/skills/learn", json={"key": key})
        assert r.status_code == 200, r.text
    sk = r.json()
    assert sk["ranks"] == {"power": 2, "precision": 1} and sk["spent"] == 3
    assert sk["perks"]["damage"] == 0.06 and sk["perks"]["crit"] == 0.02
    assert sk["can"]["slayer"] == "locked"  # a capstone needs points in the branch
    # the first respec is free, the next costs coins
    r = await client.post("/api/journal/skills/respec")
    assert r.json()["cost"] == 0 and r.json()["ranks"] == {}
    await client.post("/api/journal/skills/learn", json={"key": "bountiful"})
    async with st.sessionmaker() as s, s.begin():
        from sqlalchemy import update

        await s.execute(
            update(Wallet).where(Wallet.user_id == uuid.UUID(player["user_id"])).values(coins=1000)
        )
    before = await coins(st, player["user_id"])
    r = await client.post("/api/journal/skills/respec")
    assert r.json()["cost"] == st.config.skills.respec.coins_per_level * 6
    assert await coins(st, player["user_id"]) == before - r.json()["cost"]


async def test_quests(client: AsyncClient, player: dict[str, Any], st: Any, clock: Any) -> None:
    q = (await client.get("/api/journal")).json()["quests"]
    assert len(q["daily"]) == st.config.progression.quests.daily.count
    assert len(q["weekly"]) == st.config.progression.quests.weekly.count
    assert q["main"]["key"] == st.config.progression.quests.main[0].key
    first = q["daily"][0]
    quest = next(x for x in st.config.progression.quests.daily.pool if x.key == first["key"])
    r = await client.post("/api/journal/quests/claim", json={"period": "daily", "key": first["key"]})
    assert r.json()["error"]["code"] == "not_done"
    await bump(st, player["user_id"], {quest.stat: quest.target})
    q = (await client.get("/api/journal")).json()["quests"]
    assert next(x for x in q["daily"] if x["key"] == first["key"])["done"]
    before = await coins(st, player["user_id"])
    r = await client.post("/api/journal/quests/claim", json={"period": "daily", "key": first["key"]})
    assert r.status_code == 200, r.text
    lo, hi = st.config.progression.quests.daily.rewards.coins
    assert lo <= await coins(st, player["user_id"]) - before <= hi
    r = await client.post("/api/journal/quests/claim", json={"period": "daily", "key": first["key"]})
    assert r.json()["error"]["code"] == "claimed"
    # tomorrow brings a fresh board, counting from tomorrow's numbers
    clock.advance(days=1)
    q2 = (await client.get("/api/journal")).json()["quests"]
    assert all(not x["claimed"] and x["progress"] == 0 for x in q2["daily"])


async def test_board_survives_a_level_up(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    """Levelling past a quest's min_level mid-day must not swap the board (and wipe its progress)."""
    q1 = (await client.get("/api/journal")).json()["quests"]
    await level(st, player["user_id"], 20)
    await bump(st, player["user_id"], {"kill.any": 3})
    q2 = (await client.get("/api/journal")).json()["quests"]
    for period in ("daily", "weekly"):
        assert [x["key"] for x in q1[period]] == [x["key"] for x in q2[period]]
    slayer = next((x for x in q2["daily"] if x["key"] == "slayer"), None)
    if slayer is not None:
        assert slayer["progress"] == 3


async def test_achievements_and_titles(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    await bump(st, player["user_id"], {"kill.slime": 500, "kill.any": 500})
    a = (await client.get("/api/journal")).json()["achievements"]
    got = {x["key"]: x for x in a["achievements"]}
    assert (
        got["slime_slayer"]["unlocked"]
        and got["first_blood"]["unlocked"]
        and not got["monster_bane"]["unlocked"]
    )
    r = await client.post("/api/journal/title", json={"title": "Slime Slayer"})
    assert r.json()["error"]["code"] == "no_title"  # claim it first
    r = await client.post("/api/journal/achievements/claim", json={"key": "slime_slayer"})
    assert r.json()["got"]["title"] == "Slime Slayer"
    r = await client.post("/api/journal/title", json={"title": "Slime Slayer"})
    assert r.status_code == 200
    a = (await client.get("/api/journal")).json()["achievements"]
    assert a["title"] == "Slime Slayer" and "Slime Slayer" in a["titles"]
    r = await client.post("/api/journal/achievements/claim", json={"key": "monster_bane"})
    assert r.json()["error"]["code"] == "locked"


async def test_login_calendar(client: AsyncClient, player: dict[str, Any], st: Any, clock: Any) -> None:
    cal = (await client.get("/api/journal")).json()["calendar"]
    assert cal["day"] == 0 and not cal["claimed_today"] and len(cal["days"]) == 28
    before = await coins(st, player["user_id"])
    r = await client.post("/api/journal/calendar/claim")
    assert r.status_code == 200, r.text
    assert await coins(st, player["user_id"]) == before + st.config.progression.calendar.days[0].coins
    r = await client.post("/api/journal/calendar/claim")
    assert r.json()["error"]["code"] == "claimed_today"
    # miss a few days: nothing is lost, the calendar just waits
    clock.advance(days=4)
    r = await client.post("/api/journal/calendar/claim")
    assert r.status_code == 200 and r.json()["got"]["day"] == 2
    v = (await client.get("/api/village")).json()["village"]
    assert v["resources"]["wood"]["amount"] >= st.config.progression.calendar.days[1].res["wood"]


async def test_collection(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    await bump(st, player["user_id"], {"kill.slime": 3, "gather.wood": 12})
    c = (await client.get("/api/journal/collection")).json()
    slime = next(x for x in c["bestiary"] if x["key"] == "slime")
    assert slime["count"] == 3 and next(x for x in c["materials"] if x["key"] == "wood")["count"] == 12
    assert c["combos"]["total"] == len(st.config.combos.combos)
    assert any(x["boss"] for x in c["bestiary"])
