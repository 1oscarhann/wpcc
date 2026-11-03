"""Plot helpers shared by signup, the village service and the map API."""

from __future__ import annotations

import uuid

from hearthforge.config.loader import GameConfig
from hearthforge.domain import mapgen, plotlayout


def gate(cfg: GameConfig, plot_index: int) -> tuple[int, int, str]:
    lay = mapgen.layout(cfg.mapgen)
    return plotlayout.gate(plotlayout.template(cfg), lay.plot_origins[plot_index], (lay.center, lay.center))


def path(cfg: GameConfig, plot_index: int) -> frozenset[tuple[int, int]]:
    return plotlayout.village_path(plotlayout.template(cfg), gate(cfg, plot_index))


def debris_seed(village_id: uuid.UUID) -> int:
    return village_id.int & 0x7FFFFFFFFFFF
