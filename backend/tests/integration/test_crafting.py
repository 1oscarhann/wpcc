"""Phase 6 end to end: discover a combo, forge with a rare material, smelt ingots, repair, salvage."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from hearthforge.db.models import ItemInstance, Transaction
from hearthforge.services import inventory
from tests.conftest import signup
from tests.integration.test_village import by_key, get_village, no_debris, place


@pytest.fixture
async def player(client: AsyncClient, st: Any) -> dict[str, Any]:
    data = await signup(client)
    await no_debris(st)
    return data


async def give(st: Any, user_id: str, items: dict[str, int]) -> None:
    import uuid

    async with st.sessionmaker() as s, s.begin():
        await inventory.grant(s, st.config, uuid.UUID(user_id), items, "admin.grant")


async def test_discover_forge_and_upkeep(
    client: AsyncClient, player: dict[str, Any], st: Any, clock: Any
) -> None:
    assert (await place(client, "forge", 27, 12)).status_code == 200
    clock.advance(11)
    v = await get_village(client)
    forge = by_key(v, "forge")[0]

    # the ghost of a lumber camp beside the forge "resonates" without giving the secret away (P17)
    r = await client.get("/api/village/preview?key=lumber_camp&x=30&y=12")
    assert r.json()["mystery"] == 1 and r.json()["combos"] == []
    book = (await client.get("/api/crafting/book")).json()
    assert book["found"] == 0 and all(not c["discovered"] for c in book["combos"])
    assert all("buildings" not in c and "name" not in c for c in book["combos"])  # only hints

    assert (await place(client, "lumber_camp", 30, 12)).status_code == 200
    clock.advance(11)
    v = await get_village(client)
    assert v["discovered"] == ["forge_lumber"]
    assert [c["key"] for c in v["combos"]] == ["forge_lumber"] and v["combos"][0]["tier"] == 1
    book = (await client.get("/api/crafting/book")).json()
    found = next(c for c in book["combos"] if c["discovered"])
    assert found["name"] == "Spearwright" and found["unlocks"] == ["spear", "bow"]

    # the station offers a copper spear; add an ironbark for luck and a guaranteed modifier
    opts = (await client.get(f"/api/crafting/stations/{forge['id']}")).json()
    spear = next(g for g in opts["gear"] if g["recipe"] == "spear")
    assert spear["tier"] == 1 and spear["bill"] == {"wood": 20, "ore": 10} and spear["name"] == "Copper Spear"
    assert [i["recipe"] for i in opts["intermediates"]] == ["ingots"]
    await give(st, player["user_id"], {"ironbark": 1})
    r = await client.post(
        "/api/crafting/jobs", json={"station_id": forge["id"], "recipe": "spear", "rares": ["ironbark"]}
    )
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["kind"] == "gear" and job["rares"] == ["ironbark"]
    # one job at a time at a level-1 forge
    r2 = await client.post(
        "/api/crafting/jobs", json={"station_id": forge["id"], "recipe": "ingots", "quantity": 5}
    )
    assert r2.status_code == 400 and r2.json()["error"]["code"] == "station_busy"
    assert (await client.post(f"/api/crafting/jobs/{job['id']}/collect")).json()["error"][
        "code"
    ] == "not_ready"
    clock.advance(6)
    r = await client.post(f"/api/crafting/jobs/{job['id']}/collect")
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["item"] == "spear" and item["tier"] == 1 and item["durability"] == 120
    assert item["rarity"] != "common"  # a rare material lifts the floor (D-052)
    assert item["modifiers"][0]["key"] == "heavy"  # and its modifier always lands
    inv = (await client.get("/api/inventory")).json()["inventory"]["slots"]
    forged = next(s for s in inv if s.get("name") == "Copper Spear")
    assert not any(s["item"] == "ironbark" for s in inv)

    # smelting: ingots land in storage by themselves
    ore0 = (await get_village(client))["resources"]["ore"]["amount"]
    r = await client.post(
        "/api/crafting/jobs", json={"station_id": forge["id"], "recipe": "ingots", "quantity": 5}
    )
    assert r.status_code == 200, r.text
    v = r.json()["village"]
    assert abs(v["resources"]["ore"]["amount"] - (ore0 - 15)) < 0.01 and len(v["jobs"]) == 1
    # a busy station can't be demolished
    r = await client.delete(f"/api/village/buildings/{forge['id']}")
    assert r.status_code == 400 and r.json()["error"]["code"] == "station_busy"
    clock.advance(21)
    v = await get_village(client)
    assert v["jobs"] == [] and v["resources"]["ingots"]["amount"] == 5

    # repair: wear the spear down, then pay coins + ingots at the forge
    async with st.sessionmaker() as s, s.begin():
        iid = (await s.execute(select(ItemInstance.id).where(ItemInstance.item_key == "spear"))).scalar_one()
        await s.execute(update(ItemInstance).where(ItemInstance.id == iid).values(durability=20))
    r = await client.post("/api/inventory/repair", json={"slot": forged["slot"]})
    assert r.status_code == 200, r.text
    assert r.json()["paid"] == {"coins": 30, "ingots": 3}
    assert (
        next(s for s in r.json()["inventory"]["inventory"]["slots"] if s["slot"] == forged["slot"])[
            "durability"
        ]
        == 120
    )

    # salvage gives 40% of the inputs back into storage
    wood0 = (await get_village(client))["resources"]["wood"]["amount"]
    r = await client.post("/api/inventory/salvage", json={"slot": forged["slot"]})
    assert r.status_code == 200, r.text
    assert r.json()["returned"] == {"wood": 8, "ore": 4}
    assert (await get_village(client))["resources"]["wood"]["amount"] >= wood0 + 8
    # training gear from signup can't be salvaged
    inv = (await client.get("/api/inventory")).json()["inventory"]["slots"]
    training = next(s for s in inv if s["item"] == "training_spear")
    assert (await client.post("/api/inventory/salvage", json={"slot": training["slot"]})).status_code == 400

    async with st.sessionmaker() as s:
        reasons = {t.reason for t in (await s.execute(select(Transaction))).scalars()}
    assert {"craft.start", "craft.output", "craft.collect", "gear.repair", "gear.salvage"} <= reasons


async def test_preview_names_discovered_combos_and_cancel_refunds(
    client: AsyncClient, player: dict[str, Any], clock: Any
) -> None:
    await place(client, "forge", 27, 12)
    await place(client, "lumber_camp", 30, 12)
    clock.advance(11)
    v = await get_village(client)
    lc = by_key(v, "lumber_camp")[0]
    forge = by_key(v, "forge")[0]
    # move the camp away (combo off), then preview moving it back: now it's named
    r = await client.patch(f"/api/village/buildings/{lc['id']}", json={"x": 33, "y": 25, "rotation": 0})
    assert r.status_code == 200, r.text
    assert r.json()["village"]["combos"] == []
    r = await client.get(f"/api/village/preview?key=lumber_camp&x=30&y=12&move_id={lc['id']}")
    assert r.json()["combos"] == [{"key": "forge_lumber", "name": "Spearwright", "unlocks": ["spear", "bow"]}]
    assert r.json()["mystery"] == 0
    # no combo, no spear
    r = await client.post("/api/crafting/jobs", json={"station_id": forge["id"], "recipe": "spear"})
    assert r.json()["error"]["code"] == "combo_needed"
    # cancelling a smelt refunds 75%
    ore0 = (await get_village(client))["resources"]["ore"]["amount"]
    r = await client.post(
        "/api/crafting/jobs", json={"station_id": forge["id"], "recipe": "ingots", "quantity": 4}
    )
    job = r.json()["job"]
    r = await client.post(f"/api/crafting/jobs/{job['id']}/cancel")
    assert r.status_code == 200 and r.json()["refunded"] == {"ore": 9}
    assert abs(r.json()["village"]["resources"]["ore"]["amount"] - (ore0 - 3)) < 0.01


async def test_brew_potions_at_the_apothecary(
    client: AsyncClient, player: dict[str, Any], st: Any, clock: Any
) -> None:
    """Phase 11: Alchemist + Herb Garden is the Apothecary; potions brew in batches into your bag."""
    from hearthforge.db.models import VillageBuilding
    from tests.integration.test_village import set_resource

    async with st.sessionmaker() as s, s.begin():
        await s.execute(
            update(VillageBuilding).where(VillageBuilding.building_key == "town_hall").values(level=2)
        )
    for k, n in (("wood", 900), ("stone", 900), ("herbs", 300)):
        await set_resource(st, k, n)
    assert (await place(client, "alchemist", 27, 12)).status_code == 200
    assert (await place(client, "herb_garden", 29, 12)).status_code == 200
    clock.advance(11)
    v = await get_village(client)
    assert "alchemist_herb" in v["discovered"]
    alc = by_key(v, "alchemist")[0]
    opts = (await client.get(f"/api/crafting/stations/{alc['id']}")).json()
    brews = {b["recipe"]: b for b in opts["consumables"]}
    assert set(brews) == {"small_healing_potion", "healing_potion", "stamina_potion"}
    assert brews["healing_potion"]["needs_tier"] == 3 and brews["small_healing_potion"]["needs_tier"] is None
    assert [i["recipe"] for i in opts["intermediates"]] == ["potion_base"]

    r = await client.post(
        "/api/crafting/jobs", json={"station_id": alc["id"], "recipe": "healing_potion", "quantity": 1}
    )
    assert r.json()["error"]["code"] == "tier_too_low"
    await set_resource(st, "potion_base", 10)
    r = await client.post(
        "/api/crafting/jobs", json={"station_id": alc["id"], "recipe": "small_healing_potion", "quantity": 3}
    )
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert (await client.post(f"/api/crafting/jobs/{job['id']}/collect")).json()["error"][
        "code"
    ] == "not_ready"
    clock.advance(13)
    r = await client.post(f"/api/crafting/jobs/{job['id']}/collect")
    assert r.status_code == 200, r.text
    assert r.json()["item"]["item"] == "small_healing_potion" and r.json()["item"]["quantity"] == 3
    slots = (await client.get("/api/inventory")).json()["inventory"]["slots"]
    assert any(sl["item"] == "small_healing_potion" and sl["qty"] == 3 for sl in slots)
