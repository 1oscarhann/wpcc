// Client-side counter interpolation. Mirrors backend domain/resources.py (lazy maths) for display only:
// the server is always the source of truth and re-bases these numbers on every response.
import type { ResourceState } from "../api/types";

export function amountAt(r: ResourceState, atMs: number, nowMs: number): number {
  if (r.amount >= r.cap || r.rate <= 0 || nowMs <= atMs) return r.amount;
  return Math.min(r.cap, r.amount + (r.rate * (nowMs - atMs)) / 3_600_000);
}

export function canAfford(
  cost: Record<string, number>,
  resources: Record<string, ResourceState>,
  coins: number,
  atMs: number,
  nowMs: number,
): Record<string, number> {
  const missing: Record<string, number> = {};
  for (const [k, qty] of Object.entries(cost)) {
    const have = k === "coins" ? coins : resources[k] ? amountAt(resources[k], atMs, nowMs) : 0;
    if (have + 1e-9 < qty) missing[k] = Math.ceil(qty - have);
  }
  return missing;
}
