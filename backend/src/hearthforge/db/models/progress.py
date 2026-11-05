"""Generic per-player counters (SCHEMA §2): feed the tutorial now, quests and achievements later."""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base


class UserStat(Base):
    __tablename__ = "user_stats"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    stat_key: Mapped[str] = mapped_column(Text, primary_key=True)  # 'kill.slime', 'gather.wood', 'sell.any'…
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
