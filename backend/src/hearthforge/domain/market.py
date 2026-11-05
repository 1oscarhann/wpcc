"""Pure economy maths: NPC market prices (BALANCE §8.1, P1), payouts, trends, sparklines, and the
wandering merchant's seeded stock. No I/O here; services/market.py and services/merchant.py do that."""

from __future__ import annotations

import hashlib
import math
import random
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hearthforge.config.schemas import MarketCfg, MerchantCfg

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


# ── market ───────────────────────────────────────────────────────────────────


def baseline(cfg: MarketCfg, key: str, active_players: int) -> float:
    """P1: the 'normal' daily volume scales with how many people actually play."""
    return cfg.items[key].baseline * max(active_players, cfg.defaults.min_population)


def price_mult(units_24h: float, base_line: float, k: float, clamp: tuple[float, float]) -> float:
    lo, hi = clamp
    return max(lo, min(hi, math.exp(-k * (units_24h - base_line) / base_line)))


def price(cfg: MarketCfg, key: str, units_24h: float, active_players: int) -> tuple[float, float]:
    """(price before the Market bonus, baseline used)."""
    bl = baseline(cfg, key, active_players)
    p = cfg.items[key].base * price_mult(units_24h, bl, cfg.k(key), cfg.defaults.clamp)
    return round(p, 3), bl


@dataclass(frozen=True)
class Payout:
    coins: int
    full_units: int  # sold at the normal price
    over_units: int  # sold past the daily soft cap


def payout(
    unit_price: float, bonus: float, qty: int, sold_today: int, soft_cap: int, over_mult: float
) -> Payout:
    """Coins for selling `qty` now. Units past the player's daily soft cap pay × over_mult.
    Rounds down once for the whole sale (never per unit), so splitting a sale can't earn more."""
    full = max(0, min(qty, soft_cap - sold_today))
    over = qty - full
    each = unit_price * (1 + bonus)
    coins = math.floor(each * full + each * over_mult * over + 1e-9)
    return Payout(coins, full, over)


def bucket_start(t: datetime, interval_s: float) -> datetime:
    """Start of the fixed `interval_s` bucket containing t (aligned to the Unix epoch)."""
    secs = (t - EPOCH).total_seconds()
    return EPOCH + timedelta(seconds=math.floor(secs / interval_s) * interval_s)


def trend(
    history: list[tuple[datetime, float]], current: float, now: datetime, lookback_s: float, threshold: float
) -> tuple[int, float]:
    """(+1 up / 0 flat / −1 down, fractional change) versus the last price at or before now − lookback."""
    then = now - timedelta(seconds=lookback_s)
    old = None
    for at, p in history:
        if at <= then:
            old = p
        else:
            break
    if old is None and history:
        old = history[0][1]
    if not old:
        return 0, 0.0
    change = (current - old) / old
    if change > threshold:
        return 1, change
    if change < -threshold:
        return -1, change
    return 0, change


def sparkline(
    history: list[tuple[datetime, float]], current: float, now: datetime, span_s: float, points: int
) -> list[float]:
    """`points` evenly spaced samples over the last `span_s` (step-held). Before the first recorded
    price the line starts at that first price; the last point is always the live price."""
    if not history:
        return [round(current, 3)]
    times = [h[0] for h in history]
    out: list[float] = []
    for i in range(points - 1):
        t = now - timedelta(seconds=span_s * (1 - (i + 1) / points))
        j = bisect_right(times, t) - 1
        out.append(round(history[max(j, 0)][1], 3))
    out.append(round(current, 3))
    return out


# ── the wandering merchant ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Slot:
    slot: int
    stock_key: str
    price: int
    deal: bool


@dataclass(frozen=True)
class Rotation:
    index: int
    starts_at: datetime
    ends_at: datetime
    spot: tuple[int, int]
    greeting: str
    slots: tuple[Slot, ...]


def _seed(*parts: object) -> int:
    h = hashlib.blake2b(":".join(str(p) for p in parts).encode(), digest_size=8).digest()
    return int.from_bytes(h, "big")


def rotation_index(cfg: MerchantCfg, now: datetime) -> int:
    return math.floor((now - EPOCH).total_seconds() / cfg.rotation)


def rotation(cfg: MerchantCfg, merchant_id: str, index: int) -> Rotation:
    """Everything about one rotation, derived from (merchant id, index) alone: same input, same cart."""
    rng = random.Random(_seed("merchant", merchant_id, index))
    # weighted sample without replacement (Efraimidis–Spirakis): highest u^(1/w) wins
    keyed = sorted(((rng.random() ** (1 / s.weight), k) for k, s in cfg.stock.items()), reverse=True)
    picks = [k for _, k in keyed[: cfg.slots]]
    deal = rng.randrange(len(picks))
    slots = tuple(
        Slot(
            i,
            k,
            max(1, round(cfg.stock[k].price * (1 - cfg.deal_discount))) if i == deal else cfg.stock[k].price,
            i == deal,
        )
        for i, k in enumerate(picks)
    )
    n = len(cfg.spots)
    base = _seed("spot", merchant_id) % n
    spot = cfg.spots[(base + index * 2) % n] if n > 2 else cfg.spots[index % n]
    greeting = cfg.greetings[rng.randrange(len(cfg.greetings))]
    start = EPOCH + timedelta(seconds=index * cfg.rotation)
    return Rotation(index, start, start + timedelta(seconds=cfg.rotation), spot, greeting, slots)


def hint_pick(candidates: list[str], user_id: str, index: int) -> str:
    """Which undiscovered combo a bought hint reveals: stable per player and rotation."""
    rng = random.Random(_seed("hint", user_id, index))
    return sorted(candidates)[rng.randrange(len(candidates))]
