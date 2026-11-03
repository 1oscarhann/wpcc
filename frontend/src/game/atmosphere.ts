// Soft, large-scale lighting on top of the pixel art: ground colour variation, warm sun patches and
// drifting cloud shadows. These are smooth (linear-filtered) on purpose, like light in a real scene.
import { Container, Sprite, Texture, TilingSprite } from "pixi.js";

function hash(x: number, y: number, seed: number): number {
  let h = (x * 374761393 + y * 668265263 + seed * 2147483647) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}

/** Tileable value noise in [0,1], `cells` lattice cells across `size` pixels, a few octaves. */
function tileableNoise(size: number, cells: number, seed: number, octaves = 3): Float32Array {
  const out = new Float32Array(size * size);
  let amp = 1;
  let total = 0;
  for (let o = 0; o < octaves; o++) {
    const c = cells << o;
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const gx = (x / size) * c;
        const gy = (y / size) * c;
        const x0 = Math.floor(gx);
        const y0 = Math.floor(gy);
        const fx = gx - x0;
        const fy = gy - y0;
        const sx = fx * fx * (3 - 2 * fx);
        const sy = fy * fy * (3 - 2 * fy);
        const h = (ix: number, iy: number) => hash(((ix % c) + c) % c, ((iy % c) + c) % c, seed + o * 31);
        const v = (h(x0, y0) * (1 - sx) + h(x0 + 1, y0) * sx) * (1 - sy) + (h(x0, y0 + 1) * (1 - sx) + h(x0 + 1, y0 + 1) * sx) * sy;
        out[y * size + x] += v * amp;
      }
    }
    total += amp;
    amp *= 0.5;
  }
  for (let i = 0; i < out.length; i++) out[i] /= total;
  return out;
}

function canvasTexture(size: number, paint: (img: ImageData) => void): Texture {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d")!;
  const img = ctx.createImageData(size, size);
  paint(img);
  ctx.putImageData(img, 0, 0);
  const t = Texture.from(c);
  t.source.scaleMode = "linear";
  t.source.addressMode = "repeat";
  return t;
}

/** Darker/lusher and lighter/drier grass patches (multiply) + warm sun pools (add). */
export function groundLighting(worldPx: number): Container {
  const layer = new Container();
  const n = tileableNoise(128, 4, 7);
  const shade = canvasTexture(128, (img) => {
    for (let i = 0; i < n.length; i++) {
      const v = Math.min(1, Math.max(0, (n[i] - 0.3) / 0.45)); // 0 = lush/dark, 1 = untouched
      img.data[i * 4] = 205 + 50 * v;
      img.data[i * 4 + 1] = 222 + 33 * v;
      img.data[i * 4 + 2] = 190 + 65 * v;
      img.data[i * 4 + 3] = 255;
    }
  });
  const m = tileableNoise(128, 3, 21);
  const sun = canvasTexture(128, (img) => {
    for (let i = 0; i < m.length; i++) {
      const v = Math.max(0, (m[i] - 0.58) / 0.42);
      img.data[i * 4] = 70 * v;
      img.data[i * 4 + 1] = 58 * v;
      img.data[i * 4 + 2] = 20 * v;
      img.data[i * 4 + 3] = 255;
    }
  });
  const a = new TilingSprite({ texture: shade, width: worldPx, height: worldPx });
  a.tileScale.set(24); // one noise texel ≈ 1.5 tiles → patches several tiles wide
  a.blendMode = "multiply";
  const b = new TilingSprite({ texture: sun, width: worldPx, height: worldPx });
  b.tileScale.set(30);
  b.blendMode = "add";
  b.alpha = 0.55;
  layer.addChild(a, b);
  return layer;
}

let cloudTex: Texture | null = null;

function cloudTexture(): Texture {
  if (cloudTex) return cloudTex;
  const w = 256;
  const c = document.createElement("canvas");
  c.width = w;
  c.height = w;
  const ctx = c.getContext("2d")!;
  // a lumpy cloud silhouette made of soft overlapping blobs
  const blobs = [[128, 128, 90], [70, 140, 60], [190, 135, 65], [110, 95, 55], [165, 100, 50]];
  for (const [x, y, r] of blobs) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, "rgba(40,40,70,0.55)");
    g.addColorStop(1, "rgba(40,40,70,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, w);
  }
  cloudTex = Texture.from(c);
  cloudTex.source.scaleMode = "linear";
  return cloudTex;
}

export class CloudShadows {
  layer = new Container();
  private clouds: { s: Sprite; vx: number; vy: number }[] = [];

  constructor(count = 5) {
    for (let i = 0; i < count; i++) {
      const s = new Sprite(cloudTexture());
      s.anchor.set(0.5);
      s.scale.set(1.6 + Math.random() * 1.4, 1.1 + Math.random() * 0.6);
      s.alpha = 0.22;
      s.blendMode = "multiply";
      this.layer.addChild(s);
      this.clouds.push({ s, vx: 7 + Math.random() * 4, vy: 3 + Math.random() * 2 });
    }
  }

  /** Keep clouds drifting across (and wrapping around) the visible rectangle, in world px. */
  update(dt: number, view: { x0: number; y0: number; x1: number; y1: number }): void {
    const w = view.x1 - view.x0;
    const h = view.y1 - view.y0;
    const pad = 500;
    for (const c of this.clouds) {
      if (c.s.x === 0 && c.s.y === 0) {
        c.s.position.set(view.x0 + Math.random() * w, view.y0 + Math.random() * h);
      }
      c.s.x += c.vx * dt;
      c.s.y += c.vy * dt;
      if (c.s.x > view.x1 + pad) c.s.x = view.x0 - pad + Math.random() * 100;
      if (c.s.x < view.x0 - pad * 1.5) c.s.x = view.x1 + pad - 100;
      if (c.s.y > view.y1 + pad) c.s.y = view.y0 - pad + Math.random() * 100;
      if (c.s.y < view.y0 - pad * 1.5) c.s.y = view.y1 + pad - 100;
    }
  }
}
