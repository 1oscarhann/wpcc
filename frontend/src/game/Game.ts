// Build Mode renderer (PixiJS v8, imperative — D-019). React only renders the DOM HUD on top.
import { decode } from "@msgpack/msgpack";
import gsap from "gsap";
import { AnimatedSprite, Application, Container, Graphics, Rectangle, Sprite, Text } from "pixi.js";
import type { BuildingDef, BuildingState, VillageState } from "../api/types";
import { serverNow, useSession } from "../state/session";
import { onVillageChange, useVillage, type MapMeta } from "../state/village";
import { manifest } from "../assets/manifest";
import { ENT, leaveAvatar, reelNow, roomLink, type RoomClient } from "../net/room";
import { useFishing } from "../state/companions";
import { anyDown, isKey } from "./keymap";
import { readPad } from "./gamepad";
import { touchInput } from "../net/touch";
import { BTN } from "../sim/motion";
import { ClientGrid, gridLink } from "../sim/grid";
import { useAvatar } from "../state/avatar";
import { Ambient } from "./ambient";
import { VillagerLife } from "./villagers";
import { CloudShadows, groundLighting } from "./atmosphere";
import { AvatarWorld, type WorldHost } from "./avatarWorld";
import { MerchantCart } from "./merchantFx";
import { Explorer } from "./explorer";
import { SocialFx } from "./socialFx";
import { MateVillages } from "./mates";
import { useRealm } from "../state/realm";
import { useMarket } from "../state/market";
import { useSocial } from "../state/social";
import { CombatFx } from "./combatFx";
import { ComboFx } from "./comboFx";
import { localPlacementError, rotatedFootprint, usableBounds } from "./placement";
import { safeDestroy } from "./safe";
import { sfx } from "./sfx";
import { type Light, Sky } from "./sky";
import { Soundscape } from "./soundscape";
import { Music } from "./music";
import { DelveView } from "./delve";
import { useDelve } from "../state/delve";
import { biomeAt, dayPhase, useWorld } from "../state/world";
import { buildingLook, loadIconAtlas, loadWorldAtlas, tex } from "./sprites";

/** Map objects that cast light at night: prefix, radius (world px), colour, flicker. */
const GLOWS: [string, number, number, boolean][] = [
  ["obj.lamp", 60, 0xffd28a, true],
  ["obj.waystone", 44, 0x8fe3d6, false],
  ["obj.lava_vent", 46, 0xff7a3a, true],
  ["obj.ember_rock", 28, 0xff9a4a, true],
  ["obj.star_vein", 28, 0xb6a8ff, false],
  ["obj.frost_spire", 34, 0xa6e0ff, false],
  ["obj.moonpetal", 30, 0xd8c8ff, false],
  ["obj.venom_bloom", 22, 0xc993e8, false],
];
const TREE_PREFIXES = ["obj.oak", "obj.big_oak", "obj.birch", "obj.pine", "obj.apple"];
const DEBRIS_LEAVES = new Set(["oak", "big_oak", "birch", "pine", "apple", "bush", "weeds"]);

const T = 16;

/** The live Game, for HUD pieces that ask it things (is there water here? a photo, please). */
export const gameLink: { game: Game | null } = { game: null };
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
  private selectRing = new Graphics();
  private lighting: Container | null = null;
  private clouds = new CloudShadows(5);
  private sky = new Container();
  private ambient: Ambient | null = null;
  villagerLife: VillagerLife | null = null; // Phase 14
  private debrisViews = new Map<number, Sprite>();
  private clearing = new Set<number>();
  private fence: Sprite[] = [];
  private fenceKey = "";
  private waterTiles = new Set<string>();
  private fishTiles = new Set<string>();
  private treeSpots: { x: number; y: number }[] = [];
  // Phase 10: things that glow at night, and moonpetals (only open after dark)
  private lightSpots: { x: number; y: number; r: number; color: number; flicker: boolean }[] = [];
  private moonpetals: Sprite[] = [];
  private petalsOpen: boolean | null = null;
  private heavens: Sky | null = null;
  private delveView: DelveView | null = null;
  private sound = new Soundscape();
  private music = new Music();
  private flowerSpots: { x: number; y: number }[] = [];
  private hoverDebris: number | null = null;
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
  private grid: ClientGrid | null = null;
  private objectSprites = new Map<number, Sprite>();
  avatar: AvatarWorld | null = null;
  private combatFx: CombatFx | null = null; // Phase 13: the blizzard flag
  private mouse: { x: number; y: number } | null = null;
  private mouseLight = false;
  private camTween: gsap.core.Tween | null = null;
  private shakeAmp = 0;
  private shakeUntil = 0;
  private hitStopUntil = 0;
  private nodePrefixes: string[] = [];
  private comboFx: ComboFx | null = null;
  private mates: MateVillages | null = null;
  private resonanceCd = 0;
  private resonanceKey = "";

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
    await Promise.all([loadWorldAtlas(), loadIconAtlas(), document.fonts.load('16px "Pixelify Sans"').catch(() => undefined)]);
    const config = useSession.getState().config!;
    const gfx = useSession.getState().me?.settings.graphics as { reduce_motion?: boolean } | undefined;
    document.documentElement.dataset.reduceMotion = gfx?.reduce_motion ? "1" : "0";
    this.defs = config.buildings;
    this.nodePrefixes = Object.values(config.nodes ?? {}).flatMap((n) => n.objects);
    this.map = await useVillage.getState().fetchMap();
    this.grid = new ClientGrid(
      this.map.size, this.map.chunk_size, this.map.tile_names, this.map.object_names, this.map.plots.map((p) => p.origin),
    );
    gridLink.grid = this.grid;
    this.objects.sortableChildren = true;
    this.lighting = groundLighting(this.map.size * T);
    this.world.addChild(this.ground, this.lighting, this.below, this.objects, this.above, this.fx, this.clouds.layer, this.sky);
    this.below.addChild(this.selectRing);
    this.ambient = new Ambient(
      {
        origin: () => this.origin,
        village: () => useVillage.getState().village,
        defs: () => this.defs,
        view: () => this.viewRect(),
        waterTiles: this.waterTiles,
        treeSpots: this.treeSpots,
        flowerSpots: this.flowerSpots,
        smokeSpots: () => this.smokeSpots(),
      },
      this.objects,
      this.fx,
      this.sky,
    );
    this.villagerLife = new VillagerLife({
      origin: () => this.origin,
      village: () => useVillage.getState().village,
      defs: () => this.defs,
      objects: this.objects,
      screen: this.screen,
      toScreen: (wx, wy) => ({ x: this.world.x + wx * this.cam.zoom, y: this.world.y + wy * this.cam.zoom }),
      zoom: () => this.cam.zoom,
      avatar: () => {
        const c = this.avatar?.client;
        if (!c) return null;
        const p = c.drawPos();
        return { x: p.x, y: p.y, weapon: useAvatar.getState().weapon?.key ?? "" };
      },
    });
    this.app.stage.addChild(this.world, this.screen);
    this.heavens = new Sky(this.app);
    this.heavens.reduceMotion = gfx?.reduce_motion ?? false;
    this.app.stage.addChildAt(this.heavens.layer, 1);
    void useWorld.getState().load();
    this.comboFx = new ComboFx({
      fx: this.fx,
      objects: this.objects,
      screen: this.screen,
      origin: () => this.origin,
      defs: () => this.defs,
      toScreen: (wx, wy) => ({ x: this.world.x + wx * this.cam.zoom, y: this.world.y + wy * this.cam.zoom }),
      zoom: () => this.cam.zoom,
      view: (id) => {
        const v = this.views.get(id);
        if (!v) return undefined;
        const def = this.defs[v.key];
        const [, h] = rotatedFootprint(def.footprint, v.rotation);
        return { top: v.root.y - v.anchorTop + 6, x: v.root.x, y: v.root.y + h * T - 4, w: v.sprite.texture.width };
      },
      sparkles: (x, y) => this.sparkles(x, y),
      floatText: (wx, wy, text, color, delay, size) => this.floatText(wx, wy, text, color, delay, size),
      focus: (wx, wy) => {
        if (this.avatar) return;
        this.cam.vx = this.cam.vy = 0;
        this.tweenCamera(wx, wy, Math.max(3, Math.round(this.cam.zoom)), 0.6);
      },
      inView: (wx, wy) => {
        const r = this.viewRect();
        return wx > r.x0 - 20 && wx < r.x1 + 20 && wy > r.y0 - 20 && wy < r.y1 + 40;
      },
    });

    const v = useVillage.getState().village;
    if (v) this.onVillage(null, v, true);
    this.unsub.push(onVillageChange((prev, next) => this.onVillage(prev, next, false)));
    // Phase 9: realm-mates' villages, drawn read-only; refreshed when the realm changes
    this.mates = new MateVillages(this.objects, () => this.defs);
    this.unsub.push(
      useRealm.subscribe((s, p) => {
        if (s.mates !== p.mates) this.mates?.sync(Object.values(s.mates));
      }),
    );
    // Phase 10: opened chests stay open, rescued villagers have gone home
    const onPoiUsed = (e: Event) => {
      const q = useRealm.getState().overview?.pois[(e as CustomEvent<number>).detail];
      const sp = q && this.map ? this.objectSprites.get(q.y * this.map.size + q.x) : undefined;
      if (q && sp) this.applyPoiLook(sp, q.x, q.y, true);
    };
    window.addEventListener("hf:poi-used", onPoiUsed);
    this.unsub.push(() => window.removeEventListener("hf:poi-used", onPoiUsed));
    this.unsub.push(
      useRealm.subscribe((s, p) => {
        if (s.overview?.pois === p.overview?.pois || !this.map) return;
        for (const q of s.overview?.pois ?? []) {
          const sp = q.used ? this.objectSprites.get(q.y * this.map.size + q.x) : undefined;
          if (sp) this.applyPoiLook(sp, q.x, q.y, false);
        }
      }),
    );
    // Phase 12: the delve you're in
    this.unsub.push(
      useDelve.subscribe((s, p) => {
        if (s.delve !== p.delve) {
          this.delveView?.destroy();
          this.delveView = s.delve ? new DelveView(this.ground, this.objects, s.delve) : null;
          if (this.delveView && s.state) this.delveView.sync(s.state, s.levers, s.chests);
        } else if (this.delveView && s.state && (s.state !== p.state || s.levers !== p.levers || s.chests !== p.chests)) {
          this.delveView.sync(s.state, s.levers, s.chests);
        }
      }),
    );
    const onRealm = () => void this.refreshMap();
    window.addEventListener("hf:realm-changed", onRealm);
    this.unsub.push(() => window.removeEventListener("hf:realm-changed", onRealm));
    void useRealm.getState().load();
    void useRealm.getState().loadMates();
    void useRealm.getState().loadOverview();
    this.unsub.push(
      useVillage.subscribe((s, p) => {
        if (s.placing !== p.placing) this.syncGhost();
        if (s.selectedId !== p.selectedId) this.syncSelection();
      }),
    );
    this.bindInput();
    const cv = this.app.canvas;
    cv.addEventListener("dragover", (e) => {
      if (e.dataTransfer?.types.includes("text/villager")) e.preventDefault();
    });
    cv.addEventListener("drop", (e) => {
      const vid = e.dataTransfer?.getData("text/villager");
      if (!vid) return;
      e.preventDefault();
      const bid = this.buildingAtClient(e.clientX, e.clientY);
      if (bid) void useVillage.getState().assignVillager(vid, bid);
    });
    roomLink.listeners.add(this.onRoomClient);
    if (roomLink.client) this.onRoomClient(roomLink.client);
    this.app.ticker.add((t) => this.tick(t.deltaMS));
    gameLink.game = this;
    if (import.meta.env.DEV) {
      // for screenshot tests
      const w = window as unknown as { __hfGame?: Game; __hfVillage?: typeof useVillage; __hfDelve?: typeof useDelve; __hfRealm?: typeof useRealm };
      w.__hfGame = this;
      w.__hfVillage = useVillage;
      w.__hfDelve = useDelve;
      w.__hfRealm = useRealm;
      (window as unknown as { __hfFishing?: typeof useFishing; __hfRoomLink?: typeof roomLink }).__hfFishing = useFishing;
      (window as unknown as { __hfRoomLink?: typeof roomLink }).__hfRoomLink = roomLink;
    }
  }

  destroy(): void {
    this.destroyed = true;
    if (gameLink.game === this) gameLink.game = null;
    roomLink.listeners.delete(this.onRoomClient);
    this.avatar?.destroy();
    this.avatar = null;
    this.comboFx?.destroy();
    this.villagerLife?.destroy();
    this.sound.destroy();
    this.music.destroy();
    this.delveView?.destroy();
    this.heavens?.destroy();
    this.heavens = null;
    if (gridLink.grid === this.grid) gridLink.grid = null;
    this.unsub.forEach((u) => u());
    this.mates?.destroy();
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
    if (this.avatar && this.delveView) return; // inside a delve, east of the map
    if (this.avatar && this.map) {
      const max = this.map.size * T;
      this.cam.x = Math.max(0, Math.min(max, this.cam.x));
      this.cam.y = Math.max(0, Math.min(max, this.cam.y));
      return;
    }
    const v = useVillage.getState().village;
    if (!v) return;
    // with realm-mates you can pan over to see their villages next door (Phase 9)
    const margin = (Object.keys(useRealm.getState().mates).length ? 70 : 28) * T;
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
    const cx = th ? th.x + 2 : v.frame / 2;
    const cy = th ? th.y + 3 : v.frame / 2;
    this.cam.x = (this.origin[0] + cx) * T;
    this.cam.y = (this.origin[1] + cy) * T;
    // close enough to enjoy the pixel art; phones get a wider view
    this.cam.zoom = this.app.screen.width >= 700 ? 3 : 2;
  }

  // ── frame loop ────────────────────────────────────────────────────────────
  private tick(dms: number): void {
    if (this.avatar) {
      this.avatarTick(dms);
      return;
    }
    const dt = Math.min(dms, 50) / 1000;
    const speed = 420 / this.cam.zoom;
    let kx = 0;
    let ky = 0;
    if (anyDown(this.keys, "left")) kx -= 1;
    if (anyDown(this.keys, "right")) kx += 1;
    if (anyDown(this.keys, "up")) ky -= 1;
    if (anyDown(this.keys, "down")) ky += 1;
    this.cam.x += kx * speed * dt;
    this.cam.y += ky * speed * dt;
    if (!this.dragging && !this.camTween) {
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
    this.ambient?.update(dms);
    this.villagerLife?.update(dms);
    this.comboFx?.update(dms);
    this.ghostResonance(dms);
    this.clouds.update(dt, this.viewRect());
    this.updateSky(dms);
  }

  /** Phase 12: the lever, chest or portal you're standing at (drives the E prompt). */
  private delveNear(): void {
    const dv = this.delveView;
    const c = this.avatar?.client;
    if (!dv || !c) return;
    const p = c.drawPos();
    let near: { kind: "use" | "portal"; prop: number; label: string } | null = null;
    const portal = dv.portalPos();
    if (portal && (portal.x - p.x) ** 2 + (portal.y - p.y) ** 2 < 2.2 * 2.2) near = { kind: "portal", prop: -1, label: "Step through the portal" };
    else {
      const prop = dv.usableNear(p.x, p.y);
      if (prop) near = { kind: "use", prop: prop.index, label: prop.kind === "lever" ? "Pull the lever" : "Open the chest" };
    }
    const cur = useDelve.getState().near;
    if (cur?.prop !== near?.prop || cur?.kind !== near?.kind) useDelve.getState().set({ near });
  }

  /** Phase 10: day/night light, season tint, weather and the soundscape. */
  private updateSky(dms: number): void {
    if (!this.heavens) return;
    const dt = Math.min(dms, 50) / 1000;
    const dv = this.delveView;
    const phase = dv ? { name: "night", progress: 0.5, dark: 0.92, glow: 0 } : dayPhase();
    const world = useWorld.getState();
    const season = world.season;
    // Phase 13: the Frost Matriarch's blizzard swallows the sky around her
    const weather = dv ? "clear" : this.combatFx?.blizzard ? "snow" : world.weather;
    const biome = dv ? "cave" : biomeAt(this.cam.x / T, this.cam.y / T);
    const lights: Light[] = [];
    if (dv) {
      dv.update(dms);
      this.delveNear();
    }
    if (phase.dark > 0.02 || weather === "storm") {
      const z = this.cam.zoom;
      const r = this.viewRect();
      const pad = 80;
      const add = (wx: number, wy: number, rad: number, color: number, flicker: boolean, power = 1) => {
        if (wx < r.x0 - pad || wx > r.x1 + pad || wy < r.y0 - pad || wy > r.y1 + pad) return;
        lights.push({ x: this.world.x + wx * z, y: this.world.y + wy * z, r: rad * z, color, flicker, power });
      };
      for (const l of dv ? dv.lights(useDelve.getState().state) : this.lightSpots) add(l.x, l.y, l.r, l.color, l.flicker ?? false);
      for (const v of this.views.values()) {
        // lit windows: a warm pool around every finished building
        if (v.level < 1) continue;
        const [fw, fh] = rotatedFootprint(this.defs[v.key].footprint, v.rotation);
        add(v.root.x + (fw * T) / 2, v.root.y + fh * T - 10, 22 + fw * 9, 0xffc46e, true, 0.95);
      }
      if (this.avatar) {
        const p = this.avatar.client.drawPos();
        add(p.x * T, p.y * T - 6, 88, 0xfff0d0, true, 1.1); // your lantern
      }
    }
    this.heavens.update(dt, { phase, season, weather, biome, lights });
    this.sound.update(dt, biome, phase.name === "night", weather);
    // Phase 18: the music follows the mood: a fight, the night, or a cozy day
    this.music.setMood(this.avatar && useAvatar.getState().inCombat ? "fight" : phase.name === "night" ? "night" : "day");
    this.music.update();
    const open = phase.dark > 0.5;
    if (open !== this.petalsOpen) {
      this.petalsOpen = open;
      for (const s of this.moonpetals) if (!s.destroyed) gsap.to(s, { alpha: open ? 1 : 0, duration: 1.2 });
    }
  }

  /** P17: when the ghost would form a combo, it shimmers (named if discovered, a mystery if not). */
  private ghostResonance(dms: number): void {
    const { placing, previewInfo } = useVillage.getState();
    const live =
      placing && previewInfo && previewInfo.key === placing.key && previewInfo.x === placing.x &&
      previewInfo.y === placing.y && previewInfo.rotation === placing.rotation &&
      (previewInfo.mystery > 0 || previewInfo.combos.length > 0);
    const key = live ? `${previewInfo!.key}:${previewInfo!.x}:${previewInfo!.y}` : "";
    if (key && key !== this.resonanceKey) sfx("shimmer");
    this.resonanceKey = key;
    if (!live || !placing || placing.x === undefined || placing.y === undefined) return;
    this.resonanceCd -= dms;
    if (this.resonanceCd > 0) return;
    this.resonanceCd = 90;
    const [w, h] = rotatedFootprint(this.defs[placing.key].footprint, placing.rotation);
    const x = (this.origin[0] + placing.x) * T;
    const y = (this.origin[1] + placing.y) * T;
    const t = Math.random() * 2 * (w + h);
    const px = t < w ? x + t * T : t < w + h ? x + w * T : t < 2 * w + h ? x + (2 * w + h - t) * T : x;
    const py = t < w ? y : t < w + h ? y + (t - w) * T : t < 2 * w + h ? y + h * T : y + (2 * (w + h) - t) * T;
    const s = new AnimatedSprite([0, 1, 2, 3, 2, 1].map((k) => tex(`fx.sparkle.${k}`)));
    s.anchor.set(0.5);
    s.position.set(px, py);
    s.animationSpeed = 0.35;
    s.loop = false;
    s.onComplete = () => safeDestroy(s);
    s.zIndex = 1e6;
    this.fx.addChild(s);
    s.play();
    gsap.to(s, { y: py - 10, duration: 0.45 });
  }

  // ── Avatar Mode ───────────────────────────────────────────────────────────
  private onRoomClient = (c: RoomClient | null): void => {
    if (this.destroyed || !this.map) return;
    if (c && this.avatar?.client === c) return;
    this.avatar?.destroy();
    this.avatar = null;
    if (c) {
      const me = useSession.getState().me!;
      this.avatar = new AvatarWorld(this.worldHost, c, me.avatar.appearance);
      this.combatFx = new CombatFx(this.worldHost, this.avatar);
      this.avatar.extras.push(
        this.combatFx,
        new MerchantCart(this.worldHost, this.avatar),
        new Explorer(this.worldHost, this.avatar),
        new SocialFx(this.worldHost, this.avatar),
      );
      useVillage.getState().startPlacing(null);
      useVillage.getState().select(null);
      this.cam.vx = this.cam.vy = 0;
      const p = c.drawPos();
      this.tweenCamera(p.x * T, p.y * T - 8, this.app.screen.width >= 700 ? 3 : 2, 0.7);
      sfx("dodge");
    } else {
      const v = useVillage.getState().village;
      if (!v) return;
      const th = v.buildings.find((b) => b.key === "town_hall");
      const cx = (this.origin[0] + (th ? th.x + 2 : v.frame / 2)) * T;
      const cy = (this.origin[1] + (th ? th.y + 3 : v.frame / 2)) * T;
      this.tweenCamera(cx, cy, this.app.screen.width >= 700 ? 3 : 2, 0.7);
    }
  };

  private tweenCamera(x: number, y: number, zoom: number, duration: number): void {
    this.camTween?.kill();
    this.camTween = gsap.to(this.cam, {
      x, y, zoom, duration, ease: "power3.inOut",
      onComplete: () => {
        this.cam.zoom = zoom;
        this.camTween = null;
      },
    });
  }

  private readonly worldHost: WorldHost = {
    under: this.below,
    objects: this.objects,
    fx: this.fx,
    screen: this.screen,
    floatText: (wx, wy, text, color, delay, size) => this.floatText(wx, wy, text, color, delay, size),
    dust: (x, y) => this.dust(x, y),
    sparkles: (x, y) => this.sparkles(x, y),
    objectAt: (tx, ty) => {
      const s = this.objectSprites.get(ty * (this.map?.size ?? 0) + tx);
      return s && !s.destroyed ? s : undefined;
    },
    homeAnchor: () => {
      const v = useVillage.getState().village;
      const th = v?.buildings.find((b) => b.key === "town_hall");
      return th ? { x: (this.origin[0] + th.x + 2) * T, y: (this.origin[1] + th.y + 1) * T } : { x: 0, y: 0 };
    },
    toScreen: (wx, wy) => ({ x: this.world.x + wx * this.cam.zoom, y: this.world.y + wy * this.cam.zoom }),
    zoom: () => this.cam.zoom,
    shake: (px, ms) => {
      if (document.documentElement.dataset.reduceMotion === "1") return;
      this.shakeAmp = Math.max(this.shakeAmp, px);
      this.shakeUntil = Math.max(this.shakeUntil, performance.now() + ms);
    },
    hitStop: (ms) => {
      if (document.documentElement.dataset.reduceMotion === "1") return;
      this.hitStopUntil = Math.max(this.hitStopUntil, performance.now() + ms);
    },
    occluders: (x0, y0, x1, y1, z) => {
      const out: Container[] = [];
      const overlaps = (bx0: number, by0: number, bx1: number, by1: number) => bx0 < x1 && bx1 > x0 && by0 < y1 && by1 > y0;
      const size = this.map?.size ?? 0;
      const tx0 = Math.floor(x0 / T) - 2;
      const tx1 = Math.floor(x1 / T) + 2;
      const ty0 = Math.floor(y1 / T);
      for (let ty = ty0; ty <= ty0 + 4; ty++) {
        for (let tx = tx0; tx <= tx1; tx++) {
          const s = this.objectSprites.get(ty * size + tx);
          if (!s || s.destroyed || s.zIndex <= z || s.height < 20) continue;
          if (overlaps(s.x - s.width / 2, s.y - s.height, s.x + s.width / 2, s.y)) out.push(s);
        }
      }
      for (const s of this.debrisViews.values()) {
        if (s.zIndex > z && s.height >= 20 && overlaps(s.x - s.width / 2, s.y - s.height, s.x + s.width / 2, s.y)) out.push(s);
      }
      for (const v of this.views.values()) {
        const top = v.root.y - v.anchorTop;
        if (v.root.zIndex > z && overlaps(v.root.x, top, v.root.x + v.sprite.texture.width, top + v.sprite.texture.height)) out.push(v.root);
      }
      return out;
    },
  };

  private avatarTick(dms: number): void {
    const a = this.avatar!;
    const c = a.client;
    this.sampleAvatarInput(c);
    c.update(dms); // the predicted simulation never pauses (hit-stop is visual only, D-010)
    const now = performance.now();
    const frozen = now < this.hitStopUntil;
    gsap.globalTimeline.timeScale(frozen ? 0.05 : 1);
    if (!frozen) a.update(dms);
    if (!this.camTween) {
      const p = c.drawPos();
      const tx = p.x * T + c.me.fx * 10;
      const ty = p.y * T - 8 + c.me.fy * 8;
      const k = 1 - Math.exp(-dms / 90);
      this.cam.x += (tx - this.cam.x) * k;
      this.cam.y += (ty - this.cam.y) * k;
    } else if (this.camTween.progress() > 0.15) {
      // keep the tween's end point on the (moving) avatar
      const p = c.drawPos();
      this.camTween.vars.x = p.x * T;
      this.camTween.vars.y = p.y * T - 8;
      this.camTween.invalidate();
    }
    this.clampCamera();
    this.applyCamera();
    if (now < this.shakeUntil) {
      const amp = this.shakeAmp * ((this.shakeUntil - now) / 120);
      this.world.x += Math.round((Math.random() - 0.5) * 2 * amp * this.cam.zoom);
      this.world.y += Math.round((Math.random() - 0.5) * 2 * amp * this.cam.zoom);
    } else this.shakeAmp = 0;
    this.loadVisibleChunks();
    this.updateTimers();
    if (!frozen) this.ambient?.update(dms);
    if (!frozen) this.villagerLife?.update(dms);
    this.comboFx?.update(dms);
    this.clouds.update(Math.min(dms, 50) / 1000, this.viewRect());
    this.updateSky(dms);
  }

  private sampleAvatarInput(c: RoomClient): void {
    this.steerAutopilot(c);
    let kx = 0;
    let ky = 0;
    if (anyDown(this.keys, "left")) kx -= 1;
    if (anyDown(this.keys, "right")) kx += 1;
    if (anyDown(this.keys, "up")) ky -= 1;
    if (anyDown(this.keys, "down")) ky += 1;
    if (touchInput.active) {
      kx = touchInput.mx;
      ky = touchInput.my;
    }
    const pad = readPad(); // Phase 18: a gamepad, if one's plugged in
    if (pad && (pad.mx || pad.my)) {
      kx = pad.mx;
      ky = pad.my;
    }
    const q = (v: number) => Math.max(-127, Math.min(127, Math.round(v * 127)));
    c.input.mx = q(kx);
    c.input.my = q(ky);
    let ax = 0;
    let ay = 0;
    const p = c.drawPos();
    if (pad && (pad.ax || pad.ay)) {
      ax = pad.ax;
      ay = pad.ay;
    } else if (this.mouse && !this.touchMode && !pad?.active) {
      const w = this.screenToWorld(this.mouse.x, this.mouse.y);
      ax = w.x - p.x * T;
      ay = w.y - (p.y * T - 9);
    } else {
      const t = this.autoAim(c);
      if (t) [ax, ay] = t;
    }
    const l = Math.hypot(ax, ay);
    c.input.ax = l > 0.01 ? q(ax / l) : 0;
    c.input.ay = l > 0.01 ? q(ay / l) : 0;
    if (this.steerFight(c)) {
      // dev auto-fight already set the aim; take its movement too
      c.input.mx = q(touchInput.mx);
      c.input.my = q(touchInput.my);
    }
    c.input.held =
      (this.mouseLight || anyDown(this.keys, "attack") ? BTN.light : 0) | (anyDown(this.keys, "offhand") ? BTN.offhand : 0) |
      touchInput.held | (pad?.held ?? 0);
    if (pad) {
      c.input.latched |= pad.latched;
      if (pad.pressed.has("interact")) this.interact();
      if (pad.pressed.has("bag")) useAvatar.getState().set({ bagOpen: !useAvatar.getState().bagOpen });
      if (pad.pressed.has("map")) useRealm.getState().set({ mapOpen: !useRealm.getState().mapOpen, travelMode: false });
      for (let i = 0; i < 4; i++) if (pad.pressed.has(`quick${i + 1}`)) c.useQuick(i);
    }
    const blocking = (c.input.held & BTN.offhand) !== 0 && useAvatar.getState().offhand.type === "shield";
    if (blocking !== useAvatar.getState().blocking) useAvatar.getState().set({ blocking });
    c.input.latched |= touchInput.latched;
    touchInput.latched = 0;
  }

  /** Touch: aim at the nearest monster, else the nearest gatherable thing in reach, else straight ahead. */
  private autoAim(c: RoomClient): [number, number] | null {
    const me = c.me;
    let best: [number, number, number] | null = null;
    const rt = c.renderTick();
    for (const e of c.ents.values()) {
      if (e.kind !== ENT.monster) continue;
      const s = c.sampleAt(e, rt);
      if (!s) continue;
      const d = (s.x - me.x) ** 2 + (s.y - me.y) ** 2;
      if (d < 25 && (!best || d < best[2])) best = [s.x - me.x, s.y - me.y, d];
    }
    if (best) return [best[0], best[1]];
    const g = this.grid;
    if (!g || !this.map) return null;
    const cx = Math.floor(me.x);
    const cy = Math.floor(me.y);
    for (let r = 1; r <= 2; r++) {
      for (let y = cy - r; y <= cy + r; y++) {
        for (let x = cx - r; x <= cx + r; x++) {
          const oid = g.objectAt(x, y);
          if (oid === undefined) continue;
          const name = this.map.object_names[oid];
          if (!this.nodePrefixes.some((p) => name === p || name.startsWith(p + "."))) continue;
          if (c.depleted.has(y * this.map.size + x)) continue;
          const dx = x + 0.5 - me.x;
          const dy = y + 0.5 - me.y;
          const d = dx * dx + dy * dy;
          if (d < 5 && (!best || d < best[2])) best = [dx, dy, d];
        }
      }
    }
    return best ? [best[0], best[1]] : null;
  }

  private viewRect(): { x0: number; y0: number; x1: number; y1: number } {
    const { width, height } = this.app.screen;
    const a = this.screenToWorld(0, 0);
    const b = this.screenToWorld(width, height);
    return { x0: a.x, y0: a.y, x1: b.x, y1: b.y };
  }

  private smokeSpots(): { x: number; y: number }[] {
    const out: { x: number; y: number }[] = [];
    for (const v of this.views.values()) {
      if (v.level < 1) continue;
      const meta = manifest.sprites[this.lookName(v)] as { smoke?: [number, number][] } | undefined;
      for (const [sx, sy] of meta?.smoke ?? []) {
        const w = v.sprite.texture.width;
        out.push({ x: v.root.x + (v.sprite.scale.x < 0 ? w - sx : sx), y: v.root.y - v.anchorTop + sy });
      }
    }
    return out;
  }

  private lookName(v: BuildingView): string {
    return buildingLook(v.key, this.defs[v.key].footprint, {
      rotation: v.rotation, level: v.level, state: v.state as BuildingState["state"],
    }).name;
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
      const name = m.tile_names[ch.ground[i]];
      const s = new Sprite(tex(name));
      s.position.set((i % cs) * T, Math.floor(i / cs) * T);
      c.addChild(s);
      const tx = ch.cx * cs + (i % cs);
      const ty = ch.cy * cs + Math.floor(i / cs);
      if (name.startsWith("tile.water")) this.waterTiles.add(`${tx},${ty}`);
      if (name.startsWith("tile.water") || name.startsWith("tile.ice") || name.startsWith("tile.lava")) {
        this.fishTiles.add(`${tx},${ty}`); // Phase 16b: somewhere to cast a line
      }
      else if (name.startsWith("tile.lava") && (tx * 5 + ty * 3) % 4 === 0) {
        this.lightSpots.push({ x: tx * T + 8, y: ty * T + 8, r: 24, color: 0xff6a2a, flicker: true });
      }
      else if (name.startsWith("tile.flowers") && (tx * 7 + ty * 3) % 4 === 0) this.flowerSpots.push({ x: tx * T + 8, y: ty * T + 8 });
    }
    c.cacheAsTexture(true);
    this.ground.addChild(c);
    this.chunks.set(`${ch.cx}_${ch.cy}`, c);
    this.grid?.addChunk(ch.cx, ch.cy, ch);
    const v = useVillage.getState().village;
    const [lo, hi] = v ? usableBounds(v.frame, v.size) : [0, 0];
    for (const [lx, ly, k, flags] of ch.objects) {
      const name = m.object_names[k];
      const wtx = ch.cx * cs + lx;
      const wty = ch.cy * cs + ly;
      // a claimed plot's wild growth is replaced by that village's own debris
      if (flags & 1 && this.plotOwnerAt(wtx, wty)) continue;
      // nature inside our buildable square disappears as the plot expands over it (pond decor stays)
      const fx = wtx - this.origin[0];
      const fy = wty - this.origin[1];
      if (v && fx >= lo - 1 && fx < hi + 1 && fy >= lo - 1 && fy < hi + 1 && !name.startsWith("obj.lilypad")) continue;
      const s = new Sprite(tex(name));
      s.label = name;
      s.anchor.set(0.5, 1);
      const wx = (ch.cx * cs + lx) * T + T / 2;
      const wy = (ch.cy * cs + ly) * T + T - 1;
      s.position.set(wx, wy);
      s.zIndex = name.startsWith("obj.lilypad") ? wy - 16 : wy;
      this.objects.addChild(s);
      this.objectSprites.set(wty * m.size + wtx, s);
      const glow = GLOWS.find(([p]) => name.startsWith(p));
      if (glow) this.lightSpots.push({ x: wx, y: wy - 8, r: glow[1], color: glow[2], flicker: glow[3] });
      if (name.startsWith("obj.chest") || name.startsWith("obj.lost_villager")) this.applyPoiLook(s, wtx, wty, false);
      if (name.startsWith("obj.moonpetal")) {
        s.alpha = this.petalsOpen ? 1 : 0;
        this.moonpetals.push(s);
      }
      if (TREE_PREFIXES.some((p) => name.startsWith(p))) this.treeSpots.push({ x: wx, y: wy - s.height * 0.6 });
      else if (name.startsWith("obj.flowers") || name.startsWith("obj.flower_bush")) this.flowerSpots.push({ x: wx, y: wy - 4 });
    }
  }

  private applyPoiLook(s: Sprite, x: number, y: number, animate: boolean): void {
    const q = useRealm.getState().overview?.pois.find((p) => p.x === x && p.y === y);
    if (!q?.used) return;
    if (q.kind === "ruins") {
      s.texture = tex("obj.chest.1");
      if (animate) gsap.fromTo(s.scale, { y: 0.8 }, { y: 1, duration: 0.35, ease: "back.out(3)" });
    } else if (q.kind === "lost_villager") {
      if (animate) gsap.to(s, { alpha: 0, y: s.y - 6, duration: 1.4, delay: 0.8, onComplete: () => void (s.visible = false) });
      else s.visible = false;
    }
  }

  /** Members came or went: refetch plot owners and rebuild the world's objects (wild growth vs villages). */
  async refreshMap(): Promise<void> {
    const m = await useVillage.getState().fetchMap(true);
    if (this.destroyed || !this.map) return;
    this.map = m;
    for (const c of this.chunks.values()) if (c !== "loading") c.destroy({ children: true });
    this.chunks.clear();
    for (const sp of this.objectSprites.values()) safeDestroy(sp);
    this.objectSprites.clear();
    this.treeSpots.length = 0;
    this.flowerSpots.length = 0;
    this.lightSpots.length = 0;
    this.moonpetals.length = 0;
  }

  private plotOwnerAt(tx: number, ty: number): string | null {
    for (const p of this.map?.plots ?? []) {
      if (tx >= p.origin[0] && tx < p.origin[0] + 48 && ty >= p.origin[1] && ty < p.origin[1] + 48) return p.owner;
    }
    return null;
  }

  // ── village ───────────────────────────────────────────────────────────────
  private onVillage(prev: VillageState | null, next: VillageState, first: boolean): void {
    if (first || !prev) {
      this.origin = next.origin;
      this.centerOnVillage();
    }
    this.drawFence(next);
    this.syncDebris(next, first);
    if (prev && (prev.buildings.length !== next.buildings.length || prev.debris.length !== next.debris.length ||
        prev.buildings.some((b, i) => next.buildings[i]?.x !== b.x || next.buildings[i]?.y !== b.y))) {
      this.ambient?.invalidate();
      this.villagerLife?.invalidate();
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
    this.comboFx?.sync(next);
    if (prev && !first) {
      const had = new Set(prev.discovered ?? []);
      for (const key of next.discovered ?? []) {
        const c = next.combos?.find((x) => x.key === key);
        if (!had.has(key) && c) this.comboFx?.celebrate(c, next);
      }
    }
  }

  /** A wooden fence just outside the buildable square, open at the gate (2 tiles, matching the path). */
  private drawFence(v: VillageState): void {
    const key = `${v.size}:${v.gate.join(",")}`;
    if (key === this.fenceKey) return;
    this.fenceKey = key;
    for (const s of this.fence) s.destroy();
    this.fence = [];
    const [lo, hi] = usableBounds(v.frame, v.size);
    const [gx, gy, side] = v.gate;
    const gap = new Set<string>(side === "N" || side === "S" ? [`${gx},${gy}`, `${gx + 1},${gy}`] : [`${gx},${gy}`, `${gx},${gy + 1}`]);
    const [ox, oy] = this.origin;
    const add = (name: string, wx: number, wy: number, z: number, ax = 0, ay = 0) => {
      const s = new Sprite(tex(name));
      s.anchor.set(ax, ay);
      s.position.set(wx, wy);
      s.zIndex = z;
      this.objects.addChild(s);
      this.fence.push(s);
    };
    for (let x = lo - 1; x <= hi; x++) {
      for (const y of [lo - 1, hi]) {
        if (gap.has(`${x},${y}`)) continue;
        const wx = (ox + x) * T;
        const wy = (oy + y + 1) * T;
        if (x === lo - 1 || x === hi) add("obj.fence.post", wx + 5, wy - 2, wy - 1, 0, 1);
        else add("obj.fence.h", wx, wy - 2, wy - 1, 0, 1);
      }
    }
    for (let y = lo; y < hi; y++) {
      for (const x of [lo - 1, hi]) {
        if (gap.has(`${x},${y}`)) continue;
        const wx = (ox + x) * T + 5;
        const wy = (oy + y + 1) * T;
        add("obj.fence.v", wx, wy + 2, wy, 0, 1);
      }
    }
    // gate posts with lanterns either side of the gap
    const posts = side === "N" || side === "S" ? [[gx - 1, gy], [gx + 2, gy]] : [[gx, gy - 1], [gx, gy + 2]];
    for (const [px, py] of posts) {
      const wx = (ox + px) * T + 8;
      const wy = (oy + py + 1) * T;
      add("obj.fence.gate", wx, wy, wy + 1, 0.5, 1);
    }
  }

  private debrisSprite(id: number): Sprite | undefined {
    return this.debrisViews.get(id);
  }

  private syncDebris(v: VillageState, first: boolean): void {
    const config = useSession.getState().config!;
    const seen = new Set<number>();
    for (const [id, kind, variant, x, y] of v.debris) {
      seen.add(id);
      if (this.debrisViews.has(id)) continue;
      const name = config.debris[kind]?.sprites[variant] ?? "obj.bush.0";
      const s = new Sprite(tex(name));
      s.anchor.set(0.5, 1);
      const wx = (this.origin[0] + x) * T + T / 2;
      const wy = (this.origin[1] + y) * T + T - 1;
      s.position.set(wx, wy);
      s.zIndex = wy;
      this.objects.addChild(s);
      this.debrisViews.set(id, s);
      if (TREE_PREFIXES.some((p) => name.startsWith(p))) this.treeSpots.push({ x: wx, y: wy - s.height * 0.6 });
      if (name.startsWith("obj.flower_bush")) this.flowerSpots.push({ x: wx, y: wy - 6 });
      void first;
    }
    for (const [id, s] of this.debrisViews) {
      if (!seen.has(id) && !this.clearing.has(id)) {
        s.destroy();
        this.debrisViews.delete(id);
      }
    }
  }

  private debrisAt(sx: number, sy: number): number | null {
    const v = useVillage.getState().village;
    if (!v) return null;
    const w = this.screenToWorld(sx, sy);
    let best: { id: number; z: number } | null = null;
    for (const [id, s] of this.debrisViews) {
      if (this.clearing.has(id)) continue;
      const b = { x0: s.x - s.width / 2, x1: s.x + s.width / 2, y0: s.y - s.height, y1: s.y };
      if (w.x >= b.x0 && w.x < b.x1 && w.y >= b.y0 && w.y < b.y1 && (!best || s.zIndex > best.z)) {
        best = { id, z: s.zIndex };
      }
    }
    return best?.id ?? null;
  }

  private async clearDebris(id: number): Promise<void> {
    const s = this.debrisViews.get(id);
    if (!s || this.clearing.has(id)) return;
    this.clearing.add(id);
    const v = useVillage.getState().village!;
    const kind = v.debris.find((d) => d[0] === id)?.[1] ?? "oak";
    gsap.to(s, { rotation: 0.09, duration: 0.05, yoyo: true, repeat: 5, ease: "sine.inOut", onComplete: () => void (s.rotation = 0) });
    const gained = await useVillage.getState().clearDebris(id);
    if (!gained) {
      this.clearing.delete(id);
      return;
    }
    const x = s.x;
    const y = s.y;
    if (DEBRIS_LEAVES.has(kind)) {
      for (let i = 0; i < 7; i++) {
        const leaf = new AnimatedSprite([tex("fx.leaf.0"), tex("fx.leaf.1")]);
        leaf.animationSpeed = 0.2;
        leaf.play();
        leaf.position.set(x + (Math.random() - 0.5) * 16, y - s.height * (0.3 + Math.random() * 0.5));
        this.fx.addChild(leaf);
        gsap.to(leaf, { x: leaf.x + (Math.random() - 0.5) * 40, y: y + 2, alpha: 0, duration: 0.9 + Math.random() * 0.5, ease: "power1.in", onComplete: () => leaf.destroy() });
      }
    }
    this.dust(x, y - 2);
    gsap.to(s.scale, { x: 1.25, y: 0.6, duration: 0.12, ease: "power2.in" });
    gsap.to(s, { alpha: 0, duration: 0.18, delay: 0.06, onComplete: () => {
      s.destroy();
      this.debrisViews.delete(id);
      this.clearing.delete(id);
    } });
    const config = useSession.getState().config!;
    Object.entries(gained).forEach(([res, qty], i) => {
      const name = config.resources[res]?.name ?? res;
      this.floatText(x, y - s.height - 4 - i * 12, `+${qty} ${name}`, 0xf7d66a, i * 0.12);
    });
  }

  private floaters: { wx: number; wy: number; t: number }[] = [];

  private floatText(wx: number, wy: number, text: string, color: number, delay = 0, size = 17): void {
    // texts that pop at the same spot together (XP, loot, damage) step up a line instead of piling up
    const at = performance.now() + delay * 1000;
    this.floaters = this.floaters.filter((f) => Math.abs(at - f.t) < 650);
    const near = this.floaters.filter((f) => Math.abs(f.wx - wx) < 22 && Math.abs(f.wy - wy) < 16).length;
    this.floaters.push({ wx, wy, t: at });
    const stack = (near % 4) * (size + 3);
    const t = new Text({
      text,
      style: { fontFamily: "Pixelify Sans", fontSize: size, fill: color, stroke: { color: INK, width: size > 14 ? 4 : 3 }, fontWeight: "700" },
    });
    t.anchor.set(0.5, 1);
    t.alpha = 0;
    this.screen.addChild(t);
    const state = { lift: 0, a: 0 };
    const place = () => {
      const p = { x: this.world.x + wx * this.cam.zoom, y: this.world.y + wy * this.cam.zoom };
      t.position.set(Math.round(p.x), Math.round(p.y - state.lift - stack));
      t.alpha = state.a;
    };
    gsap.timeline({ delay, onUpdate: place, onComplete: () => t.destroy() })
      .to(state, { a: 1, lift: 14, duration: 0.18, ease: "back.out(2)" })
      .to(state, { lift: 40, duration: 0.9, ease: "power1.out" })
      .to(state, { a: 0, duration: 0.35 }, "-=0.35");
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
    if (def.walkable && b.key.startsWith("path") && view.root.parent !== this.below) {
      this.below.addChild(view.root); // paths lie flat under everyone's feet (Phase 14)
      view.label.visible = false;
    }
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
      if (this.avatar) {
        if (this.touchMode && e.pointerType !== "mouse") return;
        this.mouse = { x: e.offsetX, y: e.offsetY };
        if (e.button === 0) this.mouseLight = true;
        if (e.button === 2 && this.avatar) this.avatar.client.input.latched |= BTN.heavy;
        return;
      }
      el.setPointerCapture(e.pointerId);
      this.pointers.set(e.pointerId, { x: e.offsetX, y: e.offsetY, sx: e.offsetX, sy: e.offsetY, t: performance.now() });
      this.cam.vx = this.cam.vy = 0;
      if (this.pointers.size === 2) {
        const [a, b] = [...this.pointers.values()];
        this.pinchDist = Math.hypot(a.x - b.x, a.y - b.y);
      }
    };
    const move = (e: PointerEvent) => {
      if (e.pointerType === "mouse") this.mouse = { x: e.offsetX, y: e.offsetY };
      if (this.avatar) return;
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
      if (e.button === 0) this.mouseLight = false;
      if (this.avatar) return;
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
      if (this.avatar) this.zoomAvatar(e.deltaY < 0 ? 1 : -1);
      else this.zoomBy(e.deltaY < 0 ? 1 : -1, { x: e.offsetX, y: e.offsetY });
    };
    const keydown = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      const k = e.key.toLowerCase();
      this.keys.add(k);
      if (this.avatar) {
        this.avatarKey(k, e);
        return;
      }
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
    const blur = () => {
      this.keys.clear();
      this.mouseLight = false;
    };
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

  // ── dev helpers (screenshot runner / e2e) ───────────────────────────────
  private autopilot: {
    path: [number, number][];
    goal: [number, number];
    done: (ok: boolean) => void;
    lastProgress: number;
    started: number;
  } | null = null;

  /** Dev: centre the camera on a frame tile (screenshot runner). */
  devFocusTile(tx: number, ty: number): void {
    this.cam.x = (this.origin[0] + tx) * T;
    this.cam.y = (this.origin[1] + ty) * T;
    this.cam.vx = this.cam.vy = 0;
  }

  /** Nearest reachable tile next to a gatherable node of this kind ("tree", "rock"…), or null. */
  devFindNode(kind: string): { node: [number, number]; stand: [number, number] } | null {
    const c = this.avatar?.client;
    const cfg = useSession.getState().config;
    if (!c || !this.grid || !this.map || !cfg) return null;
    const prefixes = cfg.nodes[kind]?.objects ?? [];
    const start: [number, number] = [Math.floor(c.me.x), Math.floor(c.me.y)];
    const seen = new Set<number>([start[1] * this.map.size + start[0]]);
    const queue: [number, number][] = [start];
    while (queue.length && seen.size < 20000) {
      const [x, y] = queue.shift()!;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nx = x + dx;
        const ny = y + dy;
        const k = ny * this.map.size + nx;
        if (seen.has(k)) continue;
        seen.add(k);
        const oid = this.grid.objectAt(nx, ny);
        const name = oid === undefined ? "" : this.map.object_names[oid];
        if (name && prefixes.some((p) => name === p || name.startsWith(p + ".")) && !c.depleted.has(k) && dx !== 0) {
          return { node: [nx, ny], stand: [x, y] };
        }
        if (!this.grid.solid(nx, ny)) queue.push([nx, ny]);
      }
    }
    return null;
  }

  private planPath(tx: number, ty: number): [number, number][] | null {
    const c = this.avatar?.client;
    if (!c || !this.grid || !this.map) return null;
    const size = this.map.size;
    const key = (x: number, y: number) => y * size + x;
    const s0 = key(Math.floor(c.me.x), Math.floor(c.me.y));
    const prev = new Map<number, number>([[s0, -1]]);
    const queue = [s0];
    const goal = key(tx, ty);
    for (let qi = 0; qi < queue.length && !prev.has(goal) && prev.size < 60000; qi++) {
      const k = queue[qi];
      const x = k % size;
      const y = Math.floor(k / size);
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const n = key(x + dx, y + dy);
        if (prev.has(n) || this.grid.solid(x + dx, y + dy)) continue;
        prev.set(n, k);
        queue.push(n);
      }
    }
    if (!prev.has(goal)) return null;
    const path: [number, number][] = [];
    for (let k = goal; k !== -1; k = prev.get(k)!) path.unshift([k % size, Math.floor(k / size)]);
    return path;
  }

  /** Walk the avatar to a tile centre along a BFS path (drives the same input path as the stick).
   *  Re-plans when it stops making progress (chunks that weren't loaded yet count as open). */
  devWalkTo(tx: number, ty: number): Promise<boolean> {
    const path = this.planPath(tx, ty);
    if (!path) return Promise.resolve(false);
    return new Promise((resolve) => {
      const now = performance.now();
      this.autopilot = { path, goal: [tx, ty], done: resolve, lastProgress: now, started: now };
    });
  }

  private fight: { until: number; done: () => void; heavyEvery: number; n: number } | null = null;

  /** Dev: chase the nearest monster and fight it for `ms` (screenshot runner). */
  devFight(ms: number, heavyEvery = 0): Promise<void> {
    return new Promise((resolve) => {
      this.fight = { until: performance.now() + ms, done: resolve, heavyEvery, n: 0 };
    });
  }

  devNearestMonster(): { x: number; y: number; d: number; key: string } | null {
    const c = this.avatar?.client;
    if (!c) return null;
    let best: { x: number; y: number; d: number; key: string } | null = null;
    const rt = c.renderTick();
    for (const e of c.ents.values()) {
      if (e.kind !== ENT.monster) continue;
      const s = c.sampleAt(e, rt);
      if (!s || s.anim === 8) continue;
      const d = Math.hypot(s.x - c.me.x, s.y - c.me.y);
      if (!best || d < best.d) best = { x: s.x, y: s.y, d, key: e.type };
    }
    return best;
  }

  private steerFight(c: RoomClient): boolean {
    const f = this.fight;
    if (!f) return false;
    if (performance.now() > f.until) {
      this.fight = null;
      touchInput.active = false;
      touchInput.mx = touchInput.my = 0;
      touchInput.held = 0;
      f.done();
      return false;
    }
    const m = this.devNearestMonster();
    if (!m) return false;
    const dx = m.x - c.me.x;
    const dy = m.y - c.me.y;
    const l = Math.hypot(dx, dy) || 1;
    touchInput.active = true;
    touchInput.mx = l > 1.3 ? dx / l : 0;
    touchInput.my = l > 1.3 ? dy / l : 0;
    c.input.ax = Math.round((dx / l) * 127);
    c.input.ay = Math.round((dy / l) * 127);
    touchInput.held = l < 2.0 ? BTN.light : 0;
    if (l < 2.0 && f.heavyEvery && ++f.n % f.heavyEvery === 0) touchInput.latched |= BTN.heavy;
    return true;
  }

  private steerAutopilot(c: RoomClient): void {
    const ap = this.autopilot;
    if (!ap) return;
    const now = performance.now();
    while (ap.path.length) {
      const [x, y] = ap.path[0];
      const dx = x + 0.5 - c.me.x;
      const dy = y + 0.5 - c.me.y;
      const next = ap.path[1];
      const past = next && Math.hypot(next[0] + 0.5 - c.me.x, next[1] + 0.5 - c.me.y) <= 1.0;
      if (dx * dx + dy * dy < 0.12 || past) {
        ap.path.shift();
        ap.lastProgress = now;
      } else break;
    }
    const finish = (ok: boolean) => {
      touchInput.active = false;
      touchInput.mx = touchInput.my = 0;
      this.autopilot = null;
      ap.done(ok);
    };
    if (!ap.path.length) return finish(true);
    if (now - ap.started > 120000) return finish(false);
    if (now - ap.lastProgress > 1500) {
      const again = this.planPath(ap.goal[0], ap.goal[1]);
      if (!again) return finish(false);
      ap.path = again;
      ap.lastProgress = now;
    }
    const [x, y] = ap.path[0];
    const dx = x + 0.5 - c.me.x;
    const dy = y + 0.5 - c.me.y;
    const l = Math.hypot(dx, dy);
    // ease in on the last waypoint so slow frames (several sim steps each) can't overshoot it forever
    const k = ap.path.length === 1 ? Math.min(1, Math.max(0.25, l / 0.6)) : 1;
    touchInput.active = true;
    touchInput.mx = (dx / l) * k;
    touchInput.my = (dy / l) * k;
  }

  private avatarKey(k: string, e: KeyboardEvent): void {
    const c = this.avatar!.client;
    const av = useAvatar.getState();
    // Phase 16b: while the fishing bar runs, interact or dodge reels in (instead of rolling off the bank)
    if ((isKey(k, "dodge") || isKey(k, "interact")) && useFishing.getState().phase === "bite") {
      e.preventDefault();
      reelNow();
      return;
    }
    if (isKey(k, "ride")) roomLink.send?.("RIDE");
    else if (isKey(k, "dodge")) {
      e.preventDefault();
      c.input.latched |= BTN.dodge;
    } else if (isKey(k, "ability")) c.input.latched |= BTN.ability;
    else if (isKey(k, "heavy")) c.input.latched |= BTN.heavy;
    else if (isKey(k, "potion")) c.input.latched |= BTN.potion;
    else if (isKey(k, "quick1")) c.useQuick(0);
    else if (isKey(k, "quick2")) c.useQuick(1);
    else if (isKey(k, "quick3")) c.useQuick(2);
    else if (isKey(k, "quick4")) c.useQuick(3);
    else if (isKey(k, "bag")) {
      e.preventDefault();
      av.set({ bagOpen: !av.bagOpen });
    } else if (isKey(k, "emote")) {
      const so = useSocial.getState();
      so.set({ chatOpen: !so.chatOpen });
    } else if (k === "escape") {
      av.set({ bagOpen: false });
      useSocial.getState().set({ chatOpen: false });
      useMarket.getState().set({ merchantOpen: false });
      useRealm.getState().set({ wildMerchant: null, lore: null });
    } else if (isKey(k, "interact")) this.interact();
    else if (isKey(k, "home")) leaveAvatar();
    else if (k === "+" || k === "=") this.zoomAvatar(1);
    else if (k === "-") this.zoomAvatar(-1);
  }

  /** E (or LT on a gamepad): trade, travel, pull a lever, open a chest, or cast a line. */
  private interact(): void {
    const m = useMarket.getState();
    const r = useRealm.getState();
    if (useFishing.getState().phase === "bite") reelNow();
    else if (m.near) m.set({ merchantOpen: !m.merchantOpen });
    else if (r.nearWaystone !== null) r.set({ mapOpen: !r.mapOpen, travelMode: true });
    else if (useDelve.getState().near) {
      const n = useDelve.getState().near!;
      if (n.kind === "portal") roomLink.send?.("DUNGEON", "portal");
      else roomLink.send?.("DUNGEON", "use", n.prop);
    } else if (r.nearPoi !== null) {
      const poi = r.overview?.pois[r.nearPoi];
      if (poi?.kind === "delve") useDelve.getState().set({ panel: !useDelve.getState().panel });
      else roomLink.send?.("INTERACT", r.nearPoi);
    } else if (useFishing.getState().phase === "idle" && this.nearFishable()) roomLink.send?.("FISH", "cast");
  }

  /** Phase 18: numbers for the perf overlay (F3). */
  perf(): { fps: number; frameMs: number; sprites: number; ents: number } {
    let sprites = 0;
    const count = (c: Container) => {
      for (const ch of c.children) {
        if (!ch.visible) continue;
        sprites++;
        // a terrain chunk is cached as one texture: it draws as one sprite, whatever is inside
        if ((ch as Container).children?.length && !(ch as Container).isCachedAsTexture) count(ch as Container);
      }
    };
    count(this.app.stage);
    return { fps: this.app.ticker.FPS, frameMs: this.app.ticker.elapsedMS, sprites, ents: this.avatar?.client.ents.size ?? 0 };
  }

  /** Photo mode (Phase 16b): show or hide the names over heads. */
  setNames(show: boolean): void {
    this.screen.visible = show;
  }

  /** Photo mode: the current frame as a canvas, exactly what's on screen (minus the HTML HUD). */
  snapshot(): HTMLCanvasElement {
    const frame = new Rectangle(0, 0, this.app.screen.width, this.app.screen.height);
    return this.app.renderer.extract.canvas({ target: this.app.stage, frame }) as HTMLCanvasElement;
  }

  /** Is there water, ice or lava within casting reach of the hero? (The server decides for real.) */
  nearFishable(): boolean {
    const c = this.avatar?.client;
    const reach = useSession.getState().config?.fishing.reach ?? 1.6;
    if (!c || c.info.weapon === undefined) return false;
    const { x, y } = c.me;
    const r = Math.ceil(reach);
    for (let dy = -r; dy <= r; dy++) {
      for (let dx = -r; dx <= r; dx++) {
        const tx = Math.floor(x) + dx;
        const ty = Math.floor(y) + dy;
        if (!this.fishTiles.has(`${tx},${ty}`)) continue;
        const ddx = Math.max(tx - x, 0, x - (tx + 1));
        const ddy = Math.max(ty - y, 0, y - (ty + 1));
        if (Math.hypot(ddx, ddy) <= reach) return true;
      }
    }
    return false;
  }

  private zoomAvatar(dir: number): void {
    const cur = ZOOMS.indexOf(Math.round(this.cam.zoom));
    const next = ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, (cur < 0 ? 1 : cur) + dir))];
    if (next === this.cam.zoom || this.camTween) return;
    this.zoomTween?.kill();
    this.zoomTween = gsap.to(this.cam, { zoom: next, duration: 0.2, ease: "power2.out" });
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
    if (this.avatar) return;
    const store = useVillage.getState();
    if (!store.placing) {
      const id = this.debrisAt(sx, sy);
      if (id !== this.hoverDebris) {
        if (this.hoverDebris !== null) {
          const old = this.debrisSprite(this.hoverDebris);
          if (old && !old.destroyed) old.tint = 0xffffff;
        }
        this.hoverDebris = id;
        const s = id !== null ? this.debrisSprite(id) : undefined;
        if (s) s.tint = 0xfff2c0;
        this.app.canvas.style.cursor = id !== null || this.buildingAt(sx, sy) ? "pointer" : "grab";
      }
      return;
    }
    const [tx, ty] = this.ghostTileFor(sx, sy);
    this.hoverTile = [tx, ty];
    store.setGhost(tx, ty);
  }

  private tap(sx: number, sy: number): void {
    if (this.avatar) return;
    const store = useVillage.getState();
    if (store.placing) {
      const [tx, ty] = this.ghostTileFor(sx, sy);
      store.setGhost(tx, ty);
      if (!this.touchMode) store.confirmPlacement();
      return;
    }
    const b = this.buildingAt(sx, sy);
    if (!b) {
      const d = this.debrisAt(sx, sy);
      if (d !== null) {
        store.select(null);
        void this.clearDebris(d);
        return;
      }
    }
    store.select(b);
  }

  /** Phase 14: the building under a page point (drag a villager onto it to put them to work). */
  buildingAtClient(clientX: number, clientY: number): string | null {
    const r = this.app.canvas.getBoundingClientRect();
    return this.buildingAt(clientX - r.left, clientY - r.top);
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
