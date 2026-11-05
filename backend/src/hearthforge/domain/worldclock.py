"""Day/night, seasons and weather as pure functions of time (Phase 10, P9).

The day cycle and seasons are global (every realm shares the sun). Weather is per realm: block `i` of
`weather.block` seconds picks a state by the current season's weights with a hash of (weather_seed, i),
so it needs no storage, no worker and no syncing.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hearthforge.config.schemas import WorldClockCfg

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _secs(t: datetime) -> float:
    return (t - EPOCH).total_seconds()


@dataclass(frozen=True)
class DayPhase:
    name: str  # dawn | day | dusk | night
    progress: float  # 0..1 through this phase
    cycle: float  # 0..1 through the whole day


def day_phase(cfg: WorldClockCfg, t: datetime) -> DayPhase:
    length = cfg.day_cycle.length
    pos = _secs(t) % length
    acc = 0.0
    for name, dur in cfg.day_cycle.phases.items():
        if pos < acc + dur:
            return DayPhase(name, (pos - acc) / dur, pos / length)
        acc += dur
    return DayPhase("night", 1.0, pos / length)


def is_night(cfg: WorldClockCfg, t: datetime) -> bool:
    return day_phase(cfg, t).name == "night"


def season(cfg: WorldClockCfg, t: datetime) -> str:
    i = math.floor(_secs(t) / cfg.season_length) % len(cfg.seasons)
    return cfg.seasons[i]


def season_ends(cfg: WorldClockCfg, t: datetime) -> datetime:
    n = math.floor(_secs(t) / cfg.season_length) + 1
    return EPOCH + timedelta(seconds=n * cfg.season_length)


def _u01(seed: int, block: int) -> float:
    h = hashlib.blake2b(f"weather:{seed}:{block}".encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2**64


def block_index(cfg: WorldClockCfg, t: datetime) -> int:
    return math.floor(_secs(t) / cfg.weather.block)


def block_start(cfg: WorldClockCfg, i: int) -> datetime:
    return EPOCH + timedelta(seconds=i * cfg.weather.block)


def weather_for_block(cfg: WorldClockCfg, seed: int, i: int) -> str:
    """The season is read at the block's midpoint, so a block never straddles two seasons' weights."""
    mid = block_start(cfg, i) + timedelta(seconds=cfg.weather.block / 2)
    s = season(cfg, mid)
    weights = [(k, st.weights.get(s, 0)) for k, st in cfg.weather.states.items()]
    total = sum(w for _, w in weights)
    if total <= 0:
        return next(iter(cfg.weather.states))
    r = _u01(seed, i) * total
    acc = 0.0
    for k, w in weights:
        acc += w
        if r < acc:
            return k
    return weights[-1][0]


def weather_at(cfg: WorldClockCfg, seed: int, t: datetime) -> str:
    return weather_for_block(cfg, seed, block_index(cfg, t))


def segments(
    cfg: WorldClockCfg, seed: int, t0: datetime, t1: datetime
) -> list[tuple[datetime, datetime, str]]:
    """Weather blocks overlapping [t0, t1), clipped to it."""
    out: list[tuple[datetime, datetime, str]] = []
    if t1 <= t0:
        return out
    i = block_index(cfg, t0)
    while True:
        a = max(t0, block_start(cfg, i))
        b = min(t1, block_start(cfg, i + 1))
        if a >= t1:
            break
        out.append((a, b, weather_for_block(cfg, seed, i)))
        if b >= t1:
            break
        i += 1
    return out


def production_mult(cfg: WorldClockCfg, weather: str, resource: str) -> float:
    st = cfg.weather.states.get(weather)
    return st.production.get(resource, 1.0) if st else 1.0


def forecast(cfg: WorldClockCfg, seed: int, t: datetime, n: int = 4) -> list[dict[str, object]]:
    i = block_index(cfg, t)
    return [
        {
            "weather": weather_for_block(cfg, seed, i + k),
            "starts_ms": int(block_start(cfg, i + k).timestamp() * 1000),
            "ends_ms": int(block_start(cfg, i + k + 1).timestamp() * 1000),
        }
        for k in range(n)
    ]
