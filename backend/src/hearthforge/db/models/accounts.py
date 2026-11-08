from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import REAL, Boolean, ForeignKey, Integer, LargeBinary, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base, created_at_col, new_id, pg_enum


class UserRole(enum.StrEnum):
    player = "player"
    admin = "admin"


class AvatarLocation(enum.StrEnum):
    village = "village"
    wild = "wild"
    dungeon = "dungeon"
    visiting = "visiting"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"), default=UserRole.player)
    created_at: Mapped[datetime] = created_at_col()
    last_seen_at: Mapped[datetime | None]
    banned_at: Mapped[datetime | None]
    tutorial_step: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_test_account: Mapped[bool] = mapped_column(Boolean, default=False)
    # what your village looked like when your last socket closed: the "While you were away" baseline
    away_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    audio: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    keybinds: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    graphics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ui: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = created_at_col()


class Session(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    expires_at: Mapped[datetime] = mapped_column(index=True)
    last_used_at: Mapped[datetime]


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    code_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    used_at: Mapped[datetime | None]


class Avatar(Base):
    __tablename__ = "avatars"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    appearance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    skills: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    respecs: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    title: Mapped[str | None] = mapped_column(Text)
    pet: Mapped[str | None] = mapped_column(Text)  # Phase 16b: the pet that's out
    mount: Mapped[str | None] = mapped_column(Text)  # the mount you ride when you press G
    level: Mapped[int] = mapped_column(SmallInteger, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    hp: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_points: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_free_respec_at: Mapped[datetime | None]
    title_key: Mapped[str | None] = mapped_column(Text)
    location: Mapped[AvatarLocation] = mapped_column(
        pg_enum(AvatarLocation, "avatar_location"), default=AvatarLocation.village
    )
    realm_id: Mapped[uuid.UUID | None]
    pos_x: Mapped[float] = mapped_column(REAL, default=0)
    pos_y: Mapped[float] = mapped_column(REAL, default=0)
    updated_at: Mapped[datetime] = created_at_col()
