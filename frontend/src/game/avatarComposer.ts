// Builds a recoloured, outlined 18-frame character strip from the layered sheet (tools/artgen characters.py).
import type { Appearance } from "../api/types";
import { manifest } from "../assets/manifest";

const OUTLINE = [0x2b, 0x1e, 0x2a];
let sheet: Promise<HTMLImageElement> | null = null;
const cache = new Map<string, HTMLCanvasElement>();

function loadSheet(): Promise<HTMLImageElement> {
  if (!sheet) {
    sheet = new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = manifest.chars.image;
    });
  }
  return sheet;
}

function hexToRgb(h: string): [number, number, number] {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function layerStack(a: Appearance): { layer: string; ramp: string[] }[] {
  const r = manifest.recolor;
  return [
    { layer: `char.body.${a.body}`, ramp: r.skin[a.skin] },
    { layer: `char.outfit.${a.outfit}.${a.body}`, ramp: r.outfit[a.outfit_color] },
    { layer: `char.eyes.${a.eyes}`, ramp: r.eyes[a.eye_color] },
    { layer: `char.hair.${a.hair_style}`, ramp: r.hair[a.hair_color] },
  ];
}

export function appearanceKey(a: Appearance): string {
  return [a.body, a.skin, a.hair_style, a.hair_color, a.eyes, a.eye_color, a.outfit, a.outfit_color].join("|");
}

/** Recolour + stack + outline on raw RGBA buffers (pure, unit-tested). */
export function composePixels(
  layers: { data: Uint8ClampedArray; ramp: [number, number, number][] }[],
  keys: [number, number, number][],
  width: number,
  height: number,
  frameW: number,
): Uint8ClampedArray<ArrayBuffer> {
  const out = new Uint8ClampedArray(new ArrayBuffer(width * height * 4));
  for (const { data, ramp } of layers) {
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] === 0) continue;
      let r = data[i], g = data[i + 1], b = data[i + 2];
      for (let k = 0; k < keys.length; k++) {
        if (r === keys[k][0] && g === keys[k][1] && b === keys[k][2]) {
          [r, g, b] = ramp[k];
          break;
        }
      }
      out[i] = r;
      out[i + 1] = g;
      out[i + 2] = b;
      out[i + 3] = data[i + 3];
    }
  }
  // 1 px silhouette outline, never bleeding across frame boundaries
  const res = new Uint8ClampedArray(out.buffer.slice(0));
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      if (out[i + 3] !== 0) continue;
      const fx = Math.floor(x / frameW);
      const nbrs: [number, number][] = [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]];
      for (const [nx, ny] of nbrs) {
        if (nx < 0 || ny < 0 || nx >= width || ny >= height || Math.floor(nx / frameW) !== fx) continue;
        if (out[(ny * width + nx) * 4 + 3] === 255) {
          res[i] = OUTLINE[0];
          res[i + 1] = OUTLINE[1];
          res[i + 2] = OUTLINE[2];
          res[i + 3] = 255;
          break;
        }
      }
    }
  }
  return res;
}

/** A canvas strip of 18 frames (see manifest.chars.frames) for this look. Cached. */
export async function composeAvatar(a: Appearance): Promise<HTMLCanvasElement> {
  const key = appearanceKey(a);
  const hit = cache.get(key);
  if (hit) return hit;
  const img = await loadSheet();
  const [fw, fh] = manifest.chars.frame;
  const width = fw * manifest.chars.frames.length;
  const scratch = document.createElement("canvas");
  scratch.width = img.width;
  scratch.height = img.height;
  const sctx = scratch.getContext("2d", { willReadFrequently: true })!;
  sctx.drawImage(img, 0, 0);
  const layers = layerStack(a).map(({ layer, ramp }) => {
    const row = manifest.chars.layers[layer] ?? 0;
    return {
      data: sctx.getImageData(0, row * fh, width, fh).data,
      ramp: ramp.map(hexToRgb),
    };
  });
  const pixels = composePixels(layers, manifest.chars.shadeKeys.map(hexToRgb), width, fh, fw);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = fh;
  canvas.getContext("2d")!.putImageData(new ImageData(pixels, width, fh), 0, 0);
  cache.set(key, canvas);
  return canvas;
}

export const FRAME_INDEX: Record<string, number> = Object.fromEntries(
  manifest.chars.frames.map((name, i) => [name, i]),
);

/** Frame index for a direction ("down" | "up" | "left" | "right") + animation at time t (ms). */
export function frameFor(dir: string, anim: "idle" | "walk", tMs: number): { index: number; flip: boolean } {
  const base = dir === "left" || dir === "right" ? "side" : dir;
  const count = anim === "walk" ? 4 : 2;
  const fps = anim === "walk" ? 8 : 2;
  const i = Math.floor((tMs / 1000) * fps) % count;
  return { index: FRAME_INDEX[`${base}.${anim}.${i}`], flip: dir === "right" };
}
