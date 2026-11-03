# Hearthforge (working title)

A cozy-but-action-packed browser game. You build a village in **Build Mode**, then drop into **Avatar Mode** to explore, fight monsters and gather rare loot with friends. There's no PvP: other players can only help you.

**Status: Phase 1 (planning), waiting for approval.** There's no game code yet.

| Doc | What's in it |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | Spec critique and proposed changes, architecture, folder structure, phase breakdown |
| [docs/SCHEMA.md](docs/SCHEMA.md) | Full Postgres schema |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | WebSocket protocol (msgpack) and REST route map |
| [docs/CONFIG.md](docs/CONFIG.md) | `/config/*.yaml` formats and validation |
| [docs/BALANCE.md](docs/BALANCE.md) | First-pass balance tables |
| [docs/ART.md](docs/ART.md) | Art direction, asset packs, audio, manifest |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decision log |

Planned stack: FastAPI, SQLAlchemy 2 (async) and Alembic on Neon Postgres, msgpack WebSockets, React, Vite, TypeScript, PixiJS v8, GSAP and Howler. The backend and worker deploy to Render, and the frontend to Cloudflare Pages.
