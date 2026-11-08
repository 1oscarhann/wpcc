# Database schema (v1)

Postgres 16+ (Neon). Written as Postgres DDL so Phase 2 can turn it straight into SQLAlchemy 2.0 models and an Alembic baseline. Tables arrive in the phase that needs them (each table notes its phase), but the shape is fixed now.

## Conventions

- **Primary keys.** `uuid` (v7, generated in app, time-ordered) for entities that are exposed or move around. `bigint generated always as identity` for high-volume logs.
- **Time.** Every timestamp is `timestamptz` in UTC. `created_at default now()`.
- **Resources.** Amounts are stored as **bigint milli-units** (`1 wood = 1000`) so lazy maths never drifts. The API exposes plain numbers.
- **Config keys.** `building_key`, `item_key` and so on are `text` keys that reference `/config`. `item_key` has a real foreign key to `item_defs`, which is synced from config at startup.
- **Optimistic concurrency.** `version int` columns are used where the client needs to detect stale state.
- **Locking.** Every write path that spends something locks rows in this fixed order: `wallets` → `villages` → `containers` (ascending id) → `item_instances`. This prevents deadlocks.
- **Append-only.** `transactions` and `admin_audit_log` have a trigger that rejects `UPDATE` and `DELETE`.
- **Extensions.** `citext` (case-insensitive usernames) and `pgcrypto` (only for `gen_random_bytes` in migrations if needed).

## Enums

```sql
CREATE TYPE user_role        AS ENUM ('player','admin');
CREATE TYPE realm_role       AS ENUM ('owner','member');
CREATE TYPE realm_visibility AS ENUM ('private','public');          -- public unused in v1
CREATE TYPE building_state   AS ENUM ('active','constructing','upgrading');
CREATE TYPE rarity           AS ENUM ('common','uncommon','rare','epic','legendary');
CREATE TYPE container_kind   AS ENUM ('inventory','bank','equipment','realm_stash','mailbox');
CREATE TYPE item_origin      AS ENUM ('starter','gathered','drop','forged','crafted','merchant','reward','gift','market','admin');
CREATE TYPE ledger_asset     AS ENUM ('coin','item','resource');
CREATE TYPE event_status     AS ENUM ('pending','processing','done','failed','cancelled');
CREATE TYPE job_status       AS ENUM ('running','ready','collected','cancelled');
CREATE TYPE listing_status   AS ENUM ('active','sold','expired','cancelled');
CREATE TYPE friend_status    AS ENUM ('pending','accepted');
CREATE TYPE quest_period     AS ENUM ('tutorial','main','daily','weekly','festival');
CREATE TYPE quest_status     AS ENUM ('active','completed','claimed');
CREATE TYPE discovery_kind   AS ENUM ('combo','recipe','poi','lore','biome','monster','fish','rare_material',
                                      'blueprint','weapon','waystone','secret','boss');
CREATE TYPE wave_status      AS ENUM ('scheduled','announced','active','won','lost','postponed','cancelled');
CREATE TYPE boss_status      AS ENUM ('scheduled','active','defeated','expired');
CREATE TYPE avatar_location  AS ENUM ('village','wild','dungeon','visiting');
```

---

## 1. Accounts (Phase 2)

```sql
CREATE TABLE users (
  id               uuid PRIMARY KEY,
  username         citext NOT NULL UNIQUE,            -- 3–20 chars, [A-Za-z0-9_], profanity-filtered
  password_hash    text   NOT NULL,                   -- argon2id
  role             user_role NOT NULL DEFAULT 'player',
  created_at       timestamptz NOT NULL DEFAULT now(),
  last_seen_at     timestamptz,
  banned_at        timestamptz,
  tutorial_step    smallint NOT NULL DEFAULT 0,       -- -1 = skipped/complete
  is_test_account  boolean NOT NULL DEFAULT false     -- admin fast-forward allowed only on these
);

CREATE TABLE user_settings (
  user_id     uuid PRIMARY KEY REFERENCES users ON DELETE CASCADE,
  audio       jsonb NOT NULL DEFAULT '{"master":0.8,"music":0.6,"sfx":0.8,"muted":false}',
  keybinds    jsonb NOT NULL DEFAULT '{}',            -- overrides only
  graphics    jsonb NOT NULL DEFAULT '{}',            -- particles level, screen shake on/off, reduced motion
  ui          jsonb NOT NULL DEFAULT '{}',
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  token_hash   bytea PRIMARY KEY,                     -- sha256 of the random cookie token
  user_id      uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  csrf_secret  bytea NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  last_used_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON sessions (user_id);
CREATE INDEX ON sessions (expires_at);

CREATE TABLE recovery_codes (                         -- P5
  user_id    uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  code_hash  text NOT NULL,                           -- argon2id
  used_at    timestamptz,
  PRIMARY KEY (user_id, code_hash)
);

CREATE TABLE presence (                               -- heartbeated by api every 30s per live socket
  user_id         uuid PRIMARY KEY REFERENCES users ON DELETE CASCADE,
  heartbeat_at    timestamptz NOT NULL,
  online_since    timestamptz NOT NULL,
  in_avatar_mode  boolean NOT NULL DEFAULT false,
  realm_id        uuid
);
```

## 2. Avatars (Phases 2, 4, 5, 16)

```sql
CREATE TABLE avatars (
  user_id              uuid PRIMARY KEY REFERENCES users ON DELETE CASCADE,
  appearance           jsonb NOT NULL,                -- {body, skin, hair_style, hair_color, eyes, outfit, outfit_color}
  level                smallint NOT NULL DEFAULT 1,
  xp                   integer  NOT NULL DEFAULT 0,   -- xp into current level
  hp                   integer  NOT NULL,
  skill_points         smallint NOT NULL DEFAULT 0,   -- unspent
  last_free_respec_at  timestamptz,
  title_key            text,
  active_pet_id        uuid,
  active_mount_id      uuid,
  location             avatar_location NOT NULL DEFAULT 'village',
  realm_id             uuid,                          -- realm the position refers to
  pos_x                real NOT NULL DEFAULT 0,       -- tiles
  pos_y                real NOT NULL DEFAULT 0,
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE avatar_skills (
  user_id    uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  skill_key  text NOT NULL,
  rank       smallint NOT NULL CHECK (rank > 0),
  PRIMARY KEY (user_id, skill_key)
);

CREATE TABLE user_stats (                             -- generic counters feeding quests, achievements, leaderboards
  user_id   uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  stat_key  text NOT NULL,                            -- e.g. 'kill.wolf', 'forge.legendary', 'sell.wood', 'fish.caught'
  value     bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, stat_key)
);
```

## 3. Realms (Phases 2, 9)

```sql
CREATE TABLE realms (
  id              uuid PRIMARY KEY,
  name            text NOT NULL,
  banner          jsonb NOT NULL,                     -- {pattern, primary, secondary, emblem}
  owner_user_id   uuid NOT NULL REFERENCES users,
  is_solo         boolean NOT NULL DEFAULT true,
  visibility      realm_visibility NOT NULL DEFAULT 'private',
  invite_code     char(6) UNIQUE,                     -- NULL for solo realms; [A-HJ-NP-Z2-9] (no 0/O/1/I)
  seed            bigint NOT NULL,
  mapgen_version  smallint NOT NULL,
  weather_seed    bigint NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  archived_at     timestamptz                         -- solo realm archived when its player joins another realm
);

CREATE TABLE realm_members (
  realm_id        uuid NOT NULL REFERENCES realms ON DELETE CASCADE,
  user_id         uuid NOT NULL UNIQUE REFERENCES users ON DELETE CASCADE,  -- exactly one realm per player
  role            realm_role NOT NULL DEFAULT 'member',
  plot_index      smallint NOT NULL CHECK (plot_index BETWEEN 0 AND 9),
  stash_trusted   boolean NOT NULL DEFAULT false,     -- P3
  joined_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (realm_id, user_id),
  UNIQUE (realm_id, plot_index)
);
-- invariant (service-enforced + deferred constraint trigger): exactly one 'owner' per realm, ≤ 10 members

CREATE TABLE realm_activity (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  realm_id       uuid NOT NULL REFERENCES realms ON DELETE CASCADE,
  actor_user_id  uuid REFERENCES users,
  kind           text NOT NULL,                       -- 'forged_legendary','discovered_biome','boss_defeated','member_joined',…
  payload        jsonb NOT NULL DEFAULT '{}',
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON realm_activity (realm_id, created_at DESC);

CREATE TABLE fog_reveals (
  user_id     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  realm_id    uuid NOT NULL REFERENCES realms ON DELETE CASCADE,
  bits        bytea NOT NULL,                         -- 1 bit per 16×16 chunk (48×48 = 2304 bits = 288 bytes)
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, realm_id)
);

CREATE TABLE node_harvests (                          -- per-player depleted resource nodes; row exists only while depleted
  user_id     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  realm_id    uuid NOT NULL REFERENCES realms ON DELETE CASCADE,
  node_id     integer NOT NULL,                       -- stable id from mapgen
  respawn_at  timestamptz NOT NULL,
  PRIMARY KEY (user_id, realm_id, node_id)
);
CREATE INDEX ON node_harvests (respawn_at);

CREATE TABLE realm_poi_state (                        -- shared POI state (e.g. dungeon entrance cooldowns, boss lair)
  realm_id    uuid NOT NULL REFERENCES realms ON DELETE CASCADE,
  poi_id      integer NOT NULL,
  state       jsonb NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (realm_id, poi_id)
);

CREATE TABLE death_drops (                            -- KO loot, recoverable for 5 min (P13)
  id             uuid PRIMARY KEY,
  realm_id       uuid NOT NULL REFERENCES realms ON DELETE CASCADE,
  user_id        uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  x              real NOT NULL,
  y              real NOT NULL,
  items          jsonb NOT NULL,                      -- [{item_key, qty}] (rare materials only)
  expires_at     timestamptz NOT NULL,
  recovered_by   uuid REFERENCES users,
  recovered_at   timestamptz
);
CREATE INDEX ON death_drops (realm_id) WHERE recovered_at IS NULL;
```

Realm stash = a `containers` row with `kind='realm_stash'`, `realm_id` set. Its log = `transactions WHERE container_id = stash`.

**As built (Phases 8–9, migration 0006):** `user_stats` exactly as §2; `users.away_snapshot jsonb` (the "While you were away" baseline); `realm_activity` and `fog_reveals` as above (activity's `created_at` comes from the app clock); `discovery_kind` gains `waystone`; existing realms move to mapgen v3 in place.

## 4. Villages (Phases 2, 3, 14)

```sql
CREATE TABLE villages (
  id              uuid PRIMARY KEY,
  user_id         uuid NOT NULL UNIQUE REFERENCES users ON DELETE CASCADE,
  realm_id        uuid NOT NULL REFERENCES realms,    -- follows realm_members on join/leave
  name            text NOT NULL,
  size            smallint NOT NULL DEFAULT 24 CHECK (size BETWEEN 24 AND 48),   -- square plot side, tiles
  version         integer NOT NULL DEFAULT 0,         -- bumped on every layout change; WS patches carry it
  beauty          integer NOT NULL DEFAULT 0,         -- cached, recomputed on layout change
  happiness       smallint NOT NULL DEFAULT 50,       -- cached
  likes_count     integer NOT NULL DEFAULT 0,
  last_action     jsonb,                              -- single-level undo record {op, payload, at}
  rates_dirty     boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE village_buildings (
  id                 uuid PRIMARY KEY,
  village_id         uuid NOT NULL REFERENCES villages ON DELETE CASCADE,
  building_key       text NOT NULL,
  x                  smallint NOT NULL,               -- top-left tile, plot-local
  y                  smallint NOT NULL,
  rotation           smallint NOT NULL DEFAULT 0 CHECK (rotation BETWEEN 0 AND 3),
  level              smallint NOT NULL DEFAULT 0,     -- 0 while first construction runs
  state              building_state NOT NULL,
  work_started_at    timestamptz,
  work_completes_at  timestamptz,
  work_paid          jsonb,                           -- exact cost paid, for cancel refunds
  helped_seconds     integer NOT NULL DEFAULT 0,      -- neighbour help applied to the current timer
  skin_key           text,
  created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON village_buildings (village_id);
CREATE INDEX ON village_buildings (work_completes_at) WHERE state <> 'active';
-- overlap/bounds/limits validated in domain/placement.py under a villages row lock

CREATE TABLE village_decorations (
  id          uuid PRIMARY KEY,
  village_id  uuid NOT NULL REFERENCES villages ON DELETE CASCADE,
  deco_key    text NOT NULL,
  x           smallint NOT NULL,
  y           smallint NOT NULL,
  rotation    smallint NOT NULL DEFAULT 0,
  variant     smallint NOT NULL DEFAULT 0
);
CREATE INDEX ON village_decorations (village_id);

CREATE TABLE village_tiles (                          -- paths & nature tiles painted by the player
  village_id  uuid PRIMARY KEY REFERENCES villages ON DELETE CASCADE,
  paths       bytea NOT NULL,                         -- RLE, 1 byte per tile = path style id (0 = none)
  nature      bytea NOT NULL                          -- RLE, grass/flowers/water style ids
);

CREATE TABLE resources (                              -- lazy production; see BALANCE.md §3
  village_id        uuid NOT NULL REFERENCES villages ON DELETE CASCADE,
  resource_key      text NOT NULL,                    -- wood, stone, ore, food, herbs, fish, hide, crystal + intermediates
  amount_milli      bigint NOT NULL CHECK (amount_milli >= 0),
  base_rate_milli   bigint NOT NULL DEFAULT 0,        -- per hour, before weather (weather integrated piecewise)
  weather_class     text,                             -- 'farm' | 'herb' | NULL: which weather multipliers apply
  cap_milli         bigint NOT NULL,
  last_updated_at   timestamptz NOT NULL,
  PRIMARY KEY (village_id, resource_key)
);

CREATE TABLE villagers (
  id                 uuid PRIMARY KEY,
  village_id         uuid NOT NULL REFERENCES villages ON DELETE CASCADE,
  name               text NOT NULL,
  appearance         jsonb NOT NULL,
  traits             jsonb NOT NULL DEFAULT '[]',     -- e.g. ['loves_flowers','night_owl']
  job_building_id    uuid REFERENCES village_buildings ON DELETE SET NULL,
  home_building_id   uuid REFERENCES village_buildings ON DELETE SET NULL,
  is_guard           boolean NOT NULL DEFAULT false,
  happiness          smallint NOT NULL DEFAULT 50,
  arrived_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON villagers (village_id);
```

**As built (Phase 14, migration `0009`).**
- **Columns.** `villagers` has no `traits` default beyond `[]`, no `is_guard` (a guard is a villager whose job is a Guard Post) and no per-villager `happiness` (happiness belongs to the village).
- **New columns on `villages`.** `villagers_at` (arrivals are settled up to here) and `unhappy_since` (the leaving clock).
- **Not built.** `village_decorations` and `village_tiles` weren't: decorations and paths are `village_buildings` rows (D-103).

## 5. Items, containers and crafting (Phases 2, 4, 6)

All items live in exactly one place: a container slot, an active market listing, or a craft job's output. Inventory, bank, equipment, realm stash and mailbox are all **containers**, so a single move/transfer code path covers everything.

```sql
CREATE TABLE item_defs (                              -- mirror of config, upserted on startup, never deleted
  key          text PRIMARY KEY,
  category     text NOT NULL,                         -- material, rare_material, intermediate, weapon, offhand, armour, trinket, consumable, blueprint, cosmetic, trophy, fish
  stackable    boolean NOT NULL,
  max_stack    integer NOT NULL,
  config_hash  text NOT NULL,
  retired      boolean NOT NULL DEFAULT false
);

CREATE TABLE item_instances (                         -- unique gear
  id              uuid PRIMARY KEY,
  item_key        text NOT NULL REFERENCES item_defs,
  tier            smallint NOT NULL CHECK (tier BETWEEN 1 AND 5),
  rarity          rarity NOT NULL,
  modifiers       jsonb NOT NULL DEFAULT '[]',        -- [{key:'fire', value:0.12}]
  durability      integer NOT NULL,
  max_durability  integer NOT NULL,
  origin          item_origin NOT NULL,
  crafted_by      uuid REFERENCES users,
  roll_seed       bigint NOT NULL,                    -- reproducible roll
  skin_key        text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE containers (
  id             uuid PRIMARY KEY,
  kind           container_kind NOT NULL,
  owner_user_id  uuid REFERENCES users ON DELETE CASCADE,
  realm_id       uuid REFERENCES realms ON DELETE CASCADE,
  capacity       smallint NOT NULL,
  CHECK ((kind = 'realm_stash') = (realm_id IS NOT NULL)),
  UNIQUE (owner_user_id, kind)                        -- one inventory/bank/equipment/mailbox per player
);

CREATE TABLE container_slots (
  container_id  uuid NOT NULL REFERENCES containers ON DELETE CASCADE,
  slot          smallint NOT NULL,
  item_key      text NOT NULL REFERENCES item_defs,
  quantity      integer NOT NULL CHECK (quantity > 0),
  instance_id   uuid UNIQUE REFERENCES item_instances,   -- an instance can only be in one slot
  PRIMARY KEY (container_id, slot),
  CHECK (instance_id IS NULL OR quantity = 1)
);
-- equipment slot map: 0 main, 1 offhand, 2 armour, 3 trinket, 4–7 quick-slots (consumable stacks)

CREATE TABLE craft_jobs (                             -- forging + intermediate goods
  id                   uuid PRIMARY KEY,
  user_id              uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  station_building_id  uuid NOT NULL REFERENCES village_buildings ON DELETE CASCADE,
  recipe_key           text NOT NULL,
  combo_key            text,                          -- combo active when the job started (forging)
  tier                 smallint,
  quantity             smallint NOT NULL DEFAULT 1,
  inputs               jsonb NOT NULL,                -- exact consumed costs (for cancel refund)
  rare_inputs          jsonb NOT NULL DEFAULT '[]',   -- rare materials added → modifiers / luck
  luck                 real NOT NULL DEFAULT 0,       -- snapshot of crafting luck at start
  roll_seed            bigint NOT NULL,
  started_at           timestamptz NOT NULL,
  completes_at         timestamptz NOT NULL,
  status               job_status NOT NULL DEFAULT 'running',
  result_instance_id   uuid REFERENCES item_instances,
  collected_at         timestamptz
);
CREATE INDEX ON craft_jobs (user_id, status);
```

## 6. Economy (Phases 2, 7, 17)

```sql
CREATE TABLE wallets (
  user_id     uuid PRIMARY KEY REFERENCES users ON DELETE CASCADE,
  coins       bigint NOT NULL DEFAULT 0 CHECK (coins >= 0),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE transactions (                           -- append-only ledger (trigger blocks UPDATE/DELETE)
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id          uuid REFERENCES users,             -- NULL for system-owned containers
  realm_id         uuid,
  asset            ledger_asset NOT NULL,
  item_key         text,                              -- for item/resource
  instance_id      uuid,
  container_id     uuid,
  delta            bigint NOT NULL,                   -- coins, item qty, or resource milli-units
  balance_after    bigint,                            -- coins & stackable totals when cheap to know; NULL for lazy resources
  reason           text NOT NULL,                     -- reason code, enumerated in services/ledger.py (e.g. 'market.sell','build.cost','craft.input','loot.pickup','ko.drop','stash.withdraw','listing.fee','admin.grant')
  ref_type         text,                              -- 'building','craft_job','listing','trade','quest',…
  ref_id           text,
  idempotency_key  uuid,
  actor            text NOT NULL DEFAULT 'user',      -- user | system | admin
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON transactions (user_id, created_at DESC);
CREATE INDEX ON transactions (container_id, created_at DESC) WHERE container_id IS NOT NULL;
CREATE INDEX ON transactions (reason, created_at);
CREATE INDEX ON transactions (ref_type, ref_id);
-- NOT logged: continuous lazy production accrual (reconstructible from rates). Logged: every spend, sell, grant, move between owners.

CREATE TABLE idempotency_keys (
  user_id       uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  key           uuid NOT NULL,
  endpoint      text NOT NULL,
  request_hash  bytea NOT NULL,                       -- same key + different body → 422
  status_code   smallint,
  response      jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, key)
);                                                    -- worker prunes rows > 24h

CREATE TABLE market_prices (                          -- current NPC market price per item
  item_key         text PRIMARY KEY REFERENCES item_defs,
  price            numeric(12,3) NOT NULL,
  units_sold_24h   bigint NOT NULL DEFAULT 0,
  baseline_used    numeric(14,3) NOT NULL,
  updated_at       timestamptz NOT NULL
);

CREATE TABLE market_price_history (
  item_key   text NOT NULL REFERENCES item_defs,
  at         timestamptz NOT NULL,                    -- one row per recalc (every 10 min); pruned > 30 days
  price      numeric(12,3) NOT NULL,
  units_24h  bigint NOT NULL,
  PRIMARY KEY (item_key, at)
);

CREATE TABLE market_sales_buckets (                   -- rolling 24h = sum of last 144 ten-minute buckets
  item_key      text NOT NULL REFERENCES item_defs,
  bucket_start  timestamptz NOT NULL,
  units         bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (item_key, bucket_start)
);

CREATE TABLE market_player_daily (                    -- per-player soft cap tracking
  user_id   uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  item_key  text NOT NULL,
  day       date NOT NULL,
  units     bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, item_key, day)
);

CREATE TABLE merchant_purchases (                     -- stock itself is derived from seed + time + config
  user_id      uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  merchant_id  text NOT NULL,                         -- 'hub:<realm_id>' | 'wild:<realm_id>:<poi_id>'
  rotation     integer NOT NULL,                      -- rotation index (time bucket)
  slot         smallint NOT NULL,
  quantity     integer NOT NULL,
  PRIMARY KEY (user_id, merchant_id, rotation, slot)
);

CREATE TABLE economy_samples (                        -- Phase 7: one row per market recalc (D-060)
  at           timestamptz PRIMARY KEY,
  coin_supply  bigint  NOT NULL,                      -- sum of all wallets
  players      integer NOT NULL,
  active_24h   integer NOT NULL,
  faucet       bigint  NOT NULL,                      -- coins created since the previous sample
  sink         bigint  NOT NULL,                      -- coins destroyed since the previous sample
  last_tx_id   bigint  NOT NULL                       -- flow is counted by ledger id, never by timestamps
);
CREATE INDEX ON transactions (created_at) WHERE asset = 'coin';   -- the economy view's 24 h / 7 d sums
-- discovery_kind gains 'hint' (a combo whose buildings a merchant Recipe Hint revealed)

CREATE TABLE player_market_listings (                 -- Phase 17
  id              uuid PRIMARY KEY,
  seller_user_id  uuid NOT NULL REFERENCES users,
  item_key        text NOT NULL REFERENCES item_defs,
  instance_id     uuid UNIQUE REFERENCES item_instances,
  quantity        integer NOT NULL CHECK (quantity > 0),   -- remaining
  quantity_listed integer NOT NULL,
  unit_price      bigint NOT NULL CHECK (unit_price > 0),
  fee_paid        bigint NOT NULL,
  status          listing_status NOT NULL DEFAULT 'active',
  created_at      timestamptz NOT NULL DEFAULT now(),
  expires_at      timestamptz NOT NULL,
  closed_at       timestamptz
);
CREATE INDEX ON player_market_listings (item_key, unit_price) WHERE status = 'active';
CREATE INDEX ON player_market_listings (seller_user_id, status);
CREATE INDEX ON player_market_listings (expires_at) WHERE status = 'active';

CREATE TABLE player_market_trades (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  listing_id   uuid NOT NULL REFERENCES player_market_listings,
  buyer_id     uuid NOT NULL REFERENCES users,
  item_key     text NOT NULL,
  quantity     integer NOT NULL,
  unit_price   bigint NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON player_market_trades (item_key, created_at DESC);
```

## 7. Discovery, progression and cosmetics (Phases 6, 9, 16)

```sql
CREATE TABLE discoveries (                            -- permanent, per player; drives recipe book + collection book
  user_id   uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  kind      discovery_kind NOT NULL,
  key       text NOT NULL,                            -- e.g. combo 'forge+lumber_camp', weapon 'spear:steel:epic'
  count     integer NOT NULL DEFAULT 1,
  first_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, kind, key)
);
-- As built, by kind:
--   waystone: key = waystone index (Phase 9)
--   poi:      key = 'x,y' of the POI, data = {at: epoch s of the last use}, count = uses
--             (Phase 10: chests and lost villagers once, shrines every 20 h)
--   lore:     key = '<biome>:<entry>' the first time you read a lore stone (Phase 10)
-- Phase 10 needed no new tables; migration 0007 only moves realms to mapgen v4.

CREATE TABLE quest_progress (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  quest_key     text NOT NULL,
  period        quest_period NOT NULL,
  period_start  date NOT NULL,                        -- day/week start (UTC); epoch for main/tutorial
  progress      integer NOT NULL DEFAULT 0,
  target        integer NOT NULL,
  status        quest_status NOT NULL DEFAULT 'active',
  completed_at  timestamptz,
  claimed_at    timestamptz,
  UNIQUE (user_id, quest_key, period_start)
);
CREATE INDEX ON quest_progress (user_id, status);

CREATE TABLE user_achievements (
  user_id          uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  achievement_key  text NOT NULL,
  unlocked_at      timestamptz NOT NULL DEFAULT now(),
  claimed_at       timestamptz,
  PRIMARY KEY (user_id, achievement_key)
);                                                    -- progress is read from user_stats

CREATE TABLE user_cosmetics (                         -- outfits, dyes, banners, building skins, titles, weapon skins
  user_id       uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  cosmetic_key  text NOT NULL,
  source        text NOT NULL,                        -- 'achievement:x','merchant','festival:x','login_day:n'
  acquired_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, cosmetic_key)
);

CREATE TABLE login_rewards (
  user_id          uuid PRIMARY KEY REFERENCES users ON DELETE CASCADE,
  calendar_day     smallint NOT NULL DEFAULT 0,       -- position in the calendar (not a streak that resets)
  last_claim_date  date
);

CREATE TABLE pets (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  pet_key     text NOT NULL,
  name        text NOT NULL,
  level       smallint NOT NULL DEFAULT 1,
  xp          integer NOT NULL DEFAULT 0,
  acquired_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mounts (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  mount_key   text NOT NULL,
  name        text NOT NULL,
  acquired_at timestamptz NOT NULL DEFAULT now()
);
```

### As built (migration 0010, Phases 15/16a)

- `avatars` gains `skills jsonb` (node → rank), `respecs smallint` and `title text`.
- `quest_progress` is keyed `(user_id, quest_key, period_start)` with `period`, `stat`, `base` (the counter when handed out, D-110), `target` and `claimed_at`. `period_start` is the ISO date of the day or week, or `'main'`. No status enum: done is `value − base ≥ target`.
- `user_achievements` and `user_cosmetics` are as above; titles are cosmetics keyed `title:<name>`.
- `login_rewards` is `(user_id, calendar_day, last_claim_day, extra)`.
- `pets` and `mounts` wait for Phase 16b.

## 8. Social (Phase 15)

```sql
CREATE TABLE friendships (                            -- one row per pair, user_low < user_high
  user_low      uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  user_high     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  status        friend_status NOT NULL,
  requested_by  uuid NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  accepted_at   timestamptz,
  PRIMARY KEY (user_low, user_high),
  CHECK (user_low < user_high)
);

CREATE TABLE blocks (
  blocker_id  uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  blocked_id  uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (blocker_id, blocked_id)
);

CREATE TABLE gifts (                                  -- items travel via the recipient's mailbox container
  id          uuid PRIMARY KEY,
  from_user   uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  to_user     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  day         date NOT NULL,
  contents    jsonb NOT NULL,                         -- snapshot for the notification/away summary
  value       integer NOT NULL,                       -- market-value estimate, for the daily cap (P4)
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (from_user, to_user, day)
);

CREATE TABLE village_likes (
  liker_id     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  owner_id     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  counted      boolean NOT NULL,                      -- false if liker was below the P4 gate
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (liker_id, owner_id)
);

CREATE TABLE village_visits (
  visitor_id  uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  owner_id    uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  day         date NOT NULL,
  PRIMARY KEY (visitor_id, owner_id, day)
);

CREATE TABLE neighbour_helps (
  helper_id       uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  target_id       uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  day             date NOT NULL,
  target_kind     text NOT NULL,                      -- 'building' | 'craft_job'
  target_ref      uuid NOT NULL,
  seconds_saved   integer NOT NULL,
  PRIMARY KEY (helper_id, target_id, day)
);
```

Parties are **in memory** inside the RoomManager (realm-scoped). After a restart, players re-form them. See D-025.

### As built (migration 0010, Phase 15)

- `friendships`, `blocks` and `village_visits` are as above.
- `mail` replaces the mailbox container (D-106): `id, user_id, sender_id, sender_name, kind (gift|boss|system), items jsonb, coins, note, created_at, claimed_at`.
- `gifts` is `(from_user, to_user, day)` with `items` and `value`; the per-gift and daily caps read it.
- `village_likes` keeps `counted`; `villages.likes_count` is the denormalised total.
- `neighbour_helps` is keyed `(helper_id, building_id, day)` with `owner_id` and `seconds`; `village_buildings.helped_seconds` enforces the 50% cap.

## 9. World events (Phases 12, 13, 17)

```sql
CREATE TABLE monster_waves (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  status        wave_status NOT NULL,
  difficulty    smallint NOT NULL,                    -- from TH level at announce time
  announced_at  timestamptz,
  starts_at     timestamptz,
  ended_at      timestamptz,
  result        jsonb                                 -- {stolen:{food:120}, rewards:{coins:250}, helpers:[…], report_line:'…'}
);
CREATE INDEX ON monster_waves (user_id, status);

CREATE TABLE realm_bosses (
  id           uuid PRIMARY KEY,
  realm_id     uuid NOT NULL REFERENCES realms ON DELETE CASCADE,
  boss_key     text NOT NULL,
  lair_x       real NOT NULL,
  lair_y       real NOT NULL,
  status       boss_status NOT NULL,
  spawns_at    timestamptz NOT NULL,
  expires_at   timestamptz NOT NULL,
  hp_fraction  real NOT NULL DEFAULT 1.0,             -- persisted every 10s while fighting
  defeated_at  timestamptz
);

CREATE TABLE boss_damage (                            -- who gets loot (realm bosses + world bosses)
  boss_ref   text NOT NULL,                           -- 'realm:<id>' | 'world:<event_id>'
  user_id    uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  realm_id   uuid NOT NULL,
  damage     bigint NOT NULL DEFAULT 0,
  looted_at  timestamptz,
  PRIMARY KEY (boss_ref, user_id)
);

-- As built (Phase 13, migration 0009): text statuses instead of enums, and the boss's HP as a fraction.
--   monster_waves(id, user_id, realm_id, status text: announced|running|done|postponed, town_hall,
--                 announced_at, starts_at, ended_at, result jsonb (the report), created_at)
--   realm_bosses (id, realm_id, boss_key, lair_x, lair_y, status text: waiting|defeated|expired,
--                 spawns_at, expires_at, hp_fraction, defeated_at)
--   boss_damage  (boss_id → realm_bosses, user_id, damage, looted)   -- realm bosses only for now

CREATE TABLE world_boss_events (
  id            uuid PRIMARY KEY,
  boss_key      text NOT NULL,
  starts_at     timestamptz NOT NULL,
  ends_at       timestamptz NOT NULL,
  hp_max        bigint NOT NULL,
  hp_remaining  bigint NOT NULL,                      -- global pool; api flushes in-memory aggregate every 5s
  status        boss_status NOT NULL
);

CREATE TABLE dungeon_runs (
  id           uuid PRIMARY KEY,
  realm_id     uuid NOT NULL REFERENCES realms ON DELETE CASCADE,
  biome_key    text NOT NULL,
  seed         bigint NOT NULL,
  is_daily     boolean NOT NULL DEFAULT false,
  party        uuid[] NOT NULL,
  started_at   timestamptz NOT NULL,
  finished_at  timestamptz,
  cleared      boolean NOT NULL DEFAULT false,
  clear_ms     integer
);
CREATE INDEX ON dungeon_runs (is_daily, seed, clear_ms) WHERE cleared;
```

**As built (Phase 12, migration `0008_dungeons`).** Only cleared runs are stored:

```sql
CREATE TABLE dungeon_runs (
  id         uuid PRIMARY KEY,
  kind       text NOT NULL,            -- daily | cave
  key        text NOT NULL,            -- daily:<day> | cave:<poi index>
  day        text NOT NULL,            -- UTC date, YYYY-MM-DD
  realm_id   uuid NOT NULL REFERENCES realms ON DELETE CASCADE,
  seed       bigint NOT NULL,
  biome      text NOT NULL,
  names      jsonb NOT NULL,           -- party display names at clear time
  user_ids   jsonb NOT NULL,
  clear_ms   integer NOT NULL,
  deaths     integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  extra      jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_dungeon_runs_board ON dungeon_runs (kind, day, clear_ms);
```

## 10. Infrastructure (Phases 2, 3, 8, 18)

```sql
CREATE TABLE scheduled_events (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind          text NOT NULL,                        -- 'building.complete','craft.complete','market.recalc',…
  due_at        timestamptz NOT NULL,
  payload       jsonb NOT NULL DEFAULT '{}',
  dedupe_key    text UNIQUE,                          -- e.g. 'building.complete:<id>:<level>', 'market.recalc:2026-11-03T10:10'
  status        event_status NOT NULL DEFAULT 'pending',
  attempts      smallint NOT NULL DEFAULT 0,
  locked_until  timestamptz,
  last_error    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  processed_at  timestamptz
);
CREATE INDEX ON scheduled_events (due_at) WHERE status = 'pending';
-- poller: SELECT … WHERE status='pending' AND due_at <= now() ORDER BY due_at LIMIT 50 FOR UPDATE SKIP LOCKED

CREATE TABLE notifications (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  kind        text NOT NULL,                          -- 'building.done','wave.incoming','gift.received','friend.request','boss.spawned',…
  payload     jsonb NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  read_at     timestamptz
);
CREATE INDEX ON notifications (user_id, id DESC);     -- polling fallback: WHERE user_id=? AND id > ?

CREATE TABLE leaderboard_entries (
  board_key     text NOT NULL,                        -- 'avatar_level','legendaries','daily_dungeon','world_boss_player','world_boss_realm','likes'
  period_key    text NOT NULL,                        -- 'all' | '2026-11-03' | 'wb:<event_id>'
  subject_id    uuid NOT NULL,                        -- user or realm
  score         bigint NOT NULL,
  extra         jsonb NOT NULL DEFAULT '{}',          -- display name snapshot, party, etc.
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (board_key, period_key, subject_id)
);
CREATE INDEX ON leaderboard_entries (board_key, period_key, score DESC);

CREATE TABLE config_versions (
  hash        text PRIMARY KEY,
  loaded_at   timestamptz NOT NULL DEFAULT now(),
  summary     jsonb NOT NULL                          -- file list + counts, for the admin panel
);

CREATE TABLE admin_audit_log (                        -- append-only
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id    uuid REFERENCES users,                  -- NULL = system (e.g. anti-cheat auto-kick)
  action      text NOT NULL,
  target      text,
  payload     jsonb NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE issue_reports (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     uuid REFERENCES users ON DELETE SET NULL,
  kind        text NOT NULL,                          -- 'bug','stuck','abuse'
  payload     jsonb NOT NULL,                         -- preset categories + client state; no free text in v1
  created_at  timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);
```

## 11. Mapping from the spec's starting list

| Spec table | Here |
|---|---|
| users, user_settings, avatars, avatar_skills | same |
| realms, realm_members, realm_activity | same |
| realm_map_tiles | **dropped**: seed + `mapgen_version` (D-020); `realm_poi_state` for shared mutable bits |
| realm_stash | `containers(kind='realm_stash')` |
| villages, village_buildings, village_decorations, villagers, resources | same, plus `village_tiles` |
| items | `item_defs` (config mirror) plus `item_instances` |
| inventory_items, bank_items, equipment | `containers` plus `container_slots` (D-006) |
| discoveries, fog_reveals | same (fog as a chunk bitmap) |
| quests, quest_progress | quest defs live in config; `quest_progress` |
| achievements, user_achievements | defs in config; `user_achievements` plus `user_stats` |
| pets, mounts | same |
| market_prices, market_price_history, market_sales_24h | same, sales as 10-minute buckets, plus `market_player_daily` |
| player_market_listings | same, plus `player_market_trades` |
| transactions | same (append-only) plus `idempotency_keys` |
| friends, blocks, gifts, visits_likes | `friendships`, `blocks`, `gifts`, `village_likes`, `village_visits`, `neighbour_helps` |
| scheduled_events, leaderboard_entries, admin_audit_log | same |
| (new) | `sessions`, `recovery_codes`, `presence`, `node_harvests`, `death_drops`, `craft_jobs`, `wallets`, `merchant_purchases`, `monster_waves`, `realm_bosses`, `boss_damage`, `world_boss_events`, `dungeon_runs`, `notifications`, `user_cosmetics`, `login_rewards`, `config_versions`, `issue_reports` |

## 12. Key invariants (each gets a test)

1. A player is in exactly one realm (`realm_members.user_id UNIQUE`). Their village's `realm_id` always equals it, updated in the same transaction.
2. Every item instance is in at most one of: a container slot, an active listing, or a ready craft job (`UNIQUE instance_id` plus a service check plus a test).
3. `wallets.coins ≥ 0` and `resources.amount_milli ≥ 0` (CHECK constraints are the last line of defence behind row locks).
4. The sum of ledger `delta` for coins per user equals `wallets.coins` (a nightly admin check, plus a test).
5. No event handler changes state unless the target row's state matches what the event expects (idempotency).
