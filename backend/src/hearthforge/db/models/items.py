from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base, created_at_col, new_id, pg_enum


class Rarity(enum.StrEnum):
    common = "common"
    uncommon = "uncommon"
    rare = "rare"
    epic = "epic"
    legendary = "legendary"


class ContainerKind(enum.StrEnum):
    inventory = "inventory"
    bank = "bank"
    equipment = "equipment"
    realm_stash = "realm_stash"
    mailbox = "mailbox"


class ItemOrigin(enum.StrEnum):
    starter = "starter"
    gathered = "gathered"
    drop = "drop"
    forged = "forged"
    crafted = "crafted"
    merchant = "merchant"
    reward = "reward"
    gift = "gift"
    market = "market"
    admin = "admin"


class ItemDef(Base):
    """Mirror of config item definitions, upserted on startup and never deleted."""

    __tablename__ = "item_defs"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    stackable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_stack: Mapped[int] = mapped_column(Integer, nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    retired: Mapped[bool] = mapped_column(Boolean, default=False)


class ItemInstance(Base):
    __tablename__ = "item_instances"
    __table_args__ = (CheckConstraint("tier BETWEEN 1 AND 5", name="tier_range"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    item_key: Mapped[str] = mapped_column(ForeignKey("item_defs.key"))
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rarity: Mapped[Rarity] = mapped_column(pg_enum(Rarity, "rarity"))
    modifiers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    durability: Mapped[int] = mapped_column(Integer, nullable=False)
    max_durability: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[ItemOrigin] = mapped_column(pg_enum(ItemOrigin, "item_origin"))
    crafted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    roll_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    skin_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class Container(Base):
    __tablename__ = "containers"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "kind", name="uq_containers_owner_kind"),
        CheckConstraint("(kind = 'realm_stash') = (realm_id IS NOT NULL)", name="stash_has_realm"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[ContainerKind] = mapped_column(pg_enum(ContainerKind, "container_kind"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    realm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("realms.id", ondelete="CASCADE"))
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class ContainerSlot(Base):
    __tablename__ = "container_slots"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="qty_positive"),
        CheckConstraint("instance_id IS NULL OR quantity = 1", name="instance_single"),
    )

    container_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("containers.id", ondelete="CASCADE"), primary_key=True
    )
    slot: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    item_key: Mapped[str] = mapped_column(ForeignKey("item_defs.key"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    instance_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_instances.id"), unique=True)
