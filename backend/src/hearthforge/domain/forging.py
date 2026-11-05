"""Forging maths (BALANCE §5.2–5.5): bills, rarity and modifier rolls, durability, repair, salvage. Pure.

Rolls are seeded per job (`roll_seed`), so collecting the same job always gives the same item.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

RARITIES = ["common", "uncommon", "rare", "epic", "legendary"]


def bill(cfg, gear: str, tier: int) -> dict[str, int]:  # noqa: ANN001 - GameConfig
    """Resources + coins to forge `gear` at `tier` (1 = copper)."""
    g = cfg.recipes.gear[gear]
    t = cfg.forging.tiers[tier - 1]
    # copper uses raw resources; iron and up use intermediates × the tier's multiplier
    out = dict(g.copper) if tier == 1 else {k: math.ceil(v * t.material_mult) for k, v in g.base.items()}
    if t.coins:
        out["coins"] = out.get("coins", 0) + t.coins
    if t.crystal:
        out["crystal"] = out.get("crystal", 0) + t.crystal
    return out


def forge_seconds(cfg, tier: int) -> int:  # noqa: ANN001
    return int(cfg.forging.tiers[tier - 1].time)


def rarity_odds(cfg, luck: float, legendary_eligible: bool, rares: int = 0) -> list[float]:  # noqa: ANN001
    """Probabilities for common → legendary. Without eligibility, legendary's weight folds into epic (P8).
    Any rare material added lifts the floor to Uncommon, so its modifier always has a slot (D-052)."""
    f = cfg.forging
    w = [r.weight * math.exp(f.luck_k * luck * i) for i, r in enumerate(f.rarities)]
    if not legendary_eligible:
        w[3] += w[4]
        w[4] = 0.0
    if rares > 0:
        w[1] += w[0]
        w[0] = 0.0
    total = sum(w)
    return [x / total for x in w]


@dataclass
class Forged:
    rarity: str
    modifiers: list[dict[str, Any]] = field(default_factory=list)
    durability: int = 0


def roll(cfg, seed: int, tier: int, luck: float, rares: list[str], legendary_eligible: bool) -> Forged:  # noqa: ANN001
    f = cfg.forging
    rng = random.Random(seed)
    odds = rarity_odds(cfg, luck, legendary_eligible, len(rares))
    u = rng.random()
    idx = len(odds) - 1
    acc = 0.0
    for i, p in enumerate(odds):
        acc += p
        if u < acc:
            idx = i
            break
    rarity = f.rarities[idx]
    mods: list[dict[str, Any]] = []
    for mat in rares[: rarity.slots]:
        m = f.modifiers[mat]
        lo, hi = m.range
        t = max(rarity.value_floor, rng.random())
        mods.append({"key": m.key, "name": m.name, "effect": m.effect, "value": round(lo + (hi - lo) * t, 4)})
    for _ in range(rarity.slots - len(mods)):
        mods.append({"key": "polished", "name": "Polished", "effect": "damage", "value": f.polished})
    return Forged(rarity.key, mods, f.tiers[tier - 1].durability)


def luck_for(cfg, rares: list[str]) -> float:  # noqa: ANN001
    return float(min(len(rares), cfg.forging.max_rare_inputs))


def item_name(cfg, key: str, tier: int) -> str:  # noqa: ANN001
    base = cfg.items[key].name
    if key not in cfg.recipes.gear:
        return base
    return f"{cfg.forging.tiers[tier - 1].name} {base}"


def repair_cost(cfg, tier: int, missing: int) -> dict[str, int]:  # noqa: ANN001
    if missing <= 0:
        return {}
    t = cfg.forging.tiers[tier - 1]
    out = {"coins": math.ceil(missing * t.repair_coins)}
    ingots = math.ceil(missing / cfg.forging.repair_ingots_per)
    if ingots:
        out["ingots"] = ingots
    return out


def salvage_returns(
    cfg, inputs: dict[str, int], rares: list[str], seed: int
) -> tuple[dict[str, int], list[str]]:  # noqa: ANN001
    """40% of the non-coin inputs (rounded down) plus each rare material back at 30%."""
    s = cfg.forging.salvage
    back = {k: math.floor(v * s.fraction) for k, v in inputs.items() if k != "coins"}
    rng = random.Random(seed ^ 0x5A17)
    rare_back = [r for r in rares if rng.random() < s.rare_return]
    return {k: v for k, v in back.items() if v > 0}, rare_back


def weapon_effects(mods: list[dict[str, Any]], dull: bool) -> dict[str, float]:
    """Combat bonuses from modifiers (all off while Dull)."""
    out = {
        "damage": 0.0,
        "crit": 0.0,
        "knockback": 0.0,
        "venom": 0.0,
        "frost": 0.0,
        "fire": 0.0,
        "lifesteal": 0.0,
        "chain": 0.0,
    }
    if dull:
        return out
    for m in mods:
        e = m.get("effect")
        if e in out:
            out[e] += float(m.get("value", 0))
    return out
