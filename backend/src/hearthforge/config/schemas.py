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


class ContainerExpansion(Strict):
    step: int = Field(ge=1, le=50)
    costs: list[int] = Field(min_length=1)


class GameCfg(Strict):
    max_timer_seconds: int
    tick_rate_hz: int
    build_queue: BuildQueue
    refunds: Refunds
    gates: Gates
    auth: AuthCfg
    rate_limits: RateLimits
    containers: dict[Literal["inventory", "bank"], ContainerExpansion]


# ── resources.yaml / items.yaml ─────────────────────────────────────────────


class ResourceDef(Strict):
    name: str
    kind: Literal["raw", "intermediate"]
    icon: str
    cap_fraction: float = 1.0


class ResourcesCfg(Strict):
    resources: dict[str, ResourceDef]
    hud_order: list[str]


class UseCfg(Strict):
    """A consumable's effect. `group` shares a cooldown (all potions, all stamina drinks).
    One food buff at a time."""

    heal: float = Field(default=0, ge=0, le=1)  # share of max HP
    stamina: float = Field(default=0, ge=0, le=1)  # share of max stamina, instantly
    regen: float = Field(default=1, ge=1, le=3)  # stamina regen × this for `duration`
    buff: Literal["damage", "defence", "speed"] | None = None
    value: float = Field(default=0, ge=0, le=1)
    duration: Duration = 0
    cooldown: Duration = 0
    group: Literal["potion", "stamina", "food"]


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
    offhand_type: Literal["shield", "bombs", "tome"] | None = None
    icon: str
    use: UseCfg | None = None  # consumables: what drinking/eating it does (Phase 11)


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
    sell_bonus: list[float] | None = None  # market: extra sell price per level (fraction)

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


class XpCurve(Strict):
    a: float = Field(gt=0)
    p: float = Field(gt=0)
    b: float = Field(ge=0)


class RegenCfg(Strict):
    delay: Duration
    per_second: float = Field(ge=0, le=1)


class KoCfg(Strict):
    respawn_delay: Duration
    rare_loss: float = Field(ge=0, le=1)
    drop_lifetime: Duration


class AvatarCfg(Strict):
    base_stats: BaseStats
    per_level: PerLevel
    level_cap: int
    xp_curve: XpCurve
    regen: RegenCfg
    ko: KoCfg
    pickup_radius: float = Field(gt=0, le=4)
    reach: float = Field(gt=0, le=4)
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


class ForestCfg(Strict):
    radius: int
    tree_density: float = Field(ge=0, le=0.4)
    clearing_threshold: float = Field(ge=0, le=1)


class BandCfg(Strict):
    biome: Literal["forest", "stonepeak", "swamp", "frozen", "ashen"]
    radius: int = Field(gt=0)


class MapgenCfg(Strict):
    version: int
    map_size: int
    chunk_size: int
    hub_radius: int
    plot: PlotCfg
    meadow: MeadowCfg
    bands: list[BandCfg] = Field(min_length=1)
    forest: ForestCfg


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


# ── nodes.yaml ───────────────────────────────────────────────────────────────

Biome = Literal["meadow", "forest", "stonepeak", "swamp", "frozen", "ashen"]
Range = tuple[int, int]


def _range_ok(v: Range) -> Range:
    if v[0] < 0 or v[1] < v[0]:
        raise ValueError("range must be [min, max] with 0 <= min <= max")
    return v


class NodeBonus(Strict):
    chance: float = Field(ge=0, le=1)
    qty: Range

    @field_validator("qty")
    @classmethod
    def _q(cls, v: Range) -> Range:
        return _range_ok(v)


class NodeCfg(Strict):
    objects: list[str] = Field(min_length=1)
    biome: Biome | None = None  # only nodes in this biome (more specific nodes win)
    hits: int = Field(ge=1, le=20)
    yields: dict[str, Range]
    bonus: dict[str, NodeBonus] = {}
    respawn: Duration
    xp: int = Field(ge=0)
    sound: str
    night_only: bool = False  # only gatherable (and only shown) at night (Moonpetal)

    @field_validator("yields")
    @classmethod
    def _y(cls, v: dict[str, Range]) -> dict[str, Range]:
        for r in v.values():
            _range_ok(r)
        return v


class NodesCfg(Strict):
    nodes: dict[str, NodeCfg]


# ── combat.yaml ──────────────────────────────────────────────────────────────


class Stamina(Strict):
    regen_per_s: float = Field(gt=0)
    regen_delay: Duration


class Dodge(Strict):
    stamina: float = Field(ge=0)
    duration: Duration
    distance: float = Field(gt=0, le=6)
    iframes: Duration
    cooldown: Duration


class Knockback(Strict):
    decay: Duration
    player_mult: float = Field(ge=0)


class MoveExtras(Strict):
    """Phase 11 move options, all server-side except timings (the client predictor never needs them)."""

    width: float = Field(default=0.8, gt=0, le=4)
    speed: float = Field(default=12, gt=0, le=30)  # shot/throw: tiles per second
    pierce: bool = False
    aoe: float = Field(default=0, ge=0, le=4)  # shot: explodes on impact · starfall: impact radius
    homing: float = Field(default=0, ge=0, le=1)  # shot: how hard it steers toward the nearest monster
    count: int = Field(default=1, ge=1, le=12)  # shot: projectiles fanned across `spread` degrees
    spread: float = Field(default=0, ge=0, le=120)
    hits: int = Field(default=1, ge=1, le=12)  # circle/starfall/spin: repeated hits…
    interval: Duration = 0.2  # …this far apart
    stun: Duration = 0
    pull: float = Field(default=0, ge=0, le=6)  # tiles toward you (harpoon)
    status: Literal["", "burn", "slow", "poison"] = ""
    proc: float = Field(default=0, ge=0, le=1)
    duration: Duration = 0  # barrier
    sprite: str = ""  # shot: projectile sprite
    impact: str = ""  # circle: which shockwave the client draws


class Move(MoveExtras):
    """One swing. `arc` uses arc (degrees) + range; `line` range + width; `circle` is around you;
    `shot` fires projectiles."""

    dmg: float = Field(gt=0)
    windup: Duration
    active: Duration
    recover: Duration
    shape: Literal["arc", "line", "circle", "shot", "starfall", "barrier"]
    range: float = Field(gt=0, le=12)
    arc: float = Field(default=120, gt=0, le=360)
    knockback: float = Field(default=0.5, ge=0)
    stamina: float = Field(default=0, ge=0)
    dash: float = Field(default=0, ge=0, le=5)


class Ability(MoveExtras):
    kind: Literal["spin", "throw", "circle", "shot", "starfall", "barrier"]
    dmg: float = Field(gt=0)
    cooldown: Duration
    windup: Duration
    recover: Duration
    knockback: float = Field(default=0.5, ge=0)
    range: float = Field(gt=0, le=12)


class Weapon(Strict):
    light: list[Move] = Field(min_length=1, max_length=5)
    combo_window: Duration
    heavy: Move
    ability: Ability


class ShieldCfg(Strict):
    defence: list[int] = Field(min_length=5, max_length=5)
    block: float = Field(ge=0, le=1)  # share of a frontal hit blocked while you hold F
    block_stamina: float = Field(ge=0)
    block_arc: float = Field(gt=0, le=360)


class BombsCfg(Strict):
    dmg: float = Field(gt=0)
    radius: float = Field(gt=0, le=5)
    fuse: Duration
    charges: int = Field(ge=1, le=9)
    recharge: Duration
    throw: float = Field(gt=0, le=8)
    knockback: float = Field(ge=0)


class TomeCfg(Strict):
    dmg: float = Field(gt=0)
    cooldown: Duration
    speed: float = Field(gt=0)
    range: float = Field(gt=0)
    homing: float = Field(ge=0, le=1)


class OffhandsCfg(Strict):
    shield: ShieldCfg
    bombs: BombsCfg
    tome: TomeCfg


class DotCfg(Strict):
    share: float = Field(gt=0, le=2)  # total DoT damage as a share of the hit that applied it
    duration: Duration
    stacks: int = Field(default=1, ge=1, le=5)


class SlowCfg(Strict):
    mult: float = Field(gt=0, le=1)
    duration: Duration


class StatusesCfg(Strict):
    burn: DotCfg
    poison: DotCfg
    slow: SlowCfg


class ArmourMoveCfg(Strict):
    speed: float = Field(gt=0.5, le=1.5)
    dodge: float = Field(gt=0.5, le=1.5)


class CombatCfg(Strict):
    crit_mult: float = Field(ge=1)
    attack_scaling: float = Field(ge=0)
    defence_k: float = Field(gt=0)
    tier_mult: list[float] = Field(min_length=5, max_length=5)
    rarity_mult: dict[Literal["common", "uncommon", "rare", "epic", "legendary"], float]
    stamina: Stamina
    dodge: Dodge
    combat_lock: Duration
    lag_comp_max: Duration
    dodge_grace: Duration
    knockback: Knockback
    attack_move_slow: float = Field(gt=0, le=1)
    weapons: dict[str, Weapon]
    offhands: OffhandsCfg
    statuses: StatusesCfg
    armour_move: dict[str, ArmourMoveCfg] = {}


# ── enemies.yaml ─────────────────────────────────────────────────────────────


class EnemyAttack(Strict):
    shape: Literal["circle", "line", "shot"]  # shot: a projectile along the telegraphed line (kiters)
    range: float = Field(gt=0, le=10)  # circle radius around the landing point / line length / shot reach
    width: float = Field(default=0.8, gt=0, le=3)
    trigger: float = Field(gt=0, le=9)  # start winding up when the target is this close
    windup: Duration
    active: Duration
    recover: Duration
    lunge: float = Field(default=0, ge=0, le=6)  # tiles moved during the active phase
    knockback: float = Field(default=0.6, ge=0)
    at_target: bool = False  # circle lands on the target's spot instead of a hop (summoner roots)
    root: Duration | None = None  # a hit roots the player in place this long


class ShotCfg(Strict):
    speed: float = Field(gt=0, le=30)  # tiles per second
    radius: float = Field(default=0.3, gt=0, le=1)
    sprite: Literal["arrow", "spit", "sting", "ice", "fire", "bolt", "rock"]
    chain: int = Field(default=0, ge=0, le=4)  # chain lightning: jumps to this many more players
    chain_radius: float = Field(default=3.5, gt=0)
    chain_dmg: float = Field(default=0.6, gt=0, le=1)


class SummonCfg(Strict):
    enemy: str
    count: int = Field(ge=1, le=4)
    every: Duration
    max_alive: int = Field(ge=1, le=8)


class SplitCfg(Strict):
    into: str
    count: int = Field(ge=1, le=4)


class Poison(Strict):
    dps: float = Field(gt=0)
    duration: Duration


class LootDrop(Strict):
    item: str
    chance: float = Field(gt=0, le=1)
    qty: Range


class EnemyCfg(Strict):
    name: str
    archetype: Literal["swarmer", "chaser", "kiter", "charger", "tank", "summoner", "ambusher"]
    hp: float = Field(gt=0)
    dmg: float = Field(ge=0)
    defence: float = Field(ge=0)
    speed: float = Field(gt=0, le=10)
    radius: float = Field(gt=0, le=1.5)
    group: Range
    attack: EnemyAttack
    poison: Poison | None = None
    ambush_radius: float = Field(default=0, ge=0)  # ambushers hide until a player is this close
    loot: list[LootDrop] = []
    elite_name: str | None = None  # None: never spawns as an elite (minions, storm spawns)
    shot: ShotCfg | None = None  # kiters: what the shot looks like and how fast it flies
    keep_away: float = Field(default=0, ge=0)  # kiters/summoners back off when you get this close
    summon: SummonCfg | None = None
    split: SplitCfg | None = None  # splits into smaller ones on death (Big Slime)
    alt_attack: EnemyAttack | None = None  # bosses: a second attack used when the target is far (Phase 12)
    roaming: bool = False  # not tied to a biome: stats are scaled by the biome it appears in


class EliteCfg(Strict):
    hp: float = Field(ge=1)
    dmg: float = Field(ge=1)
    scale: float = Field(ge=1)
    xp: float = Field(ge=1)
    loot_rolls: int = Field(ge=1)
    knockback_resist: float = Field(ge=0, le=1)


class BiomeScale(Strict):
    hp: float = Field(ge=1)
    dmg: float = Field(ge=1)
    defence: float = Field(ge=0)


class BiomeSpawns(Strict):
    difficulty: int = Field(ge=1, le=6)
    groups_per_chunk: float = Field(ge=0, le=4)
    roster: dict[str, float]
    elite_chance: float = Field(ge=0, le=1)
    xp: int = Field(ge=0)
    coins: Range
    scale: BiomeScale  # BALANCE §6.2 multipliers (baked into roster stats; applied to roaming spawns)


class CoopCfg(Strict):
    hp_per_player: float = Field(ge=0)  # HP × (1 + this × extra players near the spawn)
    radius: float = Field(gt=0)


class EnemiesCfg(Strict):
    aggro_radius: float = Field(gt=0)
    leash_radius: float = Field(gt=0)
    wake_radius_chunks: int = Field(ge=1, le=4)
    despawn_after: Duration
    respawn: Duration
    elite: EliteCfg
    coop: CoopCfg
    storm_enemy: str  # appears near players during storms (world_clock.yaml → weather.storm.storm_spawns)
    minion_xp: float = Field(ge=0, le=1)  # summoned minions give this share of XP and no loot
    biomes: dict[Biome, BiomeSpawns]
    enemies: dict[str, EnemyCfg]


# ── combos.yaml (secret) ─────────────────────────────────────────────────────


class ComboCfg(Strict):
    name: str
    buildings: list[str] = Field(min_length=2, max_length=3)
    unlocks: list[str] = Field(min_length=1)
    legendary_eligible: bool = False
    hint: str


class CombosCfg(Strict):
    combos: dict[str, ComboCfg]


# ── recipes.yaml ─────────────────────────────────────────────────────────────


class ConsumableRecipe(Strict):
    station: str
    inputs: dict[str, int]
    time: Duration  # per unit
    makes: int = Field(default=1, ge=1, le=10)
    max_batch: int = Field(ge=1, le=50)
    min_tier: int = Field(default=1, ge=1, le=5)


class IntermediateRecipe(Strict):
    station: str
    inputs: dict[str, int]
    time: Duration  # per unit
    max_batch: int = Field(ge=1, le=100)


class GearRecipe(Strict):
    station: str
    copper: dict[str, int]
    base: dict[str, int]


class RecipesCfg(Strict):
    intermediates: dict[str, IntermediateRecipe]
    job_slots: dict[str, list[int]]
    gear: dict[str, GearRecipe]
    consumables: dict[str, ConsumableRecipe] = {}


# ── forging.yaml ─────────────────────────────────────────────────────────────


class TierCfg(Strict):
    name: str
    material_mult: float = Field(ge=0)
    coins: int = Field(ge=0)
    crystal: int = Field(ge=0)
    time: Duration
    durability: int = Field(ge=1)
    repair_coins: float = Field(ge=0)


class RarityCfg(Strict):
    key: Literal["common", "uncommon", "rare", "epic", "legendary"]
    weight: float = Field(gt=0)
    slots: int = Field(ge=0, le=4)
    value_floor: float = Field(ge=0, le=1)


class ModifierCfg(Strict):
    key: str
    name: str
    effect: Literal["knockback", "crit", "venom", "frost", "fire", "lifesteal", "chain"]
    range: tuple[float, float]


class SalvageCfg(Strict):
    fraction: float = Field(ge=0, le=1)
    rare_return: float = Field(ge=0, le=1)


class ForgingCfg(Strict):
    tiers: list[TierCfg] = Field(min_length=5, max_length=5)
    rarities: list[RarityCfg] = Field(min_length=5, max_length=5)
    luck_k: float = Field(ge=0)
    max_rare_inputs: int = Field(ge=0, le=5)
    modifiers: dict[str, ModifierCfg]
    polished: float = Field(ge=0, le=0.5)
    dull_damage: float = Field(gt=0, le=1)
    repair_ingots_per: int = Field(ge=1)
    salvage: SalvageCfg
    armour: dict[str, list[int]]


# ── market.yaml ──────────────────────────────────────────────────────────────


class MarketDefaults(Strict):
    k: float = Field(gt=0, le=5)
    clamp: tuple[float, float]
    min_population: int = Field(ge=1)
    over_cap_mult: float = Field(gt=0, le=1)


class MarketItem(Strict):
    base: float = Field(gt=0)
    baseline: float = Field(gt=0)  # per active player per day
    soft_cap: int = Field(ge=1)  # per player per day
    k: float | None = Field(default=None, gt=0, le=5)
    over_cap_mult: float | None = Field(default=None, gt=0, le=1)


class TrendCfg(Strict):
    lookback: Duration
    threshold: float = Field(ge=0, le=1)


class SparklineCfg(Strict):
    points: int = Field(ge=4, le=200)
    span: Duration


class MarketCfg(Strict):
    recalc_interval: Duration
    window: Duration
    active_window: Duration
    history_retention: Duration
    defaults: MarketDefaults
    trend: TrendCfg
    sparkline: SparklineCfg
    max_sell: int = Field(ge=1)
    items: dict[str, MarketItem]

    def k(self, key: str) -> float:
        return self.items[key].k or self.defaults.k

    def over_cap_mult(self, key: str) -> float:
        return self.items[key].over_cap_mult or self.defaults.over_cap_mult


# ── merchant.yaml ────────────────────────────────────────────────────────────


class MerchantStock(Strict):
    kind: Literal["item", "resource", "hint"]
    key: str | None = None
    qty: int = Field(default=1, ge=1, le=999)
    price: int = Field(ge=1)
    limit: int = Field(ge=1, le=99)
    weight: float = Field(gt=0)
    name: str | None = None
    blurb: str | None = None


class MerchantCfg(Strict):
    name: str
    rotation: Duration
    slots: int = Field(ge=1, le=12)
    interact_radius: float = Field(gt=0, le=10)
    min_markup: float = Field(ge=1)
    deal_discount: float = Field(ge=0, lt=1)
    spots: list[tuple[int, int]] = Field(min_length=1)
    greetings: list[str] = Field(min_length=1)
    stock: dict[str, MerchantStock]


# ── tutorial.yaml ────────────────────────────────────────────────────────────


class TutorialGoal(Strict):
    kind: Literal["confirm", "buildings", "stat", "discovery"]
    all: list[str] = []
    key: str | None = None
    at_least: int = Field(default=1, ge=1)
    combo: str | None = None


class TutorialStep(Strict):
    key: str
    title: str
    lines: list[str] = Field(min_length=1)
    goal: TutorialGoal
    button: str | None = None
    highlight: Literal["build", "explore", "market", "craft", "home"] | None = None
    reward: dict[str, int] = {}


class GuideCfg(Strict):
    name: str
    look: Appearance


class AwayCfg(Strict):
    min_absence: Duration
    quips: list[str] = Field(min_length=1)


class TutorialCfg(Strict):
    guide: GuideCfg
    away: AwayCfg
    steps: list[TutorialStep] = Field(min_length=1)


# ── social.yaml ──────────────────────────────────────────────────────────────


class RealmRules(Strict):
    max_members: int = Field(ge=2, le=10)
    name_min: int = Field(ge=1)
    name_max: int = Field(le=40)


class StashRules(Strict):
    capacity: int = Field(ge=1, le=255)
    newcomer_deposit_only: Duration
    untrusted_daily_value: int = Field(ge=0)
    default_item_value: int = Field(ge=0)
    gear_value_per_tier: int = Field(ge=0)


class PartyRules(Strict):
    max_size: int = Field(ge=2, le=10)
    xp_share_radius: float = Field(gt=0)
    invite_ttl: Duration


class FogRules(Strict):
    reveal_radius: int = Field(ge=0, le=6)


class WaystoneRules(Strict):
    attune_radius: float = Field(gt=0, le=8)
    use_radius: float = Field(gt=0, le=8)


class SocialCfg(Strict):
    realm: RealmRules
    stash: StashRules
    party: PartyRules
    fog: FogRules
    waystone: WaystoneRules


# ── world_clock.yaml ─────────────────────────────────────────────────────────


class DayCycleCfg(Strict):
    length: Duration
    phases: dict[Literal["dawn", "day", "dusk", "night"], Duration]


class NightCfg(Strict):
    hp: float = Field(ge=1)
    dmg: float = Field(ge=1)
    loot_qty: float = Field(ge=1)
    rare_chance: float = Field(ge=1)  # rare-material drop chances × this
    groups: float = Field(ge=1)  # spawn points per chunk × this; the extra ones only wake at night


class WeatherStateCfg(Strict):
    weights: dict[Literal["spring", "summer", "autumn", "winter"], float]
    production: dict[str, float] = {}
    rare_node: dict[str, float] = {}
    aggro: float = Field(default=1.0, gt=0, le=2)
    storm_spawns: float = Field(default=0.0, ge=0, le=1)


class WeatherCfg(Strict):
    block: Duration
    states: dict[str, WeatherStateCfg]


class WorldClockCfg(Strict):
    day_cycle: DayCycleCfg
    season_length: Duration
    seasons: list[Literal["spring", "summer", "autumn", "winter"]]
    night: NightCfg
    weather: WeatherCfg


# ── pois.yaml (Phase 10) ─────────────────────────────────────────────────────

PoiKind = Literal["ruins", "shrine", "lore_stone", "cave", "merchant", "lost_villager"]


class ChestCfg(Strict):
    coins: Range
    rolls: int = Field(ge=0, le=6)
    pool: dict[str, Range]
    rare: dict[str, float] = {}


class BlessingCfg(Strict):
    name: str
    text: str
    damage: float = Field(default=0, ge=0, le=1)
    defence: float = Field(default=0, ge=0, le=1)
    coins: float = Field(default=0, ge=0, le=2)


class ShrinesCfg(Strict):
    cooldown: Duration
    duration: Duration
    blessings: dict[str, BlessingCfg] = Field(min_length=1)


class LostVillagerCfg(Strict):
    xp: int = Field(ge=0)
    coins: Range
    names: list[str] = Field(min_length=1)


class LoreCfg(Strict):
    title: str
    text: str


class PoisCfg(Strict):
    interact_radius: float = Field(gt=0, le=6)
    clear_radius: int = Field(ge=1, le=6)
    min_spacing: float = Field(gt=0)
    edge_margin: float = Field(ge=0)
    trail_clearance: float = Field(ge=0)
    bands: dict[Biome, dict[PoiKind, int]]
    chests: dict[Biome, ChestCfg]
    shrines: ShrinesCfg
    lost_villager: LostVillagerCfg
    lore_xp: int = Field(ge=0)
    lore: dict[Biome, list[LoreCfg]]


# ── dungeons.yaml (Phase 12) ─────────────────────────────────────────────────


class DungeonLayoutCfg(Strict):
    cols: int = Field(ge=2, le=6)
    rows: int = Field(ge=2, le=6)
    cell_w: int = Field(ge=16, le=30)
    cell_h: int = Field(ge=14, le=30)
    rooms: int = Field(ge=5, le=20)


class DungeonSpaceCfg(Strict):
    x0: int = Field(ge=1024)
    slot: int = Field(ge=64, le=512)


class DungeonCombatCfg(Strict):
    monsters: Range


class MinibossCfg(Strict):
    hp: float = Field(ge=1)
    adds: int = Field(ge=0, le=6)


class DungeonBossCfg(Strict):
    enemy: str
    adds_at: list[float]
    adds: int = Field(ge=0, le=6)
    enrage_at: float = Field(ge=0, le=1)
    enrage_speed: float = Field(ge=1, le=3)


class DungeonTreasureCfg(Strict):
    coins: Range
    rolls: int = Field(ge=0, le=5)
    rune: float = Field(ge=0, le=1)
    blueprint: float = Field(ge=0, le=1)


class BossLootCfg(Strict):
    coins: Range
    runes: Range
    blueprint: float = Field(ge=0, le=1)


class DungeonXpCfg(Strict):
    room: int = Field(ge=0)
    puzzle: int = Field(ge=0)
    boss: int = Field(ge=0)


class DailyCfg(Strict):
    biome: Biome
    place: tuple[int, int]


class LeaderboardCfg(Strict):
    size: int = Field(ge=1, le=100)


class DungeonsCfg(Strict):
    layout: DungeonLayoutCfg
    space: DungeonSpaceCfg
    max_party: int = Field(ge=1, le=8)
    idle_close: Duration
    reseed: Literal["daily", "never"]
    combat: DungeonCombatCfg
    miniboss: MinibossCfg
    boss: DungeonBossCfg
    treasure: DungeonTreasureCfg
    boss_loot: BossLootCfg
    xp: DungeonXpCfg
    daily: DailyCfg
    blueprints: list[str] = Field(min_length=1)
    leaderboard: LeaderboardCfg
