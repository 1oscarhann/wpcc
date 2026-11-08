// Phase 16b: pets and mounts (what you own and which are out), the Trophy Hall, and the fishing line.
import { create } from "zustand";
import { api, ApiError } from "../api/client";
import { toast } from "./toasts";

export interface PetView {
  key: string;
  name: string;
  desc: string;
  perks: Record<string, number>;
  owned: boolean;
  nickname: string | null;
  active: boolean;
  cost: { coins: number; tokens: number } | null;
  unlock?: { hint: string; progress: number; target: number };
}

export interface MountView {
  key: string;
  name: string;
  desc: string;
  speed: number;
  owned: boolean;
  active: boolean;
  cost: { coins: number; tokens: number };
  town_hall: number;
  locked: boolean;
}

export interface CompanionsView {
  pets: PetView[];
  mounts: MountView[];
  tokens: number;
  coins: number;
  town_hall: number;
}

interface CompanionsStore {
  view: CompanionsView | null;
  fetch: () => Promise<CompanionsView | null>;
  act: (path: string, body: unknown) => Promise<CompanionsView | null>;
}

export const useCompanions = create<CompanionsStore>((set) => ({
  view: null,
  fetch: async () => {
    try {
      const v = await api<CompanionsView>("/api/companions");
      set({ view: v });
      return v;
    } catch {
      return null;
    }
  },
  act: async (path, body) => {
    try {
      const v = await api<CompanionsView>(path, { method: "POST", body });
      set({ view: v });
      return v;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
      return null;
    }
  },
}));

/** The fishing line (Avatar Mode): cast → waiting → bite (the timing bar runs) → done. */
export interface FishState {
  phase: "idle" | "waiting" | "bite";
  id: number;
  barMs: number;
  centerMs: number;
  windowMs: number;
  rarity: string;
  shownAt: number; // performance.now() when the bar started
  x: number;
  y: number;
}

const IDLE: FishState = { phase: "idle", id: 0, barMs: 0, centerMs: 0, windowMs: 0, rarity: "common", shownAt: 0, x: 0, y: 0 };

export const useFishing = create<FishState & { set: (p: Partial<FishState>) => void; reset: () => void }>((set) => ({
  ...IDLE,
  set: (p) => set(p),
  reset: () => set(IDLE),
}));
