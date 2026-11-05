// Phase 9: your realm, its members, the map overview (+ your fog), your mates' villages, and your party.
import { create } from "zustand";
import { api } from "../api/client";
import type { Appearance, BuildingState } from "../api/types";
import { toast } from "./toasts";

export interface RealmMemberView {
  user_id: string;
  username: string;
  role: "owner" | "member";
  plot: number;
  trusted: boolean;
  newcomer: boolean;
  level: number;
  online: boolean;
  appearance: Appearance;
}

export interface RealmView {
  id: string;
  name: string;
  solo: boolean;
  invite_code: string | null;
  owner_id: string;
  me: { role: "owner" | "member"; plot: number; trusted: boolean };
  max_members: number;
  members: RealmMemberView[];
}

export interface Waystone {
  index: number;
  x: number;
  y: number;
  name: string;
}

export interface Overview {
  n: number;
  chunk_size: number;
  data: Uint8Array;
  fog: Uint8Array;
  reveal_radius: number;
  waystones: Waystone[];
  attuned: number[];
  use_radius: number;
}

export interface MateVillage {
  owner_id: string;
  name: string;
  version: number;
  size: number;
  frame: number;
  origin: [number, number];
  buildings: BuildingState[];
  debris: [number, string, number, number, number][];
  gate: [number, number];
}

export interface PartyMember {
  user_id: string;
  eid: number | null;
  name: string;
  level: number;
  hp: number;
  hp_max: number;
  here: boolean;
  x: number | null;
  y: number | null;
}

export interface PartyState {
  id: string;
  leader: string;
  members: PartyMember[];
}

interface RealmStore {
  realm: RealmView | null;
  overview: Overview | null;
  mates: Record<string, MateVillage>;
  party: PartyState | null;
  invite: { party: string; from: string } | null;
  panel: "members" | "stash" | "activity" | null;
  mapOpen: boolean;
  travelMode: boolean; // the full map was opened at a waystone: attuned stones are clickable
  nearWaystone: number | null;
  set: (p: Partial<RealmStore>) => void;
  load: () => Promise<void>;
  loadOverview: () => Promise<void>;
  loadMates: () => Promise<void>;
  applyMate: (v: MateVillage) => void;
  reveal: (tx: number, ty: number) => void;
  attune: (attuned: number[]) => void;
}

const b64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

export const useRealm = create<RealmStore>((set, get) => ({
  realm: null,
  overview: null,
  mates: {},
  party: null,
  invite: null,
  panel: null,
  mapOpen: false,
  travelMode: false,
  nearWaystone: null,
  set: (p) => set(p),
  load: async () => {
    try {
      const r = await api<{ realm: RealmView }>("/api/realm");
      set({ realm: r.realm });
    } catch {
      /* keep the last copy */
    }
  },
  loadOverview: async () => {
    try {
      const o = await api<Omit<Overview, "data" | "fog"> & { data: string; fog: string }>("/api/realm/overview");
      set({ overview: { ...o, data: b64(o.data), fog: b64(o.fog) } });
    } catch {
      /* the map just stays as it was */
    }
  },
  loadMates: async () => {
    try {
      const r = await api<{ villages: MateVillage[] }>("/api/realm/villages");
      set({ mates: Object.fromEntries(r.villages.map((v) => [v.owner_id, v])) });
      const { roomLink } = await import("../net/room");
      for (const v of r.villages) roomLink.send?.("SUB_VILLAGE", v.owner_id); // live updates
    } catch {
      /* no mates drawn this time */
    }
  },
  applyMate: (v) => {
    const cur = get().mates[v.owner_id];
    if (cur && cur.version >= v.version) return;
    set({ mates: { ...get().mates, [v.owner_id]: { ...cur, ...v } } });
  },
  /** Same rule as the server: chunks within reveal_radius of you become seen. */
  reveal: (tx, ty) => {
    const o = get().overview;
    if (!o) return;
    const cx = Math.floor(tx / o.chunk_size);
    const cy = Math.floor(ty / o.chunk_size);
    let changed = false;
    const fog = o.fog;
    for (let y = Math.max(0, cy - o.reveal_radius); y <= Math.min(o.n - 1, cy + o.reveal_radius); y++) {
      for (let x = Math.max(0, cx - o.reveal_radius); x <= Math.min(o.n - 1, cx + o.reveal_radius); x++) {
        const i = y * o.n + x;
        if (!(fog[i >> 3] & (1 << (i & 7)))) {
          fog[i >> 3] |= 1 << (i & 7);
          changed = true;
        }
      }
    }
    if (changed) set({ overview: { ...o, fog } });
  },
  attune: (attuned) => {
    const o = get().overview;
    if (o) set({ overview: { ...o, attuned } });
  },
}));

export function isRevealed(o: Overview, cx: number, cy: number): boolean {
  const i = cy * o.n + cx;
  return Boolean(o.fog[i >> 3] & (1 << (i & 7)));
}

/** NOTIFY "realm": something about the realm changed (members, names, trust). */
export async function onRealmNotify(myRealmId: string | null): Promise<void> {
  const before = myRealmId;
  await useRealm.getState().load();
  const after = useRealm.getState().realm?.id ?? null;
  if (before && after && before !== after) {
    // our village moved to another realm: everything about the world changes, so start fresh
    toast("Moving your village…", "good", "home");
    window.setTimeout(() => window.location.reload(), 900);
    return;
  }
  await Promise.all([useRealm.getState().loadMates(), useRealm.getState().loadOverview()]);
  window.dispatchEvent(new CustomEvent("hf:realm-changed"));
}
