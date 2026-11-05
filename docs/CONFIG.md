# Config formats

Every balance number and every piece of content lives in `/config/*.yaml`. Code never hard-codes a cost, timer, stat, drop rate, price, curve, recipe or enemy stat.

## Loading and validation

1. At startup, `hearthforge.config.loader` reads every `*.yaml` in `/config` (or the folder in `HF_CONFIG_DIR`).
2. Each file is parsed into its own Pydantic v2 model with `model_config = ConfigDict(extra="forbid", frozen=True)`, so typos fail.
3. **Cross-reference validation** runs next. Every referenced key must exist:
   - buildings, items, recipes, combos, enemies, loot tables, biomes, skills, cosmetics and audio/sprite keys used by config;
   - every building has exactly `max_level` level entries;
   - every combo references crafting-station buildings;
   - loot weights are greater than 0;
   - no orphaned recipe.
4. **Sanity warnings** (logged, not fatal unless `HF_CONFIG_STRICT=1`, which CI sets):
   - costs and times not monotonically increasing by level;
   - any timer over `game.max_timer_seconds` (3,600, the "respect time" pillar);
   - a drop table whose expected value is above the configured coin faucet guard.
5. Any error **aborts startup** with `file:path.to.field: reason`. CI runs `uv run hf config check`.
6. Output: a frozen `GameConfig` registry, its `hash` (sha256 of the normalized content), and the **client bundle**: the same data with `secret: true` sections stripped and key-index tables added for the wire protocol.

Conventions: durations use the `"45s" | "5m" | "1h"` string syntax (parsed to seconds), percentages are fractions (`0.25`), and keys are `snake_case`.

## File list

| File | Contents | Phase |
|---|---|---|
| `game.yaml` | tick rate, area-of-interest size, grace periods, room idle timeout, autosave, rate limits, global caps | 2 |
| `world_clock.yaml` | day/night lengths, weather states, weights per season, weather effects, season length | 3, 10 |
| `resources.yaml` | raw resources and intermediate goods: display, icon key, storage group | 2 |
| `items.yaml` | every non-gear item (materials, rares, consumables, trophies, blueprints, fish) | 4 |
| `buildings.yaml` | footprint, category, unlocks, per-level cost, time, production, cap, effects, count limits | 3 |
| `decorations.yaml` | decoration catalogue, beauty points, cost, unlock | 3, 14 |
| `combos.yaml` (**secret**) | combo definitions: buildings (2–3, touching), name, unlocked gear, hint, legendary eligibility | 6 ✔ |
| `recipes.yaml` | intermediates (station, inputs, time per unit, max batch), job slots per station level, gear (station, copper bill, iron+ base bill) | 6 ✔ |
| `forging.yaml` | tiers (material multiplier, coins, crystal, time, durability, repair rate), rarities (weight, slots, value floor), luck, modifiers from rare materials, Dull, repair, salvage, armour defence | 6 ✔ |
| `weapons.yaml` | (folded into `combat.yaml → weapons` for now, D-050) | 5, 11 |
| `armour.yaml` | armour/offhand/trinket stats per tier | 11 |
| `rarity.yaml` | rarity colours, multipliers, modifier slots, roll weights, luck curve | 6 |
| `modifiers.yaml` | modifier effects and value ranges, source materials | 6 |
| `combat.yaml` | damage formula constants, crit, defence curve, stamina, dodge, combat lock, lag-comp/dodge-grace windows, knockback, **weapon movesets** | 5 ✔ |
| `avatar.yaml` | base stats, per-level growth, XP curve, level cap, KO rules, regen, pickup radius, reach | 4, 5 ✔ |
| `skills.yaml` | skill tree (3 branches) | 16 |
| `enemies.yaml` | enemy stats, attack + telegraph shape, elites, per-biome spawn tables, inline loot (D-050) | 5 ✔, 10 |
| `loot_tables.yaml` | weighted tables, nested tables, coin ranges | 5 |
| `biomes.yaml` | ring order, difficulty, enemy spawn tables, nodes, rares, ambience, music | 4, 10 |
| `mapgen.yaml` (POI part **secret**) | ring radii, plot layout, noise params, POI densities, node densities | 3, 9 |
| `nodes.yaml` | gatherable node types: which map objects, hits, yields (+ bonus rolls), per-player respawn, XP, sound | 4 ✔ |
| `dungeons.yaml` | room templates, weights, length, puzzles, bosses, rewards, daily seed rule | 12 |
| `waves.yaml` | wave interval, warning, composition by TH level, steal cap, rewards, report lines | 13 |
| `bosses.yaml` | realm and world bosses: phases, attacks, HP, scaling, loot | 13, 17 |
| `market.yaml` | NPC prices, pricing params, soft caps, recalc interval, trend/sparkline windows (listing fee/expiry join in 17) | 7 ✔, 17 |
| `merchant.yaml` | stock, rotation period, slots, deal discount, parking spots, greetings, no-arbitrage markup | 7 ✔ |
| `villagers.yaml` | name parts, appearance pools, happiness weights, arrival rules, speech lines | 14 |
| `beauty.yaml` | beauty scoring weights | 14 |
| `quests.yaml` | tutorial, main, daily and weekly pools | 8, 16 |
| `achievements.yaml` | stat thresholds → rewards and titles | 16 |
| `cosmetics.yaml` | outfits, dyes, banners, skins, titles | 16 |
| `pets.yaml`, `mounts.yaml`, `fishing.yaml` | pet and mount stats and bonuses, fish per biome/season, minigame timing | 16 |
| `login_rewards.yaml` | calendar | 16 |
| `social.yaml` | realm size and names, stash trust rules (P3), party size and XP share radius, fog reveal radius, waystone radii; gift caps, help %, new-account gates (P4) join in 15 | 9 ✔, 15 |
| `festivals.yaml` | calendar festivals: dates, decorations, enemies, quests | 17 |
| `presets.yaml` | emotes, quick messages, ping types | 9 |
| `profanity.yaml` | blocked substrings plus leetspeak normalization map | 2 |
| `tutorial.yaml` | Juniper's look, steps (lines, goal kind: confirm/buildings/stat/discovery, highlight, reward), the away card's min absence and quips | 8 ✔ |

---

## Format examples

These are illustrative. The real files are written in the phase listed above, using the numbers from BALANCE.md.

### `game.yaml`

```yaml
tick_rate_hz: 20
max_timer_seconds: 3600
room:
  idle_shutdown: 2m
  autosave_interval: 30s
  reconnect_grace: 5s
  aoi_tiles: { x: 40, y: 26 }      # half-extents (~2 screens at default zoom)
  monster_wake_radius_chunks: 2
  monster_despawn_after: 60s
  far_ai_hz: 10
  lag_comp_max: 200ms
  dodge_grace: 100ms
mode_switch:
  combat_lock: 5s
rate_limits:
  auth: { per_ip_per_min: 10, per_username_per_min: 5 }
  actions_per_min: 120
  ws_input_per_s: 25
build_queue: { base_slots: 2, bonus_slot_at_town_hall: 4 }
plot: { start_size: 24, max_size: 48 }
```

### `buildings.yaml`

```yaml
level_time_curve: &std_times [10s, 45s, 5m, 15m, 40m]     # build(L1), L2, L3, L4, L5

buildings:
  lumber_camp:
    category: production
    footprint: [2, 2]
    unlock_town_hall: 1
    max_count: [1, 2, 2, 3, 3]          # by Town Hall level 1..5
    staffed_by: 2                        # villager slots; unstaffed → 25% output
    produces: wood
    levels:
      - { cost: { wood: 40, stone: 20 },               time: 10s, rate_per_hour: 60 }
      - { cost: { wood: 100, stone: 50 },              time: 45s, rate_per_hour: 100 }
      - { cost: { wood: 120, planks: 60, stone: 60, bricks: 30, coins: 100 },     time: 5m,  rate_per_hour: 160 }
      - { cost: { wood: 280, planks: 140, stone: 140, bricks: 70, coins: 400 },   time: 15m, rate_per_hour: 240 }
      - { cost: { wood: 600, planks: 300, stone: 300, bricks: 150, coins: 1200, ironbark: 4 }, time: 40m, rate_per_hour: 350 }
    sprite: building.lumber_camp          # manifest key; level overlays resolved by the overlay kit
    beauty: 0

  forge:
    category: crafting_station
    footprint: [2, 2]
    unlock_town_hall: 1
    max_count: [1, 1, 1, 2, 2]
    levels:
      - { cost: { wood: 80, stone: 120, ore: 20 }, time: 10s }
      # …
```

### `combos.yaml` (secret: never sent to the client) — as built

```yaml
combos:
  forge_lumber:
    name: Spearwright
    buildings: [forge, lumber_camp]        # edge adjacency; a 3-combo must be one connected group
    unlocks: [spear]                       # each must have a gear recipe forged at a building in the combo
    hint: Something that burns, beside something that grows tall.
  forge_mine_tannery:
    name: Armoury
    buildings: [forge, mine, tannery]
    unlocks: [plate_armour]
    legendary_eligible: true               # P8: 2-combos cap at epic
    hint: Fire, ore and leather, all touching.
```

### `recipes.yaml` / `forging.yaml` (as built)

```yaml
intermediates:
  ingots: { station: forge, inputs: { ore: 3 }, time: 4s, max_batch: 30 }   # time is per unit
job_slots: { default: [1, 1, 1, 1, 1], workshop: [1, 1, 2, 2, 2] }
gear:
  spear: { station: forge, copper: { wood: 20, ore: 10 }, base: { planks: 4, ingots: 3 } }
```

```yaml
tiers:     [{ name: Copper, material_mult: 0, coins: 0, crystal: 0, time: 5s, durability: 120, repair_coins: 0.3 }, …]
rarities:  [{ key: common, weight: 60, slots: 0, value_floor: 0 }, …]   # must be common → legendary
luck_k: 0.1
modifiers: { ironbark: { key: heavy, name: Heavy, effect: knockback, range: [0.4, 0.8] } }
```

The loader checks that every combo building exists, every unlocked item has a gear recipe forged inside that combo, every gear item is unlocked by some combo, and every modifier comes from a rare material.

### `combat.yaml` (as built, Phase 5)

```yaml
crit_mult: 1.75
attack_scaling: 0.02          # damage × (1 + attack × this)
defence_k: 100                # taken = incoming × (1 − def / (def + k))
tier_mult: [1.0, 1.35, 1.8, 2.4, 3.2]
dodge: { stamina: 20, duration: 300ms, distance: 3.0, iframes: 250ms, cooldown: 350ms }
lag_comp_max: 200ms
dodge_grace: 100ms
weapons:
  sword:
    light:                     # one entry per combo swing; arc = degrees, range = tiles
      - { dmg: 10, windup: 60ms, active: 110ms, recover: 170ms, shape: arc, arc: 120, range: 1.55, knockback: 0.5 }
    combo_window: 450ms
    heavy: { dmg: 24, windup: 280ms, active: 130ms, recover: 300ms, stamina: 25, shape: arc, arc: 200, range: 1.9 }
    ability: { kind: spin, dmg: 18, hits: 3, interval: 200ms, range: 1.9, cooldown: 8s, windup: 100ms, recover: 250ms }
  spear:                       # line shapes use range + width; `dash` lunges the avatar during the active phase
    heavy: { dmg: 30, …, shape: line, range: 1.7, width: 0.9, dash: 3.0 }
    ability: { kind: throw, dmg: 26, speed: 14, range: 7, cooldown: 6s, … }
```

Durations are converted to whole 50 ms ticks once on the server (`sim/rules.py`) and sent to the client as `config.sim`, so prediction uses the exact same numbers.

### `nodes.yaml` / `enemies.yaml` (as built)

```yaml
nodes:
  tree: { objects: [obj.oak, obj.pine, …], hits: 3, yields: { wood: [6, 10] }, respawn: 5m, xp: 2, sound: chop }
  ancient_oak: { objects: [obj.big_oak], biome: forest, hits: 6, yields: { wood: [10, 12], ironbark: [1, 2] }, … }

enemies:
  wolf:
    archetype: chaser
    hp: 70
    dmg: 13
    defence: 4
    speed: 4.6
    group: [2, 3]
    attack: { shape: line, range: 1.7, width: 0.9, trigger: 2.3, windup: 480ms, active: 200ms, recover: 700ms, lunge: 1.8 }
    loot: [{ item: hide, chance: 0.45, qty: [1, 2] }, { item: wolf_fang, chance: 0.25, qty: [1, 1] }]
    elite_name: Alpha Wolf
biomes:
  forest: { difficulty: 2, groups_per_chunk: 0.75, roster: { wolf: 0.55, spider: 0.45 }, elite_chance: 0.08, xp: 22, coins: [3, 6] }
```

### `weapons.yaml` (original plan, superseded by `combat.yaml → weapons`)

```yaml
tier_mult: { copper: 1.0, iron: 1.35, steel: 1.8, mythril: 2.4, starforged: 3.2 }
tier_durability: { copper: 120, iron: 160, steel: 220, mythril: 300, starforged: 400 }

weapons:
  sword:
    slot: main
    sprite: weapon.sword                   # palette ramp per tier (P7)
    light:
      combo: [ { dmg: 10, windup: 60ms, active: 90ms, recover: 200ms, hitbox: { arc: 110, range: 1.4 } },
               { dmg: 10, windup: 60ms, active: 90ms, recover: 200ms, hitbox: { arc: 110, range: 1.4 } },
               { dmg: 16, windup: 90ms, active: 110ms, recover: 320ms, hitbox: { arc: 140, range: 1.6 }, knockback: 1.2 } ]
      combo_window: 400ms
    heavy:  { dmg: 24, charge: 350ms, stamina: 25, hitbox: { arc: 160, range: 1.8 }, knockback: 1.5 }
    ability:{ kind: spin, dmg_per_hit: 18, hits: 3, radius: 1.8, cooldown: 8s }
```

### `enemies.yaml`

```yaml
enemies:
  wolf:
    biome: whispering_forest
    ai: chaser
    ai_params: { aggro_radius: 7, leash: 14, circle_strafe: true }
    stats: { hp: 70, dmg: 12, defence: 4, speed: 5.5 }
    attacks:
      - { name: lunge, range: 1.6, windup: 450ms, telegraph: { shape: line, length: 2.0 }, cooldown: 1.6s }
    xp: 25
    loot: forest_beast_small
    elite: { key: alpha_wolf, hp_mult: 4.0, dmg_mult: 1.6, scale: 1.4, loot: forest_elite }
    sprite: monster.wolf
scaling:
  night: { hp: 1.25, dmg: 1.15, loot_qty: 1.5, rare_chance: 2.0 }
  coop_hp_per_extra_player: 0.5          # within 20 tiles
  coop_radius: 20
```

### `loot_tables.yaml`

```yaml
tables:
  forest_beast_small:
    rolls: 1
    coins: [3, 6]
    entries:
      - { item: hide,          qty: [1, 2], weight: 60 }
      - { item: wolf_fang,     qty: 1,      weight: 25 }
      - { nothing: true,                    weight: 15 }
    bonus:                                   # independent chance rolls
      - { item: blueprint_lantern_post, chance: 0.01 }
      - { table: gear_drop_t2,          chance: 0.02 }
```

### `market.yaml`

As built in Phase 7 (`config/market.yaml`): `recalc_interval`, `window`, `active_window`, `history_retention`, `defaults {k, clamp, min_population, over_cap_mult}`, `trend {lookback, threshold}`, `sparkline {points, span}`, `max_sell`, and `items.<key> {base, baseline, soft_cap, k?, over_cap_mult?}`. The Market's per-level bonus is `buildings.yaml → market.sell_bonus`; bag/bank expansion costs are `game.yaml → containers`. The loader checks every item exists and stacks, the clamp straddles 1, the window is a whole number of recalcs, and that no merchant entry the market also buys can be resold at a profit. The original sketch:

```yaml
recalc_interval: 10m
history_retention: 30d
defaults: { k: 0.6, clamp: [0.4, 2.5], min_population: 20 }
items:
  wood:      { base_price: 2,   per_player_baseline: 400, daily_soft_cap: 2000, over_cap_mult: 0.5 }
  ember_core:{ base_price: 110, per_player_baseline: 2,   daily_soft_cap: 20,   over_cap_mult: 0.5, k: 0.4 }
player_market:
  listing_fee: 0.05
  min_fee: 1
  duration: 48h
  max_active_listings: 20
  new_account_gate: { min_level: 5, or_account_age: 24h }   # P4
```

### `world_clock.yaml` (as built, Phase 10)

```yaml
day_cycle: { length: 24m, phases: { dawn: 2m, day: 14m, dusk: 2m, night: 6m } }   # in order, must sum to length
season_length: 7d
seasons: [spring, summer, autumn, winter]
night: { hp: 1.25, dmg: 1.15, loot_qty: 1.5, rare_chance: 2.0, groups: 1.4 }
weather:
  block: 20m
  states:
    clear: { weights: { spring: 50, summer: 65, autumn: 45, winter: 45 } }
    rain:  { weights: { …, winter: 0 }, production: { food: 1.2, herbs: 1.15 } }
    snow:  { weights: { winter: 30 }, production: { food: 0.85 }, rare_node: { frost_spire: 1.5 } }
    fog:   { weights: …, aggro: 0.7 }
    storm: { weights: …, production: { food: 1.1 }, storm_spawns: 0.25 }
```

The loader checks that the phases sum to the length and come in order, that a `clear` state exists, that every season has some weather, and that production keys are real resources.

### `pois.yaml` (Phase 10)

```yaml
interact_radius: 2.4
clear_radius: 3
min_spacing: 16
bands:  { forest: { ruins: 3, shrine: 2, lore_stone: 2, cave: 1, merchant: 1, lost_villager: 2 }, … }
chests: { forest: { coins: [40, 80], rolls: 2, pool: { hide: [2, 4], … }, rare: { ironbark: 0.25 } }, … }
shrines: { cooldown: 20h, duration: 10m, blessings: { might: { damage: 0.2 }, ward: { defence: 0.25 }, fortune: { coins: 0.5 } } }
lost_villager: { xp: 40, coins: [30, 80], names: [Wren, Odo, …] }
lore_xp: 15
lore: { meadow: [{ title, text }, …], … }
```

The loader checks that every ring with ruins has chest loot and every ring with lore stones has lore. Chest items must be real items or resources, with sane ranges and chances.

### `enemies.yaml` additions (Phase 10)

- **Per enemy:**
  - `shot` (kiters: `speed`, `radius`, `sprite`, `chain`, `chain_radius`, `chain_dmg`) and `keep_away`.
  - `summon` (`enemy`, `count`, `every`, `max_alive`).
  - `split` (`into`, `count`).
  - `roaming` (stats scaled by the biome it turns up in).
  - `attack.at_target` + `attack.root`. `elite_name` is now optional; null means it never spawns as an elite.
- **Per biome:** `scale: { hp, dmg, defence }` (BALANCE §6.2).
- **Top level:** `coop: { hp_per_player, radius }`, `storm_enemy`, `minion_xp`.
- **Cross-checks:** shot attacks need a shot block, only at-target circles root, summon/split targets exist and don't chain, roster enemies need an elite name, and the storm enemy must be roaming.

### Phase 11 additions

- **`combat.yaml`**
  - **Weapons.** warhammer, mace, bow, crystal_staff, enchanted_sword, harpoon, arcane_bow.
  - **Moves.** A move can now use `shape: circle | shot | starfall | barrier`, and the options `speed`, `pierce`, `aoe`, `homing`, `count`, `spread`, `hits`, `interval`, `stun`, `pull`, `status`, `proc`, `duration`, `sprite` and `impact`.
  - **New sections.** `offhands` (shield/bombs/tome numbers), `statuses` (burn/poison/slow) and `armour_move` (plate: speed 0.95, dodge 0.9).
- **`items.yaml`.** Offhands carry `offhand_type`. Consumables carry `use: { heal | stamina + regen | buff + value, duration, cooldown, group }`.
- **`recipes.yaml`.** New `consumables:` section (`station`, `inputs`, `time`, `makes`, `max_batch`, `min_tier`), plus the bread and potion_base intermediates and gear bills for every new weapon and offhand.
- **`combos.yaml`.** All 13 combos (D-084).
- **`forging.yaml`.** Modifiers for swamp venom, frost shard, ember core and moonpetal.
- **Loader cross-checks.**
  - Unlocks must be gear or consumable recipes.
  - Consumables need `use`, offhands need `offhand_type`.
  - `armour_move` keys must be armours.

## Secrets in the client bundle

Sections marked secret are stripped from `GET /api/config`:

- `combos.yaml` (all of it)
- `mapgen.yaml → pois` (secret POIs)
- lore texts for unread stones
- `achievements.yaml → hidden: true` entries

The client gets per-player views of these from the API (the recipe book, discoveries, a hint-only list).
