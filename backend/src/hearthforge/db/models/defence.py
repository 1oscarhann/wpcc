"""Monster waves and realm bosses (Phase 13)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import REAL, BigInteger, ForeignKey, Index, Integer, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base


class MonsterWave(Base):
    """One wave on one village: announced → running → done, or postponed if its owner went offline."""

    __tablename__ = "monster_waves"
    __table_args__ = (
        Index("ix_monster_waves_user", "user_id", "created_at"),
        Index("ix_monster_waves_live", "status", postgresql_where=text("status IN ('announced', 'running')")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    realm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("realms.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text, nullable=False)  # announced | running | done | postponed
    town_hall: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    announced_at: Mapped[datetime] = mapped_column(nullable=False)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ended_at: Mapped[datetime | None]
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RealmBoss(Base):
    """A realm boss waiting in its lair (Phase 13). HP is kept as a fraction so party scaling can change."""

    __tablename__ = "realm_bosses"
    __table_args__ = (Index("ix_realm_bosses_realm", "realm_id", "spawns_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    realm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("realms.id", ondelete="CASCADE"))
    boss_key: Mapped[str] = mapped_column(Text, nullable=False)
    lair_x: Mapped[float] = mapped_column(REAL, nullable=False)
    lair_y: Mapped[float] = mapped_column(REAL, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # waiting | defeated | expired
    spawns_at: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    hp_fraction: Mapped[float] = mapped_column(REAL, nullable=False, default=1.0)
    defeated_at: Mapped[datetime | None]


class BossDamage(Base):
    """Who hit a realm boss and how hard: loot needs ≥ 1% of the damage."""

    __tablename__ = "boss_damage"

    boss_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("realm_bosses.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    damage: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    looted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
