// Avatar Mode HUD state. The RoomClient (net/room.ts) writes it; React reads it.
import { create } from "zustand";

export type Mode = "build" | "entering" | "avatar" | "leaving";
export type InvSlot = [number, string, number, boolean]; // slot, item, qty, is_instance

export interface Weapon {
  key: string | null;
  type: string;
  tier: number;
  rarity: string;
}

interface AvatarStore {
  mode: Mode;
  hp: number;
  hpMax: number;
  st: number;
  stMax: number;
  level: number;
  xp: number;
  xpNext: number;
  flags: number;
  weapon: Weapon;
  quick: Record<string, [string, number]>;
  inv: InvSlot[];
  invCap: number;
  abCd: number; // ticks left
  abCdMax: number;
  dodgeCd: number;
  bagOpen: boolean;
  inCombat: boolean;
  koUntil: number; // performance.now() ms
  set: (p: Partial<AvatarStore>) => void;
}

export const useAvatar = create<AvatarStore>((set) => ({
  mode: "build",
  hp: 100,
  hpMax: 100,
  st: 100,
  stMax: 100,
  level: 1,
  xp: 0,
  xpNext: 100,
  flags: 0,
  weapon: { key: null, type: "sword", tier: 1, rarity: "common" },
  quick: {},
  inv: [],
  invCap: 24,
  abCd: 0,
  abCdMax: 1,
  dodgeCd: 0,
  bagOpen: false,
  inCombat: false,
  koUntil: 0,
  set: (p) => set(p),
}));
