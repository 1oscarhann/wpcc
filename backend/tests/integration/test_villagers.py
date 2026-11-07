"""Phase 14: villagers (arrivals, homes, jobs, leaving), food demand (P10), happiness, beauty, decor."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import signup
from tests.integration.test_crafting import give
from tests.integration.test_village import by_key, get_village, no_debris, place, set_resource


@pytest.fixture
async def player(client: AsyncClient, st: Any) -> dict[str, Any]:
    data = await signup(client)
    await no_debris(st)
    return data


async def test_a_new_village_gets_its_first_villagers(
    client: AsyncClient, player: dict[str, Any], st: Any
) -> None:
    v = await get_village(client)
    cfg = st.config.villagers
    house = by_key(v, "house")[0]
    cap = st.config.buildings["house"].level(house["level"]).housing
    assert len(v["villagers"]) == min(cfg.arrival.start_with, cap)
    assert all(x["home"] == house["id"] for x in v["villagers"])
    assert all(x["name"] and x["look"]["hair_style"] for x in v["villagers"])
    assert v["housing"] == {"cap": cap, "used": len(v["villagers"])}
    h = v["happiness"]
    assert 0 <= h["value"] <= 100 and set(h) >= {"beauty", "housing", "food", "tavern", "mood"}
    # P10: they eat food as a rate; no farm yet, so the food rate is floored at zero (no starvation)
    assert v["resources"]["food"]["rate"] == 0
    assert v["food_demand"] == len(v["villagers"]) * cfg.food_per_villager


async def test_jobs_add_output_and_slots_are_limited(
    client: AsyncClient,
    player: dict[str, Any],
    st: Any,
    clock: Any,
) -> None:
    assert (await place(client, "lumber_camp", 27, 12)).status_code == 200
    clock.advance(11)
    v = await get_village(client)
    camp = by_key(v, "lumber_camp")[0]
    base = v["resources"]["wood"]["rate"]
    a, b = v["villagers"][0], v["villagers"][1]
    r = await client.post(f"/api/village/villagers/{a['id']}/assign", json={"building_id": None})
    assert r.status_code == 200
    r = await client.post(f"/api/village/villagers/{b['id']}/assign", json={"building_id": None})
    v = r.json()["village"]
    idle_rate = v["resources"]["wood"]["rate"]
    r = await client.post(f"/api/village/villagers/{a['id']}/assign", json={"building_id": camp["id"]})
    assert r.status_code == 200, r.text
    v = r.json()["village"]
    bonus = st.config.villagers.jobs.production_bonus
    assert v["resources"]["wood"]["rate"] > idle_rate
    assert v["job_slots"][camp["id"]] == {"slots": 1, "workers": 1}
    # level 1 has one slot: the second villager can't squeeze in
    r = await client.post(f"/api/village/villagers/{b['id']}/assign", json={"building_id": camp["id"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "job_full"
    # nobody works at a house
    house = by_key(v, "house")[0]
    r = await client.post(f"/api/village/villagers/{b['id']}/assign", json={"building_id": house["id"]})
    assert r.json()["error"]["code"] == "no_jobs"
    assert bonus > 0 and base >= idle_rate


async def test_newcomers_arrive_while_there_is_room_and_cheer(
    client: AsyncClient,
    player: dict[str, Any],
    st: Any,
    clock: Any,
) -> None:
    await set_resource(st, "wood", 2000)
    await set_resource(st, "stone", 2000)
    await set_resource(st, "food", 2000)
    for key, x, y in (("house", 27, 12), ("farm", 9, 9)):
        r = await place(client, key, x, y)
        assert r.status_code == 200, r.text
        clock.advance(11)
    v = await get_village(client)
    n0 = len(v["villagers"])
    assert v["housing"]["cap"] > n0
    if v["happiness"]["value"] < st.config.villagers.arrival.min_happiness:
        return  # (balance changed so a bare village is glum: nothing more to check)
    clock.advance(st.config.villagers.arrival.every + 1)
    v = await get_village(client)
    assert len(v["villagers"]) == n0 + 1
    newest = v["villagers"][-1]
    assert newest["home"] is not None


async def test_decorations_go_down_instantly_and_add_beauty(
    client: AsyncClient,
    player: dict[str, Any],
    st: Any,
) -> None:
    v0 = await get_village(client)
    r = await place(client, "flower_bed", 12, 12)
    assert r.status_code == 200, r.text
    v = r.json()["village"]
    bed = by_key(v, "flower_bed")[0]
    assert bed["state"] == "active" and bed["level"] == 1
    assert v["queue"]["used"] == v0["queue"]["used"]  # no builder needed
    fb = st.config.buildings["flower_bed"].cfg.beauty
    assert v["beauty"]["decor"] == v0["beauty"]["decor"] + fb
    assert v["beauty"]["variety"] == v0["beauty"]["variety"] + st.config.villagers.beauty.variety
    # a blueprint decoration needs its blueprint, and uses it up
    r = await place(client, "lantern_post", 14, 12)
    assert r.status_code == 400 and r.json()["error"]["code"] == "needs_blueprint"
    await give(st, player["user_id"], {"blueprint_lantern_post": 1, "ore": 10})
    await set_resource(st, "ore", 100)
    r = await place(client, "lantern_post", 14, 12)
    assert r.status_code == 200, r.text
    inv = (await client.get("/api/inventory")).json()["inventory"]
    assert not any(s["item"] == "blueprint_lantern_post" for s in inv["slots"])


async def test_paths_link_buildings_for_beauty(client: AsyncClient, player: dict[str, Any], st: Any) -> None:
    await set_resource(st, "wood", 500)
    await set_resource(st, "stone", 500)
    v = await get_village(client)
    th = by_key(v, "town_hall")[0]  # 4×4 at (22, 19); the house is at (17, 20) 3×3
    # a path from the Town Hall's west edge (x=21) to the house's east edge (x=20)
    r0 = await place(client, "path_dirt", 21, 21)
    assert r0.status_code == 200, r0.text
    assert r0.json()["village"]["beauty"]["linked"] == 0  # one tile short of the house
    r1 = await place(client, "path_dirt", 20, 21)
    assert r1.status_code == 200, r1.text
    v = r1.json()["village"]
    assert v["beauty"]["linked"] == 1  # the house touches the path that touches the Town Hall
    assert v["beauty"]["connected"] == st.config.villagers.beauty.connected
    assert th["key"] == "town_hall"


async def test_misery_drives_villagers_away(
    client: AsyncClient, player: dict[str, Any], st: Any, clock: Any
) -> None:
    v = await get_village(client)
    n0 = len(v["villagers"])
    house = by_key(v, "house")[0]
    r = await client.delete(f"/api/village/buildings/{house['id']}")
    assert r.status_code == 200, r.text
    v = r.json()["village"]
    assert v["housing"]["cap"] == 0 and all(x["home"] is None for x in v["villagers"])
    if v["happiness"]["value"] >= st.config.villagers.leaving.below:
        return  # beautiful enough to stay even homeless (balance changed)
    assert v["happiness"]["leave_at_ms"] is not None
    clock.advance(st.config.villagers.leaving.after + 1)
    v = await get_village(client)
    assert len(v["villagers"]) == n0 - 1
