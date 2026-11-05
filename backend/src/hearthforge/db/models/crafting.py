from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import REAL, BigInteger, ForeignKey, Index, Integer, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hearthforge.db.base import Base, created_at_col, new_id, pg_enum


class JobStatus(enum.StrEnum):
    running = "running"
    collected = "collected"  # intermediates are collected into storage automatically when due
    cancelled = "cancelled"


class DiscoveryKind(enum.StrEnum):
    combo = "combo"
    recipe = "recipe"
    poi = "poi"
    lore = "lore"
    biome = "biome"
    monster = "monster"
    fish = "fish"
    rare_material = "rare_material"
    hint = "hint"  # a combo whose buildings a merchant hint revealed (Phase 7)


class CraftJob(Base):
    """A station job: intermediates (into storage when due) or gear (collected by hand)."""

    __tablename__ = "craft_jobs"
    __table_args__ = (Index("ix_craft_jobs_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    station_building_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("village_buildings.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # intermediate | gear
    recipe_key: Mapped[str] = mapped_column(Text, nullable=False)
    combo_key: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[int | None] = mapped_column(SmallInteger)
    quantity: Mapped[int] = mapped_column(SmallInteger, default=1)
    inputs: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    rare_inputs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    luck: Mapped[float] = mapped_column(REAL, default=0)
    legendary_eligible: Mapped[bool] = mapped_column(default=False)
    roll_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    completes_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[JobStatus] = mapped_column(pg_enum(JobStatus, "job_status"), default=JobStatus.running)
    result_instance_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_instances.id"))
    collected_at: Mapped[datetime | None]


class Discovery(Base):
    """Permanent, per player: drives the recipe book (and later the collection book)."""

    __tablename__ = "discoveries"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[DiscoveryKind] = mapped_column(pg_enum(DiscoveryKind, "discovery_kind"), primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    first_at: Mapped[datetime] = created_at_col()
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
