// Phase 6 UI state: the discovery celebration, the forge reveal, and which crafting panels are open.
import { create } from "zustand";
import type { ForgedItem } from "../api/types";

interface CraftingStore {
  discovery: { key: string; name: string; buildings: string[]; unlocks: string[] } | null;
  reveal: ForgedItem | null;
  bookOpen: boolean;
  stationId: string | null;
  bagOpen: boolean;
  set: (p: Partial<CraftingStore>) => void;
}

export const useCrafting = create<CraftingStore>((set) => ({
  discovery: null,
  reveal: null,
  bookOpen: false,
  stationId: null,
  bagOpen: false,
  set: (p) => set(p),
}));
