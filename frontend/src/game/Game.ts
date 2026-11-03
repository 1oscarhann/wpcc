// Build Mode renderer (PixiJS v8, imperative — D-019). React only renders the DOM HUD on top.
import { decode } from "@msgpack/msgpack";
import gsap from "gsap";
import { AnimatedSprite, Application, Container, Graphics, Sprite, Text } from "pixi.js";
import type { BuildingDef, BuildingState, VillageState } from "../api/types";
import { serverNow, useSession } from "../state/session";
import { onVillageChange, useVillage, type MapMeta } from "../state/village";
import { localPlacementError, rotatedFootprint, usableBounds } from "./placement";
import { buildingLook, loadWorldAtlas, tex } from "./sprites";

const T = 16;
const ZOOMS = [2, 3, 4];
const INK = 0x2b1e2a;

interface BuildingView {
  id: string;
  root: Container; // positioned at the footprint's top-left
  body: Container; // pivot at the sprite's bottom-centre, for squash & stretch
  sprite: Sprite;
  anchorTop: number;
  key: string;
  level: number;
  state: string;
  rotation: number;
  x: number;
  y: number;
  bar: Graphics;
  label: Text;
}

export class Game {
  app = new Application();
  private world = new Container();
  private ground = new Container();
  private below = new Container(); // plot border, footprint highlights
  private objects = new Container(); // trees + buildings, depth-sorted
  private above = new Container(); // ghost footprint
  private fx = new Container();
  private screen = new Container(); // unscaled labels
  private cam = { x: 0, y: 0, zoom: 3, vx: 0, vy: 0 };
  private zoomTween: gsap.core.Tween | null = null;
  private chunks = new Map<string, Container | "loading">();
  private views = new Map<string, BuildingView>();
  private ghost: { sprite: Sprite; foot: Graphics } | null = null;
  private plotBorder = new Graphics();
  private selectRing = new Graphics();
  private map: MapMeta | null = null;
  private defs: Record<string, BuildingDef> = {};
  private origin: [number, number] = [0, 0];
  private unsub: (() => void)[] = [];
  private pointers = new Map<number, { x: number; y: number; sx: number; sy: number; t: number }>();
  private dragging = false;
  private pinchDist = 0;
  private keys = new Set<string>();
  private destroyed = false;
  private hoverTile: [number, number] | null = null;
  touchMode = matchMedia("(pointer: coarse)").matches;

  constructor(private host: HTMLElement) {}

  async init(): Promise<void> {
    await this.app.init({
      resizeTo: this.host,
      background: "#2f6b3a",
      antialias: false,
      roundPixels: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
      autoDensity: true,
    });
    if (this.destroyed) return;
    this.host.appendChild(this.app.canvas);
    this.app.canvas.style.touchAction = "none";
    await Promise.all([loadWorldAtlas(), document.fonts.load('16px "Pixelify Sans"').catch(() => undefined)]);
    this.defs = useSession.getState().config!.buildings;
    this.map = await useVillage.getState().fetchMap();
    this.objects.sortableChildren = true;
    this.world.addChild(this.ground, this.below, this.objects, this.above, this.fx);
    this.below.addChild(this.plotBorder, this.selectRing);
    this.app.stage.addChild(this.world, this.screen);

    const v = useVillage.getState().village;
    if (v) this.onVillage(null, v, true);
    this.unsub.push(onVillageChange((prev, next) => this.onVillage(prev, next, false)));
    this.unsub.push(
      useVillage.subscribe((s, p) => {
        if (s.placing !== p.placing) this.syncGhost();
        if (s.selectedId !== p.selectedId) this.syncSelection();
      }),
    );
    this.bindInput();
    this.app.ticker.add((t) => this.tick(t.deltaMS));
    if (import.meta.env.DEV) (window as unknown as { __hfGame?: Game }).__hfGame = this; // for screenshot tests
  }

  destroy(): void {
    this.destroyed = true;
    this.unsub.forEach((u) => u());
    this.unbind?.();
    try {
      this.app.destroy(true, { children: true });
    } catch {
      /* init may not have finished */
    }
  }

  // ── camera ────────────────────────────────────────────────────────────────
  private applyCamera(): void {
    const { width, height } = this.app.screen;
    const z = this.cam.zoom;
    this.world.scale.set(z);
    this.world.position.set(Math.round(width / 2 - this.cam.x * z), Math.round(height / 2 - this.cam.y * z));
  }

  private clampCamera(): void {
    const v = useVillage.getState().village;
    if (!v) return;
    const margin = 28 * T;
    const x0 = this.origin[0] * T - margin;
    const y0 = this.origin[1] * T - margin;
    const x1 = (this.origin[0] + v.frame) * T + margin;
    const y1 = (this.origin[1] + v.frame) * T + margin;
    this.cam.x = Math.max(x0, Math.min(x1, this.cam.x));
    this.cam.y = Math.max(y0, Math.min(y1, this.cam.y));
  }

  zoomBy(dir: number, focus?: { x: number; y: number }): void {
    const cur = ZOOMS.indexOf(Math.round(this.cam.zoom));
    const next = ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, (cur < 0 ? 1 : cur) + dir))];
    if (next === this.cam.zoom) return;
    const f = focus ?? { x: this.app.screen.width / 2, y: this.app.screen.height / 2 };
    const before = this.screenToWorld(f.x, f.y);
    this.zoomTween?.kill();
    const state = { z: this.cam.zoom };
    this.zoomTween = gsap.to(state, {
      z: next,
      duration: 0.22,
      ease: "power2.out",
      onUpdate: () => {
        this.cam.zoom = state.z;
        // keep the point under the cursor fixed while zooming
        const { width, height } = this.app.screen;
        this.cam.x = before.x - (f.x - width / 2) / state.z;
        this.cam.y = before.y - (f.y - height / 2) / state.z;
        this.clampCamera();
      },
      onComplete: () => (this.cam.zoom = next),
    });
  }

  private screenToWorld(sx: number, sy: number): { x: number; y: number } {
    return { x: (sx - this.world.x) / this.world.scale.x, y: (sy - this.world.y) / this.world.scale.y };
  }

  private screenToFrameTile(sx: number, sy: number): [number, number] {
    const w = this.screenToWorld(sx, sy);
    return [Math.floor(w.x / T) - this.origin[0], Math.floor(w.y / T) - this.origin[1]];
  }

  frameTileToScreen(tx: number, ty: number): { x: number; y: number } {
    return {
      x: this.world.x + (this.origin[0] + tx) * T * this.cam.zoom,
      y: this.world.y + (this.origin[1] + ty) * T * this.cam.zoom,
    };
  }

  centerOnVillage(): void {
    const v = useVillage.getState().village;
    if (!v) return;
    const th = v.buildings.find((b) => b.key === "town_hall");
    const cx = th ? th.x + 1.5 : v.frame / 2;
    const cy = th ? th.y + 2.5 : v.frame / 2;
    this.cam.x = (this.origin[0] + cx) * T;
    this.cam.y = (this.origin[1] + cy) * T;
    this.cam.zoom = 2; // Build overview: the whole starting plot fits on a laptop screen
  }

  // ── frame loop ────────────────────────────────────────────────────────────
  private tick(dms: number): void {
    const dt = Math.min(dms, 50) / 1000;
    const speed = 420 / this.cam.zoom;
    let kx = 0;
    let ky = 0;
    if (this.keys.has("a") || this.keys.has("arrowleft")) kx -= 1;
    if (this.keys.has("d") || this.keys.has("arrowright")) kx += 1;
    if (this.keys.has("w") || this.keys.has("arrowup")) ky -= 1;
    if (this.keys.has("s") || this.keys.has("arrowdown")) ky += 1;
    this.cam.x += kx * speed * dt;
    this.cam.y += ky * speed * dt;
    if (!this.dragging) {
      // inertia after a drag
      this.cam.x += this.cam.vx * dt;
      this.cam.y += this.cam.vy * dt;
      const decay = Math.pow(0.0025, dt);
      this.cam.vx *= decay;
      this.cam.vy *= decay;
    }
    this.clampCamera();
    this.applyCamera();
    this.loadVisibleChunks();
    this.updateTimers();
  }

  // ── terrain chunks ────────────────────────────────────────────────────────
  private loadVisibleChunks(): void {
    const m = this.map;
    if (!m) return;
    const { width, height } = this.app.screen;
    const tl = this.screenToWorld(0, 0);
    const br = this.screenToWorld(width, height);
    const cs = m.chunk_size * T;
    const n = m.size / m.chunk_size;
    const want: string[] = [];
    for (let cy = Math.floor(tl.y / cs) - 1; cy <= Math.floor(br.y / cs) + 1; cy++) {
      for (let cx = Math.floor(tl.x / cs) - 1; cx <= Math.floor(br.x / cs) + 1; cx++) {
        if (cx < 0 || cy < 0 || cx >= n || cy >= n) continue;
        const id = `${cx}_${cy}`;
        if (!this.chunks.has(id)) want.push(id);
      }
    }
    if (!want.length) return;
    for (const id of want) this.chunks.set(id, "loading");
    for (let i = 0; i < want.length; i += 24) this.fetchChunks(want.slice(i, i + 24));
  }

  private async fetchChunks(ids: string[]): Promise<void> {
    const m = this.map!;
    try {
      const res = await fetch(`/api/realms/${m.realm_id}/chunks?ids=${ids.join(";")}`, { credentials: "same-origin" });
      if (!res.ok) throw new Error(String(res.status));
      const data = decode(new Uint8Array(await res.arrayBuffer())) as {
        chunks: { cx: number; cy: number; ground: Uint8Array; objects: number[][] }[];
      };
      if (this.destroyed) return;
      for (const ch of data.chunks) this.buildChunk(ch);
    } catch {
      for (const id of ids) this.chunks.delete(id); // retry next frame
    }
  }

  private buildChunk(ch: { cx: number; cy: number; ground: Uint8Array; objects: number[][] }): void {
    const m = this.map!;
    const cs = m.chunk_size;
    const c = new Container();
    c.position.set(ch.cx * cs * T, ch.cy * cs * T);
    for (let i = 0; i < ch.ground.length; i++) {
      const s = new Sprite(tex(m.tile_names[ch.ground[i]]));
      s.position.set((i % cs) * T, Math.floor(i / cs) * T);
      c.addChild(s);
    }
    c.cacheAsTexture(true);
    this.ground.addChild(c);
    this.chunks.set(`${ch.cx}_${ch.cy}`, c);
    const v = useVillage.getState().village;
    const [lo, hi] = v ? usableBounds(v.frame, v.size) : [0, 0];
    for (const [lx, ly, k] of ch.objects) {
      const name = m.object_names[k];
      // nature in the reserved ring of our plot disappears as the plot expands over it
      const fx = ch.cx * cs + lx - this.origin[0];
      const fy = ch.cy * cs + ly - this.origin[1];
      if (v && fx >= lo - 1 && fx < hi + 1 && fy >= lo - 1 && fy < hi + 1) continue;
      const s = new Sprite(tex(name));
      s.anchor.set(0.5, 1);
      const wx = (ch.cx * cs + lx) * T + T / 2;
      const wy = (ch.cy * cs + ly) * T + T - 1;
      s.position.set(wx, wy);
      s.zIndex = wy;
      this.objects.addChild(s);
    }
  }

  // ── village ───────────────────────────────────────────────────────────────
  private onVillage(prev: VillageState | null, next: VillageState, first: boolean): void {
    if (first || !prev) {
      this.origin = next.origin;
      this.drawPlotBorder(next);
      this.centerOnVillage();
    } else if (prev.size !== next.size) {
      this.drawPlotBorder(next);
    }
    const seen = new Set<string>();
    for (const b of next.buildings) {
      seen.add(b.id);
      const view = this.views.get(b.id);
      if (!view) {
        this.views.set(b.id, this.createView(b));
        if (!first) this.juicePop(b.id, true);
      } else {
        const levelUp = b.level > view.level;
        if (levelUp || b.state !== view.state || b.rotation !== view.rotation || b.x !== view.x || b.y !== view.y) {
          this.updateView(view, b);
          if (levelUp && !first) this.juicePop(b.id, false);
        }
      }
    }
    for (const [id, view] of this.views) {
      if (!seen.has(id)) {
        this.dust(view.root.x + view.sprite.texture.width / 2, view.root.y + view.sprite.texture.height - view.anchorTop - 2);
        view.root.destroy({ children: true });
        view.label.destroy();
        this.views.delete(id);
      }
    }
    this.syncSelection();
    this.syncGhost();
  }

  private drawPlotBorder(v: VillageState): void {
    const g = this.plotBorder;
    g.clear();
    const [lo, hi] = usableBounds(v.frame, v.size);
    const x0 = (this.origin[0] + lo) * T;
    const y0 = (this.origin[1] + lo) * T;
    const len = (hi - lo) * T;
    // dashed wooden boundary with posts at the corners
    for (let i = 0; i < len; i += 8) {
      g.rect(x0 + i, y0 - 1, 5, 2).rect(x0 + i, y0 + len - 1, 5, 2).rect(x0 - 1, y0 + i, 2, 5).rect(x0 + len - 1, y0 + i, 2, 5);
    }
    g.fill({ color: 0xf3e8cc, alpha: 0.55 });
    for (const [px, py] of [[x0, y0], [x0 + len, y0], [x0, y0 + len], [x0 + len, y0 + len]]) {
      g.rect(px - 2, py - 3, 4, 6).fill({ color: 0x7e4e31 }).stroke({ width: 1, color: INK });
    }
  }

  private createView(b: BuildingState): BuildingView {
    const root = new Container();
    const body = new Container();
    const sprite = new Sprite();
    body.addChild(sprite);
    root.addChild(body);
    const bar = new Graphics();
    root.addChild(bar);
    const label = new Text({
      text: "",
      style: { fontFamily: "Pixelify Sans", fontSize: 15, fill: 0xfaf2dd, stroke: { color: INK, width: 4 }, fontWeight: "600" },
    });
    label.anchor.set(0.5, 1);
    this.screen.addChild(label);
    this.objects.addChild(root);
    const view: BuildingView = {
      id: b.id, root, body, sprite, anchorTop: 0, key: b.key, level: -1, state: "", rotation: -1, x: -1, y: -1, bar, label,
    };
    this.updateView(view, b);
    return view;
  }

  private updateView(view: BuildingView, b: BuildingState): void {
    const def = this.defs[b.key];
    const look = buildingLook(b.key, def.footprint, b);
    const [, h] = rotatedFootprint(def.footprint, b.rotation);
    const t = tex(look.name);
    view.sprite.texture = t;
    view.sprite.scale.x = look.mirror ? -1 : 1;
    view.sprite.position.set(look.mirror ? t.width : 0, 0);
    view.body.pivot.set(t.width / 2, t.height);
    view.body.position.set(t.width / 2, t.height - look.anchorTop);
    view.anchorTop = look.anchorTop;
    view.root.position.set((this.origin[0] + b.x) * T, (this.origin[1] + b.y) * T);
    view.root.zIndex = (this.origin[1] + b.y + h) * T;
    Object.assign(view, { key: b.key, level: b.level, state: b.state, rotation: b.rotation, x: b.x, y: b.y });
  }

  private updateTimers(): void {
    const v = useVillage.getState().village;
    if (!v) return;
    const now = serverNow();
    for (const b of v.buildings) {
      const view = this.views.get(b.id);
      if (!view) continue;
      const working = b.state !== "active" && b.completes_at_ms && b.started_at_ms;
      view.bar.clear();
      view.label.visible = Boolean(working);
      if (!working) continue;
      const total = b.completes_at_ms! - b.started_at_ms!;
      const left = Math.max(0, b.completes_at_ms! - now);
      const p = total > 0 ? 1 - left / total : 1;
      const [w] = rotatedFootprint(this.defs[b.key].footprint, b.rotation);
      const bw = w * T - 6;
      // sprites carry ~12 px of transparent headroom for pennants; sit the bar just above the roof
      const top = -view.anchorTop + 6;
      view.bar.rect(3, top, bw, 5).fill({ color: INK }).rect(4, top + 1, Math.max(0, (bw - 2) * p), 3).fill({ color: 0xf7d66a });
      const s = Math.ceil(left / 1000);
      view.label.text = left <= 0 ? "Done!" : s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
      const pos = this.frameTileToScreen(b.x + w / 2, b.y);
      view.label.position.set(Math.round(pos.x), Math.round(pos.y + (top - 2) * this.cam.zoom));
    }
  }

  // ── juice ─────────────────────────────────────────────────────────────────
  private juicePop(id: string, placed: boolean): void {
    const view = this.views.get(id);
    if (!view) return;
    const b = view.body;
    gsap.killTweensOf(b.scale);
    gsap
      .timeline()
      .fromTo(b.scale, { x: 0.7, y: 1.35 }, { x: 1.15, y: 0.85, duration: 0.12, ease: "power2.out" })
      .to(b.scale, { x: 0.95, y: 1.06, duration: 0.1 })
      .to(b.scale, { x: 1, y: 1, duration: 0.16, ease: "back.out(3)" });
    const w = view.sprite.texture.width;
    const footBottom = view.root.y + view.sprite.texture.height - view.anchorTop;
    this.dust(view.root.x + w / 2, footBottom - 2);
    if (!placed) this.sparkles(view.root.x + w / 2, view.root.y - view.anchorTop / 2);
  }

  private dust(x: number, y: number): void {
    for (const dx of [-10, 0, 10]) {
      const a = new AnimatedSprite([0, 1, 2, 3, 4].map((i) => tex(`fx.dust.${i}`)));
      a.anchor.set(0.5, 0.75);
      a.position.set(x + dx, y);
      a.animationSpeed = 0.28;
      a.loop = false;
      a.onComplete = () => a.destroy();
      this.fx.addChild(a);
      a.play();
    }
  }

  private sparkles(x: number, y: number): void {
    for (let i = 0; i < 7; i++) {
      const s = new AnimatedSprite([0, 1, 2, 3, 2, 1].map((k) => tex(`fx.sparkle.${k}`)));
      s.anchor.set(0.5);
      s.position.set(x, y);
      s.animationSpeed = 0.3;
      this.fx.addChild(s);
      s.play();
      const a = (i / 7) * Math.PI * 2;
      gsap.to(s, {
        x: x + Math.cos(a) * 22,
        y: y + Math.sin(a) * 14 - 8,
        alpha: 0,
        duration: 0.7,
        ease: "power2.out",
        onComplete: () => s.destroy(),
      });
    }
  }

  // ── selection & ghost ────────────────────────────────────────────────────
  private syncSelection(): void {
    const g = this.selectRing;
    g.clear();
    const { selectedId, village } = useVillage.getState();
    const b = village?.buildings.find((x) => x.id === selectedId);
    if (!b) return;
    const [w, h] = rotatedFootprint(this.defs[b.key].footprint, b.rotation);
    const x = (this.origin[0] + b.x) * T;
    const y = (this.origin[1] + b.y) * T;
    g.rect(x, y, w * T, h * T).fill({ color: 0xf7d66a, alpha: 0.18 });
    for (let i = 0; i < w * T; i += 6) g.rect(x + i, y - 1, 3, 2).rect(x + i, y + h * T - 1, 3, 2);
    for (let i = 0; i < h * T; i += 6) g.rect(x - 1, y + i, 2, 3).rect(x + w * T - 1, y + i, 2, 3);
    g.fill({ color: 0xf7d66a });
    const view = this.views.get(b.id);
    if (view) {
      gsap.killTweensOf(view.body.scale);
      gsap.fromTo(view.body.scale, { x: 1.06, y: 0.94 }, { x: 1, y: 1, duration: 0.3, ease: "elastic.out(1.2, 0.4)" });
    }
  }

  syncGhost(): void {
    const { placing, village } = useVillage.getState();
    if (!placing || !village) {
      this.ghost?.sprite.destroy();
      this.ghost?.foot.destroy();
      this.ghost = null;
      return;
    }
    if (!this.ghost) {
      this.ghost = { sprite: new Sprite(), foot: new Graphics() };
      this.ghost.sprite.alpha = 0.82;
      this.above.addChild(this.ghost.foot, this.ghost.sprite);
    }
    const def = this.defs[placing.key];
    const tx = placing.x ?? this.hoverTile?.[0];
    const ty = placing.y ?? this.hoverTile?.[1];
    const { sprite, foot } = this.ghost;
    if (tx === undefined || ty === undefined) {
      sprite.visible = foot.visible = false;
      return;
    }
    sprite.visible = foot.visible = true;
    const look = buildingLook(placing.key, def.footprint, { rotation: placing.rotation, level: 1, state: "active" });
    const [w, h] = rotatedFootprint(def.footprint, placing.rotation);
    sprite.texture = tex(look.name);
    sprite.scale.x = look.mirror ? -1 : 1;
    const x = (this.origin[0] + tx) * T;
    const y = (this.origin[1] + ty) * T;
    sprite.position.set(x + (look.mirror ? sprite.texture.width : 0), y - look.anchorTop);
    const err = localPlacementError(village, this.defs, placing.key, tx, ty, placing.rotation, placing.moveId);
    const color = err ? 0xe05a47 : 0x8fc95c;
    foot.clear();
    // faint build grid around the ghost + the footprint itself
    for (let gy = -3; gy < h + 3; gy++) {
      for (let gx = -3; gx < w + 3; gx++) foot.rect(x + gx * T, y + gy * T, T, T);
    }
    foot.stroke({ width: 0.5, color: 0xfaf2dd, alpha: 0.18 });
    foot.rect(x, y, w * T, h * T).fill({ color, alpha: 0.35 }).stroke({ width: 1, color, alpha: 0.95 });
    sprite.tint = err ? 0xffb0a0 : 0xffffff;
    useGhostState.error = err;
  }

  // ── input ────────────────────────────────────────────────────────────────
  private unbind: (() => void) | null = null;

  private bindInput(): void {
    const el = this.app.canvas;
    const down = (e: PointerEvent) => {
      el.setPointerCapture(e.pointerId);
      this.pointers.set(e.pointerId, { x: e.offsetX, y: e.offsetY, sx: e.offsetX, sy: e.offsetY, t: performance.now() });
      this.cam.vx = this.cam.vy = 0;
      if (this.pointers.size === 2) {
        const [a, b] = [...this.pointers.values()];
        this.pinchDist = Math.hypot(a.x - b.x, a.y - b.y);
      }
    };
    const move = (e: PointerEvent) => {
      const p = this.pointers.get(e.pointerId);
      if (!p) {
        if (!this.touchMode) this.hover(e.offsetX, e.offsetY);
        return;
      }
      const dx = e.offsetX - p.x;
      const dy = e.offsetY - p.y;
      const dtm = Math.max(1, performance.now() - p.t);
      p.x = e.offsetX;
      p.y = e.offsetY;
      p.t = performance.now();
      if (this.pointers.size === 2) {
        const [a, b] = [...this.pointers.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (this.pinchDist && Math.abs(d - this.pinchDist) > 40) {
          this.zoomBy(d > this.pinchDist ? 1 : -1, { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
          this.pinchDist = d;
        }
        this.dragging = true;
        return;
      }
      if (!this.dragging && Math.hypot(e.offsetX - p.sx, e.offsetY - p.sy) > 6) this.dragging = true;
      if (this.dragging) {
        this.cam.x -= dx / this.cam.zoom;
        this.cam.y -= dy / this.cam.zoom;
        this.cam.vx = (-dx / this.cam.zoom / dtm) * 1000;
        this.cam.vy = (-dy / this.cam.zoom / dtm) * 1000;
      } else if (!this.touchMode) this.hover(e.offsetX, e.offsetY);
    };
    const up = (e: PointerEvent) => {
      const p = this.pointers.get(e.pointerId);
      this.pointers.delete(e.pointerId);
      if (!p) return;
      if (!this.dragging && this.pointers.size === 0) this.tap(e.offsetX, e.offsetY);
      if (this.pointers.size === 0) {
        this.dragging = false;
        if (performance.now() - p.t > 80) this.cam.vx = this.cam.vy = 0;
      }
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      this.zoomBy(e.deltaY < 0 ? 1 : -1, { x: e.offsetX, y: e.offsetY });
    };
    const keydown = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      const k = e.key.toLowerCase();
      this.keys.add(k);
      const store = useVillage.getState();
      if (k === "r") store.rotateGhost();
      if (k === "escape") {
        store.startPlacing(null);
        store.select(null);
      }
      if (k === "enter" && store.placing) store.confirmPlacement();
      if (k === "+" || k === "=") this.zoomBy(1);
      if (k === "-") this.zoomBy(-1);
    };
    const keyup = (e: KeyboardEvent) => this.keys.delete(e.key.toLowerCase());
    const blur = () => this.keys.clear();
    const ctx = (e: MouseEvent) => {
      e.preventDefault();
      useVillage.getState().startPlacing(null);
    };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.addEventListener("wheel", wheel, { passive: false });
    el.addEventListener("contextmenu", ctx);
    window.addEventListener("keydown", keydown);
    window.addEventListener("keyup", keyup);
    window.addEventListener("blur", blur);
    this.unbind = () => {
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      el.removeEventListener("wheel", wheel);
      el.removeEventListener("contextmenu", ctx);
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("keyup", keyup);
      window.removeEventListener("blur", blur);
    };
  }

  private ghostTileFor(sx: number, sy: number): [number, number] {
    const store = useVillage.getState();
    const p = store.placing!;
    const [w, h] = rotatedFootprint(this.defs[p.key].footprint, p.rotation);
    const [tx, ty] = this.screenToFrameTile(sx, sy);
    // the pointer holds the centre of the footprint
    return [tx - Math.floor((w - 1) / 2), ty - Math.floor((h - 1) / 2)];
  }

  private hover(sx: number, sy: number): void {
    const store = useVillage.getState();
    if (!store.placing) return;
    const [tx, ty] = this.ghostTileFor(sx, sy);
    this.hoverTile = [tx, ty];
    store.setGhost(tx, ty);
  }

  private tap(sx: number, sy: number): void {
    const store = useVillage.getState();
    if (store.placing) {
      const [tx, ty] = this.ghostTileFor(sx, sy);
      store.setGhost(tx, ty);
      if (!this.touchMode) store.confirmPlacement();
      return;
    }
    store.select(this.buildingAt(sx, sy));
  }

  private buildingAt(sx: number, sy: number): string | null {
    const w = this.screenToWorld(sx, sy);
    const hits = [...this.views.values()]
      .filter((v) => {
        const top = v.root.y - v.anchorTop;
        return w.x >= v.root.x && w.x < v.root.x + v.sprite.texture.width && w.y >= top && w.y < top + v.sprite.texture.height;
      })
      .sort((a, b) => b.root.zIndex - a.root.zIndex);
    return hits[0]?.id ?? null;
  }
}

/** Last local ghost validity, read by the HUD. */
export const useGhostState: { error: string | null } = { error: null };
