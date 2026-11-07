"""What the browser gets from GET /api/config. Secret sections (combos, secret POIs…) are never included."""

from __future__ import annotations

from typing import Any

from hearthforge.config.loader import GameConfig
from hearthforge.sim.rules import WORLD, resolve
from hearthforge.sim.stats import xp_to_next


def client_bundle(cfg: GameConfig) -> dict[str, Any]:
    plot = cfg.mapgen.plot
    return {
        "hash": cfg.hash,
        "game": {
            "build_queue": cfg.game.build_queue.model_dump(),
            "refunds": cfg.game.refunds.model_dump(),
            "gates": cfg.game.gates.model_dump(),
            "auth": {
                "username_min": cfg.game.auth.username_min,
                "username_max": cfg.game.auth.username_max,
                "password_min": cfg.game.auth.password_min,
            },
        },
        "resources": {
            k: {"name": r.name, "kind": r.kind, "icon": r.icon} for k, r in cfg.resources.resources.items()
        },
        "hud_order": cfg.resources.hud_order,
        "items": {
            k: {
                "name": i.name,
                "category": i.category,
                "stackable": i.stackable,
                "icon": i.icon,
                **({"weapon_type": i.weapon_type} if getattr(i, "weapon_type", None) else {}),
                **({"offhand_type": i.offhand_type} if getattr(i, "offhand_type", None) else {}),
                **({"use": i.use.model_dump()} if getattr(i, "use", None) else {}),
            }
            for k, i in cfg.items.items()
        },
        "buildings": {
            key: {
                "name": b.cfg.name,
                "description": b.cfg.description,
                "category": b.cfg.category,
                "footprint": list(b.cfg.footprint),
                "unlock_town_hall": b.cfg.unlock_town_hall,
                "max_count": b.cfg.max_count,
                "max_level": b.cfg.max_level,
                "requires_water": b.cfg.requires_water,
                "demolishable": b.cfg.demolishable,
                # Phases 13/14: worker/guard slots per level, watchtower damage, decoration beauty
                "jobs": b.cfg.jobs or cfg.villagers.jobs.by_category.get(b.cfg.category),
                "tower_dmg": b.cfg.tower_dmg,
                "beauty": b.cfg.beauty,
                "walkable": b.cfg.walkable,
                "requires_item": b.cfg.requires_item,
                "levels": [
                    {
                        "level": lv.level,
                        "cost": lv.cost,
                        "time_s": lv.time_s,
                        "production": lv.production,
                        "storage": lv.storage,
                        "housing": lv.housing,
                    }
                    for lv in b.levels
                ],
            }
            for key, b in cfg.buildings.items()
        },
        "waves": {
            "min_town_hall": cfg.waves.eligible.min_town_hall,
            "warning_s": cfg.waves.warning,
            "steal_max": cfg.waves.steal.max_fraction,
        },
        "bosses": {
            k: {"name": b.name, "biome": b.biome, "enemy": b.enemy, "trophy": b.loot.trophy}
            for k, b in cfg.bosses.bosses.items()
        },
        "villagers": {
            "lines": cfg.villagers.lines.model_dump(),
            "schedule": cfg.villagers.schedule.model_dump(),
            "food_per_villager": cfg.villagers.food_per_villager,
            "weights": dict(cfg.villagers.happiness.weights),
            "production_bonus": cfg.villagers.jobs.production_bonus,
            "crafting_speed": cfg.villagers.jobs.crafting_speed,
            "arrival_every_s": cfg.villagers.arrival.every,
            "min_happiness": cfg.villagers.arrival.min_happiness,
            "leave_below": cfg.villagers.leaving.below,
        },
        "avatar": {
            "base_stats": cfg.avatar.base_stats.model_dump(),
            "per_level": cfg.avatar.per_level.model_dump(),
            "creator": cfg.avatar.creator.model_dump(),
            "default_appearance": cfg.avatar.default_appearance.model_dump(),
            "pickup_radius": cfg.avatar.pickup_radius,
            "xp_to_next": [xp_to_next(cfg, lv) for lv in range(1, cfg.avatar.level_cap + 1)],
        },
        # Avatar Mode: the predictor's exact tick-based rules plus the collision rules (shared/world.json)
        "sim": resolve(cfg).bundle(),
        "world": WORLD,
        "nodes": {
            k: {"objects": n.objects, "biome": n.biome, "hits": n.hits, "yields": n.yields, "sound": n.sound}
            for k, n in cfg.nodes.nodes.items()
        },
        "combat": {
            "combat_lock_s": cfg.combat.combat_lock,
            "weapons": {
                k: {"ability": w.ability.kind, "ability_cd_s": w.ability.cooldown}
                for k, w in cfg.combat.weapons.items()
            },
            "offhands": {
                "shield": {"block": cfg.combat.offhands.shield.block},
                "bombs": {
                    "charges": cfg.combat.offhands.bombs.charges,
                    "recharge_s": cfg.combat.offhands.bombs.recharge,
                },
                "tome": {"cooldown_s": cfg.combat.offhands.tome.cooldown},
            },
        },
        # Phase 6 (public parts only: combos.yaml is secret, P17)
        "recipes": {
            "intermediates": {
                k: {
                    "station": r.station,
                    "inputs": r.inputs,
                    "seconds_per_unit": r.time,
                    "max_batch": r.max_batch,
                }
                for k, r in cfg.recipes.intermediates.items()
            },
            "gear": {k: {"station": g.station} for k, g in cfg.recipes.gear.items()},
            "consumables": {k: {"station": c.station} for k, c in cfg.recipes.consumables.items()},
        },
        "forging": {
            "tiers": [{"name": t.name, "durability": t.durability} for t in cfg.forging.tiers],
            "rarities": [r.key for r in cfg.forging.rarities],
            "modifiers": {k: {"name": m.name, "effect": m.effect} for k, m in cfg.forging.modifiers.items()},
            "max_rare_inputs": cfg.forging.max_rare_inputs,
            "armour": cfg.forging.armour,
        },
        "enemies": {
            k: {"name": e.name, "elite_name": e.elite_name, "archetype": e.archetype, "radius": e.radius}
            for k, e in cfg.enemies.enemies.items()
        },
        "plot": {
            "frame": plot.frame,
            "start_size": plot.start_size,
            "max_size": plot.max_size,
            "pond": plot.pond.model_dump(),
        },
        "map": {
            "size": cfg.mapgen.map_size,
            "chunk_size": cfg.mapgen.chunk_size,
            "bands": [{"biome": b.biome, "radius": b.radius} for b in cfg.mapgen.bands],
        },
        "debris": {k: {"sprites": d.sprites, "yields": d.yields} for k, d in cfg.debris.kinds.items()},
        "world_clock": {
            "day_length": cfg.world_clock.day_cycle.length,
            "phases": cfg.world_clock.day_cycle.phases,
            "season_length": cfg.world_clock.season_length,
            "seasons": cfg.world_clock.seasons,
            "weather_block": cfg.world_clock.weather.block,
        },
    }
