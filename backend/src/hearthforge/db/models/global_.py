"""Phase 17: the player market and world boss weekends."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Identity, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base

_U = "users.id"


class Listing(Base):
    """Goods in escrow: they left the seller's bag when listed and go to the buyer, or back by mail."""

    __tablename__ = "pmarket_listings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), nullable=False)
    seller_name: Mapped[str] = mapped_column(Text, nullable=False)
    item_key: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    listed: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column()


class Trade(Base):
    __tablename__ = "pmarket_trades"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pmarket_listings.id", ondelete="CASCADE"))
    seller_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    buyer_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    item_key: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    fee: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WorldBossEvent(Base):
    __tablename__ = "world_boss_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    boss_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    hp_max: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hp_remaining: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    finished_at: Mapped[datetime | None] = mapped_column()
    rewarded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WorldBossDamage(Base):
    __tablename__ = "world_boss_damage"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("world_boss_events.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(_U, ondelete="CASCADE"), primary_key=True)
    realm_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    damage: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
