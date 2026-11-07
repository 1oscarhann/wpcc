"""Phase 13: the wave director's online rules (P18) and settling a wave in the DB (theft, rewards, report)."""

from __future__ import annotations

import random
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update

from hearthforge.db.models import MonsterWave, Resource, User, Village, VillageBuilding, Wallet
from hearthforge.services import waves
from tests.conftest import signup


class FakeConn:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.sent: list[bytes] = []

    async def send_bytes(self, b: bytes) -> None:
        self.sent.append(b)


async def ready_village(st: Any, uid: uuid.UUID, th: int = 2) -> None:
    async with st.sessionmaker() as s, s.begin():
        vid = (await s.execute(select(Village.id).where(Village.user_id == uid))).scalar_one()
        await s.execute(
            update(VillageBuilding)
            .where(VillageBuilding.village_id == vid, VillageBuilding.building_key == "town_hall")
            .values(level=th)
        )
        await s.execute(update(User).where(User.id == uid).values(tutorial_step=-1))


async def live_waves(st: Any, uid: uuid.UUID) -> list[MonsterWave]:
    async with st.sessionmaker() as s:
        return list((await s.execute(select(MonsterWave).where(MonsterWave.user_id == uid))).scalars())


async def test_waves_wait_for_a_settled_online_player(client: AsyncClient, st: Any, clock: Any) -> None:
    data = await signup(client)
    uid = uuid.UUID(data["user_id"])
    hub = st.village_hub
    waves._next_check.clear()
    conn = FakeConn(str(uid))
    hub.register(conn)
    try:
        # TH1, in the tutorial: never
        await waves.director_tick(st)
        assert await live_waves(st, uid) == []
        await ready_village(st, uid)
        waves._next_check.clear()
        # TH2 but the village is brand new (< 3 h): not yet
        clock.advance(minutes=30)
        await waves.director_tick(st)
        assert await live_waves(st, uid) == []
        # 3 h later, but they only just logged in: not in their first minutes online (P18)
        clock.advance(hours=3)
        waves._next_check.clear()
        hub.unregister(conn)
        clock.advance(minutes=5)
        hub.register(conn)
        await waves.director_tick(st)
        assert await live_waves(st, uid) == []
        clock.advance(st.config.waves.eligible.online_before_announce + 1)
        await waves.director_tick(st)
        (w,) = await live_waves(st, uid)
        assert w.status == "announced" and w.town_hall == 2
        assert (w.starts_at - w.announced_at).total_seconds() == st.config.waves.warning
        assert conn.sent, "the owner hears about it"
        # they log out during the countdown: postponed, never fired
        hub.unregister(conn)
        clock.advance(st.config.waves.eligible.offline_grace + 1)
        await waves.director_tick(st)
        (w,) = await live_waves(st, uid)
        assert w.status == "postponed"
    finally:
        hub.unregister(conn)


async def test_finishing_a_wave_takes_and_gives(client: AsyncClient, st: Any, clock: Any) -> None:
    data = await signup(client)
    uid = uuid.UUID(data["user_id"])
    await ready_village(st, uid, th=3)
    async with st.sessionmaker() as s, s.begin():
        w = await waves.announce(s, st.config, uid, 3, clock.now(), warning=0)
        w.status = "running"
        wid = str(w.id)
        vid = (await s.execute(select(Village.id).where(Village.user_id == uid))).scalar_one()
        await s.execute(
            update(Resource)
            .where(Resource.village_id == vid, Resource.resource_key == "wood")
            .values(amount_milli=1000_000)
        )
        coins0 = (await s.execute(select(Wallet.coins).where(Wallet.user_id == uid))).scalar_one()
    base = {
        "wave_id": wid,
        "owner": str(uid),
        "th": 3,
        "biome": "forest",
        "spawned": 15,
        "killed": 12,
        "guards": 1,
        "guards_left": 1,
        "towers": 0,
        "helpers": [["Pal", 4]],
    }
    # a held wave: 3 of 15 got through (20%) → 2% of the wood goes, the rewards come in
    async with st.sessionmaker() as s, s.begin():
        report = await waves.finish(
            s,
            st.config,
            {**base, "through": 3, "through_frac": 0.2, "won": True},
            clock.now(),
            random.Random(1),
            owner_in_room=False,
        )
    assert report is not None and report["outcome"] == "held" and report["won"]
    assert report["stolen"]["wood"] == 20  # 1000 × 10% × 0.2
    assert report["rewards"]["coins"] == st.config.waves.rewards.coins_per_th * 3
    assert report["helpers"] == [["Pal", 4]] and report["line"]
    async with st.sessionmaker() as s:
        coins = (await s.execute(select(Wallet.coins).where(Wallet.user_id == uid))).scalar_one()
        row = await s.get(MonsterWave, uuid.UUID(wid))
        assert coins == coins0 + report["rewards"]["coins"]
        assert row is not None and row.status == "done" and row.result["outcome"] == "held"
        # finishing twice does nothing
    async with st.sessionmaker() as s, s.begin():
        again = await waves.finish(
            s,
            st.config,
            {**base, "through": 3, "through_frac": 0.2, "won": True},
            clock.now(),
            random.Random(1),
            owner_in_room=False,
        )
    assert again is None
