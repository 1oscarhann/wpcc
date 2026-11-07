"""Phase 14: villagers arriving and leaving (settled lazily), homes and jobs, and the happiness/beauty view.

Settling walks the clock forward in `arrival.every` steps from where it last stopped: each step a villager
arrives if there's a free bed and the village is happy enough. If happiness stays under `leaving.below`
for `leaving.after`, the newest arrival packs up. Production and food demand change with the headcount
and jobs, so the caller re-applies rates after anything moves (D-097).
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.clock import to_ms
from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError, NotFound
from hearthforge.db.models import Notification, Villager
from hearthforge.domain import economy
from hearthforge.domain import villagers as dom

if TYPE_CHECKING:
    from hearthforge.services.village import Loaded


def _bs(ld: Loaded) -> list[dom.B]:
    return [dom.B(str(b.id), b.building_key, b.x, b.y, b.rotation, b.level) for b in ld.buildings]


def _workers(ld: Loaded) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in ld.villagers:
        if v.job_building_id is not None:
            out[str(v.job_building_id)] = out.get(str(v.job_building_id), 0) + 1
    return out


def measure(cfg: GameConfig, ld: Loaded) -> tuple[dict[str, float], dict[str, float], int]:
    """(happiness parts, beauty parts, housing capacity)."""
    b = _bs(ld)
    cap = dom.housing(cfg, b)
    beauty = dom.beauty(cfg, b, ld.village.debris or [])
    views = [economy.BuildingView(x.key, x.level, "active", x.id) for x in b]
    food = economy.gross_food(cfg, views, _workers(ld))
    h = dom.happiness(
        cfg, beauty["score"], ld.village.size**2, cap, len(ld.villagers), food, dom.tavern_ok(cfg, b)
    )
    return h, beauty, cap


def _newcomer(cfg: GameConfig, ld: Loaded, at: datetime) -> Villager:
    seed = int(uuid.UUID(str(ld.village.id)).int % (2**31)) + len(ld.villagers) * 7919 + int(at.timestamp())
    rng = random.Random(seed)
    names = cfg.villagers.names
    taken = {v.name for v in ld.villagers}
    name = f"{rng.choice(names.first)} {rng.choice(names.last)}"
    for _ in range(8):
        if name not in taken:
            break
        name = f"{rng.choice(names.first)} {rng.choice(names.last)}"
    cr = cfg.avatar.creator
    look = {
        "body": rng.choice(cr.bodies),
        "skin": rng.choice(cr.skin_tones),
        "hair_style": rng.choice(cr.hair_styles),
        "hair_color": rng.choice(cr.hair_colors),
        "eyes": rng.choice(cr.eye_styles),
        "eye_color": rng.choice(cr.eye_colors),
        "outfit": rng.choice(cr.outfits),
        "outfit_color": rng.choice(cr.outfit_colors),
    }
    traits = rng.sample(cfg.villagers.traits, k=min(2, len(cfg.villagers.traits)))[: rng.randint(1, 2)]
    return Villager(
        id=uuid.uuid4(), village_id=ld.village.id, name=name, appearance=look, traits=traits, arrived_at=at
    )


def _open_jobs(cfg: GameConfig, ld: Loaded) -> list[str]:
    """Building ids with a free slot, best first (jobs.priority, guard posts lead)."""
    order = {k: i for i, k in enumerate(cfg.villagers.jobs.priority)}
    used = _workers(ld)
    out = []
    for b in sorted(ld.buildings, key=lambda b: (order.get(b.building_key, 99), str(b.id))):
        free = dom.job_slots(cfg, b.building_key, b.level) - used.get(str(b.id), 0)
        out.extend([str(b.id)] * max(0, free))
    return out


def _home(cfg: GameConfig, ld: Loaded) -> bool:
    """Everyone without a bed gets one if there's room."""
    room: dict[str, int] = {}
    for b in ld.buildings:
        if b.building_key == "house" and b.level >= 1:
            room[str(b.id)] = cfg.buildings["house"].level(b.level).housing or 0
    for v in ld.villagers:
        if v.home_building_id is not None and str(v.home_building_id) in room:
            room[str(v.home_building_id)] -= 1
    changed = False
    for v in ld.villagers:
        if v.home_building_id is None:
            hid = next((h for h, n in room.items() if n > 0), None)
            if hid is None:
                break
            v.home_building_id = uuid.UUID(hid)
            room[hid] -= 1
            changed = True
    return changed


def _arrive(session: AsyncSession, cfg: GameConfig, ld: Loaded, at: datetime) -> Villager:
    v = _newcomer(cfg, ld, at)
    if cfg.villagers.jobs.auto_assign:
        free = _open_jobs(cfg, ld)
        if free:
            v.job_building_id = uuid.UUID(free[0])
    session.add(v)
    ld.villagers.append(v)
    session.add(
        Notification(
            user_id=ld.village.user_id, kind="villager.arrived", payload={"name": v.name, "id": str(v.id)}
        )
    )
    return v


def settle(session: AsyncSession, cfg: GameConfig, ld: Loaded, now: datetime, force: bool = False) -> bool:
    """Bring arrivals, departures, homes, happiness and beauty up to `now`. True if anything moved."""
    vc = cfg.villagers
    village = ld.village
    ids = {str(b.id) for b in ld.buildings}
    changed = False
    for v in ld.villagers:  # buildings that were demolished: SET NULL in the DB, but our objects are stale
        if v.job_building_id is not None and str(v.job_building_id) not in ids:
            v.job_building_id = None
            changed = True
        if v.home_building_id is not None and str(v.home_building_id) not in ids:
            v.home_building_id = None
            changed = True
    h, beauty, cap = measure(cfg, ld)
    if village.villagers_at is None:  # a brand-new village: the first few walk in straight away
        village.villagers_at = now
        for _ in range(max(0, min(vc.arrival.start_with, cap - len(ld.villagers)))):
            _arrive(session, cfg, ld, now)
            changed = True
    else:
        step = timedelta(seconds=vc.arrival.every)
        t = village.villagers_at
        steps = 0
        while t + step <= now and steps < 200:
            t += step
            steps += 1
            if len(ld.villagers) < cap and h["value"] >= vc.arrival.min_happiness:
                _arrive(session, cfg, ld, t)
                changed = True
                h, beauty, cap = measure(cfg, ld)
        if steps >= 200:  # away for days: jump ahead, keeping the phase
            t = now - timedelta(seconds=(now - t).total_seconds() % vc.arrival.every)
        village.villagers_at = t
    if changed:
        h, beauty, cap = measure(cfg, ld)
    if h["value"] < vc.leaving.below and ld.villagers:
        if village.unhappy_since is None:
            village.unhappy_since = now
        elif (now - village.unhappy_since).total_seconds() >= vc.leaving.after:
            gone = ld.villagers.pop()  # the newest arrival packs up first
            session.add(
                Notification(user_id=village.user_id, kind="villager.left", payload={"name": gone.name})
            )
            if gone in session.new:
                session.expunge(gone)
            else:
                session.sync_session.delete(gone)  # settle() is sync; the delete flushes with the request
            village.unhappy_since = now
            changed = True
            h, beauty, cap = measure(cfg, ld)
    elif village.unhappy_since is not None:
        village.unhappy_since = None
        changed = True
    if _home(cfg, ld):
        changed = True
    hv, bv = int(h["value"]), int(round(beauty["score"]))
    if village.happiness != hv or village.beauty != bv:
        village.happiness, village.beauty = hv, bv
        changed = True
    return changed or force


def view(cfg: GameConfig, ld: Loaded, now: datetime) -> dict[str, Any]:
    h, beauty, cap = measure(cfg, ld)
    vc = cfg.villagers
    n = len(ld.villagers)
    next_ms = None
    if ld.village.villagers_at is not None and n < cap and h["value"] >= vc.arrival.min_happiness:
        next_ms = to_ms(ld.village.villagers_at + timedelta(seconds=vc.arrival.every))
    jobs: dict[str, dict[str, int]] = {}
    used = _workers(ld)
    for b in ld.buildings:
        slots = dom.job_slots(cfg, b.building_key, b.level)
        if slots:
            jobs[str(b.id)] = {"slots": slots, "workers": used.get(str(b.id), 0)}
    leave_ms = None
    if ld.village.unhappy_since is not None:
        leave_ms = to_ms(ld.village.unhappy_since + timedelta(seconds=vc.leaving.after))
    return {
        "villagers": [
            {
                "id": str(v.id),
                "name": v.name,
                "look": v.appearance,
                "traits": v.traits,
                "job": str(v.job_building_id) if v.job_building_id else None,
                "home": str(v.home_building_id) if v.home_building_id else None,
                "arrived_ms": to_ms(v.arrived_at),
            }
            for v in ld.villagers
        ],
        "happiness": {**h, "mood": dom.mood(cfg, h), "leave_at_ms": leave_ms},
        "beauty": beauty,
        "housing": {"cap": cap, "used": n},
        "next_arrival_ms": next_ms,
        "job_slots": jobs,
        "food_demand": n * vc.food_per_villager,
    }


async def assign(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    villager_id: str,
    building_id: str | None,
    now: datetime,
) -> Loaded:
    from hearthforge.services import village as village_svc

    ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    v = next((x for x in ld.villagers if str(x.id) == villager_id), None)
    if v is None:
        raise NotFound("no_villager", "That villager doesn't live here.")
    if building_id is None:
        v.job_building_id = None
    else:
        b = next((x for x in ld.buildings if str(x.id) == building_id), None)
        if b is None:
            raise NotFound("no_building", "That building isn't in your village.")
        slots = dom.job_slots(cfg, b.building_key, b.level)
        if slots == 0:
            raise GameError("no_jobs", f"Nobody can work at the {cfg.buildings[b.building_key].cfg.name}.")
        others = sum(1 for x in ld.villagers if x is not v and x.job_building_id == b.id)
        if others >= slots:
            raise GameError("job_full", "Every spot there is taken. Upgrade it for more.")
        v.job_building_id = b.id
    village_svc._apply_rates(cfg, ld)
    village_svc.touch(ld, now)
    return ld
