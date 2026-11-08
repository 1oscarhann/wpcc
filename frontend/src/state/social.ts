// Phase 15: friends, requests, blocks, the mailbox, and which village you're visiting.
import { create } from "zustand";
import { api, ApiError } from "../api/client";
import type { Appearance, VillageState } from "../api/types";
import { toast } from "./toasts";

export interface FriendView {
  id: string;
  name: string;
  level: number;
  title: string | null;
  look: Appearance | null;
  realm: string | null;
  likes: number;
  online: boolean;
}

export interface MailView {
  id: string;
  from: string;
  kind: "gift" | "boss" | "system" | string;
  items: Record<string, number>;
  coins: number;
  note: string | null;
  at_ms: number;
}

export interface SocialView {
  friends: FriendView[];
  incoming: FriendView[];
  outgoing: FriendView[];
  blocked: { id: string; name: string }[];
  max: number;
  mail: MailView[];
}

/** A visitor's view of someone's village: no purse, no workbench, no undo. */
export interface VisitView {
  village: Omit<VillageState, "coins" | "undo" | "jobs" | "new_discoveries">;
  owner: { id: string; name: string; level: number; title: string | null; look: Appearance | null };
  likes: number;
  liked: boolean;
  helped_today: string[];
  helps_left: number;
  mine: boolean;
}

/** A map ping (Phase 15): shown on the minimap, the world map and as a ring in the world. */
export interface Ping {
  id: number;
  eid: number;
  name: string;
  x: number;
  y: number;
  until: number; // performance.now() ms
  mine: boolean;
}

interface SocialStore {
  open: boolean;
  /** Avatar Mode's emote and quick-message wheel (T) */
  chatOpen: boolean;
  pings: Ping[];
  view: SocialView | null;
  /** owner id of the village being visited (the panel shows that instead of the list) */
  visiting: string | null;
  set: (p: Partial<SocialStore>) => void;
  fetch: () => Promise<SocialView | null>;
  /** POST and fold the answer (the friends view) back in. Toasts on errors; null if it failed. */
  act: <T = Partial<SocialView>>(path: string, body?: unknown) => Promise<T | null>;
}

let inflight: Promise<SocialView | null> | null = null;

export const useSocial = create<SocialStore>((set, get) => ({
  open: false,
  chatOpen: false,
  pings: [],
  view: null,
  visiting: null,
  set: (p) => set(p),
  fetch: () => {
    if (inflight) return inflight;
    inflight = api<SocialView>("/api/social")
      .then((v) => {
        set({ view: v });
        return v;
      })
      .catch(() => null)
      .finally(() => {
        inflight = null;
      });
    return inflight;
  },
  act: async (path, body) => {
    try {
      const r = await api<Record<string, unknown>>(path, { method: "POST", body });
      const prev = get().view;
      if (prev && r && typeof r === "object") {
        const merged = { ...prev };
        for (const k of ["friends", "incoming", "outgoing", "blocked", "mail"] as const) {
          if (k in r) (merged as Record<string, unknown>)[k] = r[k];
        }
        set({ view: merged });
      }
      return r as never;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
      return null;
    }
  },
}));

let pingId = 0;

export function addPing(p: Omit<Ping, "id">): void {
  const now = performance.now();
  const keep = useSocial.getState().pings.filter((x) => x.until > now && x.eid !== p.eid);
  useSocial.setState({ pings: [...keep, { ...p, id: ++pingId }].slice(-12) });
}

export function livePings(): Ping[] {
  const now = performance.now();
  return useSocial.getState().pings.filter((x) => x.until > now);
}

/** How many things are waiting for you: friend requests plus parcels. */
export function socialDot(v: SocialView | null): number {
  return v ? v.incoming.length + v.mail.length : 0;
}

/** NOTIFY "social" from the server: someone asked, accepted, helped or sent you something. */
export function onSocialNotify(payload: Record<string, unknown>): void {
  const kind = String(payload.kind ?? "");
  void useSocial.getState().fetch();
  if (kind === "friend_sent") toast("Someone wants to be friends! Check your Friends list.", "good", "party");
  else if (kind === "friend_accepted") toast("A friend request was accepted!", "good", "party");
  else if (kind === "mail") toast("A parcel arrived in your mailbox!", "good", "mail");
  else if (kind === "helped") toast("A neighbour sped up one of your builds!", "good", "heart");
}
