// Phase 9: your realm-mates' villages, drawn read-only in the world (buildings, their wild debris and a
// name sign). Kept in sync from GET /api/realm/villages plus live VILLAGE_STATE pushes for each mate.
import { Container, Sprite, Text } from "pixi.js";
import type { BuildingDef } from "../api/types";
import type { MateVillage } from "../state/realm";
import { useSession } from "../state/session";
import { rotatedFootprint } from "./placement";
import { safeDestroy } from "./safe";
import { buildingLook, tex } from "./sprites";

const T = 16;
const INK = 0x2b1e2a;

interface Drawn {
  version: number;
  sprites: Container[];
}

export class MateVillages {
  private drawn = new Map<string, Drawn>();

  constructor(
    private objects: Container,
    private defs: () => Record<string, BuildingDef>,
  ) {}

  sync(list: MateVillage[]): void {
    const keep = new Set(list.map((v) => v.owner_id));
    for (const [id, d] of this.drawn) {
      if (!keep.has(id)) {
        for (const s of d.sprites) safeDestroy(s);
        this.drawn.delete(id);
      }
    }
    for (const v of list) {
      const cur = this.drawn.get(v.owner_id);
      if (cur && cur.version === v.version) continue;
      if (cur) for (const s of cur.sprites) safeDestroy(s);
      this.drawn.set(v.owner_id, { version: v.version, sprites: this.draw(v) });
    }
  }

  private draw(v: MateVillage): Container[] {
    const out: Container[] = [];
    const defs = this.defs();
    const [ox, oy] = v.origin;
    for (const b of v.buildings) {
      const def = defs[b.key];
      if (!def) continue;
      const look = buildingLook(b.key, def.footprint, b);
      const [, h] = rotatedFootprint(def.footprint, b.rotation);
      const s = new Sprite(tex(look.name));
      s.scale.x = look.mirror ? -1 : 1;
      s.position.set((ox + b.x) * T + (look.mirror ? s.texture.width : 0), (oy + b.y) * T - look.anchorTop);
      s.zIndex = (oy + b.y + h) * T;
      this.objects.addChild(s);
      out.push(s);
    }
    const config = useSession.getState().config!;
    for (const [, kind, variant, x, y] of v.debris) {
      const name = config.debris[kind]?.sprites[variant] ?? "obj.bush.0";
      const s = new Sprite(tex(name));
      s.anchor.set(0.5, 1);
      const wy = (oy + y) * T + T - 1;
      s.position.set((ox + x) * T + T / 2, wy);
      s.zIndex = wy;
      this.objects.addChild(s);
      out.push(s);
    }
    // a little sign at the gate so you know whose village it is
    const label = new Text({
      text: v.name,
      style: { fontFamily: "Pixelify Sans", fontSize: 11, fill: 0xfaf2dd, stroke: { color: INK, width: 3 }, fontWeight: "600" },
    });
    label.anchor.set(0.5, 1);
    label.resolution = 2;
    label.position.set((ox + v.gate[0] + 0.5) * T, (oy + v.gate[1]) * T - 4);
    label.zIndex = 1e6;
    this.objects.addChild(label);
    out.push(label);
    return out;
  }

  destroy(): void {
    for (const d of this.drawn.values()) for (const s of d.sprites) safeDestroy(s);
    this.drawn.clear();
  }
}
