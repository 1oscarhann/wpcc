"""NPC market, merchant purchases, idempotency keys and economy samples (Phase 7, SCHEMA §6)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base


class IdempotencyKey(Base):
    """One row per (user, Idempotency-Key). Written in the same transaction as the action it guards,
    so a key exists exactly when its action committed. The worker prunes rows older than 24 h."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("ix_idempotency_keys_created", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class MarketPrice(Base):
    __tablename__ = "market_prices"

    item_key: Mapped[str] = mapped_column(ForeignKey("item_defs.key"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    units_sold_24h: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    baseline_used: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


class MarketPriceHistory(Base):
    __tablename__ = "market_price_history"

    item_key: Mapped[str] = mapped_column(ForeignKey("item_defs.key"), primary_key=True)
    at: Mapped[datetime] = mapped_column(primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    units_24h: Mapped[int] = mapped_column(BigInteger, nullable=False)


class MarketSalesBucket(Base):
    __tablename__ = "market_sales_buckets"

    item_key: Mapped[str] = mapped_column(ForeignKey("item_defs.key"), primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(primary_key=True)
    units: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class MarketPlayerDaily(Base):
    __tablename__ = "market_player_daily"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    item_key: Mapped[str] = mapped_column(Text, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    units: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class MerchantPurchase(Base):
    """Stock itself is derived from (merchant id, rotation, config); this only counts what you bought."""

    __tablename__ = "merchant_purchases"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rotation: Mapped[int] = mapped_column(Integer, primary_key=True)
    slot: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class EconomySample(Base):
    """Coin supply and faucet/sink flow, sampled at every market recalc (the admin economy view)."""

    __tablename__ = "economy_samples"

    at: Mapped[datetime] = mapped_column(primary_key=True)
    coin_supply: Mapped[int] = mapped_column(BigInteger, nullable=False)
    players: Mapped[int] = mapped_column(Integer, nullable=False)
    active_24h: Mapped[int] = mapped_column(Integer, nullable=False)
    faucet: Mapped[int] = mapped_column(BigInteger, nullable=False)  # coins created since the last sample
    sink: Mapped[int] = mapped_column(BigInteger, nullable=False)  # coins destroyed since the last sample
    last_tx_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )  # flow is counted by ledger id, not time
