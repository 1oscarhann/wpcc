"""Phase 15 (social) and Phase 16 (progression) tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base

_U = "users.id"


class Friendship(Base):
    """One row per pair (user_low < user_high): pending until the other side accepts."""

    __tablename__ = "friendships"
    __table_args__ = (CheckConstraint("user_low < user_high", name="ordered_pair"),)

    user_low: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    user_high: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # pending | accepted
    requested_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    accepted_at: Mapped[datetime | None]


class Block(Base):
    __tablename__ = "blocks"

    blocker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    blocked_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Mail(Base):
    """A parcel waiting to be claimed: a friend's gift, boss loot you left before collecting, rewards."""

    __tablename__ = "mail"
    __table_args__ = (Index("ix_mail_user", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"))
    sender_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(_U, ondelete="SET NULL"))
    sender_name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # gift | boss | system
    items: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
    coins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    claimed_at: Mapped[datetime | None]


class Gift(Base):
    __tablename__ = "gifts"
    __table_args__ = (Index("ix_gifts_from_day", "from_user", "day"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    from_user: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"))
    to_user: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"))
    day: Mapped[str] = mapped_column(Text, nullable=False)  # UTC date
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    contents: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class VillageLike(Base):
    __tablename__ = "village_likes"

    liker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    counted: Mapped[bool] = mapped_column(Boolean, nullable=False)  # false if the liker was below the P4 gate
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class VillageVisit(Base):
    __tablename__ = "village_visits"

    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    day: Mapped[str] = mapped_column(Text, primary_key=True)


class NeighbourHelp(Base):
    """A help on a building timer. One per timer per day, and each helper once per building per day."""

    __tablename__ = "neighbour_helps"
    __table_args__ = (Index("ix_neighbour_helps_building_day", "building_id", "day"),)

    helper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    building_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("village_buildings.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"))
    seconds_saved: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class QuestProgress(Base):
    """A quest handed out for a period. Progress = the stat now − `base` (main quests use the total)."""

    __tablename__ = "quest_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    quest_key: Mapped[str] = mapped_column(Text, primary_key=True)
    period_start: Mapped[str] = mapped_column(Text, primary_key=True)  # day / week start (UTC); 'main'
    period: Mapped[str] = mapped_column(Text, nullable=False)  # daily | weekly | main
    stat: Mapped[str] = mapped_column(Text, nullable=False)
    base: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_at: Mapped[datetime | None]


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    achievement_key: Mapped[str] = mapped_column(Text, primary_key=True)
    unlocked_at: Mapped[datetime] = mapped_column(server_default=func.now())
    claimed_at: Mapped[datetime | None]


class UserCosmetic(Base):
    __tablename__ = "user_cosmetics"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    cosmetic_key: Mapped[str] = mapped_column(Text, primary_key=True)  # 'title:Slime Slayer'
    source: Mapped[str] = mapped_column(Text, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LoginReward(Base):
    __tablename__ = "login_rewards"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    calendar_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    last_claim_day: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
