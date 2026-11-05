// Phase 8: the tutorial the server tracks, and the "While you were away" card.
import { create } from "zustand";
import { api } from "../api/client";
import type { Appearance, VillageState } from "../api/types";
import { sfx } from "../game/sfx";
import { toast } from "./toasts";
import { useVillage } from "./village";

export interface TutorialStep {
  key: string;
  title: string;
  lines: string[];
  kind: "confirm" | "buildings" | "stat" | "discovery";
  button: string | null;
  highlight: string | null;
  reward: Record<string, number>;
  progress: [number, number];
}

export interface TutorialView {
  active: boolean;
  index: number;
  total: number;
  guide: { name: string; look: Appearance };
  steps: { key: string; title: string }[];
  step?: TutorialStep;
}

export interface AwayCard {
  show: boolean;
  away_s: number;
  gained: Record<string, number>;
  full: string[];
  finished: { key: string; level: number }[];
  crafted: Record<string, number>;
  gear_ready: number;
  coins: number;
  merchant_moved: boolean;
  quip: string;
  guide: { name: string; look: Appearance };
}

interface TutorialStore {
  tut: TutorialView | null;
  minimized: boolean;
  away: AwayCard | null;
  busy: boolean;
  load: () => Promise<void>;
  check: (confirm?: string) => Promise<void>;
  skip: () => Promise<void>;
  loadAway: () => Promise<void>;
  ackAway: () => Promise<void>;
  set: (p: Partial<TutorialStore>) => void;
}

const rewardText = (r: Record<string, number>) =>
  Object.entries(r).map(([k, v]) => `+${v} ${k}`).join(", ");

export const useTutorial = create<TutorialStore>((set, get) => ({
  tut: null,
  minimized: false,
  away: null,
  busy: false,
  set: (p) => set(p),
  load: async () => {
    try {
      set({ tut: await api<TutorialView>("/api/tutorial") });
    } catch {
      /* the guide just stays quiet */
    }
  },
  check: async (confirm) => {
    if (get().busy) return;
    set({ busy: true });
    try {
      const r = await api<{ tutorial: TutorialView; completed: { key: string; title: string; reward: Record<string, number> }[]; village: VillageState | null }>(
        "/api/tutorial/check",
        { method: "POST", body: { confirm: confirm ?? null } },
      );
      if (r.village) useVillage.getState().apply(r.village);
      for (const c of r.completed) {
        if (c.key === "welcome") continue;
        const extra = Object.keys(c.reward).length ? ` (${rewardText(c.reward)})` : "";
        toast(`✓ ${c.title}${extra}`, "good", "star");
      }
      if (r.completed.length && r.tutorial.step?.key !== r.completed[0].key) {
        sfx(r.tutorial.active ? "levelup" : "fanfare");
        set({ minimized: false });
      }
      set({ tut: r.tutorial });
    } catch {
      /* try again on the next nudge */
    } finally {
      set({ busy: false });
    }
  },
  skip: async () => {
    try {
      const r = await api<{ tutorial: TutorialView }>("/api/tutorial/skip", { method: "POST" });
      set({ tut: r.tutorial });
    } catch {
      /* already over */
    }
  },
  loadAway: async () => {
    try {
      const card = await api<AwayCard>("/api/away-summary");
      if (card.show) set({ away: card });
    } catch {
      /* no card is fine */
    }
  },
  ackAway: async () => {
    set({ away: null });
    try {
      await api("/api/away-summary/ack", { method: "POST" });
    } catch {
      /* it'll show once more, no harm */
    }
  },
}));
