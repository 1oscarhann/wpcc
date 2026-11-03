from __future__ import annotations

import asyncio
from typing import Any

import msgpack
from httpx import AsyncClient
from sqlalchemy import func, select, update

from hearthforge.db.models import EventStatus, Resource, ScheduledEvent, Transaction, Village
from hearthforge.services import village as village_svc
from hearthforge.worker import handlers
from hearthforge.worker.poller import Worker
from tests.conftest import signup


async def get_village(client: AsyncClient) -> dict[str, Any]:
    r = await client.get("/api/village")
    assert r.status_code == 200, r.text
    return r.json()["village"]


async def place(client: AsyncClient, key: str, x: int, y: int, rotation: int = 0) -> Any:
    return await client.post(
        "/api/village/buildings", json={"key": key, "x": x, "y": y, "rotation": rotation}
    )


def by_key(v: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [b for b in v["buildings"] if b["key"] == key]


async def set_resource(st: Any, key: str, amount: int) -> None:
    async with st.sessionmaker() as s, s.begin():
        await s.execute(
            update(Resource).where(Resource.resource_key == key).values(amount_milli=amount * 1000)
        )


async def test_initial_state(client: AsyncClient, player: dict[str, Any]) -> None:
    v = await get_village(client)
    assert v["town_hall_level"] == 1
    assert v["queue"] == {"slots": 2, "used": 0}
    assert {b["key"] for b in v["buildings"]} == {"town_hall", "house"}
    assert v["resources"]["wood"]["amount"] == 300
    assert v["resources"]["wood"]["cap"] == 1000
    assert v["coins"] == 200
    assert v["size"] == 24 and v["frame"] == 48


async def test_place_pays_schedules_and_logs(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    r = await place(client, "lumber_camp", 26, 14)
    assert r.status_code == 200, r.text
    v = r.json()["village"]
    lc = by_key(v, "lumber_camp")[0]
    assert lc["state"] == "constructing" and lc["level"] == 0
    assert lc["completes_at_ms"] - lc["started_at_ms"] == 10_000
    assert v["resources"]["wood"]["amount"] == 260 and v["resources"]["stone"]["amount"] == 180
    assert v["queue"]["used"] == 1
    async with st.sessionmaker() as s:
        assert (await s.execute(select(func.count()).select_from(ScheduledEvent))).scalar_one() == 1
        spent = (
            await s.execute(select(func.sum(Transaction.delta)).where(Transaction.reason == "build.place"))
        ).scalar_one()
        assert spent == -60_000


async def test_placement_rules_over_http(client: AsyncClient, player: dict[str, Any]) -> None:
    r = await place(client, "lumber_camp", 22, 20)  # on the town hall
    assert r.json()["error"]["code"] == "overlap"
    r = await place(client, "mine", 26, 14)
    assert r.json()["error"]["code"] == "locked"
    r = await place(client, "house", 2, 2)
    assert r.json()["error"]["code"] == "out_of_bounds"
    assert (await place(client, "lumber_camp", 26, 14)).status_code == 200
    r = await place(client, "lumber_camp", 29, 14)
    assert r.json()["error"]["code"] == "limit_reached"


async def test_build_queue_limit(client: AsyncClient, player: dict[str, Any]) -> None:
    assert (await place(client, "house", 26, 14)).status_code == 200
    assert (await place(client, "quarry", 29, 14)).status_code == 200
    r = await place(client, "farm", 26, 24)
    assert r.json()["error"]["code"] == "queue_full"


async def test_insufficient_resources(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    await set_resource(st, "wood", 10)
    r = await place(client, "house", 26, 14)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "insufficient_resources"
    assert r.json()["error"]["details"]["missing"]["wood"] == 40


async def test_lazy_completion_and_production(
    client: AsyncClient, player: dict[str, Any], clock: Any
) -> None:
    await place(client, "lumber_camp", 26, 14)
    clock.advance(11)
    v = await get_village(client)
    lc = by_key(v, "lumber_camp")[0]
    assert lc["state"] == "active" and lc["level"] == 1
    assert v["resources"]["wood"]["rate"] == 60
    clock.advance(3600)
    v = await get_village(client)
    # 260 after paying + ~60/h, credited from the moment it finished (not from when we looked)
    assert abs(v["resources"]["wood"]["amount"] - 320) < 0.05


async def test_storage_cap(client: AsyncClient, player: dict[str, Any], clock: Any) -> None:
    await place(client, "lumber_camp", 26, 14)
    clock.advance(100 * 3600)
    v = await get_village(client)
    assert v["resources"]["wood"]["amount"] == 1000


async def test_worker_completes_and_is_idempotent(
    client: AsyncClient, player: dict[str, Any], st: Any, clock: Any
) -> None:
    await place(client, "lumber_camp", 26, 14)
    clock.advance(11)
    worker = Worker(st)
    assert await worker.run_once() is True
    assert await worker.run_once() is False
    async with st.sessionmaker() as s, s.begin():
        ev = (await s.execute(select(ScheduledEvent))).scalar_one()
        assert ev.status == EventStatus.done
        ev.status = EventStatus.pending  # simulate a duplicate delivery
    assert await worker.run_once() is True
    v = await get_village(client)
    assert by_key(v, "lumber_camp")[0]["level"] == 1  # not 2
    async with st.sessionmaker() as s:
        assert (await s.execute(select(Village.version))).scalar_one() >= 2


async def test_worker_processes_overdue_events_oldest_first(
    client: AsyncClient, st: Any, clock: Any, monkeypatch: Any
) -> None:
    await signup(client, "Early")
    await place(client, "house", 26, 14)
    client.cookies.clear()
    clock.advance(5)
    await signup(client, "Late")
    await place(client, "house", 26, 14)
    seen: list[str] = []
    original = handlers.HANDLERS["building.complete"]

    async def spy(session, st_, ev):  # noqa: ANN001
        seen.append(ev.payload["village_id"])
        await original(session, st_, ev)

    monkeypatch.setitem(handlers.HANDLERS, "building.complete", spy)
    clock.advance(3600)  # the worker was "down" for an hour
    assert await Worker(st).drain() == 2
    async with st.sessionmaker() as s:
        rows = (await s.execute(select(ScheduledEvent).order_by(ScheduledEvent.due_at))).scalars().all()
    assert seen == [r.payload["village_id"] for r in rows]


async def test_town_hall_caps_upgrades(
    client: AsyncClient, player: dict[str, Any], clock: Any, st: Any
) -> None:
    await place(client, "lumber_camp", 26, 14)
    clock.advance(11)
    lc_id = by_key(await get_village(client), "lumber_camp")[0]["id"]
    r = await client.post(f"/api/village/buildings/{lc_id}/upgrade")
    assert r.json()["error"]["code"] == "town_hall_cap"
    th_id = by_key(await get_village(client), "town_hall")[0]["id"]
    r = await client.post(f"/api/village/buildings/{th_id}/upgrade")
    assert r.status_code == 200, r.text
    assert r.json()["village"]["coins"] == 100
    clock.advance(56)
    v = await get_village(client)
    assert v["town_hall_level"] == 2
    assert v["resources"]["wood"]["cap"] == 1500
    await set_resource(st, "wood", 500)
    await set_resource(st, "stone", 500)
    r = await client.post(f"/api/village/buildings/{lc_id}/upgrade")
    assert r.status_code == 200, r.text


async def test_cancel_refunds_75_percent(client: AsyncClient, player: dict[str, Any]) -> None:
    v = (await place(client, "house", 26, 14)).json()["village"]
    hid = [b for b in v["buildings"] if b["key"] == "house" and b["state"] == "constructing"][0]["id"]
    r = await client.post(f"/api/village/buildings/{hid}/cancel")
    assert r.status_code == 200
    assert r.json()["refunded"] == {"wood": 37, "stone": 15}
    v = r.json()["village"]
    assert v["resources"]["wood"]["amount"] == 300 - 50 + 37
    assert len(by_key(v, "house")) == 1  # the in-progress one was removed


async def test_demolish_refunds_half_and_town_hall_is_protected(
    client: AsyncClient, player: dict[str, Any]
) -> None:
    v = await get_village(client)
    house = by_key(v, "house")[0]["id"]
    r = await client.delete(f"/api/village/buildings/{house}")
    assert r.json()["refunded"] == {"wood": 25, "stone": 10}
    th = by_key(v, "town_hall")[0]["id"]
    r = await client.delete(f"/api/village/buildings/{th}")
    assert r.json()["error"]["code"] == "not_demolishable"


async def test_undo_place_within_window(client: AsyncClient, player: dict[str, Any], clock: Any) -> None:
    await place(client, "house", 26, 14)
    clock.advance(20)
    r = await client.post("/api/village/undo")
    assert r.status_code == 200, r.text
    v = r.json()["village"]
    assert len(by_key(v, "house")) == 1
    assert v["resources"]["wood"]["amount"] == 300  # full refund
    r = await client.post("/api/village/undo")
    assert r.json()["error"]["code"] == "nothing_to_undo"


async def test_undo_expires(client: AsyncClient, player: dict[str, Any], clock: Any) -> None:
    await place(client, "house", 26, 14)
    clock.advance(61)
    r = await client.post("/api/village/undo")
    assert r.json()["error"]["code"] == "nothing_to_undo"


async def test_undo_demolish_restores_building(client: AsyncClient, player: dict[str, Any]) -> None:
    v = await get_village(client)
    house = by_key(v, "house")[0]
    await client.delete(f"/api/village/buildings/{house['id']}")
    r = await client.post("/api/village/undo")
    assert r.status_code == 200, r.text
    v = r.json()["village"]
    restored = by_key(v, "house")[0]
    assert (restored["x"], restored["y"], restored["level"]) == (house["x"], house["y"], 1)
    assert v["resources"]["wood"]["amount"] == 300


async def test_move_and_rotate(client: AsyncClient, player: dict[str, Any]) -> None:
    house = by_key(await get_village(client), "house")[0]["id"]
    r = await client.patch(f"/api/village/buildings/{house}", json={"x": 30, "y": 30, "rotation": 1})
    assert r.status_code == 200
    moved = by_key(r.json()["village"], "house")[0]
    assert (moved["x"], moved["y"], moved["rotation"]) == (30, 30, 1)
    r = await client.patch(f"/api/village/buildings/{house}", json={"x": 22, "y": 20, "rotation": 0})
    assert r.json()["error"]["code"] == "overlap"


async def test_preview(client: AsyncClient, player: dict[str, Any]) -> None:
    ok = (await client.get("/api/village/preview", params={"key": "house", "x": 26, "y": 14})).json()
    assert ok == {"valid": True, "errors": [], "reason": None, "combos": [], "mystery": 0}
    bad = (await client.get("/api/village/preview", params={"key": "house", "x": 22, "y": 20})).json()
    assert bad["valid"] is False and bad["errors"] == ["overlap"] and bad["reason"]


async def test_concurrent_spend_race(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    """Rapid parallel requests must never double-spend: wood for exactly one house."""
    await set_resource(st, "wood", 60)
    results = await asyncio.gather(
        *(place(client, "house", 26 + (i % 2) * 3, 14 + (i // 2) * 3) for i in range(5))
    )
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 1
    v = await get_village(client)
    assert v["resources"]["wood"]["amount"] == 10
    assert len(by_key(v, "house")) == 2


async def test_fast_forward(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    await place(client, "lumber_camp", 26, 14)
    async with st.sessionmaker() as s, s.begin():
        uid = (await s.execute(select(Village.user_id))).scalar_one()
        await village_svc.fast_forward(s, uid, 3600 + 10)
    v = await get_village(client)
    assert by_key(v, "lumber_camp")[0]["level"] == 1
    assert v["resources"]["wood"]["amount"] > 260


async def test_realm_map_and_chunks(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    m = (await client.get("/api/realm/map")).json()
    assert m["my_plot"] == 0 and len(m["plots"]) == 10 and m["plots"][0]["owner"] == "Tester"
    ox, oy = m["plots"][0]["origin"]
    cs = m["chunk_size"]
    ids = f"{ox // cs}_{oy // cs};{ox // cs + 1}_{oy // cs}"
    r = await client.get(f"/api/realms/{m['realm_id']}/chunks", params={"ids": ids})
    assert r.headers["content-type"] == "application/msgpack"
    data = msgpack.unpackb(r.content)
    assert len(data["chunks"]) == 2 and len(data["chunks"][0]["ground"]) == cs * cs
    r = await client.get("/api/realms/00000000-0000-0000-0000-000000000000/chunks", params={"ids": "0_0"})
    assert r.status_code == 403
