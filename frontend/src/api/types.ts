// Response shapes from the backend (kept in sync with hearthforge/api/*).

export interface Appearance {
  body: string;
  skin: string;
  hair_style: string;
  hair_color: string;
  eyes: string;
  eye_color: string;
  outfit: string;
  outfit_color: string;
}

export interface LevelSpec {
  level: number;
  cost: Record<string, number>;
  time_s: number;
  production: Record<string, number>;
  storage: number | null;
  housing: number | null;
}

export interface BuildingDef {
  name: string;
  description: string;
  category: string;
  footprint: [number, number];
  unlock_town_hall: number;
  max_count: number[];
  max_level: number;
  requires_water: boolean;
  demolishable: boolean;
  levels: LevelSpec[];
  jobs: number[] | null; // Phases 13/14: worker / guard slots per level
  tower_dmg: number[] | null;
  beauty: number;
  walkable: boolean;
  requires_item: string | null;
}

export interface ConfigBundle {
  hash: string;
  game: {
    build_queue: { base_slots: number; bonus_slots: { town_hall: number; slots: number }[] };
    refunds: { cancel: number; demolish: number; undo_window: number };
    gates: Record<string, boolean>;
    auth: { username_min: number; username_max: number; password_min: number };
  };
  resources: Record<string, { name: string; kind: string; icon: string }>;
  waves: { min_town_hall: number; warning_s: number; steal_max: number };
  bosses: Record<string, { name: string; biome: string; enemy: string; trophy: string }>;
  villagers: {
    lines: Record<string, string[]>;
    schedule: { work: string[]; social: string[]; home: string[] };
    food_per_villager: number;
    weights: Record<string, number>;
    production_bonus: number;
    crafting_speed: number;
    arrival_every_s: number;
    min_happiness: number;
    leave_below: number;
  };
  hud_order: string[];
  items: Record<
    string,
    {
      name: string;
      category: string;
      stackable: boolean;
      icon: string;
      weapon_type?: string;
      offhand_type?: string;
      use?: { heal: number; stamina: number; regen: number; buff: string | null; value: number; duration: number; cooldown: number; group: string };
    }
  >;
  buildings: Record<string, BuildingDef>;
  avatar: {
    creator: {
      bodies: string[];
      skin_tones: string[];
      hair_styles: string[];
      hair_colors: string[];
      eye_styles: string[];
      eye_colors: string[];
      outfits: string[];
      outfit_colors: string[];
    };
    default_appearance: Appearance;
  };
  plot: { frame: number; start_size: number; max_size: number; pond: { x: number; y: number; w: number; h: number } };
  map: { size: number; chunk_size: number; bands: { biome: string; radius: number }[] };
  world_clock: {
    day_length: number;
    phases: Record<string, number>;
    season_length: number;
    seasons: string[];
    weather_block: number;
  };
  debris: Record<string, { sprites: string[]; yields: Record<string, number> }>;
  sim: unknown; // sim/rules.ts Rules
  nodes: Record<string, { objects: string[]; biome: string | null; hits: number; yields: Record<string, [number, number]>; sound: string }>;
  combat: {
    combat_lock_s: number;
    weapons: Record<string, { ability: string; ability_cd_s: number }>;
    offhands: { shield: { block: number }; bombs: { charges: number; recharge_s: number }; tome: { cooldown_s: number } };
  };
  enemies: Record<string, { name: string; elite_name: string; archetype: string; radius: number }>;
  recipes: {
    intermediates: Record<string, { station: string; inputs: Record<string, number>; seconds_per_unit: number; max_batch: number }>;
    gear: Record<string, { station: string }>;
    consumables: Record<string, { station: string }>;
  };
  forging: {
    tiers: { name: string; durability: number }[];
    rarities: string[];
    modifiers: Record<string, { name: string; effect: string }>;
    max_rare_inputs: number;
    armour: Record<string, number[]>;
  };
  social: {
    gate: { level: number; account_age_s: number };
    friends_max: number;
    gifts: { per_friend_per_day: number; value_cap: number; daily_value_cap: number; max_stacks: number };
    help: { cut: number; per_day: number };
    emotes: string[];
    quick: string[];
    chat_radius: number;
    ping_s: number;
  };
  world_boss: { name: string; boss: string };
  festivals: Record<string, { name: string; token: string; color: string }>;
  companions: {
    pets: Record<string, { name: string; desc: string }>;
    mounts: Record<string, { name: string; speed: number }>;
  };
  fishing: {
    species: Record<string, { name: string; rarity: string; kg: [number, number]; price: number }>;
    reach: number;
    tiles: string[];
  };
  skills: {
    points_per_level: number;
    respec: { free_first: boolean; coins_per_level: number };
    branches: Record<string, { name: string; nodes: Record<string, SkillNodeDef> }>;
  };
}

export interface SkillNodeDef {
  name: string;
  desc: string;
  max: number;
  requires: string[];
  branch_points: number;
  effects: Record<string, number>;
}

export interface Me {
  user: { id: string; username: string; role: string; created_at_ms: number; tutorial_step: number };
  avatar: { appearance: Appearance; level: number; xp: number; hp: number };
  realm: { id: string; name: string; is_solo: boolean; plot_index: number; role: string };
  village: { id: string; name: string };
  settings: { audio: AudioSettings; graphics: Record<string, unknown>; keybinds: Record<string, unknown> };
  csrf_token: string;
  server_time_ms: number;
  config_hash: string;
}

export interface AudioSettings {
  master: number;
  music: number;
  sfx: number;
  muted: boolean;
}

export interface SignupResult {
  user_id: string;
  username: string;
  csrf_token: string;
  recovery_codes: string[];
}

export interface BuildingState {
  id: string;
  key: string;
  x: number;
  y: number;
  rotation: number;
  level: number;
  state: "active" | "constructing" | "upgrading";
  started_at_ms: number | null;
  completes_at_ms: number | null;
}

export interface ResourceState {
  amount: number;
  rate: number; // units per hour
  cap: number;
}

export interface VillageState {
  owner_id: string;
  village_id: string;
  name: string;
  version: number;
  size: number;
  frame: number;
  origin: [number, number];
  town_hall_level: number;
  queue: { slots: number; used: number };
  buildings: BuildingState[];
  resources: Record<string, ResourceState>;
  coins: number;
  at_ms: number;
  undo: { op: string; expires_at_ms: number } | null;
  blocked: [number, number, number, number][];
  water: [number, number, number, number][];
  /** [id, kind, variant, x, y] wild growth still covering the plot */
  debris: [number, string, number, number, number][];
  gate: [number, number, "N" | "S" | "E" | "W"];
  /** Phase 6: active combos (only ever discovered ones) and station jobs */
  combos: ActiveCombo[];
  discovered: string[];
  new_discoveries: string[];
  jobs: CraftJobView[];
  /** Phase 14: villagers, happiness and beauty */
  villagers: VillagerView[];
  happiness: Happiness;
  beauty: BeautyView;
  housing: { cap: number; used: number };
  next_arrival_ms: number | null;
  job_slots: Record<string, { slots: number; workers: number }>;
  food_demand: number;
}

export interface VillagerView {
  id: string;
  name: string;
  look: Appearance;
  traits: string[];
  job: string | null;
  home: string | null;
  arrived_ms: number;
}

export interface Happiness {
  value: number;
  beauty: number;
  housing: number;
  food: number;
  tavern: number;
  mood: "happy" | "hungry" | "crowded" | "ugly" | "bored" | "leaving";
  leave_at_ms: number | null;
}

export interface BeautyView {
  score: number;
  decor: number;
  variety: number;
  connected: number;
  nature: number;
  linked: number;
}

export interface ActiveCombo {
  key: string;
  name: string;
  buildings: string[];
  tier: number;
  unlocks: string[];
}

export interface CraftJobView {
  id: string;
  station_id: string;
  kind: "intermediate" | "gear" | "consumable";
  recipe: string;
  quantity: number;
  tier: number | null;
  rares: string[];
  started_at_ms: number;
  completes_at_ms: number;
}

export interface Modifier {
  key: string;
  name: string;
  effect: string;
  value: number;
}

export interface ForgedItem {
  instance_id: string;
  item: string;
  name: string;
  tier: number;
  rarity: string;
  modifiers: Modifier[];
  durability: number;
  max_durability: number;
}

export interface InvSlotView {
  slot: number;
  item: string;
  qty: number;
  name?: string;
  tier?: number;
  rarity?: string;
  durability?: number;
  max_durability?: number;
  modifiers?: Modifier[];
}

export interface ContainerView {
  capacity: number;
  slots: InvSlotView[];
  expand?: { step: number; next_cost: number | null; max: number };
}

export interface InventoryView {
  inventory: ContainerView;
  equipment: ContainerView;
  bank?: ContainerView;
}

// ── Phase 7: market and merchant ─────────────────────────────────────────────

export interface MarketItem {
  key: string;
  name: string;
  icon: string;
  source: "storage" | "bag";
  have: number;
  base: number;
  raw_price: number;
  price: number; // with your Market bonus
  over_price: number; // past your daily soft cap
  trend: -1 | 0 | 1;
  change: number;
  spark: number[];
  units_24h: number;
  baseline: number;
  sold_today: number;
  soft_cap: number;
}

export interface MarketView {
  has_market: boolean;
  market_level: number;
  bonus: number;
  coins: number;
  population: number;
  active_players: number;
  next_recalc_ms: number;
  max_sell: number;
  items: MarketItem[];
}

export interface SaleResult {
  item: string;
  sold: number;
  coins: number;
  unit_price: number;
  over_cap_units: number;
  sold_today: number;
  soft_cap: number;
  balance: number;
}

export interface MerchantSlot {
  slot: number;
  key: string;
  kind: "item" | "resource" | "hint";
  item: string | null;
  qty: number;
  name: string;
  blurb: string | null;
  icon: string;
  price: number;
  list_price: number;
  deal: boolean;
  limit: number;
  bought: number;
  sold_out: boolean;
}

export interface MerchantView {
  wild?: boolean;
  merchant_id: string;
  name: string;
  greeting: string;
  rotation: number;
  ends_at_ms: number;
  pos: [number, number];
  radius: number;
  near: boolean;
  slots: MerchantSlot[];
}
