// Phase 12: the delve you're in (if any). The RoomClient writes it from DUNGEON_* events; the Game
// draws it (game/delve.ts) and the HUD shows progress, the boss bar and the way out.
import { create } from "zustand";

export interface DelveLayout {
  w: number;
  h: number;
  tiles: Uint8Array; // 0 void · 1 floor · 2 wall · 3 door
  rooms: [number, string, number, number, number, number, number, string][]; // id, kind, x, y, w, h, depth, puzzle
  doors: [number, [number, number][], [number, number], boolean][]; // id, tiles, rooms, gate
  props: [string, number, number, number, number][]; // kind, x, y, room, data
  start: [number, number];
}

export interface DelveState {
  locked: number[];
  visited: number[];
  cleared: number[];
  plates: number[];
  lamps: number;
  solved: number[];
  portal: boolean;
  clear_ms: number | null;
}

export interface DelveInfo {
  id: number;
  name: string;
  kind: "cave" | "daily";
  biome: string;
  difficulty: number;
  origin: [number, number];
  layout: DelveLayout;
  state: DelveState;
  started_ms: number;
}

interface DelveStore {
  delve: DelveInfo | null;
  state: DelveState | null;
  boss: { id: number; name: string; note?: string; enraged?: boolean } | null;
  levers: Record<number, boolean>; // prop index → flipped
  chests: number[]; // prop indices you've opened
  near: { kind: "use" | "portal"; prop: number; label: string } | null;
  panel: boolean; // the Delve Gate's leaderboard panel
  set: (p: Partial<DelveStore>) => void;
}

export const useDelve = create<DelveStore>((set) => ({
  delve: null,
  state: null,
  boss: null,
  levers: {},
  chests: [],
  near: null,
  panel: false,
  set: (p) => set(p),
}));

export const SOLID_PROPS = new Set(["pillar", "chest", "lamp"]);

/** Same rule as the server's DungeonSpace._rebuild_solid (walls, void, pillars, chests, lamps, locked doors). */
export function delveSolid(info: DelveInfo, state: DelveState): Uint8Array {
  const { w, h, tiles, props, doors } = info.layout;
  const s = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) s[i] = tiles[i] === 0 || tiles[i] === 2 ? 1 : 0;
  for (const [kind, x, y] of props) if (SOLID_PROPS.has(kind)) s[y * w + x] = 1;
  const locked = new Set(state.locked);
  for (const [id, ts] of doors) if (locked.has(id)) for (const [x, y] of ts) s[y * w + x] = 1;
  return s;
}
