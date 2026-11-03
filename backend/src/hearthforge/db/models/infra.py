from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base, created_at_col, pg_enum


class EventStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class ScheduledEvent(Base):
    __tablename__ = "scheduled_events"
    __table_args__ = (
        Index("ix_scheduled_events_due", "due_at", postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[EventStatus] = mapped_column(
        pg_enum(EventStatus, "event_status"), default=EventStatus.pending
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    processed_at: Mapped[datetime | None]


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_id_desc", "user_id", text("id DESC")),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    read_at: Mapped[datetime | None]


class ConfigVersion(Base):
    __tablename__ = "config_versions"

    hash: Mapped[str] = mapped_column(Text, primary_key=True)
    loaded_at: Mapped[datetime] = created_at_col()
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = created_at_col()
