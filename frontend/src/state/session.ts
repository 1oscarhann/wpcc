import { create } from "zustand";
import { api, ApiError, setCsrf } from "../api/client";
import type { ConfigBundle, Me } from "../api/types";

type Status = "idle" | "loading" | "anon" | "ready" | "error";

interface SessionState {
  status: Status;
  me: Me | null;
  config: ConfigBundle | null;
  error: string | null;
  serverOffsetMs: number; // server_time - local_time
  load: () => Promise<void>;
  loadConfig: () => Promise<ConfigBundle>;
  setLoggedIn: (csrf: string) => Promise<void>;
  logout: () => Promise<void>;
  patchMe: (fn: (m: Me) => Me) => void;
}

export const useSession = create<SessionState>((set, get) => ({
  status: "idle",
  me: null,
  config: null,
  error: null,
  serverOffsetMs: 0,

  async loadConfig() {
    const existing = get().config;
    if (existing) return existing;
    const config = await api<ConfigBundle>("/api/config");
    set({ config });
    return config;
  },

  async load() {
    set({ status: "loading", error: null });
    try {
      await get().loadConfig();
      const me = await api<Me>("/api/me");
      setCsrf(me.csrf_token);
      set({ me, status: "ready", serverOffsetMs: me.server_time_ms - Date.now() });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) set({ status: "anon", me: null });
      else set({ status: "error", error: e instanceof Error ? e.message : String(e) });
    }
  },

  async setLoggedIn(csrf: string) {
    setCsrf(csrf);
    await get().load();
  },

  async logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      setCsrf(null);
      set({ me: null, status: "anon" });
    }
  },

  patchMe(fn) {
    const me = get().me;
    if (me) set({ me: fn(me) });
  },
}));

export function serverNow(): number {
  return Date.now() + useSession.getState().serverOffsetMs;
}
