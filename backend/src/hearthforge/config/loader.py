"""Load /config/*.yaml → validated, cross-checked, frozen GameConfig (+ content hash + client bundle).

Any error aborts startup with `file:path: reason` lines. `hf config check` runs the same code in CI.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from hearthforge.config import schemas as s

log = logging.getLogger(__name__)

FILES: dict[str, type[BaseModel]] = {
    "game": s.GameCfg,
    "resources": s.ResourcesCfg,
    "items": s.ItemsCfg,
    "buildings": s.BuildingsCfg,
    "avatar": s.AvatarCfg,
    "starter": s.StarterCfg,
    "mapgen": s.MapgenCfg,
    "profanity": s.ProfanityCfg,
    "debris": s.DebrisCfg,
    "nodes": s.NodesCfg,
    "combat": s.CombatCfg,
    "enemies": s.EnemiesCfg,
}


class ConfigError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("invalid game config:\n  " + "\n  ".join(errors))


@dataclass(frozen=True)
class ResolvedLevel:
    level: int
    cost: dict[str, int]  # resource keys, item keys and "coins"
    time_s: int
    production: dict[str, float]  # units/hour at this level (staffed)
    storage: int | None = None  # town hall base cap / storehouse bonus at this level
    housing: int | None = None


@dataclass(frozen=True)
class ResolvedBuilding:
    key: str
    cfg: s.BuildingCfg
    levels: tuple[ResolvedLevel, ...]  # index 0 = level 1

    @property
    def footprint(self) -> tuple[int, int]:
        return self.cfg.footprint

    def level(self, n: int) -> ResolvedLevel:
        return self.levels[n - 1]

    def max_count(self, town_hall_level: int) -> int:
        return self.cfg.max_count[town_hall_level - 1]


@dataclass(frozen=True)
class ItemInfo:
    key: str
    name: str
    category: str
    stackable: bool
    max_stack: int
    icon: str


@dataclass(frozen=True)
class GameConfig:
    game: s.GameCfg
    resources: s.ResourcesCfg
    items_cfg: s.ItemsCfg
    buildings_cfg: s.BuildingsCfg
    avatar: s.AvatarCfg
    starter: s.StarterCfg
    mapgen: s.MapgenCfg
    profanity: s.ProfanityCfg
    debris: s.DebrisCfg
    nodes: s.NodesCfg
    combat: s.CombatCfg
    enemies: s.EnemiesCfg
    buildings: dict[str, ResolvedBuilding]
    items: dict[str, ItemInfo]
    hash: str
    warnings: tuple[str, ...] = field(default=())

    @property
    def resource_keys(self) -> list[str]:
        return list(self.resources.resources)

    def build_queue_slots(self, town_hall_level: int) -> int:
        q = self.game.build_queue
        return q.base_slots + sum(b.slots for b in q.bonus_slots if town_hall_level >= b.town_hall)

    def summary(self) -> dict[str, Any]:
        return {
            "buildings": len(self.buildings),
            "items": len(self.items),
            "resources": len(self.resource_keys),
        }


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fmt_validation(file: str, err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"])
        out.append(f"{file}.yaml:{loc}: {e['msg']}")
    return out


def _resolve_building(
    key: str,
    b: s.BuildingsCfg,
    cfg: s.BuildingCfg,
    gates: s.Gates,
    rare_items: set[str],
) -> ResolvedBuilding:
    curve = b.level_curve
    levels: list[ResolvedLevel] = []
    for n in range(1, cfg.max_level + 1):
        if cfg.levels is not None:
            raw_cost = dict(cfg.levels[n - 1].cost)
            time_s = cfg.levels[n - 1].time
        else:
            mult = curve.cost_mult[n - 1]
            raw_cost = {k: math.ceil(v * mult) for k, v in cfg.base_cost.items()}
            if curve.extra_coins[n - 1]:
                raw_cost["coins"] = raw_cost.get("coins", 0) + curve.extra_coins[n - 1]
            if n >= curve.intermediates_from_level:
                for src, conv in curve.intermediates.items():
                    if src in raw_cost:
                        half = raw_cost[src] // 2
                        raw_cost[src] -= half
                        raw_cost[conv.item] = raw_cost.get(conv.item, 0) + math.ceil(half / conv.ratio)
            if n == curve.rare_at_level:
                for item, qty in curve.rare_cost.get(cfg.rare_group, {}).items():
                    raw_cost[item] = raw_cost.get(item, 0) + qty
            time_s = curve.times[n - 1]
        cost = _apply_gates(raw_cost, curve, gates, rare_items)
        production = {res: float(rates[n - 1]) for res, rates in cfg.produces.items() if rates[n - 1] > 0}
        storage = None
        if cfg.storage_base is not None:
            storage = cfg.storage_base[n - 1]
        elif cfg.storage_bonus is not None:
            storage = cfg.storage_bonus[n - 1]
        housing = cfg.housing[n - 1] if cfg.housing is not None else None
        levels.append(ResolvedLevel(n, cost, int(time_s), production, storage, housing))
    return ResolvedBuilding(key, cfg, tuple(levels))


def _apply_gates(
    cost: dict[str, int], curve: s.LevelCurve, gates: s.Gates, rare_items: set[str]
) -> dict[str, int]:
    out = dict(cost)
    if not gates.intermediates_enabled:
        for src, conv in curve.intermediates.items():
            if conv.item in out:
                out[src] = out.get(src, 0) + out.pop(conv.item) * conv.ratio
    if not gates.rare_costs_enabled:
        for k in list(out):
            if k in rare_items:
                del out[k]
    return {k: v for k, v in out.items() if v > 0}


def _hash(raw: dict[str, Any]) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_config(config_dir: Path, strict: bool = False) -> GameConfig:
    errors: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    parsed: dict[str, Any] = {}

    for name, model in FILES.items():
        path = config_dir / f"{name}.yaml"
        if not path.exists():
            errors.append(f"{name}.yaml: file missing in {config_dir}")
            continue
        try:
            raw[name] = _read_yaml(path)
        except yaml.YAMLError as e:
            errors.append(f"{name}.yaml: YAML parse error: {e}")
            continue
        try:
            parsed[name] = model.model_validate(raw[name])
        except ValidationError as e:
            errors.extend(_fmt_validation(name, e))
    if errors:
        raise ConfigError(errors)

    game: s.GameCfg = parsed["game"]
    res: s.ResourcesCfg = parsed["resources"]
    items_cfg: s.ItemsCfg = parsed["items"]
    bcfg: s.BuildingsCfg = parsed["buildings"]
    avatar: s.AvatarCfg = parsed["avatar"]
    starter: s.StarterCfg = parsed["starter"]
    mapgen: s.MapgenCfg = parsed["mapgen"]
    profanity: s.ProfanityCfg = parsed["profanity"]
    debris: s.DebrisCfg = parsed["debris"]
    nodes: s.NodesCfg = parsed["nodes"]
    combat: s.CombatCfg = parsed["combat"]
    enemies: s.EnemiesCfg = parsed["enemies"]

    # ── items: every resource is also a stackable item ────────────────────────
    items: dict[str, ItemInfo] = {}
    for key, r in res.resources.items():
        items[key] = ItemInfo(
            key,
            r.name,
            "material" if r.kind == "raw" else "intermediate",
            True,
            items_cfg.resource_max_stack,
            r.icon,
        )
    for key, it in items_cfg.items.items():
        if key in items:
            errors.append(f"items.yaml:items.{key}: clashes with a resource of the same key")
            continue
        items[key] = ItemInfo(
            key, it.name, it.category, it.stackable, it.max_stack if it.stackable else 1, it.icon
        )
    rare_items = {k for k, i in items.items() if i.category == "rare_material"}

    for key in res.hud_order:
        if key not in res.resources:
            errors.append(f"resources.yaml:hud_order: unknown resource '{key}'")

    # ── buildings ─────────────────────────────────────────────────────────────
    curve = bcfg.level_curve
    for arr_name in ("times", "cost_mult", "extra_coins"):
        if len(getattr(curve, arr_name)) != 5:
            errors.append(f"buildings.yaml:level_curve.{arr_name}: needs exactly 5 entries")
    for src, conv in curve.intermediates.items():
        if src not in res.resources or conv.item not in res.resources:
            errors.append(f"buildings.yaml:level_curve.intermediates.{src}: unknown resource")
    for group, req in curve.rare_cost.items():
        for item in req:
            if item not in items:
                errors.append(f"buildings.yaml:level_curve.rare_cost.{group}: unknown item '{item}'")
    if "town_hall" not in bcfg.buildings:
        errors.append("buildings.yaml:buildings: a 'town_hall' building is required")
    elif bcfg.buildings["town_hall"].storage_base is None:
        errors.append("buildings.yaml:buildings.town_hall: needs storage_base")

    cost_keys = set(res.resources) | set(items) | {"coins"}
    for key, b in bcfg.buildings.items():
        where = f"buildings.yaml:buildings.{key}"
        if len(b.max_count) != 5:
            errors.append(f"{where}.max_count: needs 5 entries (Town Hall 1..5)")
        if b.levels is not None and len(b.levels) != b.max_level:
            errors.append(f"{where}.levels: has {len(b.levels)} entries, max_level is {b.max_level}")
        if b.levels is None and not b.base_cost:
            errors.append(f"{where}: needs base_cost or explicit levels")
        for ck in list(b.base_cost) + [k for lv in (b.levels or []) for k in lv.cost]:
            if ck not in cost_keys:
                errors.append(f"{where}: cost key '{ck}' is not a resource, item or 'coins'")
        for rk, rates in b.produces.items():
            if rk not in res.resources:
                errors.append(f"{where}.produces.{rk}: unknown resource")
            if len(rates) != b.max_level:
                errors.append(f"{where}.produces.{rk}: needs {b.max_level} entries")
        for arr in ("storage_base", "storage_bonus", "housing"):
            v = getattr(b, arr)
            if v is not None and len(v) != b.max_level:
                errors.append(f"{where}.{arr}: needs {b.max_level} entries")
        if b.rare_group not in curve.rare_cost:
            errors.append(f"{where}.rare_group: '{b.rare_group}' not in level_curve.rare_cost")
    if errors:
        raise ConfigError(errors)

    buildings = {
        key: _resolve_building(key, bcfg, b, game.gates, rare_items) for key, b in bcfg.buildings.items()
    }
    for key, rb in buildings.items():
        for lv in rb.levels:
            if lv.time_s > game.max_timer_seconds:
                errors.append(
                    f"buildings.yaml:buildings.{key}: level {lv.level} takes {lv.time_s}s, "
                    f"over max_timer_seconds={game.max_timer_seconds}"
                )
        totals = [sum(v for k, v in lv.cost.items() if k != "coins") for lv in rb.levels]
        for i in range(2, len(totals)):
            if totals[i] < totals[i - 1]:
                warnings.append(f"buildings.yaml:buildings.{key}: level {i + 1} costs less than level {i}")

    # ── avatar ────────────────────────────────────────────────────────────────
    cr, ap = avatar.creator, avatar.default_appearance
    for fld, options in (
        ("body", cr.bodies),
        ("skin", cr.skin_tones),
        ("hair_style", cr.hair_styles),
        ("hair_color", cr.hair_colors),
        ("eyes", cr.eye_styles),
        ("eye_color", cr.eye_colors),
        ("outfit", cr.outfits),
        ("outfit_color", cr.outfit_colors),
    ):
        if getattr(ap, fld) not in options:
            errors.append(
                f"avatar.yaml:default_appearance.{fld}: '{getattr(ap, fld)}' is not an allowed option"
            )

    # ── starter ───────────────────────────────────────────────────────────────
    for rk in starter.resources:
        if rk not in res.resources:
            errors.append(f"starter.yaml:resources.{rk}: unknown resource")
    plot = mapgen.plot
    lo = (plot.frame - plot.start_size) // 2
    hi = lo + plot.start_size
    rects: list[tuple[int, int, int, int]] = []
    if not any(sb.key == "town_hall" for sb in starter.buildings):
        errors.append("starter.yaml:buildings: must include the town_hall")
    for i, sb in enumerate(starter.buildings):
        if sb.key not in buildings:
            errors.append(f"starter.yaml:buildings.{i}: unknown building '{sb.key}'")
            continue
        w, h = buildings[sb.key].footprint
        if not (lo <= sb.x and sb.x + w <= hi and lo <= sb.y and sb.y + h <= hi):
            errors.append(f"starter.yaml:buildings.{i}: '{sb.key}' is outside the starting plot square")
        rects.append((sb.x, sb.y, w, h))
    pond = plot.pond
    rects_all = rects + [(pond.x, pond.y, pond.w, pond.h)]
    for i in range(len(rects_all)):
        for j in range(i + 1, len(rects_all)):
            a, b2 = rects_all[i], rects_all[j]
            if a[0] < b2[0] + b2[2] and b2[0] < a[0] + a[2] and a[1] < b2[1] + b2[3] and b2[1] < a[1] + a[3]:
                errors.append(f"starter.yaml:buildings: starting buildings/pond overlap ({a} vs {b2})")
    if not (lo <= pond.x and pond.x + pond.w <= hi and lo <= pond.y and pond.y + pond.h <= hi):
        errors.append("mapgen.yaml:plot.pond: must be inside the starting plot square")
    for i, it in enumerate(starter.items):
        if it.item not in items:
            errors.append(f"starter.yaml:items.{i}: unknown item '{it.item}'")
        elif not items[it.item].stackable and it.quantity != 1:
            errors.append(f"starter.yaml:items.{i}: non-stackable items must have quantity 1")
        if it.slot >= starter.containers.get(it.container, 0):
            errors.append(f"starter.yaml:items.{i}: slot {it.slot} outside the {it.container} capacity")

    for dk, kind in debris.kinds.items():
        for rk in list(kind.yields) + list(kind.bonus):
            if rk not in res.resources:
                errors.append(f"debris.yaml:kinds.{dk}: yields unknown resource '{rk}'")

    # ── nodes / combat / enemies ──────────────────────────────────────────────
    from hearthforge.domain.mapgen import OBJECT_NAMES

    for nk, node in nodes.nodes.items():
        where = f"nodes.yaml:nodes.{nk}"
        for ik in list(node.yields) + list(node.bonus):
            if ik not in items:
                errors.append(f"{where}: yields unknown item/resource '{ik}'")
        for prefix in node.objects:
            if not any(o == prefix or o.startswith(prefix + ".") for o in OBJECT_NAMES):
                errors.append(f"{where}.objects: no map object called '{prefix}'")
    for ik, it in items_cfg.items.items():
        if it.category == "weapon" and it.weapon_type not in combat.weapons:
            errors.append(f"items.yaml:items.{ik}: weapon_type '{it.weapon_type}' has no combat.yaml moveset")
    for ek, en in enemies.enemies.items():
        for i, drop in enumerate(en.loot):
            if drop.item not in items:
                errors.append(f"enemies.yaml:enemies.{ek}.loot.{i}: unknown item '{drop.item}'")
    for bk, biome in enemies.biomes.items():
        for ek in biome.roster:
            if ek not in enemies.enemies:
                errors.append(f"enemies.yaml:biomes.{bk}.roster: unknown enemy '{ek}'")
    if not mapgen.plot.ring_radius + mapgen.plot.frame < mapgen.forest.radius < mapgen.map_size // 2:
        errors.append("mapgen.yaml:forest.radius: must sit between the plot ring and the map edge")

    if mapgen.map_size % mapgen.chunk_size:
        errors.append("mapgen.yaml:map_size: must be a multiple of chunk_size")

    if errors:
        raise ConfigError(errors)
    if strict and warnings:
        raise ConfigError([f"(strict) {w}" for w in warnings])
    for w in warnings:
        log.warning("config: %s", w)

    return GameConfig(
        game=game,
        resources=res,
        items_cfg=items_cfg,
        buildings_cfg=bcfg,
        avatar=avatar,
        starter=starter,
        mapgen=mapgen,
        profanity=profanity,
        debris=debris,
        nodes=nodes,
        combat=combat,
        enemies=enemies,
        buildings=buildings,
        items=items,
        hash=_hash(raw),
        warnings=tuple(warnings),
    )
