// Phase 14: your villagers, walking their day. Work at their job through dawn and day, the Tavern (or a
// stroll) at dusk, home at night (they go inside). They prefer paths, grumble or sing in speech bubbles
// depending on how the village feels, and stop to greet you when you walk past in Avatar Mode.
// Purely client-side: the server only knows who lives where and works what.
import { Container, Graphics, Rectangle, Sprite, Text, Texture } from "pixi.js";
import type { BuildingDef, VillageState, VillagerView } from "../api/types";
import { useDefence } from "../state/defence";
import { useSession } from "../state/session";
import { dayPhase } from "../state/world";
import { composeAvatar, frameFor } from "./avatarComposer";
import { rotatedFootprint, usableBounds } from "./placement";

const T = 16;
const SPEED = 22; // px / s
const INK = 0x2b1e2a;

export interface VillagerHost {
  origin(): [number, number];
  village(): VillageState | null;
  defs(): Record<string, BuildingDef>;
  objects: Container;
  screen: Container;
  toScreen(wx: number, wy: number): { x: number; y: number };
  zoom(): number;
  avatar(): { x: number; y: number; weapon: string } | null; // world tiles
}

interface Walker {
  v: VillagerView;
  sprite: Sprite;
  frames: Texture[];
  path: [number, number][];
  x: number; // world px, feet
  y: number;
  dir: string;
  idle: number;
  t: number;
  goal: string; // where it's heading (a key, so a phase change re-plans)
  inside: boolean;
  bubble: { c: Container; until: number } | null;
  nextTalk: number;
  greeted: number;
  pause: number;
}

const rand = (a: number, b: number) => a + Math.random() * (b - a);
const pick = <X,>(xs: X[]) => xs[Math.floor(Math.random() * xs.length)];

export class VillagerLife {
  private walkers = new Map<string, Walker>();
  private loading = new Set<string>();
  private cost: Map<string, number> | null = null; // frame tile → step cost (paths are cheaper)
  private costFor = -1;
  private time = 0;

  constructor(private host: VillagerHost) {}

  destroy(): void {
    for (const w of this.walkers.values()) {
      w.sprite.destroy();
      w.bubble?.c.destroy({ children: true });
    }
    this.walkers.clear();
  }

  /** The village changed shape: everyone re-plans. */
  invalidate(): void {
    this.cost = null;
    for (const w of this.walkers.values()) w.path = [];
  }

  // ── the map ─────────────────────────────────────────────────────────────
  private grid(v: VillageState): Map<string, number> {
    if (this.cost && this.costFor === v.version) return this.cost;
    const defs = this.host.defs();
    const [lo, hi] = usableBounds(v.frame, v.size);
    const blocked = new Set<string>();
    const paths = new Set<string>();
    for (const b of v.buildings) {
      const d = defs[b.key];
      if (!d) continue;
      const [w, h] = rotatedFootprint(d.footprint, b.rotation);
      for (let x = b.x; x < b.x + w; x++) {
        for (let y = b.y; y < b.y + h; y++) (d.walkable ? paths : blocked).add(`${x},${y}`);
      }
    }
    for (const [, , , x, y] of v.debris) blocked.add(`${x},${y}`);
    for (const [px, py, pw, ph] of v.blocked) {
      for (let x = px; x < px + pw; x++) for (let y = py; y < py + ph; y++) blocked.add(`${x},${y}`);
    }
    const cost = new Map<string, number>();
    for (let x = lo; x < hi; x++) {
      for (let y = lo; y < hi; y++) {
        const k = `${x},${y}`;
        if (!blocked.has(k)) cost.set(k, paths.has(k) ? 1 : 2.5);
      }
    }
    this.cost = cost;
    this.costFor = v.version;
    return cost;
  }

  /** Cheapest route (Dijkstra; ≤ 48×48 tiles, and only when a villager sets off). */
  private route(v: VillageState, from: [number, number], to: [number, number]): [number, number][] {
    const cost = this.grid(v);
    const key = (x: number, y: number) => `${x},${y}`;
    const goal = key(...to);
    const dist = new Map<string, number>([[key(...from), 0]]);
    const prev = new Map<string, string>();
    const open: [number, number, number][] = [[0, from[0], from[1]]];
    while (open.length) {
      let bi = 0;
      for (let i = 1; i < open.length; i++) if (open[i][0] < open[bi][0]) bi = i;
      const [d, x, y] = open.splice(bi, 1)[0];
      const k = key(x, y);
      if (k === goal) break;
      if (d > (dist.get(k) ?? Infinity)) continue;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nk = key(x + dx, y + dy);
        const c = cost.get(nk);
        if (c === undefined && nk !== goal) continue;
        const nd = d + (c ?? 1);
        if (nd < (dist.get(nk) ?? Infinity)) {
          dist.set(nk, nd);
          prev.set(nk, k);
          open.push([nd, x + dx, y + dy]);
        }
      }
    }
    if (!dist.has(goal)) return [];
    const out: [number, number][] = [];
    let c: string | undefined = goal;
    while (c) {
      const [x, y] = c.split(",").map(Number);
      out.unshift([x, y]);
      c = prev.get(c);
    }
    return out;
  }

  /** The tile in front of a building's door (bottom middle), in frame tiles. */
  private door(v: VillageState, id: string | null): [number, number] | null {
    const b = id ? v.buildings.find((x) => x.id === id) : undefined;
    if (!b) return null;
    const [w, h] = rotatedFootprint(this.host.defs()[b.key].footprint, b.rotation);
    return [b.x + Math.floor(w / 2), b.y + h];
  }

  private wanderSpot(v: VillageState, near: [number, number] | null): [number, number] {
    const cost = this.grid(v);
    for (let i = 0; i < 20; i++) {
      const [lo, hi] = usableBounds(v.frame, v.size);
      const x = near ? near[0] + Math.round(rand(-4, 4)) : Math.floor(rand(lo, hi));
      const y = near ? near[1] + Math.round(rand(-3, 3)) : Math.floor(rand(lo, hi));
      if (cost.has(`${x},${y}`)) return [x, y];
    }
    return near ?? [v.gate[0], v.gate[1] - 1];
  }

  /** Where this villager wants to be right now, and what it's called (so a change re-plans). */
  private goal(v: VillageState, w: Walker): { key: string; at: [number, number]; inside: boolean } {
    const phase = dayPhase().name;
    const sched = useSession.getState().config?.villagers.schedule;
    const raid = useDefence.getState().live !== null;
    const home = this.door(v, w.v.home);
    if (raid || (sched?.home.includes(phase) ?? phase === "night")) {
      return home ? { key: `home:${w.v.home}`, at: home, inside: true } : { key: "wander", at: this.wanderSpot(v, null), inside: false };
    }
    if (sched?.social.includes(phase)) {
      const tavern = v.buildings.find((b) => b.key === "tavern" && b.level >= 1);
      const at = tavern ? this.door(v, tavern.id) : null;
      if (at) return { key: `tavern:${tavern!.id}:${Math.floor(this.time / 20)}`, at: this.wanderSpot(v, at), inside: false };
      return { key: `stroll:${Math.floor(this.time / 15)}`, at: this.wanderSpot(v, null), inside: false };
    }
    const job = this.door(v, w.v.job);
    if (job) return { key: `job:${w.v.job}:${Math.floor(this.time / 25)}`, at: this.wanderSpot(v, job), inside: false };
    return { key: `idle:${Math.floor(this.time / 12)}`, at: this.wanderSpot(v, home), inside: false };
  }

  // ── people ──────────────────────────────────────────────────────────────
  private async add(v: VillageState, info: VillagerView): Promise<void> {
    if (this.loading.has(info.id)) return;
    this.loading.add(info.id);
    try {
      const strip = await composeAvatar(info.look);
      const base = Texture.from(strip);
      base.source.scaleMode = "nearest";
      const frames = Array.from({ length: strip.width / 16 }, (_, i) =>
        new Texture({ source: base.source, frame: new Rectangle(i * 16, 0, 16, 24) }));
      const [ox, oy] = this.host.origin();
      const at = this.door(v, info.home) ?? this.wanderSpot(v, null);
      const sprite = new Sprite(frames[0]);
      sprite.anchor.set(0.5, 1);
      const x = (ox + at[0] + 0.5) * T;
      const y = (oy + at[1] + 1) * T - 2;
      sprite.position.set(x, y);
      this.host.objects.addChild(sprite);
      this.walkers.set(info.id, {
        v: info, sprite, frames, path: [], x, y, dir: "down", idle: rand(0, 2), t: Math.random() * 1000,
        goal: "", inside: false, bubble: null, nextTalk: this.time + rand(3, 12), greeted: -1e9, pause: 0,
      });
    } finally {
      this.loading.delete(info.id);
    }
  }

  private say(w: Walker, text: string, secs = 3.2): void {
    w.bubble?.c.destroy({ children: true });
    const c = new Container();
    const t = new Text({ text, style: { fontFamily: "Fredoka", fontSize: 12, fill: INK, fontWeight: "600" } });
    t.resolution = 2;
    const pad = 5;
    const g = new Graphics()
      .roundRect(-t.width / 2 - pad, -t.height - pad * 1.4, t.width + pad * 2, t.height + pad * 1.4, 5)
      .fill({ color: 0xfaf2dd })
      .stroke({ width: 2, color: INK })
      .poly([-4, -2, 4, -2, 0, 4])
      .fill({ color: 0xfaf2dd });
    t.anchor.set(0.5, 1);
    t.y = -pad * 0.7;
    c.addChild(g, t);
    this.host.screen.addChild(c);
    w.bubble = { c, until: this.time + secs };
  }

  private lines(): Record<string, string[]> {
    return useSession.getState().config?.villagers.lines ?? {};
  }

  update(dtMs: number): void {
    const dt = Math.min(dtMs, 50) / 1000;
    this.time += dt;
    const v = this.host.village();
    if (!v) return;
    // who lives here now
    const ids = new Set((v.villagers ?? []).map((x) => x.id));
    for (const [id, w] of this.walkers) {
      if (!ids.has(id)) {
        w.sprite.destroy();
        w.bubble?.c.destroy({ children: true });
        this.walkers.delete(id);
      }
    }
    for (const info of v.villagers ?? []) {
      const w = this.walkers.get(info.id);
      if (!w) void this.add(v, info);
      else if (w.v.job !== info.job || w.v.home !== info.home) {
        w.v = info;
        w.path = [];
        w.goal = "";
      }
    }
    const [ox, oy] = this.host.origin();
    const av = this.host.avatar();
    const lines = this.lines();
    const mood = v.happiness?.mood ?? "happy";
    for (const w of this.walkers.values()) {
      w.t += dt * 1000;
      // a passing chief: stop, turn, say hello (once in a while)
      if (av && !w.inside) {
        const d = Math.hypot(av.x * T - w.x, av.y * T - w.y) / T;
        if (d < 2.6 && this.time - w.greeted > 30) {
          w.greeted = this.time;
          w.pause = 2.2;
          w.dir = Math.abs(av.x * T - w.x) > Math.abs(av.y * T - w.y) ? (av.x * T > w.x ? "right" : "left") : av.y * T > w.y ? "down" : "up";
          const raid = useDefence.getState().live !== null;
          const pool = raid ? lines.wave : Math.random() < 0.35 && av.weapon ? lines.gear : lines.greet;
          if (pool?.length) this.say(w, pick(pool).replace("{weapon}", av.weapon.replace(/_/g, " ")));
        }
      }
      if (w.pause > 0) {
        w.pause -= dt;
      } else {
        const g = this.goal(v, w);
        if (g.key !== w.goal) {
          w.goal = g.key;
          const from: [number, number] = [Math.floor(w.x / T) - ox, Math.floor((w.y - 1) / T) - oy];
          w.path = this.route(v, from, g.at).slice(1);
          if (!w.path.length && w.inside !== g.inside) w.inside = g.inside;
        }
        if (w.path.length) {
          w.inside = false;
          const [tx, ty] = w.path[0];
          const gx = (ox + tx + 0.5) * T;
          const gy = (oy + ty + 1) * T - 2;
          const dx = gx - w.x;
          const dy = gy - w.y;
          const d = Math.hypot(dx, dy);
          if (d < 1) {
            w.path.shift();
            if (!w.path.length) w.inside = g.inside; // home at night: in through the door
          } else {
            const step = Math.min(d, SPEED * dt);
            w.x += (dx / d) * step;
            w.y += (dy / d) * step;
            w.dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : dy > 0 ? "down" : "up";
          }
        }
      }
      // a word now and then: how they feel about the village (or their work)
      if (this.time > w.nextTalk && !w.inside) {
        w.nextTalk = this.time + rand(10, 24);
        if (Math.random() < 0.4) {
          const pool = mood === "happy" && w.v.job && Math.random() < 0.4 ? lines.working : lines[mood];
          if (pool?.length) this.say(w, pick(pool));
        }
      }
      const moving = w.path.length > 0 && w.pause <= 0;
      const f = frameFor(w.dir, moving ? "walk" : "idle", w.t);
      w.sprite.texture = w.frames[f.index];
      w.sprite.scale.x = f.flip ? -1 : 1;
      w.sprite.position.set(Math.round(w.x), Math.round(w.y));
      w.sprite.zIndex = w.y;
      w.sprite.alpha += ((w.inside ? 0 : 1) - w.sprite.alpha) * Math.min(1, dt * 6);
      if (w.bubble) {
        if (this.time > w.bubble.until || w.inside) {
          w.bubble.c.destroy({ children: true });
          w.bubble = null;
        } else {
          const p = this.host.toScreen(w.x, w.y - 26);
          w.bubble.c.position.set(Math.round(p.x), Math.round(p.y));
          w.bubble.c.alpha = Math.min(1, (w.bubble.until - this.time) * 3);
        }
      }
    }
  }

  /** For screenshots and tests: make someone talk now. */
  devSay(text: string): void {
    const w = [...this.walkers.values()].find((x) => !x.inside);
    if (w) this.say(w, text, 6);
  }
}
