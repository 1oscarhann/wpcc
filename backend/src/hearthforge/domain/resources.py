"""Lazy resource maths (BALANCE §3, D-007). Pure: no IO, no clock.

Amounts and rates are integer milli-units (1 wood = 1000). `settle` turns elapsed time into
stock, clamped at the cap, and carries the sub-unit remainder forward by only advancing the
timestamp by the time actually "spent". Settling in many small steps gives the same total as
settling once (property-tested).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

US_PER_HOUR = 3_600_000_000
MILLI = 1000


@dataclass(frozen=True)
class ResState:
    amount: int  # milli-units
    rate: int  # milli-units per hour (>= 0)
    cap: int  # milli-units
    at: datetime


def settle(st: ResState, now: datetime) -> ResState:
    if now <= st.at:
        return st
    if st.rate <= 0 or st.amount >= st.cap:
        # Nothing accrues; an over-cap amount (e.g. from a deposit) never decreases.
        return replace(st, at=now)
    elapsed_us = (now - st.at) // timedelta(microseconds=1)
    produced = st.rate * elapsed_us // US_PER_HOUR
    if st.amount + produced >= st.cap:
        return replace(st, amount=st.cap, at=now)
    spent_us = -(-produced * US_PER_HOUR // st.rate)  # ceil: never credit time twice
    return replace(st, amount=st.amount + produced, at=st.at + timedelta(microseconds=spent_us))


def amount_at(st: ResState, now: datetime) -> float:
    """Display value in whole units (float)."""
    return settle(st, now).amount / MILLI


def to_milli(units: float) -> int:
    return round(units * MILLI)
