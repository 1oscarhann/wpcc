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
| `0x20` | ENTER_AVATAR | `target:u8 (0 own realm, 1 visit)`, `host_id?:uuid` | Ask to join a Realm Room. Refused during a mode-switch cooldown or when blocked. |
| `0x21` | LEAVE_AVATAR | — | Refused while "in combat" (took or dealt damage in the last 5 s). |
| `0x22` | **INPUT** | `seq:u32, client_tick:u32, view_tick:u32, mx:i8, my:i8, aim:u16, buttons:u16` | 20 Hz. `mx,my ∈ [-127,127]`, and the server rejects magnitudes above 127. |
| `0x23` | ACTION | `kind:u8, a?:any, b?:any` | Discrete actions; see the kinds table below. |
| `0x24` | FISH_REEL | `bite_id:u32, client_tick:u32` | Fishing timing check. The server validates against the bite window with latency tolerance. |
| `0x30` | PARTY | `kind:u8 (invite, accept, decline, leave, kick), user_id?` | Realm-scoped and in-memory. |
| `0x31` | DUNGEON | `kind:u8 (enter, ready, leave), entrance_id?:u32` | |

**`buttons` bitfield (u16):**

| Bit | Button |
|---|---|
| 0 | light (pressed edge) |
| 1 | heavy held |
| 2 | heavy released (charge release) |
| 3 | dodge |
| 4 | ability |
| 5 | interact |
| 6–9 | quick-slot 1–4 |
| 10 | block (shield) |
| 11–15 | reserved |

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

### 3.1 SNAPSHOT

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
- Spend, sell, buy, list and gift requests also need an `Idempotency-Key: <uuid>` header. A replay returns the stored response.
- Errors: `{ "error": { "code": "insufficient_resources", "message_key": "err.insufficient", "details": {...} } }`.
- Mutating responses include a `sync` block: `{wallet, resources:{key:[amount, rate, cap]}, at_ms, village_version}`. The client re-bases its interpolated counters on every response.

| Area | Routes | Phase |
|---|---|---|
| Auth | `POST /api/auth/signup` (username, password, appearance → returns recovery codes once) · `POST /api/auth/login` · `POST /api/auth/logout` · `POST /api/auth/recover` (username, recovery code, new password) · `GET /api/me` | 2 |
| Config | `GET /api/config` (client bundle, ETag) | 2 |
| Avatar | `GET /api/avatar` · `PUT /api/avatar/appearance` · `POST /api/avatar/skills` · `POST /api/avatar/respec` | 2, 16 |
| Village | `GET /api/village/{owner_id\|me}` · `GET /api/village/preview?b=&x=&y=&rot=` (valid, combos, mystery count) · `POST /api/village/buildings` · `PATCH /api/village/buildings/{id}` (move/rotate) · `DELETE /api/village/buildings/{id}` · `POST /api/village/buildings/{id}/upgrade` · `POST /api/village/buildings/{id}/cancel` · `POST /api/village/undo` · `POST /api/village/decorations` · `PATCH`/`DELETE /api/village/decorations/{id}` · `PUT /api/village/tiles` · `POST /api/village/expand` · `POST /api/village/villagers/{id}/assign` | 3, 14 |
| Map | `GET /api/realms/{id}/chunks?ids=…` (immutable, cacheable) · `GET /api/realms/{id}/fog` | 3, 9 |
| Inventory | `GET /api/inventory` (inventory, bank, equipment, mailbox) · `POST /api/inventory/move` · `POST /api/inventory/split` · `POST /api/inventory/sort` · `POST /api/inventory/equip` · `POST /api/inventory/deposit` (to storehouse/bank) · `POST /api/inventory/expand` · `POST /api/inventory/repair` · `POST /api/inventory/salvage` · `POST /api/mailbox/claim` | 4, 6, 7 |
| Crafting | `GET /api/crafting/book` (discovered combos and recipes + hints for undiscovered) · `GET /api/crafting/stations` (active combos, available recipes) · `POST /api/crafting/jobs` · `POST /api/crafting/jobs/{id}/collect` · `POST /api/crafting/jobs/{id}/cancel` | 6 |
| Market | `GET /api/market` (prices, sparklines, trends, my soft-cap usage) · `POST /api/market/sell` · `GET /api/merchant/{merchant_id}` · `POST /api/merchant/{merchant_id}/buy` | 7 |
| Player market | `GET /api/pmarket?item=&sort=` · `POST /api/pmarket/listings` · `POST /api/pmarket/listings/{id}/buy` · `POST /api/pmarket/listings/{id}/cancel` · `GET /api/pmarket/history/{item}` | 17 |
| Realms | `GET /api/realm` · `POST /api/realms` (create) · `POST /api/realms/join` · `POST /api/realm/leave` · `POST /api/realm/kick` · `PATCH /api/realm` (rename/banner) · `POST /api/realm/invite-code` (regenerate) · `POST /api/realm/transfer` · `POST /api/realm/trust` · `GET /api/realm/activity` · `GET /api/realm/stash` · `POST /api/realm/stash/deposit` · `POST /api/realm/stash/withdraw` | 9 |
| Social | `GET /api/friends` · `POST /api/friends/request` · `POST /api/friends/{id}/accept` · `POST /api/friends/{id}/decline` · `DELETE /api/friends/{id}` · `POST /api/blocks` · `DELETE /api/blocks/{id}` · `POST /api/social/{id}/like` · `POST /api/social/{id}/gift` · `POST /api/social/{id}/help` | 15 |
| Progression | `GET /api/quests` · `POST /api/quests/{id}/claim` · `GET /api/achievements` · `POST /api/achievements/{key}/claim` · `GET /api/collection` · `GET /api/cosmetics` · `POST /api/cosmetics/equip` · `POST /api/login-reward/claim` · `GET /api/pets` · `GET /api/mounts` | 16 |
| Misc | `GET /api/notifications?after=` (polling fallback) · `POST /api/notifications/read` · `GET /api/away-summary` · `POST /api/reports` | 8 |
| Leaderboards | `GET /api/leaderboards/{board}?period=` · `GET /api/dungeons/daily` | 12, 17 |
| Admin (role=admin) | `GET /api/admin/players` · `GET /api/admin/realms` · `GET /api/admin/economy` (coin supply, faucets vs sinks by reason) · `GET /api/admin/ledger?user=` · `GET /api/admin/market` · `POST /api/admin/fast-forward` · `POST /api/admin/grant` · `POST /api/admin/events/{kind}` (spawn wave/boss/world boss) · `POST /api/admin/reset-account` · `GET /api/admin/reports` | 7, 18 |
| WebSocket | `GET /ws` | 3, 4 |
