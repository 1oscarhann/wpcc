// Client twin of backend sim/grid.py: per-tile solidity from loaded chunks + village blocks.
// Unknown (not yet loaded) chunks count as open; the server corrects us if we guess wrong.
import world from "../../../shared/world.json";

interface RawChunk {
  ground: Uint8Array;
  objects: number[][];
}

export class ClientGrid {
  private raw = new Map<string, RawChunk>();
  private solidCache = new Map<string, Uint8Array>();
  private objCache = new Map<string, Map<number, number>>();
  private blocks = new Set<number>();
  private claimed = new Set<number>();
  private solidTiles: Set<number>;
  private solidObjs: Set<number>;

  constructor(
    readonly size: number,
    readonly cs: number,
    tileNames: string[],
    objectNames: string[],
    private plotOrigins: [number, number][],
    private frame = 48,
  ) {
    this.solidTiles = new Set(tileNames.flatMap((n, i) => (world.solid_tiles.some((p) => n.startsWith(p)) ? [i] : [])));
    this.solidObjs = new Set(objectNames.flatMap((n, i) => (world.solid_objects.some((p) => n.startsWith(p)) ? [i] : [])));
  }

  addChunk(cx: number, cy: number, ch: RawChunk): void {
    const k = `${cx}_${cy}`;
    this.raw.set(k, ch);
    this.solidCache.delete(k);
    this.objCache.delete(k);
  }

  setBlocks(rects: number[][], claimed: number[]): void {
    this.blocks.clear();
    for (const [x, y, w, h] of rects) {
      for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) this.blocks.add((y + j) * this.size + x + i);
    }
    const next = new Set(claimed);
    if ([...next].some((c) => !this.claimed.has(c)) || next.size !== this.claimed.size) {
      this.claimed = next;
      this.solidCache.clear();
      this.objCache.clear();
    }
  }

  private plotAt(x: number, y: number): number | null {
    for (let i = 0; i < this.plotOrigins.length; i++) {
      const [ox, oy] = this.plotOrigins[i];
      if (x >= ox && x < ox + this.frame && y >= oy && y < oy + this.frame) return i;
    }
    return null;
  }

  private build(cx: number, cy: number): [Uint8Array, Map<number, number>] | null {
    const k = `${cx}_${cy}`;
    const ch = this.raw.get(k);
    if (!ch) return null;
    const cs = this.cs;
    const solid = new Uint8Array(cs * cs);
    const objs = new Map<number, number>();
    for (let i = 0; i < ch.ground.length; i++) if (this.solidTiles.has(ch.ground[i])) solid[i] = 1;
    for (const [lx, ly, oid, flag] of ch.objects) {
      if (flag & 1) {
        const plot = this.plotAt(cx * cs + lx, cy * cs + ly);
        if (plot !== null && this.claimed.has(plot)) continue;
      }
      const idx = ly * cs + lx;
      objs.set(idx, oid);
      if (this.solidObjs.has(oid)) solid[idx] = 1;
    }
    this.solidCache.set(k, solid);
    this.objCache.set(k, objs);
    return [solid, objs];
  }

  solid = (x: number, y: number): boolean => {
    if (x < 0 || y < 0 || x >= this.size || y >= this.size) return true;
    if (this.blocks.has(y * this.size + x)) return true;
    const cx = Math.floor(x / this.cs);
    const cy = Math.floor(y / this.cs);
    const arr = this.solidCache.get(`${cx}_${cy}`) ?? this.build(cx, cy)?.[0];
    if (!arr) return false;
    return arr[(y - cy * this.cs) * this.cs + (x - cx * this.cs)] === 1;
  };

  objectAt(x: number, y: number): number | undefined {
    const cx = Math.floor(x / this.cs);
    const cy = Math.floor(y / this.cs);
    const objs = this.objCache.get(`${cx}_${cy}`) ?? this.build(cx, cy)?.[1];
    return objs?.get((y - cy * this.cs) * this.cs + (x - cx * this.cs));
  }
}

/** The live grid (owned by Game, which feeds it chunks). */
export const gridLink: { grid: ClientGrid | null } = { grid: null };
