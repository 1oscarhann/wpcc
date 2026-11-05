// Build Mode juice for Phase 6: buildings that form a combo shimmer where they touch, stations show
// their jobs (sparks + clang while working, a bobbing item when gear is ready), and discovering a combo
// is a moment: camera swoop, light burst, fanfare, then the reveal card.
import gsap from "gsap";
import { AnimatedSprite, Container, Graphics, Sprite, Text } from "pixi.js";
import type { ActiveCombo, BuildingDef, CraftJobView, VillageState } from "../api/types";
import { useCrafting } from "../state/crafting";
import { serverNow } from "../state/session";
import { itemIcon, itemName } from "./items";
import { rotatedFootprint } from "./placement";
import { safeDestroy } from "./safe";
import { sfx } from "./sfx";
import { iconTex, tex } from "./sprites";

const T = 16;
const INK = 0x2b1e2a;
const GOLD = 0xf7d66a;

export interface ComboHost {
  fx: Container;
  objects: Container;
  screen: Container;
  origin(): [number, number];
  defs(): Record<string, BuildingDef>;
  toScreen(wx: number, wy: number): { x: number; y: number };
  zoom(): number;
  view(id: string): { top: number; x: number; y: number; w: number } | undefined; // building sprite box (world px)
  sparkles(x: number, y: number): void;
  floatText(wx: number, wy: number, text: string, color: number, delay?: number, size?: number): void;
  focus(wx: number, wy: number): void;
  inView(wx: number, wy: number): boolean;
}

type Rect = [number, number, number, number];

function seams(a: Rect, b: Rect): [number, number, number, number] | null {
  const [ax, ay, aw, ah] = a;
  const [bx, by, bw, bh] = b;
  if (ax + aw === bx || bx + bw === ax) {
    const x = ax + aw === bx ? bx : ax;
    const y0 = Math.max(ay, by);
    const y1 = Math.min(ay + ah, by + bh);
    return y1 > y0 ? [x, y0, x, y1] : null;
  }
  if (ay + ah === by || by + bh === ay) {
    const y = ay + ah === by ? by : ay;
    const x0 = Math.max(ax, bx);
    const x1 = Math.min(ax + aw, bx + bw);
    return x1 > x0 ? [x0, y, x1, y] : null;
  }
  return null;
}

interface JobView {
  bar: Graphics;
  label: Text;
  ready: Sprite | null;
  sparkCd: number;
}

export class ComboFx {
  private labels = new Map<string, Text>(); // combo instance → floating name
  private moteCd = 0;
  private jobs = new Map<string, JobView>(); // station id → bar/label/ready
  private village: VillageState | null = null;

  constructor(private host: ComboHost) {}

  destroy(): void {
    for (const t of this.labels.values()) t.destroy();
    for (const j of this.jobs.values()) this.dropJob(j);
  }

  private rect(id: string, v: VillageState): Rect | null {
    const b = v.buildings.find((x) => x.id === id);
    const def = b && this.host.defs()[b.key];
    if (!b || !def) return null;
    const [w, h] = rotatedFootprint(def.footprint, b.rotation);
    const [ox, oy] = this.host.origin();
    return [ox + b.x, oy + b.y, w, h];
  }

  /** All touching edges inside one combo instance, in world tiles. */
  private comboSeams(c: ActiveCombo, v: VillageState): [number, number, number, number][] {
    const rects = c.buildings.map((id) => this.rect(id, v)).filter((r): r is Rect => r !== null);
    const out: [number, number, number, number][] = [];
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const s = seams(rects[i], rects[j]);
        if (s) out.push(s);
      }
    }
    return out;
  }

  sync(v: VillageState): void {
    this.village = v;
    const seen = new Set<string>();
    for (const c of v.combos) {
      const id = `${c.key}:${c.buildings.join(",")}`;
      seen.add(id);
      if (!this.labels.has(id)) {
        const t = new Text({
          text: `✦ ${c.name}`,
          style: { fontFamily: "Pixelify Sans", fontSize: 13, fill: GOLD, stroke: { color: INK, width: 3 }, fontWeight: "700" },
        });
        t.anchor.set(0.5, 1);
        this.host.screen.addChild(t);
        this.labels.set(id, t);
      }
    }
    for (const [id, t] of this.labels) {
      if (!seen.has(id)) {
        t.destroy();
        this.labels.delete(id);
      }
    }
  }

  update(dms: number): void {
    const v = this.village;
    if (!v) return;
    // golden motes rise where combo buildings touch
    this.moteCd -= dms;
    const spawn = this.moteCd <= 0;
    if (spawn) this.moteCd = 140;
    const placed: { x: number; y: number; w: number; h: number }[] = [];
    for (const c of v.combos) {
      const ss = this.comboSeams(c, v);
      const id = `${c.key}:${c.buildings.join(",")}`;
      const label = this.labels.get(id);
      if (label && ss.length) {
        // the name floats above the highest building of the group
        const tops = c.buildings.map((b) => this.host.view(b)).filter((x) => x !== undefined);
        const [x0, y0, x1] = ss[0];
        const cx = ((x0 + x1) / 2) * T;
        const top = Math.min(...tops.map((t) => t!.top), y0 * T);
        const p = this.host.toScreen(cx, top - 8);
        // combos that share a building would print on top of each other: stack them
        let y = p.y;
        const w = label.width;
        const h = label.height + 2;
        for (let guard = 0; guard < 6; guard++) {
          const hit = placed.find((o) => Math.abs(o.x - p.x) < (o.w + w) / 2 && Math.abs(o.y - y) < h);
          if (!hit) break;
          y = hit.y - h;
        }
        placed.push({ x: p.x, y, w, h });
        label.position.set(Math.round(p.x), Math.round(y));
        label.visible = this.host.zoom() >= 2.5;
        label.alpha = 0.85 + Math.sin(performance.now() / 500) * 0.15;
      }
      if (!spawn) continue;
      for (const [x0, y0, x1, y1] of ss) {
        if (Math.random() > 0.55) continue;
        const t = Math.random();
        const wx = (x0 + (x1 - x0) * t) * T;
        const wy = (y0 + (y1 - y0) * t) * T;
        if (!this.host.inView(wx, wy)) continue;
        this.mote(wx, wy);
      }
    }
    this.updateJobs(v, dms);
  }

  private mote(wx: number, wy: number): void {
    const g = new Graphics().rect(-0.5, -0.5, 1.5, 1.5).fill({ color: Math.random() < 0.5 ? GOLD : 0xfff1b0 });
    g.position.set(wx + (Math.random() - 0.5) * 6, wy - Math.random() * 10);
    g.zIndex = 1e6;
    g.alpha = 0;
    this.host.fx.addChild(g);
    const rise = 12 + Math.random() * 14;
    gsap.timeline({ onComplete: () => safeDestroy(g) })
      .to(g, { alpha: 1, duration: 0.25 })
      .to(g, { y: g.y - rise, x: g.x + (Math.random() - 0.5) * 6, duration: 1.3, ease: "sine.out" }, 0)
      .to(g, { alpha: 0, duration: 0.4 }, 0.9);
  }

  // ── station jobs ─────────────────────────────────────────────────────────
  private dropJob(j: JobView): void {
    j.bar.destroy();
    j.label.destroy();
    if (j.ready) safeDestroy(j.ready);
  }

  private updateJobs(v: VillageState, dms: number): void {
    const now = serverNow();
    const byStation = new Map<string, CraftJobView>();
    for (const j of v.jobs) {
      const cur = byStation.get(j.station_id);
      if (!cur || j.completes_at_ms < cur.completes_at_ms) byStation.set(j.station_id, j);
    }
    for (const [sid, jv] of this.jobs) {
      if (!byStation.has(sid)) {
        this.dropJob(jv);
        this.jobs.delete(sid);
      }
    }
    for (const [sid, job] of byStation) {
      const box = this.host.view(sid);
      if (!box) continue;
      let jv = this.jobs.get(sid);
      if (!jv) {
        const bar = new Graphics();
        bar.zIndex = 1e6;
        this.host.fx.addChild(bar);
        const label = new Text({
          text: "",
          style: { fontFamily: "Pixelify Sans", fontSize: 13, fill: 0xfaf2dd, stroke: { color: INK, width: 3 }, fontWeight: "600" },
        });
        label.anchor.set(0.5, 1);
        this.host.screen.addChild(label);
        jv = { bar, label, ready: null, sparkCd: Math.random() * 600 };
        this.jobs.set(sid, jv);
      }
      const total = job.completes_at_ms - job.started_at_ms;
      const left = Math.max(0, job.completes_at_ms - now);
      const p = total > 0 ? 1 - left / total : 1;
      const done = left <= 0;
      const bw = box.w - 10;
      const top = box.top + 10;
      jv.bar.clear();
      if (!done) {
        jv.bar.rect(box.x + 5, top, bw, 5).fill({ color: INK }).rect(box.x + 6, top + 1, Math.max(0, (bw - 2) * p), 3).fill({ color: 0xf08a33 });
      }
      const name = job.kind === "gear" ? itemName(job.recipe, job.tier) : `${itemName(job.recipe)} ×${job.quantity}`;
      const s = Math.ceil(left / 1000);
      jv.label.text = done ? (job.kind === "gear" ? `${name} ready!` : name) : `${name} · ${s >= 60 ? `${Math.floor(s / 60)}m ` : ""}${s % 60}s`;
      const lp = this.host.toScreen(box.x + box.w / 2, top - 2);
      jv.label.position.set(Math.round(lp.x), Math.round(lp.y));
      jv.label.style.fill = done ? GOLD : 0xfaf2dd;
      // hammer sparks + clang while it works
      if (!done) {
        jv.sparkCd -= dms;
        if (jv.sparkCd <= 0) {
          jv.sparkCd = 650 + Math.random() * 250;
          const sx = box.x + box.w * (0.35 + Math.random() * 0.3);
          const sy = box.y - 6;
          if (this.host.inView(sx, sy)) {
            const a = new AnimatedSprite([0, 1, 2].map((i) => tex(`fx.hit.${i}`)));
            a.anchor.set(0.5);
            a.scale.set(0.6);
            a.position.set(sx, sy);
            a.zIndex = 1e6;
            a.animationSpeed = 0.5;
            a.loop = false;
            a.onComplete = () => safeDestroy(a);
            this.host.fx.addChild(a);
            a.play();
            sfx(job.kind === "gear" || job.recipe === "ingots" ? "clang" : "saw");
          }
        }
      }
      // gear waiting to be collected bobs above the station
      if (done && job.kind === "gear" && !jv.ready) {
        const r = new Sprite(iconTex(itemIcon(job.recipe, job.tier)));
        r.anchor.set(0.5, 1);
        r.zIndex = 1e6;
        r.position.set(box.x + box.w / 2, top - 4);
        this.host.fx.addChild(r);
        gsap.to(r, { y: r.y - 5, duration: 0.6, yoyo: true, repeat: -1, ease: "sine.inOut" });
        this.host.sparkles(r.x, r.y - 8);
        sfx("pickup");
        jv.ready = r;
      }
    }
  }

  // ── the discovery moment ─────────────────────────────────────────────────
  celebrate(c: ActiveCombo, v: VillageState): void {
    const rects = c.buildings.map((id) => this.rect(id, v)).filter((r): r is Rect => r !== null);
    if (!rects.length) return;
    const x0 = Math.min(...rects.map((r) => r[0]));
    const y0 = Math.min(...rects.map((r) => r[1]));
    const x1 = Math.max(...rects.map((r) => r[0] + r[2]));
    const y1 = Math.max(...rects.map((r) => r[1] + r[3]));
    const cx = ((x0 + x1) / 2) * T;
    const cy = ((y0 + y1) / 2) * T;
    this.host.focus(cx, cy - 10);
    window.setTimeout(() => {
      sfx("fanfare");
      // a ring of light that expands from the shared edges
      const ring = new Graphics();
      ring.position.set(cx, cy - 8);
      ring.zIndex = 1e6;
      this.host.fx.addChild(ring);
      const st = { r: 4, a: 1 };
      gsap.to(st, {
        r: Math.max(x1 - x0, y1 - y0) * T * 0.9,
        a: 0,
        duration: 1.1,
        ease: "power2.out",
        onUpdate: () => {
          ring.clear();
          ring.circle(0, 0, st.r).stroke({ width: 3, color: GOLD, alpha: st.a });
          ring.circle(0, 0, st.r * 0.7).stroke({ width: 1, color: 0xfff1b0, alpha: st.a * 0.8 });
        },
        onComplete: () => safeDestroy(ring),
      });
      // light rays
      const rays = new Graphics();
      rays.position.set(cx, cy - 8);
      rays.zIndex = 1e6;
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2;
        rays.moveTo(Math.cos(a) * 6, Math.sin(a) * 6).lineTo(Math.cos(a) * 60, Math.sin(a) * 60);
      }
      rays.stroke({ width: 2, color: 0xfff1b0, alpha: 0.8 });
      this.host.fx.addChild(rays);
      gsap.fromTo(rays.scale, { x: 0.2, y: 0.2 }, { x: 1.4, y: 1.4, duration: 0.9, ease: "power3.out" });
      gsap.to(rays, { alpha: 0, rotation: 0.4, duration: 0.9, onComplete: () => safeDestroy(rays) });
      for (const r of rects) this.host.sparkles((r[0] + r[2] / 2) * T, (r[1] + r[3] / 2) * T - 12);
      for (let i = 0; i < 40; i++) window.setTimeout(() => this.mote(cx + (Math.random() - 0.5) * (x1 - x0) * T, cy), i * 25);
      this.host.floatText(cx, cy - 30, "Combo discovered!", GOLD, 0, 22);
      window.setTimeout(() => {
        useCrafting.getState().set({
          discovery: { key: c.key, name: c.name, buildings: c.buildings.map((id) => v.buildings.find((b) => b.id === id)?.key ?? ""), unlocks: c.unlocks },
        });
      }, 1100);
    }, 650);
  }
}
