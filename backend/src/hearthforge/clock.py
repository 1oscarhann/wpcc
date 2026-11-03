"""Injectable clock. Domain code never calls datetime.now() directly."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock(Clock):
    """Test clock: time only moves when told to."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float = 0, **kwargs: float) -> datetime:
        self._now += timedelta(seconds=seconds, **kwargs)
        return self._now

    def set(self, when: datetime) -> None:
        self._now = when


def to_ms(dt: datetime | None) -> int | None:
    return None if dt is None else int(dt.timestamp() * 1000)
