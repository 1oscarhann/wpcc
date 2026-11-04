"""Avatar stats and XP (BALANCE §4). Pure."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stats:
    hp_max: int
    st_max: float
    attack: int
    defence: int
    crit: float


def stats_for(cfg, level: int) -> Stats:  # noqa: ANN001 - GameConfig
    b, p = cfg.avatar.base_stats, cfg.avatar.per_level
    n = level - 1
    return Stats(
        hp_max=b.hp + p.hp * n,
        st_max=float(b.stamina + p.stamina * n),
        attack=b.attack + p.attack * n,
        defence=b.defence + p.defence * n,
        crit=b.crit_chance,
    )


def xp_to_next(cfg, level: int) -> int:  # noqa: ANN001
    c = cfg.avatar.xp_curve
    return round(c.a * level**c.p + c.b)


def add_xp(cfg, level: int, xp: int, amount: int) -> tuple[int, int, int]:  # noqa: ANN001
    """Returns (level, xp into that level, levels gained). XP stops at the level cap."""
    cap = cfg.avatar.level_cap
    xp += amount
    gained = 0
    while level < cap and xp >= xp_to_next(cfg, level):
        xp -= xp_to_next(cfg, level)
        level += 1
        gained += 1
    if level >= cap:
        xp = 0
    return level, xp, gained
