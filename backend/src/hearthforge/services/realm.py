"""Realms (Phase 9): found, join by invite code, leave, kick, transfer, rename, trust.

Every player is always in exactly one realm. You start in a private solo realm on plot 0. Founding a
realm turns that solo realm into a shared one with an invite code. Joining moves your whole village
to a free plot in the other realm (buildings are plot-frame relative, so nothing moves on the inside)
and archives your empty solo realm. Leaving (or being kicked) brings back your archived solo realm, or
a fresh one. Lock order: realm row → member rows → village.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import Forbidden, GameError, NotFound
from hearthforge.core.profanity import is_profane
from hearthforge.db.base import new_id
from hearthforge.db.models import (
    Avatar,
    AvatarLocation,
    Container,
    ContainerKind,
    Realm,
    RealmMember,
    RealmRole,
    User,
    Village,
)
from hearthforge.services import activity

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


async def my_member(
    session: AsyncSession, user_id: uuid.UUID, lock: bool = False
) -> tuple[Realm, RealmMember]:
    q = (
        select(Realm, RealmMember)
        .join(RealmMember, RealmMember.realm_id == Realm.id)
        .where(RealmMember.user_id == user_id)
    )
    if lock:
        q = q.with_for_update()
    row = (await session.execute(q)).one_or_none()
    if row is None:
        raise NotFound("no_realm", "You're not in a realm.")
    return row[0], row[1]


async def members(session: AsyncSession, realm_id: uuid.UUID) -> list[tuple[RealmMember, User, Avatar]]:
    rows = await session.execute(
        select(RealmMember, User, Avatar)
        .join(User, User.id == RealmMember.user_id)
        .join(Avatar, Avatar.user_id == User.id)
        .where(RealmMember.realm_id == realm_id)
        .order_by(RealmMember.plot_index)
    )
    return [(m, u, a) for m, u, a in rows.all()]


def _check_name(cfg: GameConfig, name: str) -> str:
    name = " ".join(name.split())
    r = cfg.social.realm
    if not r.name_min <= len(name) <= r.name_max:
        raise GameError("bad_name", f"Realm names are {r.name_min} to {r.name_max} characters.")
    if is_profane(name, cfg.profanity):
        raise GameError("bad_name", "Pick a friendlier name.")
    return name


async def _new_code(session: AsyncSession) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        taken = (await session.execute(select(Realm.id).where(Realm.invite_code == code))).first()
        if taken is None:
            return code
    raise GameError("try_again", "Couldn't make an invite code. Try again.")


async def ensure_stash(session: AsyncSession, cfg: GameConfig, realm_id: uuid.UUID) -> Container:
    c = (
        await session.execute(
            select(Container).where(
                Container.realm_id == realm_id, Container.kind == ContainerKind.realm_stash
            )
        )
    ).scalar_one_or_none()
    if c is None:
        c = Container(
            id=new_id(), kind=ContainerKind.realm_stash, realm_id=realm_id, capacity=cfg.social.stash.capacity
        )
        session.add(c)
        await session.flush()
    return c


def view(
    cfg: GameConfig,
    realm: Realm,
    me: RealmMember,
    rows: list[tuple[RealmMember, User, Avatar]],
    online: set[str],
    now: datetime,
) -> dict[str, Any]:
    newcomer = timedelta(seconds=cfg.social.stash.newcomer_deposit_only)
    return {
        "id": str(realm.id),
        "name": realm.name,
        "solo": realm.is_solo,
        "invite_code": realm.invite_code if not realm.is_solo else None,
        "owner_id": str(realm.owner_user_id),
        "me": {"role": me.role.value, "plot": me.plot_index, "trusted": me.stash_trusted},
        "max_members": cfg.social.realm.max_members,
        "members": [
            {
                "user_id": str(u.id),
                "username": u.username,
                "role": m.role.value,
                "plot": m.plot_index,
                "trusted": m.stash_trusted or m.role == RealmRole.owner,
                "newcomer": now - m.joined_at < newcomer and m.role != RealmRole.owner,
                "level": a.level,
                "online": str(u.id) in online,
                "appearance": a.appearance,
            }
            for m, u, a in rows
        ],
    }


async def found(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, name: str, now: datetime
) -> Realm:
    """Turn your solo realm into a shared one with an invite code."""
    realm, me = await my_member(session, user_id, lock=True)
    if not realm.is_solo:
        raise GameError("already_shared", "Your realm is already open to friends.")
    realm.name = _check_name(cfg, name)
    realm.is_solo = False
    realm.invite_code = await _new_code(session)
    await ensure_stash(session, cfg, realm.id)
    activity.log(session, realm.id, user_id, "realm_founded", {"name": realm.name}, now)
    return realm


async def _move(
    session: AsyncSession,
    user_id: uuid.UUID,
    old: RealmMember,
    realm_id: uuid.UUID,
    plot: int,
    role: RealmRole,
    now: datetime,
) -> None:
    """Move a player (and their village) to `plot` in `realm_id`. Avatar goes home, out of the wild."""
    trusted = False
    await session.delete(old)
    await session.flush()
    session.add(
        RealmMember(
            realm_id=realm_id,
            user_id=user_id,
            role=role,
            plot_index=plot,
            stash_trusted=trusted,
            joined_at=now,
        )
    )
    await session.execute(update(Village).where(Village.user_id == user_id).values(realm_id=realm_id))
    await session.execute(
        update(Avatar)
        .where(Avatar.user_id == user_id)
        .values(realm_id=realm_id, location=AvatarLocation.village, pos_x=0, pos_y=0)
    )


async def join(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, code: str, now: datetime) -> Realm:
    code = code.strip().upper()
    target = (
        await session.execute(
            select(Realm).where(Realm.invite_code == code, Realm.archived_at.is_(None)).with_for_update()
        )
    ).scalar_one_or_none()
    if target is None or target.is_solo:
        raise NotFound("bad_code", "No realm has that invite code.")
    realm, me = await my_member(session, user_id, lock=True)
    if realm.id == target.id:
        raise GameError("already_member", "You're already in this realm.")
    others = (
        await session.execute(
            select(func.count())
            .select_from(RealmMember)
            .where(RealmMember.realm_id == realm.id, RealmMember.user_id != user_id)
        )
    ).scalar_one()
    if not realm.is_solo or others:
        raise GameError("leave_first", "Leave your current realm first.")
    if target.mapgen_version != cfg.mapgen.version:
        raise GameError("mapgen_version", "That realm uses an older map. It can't take new members yet.")
    taken = set(
        (
            await session.execute(select(RealmMember.plot_index).where(RealmMember.realm_id == target.id))
        ).scalars()
    )
    free = [i for i in range(cfg.mapgen.plot.count) if i not in taken]
    if len(taken) >= cfg.social.realm.max_members or not free:
        raise GameError("realm_full", "That realm is full.")
    await _move(session, user_id, me, target.id, free[0], RealmRole.member, now)
    realm.archived_at = now  # your old solo world sleeps until you need it again
    activity.log(session, target.id, user_id, "member_joined", {"plot": free[0]}, now)
    return target


async def _send_home(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, me: RealmMember, now: datetime
) -> Realm:
    """Back to a solo realm: the archived one you came from, or a fresh one."""
    solo = (
        await session.execute(
            select(Realm)
            .where(Realm.owner_user_id == user_id, Realm.is_solo.is_(True), Realm.archived_at.is_not(None))
            .order_by(Realm.archived_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if solo is None or solo.mapgen_version != cfg.mapgen.version:
        user = await session.get(User, user_id)
        assert user is not None
        solo = Realm(
            id=new_id(),
            name=f"{user.username}{cfg.starter.realm_name_suffix}",
            banner={"pattern": "plain", "primary": "leaf", "secondary": "cream", "emblem": "hearth"},
            owner_user_id=user_id,
            is_solo=True,
            seed=secrets.randbits(62),
            mapgen_version=cfg.mapgen.version,
            weather_seed=secrets.randbits(62),
            created_at=now,
        )
        session.add(solo)
        await session.flush()
    solo.archived_at = None
    await _move(session, user_id, me, solo.id, 0, RealmRole.owner, now)
    return solo


async def leave(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime
) -> tuple[Realm, Realm]:
    """Returns (realm you left, realm you're in now)."""
    realm, me = await my_member(session, user_id, lock=True)
    if realm.is_solo:
        raise GameError("solo", "You're on your own already.")
    rest = [m for m, _u, _a in await members(session, realm.id) if m.user_id != user_id]
    if me.role == RealmRole.owner and rest:
        raise GameError("owner_leaving", "Hand the realm to someone else before you leave.")
    if not rest:  # last one out: the realm simply becomes solo again, keeping your plot and map
        realm.is_solo = True
        realm.invite_code = None
        activity.log(session, realm.id, user_id, "realm_closed", {}, now)
        return realm, realm
    home = await _send_home(session, cfg, user_id, me, now)
    activity.log(session, realm.id, user_id, "member_left", {}, now)
    return realm, home


async def _owner_and_target(
    session: AsyncSession, owner_id: uuid.UUID, target_id: uuid.UUID
) -> tuple[Realm, RealmMember, RealmMember]:
    realm, me = await my_member(session, owner_id, lock=True)
    if me.role != RealmRole.owner:
        raise Forbidden("not_owner", "Only the realm's owner can do that.")
    if realm.is_solo:
        raise GameError("solo", "Found a realm first.")
    target = (
        await session.execute(
            select(RealmMember)
            .where(RealmMember.realm_id == realm.id, RealmMember.user_id == target_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFound("not_member", "They're not in your realm.")
    if target.user_id == owner_id:
        raise GameError("self", "That's you!")
    return realm, me, target


async def kick(
    session: AsyncSession, cfg: GameConfig, owner_id: uuid.UUID, target_id: uuid.UUID, now: datetime
) -> Realm:
    realm, _me, target = await _owner_and_target(session, owner_id, target_id)
    home = await _send_home(session, cfg, target_id, target, now)
    activity.log(session, realm.id, owner_id, "member_kicked", {"user_id": str(target_id)}, now)
    return home


async def transfer(session: AsyncSession, owner_id: uuid.UUID, target_id: uuid.UUID, now: datetime) -> None:
    realm, me, target = await _owner_and_target(session, owner_id, target_id)
    me.role = RealmRole.member
    me.stash_trusted = True  # the old owner keeps full stash rights
    target.role = RealmRole.owner
    realm.owner_user_id = target_id
    activity.log(session, realm.id, owner_id, "owner_changed", {"user_id": str(target_id)}, now)


async def trust(
    session: AsyncSession, owner_id: uuid.UUID, target_id: uuid.UUID, on: bool, now: datetime
) -> None:
    realm, _me, target = await _owner_and_target(session, owner_id, target_id)
    target.stash_trusted = on
    activity.log(
        session, realm.id, owner_id, "trust_changed", {"user_id": str(target_id), "trusted": on}, now
    )


async def rename(
    session: AsyncSession, cfg: GameConfig, owner_id: uuid.UUID, name: str, now: datetime
) -> None:
    realm, me = await my_member(session, owner_id, lock=True)
    if me.role != RealmRole.owner:
        raise Forbidden("not_owner", "Only the realm's owner can rename it.")
    realm.name = _check_name(cfg, name)
    activity.log(session, realm.id, owner_id, "realm_renamed", {"name": realm.name}, now)


async def new_invite_code(session: AsyncSession, owner_id: uuid.UUID) -> str:
    realm, me = await my_member(session, owner_id, lock=True)
    if me.role != RealmRole.owner or realm.is_solo:
        raise Forbidden("not_owner", "Only the realm's owner can change the invite code.")
    realm.invite_code = await _new_code(session)
    return realm.invite_code
