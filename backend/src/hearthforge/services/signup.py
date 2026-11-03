"""New player creation: user, settings, avatar, solo realm, village, resources, wallet, containers, items."""

from __future__ import annotations

import secrets
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.config.schemas import Appearance
from hearthforge.core.errors import GameError
from hearthforge.core.profanity import username_problem
from hearthforge.core.security import Passwords, new_recovery_code
from hearthforge.db.base import new_id
from hearthforge.db.models import (
    Avatar,
    BuildingState,
    Container,
    ContainerKind,
    ContainerSlot,
    ItemInstance,
    ItemOrigin,
    Rarity,
    Realm,
    RealmMember,
    RealmRole,
    RecoveryCode,
    Resource,
    User,
    UserSettings,
    Village,
    VillageBuilding,
    Wallet,
)
from hearthforge.domain.economy import BuildingView, caps_milli, rates_milli
from hearthforge.domain.resources import MILLI
from hearthforge.services import ledger

DEFAULT_AUDIO = {"master": 0.8, "music": 0.6, "sfx": 0.8, "muted": False}


def validate_appearance(cfg: GameConfig, raw: dict) -> dict:
    try:
        ap = Appearance.model_validate(raw)
    except ValidationError as e:
        raise GameError("bad_appearance", "That look isn't valid.", errors=str(e)) from e
    cr = cfg.avatar.creator
    checks = {
        "body": cr.bodies,
        "skin": cr.skin_tones,
        "hair_style": cr.hair_styles,
        "hair_color": cr.hair_colors,
        "eyes": cr.eye_styles,
        "eye_color": cr.eye_colors,
        "outfit": cr.outfits,
        "outfit_color": cr.outfit_colors,
    }
    for fld, options in checks.items():
        if getattr(ap, fld) not in options:
            raise GameError("bad_appearance", f"Unknown {fld.replace('_', ' ')}.", field=fld)
    return ap.model_dump()


def check_username(cfg: GameConfig, username: str) -> None:
    a = cfg.game.auth
    problem = username_problem(username, cfg.profanity, a.username_min, a.username_max)
    if problem:
        raise GameError("bad_username", problem)


def check_password(cfg: GameConfig, password: str) -> None:
    if len(password) < cfg.game.auth.password_min:
        raise GameError("weak_password", f"Passwords need at least {cfg.game.auth.password_min} characters.")
    if len(password) > 256:
        raise GameError("weak_password", "That password is too long.")


async def username_taken(session: AsyncSession, username: str) -> bool:
    return (await session.execute(select(User.id).where(User.username == username))).first() is not None


async def create_player(
    session: AsyncSession,
    cfg: GameConfig,
    passwords: Passwords,
    now: datetime,
    username: str,
    password: str,
    appearance: dict,
) -> tuple[User, list[str]]:
    """Must run inside an open transaction. Returns the user and the plaintext recovery codes (shown once)."""
    check_username(cfg, username)
    check_password(cfg, password)
    look = validate_appearance(cfg, appearance)
    if await username_taken(session, username):
        raise GameError("username_taken", "That username is taken.", status=409)

    user = User(id=new_id(), username=username, password_hash=passwords.hash(password), created_at=now)
    session.add(user)
    session.add(UserSettings(user_id=user.id, audio=dict(DEFAULT_AUDIO), keybinds={}, graphics={}, ui={}))
    await session.flush()

    codes = [new_recovery_code() for _ in range(cfg.game.auth.recovery_codes)]
    for code in codes:
        session.add(RecoveryCode(user_id=user.id, code_hash=passwords.hash(code)))

    st = cfg.starter
    realm = Realm(
        id=new_id(),
        name=f"{username}{st.realm_name_suffix}",
        owner_user_id=user.id,
        is_solo=True,
        banner={"pattern": "plain", "primary": "leaf", "secondary": "cream", "emblem": "hearth"},
        seed=secrets.randbits(62),
        mapgen_version=cfg.mapgen.version,
        weather_seed=secrets.randbits(62),
        created_at=now,
    )
    session.add(realm)
    await session.flush()
    session.add(
        RealmMember(realm_id=realm.id, user_id=user.id, role=RealmRole.owner, plot_index=0, joined_at=now)
    )

    base = cfg.avatar.base_stats
    session.add(Avatar(user_id=user.id, appearance=look, hp=base.hp, realm_id=realm.id, updated_at=now))

    village = Village(
        id=new_id(),
        user_id=user.id,
        realm_id=realm.id,
        name=f"{username}{st.village_name_suffix}",
        size=cfg.mapgen.plot.start_size,
        created_at=now,
        updated_at=now,
    )
    session.add(village)
    await session.flush()

    views = []
    for sb in st.buildings:
        session.add(
            VillageBuilding(
                id=new_id(),
                village_id=village.id,
                building_key=sb.key,
                x=sb.x,
                y=sb.y,
                rotation=0,
                level=sb.level,
                state=BuildingState.active,
                created_at=now,
            )
        )
        views.append(BuildingView(sb.key, sb.level, "active"))
    rates = rates_milli(cfg, views)
    caps = caps_milli(cfg, views)
    for key in cfg.resource_keys:
        amount = st.resources.get(key, 0) * MILLI
        session.add(
            Resource(
                village_id=village.id,
                resource_key=key,
                amount_milli=amount,
                base_rate_milli=rates[key],
                cap_milli=caps[key],
                last_updated_at=now,
            )
        )
        ledger.log_resource(session, user.id, realm.id, key, amount, ledger.STARTER_GRANT, actor="system")

    wallet = Wallet(user_id=user.id, coins=0, updated_at=now)
    session.add(wallet)
    await session.flush()
    await ledger.change_coins(session, wallet, st.coins, ledger.STARTER_GRANT, actor="system")

    containers: dict[str, Container] = {}
    for kind, capacity in st.containers.items():
        c = Container(id=new_id(), kind=ContainerKind(kind), owner_user_id=user.id, capacity=capacity)
        containers[kind] = c
        session.add(c)
    await session.flush()
    for it in st.items:
        instance_id = None
        info = cfg.items[it.item]
        if not info.stackable:
            inst = ItemInstance(
                id=new_id(),
                item_key=it.item,
                tier=it.tier or 1,
                rarity=Rarity(it.rarity or "common"),
                modifiers=[],
                durability=it.durability or 100,
                max_durability=it.durability or 100,
                origin=ItemOrigin.starter,
                roll_seed=secrets.randbits(62),
                created_at=now,
            )
            session.add(inst)
            await session.flush()
            instance_id = inst.id
        container = containers[it.container]
        session.add(
            ContainerSlot(
                container_id=container.id,
                slot=it.slot,
                item_key=it.item,
                quantity=it.quantity,
                instance_id=instance_id,
            )
        )
        ledger.log_item(
            session,
            user.id,
            it.item,
            it.quantity,
            ledger.STARTER_GRANT,
            container_id=container.id,
            instance_id=instance_id,
            actor="system",
        )
    await session.flush()
    return user, codes
