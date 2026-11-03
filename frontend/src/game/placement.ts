// Instant client-side placement feedback for the ghost. Mirrors backend domain/placement.py;
// the server re-checks everything (limits, costs, queue) and is authoritative.
import type { BuildingDef, VillageState } from "../api/types";

export function rotatedFootprint(fp: [number, number], rotation: number): [number, number] {
  return rotation % 2 ? [fp[1], fp[0]] : [fp[0], fp[1]];
}

export function usableBounds(frame: number, size: number): [number, number] {
  const lo = Math.floor((frame - size) / 2);
  return [lo, lo + size];
}

interface R {
  x: number;
  y: number;
  w: number;
  h: number;
}
const overlaps = (a: R, b: R) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

function touches(a: R, b: R): boolean {
  if (overlaps(a, b)) return false;
  return overlaps({ x: a.x - 1, y: a.y, w: a.w + 2, h: a.h }, b) || overlaps({ x: a.x, y: a.y - 1, w: a.w, h: a.h + 2 }, b);
}

export function localPlacementError(
  v: VillageState,
  defs: Record<string, BuildingDef>,
  key: string,
  x: number,
  y: number,
  rotation: number,
  ignoreId?: string,
): string | null {
  const def = defs[key];
  if (!def) return "unknown_building";
  const [w, h] = rotatedFootprint(def.footprint, rotation);
  const [lo, hi] = usableBounds(v.frame, v.size);
  if (x < lo || y < lo || x + w > hi || y + h > hi) return "out_of_bounds";
  const r = { x, y, w, h };
  for (const b of v.buildings) {
    if (b.id === ignoreId) continue;
    const [bw, bh] = rotatedFootprint(defs[b.key].footprint, b.rotation);
    if (overlaps(r, { x: b.x, y: b.y, w: bw, h: bh })) return "overlap";
  }
  const [px, py, pw, ph] = v.blocked[0] ?? [0, 0, 0, 0];
  const pond = { x: px, y: py, w: pw, h: ph };
  if (overlaps(r, pond)) return "on_water";
  if (def.requires_water && !touches(r, pond)) return "needs_water";
  return null;
}

export const PLACEMENT_TEXT: Record<string, string> = {
  out_of_bounds: "That's outside your plot.",
  overlap: "Something is already there.",
  on_water: "You can't build on the pond.",
  needs_water: "This needs to touch the pond.",
  locked: "Upgrade your Town Hall to unlock this.",
  limit_reached: "You've built as many of these as your Town Hall allows.",
  unknown_building: "That building doesn't exist.",
};
