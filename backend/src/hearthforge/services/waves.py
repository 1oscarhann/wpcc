"""Phase 13: the wave director (P18 online rules) and wave outcomes (theft, rewards, the report).

The director runs in the API process every few seconds. For each online village that's due it writes an
`announced` wave with a 10 minute warning. When the warning runs out it starts the wave in the realm room
(creating the room if nobody's in Avatar Mode yet). Owners who go offline before it starts get it
postponed, never fired (P18). The room hands finished waves back through its flush; `finish` settles the
village, takes what got stolen, pays the rewards and writes the report.
"""

from __future__ import annotations

import logging
import math
import random
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.clock import to_ms
from hearthforge.config.loader import GameConfig
from hearthforge.db.models import MonsterWave, RealmMember, User, Village, VillageBuilding
from hearthforge.domain.resources import MILLI
from hearthforge.services import inventory, ledger
from hearthforge.services import village as village_svc
from hearthforge.services.tutorial import in_tutorial

if TYPE_CHECKING:
    from hearthforge.state import AppState

log = logging.getLogger("hearthforge.waves")

WAVE_STOLEN = "wave.stolen"
WAVE_REWARD = "wave.reward"

_next_check: dict[str, datetime] = {}  # user → don't look again before (cheap eligibility cache)


async def eligible(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime
) -> tuple[bool, datetime, int]:
    """(due?, when to look again, Town Hall level)."""
    el = cfg.waves.eligible
    user = await session.get(User, user_id)
    if user is None or in_tutorial(user):
        return False, now + timedelta(seconds=60), 0
    village = (await session.execute(select(Village).where(Village.user_id == user_id))).scalar_one_or_none()
    if village is None:
        return False, now + timedelta(hours=1), 0
    th = (
        await session.execute(
            select(func.max(VillageBuilding.level)).where(
                VillageBuilding.village_id == village.id, VillageBuilding.building_key == "town_hall"
            )
        )
    ).scalar_one_or_none() or 1
    if th < el.min_town_hall:
        return False, now + timedelta(seconds=60), th
    last = (
        await session.execute(
            select(func.max(MonsterWave.ended_at)).where(
                MonsterWave.user_id == user_id, MonsterWave.status == "done"
            )
        )
    ).scalar_one_or_none()
    since = last or village.created_at
    due_at = since + timedelta(seconds=el.since_last)
    if now < due_at:
        return False, due_at, th
    return True, now, th


async def announce(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    th: int,
    now: datetime,
    warning: float | None = None,
) -> MonsterWave:
    realm_id = (
        await session.execute(select(RealmMember.realm_id).where(RealmMember.user_id == user_id))
    ).scalar_one()
    w = MonsterWave(
        id=uuid.uuid4(),
        user_id=user_id,
        realm_id=realm_id,
        status="announced",
        town_hall=th,
        announced_at=now,
        starts_at=now + timedelta(seconds=cfg.waves.warning if warning is None else warning),
    )
    session.add(w)
    await session.flush()
    return w


def view(w: MonsterWave | None) -> dict[str, Any] | None:
    if w is None:
        return None
    return {
        "id": str(w.id),
        "status": w.status,
        "town_hall": w.town_hall,
        "starts_at_ms": to_ms(w.starts_at),
        "ended_at_ms": to_ms(w.ended_at),
        "result": w.result,
    }


async def current(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    live = (
        await session.execute(
            select(MonsterWave)
            .where(MonsterWave.user_id == user_id, MonsterWave.status.in_(("announced", "running")))
            .order_by(MonsterWave.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    history = list(
        (
            await session.execute(
                select(MonsterWave)
                .where(MonsterWave.user_id == user_id, MonsterWave.status == "done")
                .order_by(MonsterWave.ended_at.desc())
                .limit(5)
            )
        ).scalars()
    )
    return {"current": view(live), "history": [view(w) for w in history]}


# ── the director ─────────────────────────────────────────────────────────────
async def director_loop(st: AppState) -> None:
    import asyncio

    while True:
        await asyncio.sleep(st.config.waves.director_every)
        try:
            await director_tick(st)
        except Exception:  # noqa: BLE001 - keep directing
            log.exception("wave director tick failed")


async def director_tick(st: AppState) -> None:
    cfg = st.config
    hub = st.village_hub
    rooms = st.rooms
    if hub is None or rooms is None:
        return
    now = st.clock.now()
    notes: list[tuple[str, dict[str, Any]]] = []
    async with st.sessionmaker() as s, s.begin():
        live = list(
            (
                await s.execute(
                    select(MonsterWave)
                    .where(MonsterWave.status.in_(("announced", "running")))
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        busy = set()
        for w in live:
            uid = str(w.user_id)
            busy.add(uid)
            online = hub.online_for(uid) is not None
            if w.status == "announced":
                if not online:  # P18: logged out during the countdown → postponed, never fired
                    w.status, w.ended_at = "postponed", now
                    rooms.announced.pop(uid, None)
                elif w.starts_at <= now:
                    room = await rooms.room_for_realm(w.realm_id)
                    err = room.defence.start(str(w.id), uid, w.town_hall) if room is not None else "no_room"
                    if err is None:
                        rooms.announced[uid] = to_ms(w.starts_at) or 0
                        w.status = "running"
                        notes.append((uid, {"status": "running", "id": str(w.id)}))
                    else:
                        log.warning("wave %s couldn't start: %s", w.id, err)
                        w.status, w.ended_at = "postponed", now
            elif w.status == "running":
                room = rooms.rooms.get(w.realm_id)
                lost = room is None or (
                    uid not in room.defence.runs
                    and all(r["wave_id"] != str(w.id) for r in room.defence.results)
                )
                if lost and (now - w.starts_at).total_seconds() > cfg.waves.max_duration + 120:
                    w.status, w.ended_at = "postponed", now  # the room went away mid-wave (restart)
        # realm bosses: wake the next one in every realm someone's online in (Phase 13)
        from hearthforge.db.models import Realm
        from hearthforge.services import bosses as boss_svc

        uids = [uuid.UUID(u) for u in hub.online()]
        if uids:
            realms = (
                await s.execute(
                    select(Realm.id, Realm.seed)
                    .join(RealmMember, RealmMember.realm_id == Realm.id)
                    .where(RealmMember.user_id.in_(uids))
                    .distinct()
                )
            ).all()
            for rid, seed in realms:
                await boss_svc.ensure(s, cfg, rid, seed, now)
        on_for = cfg.waves.eligible.online_before_announce
        for uid in sorted(hub.online()):
            if uid in busy or _next_check.get(uid, now) > now:
                continue
            secs = hub.online_for(uid)
            if secs is None or secs < on_for:
                continue
            ok, again, th = await eligible(s, cfg, uuid.UUID(uid), now)
            if not ok:
                _next_check[uid] = again
                continue
            w = await announce(s, cfg, uuid.UUID(uid), th, now)
            rooms.announced[uid] = to_ms(w.starts_at) or 0
            notes.append((uid, {"status": "announced", "id": str(w.id), "starts_at_ms": to_ms(w.starts_at)}))
    for uid, payload in notes:
        await hub.notify([uid], "wave", payload)


# ── the outcome ──────────────────────────────────────────────────────────────
async def finish(
    session: AsyncSession,
    cfg: GameConfig,
    result: dict[str, Any],
    now: datetime,
    rng: random.Random,
    *,
    owner_in_room: bool,
) -> dict[str, Any] | None:
    """Settle a finished wave: theft, rewards, the report. Returns the report (None if already done)."""
    w = (
        await session.execute(
            select(MonsterWave).where(MonsterWave.id == uuid.UUID(result["wave_id"])).with_for_update()
        )
    ).scalar_one_or_none()
    if w is None or w.status != "running":
        return None
    wc = cfg.waves
    ld = await village_svc.load_locked(session, user_id=w.user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    frac = wc.steal.max_fraction * float(result["through_frac"])
    stolen: dict[str, int] = {}
    for rk in wc.steal.resources:
        r = ld.resources.get(rk)
        if r is None or frac <= 0:
            continue
        amount = math.floor(r.amount_milli * frac / MILLI)
        if amount <= 0:
            continue
        r.amount_milli -= amount * MILLI
        stolen[rk] = amount
        ledger.log_resource(
            session,
            w.user_id,
            ld.village.realm_id,
            rk,
            -amount * MILLI,
            WAVE_STOLEN,
            ref_type="wave",
            ref_id=str(w.id),
        )
    rewards: dict[str, int] = {}
    rare: dict[str, int] = {}
    th = min(5, max(2, w.town_hall))
    if result["won"]:
        coins = wc.rewards.coins_per_th * th
        assert ld.wallet is not None
        await ledger.change_coins(session, ld.wallet, coins, WAVE_REWARD, ref_type="wave", ref_id=str(w.id))
        rewards["coins"] = coins
        for rk, qty in wc.rewards.bundle.get(th, {}).items():
            if rk in ld.resources:
                ld.resources[rk].amount_milli += qty * MILLI  # rewards may exceed the cap; never lost
                rewards[rk] = rewards.get(rk, 0) + qty
                ledger.log_resource(
                    session,
                    w.user_id,
                    ld.village.realm_id,
                    rk,
                    qty * MILLI,
                    WAVE_REWARD,
                    ref_type="wave",
                    ref_id=str(w.id),
                )
        item = wc.rewards.rare.get(result["biome"])
        if item and rng.random() < wc.rewards.rare_chance:
            rare[item] = 1
            if not owner_in_room:  # in the room the bag lives in memory: the room drops it at their feet
                left = await inventory.grant(session, cfg, w.user_id, rare, WAVE_REWARD)
                for k, q in left.items():  # bag full: the storehouse keeps it as a resource if it is one
                    if k in ld.resources:
                        ld.resources[k].amount_milli += q * MILLI
    through = int(result["through"])
    outcome = "flawless" if through == 0 else "held" if result["won"] else "overrun"
    pool = getattr(wc.report_lines, outcome)
    res_name = "bread"
    if stolen:
        top = max(stolen, key=lambda k: stolen[k])
        res_name = cfg.resources.resources[top].name.lower()
    line = rng.choice(pool).replace("{res}", res_name)
    report = {
        "id": str(w.id),
        "outcome": outcome,
        "won": bool(result["won"]),
        "line": line,
        "spawned": result["spawned"],
        "killed": result["killed"],
        "through": through,
        "stolen": stolen,
        "rewards": rewards,
        "rare": rare,
        "guards": result["guards"],
        "guards_left": result["guards_left"],
        "towers": result["towers"],
        "helpers": result["helpers"],
    }
    w.status, w.ended_at, w.result = "done", now, report
    village_svc.touch(ld, now)
    _next_check.pop(str(w.user_id), None)
    return report
