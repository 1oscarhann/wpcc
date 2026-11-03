// Village state for Build Mode. The server is the source of truth: every REST response and every
// WebSocket push carries the full village state with a version, and older versions are ignored.
import { create } from "zustand";
import { api, ApiError } from "../api/client";
import type { VillageState } from "../api/types";
import { toast } from "./toasts";

export interface MapMeta {
  realm_id: string;
  version: number;
  size: number;
  chunk_size: number;
  tile_names: string[];
  object_names: string[];
  hub: { center: number; radius: number };
  plots: { index: number; origin: [number, number]; owner: string | null }[];
  my_plot: number;
}

export interface Placing {
  key: string;
  rotation: number;
  moveId?: string;
  x?: number;
  y?: number;
}

type Listener = (prev: VillageState | null, next: VillageState) => void;

interface VillageStore {
  village: VillageState | null;
  map: MapMeta | null;
  selectedId: string | null;
  placing: Placing | null;
  busy: boolean;
  wsConnected: boolean;
  fetch: () => Promise<void>;
  fetchMap: () => Promise<MapMeta>;
  apply: (v: VillageState) => void;
  select: (id: string | null) => void;
  startPlacing: (p: Placing | null) => void;
  setGhost: (x: number, y: number) => void;
  rotateGhost: () => void;
  confirmPlacement: () => Promise<boolean>;
  upgrade: (id: string) => Promise<void>;
  cancel: (id: string) => Promise<void>;
  demolish: (id: string) => Promise<void>;
  undo: () => Promise<void>;
  setWs: (connected: boolean) => void;
}

const listeners = new Set<Listener>();
export function onVillageChange(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function errorToast(e: unknown) {
  toast(e instanceof ApiError ? e.message : "Something went wrong.", "bad");
}

export const useVillage = create<VillageStore>((set, get) => {
  async function mutate(path: string, method: string, body?: unknown, okText?: string): Promise<boolean> {
    set({ busy: true });
    try {
      const r = await api<{ village: VillageState }>(path, { method, body });
      get().apply(r.village);
      if (okText) toast(okText, "good");
      return true;
    } catch (e) {
      errorToast(e);
      return false;
    } finally {
      set({ busy: false });
    }
  }

  return {
    village: null,
    map: null,
    selectedId: null,
    placing: null,
    busy: false,
    wsConnected: false,

    async fetch() {
      const r = await api<{ village: VillageState }>("/api/village");
      get().apply(r.village);
    },

    async fetchMap() {
      const existing = get().map;
      if (existing) return existing;
      const map = await api<MapMeta>("/api/realm/map");
      set({ map });
      return map;
    },

    apply(next) {
      const prev = get().village;
      if (prev && next.version < prev.version) return;
      set({ village: next });
      const sel = get().selectedId;
      if (sel && !next.buildings.some((b) => b.id === sel)) set({ selectedId: null });
      for (const fn of listeners) fn(prev, next);
    },

    select(id) {
      set({ selectedId: id, placing: null });
    },

    startPlacing(p) {
      set({ placing: p, selectedId: null });
    },

    setGhost(x, y) {
      const p = get().placing;
      if (p && (p.x !== x || p.y !== y)) set({ placing: { ...p, x, y } });
    },

    rotateGhost() {
      const p = get().placing;
      if (p) set({ placing: { ...p, rotation: (p.rotation + 1) % 4 } });
    },

    async confirmPlacement() {
      const p = get().placing;
      if (!p || p.x === undefined || p.y === undefined || get().busy) return false;
      const ok = p.moveId
        ? await mutate(`/api/village/buildings/${p.moveId}`, "PATCH", { x: p.x, y: p.y, rotation: p.rotation })
        : await mutate("/api/village/buildings", "POST", { key: p.key, x: p.x, y: p.y, rotation: p.rotation });
      if (ok) set({ placing: null });
      return ok;
    },

    upgrade: async (id) => void (await mutate(`/api/village/buildings/${id}/upgrade`, "POST")),
    cancel: async (id) => void (await mutate(`/api/village/buildings/${id}/cancel`, "POST", undefined, "Cancelled — most of the cost came back.")),
    demolish: async (id) => {
      if (await mutate(`/api/village/buildings/${id}`, "DELETE", undefined, "Demolished. Half the materials came back.")) {
        set({ selectedId: null });
      }
    },
    undo: async () => void (await mutate("/api/village/undo", "POST", undefined, "Undone!")),

    setWs(connected) {
      set({ wsConnected: connected });
    },
  };
});
