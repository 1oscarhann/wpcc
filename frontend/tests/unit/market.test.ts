import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import type { MarketItem } from "../../src/api/types";
import { payoutPreview } from "../../src/ui/hud/Market";

const item = (p: Partial<MarketItem>): MarketItem => ({
  key: "wood", name: "Wood", icon: "icon.wood", source: "storage", have: 500, base: 2, raw_price: 3.644,
  price: 3.644, over_price: 1.822, trend: 0, change: 0, spark: [3.644], units_24h: 0, baseline: 8000,
  sold_today: 0, soft_cap: 2000, ...p,
});

describe("payoutPreview", () => {
  it("matches the server: one floor for the whole sale", () => {
    expect(payoutPreview(item({}), 50)).toEqual({ coins: Math.floor(3.644 * 50), over: 0 });
  });
  it("halves units past the daily soft cap", () => {
    const r = payoutPreview(item({ price: 10, over_price: 5, sold_today: 15, soft_cap: 40 }), 30);
    expect(r).toEqual({ coins: 275, over: 5 });
  });
});

describe("api idempotency", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("retries a dropped mutation once with the same key", async () => {
    const keys: string[] = [];
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
      keys.push((init.headers as Record<string, string>)["idempotency-key"]);
      if (++calls === 1) throw new TypeError("network down");
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }));
    await expect(api("/api/market/sell", { method: "POST", body: { item: "wood", quantity: 1 } })).resolves.toEqual({ ok: true });
    expect(keys).toHaveLength(2);
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(keys[1]).toBe(keys[0]);
  });
  it("never retries or keys a GET", async () => {
    const f = vi.fn(async () => {
      throw new TypeError("down");
    });
    vi.stubGlobal("fetch", f);
    await expect(api("/api/market")).rejects.toMatchObject({ code: "network" });
    expect(f).toHaveBeenCalledTimes(1);
  });
});
