// Ambient life for Build Mode: strolling villagers, ducks, butterflies, chimney smoke, water glints,
// falling leaves and passing birds. Purely cosmetic; real villagers with jobs arrive in Phase 14.
import { AnimatedSprite, Container, Rectangle, Sprite, Texture } from "pixi.js";
import type { Appearance, BuildingDef, VillageState } from "../api/types";
import { useSession } from "../state/session";
import { composeAvatar, frameFor } from "./avatarComposer";
import { rotatedFootprint, usableBounds } from "./placement";
import { tex } from "./sprites";

const T = 16;

export interface WorldInfo {
  origin(): [number, number];
  village(): VillageState | null;
  defs(): Record<string, BuildingDef>;
  view(): { x0: number; y0: number; x1: number; y1: number }; // world px
  waterTiles: Set<string>; // world tile "x,y"
  treeSpots: { x: number; y: number }[]; // world px (canopy)
  flowerSpots: { x: number; y: number }[];
  smokeSpots(): { x: number; y: number }[];
}

interface Walker {
  sprite: Sprite;
  frames: Texture[];
  path: [number, number][]; // frame tiles still to walk
  x: number; // world px (feet)
  y: number;
  dir: string;
  idle: number;
  t: number;
}

const rand = (a: number, b: number) => a + Math.random() * (b - a);
const pick = <X,>(xs: X[]) => xs[Math.floor(Math.random() * xs.length)];

export class Ambient {
  private walkers: Walker[] = [];
  private ducks: { s: AnimatedSprite; tx: number; ty: number }[] = [];
  private butterflies: { s: AnimatedSprite; ax: number; ay: number; ph: number; retarget: number }[] = [];
  private timers = { smoke: 0, glint: 0, leaf: 0, bird: rand(4, 10) };
  private spawning = false;
  private time = 0;

  constructor(
    private info: WorldInfo,
    private objects: Container, // depth-sorted world layer
    private fx: Container, // above objects
    private sky: Container, // birds
  ) {}

  // ── villagers ──────────────────────────────────────────────────────────────
  private blocked(v: VillageState): Set<string> {
    const b = new Set<string>();
    const defs = this.info.defs();
    for (const bl of v.buildings) {
      const [w, h] = rotatedFootprint(defs[bl.key].footprint, bl.rotation);
      for (let x = bl.x; x < bl.x + w; x++) for (let y = bl.y; y < bl.y + h; y++) b.add(`${x},${y}`);
    }
    for (const [, , , x, y] of v.debris) b.add(`${x},${y}`);
    for (const [px, py, pw, ph] of v.blocked) {
      for (let x = px; x < px + pw; x++) for (let y = py; y < py + ph; y++) b.add(`${x},${y}`);
    }
    return b;
  }

  private route(v: VillageState, from: [number, number], to: [number, number]): [number, number][] {
    const [lo, hi] = usableBounds(v.frame, v.size);
    const blocked = this.blocked(v);
    const key = (p: [number, number]) => `${p[0]},${p[1]}`;
    const prev = new Map<string, [number, number] | null>([[key(from), null]]);
    const q: [number, number][] = [from];
    while (q.length) {
      const cur = q.shift()!;
      if (cur[0] === to[0] && cur[1] === to[1]) break;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const n: [number, number] = [cur[0] + dx, cur[1] + dy];
        if (n[0] < lo || n[1] < lo || n[0] >= hi || n[1] >= hi || prev.has(key(n)) || blocked.has(key(n))) continue;
        prev.set(key(n), cur);
        q.push(n);
      }
    }
    if (!prev.has(key(to))) return [];
    const path: [number, number][] = [];
    let c: [number, number] | null | undefined = to;
    while (c) {
      path.unshift(c);
      c = prev.get(key(c));
    }
    return path;
  }

  private destinations(v: VillageState): [number, number][] {
    const defs = this.info.defs();
    const out: [number, number][] = [];
    for (const b of v.buildings) {
      const [w, h] = rotatedFootprint(defs[b.key].footprint, b.rotation);
      out.push([b.x + Math.floor(w / 2), b.y + h]); // in front of the door
    }
    const [lo, hi] = usableBounds(v.frame, v.size);
    for (let i = 0; i < 6; i++) out.push([Math.floor(rand(lo, hi)), Math.floor(rand(lo, hi))]);
    return out;
  }

  private async spawnWalkers(v: VillageState): Promise<void> {
    const houses = v.buildings.filter((b) => b.key === "house" && b.level > 0).length;
    const want = Math.min(10, 2 + houses * 2);
    if (this.walkers.length >= want || this.spawning) return;
    this.spawning = true;
    try {
      const cr = useSession.getState().config!.avatar.creator;
      const look: Appearance = {
        body: pick(cr.bodies), skin: pick(cr.skin_tones), hair_style: pick(cr.hair_styles),
        hair_color: pick(cr.hair_colors), eyes: pick(cr.eye_styles), eye_color: pick(cr.eye_colors),
        outfit: pick(cr.outfits), outfit_color: pick(cr.outfit_colors),
      };
      const strip = await composeAvatar(look);
      const base = Texture.from(strip);
      base.source.scaleMode = "nearest";
      const frames = Array.from({ length: strip.width / 16 }, (_, i) =>
        new Texture({ source: base.source, frame: new Rectangle(i * 16, 0, 16, 24) }));
      const start = pick(this.destinations(v));
      if (this.blocked(v).has(`${start[0]},${start[1]}`)) return;
      const [ox, oy] = this.info.origin();
      const sprite = new Sprite(frames[0]);
      sprite.anchor.set(0.5, 1);
      const w: Walker = {
        sprite, frames, path: [], x: (ox + start[0] + 0.5) * T, y: (oy + start[1] + 1) * T - 2, dir: "down",
        idle: rand(0, 2), t: Math.random() * 1000,
      };
      sprite.position.set(w.x, w.y);
      this.objects.addChild(sprite);
      this.walkers.push(w);
    } finally {
      this.spawning = false;
    }
  }

  private updateWalkers(dt: number, v: VillageState): void {
    const [ox, oy] = this.info.origin();
    const speed = 24;
    for (const w of this.walkers) {
      w.t += dt * 1000;
      if (w.path.length === 0) {
        w.idle -= dt;
        if (w.idle <= 0) {
          const from: [number, number] = [Math.floor(w.x / T) - ox, Math.floor((w.y - 1) / T) - oy];
          w.path = this.route(v, from, pick(this.destinations(v))).slice(1);
          w.idle = rand(1.5, 5);
        }
      } else {
        const [tx, ty] = w.path[0];
        const gx = (ox + tx + 0.5) * T;
        const gy = (oy + ty + 1) * T - 2;
        const dx = gx - w.x;
        const dy = gy - w.y;
        const d = Math.hypot(dx, dy);
        if (d < 1) {
          w.path.shift();
        } else {
          const step = Math.min(d, speed * dt);
          w.x += (dx / d) * step;
          w.y += (dy / d) * step;
          w.dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : dy > 0 ? "down" : "up";
        }
      }
      const f = frameFor(w.dir, w.path.length ? "walk" : "idle", w.t);
      w.sprite.texture = w.frames[f.index];
      w.sprite.scale.x = f.flip ? -1 : 1;
      w.sprite.position.set(Math.round(w.x), Math.round(w.y));
      w.sprite.zIndex = w.y;
    }
  }

  // ── ducks ──────────────────────────────────────────────────────────────────
  private pond(v: VillageState): { x0: number; y0: number; x1: number; y1: number } {
    const [ox, oy] = this.info.origin();
    const [px, py, pw, ph] = v.blocked[0];
    return { x0: (ox + px) * T + 6, y0: (oy + py) * T + 8, x1: (ox + px + pw) * T - 6, y1: (oy + py + ph) * T - 4 };
  }

  private updateDucks(dt: number, v: VillageState): void {
    const p = this.pond(v);
    while (this.ducks.length < 2) {
      const s = new AnimatedSprite([tex("fx.duck.0"), tex("fx.duck.1")]);
      s.anchor.set(0.5, 1);
      s.animationSpeed = 0.04;
      s.play();
      s.position.set(rand(p.x0, p.x1), rand(p.y0, p.y1));
      this.objects.addChild(s);
      this.ducks.push({ s, tx: s.x, ty: s.y });
    }
    for (const d of this.ducks) {
      const dx = d.tx - d.s.x;
      const dy = d.ty - d.s.y;
      const dist = Math.hypot(dx, dy);
      if (dist < 1.5) {
        if (Math.random() < dt * 0.4) {
          d.tx = rand(p.x0, p.x1);
          d.ty = rand(p.y0, p.y1);
        }
      } else {
        d.s.x += (dx / dist) * 7 * dt;
        d.s.y += (dy / dist) * 7 * dt;
        d.s.scale.x = dx > 0 ? -1 : 1;
      }
      d.s.zIndex = d.s.y;
    }
  }

  // ── butterflies ────────────────────────────────────────────────────────────
  private updateButterflies(dt: number): void {
    const view = this.info.view();
    const near = this.info.flowerSpots.filter((f) => f.x > view.x0 && f.x < view.x1 && f.y > view.y0 && f.y < view.y1);
    const want = Math.min(10, Math.max(3, Math.floor(near.length / 6)));
    while (this.butterflies.length < want && near.length) {
      const c = Math.floor(Math.random() * 4);
      const s = new AnimatedSprite([tex(`fx.butterfly${c}.0`), tex(`fx.butterfly${c}.1`)]);
      s.anchor.set(0.5);
      s.animationSpeed = 0.3;
      s.play();
      const f = pick(near);
      s.position.set(f.x, f.y - 12);
      this.fx.addChild(s);
      this.butterflies.push({ s, ax: f.x, ay: f.y - 12, ph: Math.random() * 10, retarget: rand(3, 7) });
    }
    for (const b of this.butterflies) {
      b.ph += dt;
      b.retarget -= dt;
      if (b.retarget < 0 && near.length) {
        const f = pick(near);
        b.ax = f.x;
        b.ay = f.y - 10;
        b.retarget = rand(4, 9);
      }
      const tx = b.ax + Math.sin(b.ph * 1.3) * 18 + Math.sin(b.ph * 3.1) * 6;
      const ty = b.ay + Math.cos(b.ph * 1.7) * 9 + Math.sin(b.ph * 5) * 3;
      b.s.x += (tx - b.s.x) * Math.min(1, dt * 1.5);
      b.s.y += (ty - b.s.y) * Math.min(1, dt * 1.5);
    }
  }

  // ── one-shot effects ───────────────────────────────────────────────────────
  private puff(names: string[], x: number, y: number, speed: number, life: number, drift: [number, number],
               parent: Container): void {
    const s = new AnimatedSprite(names.map((n) => tex(n)));
    s.anchor.set(0.5);
    s.position.set(x, y);
    s.animationSpeed = speed;
    s.loop = false;
    s.play();
    parent.addChild(s);
    const start = performance.now();
    const x0 = x;
    const y0 = y;
    const tick = () => {
      const p = (performance.now() - start) / (life * 1000);
      if (p >= 1 || s.destroyed) {
        if (!s.destroyed) s.destroy();
        return;
      }
      s.x = x0 + drift[0] * p + Math.sin(p * 9) * 1.5;
      s.y = y0 + drift[1] * p;
      s.alpha = p > 0.6 ? 1 - (p - 0.6) / 0.4 : 1;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  private updateEffects(dt: number): void {
    const view = this.info.view();
    const inView = (p: { x: number; y: number }) => p.x > view.x0 - 32 && p.x < view.x1 + 32 && p.y > view.y0 - 32 && p.y < view.y1 + 32;
    this.timers.smoke -= dt;
    if (this.timers.smoke <= 0) {
      this.timers.smoke = 0.7;
      for (const p of this.info.smokeSpots()) {
        if (inView(p)) this.puff(["fx.smoke.0", "fx.smoke.1", "fx.smoke.2", "fx.smoke.3", "fx.smoke.4"], p.x, p.y, 0.035, 3.2, [10, -26], this.fx);
      }
    }
    this.timers.glint -= dt;
    if (this.timers.glint <= 0) {
      this.timers.glint = 0.12;
      const water = [...this.info.waterTiles].map((k) => k.split(",").map(Number)).filter(([x, y]) =>
        inView({ x: x * T, y: y * T }));
      if (water.length) {
        const [x, y] = pick(water);
        this.puff(["fx.glint.0", "fx.glint.1", "fx.glint.2", "fx.glint.3"], x * T + rand(2, 14), y * T + rand(3, 13), 0.12, 0.6, [0, 0], this.fx);
      }
    }
    this.timers.leaf -= dt;
    if (this.timers.leaf <= 0) {
      this.timers.leaf = rand(0.4, 1.2);
      const trees = this.info.treeSpots.filter(inView);
      if (trees.length) {
        const t = pick(trees);
        this.puff(["fx.leaf.0", "fx.leaf.1", "fx.leaf.0", "fx.leaf.1"], t.x + rand(-10, 10), t.y + rand(-6, 6), 0.05, 3.5, [rand(10, 24), 26], this.fx);
      }
    }
    this.timers.bird -= dt;
    if (this.timers.bird <= 0) {
      this.timers.bird = rand(18, 35);
      const y = rand(view.y0 + 40, view.y1 - 120);
      const n = 3 + Math.floor(Math.random() * 3);
      for (let i = 0; i < n; i++) {
        const s = new AnimatedSprite([tex("fx.bird.0"), tex("fx.bird.1")]);
        s.animationSpeed = 0.12 + Math.random() * 0.05;
        s.play();
        s.position.set(view.x0 - 30 - i * 14, y + (i % 2) * 9 + i * 3);
        this.sky.addChild(s);
        const vx = 70 + Math.random() * 10;
        const tick = () => {
          if (s.destroyed) return;
          s.x += vx / 60;
          s.y -= 0.12;
          if (s.x > view.x1 + 60) s.destroy();
          else requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }
    }
  }

  update(dtMs: number): void {
    const dt = Math.min(dtMs, 50) / 1000;
    this.time += dt;
    const v = this.info.village();
    if (!v) return;
    void this.spawnWalkers(v);
    this.updateWalkers(dt, v);
    this.updateDucks(dt, v);
    this.updateButterflies(dt);
    this.updateEffects(dt);
  }

  /** A building or debris changed: walkers re-plan so nobody walks through new walls. */
  invalidate(): void {
    for (const w of this.walkers) w.path = [];
  }
}
