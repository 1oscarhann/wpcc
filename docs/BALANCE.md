# Balance: first pass

> These are starting numbers to get a playable game, not final tuning. Every value here becomes YAML in `/config` (see CONFIG.md). The vertical-slice systems (Phases 2–8) are specified in detail. Later systems get enough numbers to pin down the shape, and get tuned in their own phase.

## 0. Pacing targets (what the numbers are aiming for)

| Moment | Target |
|---|---|
| First combo discovered (tutorial spear) | < 5 min |
| Town Hall 2 | ~20 min |
| Town Hall 3 | ~2–3 h of play (spread over days) |
| Town Hall 5 | ~20–30 h |
| Avatar level 10 | ~5 h |
| Avatar level 30 | ~60–80 h |
| A typical short session (15 min) | at least one upgrade finished, one fight won, one thing sold or forged |
| Longest single timer | 45 min (TH4→5); nothing above 1 h |
| Offline production | fills storage in ~8–16 h, so a once-a-day player never wastes much |

---

## 1. New player start

| Thing | Value |
|---|---|
| Coins | 200 |
| Resources | wood 300, stone 200, food 200, ore 50 |
| Pre-placed | Town Hall L1 (centre), House L1 |
| Plot | 32×32 (D-041), with a 6×4 pond near one edge (for the Fishing Dock), overgrown with ~70 pieces of clearable debris (D-040) |
| Inventory / bank / mailbox | 24 / 60 / 50 slots |
| Starter gear | Training Sword (copper, common, 120 durability), 3× Small Healing Potion |
| Build queue | 2 slots (3 at TH4) |

---

## 2. Buildings

### 2.1 Town Hall

| Level | Upgrade cost | Time | Unlocks | Base storage cap |
|---|---|---|---|---|
| 1 | (start) | — | House, Storehouse, Market, Lumber Camp, Quarry, Farm, Forge, Walls, Training Dummy · deco set *Rustic* | 1,000 |
| 2 | 200 wood, 150 stone, 100 coins | 55 s | Mine, Herb Garden, Workshop, Alchemist, Fishing Dock, Gate, Guard Post, Pet House · deco *Garden* | 1,500 |
| 3 | 600 wood, 500 stone, 150 ore, 400 coins | 8 min | Wizard Tower, Tannery, Tavern, Watchtower, Trophy Hall, Stable · deco *Festival* | 2,000 |
| 4 | 800 planks, 700 bricks, 500 ore, 1,200 coins, **5 Ironbark** | 20 min | 3rd build slot, 2nd Forge · deco *Noble* | 2,500 |
| 5 | 2,000 planks, 1,750 bricks, 1,400 ore, 40 crystal, 4,000 coins, **5 Starstone** | 45 min | building skins · deco *Starforged* | 3,000 |

TH4 and TH5 need rare materials, so you *have* to adventure (pillar 1). The amounts are small (one or two trips), so it's not a grind wall.

### 2.2 Standard level curve (every building except the Town Hall)

| Level | Time | Cost multiplier (× base cost) | Extra coins | Extra |
|---|---|---|---|---|
| 1 (build) | 10 s | ×1 | — | — |
| 2 | 45 s | ×2.5 | — | — |
| 3 | 5 min | ×6 | 100 | from L3, half the wood is paid as planks and half the stone as bricks (2:1) |
| 4 | 15 min | ×14 | 400 | — |
| 5 | 40 min | ×30 | 1,200 | 4 Ironbark (production/core/defence) or 4 Starstone (crafting stations) |

Other rules:
- A building can't be upgraded above the Town Hall's level.
- **Cancelling** refunds 75% of what was paid.
- **Demolishing** refunds 50% of the base build cost.
- **Undo** (single level, within 60 s, no other action since) refunds 100%.

### 2.3 Building catalogue

| Building | Size | TH | Base cost | Effect per level (L1 → L5) |
|---|---|---|---|---|
| House | 2×2 | 1 | 50 wood, 20 stone | holds 2 / 3 / 4 / 5 / 6 villagers |
| Storehouse | 2×2 | 1 (×1) | 100 wood, 80 stone | +1,000 / +2,500 / +5,000 / +9,000 / +15,000 cap per resource |
| Market | 3×2 | 1 (×1) | 120 wood, 80 stone | sell price +0 / +2 / +4 / +6 / +8% |
| Lumber Camp | 2×2 | 1 | 40 wood, 20 stone | wood/h 60 / 100 / 160 / 240 / 350 |
| Quarry | 2×2 | 1 | 50 wood | stone/h 50 / 85 / 135 / 200 / 290 |
| Farm | 3×3 | 1 | 40 wood, 10 stone | food/h 60 / 100 / 160 / 240 / 350; hide/h 0 / 6 / 10 / 16 / 24 |
| Mine | 2×2 | 2 | 60 wood, 40 stone | ore/h 30 / 50 / 80 / 120 / 175; crystal/h 0 / 0 / 4 / 8 / 14 |
| Fishing Dock | 2×3 | 2 | 60 wood, 20 stone | fish/h 20 / 35 / 55 / 80 / 115 (must touch water) |
| Herb Garden | 2×2 | 2 | 40 wood, 20 stone | herbs/h 25 / 40 / 65 / 95 / 140 |
| Forge | 2×2 | 1 | 80 wood, 120 stone, 20 ore | ingot crafting; weapon tier = combo's lowest building level |
| Workshop | 2×2 | 2 | 120 wood, 60 stone | planks, bricks; 1 job slot (2 at L3+) |
| Alchemist | 2×2 | 2 | 100 wood, 80 stone, 30 herbs | potion base, potions |
| Wizard Tower | 2×2 | 3 | 80 wood, 150 stone, 20 crystal | arcane combos |
| Tannery | 2×2 | 3 | 100 wood, 40 stone, 20 hide | leather |
| Tavern | 3×2 (×1) | 3 | 150 wood, 80 stone, 50 food | bread; happiness "tavern access" |
| Walls | 1×1 | 1 | 5 stone | wave defence: monsters path around them; HP per level |
| Gate | 2×1 | 2 | 40 wood, 40 stone | lets guards/villagers through walls |
| Watchtower | 1×1 | 3 | 80 wood, 100 stone | wave defence: arrows 6 / 9 / 13 / 18 / 24 dmg every 1.2 s, range 7 |
| Guard Post | 2×2 | 2 | 60 wood, 80 stone, 20 ore | 1 / 1 / 2 / 2 / 3 guard slots; guard stats +15%/level |
| Trophy Hall | 3×3 (×1) | 3 | 200 wood, 300 stone, 50 ore | 2 / 4 / 6 / 8 / 10 display slots |
| Stable | 3×2 (×1) | 3 | 200 wood, 100 stone, 100 food | mounts (1 at L1, 2 at L3, 3 at L5) |
| Pet House | 2×2 (×1) | 2 | 120 wood, 60 stone, 50 food | pets (1 / 1 / 2 / 2 / 3 active-able) |
| Training Dummy | 1×1 | 1 | 30 wood | shows DPS, tests combos |

**Count limits by Town Hall level** (TH1 → TH5):

| Building | Limits |
|---|---|
| House | 3 / 5 / 7 / 9 / 12 |
| Lumber Camp, Farm | 1 / 2 / 2 / 3 / 3 |
| Quarry | 1 / 1 / 2 / 2 / 3 |
| Mine, Herb Garden | 0 / 1 / 1 / 2 / 2 |
| Fishing Dock | 0 / 1 / 1 / 1 / 2 |
| Forge | 1 / 1 / 1 / 2 / 2 |
| Other crafting stations | 1 each once unlocked |
| Guard Post | 0 / 1 / 2 / 3 / 4 |
| Watchtower | 0 / 0 / 1 / 2 / 3 |
| Walls | 20 / 40 / 60 / 80 / 100 |

Units marked ×1 are unique.

### 2.4 Plot expansion

| Size | 32 | 36 | 40 | 44 | 48 |
|---|---|---|---|---|---|
| Coins | — | 1,200 | 3,500 | 8,000 | 15,000 |
| Needs TH | — | 2 | 3 | 4 | 5 |

---

## 3. Resources and production

- **Raw resources:** wood, stone, ore, food, herbs, fish, hide, crystal.
- **Intermediate goods:** planks, bricks, ingots, leather, bread, potion base. These share the storehouse cap and live in the village pool.
- **Storage cap per resource** = Town Hall base cap + Storehouse bonus. Crystal's cap is 10% of that.
- **Lazy calculation:**

  ```
  amount(t) = min(cap, amount(t0) + Σ over weather blocks b in [t0, t]: base_rate × weather_mult(b) × overlap_hours(b))
  ```

  - It's settled (written back) on every read-modify-write and whenever a rate changes (build, upgrade, staffing, happiness).
  - The cap applies per weather block. A resource that's already over the cap (for example from a deposit) never decreases.
- **Staffing:** an unstaffed production building runs at 25%. *Until villagers ship (Phase 14), every building counts as fully staffed* (`villagers.enabled: false`).
- **Happiness bonus:** `production × (1 + 0.25 × max(0, (happiness − 50) / 50))`, so +0% at happiness 50 and +25% at 100.
- **Villager food demand:** 4 food/h per villager is subtracted from the net food *rate*, floored at 0 (P10).

### 3.1 Intermediate goods (crafting jobs, short timers)

| Good | Station | Input → output | Time per unit | Max batch |
|---|---|---|---|---|
| Ingot | Forge | 3 ore → 1 | 4 s | 30 |
| Plank | Workshop | 2 wood → 1 | 2 s | 30 |
| Brick | Workshop | 2 stone → 1 | 2 s | 30 |
| Leather | Tannery | 2 hide → 1 | 4 s | 30 |
| Bread | Tavern | 3 food → 1 | 3 s | 30 |
| Potion base | Alchemist | 3 herbs → 1 | 4 s | 20 |

A batch of 30 planks takes 60 s, which is the upper bound on purpose.

### 3.2 Clearing your plot (Build Mode, D-040)

| Debris | Yield | Share of debris |
|---|---|---|
| Oak / big oak / birch / pine | 10 / 18 / 8 / 9 wood | ~40% |
| Apple tree | 6 wood + 8 food | ~4% |
| Rock / big rock | 6 / 14 stone (+25% / 50% chance of 2–3 ore) | ~19% |
| Bush / flowering bush | 4 food | ~14% |
| Stump / fallen log | 4 / 12 wood | ~7% |
| Weeds and mushrooms | 2 herbs | ~12% |

Clearing is free and instant. A fresh plot has about 70 pieces (≈350 wood, 120 stone, 60 food, some ore and herbs), which is roughly the TH2 upgrade plus the first production buildings.

### 3.3 Hand gathering (Avatar Mode)

| Node | Biome | Hits | Yield | Per-player respawn |
|---|---|---|---|---|
| Tree | meadow+ | 3 | 6–10 wood | 5 min |
| Rock | meadow+ | 3 | 5–8 stone, 15%: 1–2 ore | 5 min |
| Ore vein | meadow edge+ | 4 | 4–6 ore | 8 min |
| Herb patch | meadow+ | pick | 3–5 herbs | 4 min |
| Ancient Oak | forest | 6 | 10 wood + 1–2 **Ironbark** | 20 min |
| Star Vein | stonepeak | 6 | 2–4 crystal + 1–2 **Starstone** | 25 min |
| Venom Bloom | swamp | pick (puffs a poison cloud with a telegraph, so dodge it) | 1–2 **Swamp Venom** | 25 min |
| Frost Spire | frozen | 6 | 1–2 **Frost Shard** | 30 min |
| Lava Vent | ashen | timing tap | 1 **Ember Core** | 30 min |
| Moonpetal | any biome ≥ 2, **night only** | pick | 1 **Moonpetal** | each night |
| Fishing spot | water | minigame | fish species (see §11) | 2 min |

Hand-gathered resources are worth ~1 minute of L1 production per hit, so a 10-minute meadow gathering run (~200 wood) beats ~3 h of an L1 Lumber Camp. That's how Avatar Mode feeds Build Mode early. Later it's rares that matter.

---

## 4. Avatar

| Stat | Base (L1) | Per level | L30 |
|---|---|---|---|
| HP | 100 | +8 | 332 |
| Stamina | 100 | +1 | 129 |
| Attack | 10 | +1 | 39 |
| Defence | 5 | +1 | 34 (+ armour) |
| Crit chance | 5% | — (skills, modifiers) | 5% |
| Move speed | 5.0 tiles/s | — | 5.0 (mount 9.0) |

**XP to next level** = `round(80 × L^1.55 + 20)`:

| Level | 1 | 2 | 5 | 10 | 15 | 20 | 25 | 29 |
|---|---|---|---|---|---|---|---|---|
| XP to next | 100 | 254 | 989 | 2,859 | 5,341 | 8,332 | 11,766 | 14,805 |

The cumulative total to level 30 is about 176k XP.

**XP sources:**

| Source | XP |
|---|---|
| Kill, by biome | 8 / 22 / 55 / 100 / 160 / 250 |
| Elite kill | ×5 |
| Hand-gathered node | 2 (rare node 15) |
| Dungeon clear | 200 × difficulty |
| Realm boss | 1,500 → 12,000 by tier |
| Daily quest | 150 + 25×level |
| Weekly quest | 600 + 100×level |

**Out-of-combat regen:** after 5 s with no damage, heal 6% of max HP per second, so you're never stuck waiting.

**KO:**
- You wake at the Town Hall with full HP.
- You lose 25% (rounded down per stack, minimum 1 if the stack is ≥ 2) of **rare materials in your inventory**.
- That loss drops as a marker for 5 min. You or a party member can recover it, and anything a friend picks up gets mailed back (P13).

---

## 5. Combat

### 5.1 Formula and constants

```
damage   = weapon_base × tier_mult × (1 + attack × 0.02) × rarity_mult × (crit ? 1.75 : 1) × (dull ? 0.7 : 1)
taken    = incoming × (1 − defence / (defence + 100))
```

| Constant | Value |
|---|---|
| Stamina regen | 30/s after 0.6 s without spending |
| Dodge | 20 stamina, 3 tiles over 280 ms, i-frames 220 ms, 350 ms cooldown |
| Hit-stop | light 40 ms · heavy 55 ms · crit/kill 60 ms |
| Screen shake | heavy and crit only: 3 art-px, 120 ms (respects the "reduce motion" setting) |
| Knockback | base 0.6 tiles, × weapon and modifier multipliers; tanks and bosses × 0.2 |
| Combat lock (no mode switch) | 5 s after dealing or taking damage |

### 5.2 Tiers and rarity

| Tier | Building level | Damage multiplier | Durability | Repair coins per point |
|---|---|---|---|---|
| Copper | 1 | 1.00 | 120 | 0.3 |
| Iron | 2 | 1.35 | 160 | 0.6 |
| Steel | 3 | 1.80 | 220 | 1.2 |
| Mythril | 4 | 2.40 | 300 | 2.0 |
| Starforged | 5 | 3.20 | 400 | 3.5 |

| Rarity | Colour | Damage multiplier | Modifier slots | Base weight |
|---|---|---|---|---|
| Common | grey `#9aa0a6` | 1.00 | 0 | 60 |
| Uncommon | green `#4caf50` | 1.08 | 1 | 26 |
| Rare | blue `#3d8bfd` | 1.18 | 1 | 10 |
| Epic | purple `#a259ff` | 1.30 | 2 | 3.5 |
| Legendary | orange `#ff9f1c` | 1.45 | 3 | 0.5 (only if eligible, P8; otherwise its weight folds into Epic) |

**Rarity roll:** `weight_i × exp(0.1 × luck × i)` with i = 0 (common) … 4 (legendary), then normalized.

Luck sources:
- Crafting skill *Master's Touch* gives +1 per rank (max 5).
- Each rare material added gives +1 (max 3).
- A Boss Trophy gives +2 and makes the weapon Legendary-eligible.

| Luck | Common | Uncommon | Rare | Epic | Legendary |
|---|---|---|---|---|---|
| 0 | 60.0% | 26.0% | 10.0% | 3.5% | 0.5% |
| 3 | 48.5% | 28.4% | 14.7% | 7.0% | 1.3% |
| 6 | 35.9% | 28.3% | 19.8% | 12.7% | 3.3% |
| 9 | 23.5% | 25.1% | 23.7% | 20.4% | 7.2% |

**Durability** drops by 1 per hit landed. At 0 the weapon is **Dull** (P2): −30% damage and modifiers off, but it never breaks. Repair costs `missing × coin rate` coins plus `ceil(missing / 40)` ingots.

**Salvage** returns 40% of non-coin inputs (rounded down), plus a 30% chance per rare material used to get it back.

### 5.3 Modifiers (from rare materials added at forging)

Each rare material added guarantees its modifier, up to the item's slot count. Empty slots give a flat +3% damage ("Polished"). The value rolls within its range, and higher rarity raises the floor.

| Rare material | Modifier | Effect | Range |
|---|---|---|---|
| Ironbark | Knockback | +knockback | +40–80% |
| Starstone | Keen | +crit chance | +4–10% |
| Swamp Venom | Venom | poison: 40% of hit damage over 5 s, stacks ×3 | proc 20–35% |
| Frost Shard | Frost | slow 35% for 2 s | proc 20–35% |
| Ember Core | Fire | burn: 30% of hit damage over 3 s | proc 25–40% |
| Moonpetal | Lifesteal | heal % of damage dealt | 3–8% |
| Ancient Rune | Chain Lightning | arcs to 2 enemies within 3 tiles for 50% damage | proc 15–25% |
| Boss Trophy | (boss-specific) | e.g. Gel Crown: "Bouncy": kills spawn a friendly slime for 5 s | — |

### 5.4 Weapons (base values at copper; tier and rarity multiply them)

| Weapon | Combo | Light | Heavy (stamina) | Ability, Q (cooldown) | Rough DPS* |
|---|---|---|---|---|---|
| Sword | Forge+Mine | 3-hit 10/10/16, arc 110°, reach 1.4 | wide slash 24, 160°, 1.8 (25) | spin 3×18, r1.8 (8 s) | 39 |
| Spear | Forge+Lumber | thrust 14, line 2.4, 0.45 s | charge lunge 30, dash 3 (30) | throw 26, pierces, returns (6 s) | 37 |
| Warhammer | Forge+Quarry | 26, arc 120°, 1.5, 0.8 s, big knockback | ground slam 40, r2.2 (35) | earthquake 20 + stun 1.5 s, r3.5 (12 s) | 39 |
| Mace | Forge+Quarry | 19, arc 100°, 1.4, 0.6 s | slam 30, r1.8 (30) | earthquake (12 s) | 38 |
| Bow | Forge+Lumber | shot 9, 14 t/s, range 9, 0.3 s | charged pierce 28, 0.8 s charge (20) | volley 6×8, cone (10 s) | 36 |
| Crystal Staff | Wizard+Quarry | bolt 11, 10 t/s, range 8, 0.4 s | charged orb 34 AoE r1.5 (25) | crystal barrier, 3 s, blocks projectiles (14 s) | 33 |
| Enchanted Sword | Forge+Wizard | 11/11/17 + elemental trail | elemental wave 26, projectile (25) | elemental burst 40, r2.5 (10 s) | 43 |
| Harpoon | Dock+Forge | thrust 15, line 2.6, 0.5 s | pull 12 + yank to you (25) | whirlpool 6×8, pulls in, r3 (12 s) | 36 |
| Arcane Bow | Forge+Lumber+Wizard | 11, slight homing, 0.3 s | charged 34, pierce + element (20) | starfall 8×10 (10 s) | 44 |

\*Rough DPS = sustained light-attack DPS at L1 stats (attack 10), copper, common.

**Offhands** go in a separate key, **F** (P19; touch gets a 4th button):

| Offhand | Combo | Use |
|---|---|---|
| Shield | Forge+Mine | +defence 6/9/13/18/24 by tier; hold F to block 60% of frontal damage, 10 stamina per blocked hit |
| Barrel Bombs | Tavern+Workshop | throw: 45 AoE r2, 1.2 s fuse, 3 charges, recharge 6 s each |
| Elemental Tome | Wizard+Alchemist+Herb | spell by element: 30 damage + status (7 s) |

**Armour:**

| Armour | Defence by tier (copper → starforged) | Notes |
|---|---|---|
| Leather (Tannery+Workshop) | 8 / 12 / 18 / 26 / 36 | −0% move speed |
| Plate (Forge+Mine+Tannery) | 15 / 22 / 32 / 45 / 60 | −5% move speed, −10% dodge distance |

### 5.5 Forging bills

**Copper** uses raw resources (so the tutorial spear works at TH1). **Iron and up** use intermediates × a tier multiplier.

| Weapon | Copper bill | Iron+ base bill |
|---|---|---|
| Spear, Bow | 20 wood, 10 ore | 4 planks, 3 ingots |
| Sword, Shield | 10 wood, 20 ore | 2 planks, 5 ingots |
| Warhammer, Mace | 10 wood, 15 stone, 15 ore | 4 bricks, 4 ingots |
| Crystal Staff | 15 wood, 10 crystal | 3 planks, 4 crystal, 2 ingots |
| Enchanted Sword | 10 wood, 15 ore, 8 crystal | 2 planks, 4 ingots, 4 crystal |
| Harpoon | 15 wood, 10 ore, 10 fish | 3 planks, 3 ingots, 10 fish |
| Arcane Bow | — (3-combo: iron+ only) | 5 planks, 3 ingots, 6 crystal |
| Leather / Plate armour | 15 hide / 30 ore | 6 leather / 8 ingots + 3 leather |

| Tier | Material multiplier | Coins | Crystal | Forge time |
|---|---|---|---|---|
| Copper | — | 0 | — | 5 s |
| Iron | ×1 | 30 | — | 10 s |
| Steel | ×2 | 120 | — | 20 s |
| Mythril | ×3.5 | 400 | +10 | 40 s |
| Starforged | ×6 | 1,200 | +30 | 60 s |

### 5.6 Consumables

| Item | Station / combo | Bill | Effect | Cooldown |
|---|---|---|---|---|
| Small Healing Potion | Alchemist+Herb | 1 potion base | heal 35% max HP over 1 s | 8 s (shared) |
| Healing Potion | Alchemist+Herb (L3+) | 2 potion base, 1 fish | heal 60% over 1 s | 8 s |
| Stamina Potion | Alchemist+Herb | 1 potion base, 1 bread | instant full stamina, +50% regen for 10 s | 15 s |
| Buff Food | Alchemist+Farm | 2 bread, 2 herbs | +10% damage or +10% defence or +8% speed for 5 min | — |

---

### 5.7 As built (Phase 5)

The live numbers are in `config/combat.yaml` and `config/enemies.yaml`. Changes from the tables above, all made to favour readability at 16 px and the player (D-009):

| What | Plan | Built | Why |
|---|---|---|---|
| Sword light | arc 110°, reach 1.4 | arc 120°, reach 1.55 | Hits feel fair when the sprite overlaps by a pixel |
| Dodge | 280 ms, i-frames 220 ms | 300 ms (6 ticks), i-frames 250 ms (5 ticks) | Whole 50 ms ticks |
| Enemies (meadow / forest) | archetype table × biome multiplier | slime 24 HP / 5 dmg; wolf 70 / 13 / def 4; spider 60 / 15 + poison 3/s for 4 s | Biome multipliers baked in |
| Gear drops | 1.5% per kill | not yet | Gear needs tiers, rarity and modifiers (Phase 6) |
| Co-op HP scaling | +50% per extra player | not yet | Arrives with realms and parties (Phase 9) |

Sanity check, as built: a starter sword hits a slime for 12, so slimes die in 2 hits (a test checks this).

## 6. Enemies

### 6.1 Archetypes (base stats at difficulty 1)

| Archetype | HP | DMG | DEF | Speed | Attack | Windup (telegraph) |
|---|---|---|---|---|---|---|
| Swarmer | 24 | 5 | 0 | 3.0 | hop bite, circle r0.8 | 400 ms |
| Chaser | 35 | 7 | 2 | 5.0 | lunge, line 1.6 | 450 ms |
| Kiter | 30 | 6 | 1 | 4.0 | projectile, range 8 | 500 ms |
| Charger | 40 | 9 | 2 | 7.0 dash | dash, line 4 | 600 ms |
| Tank | 90 | 10 | 6 | 2.5 | slam, circle r1.6 | 800 ms |
| Summoner | 60 | 4 | 3 | 2.5 | summons 2 swarmers every 6 s; root circle at the player | 900 ms |
| Ambusher | 30 | 9 | 1 | 4.5 | pounce, line 3 (a hiding shimmer shows 600 ms before) | 350 ms |

**Elites** get ×4 HP, ×1.6 damage, ×1.3 sprite scale, and one extra attack.

### 6.2 Biome multipliers

| Difficulty | Biome | HP × | DMG × | +DEF | Coins per kill |
|---|---|---|---|---|---|
| 1 | Meadow | 1.0 | 1.0 | +0 | 1–3 |
| 2 | Whispering Forest | 2.0 | 1.8 | +2 | 3–6 |
| 3 | Stonepeak | 4.0 | 3.0 | +6 | 6–12 |
| 4 | Murkwater Swamp | 6.5 | 4.5 | +10 | 10–20 |
| 5 | Frozen North | 10 | 6.5 | +16 | 15–30 |
| 6 | Ashen Wastes | 14 | 9.0 | +24 | 25–45 |

Other scaling:
- **Night:** ×1.25 HP, ×1.15 damage, ×1.5 loot quantity, ×2 rare-drop chance.
- **Co-op:** HP × (1 + 0.5 × extra players within 20 tiles).
- **Bosses:** HP × (1 + 0.75 × extra participants).

### 6.3 Roster

| Biome | Enemies (archetype) | Elite | Common drop |
|---|---|---|---|
| Meadow | Green Slime (swarmer), Big Slime (tank, splits into 2), Thornhare (charger), Buzzling (kiter) | Crowned Slime | slime gel |
| Forest | Wolf (chaser), Webspinner (ambusher, poison), Bandit Archer (kiter), Bandit Brute (tank), Sapling (summoner) | Alpha Wolf | hide, wolf fang, spider silk |
| Stonepeak | Rock Golem (tank), Ram Goat (charger), Harpy (kiter), Crystal Sprite (summoner), Pebblings (swarmer) | Granite Golem | golem shard |
| Swamp | Bog Lurker (ambusher), Toad Spitter (kiter), Leechlings (swarmer), Mire Shaman (summoner), Snapjaw (charger) | Elder Lurker | bog moss |
| Frozen | Ice Wraith (kiter), Frost Wolf (chaser), Yeti (tank), Snow Imps (swarmer), Rime Stalker (ambusher) | Wraith Queen | frost fur |
| Ashen | Fire Imp (swarmer), Magma Hound (charger), Ash Golem (tank), Cinder Witch (summoner), Ember Archer (kiter) | Obsidian Golem | ember dust |
| Storm (any biome, storm weather) | Storm Elemental (kiter, chain lightning) | — | storm glass (rare-ish) |

**Sanity check, time to kill:**

| Matchup | Time to kill |
|---|---|
| Meadow slime vs starter sword (12 per hit) | 2 hits ✔ "feel powerful" |
| Ashen chaser (490 HP) vs a L25 mythril epic sword (~170 DPS) | ~3 s ✔ |

**Sanity check, damage taken:**

| Matchup | Hits to KO |
|---|---|
| Forest wolf (12.6) vs L5 with 9 def → 11.6 per hit, 132 HP | ~11 hits |
| Ashen chaser (63) vs L25 with plate (74 def) → 36 per hit, 292 HP | ~8 hits |

### 6.4 Loot (example tables; the full ones live in `loot_tables.yaml`)

| Source | Drop |
|---|---|
| Normal kill | coins (biome range) + 60% one common biome material + 1.5% gear drop (tier = biome difficulty, capped at 5) + 0.5% decoration blueprint |
| Elite | 3 rolls, 15% gear, 5% blueprint |
| Night | rolls ×1.5 |
| Loot visibility | per player: every player in range gets their own independent rolls, and drops are visible only to their owner |

---

## 7. Bosses

| Boss | Biome | Solo HP | Phases | Signature attacks | Trophy |
|---|---|---|---|---|---|
| Grubmaw the Slime King | Meadow/Forest edge | 7,500 | 100 / 66 / 33% | belly slam (circle), slime rain (random circles), splits into 4 Slimelings at 33% | Gel Crown |
| The Stone Colossus | Stonepeak | 18,000 | 3 | fist line slam, rockfall, exposed-core window | Colossus Core |
| Swamp Hydra | Swamp | 30,000 | 3 (heads) | poison breath cones; heads regrow unless burned | Hydra Fang |
| Frost Matriarch | Frozen | 45,000 | 3 | ice ring, blizzard (vision ↓), summons Frost Wolves | Matriarch's Tiara |
| Cinder Tyrant | Ashen | 60,000 | 3 | lava-crack lines, meteor circles, enrage at 15% | Tyrant's Heart |

- **Targets:** about 2–4 min solo with tier-appropriate gear, and about the same with 4 players (HP scales).
- **Spawning:** one realm boss spawns every **72 h** (rotating through the biomes realm members have unlocked) and stays **24 h**.
- **Loot:** everyone with ≥ 1% of damage dealt gets loot: XP, coins, rares, and a 20% trophy chance (first kill per boss is guaranteed).
- **World boss weekends:**
  - Global HP = 2,000,000 × number of realms active in the last 7 days.
  - Personal reward tiers at any participation / 5k / 25k / 100k damage.
  - Top 10 realms get a banner cosmetic.

---

## 8. Market and coins

### 8.1 NPC market

```
baseline = per_player_baseline × max(active_players_24h, min_population = 20)          (P1)
price    = base × clamp(exp(−k × (units_sold_24h − baseline) / baseline), 0.4, 2.5) × (1 + market_level_bonus)
```

With k = 0.6, nothing sold gives ×1.82, selling exactly the baseline gives ×1.0, 2× the baseline gives ×0.55, and 3× clamps to ×0.4.

Prices are recalculated every 10 min. After a player passes their per-item daily soft cap, *their* price is ×0.5.

| Item | Base | Per-player baseline/day | Daily soft cap | | Item | Base | Baseline | Soft cap |
|---|---|---|---|---|---|---|---|---|
| wood | 2 | 400 | 2,000 | | planks | 5 | 100 | 600 |
| stone | 2 | 300 | 2,000 | | bricks | 5 | 100 | 600 |
| food | 2 | 300 | 2,000 | | ingots | 12 | 60 | 400 |
| ore | 4 | 120 | 800 | | leather | 14 | 40 | 300 |
| herbs | 4 | 100 | 600 | | bread | 7 | 80 | 500 |
| fish | 6 | 80 | 500 | | potion base | 10 | 40 | 300 |
| hide | 5 | 60 | 400 | | slime gel | 3 | 60 | 400 |
| crystal | 15 | 15 | 100 | | wolf fang / spider silk | 6 / 7 | 30 | 200 |
| Ironbark | 25 | 5 | 40 | | golem shard / bog moss | 14 / 18 | 20 | 150 |
| Starstone | 45 | 3 | 25 | | frost fur / ember dust | 26 / 34 | 15 | 100 |
| Swamp Venom | 60 | 2 | 20 | | Moonpetal | 70 | 2 | 15 |
| Frost Shard | 80 | 2 | 15 | | Ancient Rune | 150 | 1 | 8 |
| Ember Core | 110 | 1.5 | 10 | | Boss Trophies | — | not sellable | — |

### 8.2 Coin sinks

| Sink | Cost |
|---|---|
| Building upgrades (L3+) | 100 / 400 / 1,200 per level |
| Town Hall | 5,700 total |
| Plot expansion | 33,200 total |
| Inventory 24 → 48 (+6 per step) | 300 / 800 / 1,800 / 3,500 |
| Bank 60 → 200 (+20 per step) | 400 / 900 / 1,600 / 2,600 / 4,000 / 6,000 / 9,000 |
| Respec | free weekly, otherwise 100 + 30 × level |
| Repairs | see §5.2 |
| Player market fee | 5% (min 1) |
| Merchant | rotation every 4 h, 6 slots: blueprints 300–2,000, seeds 50–200, pet eggs 2,500–6,000, recipe hints 400, rare decorations 800–5,000 |
| Cosmetics | 500–5,000 |

**Faucet sketch (mid-game, TH3):**
- Passive village output sells for about 1.4k coins/h at base price, capped by storage.
- An active forest or mountain session earns about 3–4k coins/h (kills, drops, sales).
- Total ≈ 5k/h, so an 8k-coin goal takes about 1.5 h of play. The admin economy view tracks faucet vs sink by reason code so this can be re-tuned with real data.

---

## 9. Monster waves

| Rule | Value |
|---|---|
| Eligible | ≥ 3 h since the last wave **and** online ≥ 10 min **and** not in the tutorial **and** TH ≥ 2 |
| Warning | 10 min countdown (`TIMER` message plus a horn sound) |
| Offline at start | postponed, never fired |
| Composition | TH2: 2 waves × 5 (meadow) · TH3: 3 waves forest mix + 1 elite · TH4: 4 waves stonepeak mix + 2 elites · TH5: 4 waves mixed + a mini-boss |
| Guards | 80 HP, 8 damage, +15% per Guard Post level; respawn after the wave |
| Loss | monsters reaching the Storehouse steal up to 10% of each stored raw resource, proportional to how many got through. **Never** destroys or damages buildings |
| Win | 60 × TH coins, a material bundle, a 25% chance at a rare material roll, wave achievement progress |
| Report line pool | "The goblins ran off with your bread, again." · "Three slimes now live in your storehouse. They seem happy." · … (`waves.yaml`) |

---

## 10. Villagers, happiness, beauty (Phase 14)

```
happiness = 100 × (0.35 × beauty_norm + 0.25 × housing + 0.25 × food + 0.15 × tavern)
beauty_norm = min(1, beauty_score / (plot_tiles × 0.12))
housing = min(1, housing_capacity / villagers)     food = min(1, gross_food_rate / (villagers × 4))
tavern = 1 if a Tavern exists within 12 tiles path-distance of most homes, else 0
```

- **Beauty points:**
  - flower bed 2, hedge 1, lantern 1.5, bench 1, tree 1.5, well 4, fountain 8, statue 6, banner 2, market stall 3, seasonal item 3;
  - +1.5 per *distinct* decoration type (variety);
  - +2 per building connected to the Town Hall by paths;
  - 0.5 per nature tile.
- **Arrivals:** a new villager arrives every 10 min (settled lazily) if there's free housing and happiness ≥ 40. A villager leaves if happiness stays < 20 for 2 h (the warning comes first via speech bubbles).

---

## 11. Progression and misc (Phase 16)

| System | First pass |
|---|---|
| Skill tree | 3 branches × ~10 nodes, 1 point per level (29 total). Combat: +3% damage per rank, faster light attack, dodge leaves frost/fire trail, weapon mastery. Gathering: +15% hand yield per rank, faster chop/mine, +rare odds. Crafting: Master's Touch (luck +1 per rank), extra modifier slot (capstone), −10% repair cost per rank, −15% forge time per rank. |
| Daily quests | 3 per day from a pool: "Forge a Rare+ weapon", "Defeat 20 Forest wolves", "Sell 100 wood", "Gather 10 herbs by hand", "Upgrade any building". Rewards: 150 + 25×level XP plus 100–300 coins. |
| Weekly quests | 5 per week, bigger targets. 600 + 100×level XP, 1,000–2,500 coins, plus a cosmetic token. |
| Achievements | stat thresholds, e.g. *Slime Slayer* (500 slimes), *Master Smith* (10 Epic+ forged), *Combo Hunter* (all 13 combos). Each gives a title and/or cosmetic. |
| Login calendar | 28 days, advances only when claimed (no streak loss). Materials on most days, cosmetics on days 7/14/21/28. Never anything required. |
| Pets | fox (+5% gather speed), owl (+10% fog-reveal radius), slime (attacks for 5), frost wolf (slows), ember salamander (burn aura). Bonuses ≤ 10%. |
| Mounts | horse 9 t/s (Stable L1), exotic mounts later. Unavailable in dungeons and in combat. |
| Fishing | timing bar (window 300 ms at the easiest, 120 ms for legendaries), 6–8 species per biome, seasonal specials; sell 8–200 coins. |
| Social | 1 gift/day/friend, value cap 300; help = −25% of remaining time, at most 1 help per timer per day, at most 50% of a timer from helps; new-account gate: level 5 or 24 h (P4). |
| Realm stash | untrusted members withdraw up to 500 value/day; first 48 h deposit-only (P3). |
