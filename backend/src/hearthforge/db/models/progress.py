"""Generic per-player counters (SCHEMA §2): feed the tutorial now, quests and achievements later."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base


class UserStat(Base):
    __tablename__ = "user_stats"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    stat_key: Mapped[str] = mapped_column(Text, primary_key=True)  # 'kill.slime', 'gather.wood', 'sell.any'…
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class DungeonRun(Base):
    """A cleared delve (Phase 12). Daily runs feed the global leaderboard (fastest clear of the day)."""

    __tablename__ = "dungeon_runs"
    __table_args__ = (Index("ix_dungeon_runs_board", "kind", "day", "clear_ms"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # daily | cave
    key: Mapped[str] = mapped_column(Text, nullable=False)
    day: Mapped[str] = mapped_column(Text, nullable=False)  # UTC date, YYYY-MM-DD
    realm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("realms.id", ondelete="CASCADE"))
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    biome: Mapped[str] = mapped_column(Text, nullable=False)
    names: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    user_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    clear_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    deaths: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
