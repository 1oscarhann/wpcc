import { describe, expect, it } from "vitest";
import golden from "../../../shared/golden/movement.json";
import { RoomClient } from "../../src/net/room";
import { ClientGrid } from "../../src/sim/grid";
import { newMotion, step, toList } from "../../src/sim/motion";
import type { Rules } from "../../src/sim/rules";

const rules = golden.rules as unknown as Rules;

function joined(x: number, y: number): unknown[] {
  const self = [...toList(newMotion(x, y, 100)), 100, 100, 0];
  const info = {
    level: 1, xp: 0, xp_next: 100, hp_max: 100, weapon: { key: null, type: "sword", tier: 1, rarity: "common" },
    quick: {}, inv: [], inv_capacity: 24, home: { rect: [0, 0, 1, 1], door: [x, y] }, hz: 20,
  };
  return [0xa0, "realm", 100, 7, self, info, [], [], [], []];
}

describe("RoomClient prediction", () => {
  it("predicts instantly, then reconciles to the server by replaying unacked inputs", () => {
    const sent: unknown[][] = [];
    const grid = new ClientGrid(64, 16, ["tile.grass.0"], ["obj.oak.0"], []);
    const c = new RoomClient((...a) => void sent.push(a), joined(10.5, 10.5), grid, rules);
    c.input.mx = 127;
    c.update(50 * 4); // four fixed steps
    expect(sent.filter((m) => m[0] === "INPUT")).toHaveLength(4);
    expect(c.me.x).toBeCloseTo(10.5 + 4 * rules.speed_tick, 9);

    // the server applied the first two inputs but got knocked back a little on the way
    const server = newMotion(10.5, 10.5, 100);
    for (let i = 0; i < 2; i++) step(server, 127, 0, 0, 0, 0, rules, rules.weapons.sword, grid.solid);
    server.x -= 0.3;
    const before = c.drawPos();
    c.onSnapshot([0xa1, 102, 2, [...toList(server), 100, 100, 0], [], []]);
    // reconciled: server state + the 2 unacked inputs replayed on top
    expect(c.me.x).toBeCloseTo(10.5 + 4 * rules.speed_tick - 0.3, 9);
    // but nothing jumps on screen: the correction is absorbed by the visual offset and fades out
    expect(c.drawPos().x).toBeCloseTo(before.x, 9);
    c.input.mx = 0;
    c.update(400);
    expect(Math.abs(c.offset.x)).toBeLessThan(0.01);
  });

  it("interpolates other entities 100 ms in the past", () => {
    const grid = new ClientGrid(64, 16, ["tile.grass.0"], ["obj.oak.0"], []);
    const c = new RoomClient(() => undefined, joined(10.5, 10.5), grid, rules);
    const ent = (tick: number, x: number) => [0xa1, tick, 0, [...toList(c.me), 100, 100, 0], [[42, 1, "slime", x * 64, 640, 0, 0, 0, 0, 255, 0]], []];
    c.onSnapshot(ent(110, 10));
    c.onSnapshot(ent(111, 11));
    const e = c.ents.get(42)!;
    expect(c.sampleAt(e, 110.5)!.x).toBeCloseTo(10.5, 9);
    expect(c.sampleAt(e, 200)!.x).toBe(11); // never extrapolates
  });
});
