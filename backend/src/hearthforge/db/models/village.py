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
    Index,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base, created_at_col, new_id, pg_enum


class BuildingState(enum.StrEnum):
    active = "active"
    constructing = "constructing"
    upgrading = "upgrading"


class Village(Base):
    __tablename__ = "villages"
    __table_args__ = (CheckConstraint("size BETWEEN 24 AND 48", name="size_range"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    realm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("realms.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(SmallInteger, default=24)
    version: Mapped[int] = mapped_column(Integer, default=0)
    beauty: Mapped[int] = mapped_column(Integer, default=0)
    happiness: Mapped[int] = mapped_column(SmallInteger, default=50)
    likes_count: Mapped[int] = mapped_column(Integer, default=0)
    last_action: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    debris: Mapped[list[list[Any]]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = created_at_col()


class VillageBuilding(Base):
    __tablename__ = "village_buildings"
    __table_args__ = (
        CheckConstraint("rotation BETWEEN 0 AND 3", name="rotation_range"),
        Index(
            "ix_village_buildings_work_due",
            "work_completes_at",
            postgresql_where=text("state <> 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    village_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("villages.id", ondelete="CASCADE"), index=True)
    building_key: Mapped[str] = mapped_column(Text, nullable=False)
    x: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    y: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rotation: Mapped[int] = mapped_column(SmallInteger, default=0)
    level: Mapped[int] = mapped_column(SmallInteger, default=0)
    state: Mapped[BuildingState] = mapped_column(pg_enum(BuildingState, "building_state"))
    work_started_at: Mapped[datetime | None]
    work_completes_at: Mapped[datetime | None]
    work_paid: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    helped_seconds: Mapped[int] = mapped_column(Integer, default=0)
    skin_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class Resource(Base):
    """Lazy production (BALANCE §3). Amounts and rates are milli-units (D-007)."""

    __tablename__ = "resources"
    __table_args__ = (CheckConstraint("amount_milli >= 0", name="amount_nonneg"),)

    village_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("villages.id", ondelete="CASCADE"), primary_key=True
    )
    resource_key: Mapped[str] = mapped_column(Text, primary_key=True)
    amount_milli: Mapped[int] = mapped_column(BigInteger, nullable=False)
    base_rate_milli: Mapped[int] = mapped_column(BigInteger, default=0)
    weather_class: Mapped[str | None] = mapped_column(Text)
    cap_milli: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(nullable=False)


class Presence(Base):
    __tablename__ = "presence"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    heartbeat_at: Mapped[datetime]
    online_since: Mapped[datetime]
    in_avatar_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    realm_id: Mapped[uuid.UUID | None]
