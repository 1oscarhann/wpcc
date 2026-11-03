from __future__ import annotations

import enum
import os
import time
import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {datetime: DateTime(timezone=True)}


def new_id() -> uuid.UUID:
    """Time-ordered UUID v7 (RFC 9562). Python 3.13 has no uuid.uuid7, so build it by hand."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    rand_a = rand >> 68  # 12 bits
    rand_b = rand & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b
    return uuid.UUID(int=value)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def pg_enum(enum_cls: type[enum.Enum], name: str):  # noqa: ANN201
    from sqlalchemy import Enum

    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])
