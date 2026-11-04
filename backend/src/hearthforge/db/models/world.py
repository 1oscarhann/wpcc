from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import REAL, ForeignKey, Index, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base, new_id


class NodeHarvest(Base):
    """A resource node one player has depleted. The row only exists until it respawns (PLAN §2.6)."""

    __tablename__ = "node_harvests"
    __table_args__ = (Index("ix_node_harvests_respawn_at", "respawn_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    realm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("realms.id", ondelete="CASCADE"), primary_key=True)
    node_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    respawn_at: Mapped[datetime] = mapped_column(nullable=False)


class DeathDrop(Base):
    """Rare materials dropped on KO, recoverable for a few minutes (BALANCE §4, P13)."""

    __tablename__ = "death_drops"
    __table_args__ = (
        Index("ix_death_drops_realm_open", "realm_id", postgresql_where=text("recovered_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    realm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("realms.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    x: Mapped[float] = mapped_column(REAL, nullable=False)
    y: Mapped[float] = mapped_column(REAL, nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    recovered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    recovered_at: Mapped[datetime | None]
