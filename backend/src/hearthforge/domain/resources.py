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


def settle_weather(st: ResState, now: datetime, segments: list[tuple[datetime, datetime, float]]) -> ResState:
    """Like `settle`, but the rate is multiplied per time segment (weather blocks, P9).
    `segments` must cover [st.at, now) in order: (start, end, multiplier)."""
    if now <= st.at or not segments:
        return settle(st, now)
    base = st.rate
    cur = st
    for _a, b, mult in segments:
        if b <= cur.at:
            continue
        end = min(b, now)
        if end <= cur.at:
            continue
        nxt = settle(replace(cur, rate=round(base * mult)), end)
        # a sub-unit remainder can leave `at` short of the segment end; move on so the next segment
        # starts on time (this drops less than one milli-unit per boundary)
        cur = replace(nxt, rate=base, at=end if nxt.at < end and nxt.amount < nxt.cap else nxt.at)
        if cur.at >= now:
            break
    return replace(cur, rate=base)
