"""Phase 16: the skill tree. Pure: points, learning rules and the perks a set of ranks adds up to."""

from __future__ import annotations

from collections.abc import Mapping

from hearthforge.config.loader import GameConfig


def points_total(cfg: GameConfig, level: int) -> int:
    return max(0, level - 1) * cfg.skills.points_per_level


def spent(skills: Mapping[str, int]) -> int:
    return sum(int(v) for v in skills.values())


def node(cfg: GameConfig, key: str) -> tuple[str, object] | None:
    for bk, br in cfg.skills.branches.items():
        if key in br.nodes:
            return bk, br.nodes[key]
    return None


def learn_error(cfg: GameConfig, skills: Mapping[str, int], level: int, key: str) -> str | None:
    """Why `key` can't take another rank right now (None = it can)."""
    found = node(cfg, key)
    if found is None:
        return "unknown_skill"
    bk, n = found
    rank = int(skills.get(key, 0))
    if rank >= n.max:  # type: ignore[attr-defined]
        return "maxed"
    if spent(skills) >= points_total(cfg, level):
        return "no_points"
    for r in n.requires:  # type: ignore[attr-defined]
        if int(skills.get(r, 0)) < 1:
            return "locked"
    in_branch = sum(int(skills.get(k, 0)) for k in cfg.skills.branches[bk].nodes)
    if in_branch < n.branch_points:  # type: ignore[attr-defined]
        return "locked"
    return None


def perks(cfg: GameConfig, skills: Mapping[str, int]) -> dict[str, float]:
    out: dict[str, float] = {}
    for br in cfg.skills.branches.values():
        for k, n in br.nodes.items():
            rank = int(skills.get(k, 0))
            if rank <= 0:
                continue
            for eff, per in n.effects.items():
                out[eff] = out.get(eff, 0.0) + per * min(rank, n.max)
    return out


def with_pet(cfg: GameConfig, skills: Mapping[str, int], pet: str | None) -> dict[str, float]:
    """Skill perks plus the active pet's (Phase 16b): the one set every system reads."""
    out = perks(cfg, skills)
    pc = cfg.companions.pets.get(pet or "")
    if pc is not None:
        for eff, v in pc.perks.items():
            out[eff] = out.get(eff, 0.0) + v
    return out


def respec_cost(cfg: GameConfig, level: int, respecs: int) -> int:
    if respecs == 0 and cfg.skills.respec.free_first:
        return 0
    return cfg.skills.respec.coins_per_level * level
