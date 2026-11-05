from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base, created_at_col, pg_enum


class LedgerAsset(enum.StrEnum):
    coin = "coin"
    item = "item"
    resource = "resource"


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("coins >= 0", name="coins_nonneg"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    coins: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = created_at_col()


class Transaction(Base):
    """Append-only ledger. A trigger (see migration) rejects UPDATE and DELETE."""

    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_user_created", "user_id", "created_at"),
        Index("ix_transactions_reason_created", "reason", "created_at"),
        Index("ix_transactions_ref", "ref_type", "ref_id"),
        Index("ix_transactions_coin_created", "created_at", postgresql_where=text("asset = 'coin'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    realm_id: Mapped[uuid.UUID | None]
    asset: Mapped[LedgerAsset] = mapped_column(pg_enum(LedgerAsset, "ledger_asset"))
    item_key: Mapped[str | None] = mapped_column(Text)
    instance_id: Mapped[uuid.UUID | None]
    container_id: Mapped[uuid.UUID | None]
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    ref_type: Mapped[str | None] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[uuid.UUID | None]
    actor: Mapped[str] = mapped_column(Text, default="user")
    created_at: Mapped[datetime] = created_at_col()
