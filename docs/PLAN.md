# Hearthforge: Phase 1 plan

> **Status: waiting for approval.** No game code gets written until this plan is approved.
>
> Companion docs:
> - [SCHEMA.md](SCHEMA.md): full Postgres schema
> - [PROTOCOL.md](PROTOCOL.md): WebSocket protocol and REST route map
> - [CONFIG.md](CONFIG.md): config file formats and validation rules
> - [BALANCE.md](BALANCE.md): first-pass balance tables
> - [ART.md](ART.md): art direction, asset packs, audio, fonts
> - [DECISIONS.md](DECISIONS.md): decision log (it starts here)

---

## 1. Spec issues and proposed changes

I read the whole spec looking for contradictions, things that won't survive contact with real browsers or real players, and things that cost a lot for little fun. These are grouped by how badly I need an answer.

### 1.1 Blocking: decide before Phase 2/3

**B1. Perspective: isometric pixel art can't be built from CC0 packs. Proposal: top-down 3/4 pixel art.**

> **Resolved:** top-down, and all art is original and generated in-house by `tools/artgen` (no packs at all). See ART.md and D-031.
- I couldn't find a cohesive CC0 *isometric pixel-art* pack with animated characters.
  - Kenney's isometric packs are pre-rendered 3D-style sprites, not pixel art, and come with little or no character animation.
  - Kenney's pixel packs (Tiny Town, Tiny Dungeon, Roguelike) are all top-down.
  - Mixing OpenGameArt odds and ends breaks the "one pixel scale, one lighting direction" rule straight away.
- The best CC0 base I found is **Ninja Adventure** (pixel-boy, CC0, 16×16, top-down). It has 50+ animated characters, 30+ animated monsters, 9 animated bosses, 60+ items, tilesets, 30+ FX, UI, 2 fonts, 37 music tracks and 100+ SFX. It is one cohesive style, which is what consistency needs.
- Top-down also fixes three engineering problems:
  - Orthogonal adjacency, which is the whole combo system, reads instantly on screen. In isometric, edge-adjacent tiles look diagonal.
  - There's no isometric depth-sorting or skewed hitbox maths in the action combat.
  - Stardew Valley, the main "cozy" reference, is top-down 3/4 anyway.
- Cost of this change: no "diorama" look, and the visual flavour leans Zelda-like with a light Japanese tint (Ninja Adventure's theme) rather than European medieval. A palette pass and the Kenney Tiny Town props can pull it back towards medieval.
- **Alternatives if you refuse:**
  - (a) Isometric with Kenney's non-pixel isometric renders. Clean, but no animated characters or monsters, so the juice and combat suffer badly.
  - (b) Isometric pixel art commissioned or drawn later. Until then I'd build with placeholder art, which defeats the "check the screenshots" loop.
  - (c) LPC (Liberated Pixel Cup), which has a real layered character generator and walk/slash/thrust/shoot/spellcast animations that map perfectly onto the weapon movesets. But it's CC-BY-SA/GPL (attribution plus share-alike), 32px, and top-down too.

**B2. Hosting layout breaks login on Safari. Proposal: a custom domain with an `api.` subdomain.**
- The frontend on `*.pages.dev` and the API on `*.onrender.com` are on different public suffixes, so they're cross-site.
- Safari blocks cross-site cookies by default, and `SameSite=None` does **not** get around it. httpOnly cookie sessions would silently fail for every iPhone user.
- Fix options:
  - **(A, recommended):** buy a domain (around $10/yr). Run `play.example.com` on Cloudflare Pages and `api.example.com` on Render. They're same-site, so `SameSite=Lax` cookies just work, and CORS only has to allow one origin.
  - **(B):** a Cloudflare Pages Function proxies `/api/*` and `/ws` to Render, making everything same-origin. Free, but it adds a hop and one more moving part.
- Local dev uses Vite's proxy, so nothing blocks Phase 2. This needs a decision before Phase 18.

**B3. Branch naming.**
- The spec says to commit each phase on `phase-N-short-name`.
- This session is pinned to `claude/serene-galileo-iyapi2`, and I can't push other branches without your explicit OK.
- Proposal: you say "yes, phase branches", and from Phase 2 on I create `phase-2-foundations` etc. off the previous phase. Until then everything goes on the session branch.

### 1.2 Hosting cost: heads-up, not a choice

- Render's free web services spin down after inactivity, which kills in-memory Realm Rooms. Render background workers aren't on the free tier at all. Budget for paid instances for both the API and the worker.
- The worker polls `scheduled_events` around the clock, which stops Neon's scale-to-zero, so free-tier compute hours will run out. Expect a paid Neon plan once real people play.
- If money matters more than the spec's "separate worker", the worker loop can run *inside* the API process in v1 behind a flag (`RUN_WORKER_IN_PROCESS=true`). The code stays separate, so splitting later is a config change.

### 1.3 Non-blocking proposals (I'll adopt these unless you object)

| # | Spec says | Problem | Proposal |
|---|---|---|---|
| P1 | Market `price = base × clamp(exp(-k × (sold − baseline)/baseline), …)` | A fixed `baseline` is tuned for one population. With 12 players, `sold ≪ baseline` and every price sits at the 2.5× ceiling. With 5,000 players everything sits on the 0.4× floor. | `baseline = per_player_baseline × max(active_players_24h, min_population)`. All knobs stay in config. |
| P2 | Weapons have durability | A weapon that breaks mid-fight goes against "cozy" and "respect time". | At 0 durability a weapon becomes **Dull** (−30% damage, no modifiers) and never breaks. The repair coin sink still works. |
| P3 | Realm stash: anyone can withdraw | A new member can join and empty it, which contradicts "nobody can take your stuff". | The owner marks members as *trusted*. Untrusted members can withdraw up to a daily value cap. Members in their first 48h can only deposit. Everything is logged. |
| P4 | Username-only signups, plus gifts, likes and a global market | Unlimited free alts can feed gifts to a main account, farm "most-liked village" and wash coins. | New accounts can't send gifts, list on the player market, or have their likes count until they reach avatar level 5 **or** account age 24h (config). Gifts have a daily value cap. |
| P5 | No email, and "email password reset" is out of scope | A forgotten password means a lost account forever. | Show 8 one-time **recovery codes** at signup, store only their hashes, and add "reset password with a recovery code". No personal data is added. |
| P6 | Buildings rotate in 4 directions | 4 facings × 5 levels × ~25 buildings = 500 building sprites, which no CC0 pack has. | Rotation swaps the footprint for non-square buildings and **mirrors** the sprite (2 visual facings). The door marker shows the facing. |
| P7 | Visible art change per building level; distinct sprite per weapon tier; layered character creator | The same art-volume problem. | **Building levels** use one base sprite plus a level *overlay kit* (L2 flags, L3 stone base, L4 banners and roof trim, L5 gold trim and sparkle). **Weapon tiers** use one base sprite per type with **palette ramps** (copper, iron, steel, mythril, starforged) via a palette-swap shader. **Character creator** uses base bodies plus palette swaps for skin, hair and outfit, with hair styles limited to what the art provides (see ART.md). |
| P8 | "Arcane Bows (legendary tier eligible)" | Ambiguous: are other weapons capped below Legendary? | Two-building combos cap at **Epic** unless a **Boss Trophy** is added as a material. Three-building combos are always Legendary-eligible. This gives trophies and 3-combos a purpose. |
| P9 | Rain boosts farms, and resources are lazily calculated | A rate that changes with the weather breaks the "constant rate since `last_updated_at`" assumption. | Weather is a **deterministic timeline** (seeded per realm, in 20-minute blocks), so the lazy calculation integrates piecewise across blocks. It's still lazy and still exact. |
| P10 | Villagers need food; happiness includes food | Consuming food over time produces negative rates and starvation edge cases in lazy maths. | Villagers consume food *rate*, not stock. Net food rate = gross − demand, floored at 0. The happiness food factor = gross ÷ demand. There's no starvation. |
| P11 | Vertical slice = phases 2–8 | No XP/levels or sound until much later, but combat without numbers going up and without hit sounds feels dead in a playtest. | Move **XP and levels** (not the skill tree) and **core SFX** (hits, pickups, UI, placement) into Phases 5–6. |
| P12 | Six biome rings outward | Walking to the Ashen Wastes takes about 45 s every time. | Add **Waystones**: discoverable POIs, free fast travel between discovered ones (none inside dungeons). |
| P13 | A KO drops loot "so you or a friend can recover it" | If a friend picks it up, who gets it? | It gets **mailed back to the owner**, and the friend earns a small "Good Samaritan" coin reward and achievement progress. Helping only ever helps. |
| P14 | Server-authoritative combat at up to 150 ms latency | Strict authority makes dodges feel unfair under lag. | **Favour the player** (there's no PvP, so nobody loses out): lag compensation on player attacks, plus a dodge grace window on monster hits. See §2.5. |
| P15 | "Hand-gathering is the **only** way to get rare materials", but Boss Trophies and Ancient Runes come from bosses and dungeons | Contradiction. | Rare materials come **only from Avatar Mode**. Biome rares come from hand-gathered nodes, Runes from dungeons, Trophies from bosses. Monsters drop common materials, coins, blueprints and gear. |
| P16 | Weekly "seasons" plus "seasonal events" | Two things share one name, which confuses players and code. | Weekly palette rotation = **Seasons**. Calendar events (Halloween etc.) = **Festivals**. |
| P17 | Recipe Book shows undiscovered combos as "???"; the placement preview shows combos | If the client receives the full combo table, anyone can read every secret in DevTools on day one. | The public config bundle never contains undiscovered combos or secret POIs. The ghost preview asks the server (debounced) and shows discovered combos by name and undiscovered ones as a "✨ something resonates…" sparkle. |
| P18 | Waves "every few real hours" while online | "Online" needs a definition, and a logout during the countdown needs handling. | Online = a live socket heartbeat within 60 s. Logging out during the countdown **postpones** the wave. A wave can't start in your first 30 minutes after login, or during the tutorial. |
| P19 | Q is the weapon ability, and bombs and tomes (offhand) are also listed under "Ability (Q)" | One key, two abilities. | Q = main-weapon ability, **F** = offhand (bomb throw, tome spell, hold to block with a shield). Touch gets a 4th action button. Gamepad: RB = Q, LB = F. |
| P20 | Spear forged in the tutorial at TH1 | The intermediate goods it needs (planks) come from the Workshop, which is TH2. | **Copper-tier** recipes use raw resources (wood and ore). Iron+ use intermediates. |
| P21 | Rare materials needed for big upgrades? (not in the spec) | Without it, Build Mode never *needs* Avatar Mode, which weakens pillar 1. | TH4/TH5 and level-5 buildings need a handful of biome rares (4–5 Ironbark or Starstone). It's one or two trips, not a grind. |

### 1.4 Capacity reality check

- Every Realm Room shares **one** Python event loop in a single process. The spec's budget is "<10 ms per tick with 10 players and 100 monsters", but at 20 Hz the *whole process* has 50 ms per tick across **all** rooms.
- That means about 4 worst-case rooms per process, or roughly 20–40 typical ones (2–3 players, ~20 awake monsters).
- Mitigations built in from day one:
  - Monsters only spawn and simulate in chunks near players, and they sleep otherwise.
  - Far monsters run AI at 10 Hz.
  - Interest management uses a spatial hash.
  - Snapshots are encoded once per entity per tick and reused across viewers.
- The `RealmRoom` interface means rooms can move to separate processes later without touching game logic.
- The Phase 4 benchmark script measures this for real.

---

## 2. Architecture

### 2.1 Processes

```
                         ┌──────────────────────────────── Render ──────────────────────────────┐
 Browser (Cloudflare     │  api  (uvicorn, 1 process, asyncio + uvloop)                         │
 Pages, React + Pixi)    │   ├─ REST routers (JSON)                                             │
   ├─ REST (JSON) ───────┼──►├─ WS gateway /ws (msgpack)  ◄── one socket per tab               │
   └─ WS (msgpack) ◄────►│   ├─ RoomManager → RealmRoom × N (20 Hz tick tasks)                  │
                         │   ├─ VillageHub (village channel fan-out)                            │
                         │   ├─ NotifyHub (per-user notifications)                              │
                         │   ├─ in-memory rate limiter, presence heartbeats                     │
                         │   └─ PgListener (LISTEN hf_events, direct Neon conn)                │
                         │                                                                      │
                         │  worker (separate process)                                           │
                         │   ├─ polls scheduled_events (FOR UPDATE SKIP LOCKED, due_at order)  │
                         │   ├─ handlers: building/craft completion, market recalc, resets,     │
                         │   │   waves, bosses, listing expiry, cleanup                         │
                         │   └─ NOTIFY hf_events {kind, user_id|realm_id|village_id}            │
                         └──────────────────────────────────┬───────────────────────────────────┘
                                                            │ asyncpg (direct endpoint, ssl)
                                                     ┌──────▼──────┐
                                                     │ Neon Postgres│
                                                     └─────────────┘
```

- **Worker → API signalling:** Postgres `NOTIFY` on channel `hf_events`. The API holds one dedicated `LISTEN` connection on the Neon **direct** (non-pooled) endpoint, because PgBouncer transaction pooling doesn't support LISTEN. As a fallback, the API re-polls notification rows every 10 s if the listener drops.
- **Neon connection:** use the direct endpoint for everything in v1 (one API process and one worker means a small pool). If the pooled endpoint is ever used, asyncpg needs `statement_cache_size=0`.
- **No Redis.** Rate limits, presence, parties and rooms are in-memory, which is valid because v1 is a single instance. Presence is also heartbeated into a `presence` table so the worker can check "is this player online?".

### 2.2 Layering (backend)

```
api/ (routers, thin) → services/ (transactions, row locks, ledger) → domain/ (pure functions, no IO)
realtime/ (gateway, hubs) → sim/ (RealmRoom; pure-ish simulation + persistence port)
worker/handlers → services/
```

- `domain/` is pure: lazy resources, placement, combos, damage, loot rolls, pricing, mapgen. It's fed `now`, `rng` and config, which makes it trivially testable with fixed seeds and fixed clocks.
- **One ledger service** (`services/ledger.py`) is the only code that changes coins, items or resources. Every mutation runs inside a DB transaction, takes `SELECT … FOR UPDATE` row locks in a **fixed lock order** (wallet → village → containers by id), and writes a `transactions` row with a reason code.
- An **injectable Clock** is used everywhere. Tests freeze it, and admin fast-forward rewrites a player's timestamps (D-014).

### 2.3 Timers: two paths, both idempotent

Every timer (building upgrade, forge job, wave) is stored as a row with `completes_at` plus a `scheduled_events` row.

1. **Worker path:** picks due events with `FOR UPDATE SKIP LOCKED` in `due_at` order, so overdue events after an outage run oldest-first.
2. **Lazy path:** any read or write of that village or job first "settles" anything already due, under the same row lock.

The completion handler locks the target row and checks `state` before doing anything. A second run sees `state = active` and exits. This is what makes "processed twice must not double-apply" true by construction. Every scheduled event also has a `dedupe_key`, so double-scheduling is impossible as well.

### 2.4 Realm Room lifecycle

- A room is **created** when the first player of a realm enters Avatar Mode, a wave or boss needs simulating, or a friend visits.
- It is **destroyed** 2 minutes after the last avatar leaves (configurable).
- It owns avatars, monsters, projectiles, per-player drops, telegraphs, resource-node state cache, dungeon sub-instances, and wave or boss encounters.
- **Persistence** goes through a write-behind queue flushed every 1 s in a single transaction: item grants, XP, kills (for quests and stats), avatar HP and position (every 30 s and on leave).
  - A pickup that fails at flush (inventory full) restores the drop and sends a toast.
  - A crash loses at most about 1 s of pickups and **never duplicates** anything, because drops only exist in memory until granted.
- **Visiting a friend's village** (even in another realm): the visitor joins the *host's* realm room with a `visitor` flag and is confined to the host's plot. That reuses all the realm code with no special visit server.

### 2.5 Netcode (Avatar Mode)

| Piece | Choice |
|---|---|
| Tick | Fixed 50 ms (20 Hz) on the server. The client predicts at the same fixed step using **shared movement code** (Python and TS implementations checked against shared golden vectors in `/shared/golden/`). |
| Inputs | Sent every 50 ms: `seq`, `client_tick`, `view_tick` (the server tick the client is rendering others at), quantized move vector (i8,i8), aim (u16), and a button bitfield. The server keeps a per-player input queue, consumes 1 per tick (2 when the queue is longer than 3), and repeats the last movement input when the queue is empty. |
| Local avatar | Predicted. The renderer *extrapolates* within the current step using live input, so there's zero added latency. Reconciliation replays unacked inputs after each snapshot, and corrections are smoothed over about 100 ms. |
| Others | Interpolated with a 100 ms buffer. |
| Lag compensation (favour the player) | The server keeps 8 ticks of monster position history. Player hits are checked against monster positions at `view_tick`, clamped to ≤ 200 ms back. |
| Dodge grace (favour the player) | Monster hits on players are held for up to 100 ms. If a dodge input arrives with `client_tick ≤ hit_tick`, the hit is cancelled. |
| Hit feedback | Swing, flash and SFX play instantly client-side on a predicted hit. Damage numbers and kills wait for server confirmation. **Hit-stop is visual only:** it freezes render animation for 40–60 ms, never the predicted simulation. |
| Validation | Movement is simulated from the input vector, so speed hacks are impossible by construction. Also rejected: \|move\| > 1, non-monotonic `seq`, more than 25 inputs/s sustained, cooldown, stamina and range violations, and pickups out of range. Repeat offences mean disconnect plus an `admin_audit_log` entry. |
| Snapshots | Per player, per tick: own state (full float precision for reconciliation) plus entities inside the area of interest (about 2 screens), with positions quantized to 1/64 tile. Events ride along in the snapshot. Under backpressure older snapshots are dropped, and their events are merged into the next one. |
| Reconnect | 5 s grace with the avatar frozen and invulnerable. On reconnect the client gets `ROOM_JOINED` with a full snapshot. |

WebSockets run over TCP, so there's no packet loss to design around, only head-of-line stalls, which the interpolation buffer absorbs.

### 2.6 World and map

- Realm maps are **generated from `(seed, mapgen_version)`** and never stored tile by tile.
- The server generates 16×16-tile **chunks** on demand (LRU-cached per active realm). The client fetches them via `GET /api/realms/{id}/chunks?ids=…`. They're immutable, so they get ETags and long cache headers.
- Chunks are generated in Python only. JS never reproduces the generator, which avoids cross-language float determinism problems.
- Layout (all numbers in config):

```
r = 0–18     hub (market square, notice board, merchant)
r = 18–76    meadow parkland + roads
r = 76–144   plot ring: 10 plots (max 48×48) centred on r = 110
r = 144–175  meadow           (difficulty 1)
r = 175–215  Whispering Forest (2)
r = 215–255  Stonepeak         (3)
r = 255–295  Murkwater Swamp   (4)
r = 295–335  Frozen North      (5)
r = 335–375  Ashen Wastes      (6)
map: 768 × 768 tiles, 48 × 48 chunks; ring edges are domain-warped with noise so they look natural
```

- **Fog of war:** one 2,304-bit bitmap per player per realm (288 bytes), revealed per chunk.
- **Resource nodes** come from mapgen. Per-player depletion is stored as `node_harvests` rows that only exist while a node is depleted.
- **Monsters** spawn lazily from mapgen spawn points when a player comes within 2 chunks, and despawn 60 s after nobody is near.

### 2.7 Config pipeline

- `/config/*.yaml` → Pydantic models (`extra="forbid"`) → cross-reference validation → frozen `GameConfig` registry plus a content hash.
- Any validation error stops startup and prints the file, path and reason. `uv run hf config check` runs the same validation in CI.
- `GET /api/config` serves a **client bundle**: everything the client needs (stats, costs, movesets, key→index tables for the wire protocol) **minus** sections marked secret (combos, secret POIs, hidden lore). It's served with an ETag on the hash, so rebalancing never needs a frontend redeploy.
- The `item_defs` table is upserted from config at startup (never deleted, only marked `retired`) so foreign keys and admin queries work.

### 2.8 Frontend shape

- **Pixi is imperative.** One `Game` engine owns the Pixi `Application`, the world container, the camera and a mode state machine (`BuildMode` / `AvatarMode`). React renders only DOM UI (HUD, panels, menus) on top. The two talk through small **zustand** stores and an event emitter. I'm deliberately not using `@pixi/react` for the world, for performance and control.
- One world renderer serves both modes. The village is literally a plot on the realm map, so switching modes is a camera tween plus an input swap with no loading screen.
- Pixel-perfect rendering: nearest-neighbour scaling, `roundPixels`, and integer zoom levels at rest (2×, 3×, 4×). Non-integer zoom only appears mid-tween.
- REST types are generated from FastAPI's OpenAPI (`openapi-typescript`). WS message ids come from `/shared/protocol.json`, which both sides import.

---

## 3. Folder structure

```
/
├── backend/
│   ├── pyproject.toml / uv.lock
│   ├── alembic.ini
│   ├── migrations/                    # Alembic versions
│   ├── src/hearthforge/
│   │   ├── main.py                    # app factory, lifespan (config load, listener, room manager)
│   │   ├── settings.py                # pydantic-settings, reads env
│   │   ├── clock.py                   # injectable Clock
│   │   ├── db/
│   │   │   ├── engine.py, session.py, base.py
│   │   │   └── models/                # one module per domain (accounts, realm, village, items, economy, social, progression, events, admin)
│   │   ├── config/
│   │   │   ├── loader.py              # YAML → models → cross-validate → registry + hash
│   │   │   ├── schemas/               # pydantic models per config file
│   │   │   └── client_bundle.py       # strips secret sections
│   │   ├── core/                      # security (argon2, sessions), csrf, rate_limit, errors, idempotency, profanity, eventbus
│   │   ├── domain/                    # PURE logic, no IO
│   │   │   ├── resources.py           # lazy production, caps, weather integration
│   │   │   ├── placement.py           # footprints, bounds, overlap, rotation, water-adjacency
│   │   │   ├── combos.py              # orthogonal adjacency graph, 2- and 3-building combos
│   │   │   ├── forging.py             # tier, rarity roll, modifier roll, durability
│   │   │   ├── damage.py, statuses.py
│   │   │   ├── loot.py                # drop tables, per-player rolls
│   │   │   ├── pricing.py             # dynamic market price
│   │   │   ├── progression.py         # XP curve, skill effects
│   │   │   ├── happiness.py, beauty.py
│   │   │   ├── waves.py
│   │   │   ├── worldclock.py          # day/night, weather timeline, season
│   │   │   ├── mapgen/                # realm map + chunk generation
│   │   │   └── dungeongen/            # room graph generation
│   │   ├── services/                  # IO + transactions (one per domain area) incl. ledger.py
│   │   ├── api/                       # routers: auth, me, config, village, inventory, crafting, market,
│   │   │                              #   player_market, realms, social, quests, collection, leaderboards, admin
│   │   ├── realtime/
│   │   │   ├── gateway.py             # /ws endpoint, auth on upgrade, Origin check, rate limits
│   │   │   ├── protocol.py            # msgpack encode/decode, message ids from /shared/protocol.json
│   │   │   ├── hubs.py                # VillageHub, NotifyHub
│   │   │   └── pg_listener.py
│   │   ├── sim/                       # Realm Room
│   │   │   ├── room.py                # RealmRoom interface + InProcessRealmRoom
│   │   │   ├── manager.py             # create/destroy rooms, routing
│   │   │   ├── loop.py                # fixed-step tick loop, overrun logging
│   │   │   ├── world.py, chunks.py, spatial.py, interest.py
│   │   │   ├── movement.py            # MUST match frontend/src/game/sim/movement.ts (golden vectors)
│   │   │   ├── combat.py, lagcomp.py, projectiles.py, telegraphs.py
│   │   │   ├── ai/                    # chaser, kiter, charger, swarmer, tank, summoner, ambusher, boss phases
│   │   │   ├── drops.py, nodes.py, encounters.py (waves, bosses), dungeon.py, party.py
│   │   │   └── persistence.py         # write-behind queue
│   │   ├── worker/
│   │   │   ├── main.py, poller.py
│   │   │   └── handlers/              # one module per event kind
│   │   └── cli/admin.py               # typer: config check, fast-forward, grant, spawn wave/boss, reset account
│   ├── tests/
│   │   ├── unit/                      # domain/*, pure
│   │   ├── integration/               # services + real Postgres (row locks, races)
│   │   ├── sim/                       # room tick tests, input validation
│   │   └── conftest.py
│   └── scripts/
│       ├── seed.py                    # demo realm, bot villages, market history
│       ├── bench_tick.py              # 10 players + 100 monsters tick benchmark
│       └── loadtest_bots.py           # 10 WS bot clients in one realm
├── frontend/
│   ├── package.json / vite.config.ts / tsconfig.json / index.html
│   ├── src/
│   │   ├── main.tsx, App.tsx, routes/
│   │   ├── api/                       # fetch wrapper (CSRF, idempotency keys), generated OpenAPI types
│   │   ├── net/                       # ws client, codec, clock sync, prediction, reconciliation, interpolation
│   │   ├── game/
│   │   │   ├── Game.ts                # Pixi app, mode state machine, main loop
│   │   │   ├── camera/, input/ (keyboard, mouse, touch joystick, gamepad, rebinding)
│   │   │   ├── world/                 # chunk renderer, village renderer, fog, day/night tint, weather
│   │   │   ├── entities/              # avatar, monster, villager, drop, projectile views
│   │   │   ├── fx/                    # particles, hit-stop, shake, damage numbers, trails, pools
│   │   │   ├── modes/BuildMode.ts, modes/AvatarMode.ts
│   │   │   ├── sim/movement.ts        # shared-logic port (golden-vector tested)
│   │   │   └── audio/                 # Howler wrapper, music crossfade, volume persistence
│   │   ├── ui/
│   │   │   ├── theme/                 # tokens (colours, rarity colours, spacing, fonts)
│   │   │   ├── components/            # Panel, Button, Slot, Tooltip, Tabs, Modal, Bar, Sparkline…
│   │   │   ├── hud/                   # BuildHud, AvatarHud, MiniMap
│   │   │   └── screens/               # Login, CharacterCreator, Inventory, RecipeBook, Market, Realm…
│   │   ├── state/                     # zustand stores
│   │   ├── assets/
│   │   │   ├── manifest.json          # logical name → file/atlas frame (the ONLY way code references art/audio)
│   │   │   ├── atlases/, audio/, fonts/
│   │   └── debug/Gallery.tsx          # /debug sprite/anim/tile/UI/rarity/font gallery
│   ├── tests/unit/                    # vitest
│   └── tests/e2e/                     # playwright flows + screenshot runner
├── config/                            # *.yaml balance + content (see CONFIG.md)
├── shared/
│   ├── protocol.json                  # WS message ids + enum tables
│   └── golden/                        # JSON vectors run by BOTH pytest and vitest (movement, damage, pricing, combos)
├── assets-src/                        # raw source packs (unzipped, untouched) + LICENSE files
├── tools/
│   ├── pack_atlases.ts                # assets-src → atlases + manifest entries
│   ├── validate_manifest.ts           # every manifest key resolves; no orphan files
│   └── screenshots.ts                 # desktop 1440×900 + mobile 390×844 → docs/screenshots/phase-N/
├── docs/                              # PLAN, SCHEMA, PROTOCOL, CONFIG, BALANCE, ART, DECISIONS, screenshots/
├── .github/workflows/ci.yml           # ruff, mypy, pytest (Postgres service), config check, tsc, eslint, vitest
├── docker-compose.yml                 # optional local Postgres for dev/tests
├── render.yaml
├── .env.example
├── CREDITS.md
└── README.md
```

---

## 4. Phase breakdown

Sizes are rough code volume, not calendar time: **S** < 1.5k LOC, **M** 1.5–3.5k, **L** 3.5–5.5k, **XL** > 5.5k. The total is about 65–75k LOC plus config, which is a big project. The vertical slice (2–8) is roughly the first third.

Every phase ends with tests green, a screenshot pass where it applies, a `DECISIONS.md` update, a summary of what changed and what was cut, and run/test instructions.

| # | Phase | Size | Contents | Main risk |
|---|---|---|---|---|
| 1 | **Plan** | — | This doc set. | — |
| 2 | **Foundations** | M | uv/Vite scaffold, CI, Alembic baseline (accounts, realms, villages, items/containers, ledger, events), config loader and validator with the first YAML files, argon2 auth, sessions, CSRF, rate limits, profanity filter, recovery codes, signup creating the solo realm, village, avatar, wallet and containers. Character creator UI, themed UI kit (Panel/Button/etc.), `/debug` gallery skeleton, asset pipeline and manifest. | Getting the UI kit right early, because everything reuses it. |
| 3 | **Build Mode core** | L | Pixi world renderer and camera (pan, zoom, inertia), chunk endpoint and mapgen v0 (hub, plots, meadow), placement/rotate/move/demolish/undo with ghost preview, the core and production buildings, lazy resources with caps, build queue (2/3 slots), the worker process and upgrade timers (both paths), village WS channel, building pop-in juice, live counters. | Placement UX on touch. |
| 4 | **Avatar Mode core** | XL | Mode-switch camera tween, `/ws` gateway, RealmRoom plus the 20 Hz loop, input/prediction/reconciliation/interpolation, golden-vector movement parity, tile and building collision, meadow and forest bands, hand-gathering (chop, mine, pick) with per-player nodes, inventory grid basics, deposit to storehouse/bank, the tick benchmark script. | **Netcode feel.** This is the riskiest phase, so I'll test it at 150 ms of simulated latency before calling it done. |
| 5 | **Combat core** | L | Sword and spear movesets, dodge plus i-frames, stamina, 3 enemy types (slime, wolf, spider) plus elites with telegraphs and AI, damage formula and statuses, lag comp and dodge grace, per-player loot, KO and death-drop rules, **XP and levels** (P11), and the juice pass: hit-stop, flash, knockback, numbers, shake, afterimages, rarity beams, **core SFX** (P11). | Combat readability at 16 px. |
| 6 | **Combos & forging** | M | Adjacency graph, 2- and 3-building combos, the discovery moment, the recipe book with hints, the server preview with mystery sparkle (P17), intermediate goods (planks, ingots, bricks), forge jobs with hammering animation, tier/rarity/modifiers, durability with Dull (P2), repair and salvage. | Making discovery feel magical, not menu-y. |
| 7 | **Economy core** | M | Market building UI, dynamic pricing with the worker recalc and population-scaled baseline (P1), sparklines and trend arrows, per-player soft caps, idempotency keys, ledger race tests, the wandering merchant (seeded rotation), inventory and bank expansion, a coin-supply metric. | Faucet/sink balance. |
| 8 | **🎮 Vertical slice checkpoint** | M | Guide character, a skippable tutorial under 5 minutes (place camp and quarry → chop → slimes → sell → Forge + Lumber Camp → spear), "While you were away" summary, Playwright e2e of the full flow. **Stop for your playtest** and suggest tuning. | Whether it's fun. That's what this phase finds out. |
| 9 | **Realms & co-op** | L | Create/join/leave/kick/transfer with village relocation, invite codes, full mapgen ring with 10 plots, fog of war, mini-map and full map, seeing mates live, parties, realm stash with trust rules (P3), activity feed, waystones (P12). | Join/leave edge cases mid-session. |
| 10 | **World expansion** | XL | All 6 biomes, remaining enemy types and elites, POIs (ruins, shrines, lore stones, caves, merchants, lost villagers), night spawns, day/night lighting, weather timeline plus effects (P9), seasons palette, ambient audio per biome. | Content volume and art coverage. |
| 11 | **Full weapon roster** | L | All 13 combos, every remaining moveset (hammer/mace, bow, staff, enchanted sword, harpoon, bombs, tomes), shields, leather and plate armour, potions, buff food, quick-slots. | Ten movesets to make feel distinct. |
| 12 | **Dungeons** | XL | Room-graph generator, combat/treasure/puzzle rooms (plates, levers), mini-boss and boss, party instances inside the room, Ancient Runes and blueprints, daily seeded dungeon plus leaderboard. | Procgen quality. |
| 13 | **Defence & bosses** | L | Wave scheduler with the online rules (P18), guards and towers AI, steal cap and funny reports, 5 multi-phase realm bosses with HP scaling and per-damager loot. | Boss design time. |
| 14 | **Villagers & beauty** | L | Villager generation, jobs, drag-to-assign, pathing between home and work, speech bubbles, arrivals, happiness (P10), beauty score, decoration catalogue, villager reactions to the avatar. | Pathfinding performance with 20+ villagers. |
| 15 | **Social** | M | Friends, blocks, visiting (P4 gates), likes, gifts via mailbox, neighbour help, emotes, quick messages, map pings. | Abuse edge cases. |
| 16 | **Progression** | XL | Skill tree and respec, daily and weekly quests, main questline, achievements and titles, collection book, trophy hall, pets, mounts, fishing minigame, photo mode, login calendar. | Breadth. |
| 17 | **Global layer** | L | Player market (escrow, fees, expiry, history), global leaderboards, world boss weekends (shared HP), festival framework. | Market race conditions. |
| 18 | **Polish & launch** | L | Full juice and UI consistency pass, audio pass, touch and gamepad and rebinding, performance budgets, admin panel, load test, README, `render.yaml`, Pages config, domain setup (B2), `CREDITS.md` audit. | Mobile performance. |

**Deferred inside v1:** delta-compressed snapshots (full AOI snapshots are about 16 KB/s per player, which is fine), multi-process rooms, public realms (the schema already supports them via `realms.visibility`).

---

## 5. Testing approach (from Phase 2 on)

- **Pure domain tests** (fast, no DB): lazy maths (with Hypothesis property tests: never exceeds cap, never negative, piecewise equals one-shot), placement, combos (including overlapping and 3-building ones), damage, loot (seeded), pricing, XP, mapgen determinism.
- **Integration tests** against real Postgres (a CI service container; locally docker-compose or a Neon dev branch): ledger correctness, **concurrent spend races** (N parallel requests on one wallet, exactly one wins), idempotency keys, timer idempotency (run the handler twice), realm join/leave/kick relocation, wave rules.
- **Sim tests:** drive a RealmRoom with scripted inputs. Covers speed hacks, cooldown spam, out-of-range hits, lag-comp window, dodge grace.
- **Golden vectors** in `/shared/golden/`, run by both pytest and vitest: movement steps, damage, pricing, combo detection. This is how the Python and TS ports of shared logic can't drift.
- **Playwright:** e2e flows plus the screenshot runner (desktop 1440×900 and mobile 390×844).
- **Benchmarks:** `bench_tick.py` (budget < 10 ms per room at 10 players and 100 monsters) and `loadtest_bots.py`.

---

## 6. Top risks

1. **Netcode feel in Python at 20 Hz.** Mitigation: Phase 4 is dedicated to it, with a latency-injection dev toggle and golden vectors.
2. **Art coverage.** Even with Ninja Adventure, 6 biomes, 13 weapon types, 25 buildings and 5 bosses will need palette swaps, overlays and some hand-edited sprites. Mitigation: the manifest indirection, the overlay kit, palette ramps, and the `/debug` gallery checks.
3. **Scope.** 18 phases is a lot. The vertical slice checkpoint in Phase 8 is the moment to cut or reshape what comes after.
4. **Single-process capacity** (§1.4). Mitigation: sleeping monsters, the interface boundary, benchmarks.
5. **Economy inflation.** Mitigation: P1, a faucet/sink dashboard from Phase 7, every coin change in the ledger.
