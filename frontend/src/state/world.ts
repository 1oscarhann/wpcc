// The sky over your realm (Phase 10, P9). The day/night phase is a pure function of time computed from
// the clock config in the bundle (no requests); season and weather come from GET /api/world, refreshed
// when the current 20-minute weather block ends.
import { create } from "zustand";
import { api } from "../api/client";
import { serverNow, useSession } from "./session";

export type Weather = "clear" | "rain" | "snow" | "fog" | "storm";

export interface Forecast {
  weather: Weather;
  starts_ms: number;
  ends_ms: number;
}

interface WorldResponse {
  now_ms: number;
  phase: string;
  season: string;
  season_ends_ms: number;
  weather: Weather;
  effects: { production: Record<string, number>; aggro: number; rare_node: Record<string, number> };
  forecast: Forecast[];
}

interface WorldState {
  season: string;
  seasonEnds: number;
  weather: Weather;
  effects: WorldResponse["effects"] | null;
  forecast: Forecast[];
  loaded: boolean;
  load: () => Promise<void>;
}

/** Dev/screenshot override: ?sky=night,storm,winter forces a phase, weather and/or season. */
function override(): { phase?: string; weather?: Weather; season?: string; at?: number } {
  if (!import.meta.env.DEV || typeof location === "undefined") return {};
  const q = new URLSearchParams(location.search).get("sky");
  if (!q) return {};
  const out: { phase?: string; weather?: Weather; season?: string; at?: number } = {};
  for (const p of q.split(",")) {
    if (["dawn", "day", "dusk", "night"].includes(p)) out.phase = p;
    else if (["clear", "rain", "snow", "fog", "storm"].includes(p)) out.weather = p as Weather;
    else if (["spring", "summer", "autumn", "winter"].includes(p)) out.season = p;
    else if (/^\d+(\.\d+)?$/.test(p)) out.at = Number(p);
  }
  return out;
}
const OVERRIDE = override();
if (import.meta.env.DEV && typeof window !== "undefined") {
  // screenshots/playtests: window.__hfSky("night,storm") re-points the sky without a reload
  (window as unknown as { __hfSky?: (q: string) => void }).__hfSky = (q: string) => {
    const u = new URL(location.href);
    u.searchParams.set("sky", q);
    history.replaceState(null, "", u);
    for (const k of Object.keys(OVERRIDE)) delete (OVERRIDE as Record<string, unknown>)[k];
    Object.assign(OVERRIDE, override());
    const st = useWorld.getState();
    useWorld.setState({ weather: OVERRIDE.weather ?? st.weather, season: OVERRIDE.season ?? st.season });
  };
}

let timer: number | null = null;

export const useWorld = create<WorldState>((set, get) => ({
  season: "spring",
  seasonEnds: 0,
  weather: "clear",
  effects: null,
  forecast: [],
  loaded: false,
  async load() {
    try {
      const r = await api<WorldResponse>("/api/world");
      set({
        season: OVERRIDE.season ?? r.season,
        seasonEnds: r.season_ends_ms,
        weather: OVERRIDE.weather ?? r.weather,
        effects: r.effects,
        forecast: r.forecast,
        loaded: true,
      });
      const next = r.forecast[0]?.ends_ms ?? r.now_ms + 60_000;
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => void get().load(), Math.max(10_000, next - serverNow() + 1500));
    } catch {
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => void get().load(), 30_000);
    }
  },
}));

export interface DayPhase {
  name: string; // dawn | day | dusk | night
  progress: number; // 0..1 through this phase
  /** 0 = full daylight … 1 = deepest night, smooth through dawn and dusk. */
  dark: number;
  /** 0..1 how much warm sunrise/sunset glow there is. */
  glow: number;
}

/** Mirror of backend domain/worldclock.day_phase, plus smooth lighting curves for the renderer. */
export function dayPhase(now = serverNow()): DayPhase {
  const wc = useSession.getState().config?.world_clock;
  if (!wc) return { name: "day", progress: 0.5, dark: 0, glow: 0 };
  const lengthMs = wc.day_length * 1000;
  let pos = ((now % lengthMs) + lengthMs) % lengthMs;
  if (OVERRIDE.phase) {
    let acc = 0;
    for (const [n, d] of Object.entries(wc.phases)) {
      if (n === OVERRIDE.phase) {
        pos = (acc + d * (OVERRIDE.at ?? 0.5)) * 1000;
        break;
      }
      acc += d;
    }
  }
  let acc = 0;
  for (const [name, dur] of Object.entries(wc.phases)) {
    const d = dur * 1000;
    if (pos < acc + d) {
      const p = (pos - acc) / d;
      const ease = (x: number) => x * x * (3 - 2 * x);
      const dark = name === "night" ? 1 : name === "dusk" ? ease(p) : name === "dawn" ? 1 - ease(p) : 0;
      const glow = name === "dusk" || name === "dawn" ? Math.sin(p * Math.PI) : 0;
      return { name, progress: p, dark, glow };
    }
    acc += d;
  }
  return { name: "night", progress: 1, dark: 1, glow: 0 };
}

/** Which ring of the map (x, y in tiles) is in: meadow, forest, …, ashen. Edges are approximate. */
export function biomeAt(x: number, y: number): string {
  const cfg = useSession.getState().config;
  if (!cfg) return "meadow";
  const c = cfg.map.size / 2;
  const r = Math.hypot(x - c, y - c);
  let biome = "meadow";
  for (const b of cfg.map.bands) if (r >= b.radius) biome = b.biome;
  return biome;
}

/** What actually falls from the sky here: rain turns to snow up north and to ash in the wastes. */
export function precipitation(weather: Weather, biome: string): "none" | "rain" | "snow" | "ash" {
  if (weather === "clear" || weather === "fog") return biome === "ashen" ? "ash" : "none";
  if (biome === "ashen") return "ash";
  if (biome === "frozen" || weather === "snow") return "snow";
  return "rain";
}
