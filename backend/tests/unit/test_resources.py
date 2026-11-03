from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hearthforge.domain.resources import MILLI, ResState, amount_at, settle

pytestmark = pytest.mark.nodb
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def state(amount: float = 0, rate: float = 60, cap: float = 1000) -> ResState:
    return ResState(round(amount * MILLI), round(rate * MILLI), round(cap * MILLI), T0)


def test_one_hour_produces_rate() -> None:
    assert settle(state(rate=60), T0 + timedelta(hours=1)).amount == 60 * MILLI


def test_caps_and_stays_capped() -> None:
    s = settle(state(amount=990, rate=60), T0 + timedelta(hours=1))
    assert s.amount == 1000 * MILLI
    assert settle(s, T0 + timedelta(hours=5)).amount == 1000 * MILLI


def test_over_cap_never_decreases() -> None:
    s = settle(state(amount=1500, rate=60, cap=1000), T0 + timedelta(hours=1))
    assert s.amount == 1500 * MILLI


def test_offline_production_three_days() -> None:
    s = settle(state(rate=60, cap=10_000), T0 + timedelta(days=3))
    assert s.amount == 4320 * MILLI


def test_time_going_backwards_is_noop() -> None:
    s = state(amount=5)
    assert settle(s, T0 - timedelta(hours=1)) == s


def test_zero_rate() -> None:
    assert settle(state(amount=7, rate=0), T0 + timedelta(hours=9)).amount == 7 * MILLI


def test_amount_at_display() -> None:
    assert amount_at(state(rate=60), T0 + timedelta(minutes=30)) == pytest.approx(30.0)


@settings(max_examples=300, deadline=None)
@given(
    rate=st.integers(min_value=0, max_value=2_000_000),
    amount=st.integers(min_value=0, max_value=5_000_000),
    cap=st.integers(min_value=1, max_value=20_000_000),
    steps=st.lists(st.integers(min_value=0, max_value=7_200_000_000), min_size=1, max_size=40),
)
def test_many_small_settles_equal_one_big(rate: int, amount: int, cap: int, steps: list[int]) -> None:
    """Settling every few seconds must not lose or gain stock compared to settling once."""
    start = ResState(amount, rate, cap, T0)
    s = start
    t = T0
    for us in steps:
        t += timedelta(microseconds=us)
        s = settle(s, t)
        assert s.amount >= 0
        assert s.amount <= max(cap, amount)
    once = settle(start, t)
    assert abs(s.amount - once.amount) <= 1
