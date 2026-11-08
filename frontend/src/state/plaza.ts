// Phase 17: the Plaza — the player market, leaderboards, the world boss and festivals.
import { create } from "zustand";
import { api } from "../api/client";

export type PlazaTab = "market" | "boards" | "world" | "festival";

export interface WorldBossView {
  name: string;
  boss: string;
  next_ms: number | null;
  tiers: { damage: number; coins: number; items: Record<string, number> }[];
  top_realms: number;
  title: string;
  event: null | {
    id: string;
    status: "active" | "defeated" | "expired";
    hp_max: number;
    hp_remaining: number;
    starts_ms: number;
    ends_ms: number;
    realms: { realm_id: string; name: string; damage: number; fighters: number }[];
    players: { name: string; damage: number }[];
    me: { damage: number; tier: number };
  };
}

export interface FestivalView {
  active: null | {
    key: string;
    name: string;
    desc: string;
    color: string;
    token: string;
    token_name: string;
    have: number;
    starts_ms: number;
    ends_ms: number;
    drop_chance: number;
    shop: { index: number; item: string | null; name: string; title: string | null; qty: number; cost: number; owned: boolean }[];
  };
  next: null | { key: string; name: string; starts_ms: number };
}

interface PlazaStore {
  tab: PlazaTab | null;
  world: WorldBossView | null;
  festival: FestivalView | null;
  set: (p: Partial<PlazaStore>) => void;
  refresh: () => Promise<void>;
}

export const usePlaza = create<PlazaStore>((set) => ({
  tab: null,
  world: null,
  festival: null,
  set: (p) => set(p),
  refresh: async () => {
    const [world, festival] = await Promise.all([
      api<WorldBossView>("/api/worldboss").catch(() => null),
      api<FestivalView>("/api/festival").catch(() => null),
    ]);
    set({ world, festival });
  },
}));
