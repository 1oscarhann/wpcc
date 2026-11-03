// Typed access to the generated asset manifest (tools/artgen). Code never hard-codes art paths.
import raw from "./manifest.json";

export interface SpriteMeta {
  atlas: string;
  footprint?: [number, number];
  anchor?: [number, number];
}

export interface Manifest {
  version: number;
  tileSize: number;
  atlases: Record<string, string>;
  sprites: Record<string, SpriteMeta>;
  blobMasks: number[];
  chars: {
    image: string;
    frame: [number, number];
    frames: string[];
    layers: Record<string, number>;
    shadeKeys: string[];
  };
  recolor: Record<"skin" | "hair" | "eyes" | "outfit", Record<string, string[]>>;
  icons: { image: string; size: number; cols: number; names: Record<string, number> };
  ui: Record<string, string>;
  title: string;
  fonts: { heading: string; body: string };
}

export const manifest = raw as unknown as Manifest;

export function iconIndex(name: string): number {
  const i = manifest.icons.names[name];
  return i === undefined ? manifest.icons.names["info"] : i;
}
