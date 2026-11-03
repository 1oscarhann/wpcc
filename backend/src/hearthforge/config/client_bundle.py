"""What the browser gets from GET /api/config. Secret sections (combos, secret POIs…) are never included."""

from __future__ import annotations

from typing import Any

from hearthforge.config.loader import GameConfig


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
            k: {"name": i.name, "category": i.category, "stackable": i.stackable, "icon": i.icon}
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
        "avatar": {
            "base_stats": cfg.avatar.base_stats.model_dump(),
            "per_level": cfg.avatar.per_level.model_dump(),
            "creator": cfg.avatar.creator.model_dump(),
            "default_appearance": cfg.avatar.default_appearance.model_dump(),
        },
        "plot": {
            "frame": plot.frame,
            "start_size": plot.start_size,
            "max_size": plot.max_size,
            "pond": plot.pond.model_dump(),
        },
        "map": {"size": cfg.mapgen.map_size, "chunk_size": cfg.mapgen.chunk_size},
    }
