// Atlas loading + sprite naming. All names come from the generated manifest (tools/artgen).
import { Assets, Rectangle, Spritesheet, Texture, TextureStyle } from "pixi.js";
import type { BuildingState } from "../api/types";
import { manifest } from "../assets/manifest";
import { rotatedFootprint } from "./placement";

TextureStyle.defaultOptions.scaleMode = "nearest";

let sheet: Spritesheet | null = null;

export async function loadWorldAtlas(): Promise<Spritesheet> {
  if (!sheet) sheet = (await Assets.load(manifest.atlases.world)) as Spritesheet;
  return sheet;
}

export function tex(name: string): Texture {
  const t = sheet?.textures[name];
  if (!t) throw new Error(`missing sprite ${name}`);
  return t;
}

let iconSource: Texture | null = null;
const iconCache = new Map<string, Texture>();

export async function loadIconAtlas(): Promise<void> {
  if (!iconSource) iconSource = (await Assets.load(manifest.icons.image)) as Texture;
}

/** A 16×16 item/resource icon as a Pixi texture (icons.png grid). */
export function iconTex(name: string): Texture {
  const key = name.replace(/^icon\./, "");
  const hit = iconCache.get(key);
  if (hit) return hit;
  if (!iconSource) throw new Error("icon atlas not loaded");
  const { size, cols, names } = manifest.icons;
  const i = names[key] ?? names["info"];
  const t = new Texture({ source: iconSource.source, frame: new Rectangle((i % cols) * size, Math.floor(i / cols) * size, size, size) });
  iconCache.set(key, t);
  return t;
}

export function hasSprite(name: string): boolean {
  return Boolean(sheet?.textures[name]);
}

export interface BuildingLook {
  name: string;
  mirror: boolean;
  anchorTop: number; // px from the sprite's top to the footprint's top edge
}

export function buildingLook(
  key: string,
  footprint: [number, number],
  b: Pick<BuildingState, "rotation" | "level" | "state">,
): BuildingLook {
  const [w, h] = rotatedFootprint(footprint, b.rotation);
  if (b.state === "constructing" && b.level === 0) {
    const name = `building.scaffold.${w}x${h}`;
    return { name, mirror: false, anchorTop: manifest.sprites[name]?.anchor?.[1] ?? 0 };
  }
  const level = Math.max(1, Math.min(5, b.level));
  const variant = b.rotation % 2 && manifest.sprites[`building.${key}.b.l${level}`] ? "b" : "a";
  const name = `building.${key}.${variant}.l${level}`;
  return { name, mirror: b.rotation >= 2, anchorTop: manifest.sprites[name]?.anchor?.[1] ?? 0 };
}
