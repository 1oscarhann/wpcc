"""Phase 16: skills, quests, achievements, titles, the login calendar and the collection book.

Quests and achievements read the per-player counters in user_stats. Daily and weekly quests snapshot the
counter when they're handed out (`base`) and count from there; main quests and achievements read totals.
XP and coins are granted here; if the player is in the world, XP goes through the room (it owns the
avatar's level and XP while they play) so nothing gets overwritten on its next save.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.clock import to_ms
from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError, NotFound
from hearthforge.db.models import (
    Avatar,
    Discovery,
    DiscoveryKind,
    LoginReward,
    Notification,
    QuestProgress,
    UserAchievement,
    UserCosmetic,
    UserStat,
    Village,
    VillageBuilding,
    Villager,
)
from hearthforge.domain import skills as skills_dom
from hearthforge.domain.resources import MILLI
from hearthforge.services import inventory, ledger, stats
from hearthforge.sim.stats import add_xp

if TYPE_CHECKING:
    from hearthforge.state import AppState

QUEST_REWARD = "quest.reward"
ACHIEVEMENT_REWARD = "achievement.reward"
CALENDAR_REWARD = "calendar.reward"
SKILL_RESPEC = "skill.respec"


async def perks_of(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> dict[str, float]:
    row = (await session.execute(select(Avatar.skills, Avatar.pet).where(Avatar.user_id == user_id))).first()
    return skills_dom.with_pet(cfg, (row[0] if row else None) or {}, row[1] if row else None)


async def grant_xp(st: AppState, session: AsyncSession, user_id: uuid.UUID, amount: int) -> None:
    """XP from a quest or achievement. In the world, the room owns your XP; otherwise write it here."""
    if amount <= 0:
        return
    found = st.rooms.find(user_id) if st.rooms is not None else None
    if found is not None:
        room, p = found
        room.grant_xp(p, amount)
        return
    av = (
        await session.execute(select(Avatar).where(Avatar.user_id == user_id).with_for_update())
    ).scalar_one()
    level, xp, _gained = add_xp(st.config, av.level, av.xp, amount)
    av.level, av.xp = level, xp


async def _coins(session: AsyncSession, user_id: uuid.UUID, amount: int, reason: str, ref: str) -> None:
    if amount > 0:
        wallet = await ledger.lock_wallet(session, user_id)
        await ledger.change_coins(session, wallet, amount, reason, ref_type="progress", ref_id=ref)


async def _title(session: AsyncSession, user_id: uuid.UUID, title: str | None, source: str) -> None:
    if title and await session.get(UserCosmetic, (user_id, f"title:{title}")) is None:
        session.add(UserCosmetic(user_id=user_id, cosmetic_key=f"title:{title}", source=source))


# ── skills ───────────────────────────────────────────────────────────────────
async def skills_view(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> dict[str, Any]:
    av = (await session.execute(select(Avatar).where(Avatar.user_id == user_id))).scalar_one()
    skills = av.skills or {}
    total = skills_dom.points_total(cfg, av.level)
    return {
        "level": av.level,
        "points": total,
        "spent": skills_dom.spent(skills),
        "ranks": skills,
        "respec_cost": skills_dom.respec_cost(cfg, av.level, av.respecs),
        "perks": skills_dom.perks(cfg, skills),
        "can": {
            k: skills_dom.learn_error(cfg, skills, av.level, k)
            for br in cfg.skills.branches.values()
            for k in br.nodes
        },
    }


async def learn(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, key: str) -> None:
    av = (
        await session.execute(select(Avatar).where(Avatar.user_id == user_id).with_for_update())
    ).scalar_one()
    skills = dict(av.skills or {})
    err = skills_dom.learn_error(cfg, skills, av.level, key)
    if err is not None:
        msg = {
            "unknown_skill": "No such skill.",
            "maxed": "That skill is maxed out.",
            "no_points": "No skill points left. Level up for more.",
            "locked": "Learn the skills before it first.",
        }[err]
        raise GameError(err, msg)
    skills[key] = int(skills.get(key, 0)) + 1
    av.skills = skills


async def respec(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> int:
    av = (
        await session.execute(select(Avatar).where(Avatar.user_id == user_id).with_for_update())
    ).scalar_one()
    if not av.skills:
        raise GameError("nothing_to_reset", "You haven't learned anything yet.")
    cost = skills_dom.respec_cost(cfg, av.level, av.respecs)
    if cost:
        wallet = await ledger.lock_wallet(session, user_id)
        await ledger.change_coins(session, wallet, -cost, SKILL_RESPEC, ref_type="progress", ref_id="respec")
    av.skills = {}
    av.respecs += 1
    return cost


# ── quests ───────────────────────────────────────────────────────────────────
def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _pick(cfg: GameConfig, period: str, user_id: uuid.UUID, start: str, level: int) -> list[Any]:
    qp = getattr(cfg.progression.quests, period)
    pool = [q for q in qp.pool if q.min_level <= level] or list(qp.pool)
    rng = random.Random(f"{user_id}:{period}:{start}")
    return rng.sample(pool, k=min(qp.count, len(pool)))


async def _stat_values(session: AsyncSession, user_id: uuid.UUID, keys: set[str]) -> dict[str, int]:
    out = await stats.read(session, user_id, keys) if keys else {}
    if "discover.combo" in keys:  # counted from the discoveries themselves
        out["discover.combo"] = (
            await session.execute(
                select(func.count()).where(
                    Discovery.user_id == user_id, Discovery.kind == DiscoveryKind.combo
                )
            )
        ).scalar_one()
    return out


async def _village_numbers(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    v = (await session.execute(select(Village.id).where(Village.user_id == user_id))).scalar_one_or_none()
    if v is None:
        return 1, 0
    th = (
        await session.execute(
            select(func.max(VillageBuilding.level)).where(
                VillageBuilding.village_id == v, VillageBuilding.building_key == "town_hall"
            )
        )
    ).scalar_one_or_none() or 1
    n = (await session.execute(select(func.count()).where(Villager.village_id == v))).scalar_one()
    return th, n


async def quests_view(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime
) -> dict[str, Any]:
    """Hand out today's and this week's quests if they're new, then report progress on everything."""
    level = (await session.execute(select(Avatar.level).where(Avatar.user_id == user_id))).scalar_one()
    today = now.date()
    periods = {"daily": today.isoformat(), "weekly": _week_start(today).isoformat()}
    rows = {
        (r.quest_key, r.period_start): r
        for r in (
            await session.execute(
                select(QuestProgress).where(
                    QuestProgress.user_id == user_id,
                    QuestProgress.period_start.in_([*periods.values(), "main"]),
                )
            )
        ).scalars()
    }
    picks: dict[str, list[Any]] = {}
    for period, start in periods.items():
        # once a board is handed out it stays put for the period, even if you level past a quest's
        # min_level mid-day (re-picking would swap quests and wipe their progress)
        pool = {q.key: q for q in getattr(cfg.progression.quests, period).pool}
        have = [pool[k] for (k, ps), r in rows.items() if ps == start and r.period == period and k in pool]
        picks[period] = sorted(have or _pick(cfg, period, user_id, start, level), key=lambda q: q.key)
    want_stats = {q.stat for qs in picks.values() for q in qs}
    want_stats |= {q.stat for q in cfg.progression.quests.main if q.stat}
    values = await _stat_values(session, user_id, want_stats)
    out: dict[str, Any] = {"daily": [], "weekly": [], "main": None, "resets": {}}
    for period, start in periods.items():
        for q in picks[period]:
            row = rows.get((q.key, start))
            if row is None:  # first look this period: snapshot the counter
                row = QuestProgress(
                    user_id=user_id,
                    quest_key=q.key,
                    period_start=start,
                    period=period,
                    stat=q.stat,
                    base=values.get(q.stat, 0),
                    target=q.target,
                )
                session.add(row)
            progress = max(0, values.get(q.stat, 0) - row.base)
            out[period].append(
                {
                    "key": q.key,
                    "title": q.title,
                    "progress": min(progress, row.target),
                    "target": row.target,
                    "done": progress >= row.target,
                    "claimed": row.claimed_at is not None,
                    "reward": quest_reward(cfg, period, level),
                }
            )
    nxt_day = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
    nxt_week = datetime.combine(
        _week_start(today) + timedelta(days=7), datetime.min.time(), tzinfo=now.tzinfo
    )
    out["resets"] = {"daily_ms": to_ms(nxt_day), "weekly_ms": to_ms(nxt_week)}
    # the main questline: the first one you haven't claimed
    th, villagers = await _village_numbers(session, user_id)
    for i, mq in enumerate(cfg.progression.quests.main):
        row = rows.get((mq.key, "main"))
        if row is not None and row.claimed_at is not None:
            continue
        if mq.stat:
            progress, target = values.get(mq.stat, 0), mq.target
        elif mq.town_hall:
            progress, target = th, mq.town_hall
        else:
            progress, target = villagers, mq.villagers or 1
        out["main"] = {
            "key": mq.key,
            "index": i,
            "total": len(cfg.progression.quests.main),
            "title": mq.title,
            "progress": min(progress, target),
            "target": target,
            "done": progress >= target,
            "reward": mq.reward.model_dump(),
        }
        break
    return out


def quest_reward(cfg: GameConfig, period: str, level: int) -> dict[str, Any]:
    r = getattr(cfg.progression.quests, period).rewards
    lo, hi = r.coins
    return {"xp": r.xp_base + r.xp_per_level * level, "coins": [lo, hi], "token": r.token}


async def claim_quest(
    st: AppState, session: AsyncSession, user_id: uuid.UUID, period: str, key: str, now: datetime
) -> dict[str, Any]:
    cfg = st.config
    view = await quests_view(session, cfg, user_id, now)
    await session.flush()
    level = (await session.execute(select(Avatar.level).where(Avatar.user_id == user_id))).scalar_one()
    if period == "main":
        mq = view["main"]
        if mq is None or mq["key"] != key:
            raise NotFound("no_quest", "That isn't your current main quest.")
        if not mq["done"]:
            raise GameError("not_done", "Not finished yet.")
        row = await session.get(QuestProgress, (user_id, key, "main"))
        if row is None:
            row = QuestProgress(
                user_id=user_id, quest_key=key, period_start="main", period="main", stat="", base=0, target=1
            )
            session.add(row)
        row.claimed_at = now
        rw = mq["reward"]
        await grant_xp(st, session, user_id, rw["xp"])
        await _coins(session, user_id, rw["coins"], QUEST_REWARD, f"main:{key}")
        await _title(session, user_id, rw.get("title"), f"quest:{key}")
        await stats.bump(session, user_id, {"quest.main": 1})
        return {"xp": rw["xp"], "coins": rw["coins"], "title": rw.get("title")}
    if period not in ("daily", "weekly"):
        raise NotFound("no_quest", "No such quest.")
    q = next((x for x in view[period] if x["key"] == key), None)
    if q is None:
        raise NotFound("no_quest", "That quest isn't on your board.")
    if not q["done"]:
        raise GameError("not_done", "Not finished yet.")
    if q["claimed"]:
        raise GameError("claimed", "Already claimed.")
    start = now.date().isoformat() if period == "daily" else _week_start(now.date()).isoformat()
    row = await session.get(QuestProgress, (user_id, key, start), with_for_update=True)
    assert row is not None
    row.claimed_at = now
    r = quest_reward(cfg, period, level)
    coins = random.Random(f"{user_id}:{key}:{start}").randint(*r["coins"])
    await grant_xp(st, session, user_id, r["xp"])
    await _coins(session, user_id, coins, QUEST_REWARD, f"{period}:{key}")
    if r["token"]:
        await inventory.grant(session, cfg, user_id, {"cosmetic_token": r["token"]}, QUEST_REWARD)
    await stats.bump(session, user_id, {f"quest.{period}": 1})
    return {"xp": r["xp"], "coins": coins, "token": r["token"]}


# ── achievements and titles ──────────────────────────────────────────────────
async def achievements_view(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime
) -> dict[str, Any]:
    """Unlocks anything newly reached (with a notification) and lists them all."""
    defs = cfg.progression.achievements
    values = await _stat_values(session, user_id, {a.stat for a in defs.values()})
    have = {
        r.achievement_key: r
        for r in (
            await session.execute(select(UserAchievement).where(UserAchievement.user_id == user_id))
        ).scalars()
    }
    out = []
    for key, a in defs.items():
        v = values.get(a.stat, 0)
        row = have.get(key)
        if row is None and v >= a.target:
            row = UserAchievement(user_id=user_id, achievement_key=key, unlocked_at=now)
            session.add(row)
            session.add(
                Notification(user_id=user_id, kind="achievement", payload={"key": key, "name": a.name})
            )
        out.append(
            {
                "key": key,
                "name": a.name,
                "desc": a.desc,
                "progress": min(v, a.target),
                "target": a.target,
                "unlocked": row is not None,
                "claimed": row is not None and row.claimed_at is not None,
                "title": a.title,
                "coins": a.coins,
            }
        )
    titles = sorted(
        k.removeprefix("title:")
        for (k,) in (
            await session.execute(
                select(UserCosmetic.cosmetic_key).where(
                    UserCosmetic.user_id == user_id, UserCosmetic.cosmetic_key.like("title:%")
                )
            )
        ).all()
    )
    current = (
        await session.execute(select(Avatar.title).where(Avatar.user_id == user_id))
    ).scalar_one_or_none()
    return {"achievements": out, "titles": titles, "title": current}


async def claim_achievement(
    st: AppState, session: AsyncSession, user_id: uuid.UUID, key: str, now: datetime
) -> dict[str, Any]:
    await achievements_view(session, st.config, user_id, now)
    await session.flush()
    row = await session.get(UserAchievement, (user_id, key), with_for_update=True)
    if row is None:
        raise GameError("locked", "Not unlocked yet.")
    if row.claimed_at is not None:
        raise GameError("claimed", "Already claimed.")
    a = st.config.progression.achievements[key]
    row.claimed_at = now
    await _coins(session, user_id, a.coins, ACHIEVEMENT_REWARD, key)
    await _title(session, user_id, a.title, f"achievement:{key}")
    return {"coins": a.coins, "title": a.title}


async def set_title(session: AsyncSession, user_id: uuid.UUID, title: str | None) -> None:
    if title is not None and await session.get(UserCosmetic, (user_id, f"title:{title}")) is None:
        raise GameError("no_title", "You haven't earned that title.")
    av = (
        await session.execute(select(Avatar).where(Avatar.user_id == user_id).with_for_update())
    ).scalar_one()
    av.title = title


# ── the login calendar ───────────────────────────────────────────────────────
async def calendar_view(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime
) -> dict[str, Any]:
    row = await session.get(LoginReward, user_id)
    day = row.calendar_day if row else 0
    claimed_today = row is not None and row.last_claim_day == now.date().isoformat()
    days = cfg.progression.calendar.days
    return {
        "day": day % len(days),  # the next one to claim (0-based)
        "round": day // len(days),
        "claimed_today": claimed_today,
        "days": [d.model_dump() for d in days],
    }


async def claim_calendar(
    st: AppState, session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> dict[str, Any]:
    cfg = st.config
    row = await session.get(LoginReward, user_id, with_for_update=True)
    if row is None:
        row = LoginReward(user_id=user_id, calendar_day=0, extra={})
        session.add(row)
    today = now.date().isoformat()
    if row.last_claim_day == today:
        raise GameError("claimed_today", "Come back tomorrow for the next one.")
    days = cfg.progression.calendar.days
    d = days[row.calendar_day % len(days)]
    await _coins(session, user_id, d.coins, CALENDAR_REWARD, f"day:{row.calendar_day}")
    if d.items:
        left = await inventory.grant(session, cfg, user_id, dict(d.items), CALENDAR_REWARD)
        if left:  # bag full: it waits in the mail
            from hearthforge.services import social

            social.send_mail(session, user_id, "system", "Login calendar", left, note="Your calendar reward")
    if d.res:
        from hearthforge.services import village as village_svc

        ld = await village_svc.load_locked(session, user_id=user_id)
        village_svc.settle_village(session, cfg, ld, now)
        for k, q in d.res.items():
            if k in ld.resources:
                ld.resources[k].amount_milli += q * MILLI  # gifts may exceed the cap; never lost
                ledger.log_resource(session, user_id, ld.village.realm_id, k, q * MILLI, CALENDAR_REWARD)
        village_svc.touch(ld, now)
    await _title(session, user_id, d.title, f"login_day:{row.calendar_day + 1}")
    row.calendar_day += 1
    row.last_claim_day = today
    return {"day": row.calendar_day, **d.model_dump()}


# ── the collection book ──────────────────────────────────────────────────────
async def collection(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> dict[str, Any]:
    """What you've found so far: monsters, bosses, materials, gear, brews, combos, lore."""
    st = {
        k: int(v)
        for k, v in (
            await session.execute(
                select(UserStat.stat_key, UserStat.value).where(UserStat.user_id == user_id)
            )
        ).all()
    }
    disc = list(
        (
            await session.execute(select(Discovery.kind, Discovery.key).where(Discovery.user_id == user_id))
        ).all()
    )
    boss_enemies = {b.enemy for b in cfg.bosses.bosses.values()} | {cfg.dungeons.boss.enemy}
    bestiary = [
        {"key": k, "name": e.name, "count": st.get(f"kill.{k}", 0), "boss": k in boss_enemies}
        for k, e in cfg.enemies.enemies.items()
        if k not in ("storm_elemental", "seedling")
    ]
    materials = [
        {"key": k, "name": i.name, "icon": i.icon, "count": st.get(f"gather.{k}", 0)}
        for k, i in cfg.items.items()
        if i.category in ("material", "rare_material")
    ]
    gear = [
        {"key": k, "name": cfg.items[k].name, "icon": cfg.items[k].icon, "count": st.get(f"forge.{k}", 0)}
        for k in cfg.recipes.gear
        if k in cfg.items
    ]
    brews = [
        {"key": k, "name": cfg.items[k].name, "icon": cfg.items[k].icon, "count": st.get(f"brew.{k}", 0)}
        for k in cfg.recipes.consumables
        if k in cfg.items
    ]
    fish = [
        {"key": k, "name": sp.name, "icon": f"icon.fish_{k}", "count": st.get(f"fish.{k}", 0)}
        for k, sp in cfg.fishing.species.items()
    ]
    combos = sorted(k for kind, k in disc if kind == DiscoveryKind.combo)
    lore = sorted(k for kind, k in disc if kind == DiscoveryKind.lore)
    trophies = [
        {
            "key": b.loot.trophy,
            "name": cfg.items[b.loot.trophy].name,
            "icon": cfg.items[b.loot.trophy].icon,
            "boss": b.name,
            "count": st.get(f"kill.{b.enemy}", 0),
        }
        for b in cfg.bosses.bosses.values()
    ]
    return {
        "bestiary": bestiary,
        "materials": materials,
        "gear": gear,
        "brews": brews,
        "trophies": trophies,
        "fish": fish,
        "combos": {"found": combos, "total": len(cfg.combos.combos)},
        "lore": {"found": len(lore), "keys": lore},
    }
