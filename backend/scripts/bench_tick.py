"""Tick benchmark (PLAN §5): one RealmRoom with N wandering players and M monsters, no DB or sockets.

    cd backend && uv run python scripts/bench_tick.py --players 10 --monsters 100 --ticks 400

Budget: p99 under 10 ms per tick (snapshots for every player included).
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
import time
import uuid
from types import SimpleNamespace

from hearthforge.config.loader import load_config
from hearthforge.settings import REPO_ROOT
from hearthforge.sim import motion as mo
from hearthforge.sim.combat import Combat, SpawnPoint
from hearthforge.sim.room import Input, Player, RealmRoom
from hearthforge.sim.rules import BTN_LIGHT
from hearthforge.sim.stats import stats_for


class NullConn:
    async def send_bytes(self, data: bytes) -> None:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=10)
    ap.add_argument("--monsters", type=int, default=100)
    ap.add_argument("--ticks", type=int, default=400)
    ap.add_argument(
        "--cold",
        action="store_true",
        help="don't pre-generate map chunks (the client's chunk fetches warm them in production)",
    )
    args = ap.parse_args()
    cfg = load_config(REPO_ROOT / "config")
    st = SimpleNamespace(config=cfg, village_hub=None, rooms=None)
    room = RealmRoom(st, uuid.uuid4(), seed=99)  # type: ignore[arg-type]
    room.set_villages({}, set())
    room.combat = Combat(room)
    room.combat._wake = lambda t: None  # type: ignore[method-assign]  # we place monsters ourselves
    rng = random.Random(3)
    c = cfg.mapgen.map_size // 2
    r = cfg.mapgen.forest.radius + 12
    cx, cy = c + r, c
    spots = [
        (x + 0.5, y + 0.5)
        for x in range(cx - 20, cx + 20)
        for y in range(cy - 14, cy + 14)
        if not room.grid.solid(x, y)
    ]
    players = []
    for i in range(args.players):
        x, y = rng.choice(spots)
        s = stats_for(cfg, 10)
        p = Player(
            eid=room.new_id(),
            user_id=uuid.uuid4(),
            name=f"bot{i}",
            appearance={},
            conn=NullConn(),  # type: ignore[arg-type]
            m=mo.Motion(x=x, y=y, st=s.st_max, st_max=s.st_max),
            level=10,
            xp=0,
            hp=float(s.hp_max),
            stats=s,
            weapon={"key": None, "type": "sword", "tier": 2, "rarity": "rare"},
            quick={},
            inv=[],
            inv_cap=24,
            home_rect=(0, 0, 1, 1),
            home_door=(x, y),
        )
        room.players[p.eid] = p
        room.by_user[p.user_id] = p
        players.append(p)
    for i in range(args.monsters):
        x, y = rng.choice(spots)
        sp = SpawnPoint(10_000 + i, x, y, "forest", rng.choice(["wolf", "spider"]), i % 15 == 0, 1)
        room.combat.spawns[sp.id] = sp
        room.combat._spawn(sp, 0)
    if not args.cold:
        cs = cfg.mapgen.chunk_size
        for gy in range((cy - 60) // cs, (cy + 60) // cs + 1):
            for gx in range((cx - 60) // cs, (cx + 60) // cs + 1):
                room.grid.solid(gx * cs, gy * cs)
    times = []
    for t in range(args.ticks):
        for p in players:
            a = t * 0.05 + p.eid
            p.last_seq += 1
            p.inputs.append(
                Input(
                    p.last_seq,
                    p.last_seq,
                    room.tick_no,
                    int(127 * math.cos(a)),
                    int(127 * math.sin(a)),
                    127,
                    0,
                    BTN_LIGHT if t % 7 == 0 else 0,
                )
            )
            if p.ko:
                p.hp = p.stats.hp_max
        t0 = time.perf_counter()
        room.tick()
        for p in players:
            room.snapshot(p)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    p50, p99 = times[len(times) // 2], times[int(len(times) * 0.99) - 1]
    alive = len(room.combat.monsters)
    print(f"{args.players} players, {args.monsters} monsters ({alive} alive at the end), {args.ticks} ticks")
    mean = statistics.mean(times)
    print(f"tick+snapshots: p50 {p50:.2f} · p99 {p99:.2f} · max {times[-1]:.2f} · mean {mean:.2f} (ms)")
    print("budget 10 ms p99:", "OK" if p99 < 10 else "OVER")


if __name__ == "__main__":
    main()
