# Credits

Audited in Phase 18 (2026-11-08). Nothing in the game is taken from a third-party asset pack.

## Art

Every sprite, tile, building, character layer, monster, boss, pet, mount, fish, icon, UI texture and the title scene is **original**, drawn by our own code in `tools/artgen` (Python and Pillow, deterministic; see `docs/ART.md` and D-031). No third-party art packs are used.

## Sound and music

All sound effects, ambient beds (wind, rain, birds, crickets, frogs, embers…) and the background music are **synthesized at runtime** with the Web Audio API by our own code (`frontend/src/game/sfx.ts`, `soundscape.ts`, `music.ts`; D-047, D-126). No samples or recordings are shipped.

## Fonts

| Font | Use | Licence | Source |
|---|---|---|---|
| Pixelify Sans (The Pixelify Sans Project Authors) | Headings | SIL Open Font License 1.1 (`frontend/public/assets/fonts/OFL-PixelifySans.txt`) | Google Fonts |
| Fredoka (The Fredoka Project Authors) | Body text | SIL Open Font License 1.1 (`frontend/public/assets/fonts/OFL-Fredoka.txt`) | Google Fonts |

## Software

Shipped in the browser bundle:

| Library | Licence |
|---|---|
| PixiJS | MIT |
| React, React DOM | MIT |
| React Router | MIT |
| Zustand | MIT |
| @msgpack/msgpack | ISC |
| GSAP | GSAP Standard "no charge" licence (free, including commercial use; https://gsap.com/standard-license) |

On the server:

| Library | Licence |
|---|---|
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| SQLAlchemy | MIT |
| Alembic | MIT |
| asyncpg | Apache-2.0 |
| Pydantic, pydantic-settings | MIT |
| argon2-cffi | MIT |
| msgpack | Apache-2.0 |
| PyYAML | MIT |
| Typer | MIT |
| websockets, httpx (tools and tests) | BSD-3-Clause |

Tools: Pillow (MIT-CMU) for the art generator; Vite, TypeScript, Vitest, Playwright, Ruff and pytest for building and testing (not shipped).
