# Hearthforge (working title)

A cozy-but-action-packed browser game. You build a village in **Build Mode**, then drop into **Avatar Mode** to explore, fight monsters and gather rare loot with friends. There's no PvP: other players can only help you.

**Status:** all 18 phases are done: Build Mode, Avatar Mode, combat and ten weapon movesets, combos and forging, the NPC market and wandering merchant, the tutorial, realms and co-op, six biomes with POIs and weather, dungeons, raids and realm bosses, villagers and decorations, **social** (friends, blocks, mail, gifts, visits, likes, neighbour help, emotes, quick messages, map pings), **progression** (skill tree, daily/weekly/main quests, achievements and titles, the collection book, the login calendar, pets, mounts, fishing, photo mode), the **global layer** (a player market with escrow, global leaderboards, world boss weekends with one health bar for every realm, festivals) and **launch polish** (rebindable keys, gamepad, a phone "More" menu, generated music, an admin panel, a perf overlay, size budgets in CI, a load test, one-image deploy). See [docs/PLAN.md](docs/PLAN.md).

### Controls (Avatar Mode)

| Action | Desktop | Touch |
|---|---|---|
| Walk | WASD / arrows | left stick |
| Attack / gather (hold to keep swinging) | left mouse, aims at the cursor | big sword button (auto-aims) |
| Heavy attack (stamina) | right mouse or K | small sword button |
| Ability (sword spin / spear throw) | Q | swirl button |
| Dodge roll (i-frames) | Space or Shift | arrows button |
| Potion | 1 or R | potion button |
| Bag | B, I or Tab | bag button |
| Emotes and quick messages | T | speech-bubble button |
| Journal (quests, skills, feats, calendar) | L | scroll button |
| Map (tap a spot to ping it for your realm) | M | mini-map |
| Fish (stand by water, ice or lava), then reel in the gold | E, then E or Space | Fish button, then Reel |
| Ride your mount | G | saddle button |
| Photo mode | P | camera button |
| Back to Build Mode | H or the Village button (not mid-fight) | Village button |
| Talk / open / interact | E | tap it |
| Performance overlay | F3 (or `?perf` in the address) | |

Every key can be rebound in **Settings → Controls** (saved to your account). A standard gamepad works too: left stick walks, right stick aims, A (or RT) attacks, X heavy, Y ability, B dodges, LB off-hand, RB potion, LT talks/fishes/uses, the D-pad picks quick slots, Start opens the bag and Back the map. Build Mode stays mouse-and-keyboard. On phones the HUD keeps the main buttons in a row and tucks the rest under **More**.

Walk into your own village to drop gathered resources into storage.

| Doc | What's in it |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | Spec critique, architecture, folder structure, phase breakdown |
| [docs/SCHEMA.md](docs/SCHEMA.md) | Full Postgres schema |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | WebSocket protocol (msgpack) and REST route map |
| [docs/CONFIG.md](docs/CONFIG.md) | `/config/*.yaml` formats and validation |
| [docs/BALANCE.md](docs/BALANCE.md) | First-pass balance tables |
| [docs/ART.md](docs/ART.md) | Art direction and the generator |
| [docs/PERF.md](docs/PERF.md) | Performance budgets and the load test |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decision log |
| [CREDITS.md](CREDITS.md) | Fonts and libraries, with licences (all art and audio is ours) |

## Run it locally

You need Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 22, and Postgres 16.

### 1. Postgres

With Docker:

```bash
docker compose up -d db
```

Or a native cluster on port 5433:

```bash
initdb -D ~/hf-pg -U hf --auth=trust
```

```bash
pg_ctl -D ~/hf-pg -o "-p 5433" -l ~/hf-pg/log.txt start
```

```bash
createdb -h 127.0.0.1 -p 5433 -U hf hearthforge
```

### 2. Backend (API on :8000)

```bash
cp .env.example .env
```

```bash
cd backend && uv sync && uv run alembic upgrade head
```

```bash
uv run uvicorn hearthforge.main:app --reload --port 8000
```

### 3. Timer worker (completes buildings on time)

```bash
cd backend && uv run python -m hearthforge.worker
```

Without it, timers still complete the next time the village is read (lazy settle), so the game works either way.

Set `HF_MONSTERS=0` to explore without monsters (handy for screenshots of Phase 4).

To feel the netcode under latency, open `http://127.0.0.1:5173/play?lag=150` (dev builds only): every frame is delayed by half that in each direction, with jitter.

### 4. Frontend (on :5173)

```bash
cd frontend && npm install && npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` and `/ws` to the API, so cookies are same-site.

## Tests and checks

```bash
cd backend && uv run pytest
```

```bash
cd backend && uv run ruff check src tests && uv run hf config check
```

```bash
cd frontend && npx tsc -b && npx vitest run
```

```bash
cd tools/artgen && uv run python -m artgen.validate
```

```bash
cd backend && uv run python scripts/bench_tick.py --players 10 --monsters 100
```

Size budgets (CI runs this after the build; see [docs/PERF.md](docs/PERF.md)):

```bash
cd frontend && npm run build && node ../tools/budget.mjs dist
```

Load test: bots sign up, share realms and play at 20 Hz against a dev API:

```bash
cd backend && uv run python ../tools/loadtest.py --bots 30 --seconds 40
```

The shared movement code has golden vectors replayed by both test suites. If you change `sim/motion.py` (and its twin `frontend/src/sim/motion.ts`) on purpose, regenerate them:

```bash
cd backend && uv run python scripts/gen_golden.py
```

Backend tests create and drop a throwaway database on the Postgres at `TEST_DATABASE_ADMIN_URL` (default `postgresql://hf@127.0.0.1:5433/postgres`).

## Admin tools

```bash
cd backend && uv run hf --help
```

| Command | What it does |
|---|---|
| `hf config check` | Validate `/config` |
| `hf test-account NAME` | Allow fast-forward on an account |
| `hf fast-forward NAME 2h` | Move timers and production forward |
| `hf grant NAME --coins 500 --res wood=1000 --item ironbark=2 --level 8 --stat kill.slime=50` | Give coins, resources, bag items, a level or stat counts (written to the ledger and audit log) |
| `hf make-admin NAME` | Admin role: unlocks the **/admin** page (players, grants, bans, test accounts, the world boss, the economy and the audit log) |
| `hf economy` | Coin supply, faucets vs sinks by reason (24 h and 7 d) |
| `hf market recalc` | Reprice the NPC market now (the worker does it every 10 min) |
| `hf market seed --yes` | **Dev only:** 48 h of made-up sales so sparklines and trends have a story |

## Deploy

One Docker image holds everything: it builds the frontend, and the API serves it from the same origin as `/api` and `/ws`, so cookies and the socket need no CORS (D-123). Migrations run when the container starts.

```bash
docker build -t hearthforge .
```

```bash
docker run -p 8000:8000 -e DATABASE_URL=postgresql://user:pass@host:5432/hearthforge -e COOKIE_SECURE=false hearthforge
```

(`COOKIE_SECURE=false` only for plain-http testing on localhost.) The same image runs the timer worker with `python -m hearthforge.worker`.

### Render

[`render.yaml`](render.yaml) is a blueprint: one web service, one worker and a Postgres. In the Render dashboard pick **New → Blueprint**, point it at this repo, then:

1. Set `FRONTEND_ORIGINS` to your real address(es).
2. Add your domain under the web service's **Settings → Custom Domains** and create the CNAME it asks for.
3. Keep `numInstances: 1`. Realm rooms live in memory, so a second API process would split realms in half (PLAN §1.4). Don't use a free instance either: it sleeps and drops every live room.

### Cloudflare Pages in front (optional)

To serve the static files from Cloudflare's edge, deploy `frontend/` to Pages: build command `npm run build`, output `dist`, and set `API_ORIGIN` to the API's address. `frontend/functions/_middleware.ts` proxies `/api` and `/ws` to it, so the browser still sees one origin.

## Art

Every sprite is generated by code. To regenerate after changing `tools/artgen`:

```bash
cd tools/artgen && uv run python -m artgen
```

## Screenshots

With both servers running, this saves desktop and mobile shots to `docs/screenshots/phase-N/`:

```bash
node tools/screenshots.mjs 6
```

`ONLY=desktop` or `ONLY=mobile` limits it to one viewport. Phases before 18 were shot before the phone HUD got its More menu, so a few of their mobile flows open panels the old way. Phases 4 and 5 drive the hero with a dev-only autopilot (`window.__hfGame.devWalkTo / devFight`).

The `/debug` page shows every sprite, icon, character layer, widget, rarity colour and font.
