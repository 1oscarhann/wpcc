// Phase 13: waves on your village and realm bosses, as the HUD sees them.
import { create } from "zustand";
import { api } from "../api/client";

export interface WaveReport {
  id: string;
  outcome: "flawless" | "held" | "overrun";
  won: boolean;
  line: string;
  spawned: number;
  killed: number;
  through: number;
  stolen: Record<string, number>;
  rewards: Record<string, number>;
  rare: Record<string, number>;
  guards: number;
  guards_left: number;
  towers: number;
  helpers: [string, number][];
}

export interface WaveView {
  id: string;
  status: "announced" | "running" | "done" | "postponed";
  town_hall: number;
  starts_at_ms: number | null;
  ended_at_ms: number | null;
  result: WaveReport | null;
}

export interface BossMarker {
  key: string;
  name: string;
  x: number;
  y: number;
  expires_ms: number;
}

export interface BossInfo {
  key: string;
  name: string;
  biome: string;
  x: number;
  y: number;
  status: "waiting" | "sleeping" | "defeated" | "expired";
  spawns_at_ms: number;
  expires_at_ms: number;
  hp_fraction: number;
  next_at_ms: number;
}

interface DefenceStore {
  wave: WaveView | null; // announced or running
  live: { sub: number; subs: number; stolen: number } | null; // while it runs
  report: WaveReport | null; // shown after a wave
  history: WaveView[];
  bosses: BossMarker[]; // awake realm bosses (map markers)
  boss: BossInfo | null; // from /api/bosses (also the next one's time)
  bossNote: { id: number; text: string; at: number } | null; // under the boss bar
  vulnerable: { id: number; until: number } | null;
  set: (p: Partial<DefenceStore>) => void;
  refresh: () => Promise<void>;
  refreshBoss: () => Promise<void>;
}

export const useDefence = create<DefenceStore>((set) => ({
  wave: null,
  live: null,
  report: null,
  history: [],
  bosses: [],
  boss: null,
  bossNote: null,
  vulnerable: null,
  set: (p) => set(p),
  refresh: async () => {
    try {
      const r = await api<{ current: WaveView | null; history: WaveView[] }>("/api/waves");
      set({ wave: r.current, history: r.history, live: r.current?.status === "running" ? { sub: 0, subs: 0, stolen: 0 } : null });
    } catch {
      /* offline: the next notify will catch us up */
    }
  },
  refreshBoss: async () => {
    try {
      const r = await api<{ boss: BossInfo | null }>("/api/bosses");
      set({ boss: r.boss });
    } catch {
      /* fine */
    }
  },
}));

/** NOTIFY "wave" from the village hub (works in Build Mode too). */
export function onWaveNotify(payload: Record<string, unknown>): void {
  const d = useDefence.getState();
  const status = payload.status as string;
  if (status === "announced") {
    d.set({
      wave: { id: payload.id as string, status: "announced", town_hall: 0, starts_at_ms: payload.starts_at_ms as number, ended_at_ms: null, result: null },
      report: null,
    });
  } else if (status === "running") {
    d.set({ wave: d.wave ? { ...d.wave, status: "running" } : null, live: { sub: 0, subs: 0, stolen: 0 } });
  } else if (status === "done") {
    d.set({ wave: null, live: null, report: payload.report as WaveReport });
  }
}
