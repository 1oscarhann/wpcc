"""Phase 18 load test: bots that sign up, share realms (10 to a realm, like real friends), step into the
world and play at 20 Hz — walking, swinging, dodging — while we measure what a player would feel.

    cd backend && uv run python ../tools/loadtest.py --bots 30 --seconds 45

Needs the API in dev mode (HF_ENV=dev): bots skip the per-IP signup limit with a dev-only header, and
the room timings come from GET /api/dev/rooms. Reports, per run:
  - server tick time per room (p50 / p99 / max, the budget is p99 < 10 ms at 20 Hz)
  - snapshot gaps as each bot sees them (should sit at 50 ms)
  - input → acknowledgement round trips (what prediction has to hide)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import msgpack
import websockets

ROOT = Path(__file__).resolve().parents[1]
PROTO = json.loads((ROOT / "shared" / "protocol.json").read_text())
C2S = {k: int(v, 16) for k, v in PROTO["client_to_server"].items()}
S2C = {int(v, 16): k for k, v in PROTO["server_to_client"].items()}
LIGHT = 1  # BTN.light (shared/world.json)
DODGE = 8


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


class Bot:
    def __init__(self, base: str, name: str, look: dict[str, Any]) -> None:
        self.base = base
        self.name = name
        self.look = look
        self.http = httpx.AsyncClient(base_url=base, headers={"x-hf-loadtest": "1"}, timeout=20)
        self.gaps: list[float] = []
        self.rtts: list[float] = []
        self.snaps = 0
        self.errors: list[str] = []

    async def signup(self) -> None:
        r = await self.http.post(
            "/api/auth/signup", json={"username": self.name, "password": "load test 123", "appearance": self.look}
        )
        r.raise_for_status()
        self.http.headers["x-csrf-token"] = r.json()["csrf_token"]
        await self.http.post("/api/tutorial/skip", json={})

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = await self.http.post(path, json=body, headers={"idempotency-key": str(uuid.uuid4())})
        r.raise_for_status()
        return r.json()

    async def play(self, seconds: float) -> None:
        url = self.base.replace("http", "ws", 1) + "/ws"
        cookie = "; ".join(f"{k}={v}" for k, v in self.http.cookies.items())
        try:
            async with websockets.connect(url, additional_headers={"cookie": cookie, "origin": self.base}, max_size=None) as ws:
                await ws.send(msgpack.packb([C2S["HELLO"], PROTO["version"], "loadtest", False]))
                await ws.send(msgpack.packb([C2S["ENTER_AVATAR"]]))
                sent: dict[int, float] = {}
                state = {"tick": 0, "joined": False}

                async def reader() -> None:
                    last = None
                    async for raw in ws:
                        msg = msgpack.unpackb(raw, raw=False, strict_map_key=False)
                        op = S2C.get(msg[0])
                        if op == "ROOM_JOINED":
                            state["joined"] = True
                            state["tick"] = msg[2]
                        elif op == "SNAPSHOT":
                            now = time.perf_counter()
                            state["tick"] = msg[1]
                            self.snaps += 1
                            if last is not None:
                                self.gaps.append((now - last) * 1000)
                            last = now
                            t0 = sent.pop(msg[2], None)
                            if t0 is not None:
                                self.rtts.append((now - t0) * 1000)
                            for k in [k for k in sent if k < msg[2]]:
                                sent.pop(k, None)
                        elif op == "KICK":
                            self.errors.append(f"kicked: {msg[1:]}")
                            return

                async def writer() -> None:
                    seq = 0
                    mx = my = 0
                    end = time.perf_counter() + seconds
                    while not state["joined"] and time.perf_counter() < end:
                        await asyncio.sleep(0.05)
                    nxt = time.perf_counter()
                    while time.perf_counter() < end:
                        if seq % 40 == 0:  # a new direction every two seconds
                            mx, my = random.choice([(0, 0), (127, 0), (-127, 0), (0, 127), (0, -127), (90, 90), (-90, 90)])
                        b = LIGHT if random.random() < 0.15 else 0
                        if random.random() < 0.01:
                            b |= DODGE
                        seq += 1
                        sent[seq] = time.perf_counter()
                        vt = max(0, state["tick"] - 2)
                        await ws.send(msgpack.packb([C2S["INPUT"], seq, seq, vt, mx, my, mx or 64, my, b]))
                        nxt += 0.05
                        await asyncio.sleep(max(0, nxt - time.perf_counter()))
                    await ws.send(msgpack.packb([C2S["LEAVE_AVATAR"]]))

                rd = asyncio.create_task(reader())
                await writer()
                await asyncio.sleep(0.3)
                rd.cancel()
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"{type(e).__name__}: {e}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--bots", type=int, default=20)
    ap.add_argument("--per-realm", type=int, default=10)
    ap.add_argument("--seconds", type=float, default=40)
    a = ap.parse_args()
    cfg = httpx.get(f"{a.base}/api/config", timeout=20).json()
    look = cfg["avatar"]["default_appearance"]
    run = random.randint(1000, 9999)
    bots = [Bot(a.base, f"Bot{run}x{i}", look) for i in range(a.bots)]
    t0 = time.perf_counter()
    for i in range(0, len(bots), 10):
        await asyncio.gather(*(b.signup() for b in bots[i : i + 10]))
    # realm-mates: the first bot of each group opens a realm, the rest join it
    for g in range(0, len(bots), a.per_realm):
        host, *rest = bots[g : g + a.per_realm]
        r = await host.post("/api/realms", {"name": f"Load {run} {g // a.per_realm}"})
        code = r["realm"]["invite_code"]
        for b in rest:
            await b.post("/api/realms/join", {"code": code})
    print(f"{len(bots)} bots signed up in {time.perf_counter() - t0:.1f}s; playing for {a.seconds:.0f}s…")
    await asyncio.gather(*(b.play(a.seconds) for b in bots))
    rooms = (await bots[0].http.get("/api/dev/rooms")).json()["rooms"]
    gaps = [g for b in bots for g in b.gaps]
    rtts = [r for b in bots for r in b.rtts]
    errors = [e for b in bots for e in b.errors]
    print("\n── rooms (server tick, ms) ─────────────────────────")
    for r in rooms:
        t = r["tick_ms"]
        print(f"  {r['realm_id'][-8:]}  players {r['players']:>3}  monsters {r['monsters']:>3}  "
              f"p50 {t.get('p50', 0):6.2f}  p99 {t.get('p99', 0):6.2f}  max {t.get('max', 0):6.2f}")
    print("── what the bots felt ─────────────────────────────")
    print(f"  snapshots: {sum(b.snaps for b in bots)} ({sum(b.snaps for b in bots) / len(bots) / a.seconds:.1f}/s per bot)")
    print(f"  snapshot gap ms: p50 {pct(gaps, 0.5):.1f}  p95 {pct(gaps, 0.95):.1f}  p99 {pct(gaps, 0.99):.1f}")
    print(f"  input→ack ms:    p50 {pct(rtts, 0.5):.1f}  p95 {pct(rtts, 0.95):.1f}  p99 {pct(rtts, 0.99):.1f}"
          f"  (mean {statistics.fmean(rtts) if rtts else float('nan'):.1f})")
    print(f"  errors: {len(errors)}" + (f" e.g. {errors[0]}" if errors else ""))
    for b in bots:
        await b.http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
