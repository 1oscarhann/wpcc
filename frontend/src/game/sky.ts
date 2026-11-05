// Phase 10 sky: day/night lighting with real light pools, season and weather tint, and weather
// particles (rain, snow, ash, fog, storm lightning). All screen-space, drawn over the world and under
// the UI layer. Lighting is one multiply pass: a base colour (season × weather × dusk glow → night
// blue) with additive light sprites rendered into a small render texture each frame.
import { type Application, Container, RenderTexture, Sprite, Texture } from "pixi.js";
import type { DayPhase, Weather } from "../state/world";
import { precipitation } from "../state/world";
import { sfx } from "./sfx";

export interface Light {
  x: number; // screen px
  y: number;
  r: number; // screen px
  color: number;
  power?: number; // 0..1.5
  flicker?: boolean;
}

const SEASON: Record<string, number> = {
  spring: 0xfdf8f0,
  summer: 0xfff3dc,
  autumn: 0xffe2bf,
  winter: 0xe6edf8,
};
const WEATHER_TINT: Record<Weather, number> = {
  clear: 0xffffff,
  rain: 0xd8dee8,
  snow: 0xeef2f8,
  fog: 0xe9ecef,
  storm: 0xb6bdcc,
};
const GLOW = 0xffc58f;
const NIGHT = 0x56649c;

function rgb(c: number): [number, number, number] {
  return [(c >> 16) & 255, (c >> 8) & 255, c & 255];
}
function mul(a: number, b: number): number {
  const [ar, ag, ab] = rgb(a);
  const [br, bg, bb] = rgb(b);
  return (((ar * br) / 255) << 16) | (((ag * bg) / 255) << 8) | ((ab * bb) / 255);
}
function lerp(a: number, b: number, t: number): number {
  const [ar, ag, ab] = rgb(a);
  const [br, bg, bb] = rgb(b);
  const k = Math.max(0, Math.min(1, t));
  return (Math.round(ar + (br - ar) * k) << 16) | (Math.round(ag + (bg - ag) * k) << 8) | Math.round(ab + (bb - ab) * k);
}

function canvasTex(w: number, h: number, paint: (ctx: CanvasRenderingContext2D) => void): Texture {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  paint(c.getContext("2d")!);
  const t = Texture.from(c);
  t.source.scaleMode = "linear";
  return t;
}

let textures: Record<string, Texture> | null = null;
function tex(): Record<string, Texture> {
  if (textures) return textures;
  textures = {
    light: canvasTex(128, 128, (ctx) => {
      const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
      g.addColorStop(0, "rgba(255,255,255,1)");
      g.addColorStop(0.35, "rgba(255,255,255,0.75)");
      g.addColorStop(0.7, "rgba(255,255,255,0.25)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 128, 128);
    }),
    rain: canvasTex(2, 12, (ctx) => {
      const g = ctx.createLinearGradient(0, 0, 0, 12);
      g.addColorStop(0, "rgba(200,225,250,0)");
      g.addColorStop(1, "rgba(220,238,255,0.85)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 2, 12);
    }),
    snow: canvasTex(6, 6, (ctx) => {
      const g = ctx.createRadialGradient(3, 3, 0, 3, 3, 3);
      g.addColorStop(0, "rgba(255,255,255,1)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 6, 6);
    }),
    ash: canvasTex(4, 4, (ctx) => {
      ctx.fillStyle = "rgba(120,110,108,0.9)";
      ctx.fillRect(1, 1, 2, 2);
    }),
    ember: canvasTex(6, 6, (ctx) => {
      const g = ctx.createRadialGradient(3, 3, 0, 3, 3, 3);
      g.addColorStop(0, "rgba(255,224,138,1)");
      g.addColorStop(0.5, "rgba(234,90,36,0.8)");
      g.addColorStop(1, "rgba(234,90,36,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 6, 6);
    }),
    fog: canvasTex(256, 160, (ctx) => {
      for (const [x, y, r] of [[128, 80, 80], [70, 90, 55], [190, 85, 60], [110, 60, 50], [160, 70, 45]]) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, "rgba(240,244,248,0.5)");
        g.addColorStop(1, "rgba(240,244,248,0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, 256, 160);
      }
    }),
  };
  return textures;
}

interface Particle {
  s: Sprite;
  vx: number;
  vy: number;
  life: number;
  kind: string;
}

export class Sky {
  /** Add this between the world and the screen-space UI. */
  readonly layer = new Container();
  private scene = new Container();
  private base = new Sprite(Texture.WHITE);
  private lightPool: Sprite[] = [];
  private rt: RenderTexture | null = null;
  private dark = new Sprite();
  private flat = new Sprite(Texture.WHITE);
  private haze = new Sprite(Texture.WHITE);
  private flash = new Sprite(Texture.WHITE);
  private fx = new Container();
  private fogs: Sprite[] = [];
  private parts: Particle[] = [];
  private kind = "none";
  private w = 0;
  private h = 0;
  private time = 0;
  private nextBolt = 6;
  private flashT = 0;
  reduceMotion = false;

  constructor(private app: Application) {
    this.scene.addChild(this.base);
    this.dark.blendMode = "multiply";
    this.flat.blendMode = "multiply";
    this.haze.alpha = 0;
    this.flash.alpha = 0;
    this.flash.blendMode = "add";
    this.layer.addChild(this.flat, this.dark, this.fx, this.haze, this.flash);
    this.layer.eventMode = "none";
  }

  destroy(): void {
    this.rt?.destroy(true);
    this.layer.destroy({ children: true });
    this.scene.destroy({ children: true });
  }

  private resize(w: number, h: number): void {
    if (w === this.w && h === this.h) return;
    this.w = w;
    this.h = h;
    this.rt?.destroy(true);
    // half resolution is plenty for soft light, and keeps the extra pass cheap on phones
    this.rt = RenderTexture.create({ width: Math.max(1, Math.ceil(w / 2)), height: Math.max(1, Math.ceil(h / 2)) });
    this.rt.source.scaleMode = "linear";
    this.dark.texture = this.rt;
    for (const s of [this.flat, this.dark, this.haze, this.flash]) s.setSize(w, h);
    this.base.setSize(this.rt.width, this.rt.height);
  }

  update(
    dt: number,
    o: { phase: DayPhase; season: string; weather: Weather; biome: string; lights: Light[] },
  ): void {
    const { width: w, height: h } = this.app.screen;
    this.resize(w, h);
    this.time += dt;
    // ── colour ──
    let col = mul(SEASON[o.season] ?? 0xffffff, WEATHER_TINT[o.weather] ?? 0xffffff);
    if (o.biome === "ashen") col = mul(col, 0xf2dccb);
    col = lerp(col, mul(col, GLOW), o.phase.glow * 0.7);
    col = lerp(col, NIGHT, o.phase.dark * 0.9);
    const lit = o.phase.dark > 0.02 || o.weather === "storm";
    this.flat.visible = !lit;
    this.dark.visible = lit;
    if (!lit) {
      this.flat.tint = col;
    } else if (this.rt) {
      this.base.tint = col;
      const strength = Math.max(o.phase.dark, o.weather === "storm" ? 0.35 : 0);
      let i = 0;
      for (const l of o.lights) {
        let s = this.lightPool[i];
        if (!s) {
          s = new Sprite(tex().light);
          s.anchor.set(0.5);
          s.blendMode = "add";
          this.scene.addChild(s);
          this.lightPool.push(s);
        }
        s.visible = true;
        const fl = l.flicker ? 0.92 + Math.sin(this.time * 9 + i * 1.7) * 0.05 + Math.sin(this.time * 23 + i) * 0.03 : 1;
        s.position.set(l.x / 2, l.y / 2);
        s.width = s.height = (l.r * 2 * fl) / 2;
        s.tint = l.color;
        s.alpha = Math.min(1, strength * (l.power ?? 1) * fl);
        i++;
      }
      for (; i < this.lightPool.length; i++) this.lightPool[i].visible = false;
      this.app.renderer.render({ container: this.scene, target: this.rt, clear: true });
    }
    // ── weather ──
    const kind = precipitation(o.weather, o.biome);
    if (kind !== this.kind) this.setKind(kind);
    this.updateParticles(dt, o.weather);
    this.updateFog(dt, o.weather === "fog" || (o.weather === "snow" && o.biome === "frozen"));
    // ── lightning ──
    if (o.weather === "storm" && !this.reduceMotion) {
      this.nextBolt -= dt;
      if (this.nextBolt <= 0) {
        this.nextBolt = 7 + Math.random() * 12;
        this.flashT = 0.45;
        window.setTimeout(() => sfx("thunder"), 250 + Math.random() * 900);
      }
    }
    if (this.flashT > 0) {
      this.flashT -= dt;
      const t = this.flashT;
      this.flash.alpha = t > 0.3 ? 0.5 : t > 0.22 ? 0.08 : t > 0 ? (t / 0.22) * 0.38 : 0;
    } else this.flash.alpha = 0;
  }

  private setKind(kind: string): void {
    this.kind = kind;
    for (const p of this.parts) p.s.destroy();
    this.parts = [];
  }

  private updateParticles(dt: number, weather: Weather): void {
    const area = (this.w * this.h) / (1440 * 900);
    const k = this.kind;
    const per = k === "rain" ? (weather === "storm" ? 260 : 150) : k === "snow" ? (weather === "snow" || weather === "storm" ? 140 : 80) : k === "ash" ? 70 : 0;
    const want = Math.round(per * Math.min(1.4, Math.max(0.35, area)) * (this.reduceMotion ? 0.4 : 1));
    while (this.parts.length < want) this.parts.push(this.spawn(k, true));
    while (this.parts.length > want) this.parts.pop()!.s.destroy();
    const windX = weather === "storm" ? -140 : -50;
    for (let i = 0; i < this.parts.length; i++) {
      const p = this.parts[i];
      p.life += dt;
      if (p.kind === "snow" || p.kind === "ash") p.s.x += Math.sin(p.life * 1.7 + i) * 12 * dt;
      p.s.x += p.vx * dt + (p.kind === "rain" ? windX * dt * 0.2 : 0);
      p.s.y += p.vy * dt;
      if (p.kind === "ember") p.s.alpha = 0.6 + Math.sin(p.life * 6 + i) * 0.35;
      if (p.s.y > this.h + 20 || p.s.y < -40 || p.s.x < -40 || p.s.x > this.w + 40) {
        p.s.destroy();
        this.parts[i] = this.spawn(k, false);
      }
    }
  }

  private spawn(kind: string, anywhere: boolean): Particle {
    const t = tex();
    let p: Particle;
    if (kind === "rain") {
      const s = new Sprite(t.rain);
      s.rotation = 0.12;
      s.alpha = 0.45 + Math.random() * 0.35;
      s.scale.set(1, 0.8 + Math.random() * 0.8);
      p = { s, vx: -60, vy: 560 + Math.random() * 180, life: 0, kind };
    } else if (kind === "snow") {
      const s = new Sprite(t.snow);
      s.scale.set(0.6 + Math.random() * 0.9);
      s.alpha = 0.7 + Math.random() * 0.3;
      p = { s, vx: -10 - Math.random() * 15, vy: 30 + Math.random() * 40, life: Math.random() * 10, kind };
    } else {
      const ember = Math.random() < 0.25;
      const s = new Sprite(ember ? t.ember : t.ash);
      s.scale.set(ember ? 0.8 + Math.random() * 0.6 : 0.8 + Math.random());
      s.blendMode = ember ? "add" : "normal";
      p = { s, vx: -8 - Math.random() * 10, vy: ember ? -12 - Math.random() * 18 : 14 + Math.random() * 18, life: Math.random() * 10, kind: ember ? "ember" : "ash" };
    }
    p.s.anchor.set(0.5);
    p.s.position.set(Math.random() * (this.w + 80) - 20, anywhere ? Math.random() * this.h : p.vy < 0 ? this.h + 10 : -20);
    this.fx.addChild(p.s);
    return p;
  }

  private updateFog(dt: number, on: boolean): void {
    const target = on ? 0.16 : 0;
    this.haze.alpha += (target - this.haze.alpha) * Math.min(1, dt * 0.8);
    this.haze.tint = 0xeef2f6;
    if (on && this.fogs.length === 0) {
      for (let i = 0; i < 6; i++) {
        const s = new Sprite(tex().fog);
        s.anchor.set(0.5);
        s.scale.set(3 + Math.random() * 2, 2 + Math.random());
        s.position.set(Math.random() * this.w, Math.random() * this.h);
        s.alpha = 0;
        this.fx.addChild(s);
        this.fogs.push(s);
      }
    }
    for (let i = 0; i < this.fogs.length; i++) {
      const s = this.fogs[i];
      s.x += (14 + i * 3) * dt;
      if (s.x - s.width / 2 > this.w) s.x = -s.width / 2;
      s.alpha += ((on ? 0.75 : 0) - s.alpha) * Math.min(1, dt * 0.6);
    }
    if (!on && this.fogs.length && this.fogs.every((s) => s.alpha < 0.02)) {
      for (const s of this.fogs) s.destroy();
      this.fogs = [];
    }
  }
}
