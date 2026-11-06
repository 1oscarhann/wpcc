# Wire protocol

There are two transports:

- **REST (JSON)** for everything turn-based.
- **One WebSocket per tab (msgpack, binary)** for realtime: Realm Room, village channel, notifications.

Message ids and enum tables live in `/shared/protocol.json`, which both the backend and frontend import, so ids can't drift between them.

---

## 1. WebSocket transport

### 1.1 Connection

- `GET /ws`, upgraded to a WebSocket. Auth uses the session cookie (same-site, see PLAN B2). The server **checks the `Origin` header** against the allowed frontend origin to block cross-site WebSocket hijacking.
- Every frame is a **binary msgpack array**: `[op, ...fields]`. `op` is a uint8. Using arrays instead of maps keeps frames small.
- Strings never appear in hot messages. Config keys (monster types, items, FX) go over the wire as **u16 indices** into key tables that the client gets from `GET /api/config` (`bundle.keytables`). The config hash is checked in `WELCOME`, and if it doesn't match the client reloads the bundle.
- Units:
  - **Positions:** others are sent as u16 in 1/64-tile units (enough for maps up to 1,023 tiles). Your own avatar is sent as float32, for exact reconciliation.
  - **Angles:** u16 (0–65535 = 0–2π) for aim, u8 for facing.
  - **HP:** others as a u8 percentage, your own as an exact int.

### 1.2 Rate limits (per connection, in-memory token buckets; numbers in `config/game.yaml`)

| Class | Limit | On breach |
|---|---|---|
| `INPUT` | 25/s sustained, burst 40 | Excess is dropped. If it stays over 40/s for 3 s: kick plus an audit log entry. |
| Actions (emote, ping, use, interact…) | 10/s, burst 20 | Dropped, with a `ERROR rate_limited`. |
| Everything else | 30/s | Dropped. |
| Malformed or impossible frames | — | 3 strikes and you're kicked, plus an audit log entry. |

### 1.3 Backpressure

- Each client has an outbound queue.
- If more than 4 snapshots are queued, older **snapshots** are dropped (each one is full-state, so dropping is safe). Their `events` are merged into the next snapshot that does get sent.
- Non-snapshot messages are never dropped.
- If the queue stays over 256 KB for 5 s, the client is disconnected and reconnects with a fresh state.

---

## 2. Client → Server

| op | Name | Fields | Notes |
|---|---|---|---|
| `0x01` | HELLO | `proto_ver:u16, build:str, resume:bool` | First frame. The server answers `WELCOME` or `KICK(version)`. |
| `0x02` | PING | `client_ms:f64` | Every 2 s. Used for clock sync and RTT. |
| `0x10` | SUB_VILLAGE | `owner_id:str` (UUID text, D-037) | Watch a village (yours; visiting arrives in Phase 15). The server replies with `VILLAGE_STATE`. |
| `0x11` | UNSUB_VILLAGE | `owner_id` | |
| `0x20` | ENTER_AVATAR | — (v1: always your own realm; visiting adds `target, host_id` in Phase 15) | Join your realm's room. Within the 5 s reconnect grace you get your old avatar back. |
| `0x21` | LEAVE_AVATAR | — | Refused while "in combat" (took or dealt damage in the last 5 s). |
| `0x22` | **INPUT** | `seq:u32, client_tick:u32, view_tick:u32, mx:i8, my:i8, ax:i8, ay:i8, buttons:u16` | 20 Hz. Every value in `[-127,127]` (D-044: aim is a vector). Bad arity, ranges, replayed `seq` or more than the token bucket allows (25/s sustained, 25 burst) are strikes; 25 strikes = kick. INPUT doesn't count toward the generic 30 msgs/s limit. |
| `0x23` | ACTION | `kind:u8, a?:any, b?:any` | Discrete actions; see the kinds table below. |
| `0x24` | FISH_REEL | `bite_id:u32, client_tick:u32` | Fishing timing check. The server validates against the bite window with latency tolerance. |
| `0x30` | PARTY | `kind:u8 (invite, accept, decline, leave, kick), user_id?` | Realm-scoped and in-memory. |
| `0x34` | DUNGEON | `["leave"] · ["use", prop] · ["portal"]` | **Phase 12.** Enter through `INTERACT`. See §3.0. |
| `0x33` | USE_QUICK | `slot:u8 (0–3)` | **Phase 11.** Drink or eat what's in quick-slot 1–4 (equipment slots 4–7). |
| `0x32` | INTERACT | `poi_index:u32` | **Phase 10.** Use the point of interest you're standing at (≤ 2.4 tiles). The answer is a POI event, or a TOAST (`poi_too_far`, `chest_empty`, `shrine_resting`, `villager_home`). |

**`buttons` bitfield (u16):**

As built in Phase 4/5 (the numbers live in `shared/world.json → buttons`):

| Bit | Button |
|---|---|
| 0 (1) | light attack / gather (held = keep swinging) |
| 1 (2) | heavy attack (costs stamina) |
| 2 (4) | ability (spin / throw) |
| 3 (8) | dodge |
| 4 (16) | quick-slot potion |
| 5–15 | reserved (interact, more quick-slots, block arrive with their features) |

Buttons are latched on the client until the next 50 ms step, so taps shorter than a step are never lost.

**ACTION kinds:**

| Kind | Action | Args |
|---|---|---|
| 1 | EMOTE | `emote_id:u8` (wave, cheer, laugh, dance, point) |
| 2 | QUICK_MSG | `msg_id:u8` ("Help!", "Over here!", "Boss spotted!", "GG", "Thanks!") |
| 3 | MAP_PING | `x:u16, y:u16, party_only:bool` |
| 4 | PICKUP | `drop_id:u32` (manual pickup; auto-pickup is also handled server-side by range) |
| 5 | USE_WAYSTONE | `waystone_id:u32` |
| 6 | READ_LORE | `poi_id:u32` |
| 7 | OPEN_CHEST | `poi_id:u32` |
| 8 | LIKE_VILLAGE | (visiting only) |

---

## 3. Server → Client

| op | Name | Fields |
|---|---|---|
| `0x81` | WELCOME | `user_id, server_ms:f64, tick_rate:u8, proto_ver:u16, config_hash:str, resume_ok:bool` |
| `0x82` | PONG | `client_ms:f64, server_ms:f64, server_tick:u32` |
| `0x83` | ERROR | `code:u16, key:str, ctx?:map` (`key` is an i18n key, e.g. `err.in_combat`) |
| `0x84` | KICK | `reason:u8 (version, cheat, replaced, server_shutdown, banned)` |
| `0x90` | VILLAGE_STATE | `owner_id, version:u32, village:map` (full state, same shape as `GET /api/village`; pushed on every change, D-036) |
| `0x91` | VILLAGE_PATCH | `owner_id, version:u32, ops:[[op_kind, ...]]` |
| `0xA0` | ROOM_JOINED | `room_kind:u8 (realm, dungeon), realm_id, tick:u32, you:u32 (entity id), map:{seed, ver, chunk_url}, clock:{day_phase, weather, season}, party:[…], nodes_depleted:[u32], snapshot` |
| `0xA1` | **SNAPSHOT** | see §3.1 |
| `0xA2` | ROOM_LEFT | `reason:u8 (left, idle, moved_realm, kicked, ko_returned)` |
| `0xA3` | PARTY_STATE | `members:[[user_id, name, hp_pct, x, y, online]]` |
| `0xA4` | WORLD_CLOCK | `day_phase:u8, weather:u8, season:u8, next_change_ms:u32` |
| `0xB0` | NOTIFY | `id:u64, kind:str, payload:map` (also stored in `notifications` for the polling fallback) |
| `0xB1` | REALM_FEED | `id:u64, kind:str, actor:str, payload:map` |
| `0xB2` | TIMER | `kind:u8 (wave_countdown, boss_spawn, festival), ends_ms:f64, payload` |
| `0xC0` | RESYNC | `what:u8 bitmask (wallet, inventory, village, quests, mailbox)`: tells the client to re-fetch via REST |

### 3.0 Avatar Mode frames as built (Phase 4/5)

```
ROOM_JOINED [0xA0, realm_id, tick, you:eid, self, info:map, blocks:[[x,y,w,h]], claimed:[plot], depleted:[[node_id, ms_left]], roster:[[eid, user_id, name, appearance, weapon_type, level]]]
SNAPSHOT    [0xA1, tick, ack_seq, self, ents, ev]
ROOM_LEFT   [0xA2, reason]        # 0 left, 4 replaced (another tab), 5 shutdown
BLOCKS      [0xA5, blocks, claimed]   # a village changed: new solid rects
self = [x, y, st, st_max, fx, fy, st_delay, dodge, ddx, ddy, dodge_cd, atk, atk_i, atk_t, ax, ay, combo, combo_t, ab_cd, kbx, kby, hp, hp_max, flags]
       # the first 21 values are the shared Motion state, so the client can replay unacked inputs exactly
ents = [[id, kind, type, x*64, y*64, dx*100, dy*100, anim, anim_t, hp(0-255), flags]]
       # every entity in the area of interest (±28×18 tiles), every tick; absent = gone
```

- `kind` / `anim` / event ids come from `shared/protocol.json` (`entity_kinds`, `anims`, `events`).
- `type` is the enemy key for monsters, the item key for drops (`flags` = quantity), `"spear"` for projectiles and the weapon type for avatars.
- Events used so far: HIT `[1, src, dst, dmg, crit, kind]` (kind 0 normal, 1 poison, 2 dodged, 3 heavy), TELEGRAPH `[2, mid, shape(0 circle, 1 line), x, y, dx, dy, range, width, warn_ms]`, PICKUP `[5, drop, item, qty, all]`, KO `[6, eid, lost]`, XP `[7, amount, level, xp, xp_next, levels_gained, hp_max]`, SFX `[10, name, x, y]`, NODE `[13, node, hits, total, depleted, respawn_ms, sound]`, TOAST `[17, key, args]`, DEPOSIT `[19, {item: qty}]`, DEATH `[20, mid, x, y, enemy, elite]`, SWING `[21, eid, atk, combo_i, ax*100, ay*100]`, HEAL `[22, eid, amount, quick]`, RESPAWN `[23, x, y]`, INVENTORY `[24, stacks]`, PLAYER `[25, …roster entry]`, PLAYER_LEFT `[26, eid]`, PROJECTILE_END `[27, id, x, y]`.
- The table below is the long-term target; the delta-compressed `new/upd/gone` form is deferred (full AOI lists are ~600 B per tick).
- **Phase 10 (protocol v4).**
  - **New op.** C2S `INTERACT [poi_index]` (`0x32`).
  - **New events.** ZAP `[32, x0, y0, x1, y1]` (chain lightning) and POI `[33, index, kind, data]` (what using a POI did: chest loot, blessing, lore text, trader id, rescued villager).
  - **Flags.** New self flag `rooted` (16). Monster entity flags gain 16 (spawned at night) and 32 (summoned minion).
  - **Monster shots.** They are `projectile` entities whose `type` is the sprite (`arrow`, `spit`, `sting`, `ice`, `fire`, `bolt`, `rock`), with `flags` = 1.
  - **DEATH.** The flag 2 means "faded" (dawn, storm passed, summoner died): no loot, no poof.
  - **TELEPORT.** Index -1 means a dev hop.
- **Phase 11 (protocol v5).**
  - **New op.** C2S `USE_QUICK [slot 0–3]` (`0x33`).
  - **New input bit.** `offhand` (32): hold for the shield, tap for bombs and tome.
  - **New events.**
    - IMPACT `[34, x, y, r, kind]`: slam, quake, burst, whirl, boom or star.
    - MOVE_MODS `[35, speed, dodge, regen]`: rebuild your movement rules, D-079.
    - OFFHAND `[36, type, charges, ready_ms]`.
    - BARRIER `[37, id, x0, y0, x1, y1, ms]`.
    - BUFF `[38, item, kind, value, ms, quick]`.
    - LOADOUT `[39, weapon, offhand, defence]`.
  - **STATUS.** `[3, mid, burn|slow|poison]` now covers monsters.
  - **HIT.** kind 4 means a shield block.
  - **Projectiles.** Player projectiles carry their sprite as `type` (`arrow`, `crystal`, `orb`, `wave`, `arcane`, `tome_<element>`, `spear`). Bombs are projectiles with `flags` = 2.
- **Phase 12 (protocol v6).**
  - **New op.** C2S `DUNGEON` (`0x34`) is one of three messages:
    - `["leave"]` leaves the delve. It's refused mid-fight unless the boss is down.
    - `["use", prop_index]` pulls a lever or opens a chest within reach.
    - `["portal"]` goes home through the portal. You must stand at it.
  - **Entering.** You enter through `INTERACT` on a cave or the Delve Gate.
  - **New events.**
    - DUNGEON_ENTER `[40, info]`. `info` holds `{id, name, kind, biome, difficulty, origin, layout, state, started_ms}`.
      - `layout` holds `{w, h, tiles (bytes: 0 void, 1 floor, 2 wall, 3 door), rooms, doors, props, start}`.
      - Each room is `[id, kind, x, y, w, h, depth, puzzle]`.
      - Each door is `[id, tiles, rooms, gate]`.
      - Each prop is `[kind, x, y, room, data]`.
      - `state` holds `{locked, visited, cleared, plates, lamps, solved, portal, clear_ms}`.
    - DUNGEON_LEFT `[41]`.
    - DUNGEON `[42, op, …]`. Each op carries:
      - `doors`: the locked door ids.
      - `visit`, `cleared`, `solved`: a room id.
      - `plates`: the lit plate indices.
      - `lamps`: the lamp mask and the lever that was pulled.
      - `boss`: the entity id and name.
      - `phase`: the phase number.
      - `enrage`: the entity id.
      - `portal`: `clear_ms`.
      - `chest`: the prop index. It goes only to the player who opened it.
  - **Flags.** Monster entity flag 64 marks a boss.
  - **TOAST.** New keys: `delve_enter {name}`, `delve_ko`, `delve_full`, `delve_already_in`, `delve_in_combat`.

### 3.1 SNAPSHOT (target format)

```
[0xA1,
  tick:u32,
  ack_seq:u32,                          # last INPUT seq applied → client drops older inputs and replays the rest
  self:[x:f32, y:f32, vx:f32, vy:f32, facing:u8, anim:u8, anim_t:u8,
        hp:i32, hp_max:i32, stamina:f32, stamina_max:f32,
        cd:[ability_ms:u16, dodge_ms:u16, quick1..4_ms:u16],
        statuses:[[status_id:u8, remaining_ms:u16, stacks:u8]],
        flags:u16],                     # in_combat, invulnerable, ko, mounted, in_water…
  new:[[id:u32, kind:u8, type:u16, extra:map?]],   # entities entering the area of interest (static info)
  upd:[[id:u32, x:u16, y:u16, facing:u8, anim:u8, anim_t:u8, hp_pct:u8, flags:u16]],
  gone:[id:u32],
  ev:[[ev_kind:u8, ...]]
]
```

- **Entity `kind`:** 0 avatar, 1 monster, 2 projectile, 3 drop (sent **only** to its owner), 4 npc (villager, guard, merchant), 5 interactable (chest, lever, plate, waystone), 6 telegraph shape, 7 pet, 8 death-drop marker.
- **`flags` (u16):** hurt-flash, elite, night-variant, burning, frozen, poisoned, slowed, stunned, telegraphing, invulnerable, ko, party-member, rarity (3 bits, for drops).
- **`upd` only contains entities whose quantized state changed.** An entity that's present but not in `upd` hasn't changed.

**Event kinds (`ev`):**

Protocol **v3** (Phase 9) adds C2S `PARTY [action, arg]` (invite eid / accept party id / leave) and `TRAVEL [waystone]`, events `WAYSTONE 28 [index, name, attuned]`, `TELEPORT 29 [x, y, index]`, `PARTY 30 [state|null]`, `PARTY_INVITE 31 [party, from]`, `ROOM_LEFT moved (6)`, and `NOTIFY ["realm", {}]`. `SUB_VILLAGE` accepts realm-mates.

| ev | Name | Fields |
|---|---|---|
| 1 | HIT | `src:u32, dst:u32, dmg:u32, crit:bool, kb_angle:u8, element:u8` |
| 2 | TELEGRAPH | `id:u32, shape:u8 (circle, cone, line, ring), x:u16, y:u16, a:u16, size:u16, warn_ms:u16` |
| 3 | STATUS | `dst:u32, status_id:u8, on:bool` |
| 4 | DROP | `id:u32, item:u16, qty:u16, rarity:u8, x:u16, y:u16` (personal) |
| 5 | PICKUP | `id:u32, item:u16, qty:u16`: the arc-to-HUD juice fires on this |
| 6 | KO | `who:u32` |
| 7 | XP | `amount:u32, level_up:bool` |
| 8 | DISCOVERY | `kind:u8, key:u16` (biome, poi, lore, monster, rare_material…) |
| 9 | FX | `fx:u16, x:u16, y:u16, a:u16` (server-cued effects like a boss slam or chest burst) |
| 10 | SFX | `sfx:u16, x:u16, y:u16` |
| 11 | EMOTE / QUICK_MSG | `who:u32, kind:u8, id:u8` |
| 12 | MAP_PING | `who:u32, x:u16, y:u16` |
| 13 | NODE | `node_id:u32, depleted:bool` (personal) |
| 14 | BOSS | `id:u32, phase:u8, hp_pct:u8, name_key:u16` |
| 15 | WAVE | `state:u8, remaining:u16, wave_no:u8` |
| 16 | FISH_BITE | `bite_id:u32, window_start_tick:u32, window_ticks:u8` |
| 17 | TOAST | `key:u16, args:map` (inventory full, etc.) |
| 18 | CORRECTION | `reason:u8`: debug only, sent when the server snapped you because of an invalid move |

### 3.2 VILLAGE_PATCH op kinds

| op_kind | Name | Fields |
|---|---|---|
| 1 | B_PLACE | `building:map` |
| 2 | B_MOVE | `id, x, y, rot` |
| 3 | B_REMOVE | `id` |
| 4 | B_WORK | `id, state, completes_at_ms` (upgrade/construct started or cancelled) |
| 5 | B_DONE | `id, level` (pop-in juice for everyone watching) |
| 6 | D_PLACE | `deco:map` |
| 7 | D_MOVE | `id, x, y, rot` |
| 8 | D_REMOVE | `id` |
| 9 | TILES | `layer, rle_chunk` |
| 10 | RES | `{key: [amount, rate_per_h, cap]}` + `at_ms` (resource resync) |
| 11 | COMBOS | `active:[combo_id]`, `new_discovery?:combo_key` |
| 12 | VILLAGER | `villager:map` (arrive, assign, mood) |
| 13 | STATS | `beauty, happiness, likes` |

If `version` isn't `last_version + 1`, the client discards local state and refetches `GET /api/village/{owner}`.

---

## 4. Client-side netcode algorithm

```
every 50 ms (fixed step):
  input = sample()                                  # quantized exactly as sent
  seq += 1; send INPUT(seq, client_tick, view_tick, input)
  pending.push(seq, input)
  local = movement.step(local, input, collision)    # shared logic (golden-vector tested)

on SNAPSHOT:
  drop pending inputs with seq ≤ ack_seq
  server_self = snapshot.self
  replay = server_self; for each pending: replay = movement.step(replay, input)
  error = replay.pos − local.pos
  if |error| > 2 tiles: snap; else: local = replay, visual_offset += −error (decays over ~100 ms)
  push other entities into the interpolation buffer, keyed by server tick

render (every frame):
  local_draw = local.pos + local.vel × alpha + visual_offset      # alpha = time since last step / 50 ms (extrapolate)
  others_draw = interpolate(buffer, server_time_estimate − 100 ms)
  view_tick  = tick being displayed for others (sent with the next INPUT)
```

The clock offset is estimated from `PING`/`PONG` with an RTT-filtered median of the last 8 samples.

---

## 5. REST route map

**Conventions:**

- JSON bodies validated with Pydantic (`extra="forbid"`).
- Every mutating request needs an `X-CSRF-Token` header (a double-submit token, bound to the session).
- Spend, sell, buy, list and gift requests also need an `Idempotency-Key: <uuid>` header. A replay returns the stored response. **As built (Phase 7, D-056):** required on `POST /api/village/buildings`, `…/upgrade`, `POST /api/crafting/jobs`, `POST /api/inventory/repair`, `POST /api/inventory/expand`, `POST /api/market/sell` and `POST /api/merchant/{id}/buy`. Missing → 400 `idempotency_key_required`; same key with another body → 422 `idempotency_mismatch`. The web client sends one on every mutation and retries a network failure once with the same key.
- Errors: `{ "error": { "code": "insufficient_resources", "message_key": "err.insufficient", "details": {...} } }`.
- Mutating responses include a `sync` block: `{wallet, resources:{key:[amount, rate, cap]}, at_ms, village_version}`. The client re-bases its interpolated counters on every response.

| Area | Routes | Phase |
|---|---|---|
| Auth | `POST /api/auth/signup` (username, password, appearance → returns recovery codes once) · `POST /api/auth/login` · `POST /api/auth/logout` · `POST /api/auth/recover` (username, recovery code, new password) · `GET /api/me` | 2 |
| Config | `GET /api/config` (client bundle, ETag) | 2 |
| Avatar | `GET /api/avatar` · `PUT /api/avatar/appearance` · `POST /api/avatar/skills` · `POST /api/avatar/respec` | 2, 16 |
| Village | `GET /api/village/{owner_id\|me}` (Phase 6 adds `combos` (active), `discovered` (combo keys) and `jobs`) · `GET /api/village/preview?key=&x=&y=&rotation=&move_id=` (valid, `combos` it would form *if already discovered*, `mystery` = how many undiscovered ones, P17) · `POST /api/village/buildings` · `PATCH /api/village/buildings/{id}` (move/rotate) · `DELETE /api/village/buildings/{id}` · `POST /api/village/buildings/{id}/upgrade` · `POST /api/village/buildings/{id}/cancel` · `POST /api/village/undo` · `POST /api/village/decorations` · `PATCH`/`DELETE /api/village/decorations/{id}` · `PUT /api/village/tiles` · `POST /api/village/expand` · `POST /api/village/villagers/{id}/assign` | 3, 14 |
| Map | `GET /api/realms/{id}/chunks?ids=…` (immutable, cacheable) · `GET /api/realms/{id}/fog` | 3, 9 |
| Inventory | **Built in Phase 4:** `GET /api/inventory` (inventory + equipment) and `POST /api/inventory/move {src:{kind,slot}, dst:{kind,slot}}` (move, merge, swap, equip). Planned: `POST /api/inventory/split` · `POST /api/inventory/sort` · `POST /api/inventory/equip` · `POST /api/inventory/deposit` (to storehouse/bank) · `POST /api/inventory/expand {kind: inventory|bank}` (built in Phase 7; `GET /api/inventory` now also returns `bank` and each container's `expand: {step, next_cost, max}`; bank moves are refused while you're in Avatar Mode) · `POST /api/inventory/repair` · `POST /api/inventory/salvage` · `POST /api/mailbox/claim` | 4, 6, 7 |
| Crafting | **Built in Phase 6:** `GET /api/crafting/book` (discovered combos in full; undiscovered ones only as `{discovered: false, size, hint}`) · `GET /api/crafting/stations/{building_id}` (what this station makes now, with exact bills, tiers and rarity odds per number of rares) · `POST /api/crafting/jobs {station_id, recipe, quantity, rares}` · `POST /api/crafting/jobs/{id}/collect` (gear → `item`) · `POST /api/crafting/jobs/{id}/cancel` (75% back, rares returned) · `POST /api/inventory/repair {kind, slot}` · `POST /api/inventory/salvage {slot}` | 6 |
| Market | **Built in Phase 7:** `GET /api/market` → `{has_market, market_level, bonus, population, next_recalc_ms, max_sell, items:[{key, source: storage\|bag, have, price (with your bonus), over_price, trend −1/0/1, change, spark[24], units_24h, baseline, sold_today, soft_cap}]}` · `POST /api/market/sell {item, quantity}` → `{village, sale:{coins, unit_price, over_cap_units, sold_today, balance}, inventory?}` · `GET /api/merchant/hub` (or `hub:<realm id>`) → `{name, greeting, rotation, ends_at_ms, pos:[x,y], radius, near, slots:[{slot, kind: item\|resource\|hint, name, price, list_price, deal, limit, bought, sold_out}]}` · `POST /api/merchant/hub/buy {slot, rotation}` (you must stand at the cart in Avatar Mode; a stale `rotation` → 409 `merchant_moved_on`) | 7 |
| Player market | `GET /api/pmarket?item=&sort=` · `POST /api/pmarket/listings` · `POST /api/pmarket/listings/{id}/buy` · `POST /api/pmarket/listings/{id}/cancel` · `GET /api/pmarket/history/{item}` | 17 |
| Realms | **Built in Phase 9:** `GET /api/realm` (members, roles, trust, online) · `POST /api/realms {name}` (open your solo realm) · `POST /api/realms/join {code}` · `POST /api/realm/leave` · `POST /api/realm/kick {user_id}` · `POST /api/realm/transfer {user_id}` · `POST /api/realm/trust {user_id, trusted}` · `PATCH /api/realm {name}` · `POST /api/realm/invite-code` · `GET /api/realm/activity?before=` · `GET /api/realm/stash` · `POST /api/realm/stash/deposit|withdraw {slot, quantity}` · `GET /api/realm/villages` (mates) · `GET /api/realm/overview` (chunk bytes, fog, waystones). Phase 8: `GET /api/tutorial` · `POST /api/tutorial/check {confirm?}` · `POST /api/tutorial/skip` · `GET /api/away-summary` · `POST /api/away-summary/ack`. Originally planned: `GET /api/realm` · `POST /api/realms` (create) · `POST /api/realms/join` · `POST /api/realm/leave` · `POST /api/realm/kick` · `PATCH /api/realm` (rename/banner) · `POST /api/realm/invite-code` (regenerate) · `POST /api/realm/transfer` · `POST /api/realm/trust` · `GET /api/realm/activity` · `GET /api/realm/stash` · `POST /api/realm/stash/deposit` · `POST /api/realm/stash/withdraw` | 9 |
| Social | `GET /api/friends` · `POST /api/friends/request` · `POST /api/friends/{id}/accept` · `POST /api/friends/{id}/decline` · `DELETE /api/friends/{id}` · `POST /api/blocks` · `DELETE /api/blocks/{id}` · `POST /api/social/{id}/like` · `POST /api/social/{id}/gift` · `POST /api/social/{id}/help` | 15 |
| Progression | `GET /api/quests` · `POST /api/quests/{id}/claim` · `GET /api/achievements` · `POST /api/achievements/{key}/claim` · `GET /api/collection` · `GET /api/cosmetics` · `POST /api/cosmetics/equip` · `POST /api/login-reward/claim` · `GET /api/pets` · `GET /api/mounts` | 16 |
| Misc | `GET /api/notifications?after=` (polling fallback) · `POST /api/notifications/read` · `GET /api/away-summary` · `POST /api/reports` | 8 |
| Leaderboards | `GET /api/leaderboards/{board}?period=` · `GET /api/dungeons/daily` | 12, 17 |
| Admin (role=admin) | `GET /api/admin/players` · `GET /api/admin/realms` · `GET /api/admin/economy` (coin supply, faucets vs sinks by reason; **built in Phase 7**: `{coin_supply, wallets, mean_coins, series:[{at_ms, supply, faucet, sink, active}], day/week:{faucets, sinks, net}}`) · `GET /api/admin/ledger?user=` · `GET /api/admin/market` · `POST /api/admin/fast-forward` · `POST /api/admin/grant` · `POST /api/admin/events/{kind}` (spawn wave/boss/world boss) · `POST /api/admin/reset-account` · `GET /api/admin/reports` | 7, 18 |
| WebSocket | `GET /ws` | 3, 4 |
