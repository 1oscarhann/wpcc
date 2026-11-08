# Performance budgets and the load test (Phase 18)

The target is a mid-range phone on 4G. The server target is one modest instance holding every realm room in memory (PLAN §1.4).

## Budgets

| What | Budget | Where it's checked | Now |
|---|---|---|---|
| Main script, gzipped | ≤ 350 KB | `tools/budget.mjs` in CI, after `vite build` | 307 KB |
| All scripts, gzipped | ≤ 520 KB | same | 404 KB |
| World atlas PNG | ≤ 700 KB | same | 168 KB |
| Characters + icons PNG | ≤ 160 KB | same | 26 KB |
| First load (scripts + art + fonts) | ≤ 1.3 MB | same | 856 KB |
| Server tick, per room | p99 < 10 ms (a fifth of the 50 ms tick) | `GET /api/dev/rooms`, the admin panel's Rooms card, `tools/loadtest.py` | p99 2–6 ms with 10 players and 70–140 monsters |
| Frame time on the client | ≤ 22 ms (45 fps) | the F3 overlay | depends on the device; headless Chromium (software rendering) runs ~5 fps and isn't a guide |
| Sprites on stage | ≤ 4,000 | the F3 overlay (terrain chunks count as one each, they're cached as textures) | |
| Round trip | ≤ 250 ms feels fine; prediction hides it (PLAN §2.5, D-009) | the F3 overlay | |

The F3 overlay (or `?perf` in the address) shows each number in red when it's over.

## The load test

`tools/loadtest.py` signs up bots (10 to a realm, like friends), steps them into the world and plays at 20 Hz: walking in a new direction every two seconds, swinging 15% of the time, dodging now and then. It needs the API in dev mode: bots skip the per-IP signup limit with a dev-only header, and room timings come from `GET /api/dev/rooms`.

```bash
cd backend && uv run python ../tools/loadtest.py --bots 30 --seconds 40
```

### Run of 2026-11-08 (this sandbox: one container, Postgres alongside)

| | |
|---|---|
| Bots | 30, in 3 realms of 10 |
| Rooms (server tick ms) | p50 1.3–3.0, **p99 2.0–6.0**, max 5.7–10.6, with 74–142 monsters awake |
| Snapshots per bot | 17.9/s (the room sends 20/s) |
| Snapshot gaps | p50 49.8 ms, p95 113 ms, p99 184 ms |
| Input → acknowledgement | p50 67 ms, p95 189 ms (mean 92) |
| Errors | 0 |

The bots' own numbers are pessimistic: 30 clients share one Python process and one core with the server, so their event loop is the bottleneck for the gaps and round trips. The server's tick, the number that limits how many players a room holds, stays far inside budget. At this rate one process should hold roughly 15–20 busy realms before p99 reaches 10 ms; past that, rooms go to more processes (rooms sit behind the `RealmRoom` interface for exactly this, D-003).
