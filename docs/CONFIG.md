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
| `combos.yaml` (**secret**) | combo definitions, hints, unlocked recipe groups | 6 |
| `recipes.yaml` | intermediate goods plus gear recipes: inputs per tier, time, station | 6 |
| `weapons.yaml` | weapon types, movesets, hitboxes, timings, stamina, base damage | 5, 11 |
| `armour.yaml` | armour/offhand/trinket stats per tier | 11 |
| `rarity.yaml` | rarity colours, multipliers, modifier slots, roll weights, luck curve | 6 |
| `modifiers.yaml` | modifier effects and value ranges, source materials | 6 |
| `combat.yaml` | damage formula constants, crit, defence curve, statuses, hit-stop, stamina, dodge | 5 |
| `avatar.yaml` | base stats, per-level growth, XP curve, level cap, KO rules, regen | 4, 5 |
| `skills.yaml` | skill tree (3 branches) | 16 |
| `enemies.yaml` | enemy stats, AI behaviour and params, telegraphs, loot refs, night/co-op scaling | 5, 10 |
| `loot_tables.yaml` | weighted tables, nested tables, coin ranges | 5 |
| `biomes.yaml` | ring order, difficulty, enemy spawn tables, nodes, rares, ambience, music | 4, 10 |
| `mapgen.yaml` (POI part **secret**) | ring radii, plot layout, noise params, POI densities, node densities | 3, 9 |
| `nodes.yaml` | gatherable node types, yields, respawn, tool requirements | 4 |
| `dungeons.yaml` | room templates, weights, length, puzzles, bosses, rewards, daily seed rule | 12 |
| `waves.yaml` | wave interval, warning, composition by TH level, steal cap, rewards, report lines | 13 |
| `bosses.yaml` | realm and world bosses: phases, attacks, HP, scaling, loot | 13, 17 |
| `market.yaml` | NPC prices, pricing params, soft caps, recalc interval, listing fee/expiry | 7, 17 |
| `merchant.yaml` | stock pools, rotation period, prices | 7 |
| `villagers.yaml` | name parts, appearance pools, happiness weights, arrival rules, speech lines | 14 |
| `beauty.yaml` | beauty scoring weights | 14 |
| `quests.yaml` | tutorial, main, daily and weekly pools | 8, 16 |
| `achievements.yaml` | stat thresholds → rewards and titles | 16 |
| `cosmetics.yaml` | outfits, dyes, banners, skins, titles | 16 |
| `pets.yaml`, `mounts.yaml`, `fishing.yaml` | pet and mount stats and bonuses, fish per biome/season, minigame timing | 16 |
| `login_rewards.yaml` | calendar | 16 |
| `social.yaml` | gift caps, help %, new-account gates (P4), stash trust rules (P3) | 9, 15 |
| `festivals.yaml` | calendar festivals: dates, decorations, enemies, quests | 17 |
| `presets.yaml` | emotes, quick messages, ping types | 9 |
| `profanity.yaml` | blocked substrings plus leetspeak normalization map | 2 |
| `tutorial.yaml` | steps, guide lines, triggers | 8 |

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

### `combos.yaml` (secret: never sent to the client)

```yaml
combos:
  forge_lumber:
    buildings: [forge, lumber_camp]        # orthogonal edge adjacency; 3-combos must form a connected chain/cluster
    unlocks: [spear, bow]
    legendary_eligible: false              # P8: 2-combos cap at epic unless a boss trophy is added
    hint: "Something that burns, beside something that grows tall."
    discovery_fx: combo_burst_orange
  forge_lumber_wizard:
    buildings: [forge, lumber_camp, wizard_tower]
    unlocks: [arcane_bow]
    legendary_eligible: true
    hint: "Fire, timber and starlight, all touching."
```

### `weapons.yaml`

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

### `world_clock.yaml`

```yaml
day_cycle: { length: 24m, phases: { dawn: 2m, day: 14m, dusk: 2m, night: 6m } }
season_length: 7d
seasons: [spring, summer, autumn, winter]
weather:
  block: 20m
  states:
    clear: { weights: { spring: 50, summer: 65, autumn: 45, winter: 45 } }
    rain:  { weights: { spring: 25, summer: 15, autumn: 30, winter: 0 },
             effects: { production: { farm: 1.2, herb: 1.1 } } }
    snow:  { weights: { winter: 30 }, effects: { rare_node_bonus: { frost_shard: 1.5 } } }
    fog:   { weights: { spring: 15, summer: 5, autumn: 15, winter: 10 }, effects: { wild_vision: 0.6 } }
    storm: { weights: { spring: 10, summer: 15, autumn: 10, winter: 15 }, effects: { spawn_table: storm_specials } }
```

## Secrets in the client bundle

Sections marked secret are stripped from `GET /api/config`:

- `combos.yaml` (all of it)
- `mapgen.yaml → pois` (secret POIs)
- lore texts for unread stones
- `achievements.yaml → hidden: true` entries

The client gets per-player views of these from the API (the recipe book, discoveries, a hint-only list).
