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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base, created_at_col, new_id, pg_enum


class RealmRole(enum.StrEnum):
    owner = "owner"
    member = "member"


class RealmVisibility(enum.StrEnum):
    private = "private"
    public = "public"


class Realm(Base):
    __tablename__ = "realms"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    banner: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    is_solo: Mapped[bool] = mapped_column(Boolean, default=True)
    visibility: Mapped[RealmVisibility] = mapped_column(
        pg_enum(RealmVisibility, "realm_visibility"), default=RealmVisibility.private
    )
    invite_code: Mapped[str | None] = mapped_column(String(6), unique=True)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mapgen_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    weather_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    archived_at: Mapped[datetime | None]


class RealmMember(Base):
    __tablename__ = "realm_members"
    __table_args__ = (
        UniqueConstraint("realm_id", "plot_index", name="uq_realm_members_plot"),
        CheckConstraint("plot_index BETWEEN 0 AND 9", name="plot_range"),
    )

    realm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("realms.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, unique=True
    )
    role: Mapped[RealmRole] = mapped_column(pg_enum(RealmRole, "realm_role"), default=RealmRole.member)
    plot_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stash_trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = created_at_col()
