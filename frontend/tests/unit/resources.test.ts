import { describe, expect, it } from "vitest";
import { amountAt, canAfford } from "../../src/game/resources";
import { localPlacementError, rotatedFootprint } from "../../src/game/placement";
import type { BuildingDef, VillageState } from "../../src/api/types";

describe("amountAt", () => {
  it("interpolates and clamps at the cap", () => {
    const r = { amount: 100, rate: 60, cap: 130 };
    expect(amountAt(r, 0, 1_800_000)).toBeCloseTo(130); // +30 after 30 min
    expect(amountAt(r, 0, 900_000)).toBeCloseTo(115);
    expect(amountAt(r, 0, 99_000_000)).toBe(130);
  });
  it("never decreases an over-cap amount", () => {
    expect(amountAt({ amount: 500, rate: 60, cap: 100 }, 0, 3_600_000)).toBe(500);
  });
  it("reports what is missing", () => {
    const res = { wood: { amount: 30, rate: 0, cap: 1000 } };
    expect(canAfford({ wood: 50, coins: 10 }, res, 5, 0, 0)).toEqual({ wood: 20, coins: 5 });
  });
});

const def = (fp: [number, number], water = false) =>
  ({ footprint: fp, requires_water: water } as unknown as BuildingDef);
const DEFS = { house: def([2, 2]), dock: def([2, 3], true), market: def([3, 2]) };
const V = {
  frame: 48, size: 24, blocked: [[14, 31, 5, 3]],
  buildings: [{ id: "h", key: "house", x: 20, y: 20, rotation: 0 }],
} as unknown as VillageState;

describe("localPlacementError (mirrors backend placement rules)", () => {
  it("rotates footprints", () => expect(rotatedFootprint([3, 2], 1)).toEqual([2, 3]));
  it("accepts a free spot", () => expect(localPlacementError(V, DEFS, "house", 26, 14, 0)).toBeNull());
  it("rejects bounds/overlap/water", () => {
    expect(localPlacementError(V, DEFS, "house", 11, 20, 0)).toBe("out_of_bounds");
    expect(localPlacementError(V, DEFS, "house", 21, 21, 0)).toBe("overlap");
    expect(localPlacementError(V, DEFS, "house", 21, 21, 0, "h")).toBeNull();
    expect(localPlacementError(V, DEFS, "house", 14, 31, 0)).toBe("on_water");
  });
  it("docks must touch the pond", () => {
    expect(localPlacementError(V, DEFS, "dock", 26, 14, 0)).toBe("needs_water");
    expect(localPlacementError(V, DEFS, "dock", 19, 31, 0)).toBeNull();
  });
});
