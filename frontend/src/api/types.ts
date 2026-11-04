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
  hud_order: string[];
  items: Record<string, { name: string; category: string; stackable: boolean; icon: string }>;
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
  map: { size: number; chunk_size: number };
  debris: Record<string, { sprites: string[]; yields: Record<string, number> }>;
  sim: unknown; // sim/rules.ts Rules
  nodes: Record<string, { objects: string[]; biome: string | null; hits: number; yields: Record<string, [number, number]>; sound: string }>;
  combat: { combat_lock_s: number; weapons: Record<string, { ability: string; ability_cd_s: number }> };
  enemies: Record<string, { name: string; elite_name: string; archetype: string; radius: number }>;
  recipes: {
    intermediates: Record<string, { station: string; inputs: Record<string, number>; seconds_per_unit: number; max_batch: number }>;
    gear: Record<string, { station: string }>;
  };
  forging: {
    tiers: { name: string; durability: number }[];
    rarities: string[];
    modifiers: Record<string, { name: string; effect: string }>;
    max_rare_inputs: number;
    armour: Record<string, number[]>;
  };
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
  kind: "intermediate" | "gear";
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

export interface InventoryView {
  inventory: { capacity: number; slots: InvSlotView[] };
  equipment: { capacity: number; slots: InvSlotView[] };
}
