"""Pydantic models for every /config/*.yaml file. Unknown keys are errors (extra="forbid")."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)\s*$")
_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(v: object) -> float:
    """'45s' | '5m' | '1h' | '30d' | number (seconds) → seconds."""
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        m = _DURATION.match(v)
        if m:
            return float(m.group(1)) * _UNITS[m.group(2)]
    raise ValueError(f"not a duration: {v!r} (use e.g. '45s', '5m', '1h')")


Duration = Annotated[float, BeforeValidator(parse_duration)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── game.yaml ────────────────────────────────────────────────────────────────


class BonusSlot(Strict):
    town_hall: int
    slots: int


class BuildQueue(Strict):
    base_slots: int = Field(ge=1)
    bonus_slots: list[BonusSlot] = []


class Refunds(Strict):
    cancel: float = Field(ge=0, le=1)
    demolish: float = Field(ge=0, le=1)
    undo_window: Duration


class Gates(Strict):
    intermediates_enabled: bool
    rare_costs_enabled: bool
    villagers_enabled: bool


class AuthCfg(Strict):
    username_min: int
    username_max: int
    password_min: int = Field(ge=8)
    session_ttl: Duration
    recovery_codes: int = Field(ge=1, le=20)


class RateLimits(Strict):
    auth_per_ip_per_min: int
    auth_per_username_per_min: int
    actions_per_min: int
    preview_per_min: int


class GameCfg(Strict):
    max_timer_seconds: int
    tick_rate_hz: int
    build_queue: BuildQueue
    refunds: Refunds
    gates: Gates
    auth: AuthCfg
    rate_limits: RateLimits


# ── resources.yaml / items.yaml ─────────────────────────────────────────────


class ResourceDef(Strict):
    name: str
    kind: Literal["raw", "intermediate"]
    icon: str
    cap_fraction: float = 1.0


class ResourcesCfg(Strict):
    resources: dict[str, ResourceDef]
    hud_order: list[str]


class ItemDefCfg(Strict):
    name: str
    category: Literal[
        "material",
        "rare_material",
        "intermediate",
        "weapon",
        "offhand",
        "armour",
        "trinket",
        "consumable",
        "blueprint",
        "cosmetic",
        "trophy",
        "fish",
    ]
    stackable: bool
    max_stack: int = 1
    weapon_type: str | None = None
    icon: str


class ItemsCfg(Strict):
    items: dict[str, ItemDefCfg]
    resource_max_stack: int


# ── buildings.yaml ───────────────────────────────────────────────────────────


class Conversion(Strict):
    item: str
    ratio: int = Field(ge=1)


class LevelCurve(Strict):
    times: list[Duration]
    cost_mult: list[float]
    extra_coins: list[int]
    intermediates_from_level: int
    intermediates: dict[str, Conversion]
    rare_at_level: int
    rare_cost: dict[str, dict[str, int]]


class ExplicitLevel(Strict):
    cost: dict[str, int]
    time: Duration


class BuildingCfg(Strict):
    name: str
    description: str
    category: Literal["core", "production", "crafting", "defence", "special", "decoration"]
    footprint: tuple[int, int]
    unlock_town_hall: int = Field(default=1, ge=1, le=5)
    max_count: list[int]
    max_level: int = 5
    base_cost: dict[str, int] = {}
    levels: list[ExplicitLevel] | None = None
    produces: dict[str, list[float]] = {}
    storage_base: list[int] | None = None
    storage_bonus: list[int] | None = None
    housing: list[int] | None = None
    requires_water: bool = False
    rare_group: str = "default"
    demolishable: bool = True

    @field_validator("footprint")
    @classmethod
    def _fp(cls, v: tuple[int, int]) -> tuple[int, int]:
        if not (1 <= v[0] <= 6 and 1 <= v[1] <= 6):
            raise ValueError("footprint must be within 1..6 tiles per side")
        return v


class BuildingsCfg(Strict):
    level_curve: LevelCurve
    buildings: dict[str, BuildingCfg]


# ── avatar.yaml ──────────────────────────────────────────────────────────────


class BaseStats(Strict):
    hp: int
    stamina: int
    attack: int
    defence: int
    crit_chance: float
    move_speed: float


class PerLevel(Strict):
    hp: int
    stamina: int
    attack: int
    defence: int


class CreatorCfg(Strict):
    bodies: list[str]
    skin_tones: list[str]
    hair_styles: list[str]
    hair_colors: list[str]
    eye_styles: list[str]
    eye_colors: list[str]
    outfits: list[str]
    outfit_colors: list[str]


class Appearance(Strict):
    body: str
    skin: str
    hair_style: str
    hair_color: str
    eyes: str
    eye_color: str
    outfit: str
    outfit_color: str


class AvatarCfg(Strict):
    base_stats: BaseStats
    per_level: PerLevel
    level_cap: int
    creator: CreatorCfg
    default_appearance: Appearance


# ── starter.yaml ─────────────────────────────────────────────────────────────


class StarterBuilding(Strict):
    key: str
    level: int
    x: int
    y: int


class StarterItem(Strict):
    container: Literal["inventory", "bank", "equipment", "mailbox"]
    slot: int
    item: str
    quantity: int = 1
    tier: int | None = None
    rarity: Literal["common", "uncommon", "rare", "epic", "legendary"] | None = None
    durability: int | None = None


class StarterCfg(Strict):
    coins: int
    resources: dict[str, int]
    buildings: list[StarterBuilding]
    containers: dict[Literal["inventory", "bank", "equipment", "mailbox"], int]
    items: list[StarterItem]
    village_name_suffix: str
    realm_name_suffix: str


# ── mapgen.yaml ──────────────────────────────────────────────────────────────


class Rect(Strict):
    x: int
    y: int
    w: int
    h: int


class PlotCfg(Strict):
    count: int = Field(ge=1, le=10)
    ring_radius: int
    frame: int
    start_size: int
    max_size: int
    expand_step: int
    clear_margin: int
    pond: Rect


class MeadowCfg(Strict):
    flower_patch_threshold: float
    tree_density_near: float
    tree_density_far: float
    rock_density: float
    bush_density: float
    tall_grass_density: float


class MapgenCfg(Strict):
    version: int
    map_size: int
    chunk_size: int
    hub_radius: int
    plot: PlotCfg
    meadow: MeadowCfg


# ── profanity.yaml ───────────────────────────────────────────────────────────


class ProfanityCfg(Strict):
    leet: dict[str, str]
    blocked: list[str]
    allowed: list[str] = []
    reserved: list[str] = []


# ── debris.yaml ──────────────────────────────────────────────────────────────


class DebrisBonus(Strict):
    chance: float = Field(ge=0, le=1)
    qty: int = Field(ge=1)


class DebrisKind(Strict):
    sprites: list[str] = Field(min_length=1)
    weight: float = Field(gt=0)
    yields: dict[str, int]
    bonus: dict[str, DebrisBonus] = {}


class DebrisCfg(Strict):
    density: float = Field(ge=0, le=0.5)
    keep_clear_radius: int = Field(ge=0)
    avoid_buildings: int = Field(ge=0)
    kinds: dict[str, DebrisKind]
