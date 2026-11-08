"""Phase 15: friends, blocks, mail, gifts, likes, visits and neighbour help (P4 gates).

Friends are global (any realm). Blocks cut every channel both ways: no requests, gifts, visits, likes,
help, quick messages or pings. New accounts can't send gifts, and their likes don't count, until their
avatar reaches `gate.level` or the account is `gate.account_age` old (P4). Gifts travel as mail.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.clock import to_ms
from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError, NotFound
from hearthforge.db.models import (
    Avatar,
    Block,
    BuildingState,
    EventStatus,
    Friendship,
    Gift,
    Mail,
    NeighbourHelp,
    Notification,
    Realm,
    RealmMember,
    ScheduledEvent,
    User,
    Village,
    VillageBuilding,
    VillageLike,
    VillageVisit,
)
from hearthforge.services import events, inventory, ledger, stats
from hearthforge.services.stash import unit_value

SOCIAL_HELP = "social.help"
MAIL_CLAIM = "mail.claim"
GIFT_SEND = "gift.send"


def day_of(now: datetime) -> str:
    return now.date().isoformat()


def _pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (a, b) if str(a) < str(b) else (b, a)


async def user_named(session: AsyncSession, name: str) -> User:
    u = (
        await session.execute(select(User).where(func.lower(User.username) == name.strip().lower()))
    ).scalar_one_or_none()
    if u is None:
        raise NotFound("no_user", "Nobody by that name.")
    return u


async def blocked_between(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    n = (
        await session.execute(
            select(func.count()).where(
                or_(
                    and_(Block.blocker_id == a, Block.blocked_id == b),
                    and_(Block.blocker_id == b, Block.blocked_id == a),
                )
            )
        )
    ).scalar_one()
    return n > 0


async def blocked_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Everyone this player has blocked or been blocked by (both ways are silent)."""
    rows = (
        await session.execute(
            select(Block.blocker_id, Block.blocked_id).where(
                or_(Block.blocker_id == user_id, Block.blocked_id == user_id)
            )
        )
    ).all()
    return {b if a == user_id else a for a, b in rows}


async def are_friends(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    lo, hi = _pair(a, b)
    f = await session.get(Friendship, (lo, hi))
    return f is not None and f.status == "accepted"


async def same_realm(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    rows = (await session.execute(select(RealmMember.realm_id).where(RealmMember.user_id.in_([a, b])))).all()
    return len(rows) == 2 and rows[0][0] == rows[1][0]


async def passes_gate(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime) -> bool:
    """P4: level `gate.level`, or an account at least `gate.account_age` old."""
    g = cfg.social.gate
    row = (
        await session.execute(
            select(User.created_at, Avatar.level)
            .join(Avatar, Avatar.user_id == User.id)
            .where(User.id == user_id)
        )
    ).one_or_none()
    if row is None:
        return False
    created, level = row
    return level >= g.level or (now - created).total_seconds() >= g.account_age


# ── friends ──────────────────────────────────────────────────────────────────
async def friends_view(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, online: set[str]
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                select(Friendship).where(or_(Friendship.user_low == user_id, Friendship.user_high == user_id))
            )
        ).scalars()
    )
    other = {r.user_high if r.user_low == user_id else r.user_low: r for r in rows}
    info: dict[uuid.UUID, Any] = {}
    if other:
        q = (
            select(
                User.id,
                User.username,
                Avatar.level,
                Avatar.title,
                Avatar.appearance,
                Realm.name,
                Village.likes_count,
            )
            .join(Avatar, Avatar.user_id == User.id)
            .join(RealmMember, RealmMember.user_id == User.id, isouter=True)
            .join(Realm, Realm.id == RealmMember.realm_id, isouter=True)
            .join(Village, Village.user_id == User.id, isouter=True)
            .where(User.id.in_(list(other)))
        )
        info = {r[0]: r for r in (await session.execute(q)).all()}

    def entry(uid: uuid.UUID) -> dict[str, Any]:
        r = info.get(uid)
        return {
            "id": str(uid),
            "name": r[1] if r else "?",
            "level": r[2] if r else 1,
            "title": r[3] if r else None,
            "look": r[4] if r else None,
            "realm": r[5] if r else None,
            "likes": r[6] if r else 0,
            "online": str(uid) in online,
        }

    friends, incoming, outgoing = [], [], []
    for uid, f in other.items():
        if f.status == "accepted":
            friends.append(entry(uid))
        elif f.requested_by == user_id:
            outgoing.append(entry(uid))
        else:
            incoming.append(entry(uid))
    friends.sort(key=lambda e: (not e["online"], e["name"].lower()))
    blocked = list(
        (
            await session.execute(
                select(User.id, User.username)
                .join(Block, Block.blocked_id == User.id)
                .where(Block.blocker_id == user_id)
            )
        ).all()
    )
    return {
        "friends": friends,
        "incoming": incoming,
        "outgoing": outgoing,
        "blocked": [{"id": str(i), "name": n} for i, n in blocked],
        "max": cfg.social.friends.max,
    }


async def request(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, name: str, now: datetime
) -> str:
    """Send (or, if they already asked you, accept) a friend request. Returns 'sent' | 'accepted'."""
    target = await user_named(session, name)
    if target.id == user_id:
        raise GameError("self", "That's you!")
    if await blocked_between(session, user_id, target.id):
        raise GameError("blocked", "You can't add them.")
    lo, hi = _pair(user_id, target.id)
    f = await session.get(Friendship, (lo, hi), with_for_update=True)
    if f is not None and f.status == "accepted":
        raise GameError("already_friends", "You're already friends.")
    if f is not None and f.requested_by != user_id:
        return await _accept(session, f, now)
    if f is not None:
        raise GameError("already_asked", "Your request is waiting for them.")
    count = (
        await session.execute(
            select(func.count()).where(
                or_(Friendship.user_low == user_id, Friendship.user_high == user_id),
                Friendship.status == "accepted",
            )
        )
    ).scalar_one()
    if count >= cfg.social.friends.max:
        raise GameError("friends_full", f"You have {cfg.social.friends.max} friends already.")
    session.add(Friendship(user_low=lo, user_high=hi, status="pending", requested_by=user_id, created_at=now))
    me = await session.get(User, user_id)
    session.add(
        Notification(user_id=target.id, kind="friend.request", payload={"from": me.username if me else "?"})
    )
    return "sent"


async def _accept(session: AsyncSession, f: Friendship, now: datetime) -> str:
    f.status, f.accepted_at = "accepted", now
    for uid in (f.user_low, f.user_high):
        await stats.bump(session, uid, {"friend.made": 1})
    session.add(Notification(user_id=f.requested_by, kind="friend.accepted", payload={}))
    return "accepted"


async def respond(
    session: AsyncSession, user_id: uuid.UUID, other: uuid.UUID, accept: bool, now: datetime
) -> str:
    lo, hi = _pair(user_id, other)
    f = await session.get(Friendship, (lo, hi), with_for_update=True)
    if f is None or f.status != "pending" or f.requested_by == user_id:
        raise NotFound("no_request", "No request from them.")
    if accept:
        return await _accept(session, f, now)
    await session.delete(f)
    return "declined"


async def remove(session: AsyncSession, user_id: uuid.UUID, other: uuid.UUID) -> None:
    lo, hi = _pair(user_id, other)
    await session.execute(delete(Friendship).where(Friendship.user_low == lo, Friendship.user_high == hi))


async def block(session: AsyncSession, user_id: uuid.UUID, other: uuid.UUID) -> None:
    if other == user_id:
        raise GameError("self", "That's you!")
    if await session.get(User, other) is None:
        raise NotFound("no_user", "Nobody by that name.")
    await remove(session, user_id, other)
    if await session.get(Block, (user_id, other)) is None:
        session.add(Block(blocker_id=user_id, blocked_id=other))


async def unblock(session: AsyncSession, user_id: uuid.UUID, other: uuid.UUID) -> None:
    await session.execute(delete(Block).where(Block.blocker_id == user_id, Block.blocked_id == other))


# ── mail ─────────────────────────────────────────────────────────────────────
def send_mail(
    session: AsyncSession,
    to: uuid.UUID,
    kind: str,
    sender_name: str,
    items: dict[str, int],
    coins: int = 0,
    note: str = "",
    sender_id: uuid.UUID | None = None,
) -> Mail:
    m = Mail(
        id=uuid.uuid4(),
        user_id=to,
        sender_id=sender_id,
        sender_name=sender_name,
        kind=kind,
        items={k: int(v) for k, v in items.items() if v > 0},
        coins=coins,
        note=note,
    )
    session.add(m)
    session.add(Notification(user_id=to, kind="mail.new", payload={"from": sender_name, "kind": kind}))
    return m


async def mailbox(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime
) -> list[dict[str, Any]]:
    keep = now - timedelta(seconds=cfg.social.mail.keep)
    rows = list(
        (
            await session.execute(
                select(Mail)
                .where(Mail.user_id == user_id, Mail.claimed_at.is_(None), Mail.created_at >= keep)
                .order_by(Mail.created_at.desc())
                .limit(cfg.social.mail.max)
            )
        ).scalars()
    )
    return [
        {
            "id": str(m.id),
            "from": m.sender_name,
            "kind": m.kind,
            "items": m.items,
            "coins": m.coins,
            "note": m.note,
            "at_ms": to_ms(m.created_at),
        }
        for m in rows
    ]


async def claim_mail(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, mail_id: str, now: datetime
) -> dict[str, int]:
    """Into your bag (and coins into your purse). What doesn't fit stays in the parcel."""
    m = (
        await session.execute(
            select(Mail).where(Mail.id == uuid.UUID(mail_id), Mail.user_id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if m is None or m.claimed_at is not None:
        raise NotFound("no_mail", "That parcel is gone.")
    if m.coins:
        wallet = await ledger.lock_wallet(session, user_id)
        await ledger.change_coins(session, wallet, m.coins, MAIL_CLAIM, ref_type="mail", ref_id=str(m.id))
        m.coins = 0
    left = await inventory.grant(session, cfg, user_id, dict(m.items), MAIL_CLAIM) if m.items else {}
    got = {k: v - left.get(k, 0) for k, v in m.items.items() if v - left.get(k, 0) > 0}
    m.items = left
    if not left:
        m.claimed_at = now
    return got


# ── gifts ────────────────────────────────────────────────────────────────────
async def send_gift(
    session: AsyncSession,
    cfg: GameConfig,
    user_id: uuid.UUID,
    to: uuid.UUID,
    items: dict[str, int],
    now: datetime,
) -> Mail:
    g = cfg.social.gifts
    if to == user_id:
        raise GameError("self", "You can't gift yourself.")
    if not await are_friends(session, user_id, to) or await blocked_between(session, user_id, to):
        raise GameError("not_friends", "You can only send gifts to friends.")
    if not await passes_gate(session, cfg, user_id, now):
        raise GameError(
            "too_new",
            f"New accounts can send gifts from avatar level {cfg.social.gate.level} or after a day.",
        )
    items = {k: int(v) for k, v in items.items() if int(v) > 0}
    if not items or len(items) > g.max_stacks:
        raise GameError("bad_gift", f"Pick 1–{g.max_stacks} kinds of things to send.")
    for k in items:
        info = cfg.items.get(k)
        if info is None or not info.stackable:
            raise GameError("bad_gift", "Only stackable goods can be gifted (gear stays with you).")
    day = day_of(now)
    sent_to = (
        await session.execute(
            select(func.count()).where(Gift.from_user == user_id, Gift.to_user == to, Gift.day == day)
        )
    ).scalar_one()
    if sent_to >= g.per_friend_per_day:
        raise GameError("gift_today", "You've already sent them a gift today.")
    value = sum(unit_value(cfg, k) * q for k, q in items.items())
    if value > g.value_cap:
        raise GameError("gift_too_big", f"A gift can be worth at most {g.value_cap} coins (this is {value}).")
    today = (
        await session.execute(
            select(func.coalesce(func.sum(Gift.value), 0)).where(Gift.from_user == user_id, Gift.day == day)
        )
    ).scalar_one()
    if today + value > g.daily_value_cap:
        raise GameError(
            "gift_daily_cap", f"You can give {g.daily_value_cap} coins' worth a day; {today} so far."
        )
    bag = (await inventory.bags(session, user_id, ("inventory",)))["inventory"]
    for k, q in items.items():
        have = sum(s.quantity for s in bag.slots.values() if s.item_key == k and s.instance_id is None)
        if have < q:
            raise GameError("not_enough", f"You only have {have} {cfg.items[k].name}.")
    for k, q in items.items():
        await inventory.take_stack(session, bag, k, q)
        ledger.log_item(session, user_id, k, -q, GIFT_SEND, container_id=bag.c.id)
    me = await session.get(User, user_id)
    name = me.username if me else "A friend"
    session.add(Gift(id=uuid.uuid4(), from_user=user_id, to_user=to, day=day, value=value, contents=items))
    await stats.bump(session, user_id, {"gift.sent": 1})
    return send_mail(session, to, "gift", name, items, note=f"A gift from {name}", sender_id=user_id)


# ── visits, likes, help ──────────────────────────────────────────────────────
async def can_visit(session: AsyncSession, me: uuid.UUID, owner: uuid.UUID) -> bool:
    if me == owner:
        return True
    if await blocked_between(session, me, owner):
        return False
    return await are_friends(session, me, owner) or await same_realm(session, me, owner)


async def visit(
    session: AsyncSession,
    cfg: GameConfig,
    me: uuid.UUID,
    owner: uuid.UUID,
    state: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """The extras a visitor sees on top of the owner's village state (which buildings you can help, etc.)."""
    day = day_of(now)
    if me != owner and await session.get(VillageVisit, (me, owner, day)) is None:
        session.add(VillageVisit(visitor_id=me, owner_id=owner, day=day))
        await stats.bump(session, me, {"visit.any": 1})
        session.add(Notification(user_id=owner, kind="village.visited", payload={}))
    liked = await session.get(VillageLike, (me, owner)) is not None
    helped = {
        str(b)
        for (b,) in (
            await session.execute(
                select(NeighbourHelp.building_id).where(
                    NeighbourHelp.owner_id == owner, NeighbourHelp.day == day
                )
            )
        ).all()
    }
    village = (await session.execute(select(Village).where(Village.user_id == owner))).scalar_one()
    who = (
        await session.execute(
            select(User.username, Avatar.level, Avatar.title, Avatar.appearance)
            .join(Avatar, Avatar.user_id == User.id)
            .where(User.id == owner)
        )
    ).one()
    helps_left = (
        cfg.social.help.per_day
        - (
            await session.execute(
                select(func.count()).where(NeighbourHelp.helper_id == me, NeighbourHelp.day == day)
            )
        ).scalar_one()
    )
    for key in ("coins", "undo", "jobs", "new_discoveries"):
        state.pop(key, None)  # a visitor doesn't see your purse or your workbench
    return {
        "village": state,
        "owner": {"id": str(owner), "name": who[0], "level": who[1], "title": who[2], "look": who[3]},
        "likes": village.likes_count,
        "liked": liked,
        "helped_today": sorted(helped),
        "helps_left": max(0, helps_left),
        "mine": me == owner,
    }


async def like(
    session: AsyncSession, cfg: GameConfig, me: uuid.UUID, owner: uuid.UUID, now: datetime
) -> dict[str, Any]:
    if me == owner:
        raise GameError("self", "You can't like your own village (we know it's lovely).")
    if not await can_visit(session, me, owner):
        raise GameError("cant_visit", "You can't visit that village.")
    if await session.get(VillageLike, (me, owner)) is not None:
        raise GameError("already_liked", "You already like this village.")
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = (
        await session.execute(
            select(func.count()).where(VillageLike.liker_id == me, VillageLike.created_at >= day_start)
        )
    ).scalar_one()
    if today >= cfg.social.likes.per_day:
        raise GameError("likes_today", "That's all your likes for today.")
    counted = await passes_gate(session, cfg, me, now)
    session.add(VillageLike(liker_id=me, owner_id=owner, counted=counted, created_at=now))
    village = (
        await session.execute(select(Village).where(Village.user_id == owner).with_for_update())
    ).scalar_one()
    if counted:
        village.likes_count += 1
        session.add(Notification(user_id=owner, kind="village.liked", payload={}))
    await stats.bump(session, me, {"like.given": 1})
    return {"likes": village.likes_count, "counted": counted}


async def help_building(
    session: AsyncSession, cfg: GameConfig, me: uuid.UUID, building_id: str, now: datetime
) -> dict[str, Any]:
    """Take `help.cut` of the time left off a friend's (or realm-mate's) building timer."""
    hc = cfg.social.help
    b = (
        await session.execute(
            select(VillageBuilding).where(VillageBuilding.id == uuid.UUID(building_id)).with_for_update()
        )
    ).scalar_one_or_none()
    if b is None:
        raise NotFound("no_building", "That building is gone.")
    village = await session.get(Village, b.village_id)
    assert village is not None
    owner = village.user_id
    if owner == me:
        raise GameError("self", "You can't help yourself (but you can hurry up).")
    if not await can_visit(session, me, owner):
        raise GameError("cant_visit", "You can only help friends and realm-mates.")
    if b.state == BuildingState.active or b.work_completes_at is None or b.work_started_at is None:
        raise GameError("nothing_to_help", "That building isn't being built or upgraded.")
    left = (b.work_completes_at - now).total_seconds()
    if left <= 1:
        raise GameError("nothing_to_help", "It's just about done.")
    day = day_of(now)
    if (
        await session.execute(
            select(func.count()).where(NeighbourHelp.building_id == b.id, NeighbourHelp.day == day)
        )
    ).scalar_one():
        raise GameError("helped_today", "Someone already helped this one today.")
    mine = (
        await session.execute(
            select(func.count()).where(NeighbourHelp.helper_id == me, NeighbourHelp.day == day)
        )
    ).scalar_one()
    if mine >= hc.per_day:
        raise GameError("helps_today", "You've helped plenty today. Rest those arms.")
    total = (b.work_completes_at - b.work_started_at).total_seconds()
    room = max(0.0, hc.max_share * total - b.helped_seconds)
    saved = int(min(left * hc.cut, room))
    if saved < 1:
        raise GameError("help_capped", "Helps already took half of this timer off.")
    old_started_ms = to_ms(b.work_started_at) or 0
    b.work_completes_at -= timedelta(seconds=saved)
    b.helped_seconds += saved
    await session.execute(
        update(ScheduledEvent)
        .where(
            ScheduledEvent.dedupe_key == events.building_event_key(str(b.id), b.level + 1, old_started_ms),
            ScheduledEvent.status == EventStatus.pending,
        )
        .values(due_at=b.work_completes_at)
    )
    village.version += 1
    session.add(NeighbourHelp(helper_id=me, building_id=b.id, day=day, owner_id=owner, seconds_saved=saved))
    await stats.bump(session, me, {"help.given": 1})
    me_user = await session.get(User, me)
    session.add(
        Notification(
            user_id=owner,
            kind="village.helped",
            payload={"from": me_user.username if me_user else "?", "key": b.building_key, "seconds": saved},
        )
    )
    if hc.reward_coins:
        wallet = await ledger.lock_wallet(session, me)
        await ledger.change_coins(
            session, wallet, hc.reward_coins, SOCIAL_HELP, ref_type="building", ref_id=str(b.id)
        )
    return {
        "saved": saved,
        "owner": str(owner),
        "completes_at_ms": to_ms(b.work_completes_at),
        "coins": hc.reward_coins,
    }
