// Ambient life: ducks, butterflies, chimney smoke, water glints, falling leaves and passing birds.
// Purely cosmetic. (The strolling villagers became real ones in Phase 14: see villagers.ts.)
import { AnimatedSprite, Container } from "pixi.js";
import type { BuildingDef, VillageState } from "../api/types";
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


const rand = (a: number, b: number) => a + Math.random() * (b - a);
const pick = <X,>(xs: X[]) => xs[Math.floor(Math.random() * xs.length)];

export class Ambient {
  private ducks: { s: AnimatedSprite; tx: number; ty: number }[] = [];
  private butterflies: { s: AnimatedSprite; ax: number; ay: number; ph: number; retarget: number }[] = [];
  private timers = { smoke: 0, glint: 0, leaf: 0, bird: rand(4, 10) };
  private time = 0;

  constructor(
    private info: WorldInfo,
    private objects: Container, // depth-sorted world layer
    private fx: Container, // above objects
    private sky: Container, // birds
  ) {}

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
    // Phase 14: real villagers live in villagers.ts now; the ambient walkers retired
    this.updateDucks(dt, v);
    this.updateButterflies(dt);
    this.updateEffects(dt);
  }

  /** A building or debris changed (villagers re-plan in villagers.ts). */
  invalidate(): void {}
}
