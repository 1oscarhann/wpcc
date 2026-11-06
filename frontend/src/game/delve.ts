// Phase 12: draws the delve you're in. Tiles go into a cached floor layer, props into the y-sorted
// objects layer, gates and puzzle bits update from the delve store, and torches feed the sky's light.
import { AnimatedSprite, Container, Graphics, Sprite } from "pixi.js";
import type { DelveInfo, DelveState } from "../state/delve";
import type { Light } from "./sky";
import { safeDestroy } from "./safe";
import { tex } from "./sprites";

const T = 16;

interface PropView {
  kind: string;
  sprite: Sprite;
  x: number; // world px (tile centre)
  y: number;
  index: number;
  data: number;
}

export class DelveView {
  private floor = new Container();
  private props: PropView[] = [];
  private gates: { door: number; sprite: Sprite }[] = [];
  private portal: AnimatedSprite | null = null;
  private time = 0;

  constructor(
    private ground: Container,
    private objects: Container,
    readonly info: DelveInfo,
  ) {
    const { w, h, tiles } = info.layout;
    const [ox, oy] = info.origin;
    this.floor.position.set(ox * T, oy * T);
    // the void around the delve is pitch black
    this.floor.addChild(new Graphics().rect(-40 * T, -40 * T, (w + 80) * T, (h + 80) * T).fill({ color: 0x0d0a10 }));
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const t = tiles[y * w + x];
        if (t === 0) continue;
        let name: string;
        if (t === 2) {
          const below = y + 1 < h ? tiles[(y + 1) * w + x] : 0;
          name = below === 1 || below === 3 ? "tile.dwall.face" : "tile.dwall.top";
        } else name = `tile.dfloor.${(x * 7 + y * 13 + ((x * y) % 5)) % 4}`;
        const s = new Sprite(tex(name));
        s.position.set(x * T, y * T);
        this.floor.addChild(s);
      }
    }
    this.floor.cacheAsTexture(true);
    this.ground.addChild(this.floor);
    // gates: one portcullis per door tile, drawn standing on the tile
    for (const [id, ts] of info.layout.doors) {
      for (const [x, y] of ts) {
        const s = new Sprite(tex("obj.dgate.1"));
        s.anchor.set(0, 1);
        s.position.set((ox + x) * T, (oy + y + 1) * T);
        s.zIndex = (oy + y + 1) * T - 2;
        this.objects.addChild(s);
        this.gates.push({ door: id, sprite: s });
      }
    }
    info.layout.props.forEach(([kind, x, y, , data], index) => {
      const name = this.propSprite(kind, data, false);
      if (!name) return;
      const s = new Sprite(tex(name));
      const wx = (ox + x + 0.5) * T;
      const wy = (oy + y + 1) * T - 1;
      const wallMounted = kind === "torch" || kind === "banner";
      s.anchor.set(0.5, 1);
      s.position.set(wx, wallMounted ? wy - 2 : wy);
      s.zIndex = wallMounted ? wy + 1 : kind === "plate" ? wy - 14 : wy;
      this.objects.addChild(s);
      this.props.push({ kind, sprite: s, x: wx, y: wy - 8, index, data });
    });
  }

  private propSprite(kind: string, data: number, on: boolean): string | null {
    switch (kind) {
      case "torch":
        return "obj.dtorch.0";
      case "pillar":
        return "obj.dpillar.0";
      case "rubble":
        return `obj.drubble.${data % 2}`;
      case "bones":
        return `obj.dbones.${data % 2}`;
      case "crystal":
        return `obj.dcrystal.${data % 2}`;
      case "plate":
        return `obj.dplate.${on ? 1 : 0}`;
      case "lever":
        return `obj.dlever.${on ? 1 : 0}`;
      case "lamp":
        return `obj.dlamp.${on ? 1 : 0}`;
      case "chest":
        return `obj.chest.${on ? 1 : 0}`;
      case "banner":
        return "obj.dbanner.0";
      default:
        return null;
    }
  }

  /** Doors, plates, lamps, levers, chests and the portal follow the delve's state. */
  sync(state: DelveState, levers: Record<number, boolean>, chests: number[]): void {
    const locked = new Set(state.locked);
    for (const g of this.gates) g.sprite.texture = tex(locked.has(g.door) ? "obj.dgate.0" : "obj.dgate.1");
    const plates = new Set(state.plates);
    const opened = new Set(chests);
    const solved = new Set(state.solved);
    for (const p of this.props) {
      const room = this.info.layout.props[p.index][3];
      let on = false;
      if (p.kind === "plate") on = plates.has(p.index) || solved.has(room);
      else if (p.kind === "lamp") on = (state.lamps & (1 << p.data)) !== 0;
      else if (p.kind === "lever") on = Boolean(levers[p.index]);
      else if (p.kind === "chest") on = opened.has(p.index);
      else continue;
      p.sprite.texture = tex(this.propSprite(p.kind, p.data, on)!);
    }
    if (state.portal && !this.portal) {
      const boss = this.info.layout.rooms.find((r) => r[1] === "boss");
      if (boss) {
        const [, , x, y, w, h] = boss;
        const [ox, oy] = this.info.origin;
        this.portal = new AnimatedSprite([0, 1, 2, 3].map((i) => tex(`obj.dportal.${i}`)));
        this.portal.anchor.set(0.5, 1);
        this.portal.animationSpeed = 0.12;
        this.portal.position.set((ox + x + w / 2) * T, (oy + y + h / 2 + 2.6) * T);
        this.portal.zIndex = this.portal.y;
        this.objects.addChild(this.portal);
        this.portal.play();
      }
    }
  }

  portalPos(): { x: number; y: number } | null {
    return this.portal ? { x: this.portal.x / T, y: this.portal.y / T - 0.6 } : null;
  }

  /** Usable props near a tile position: levers and chests. */
  usableNear(x: number, y: number, r = 1.9): PropView | null {
    let best: PropView | null = null;
    let bd = r * r;
    for (const p of this.props) {
      if (p.kind !== "lever" && p.kind !== "chest") continue;
      const d = (p.x / T - x) ** 2 + (p.y / T + 0.5 - y) ** 2;
      if (d < bd) {
        bd = d;
        best = p;
      }
    }
    return best;
  }

  update(dms: number): void {
    this.time += dms;
    const f = Math.floor(this.time / 140) % 2;
    for (const p of this.props) if (p.kind === "torch") p.sprite.texture = tex(`obj.dtorch.${(f + p.index) % 2}`);
  }

  lights(state: DelveState | null): Light[] {
    const out: Light[] = [];
    for (const p of this.props) {
      if (p.kind === "torch") out.push({ x: p.x, y: p.y - 4, r: 72, color: 0xffb46a, flicker: true });
      else if (p.kind === "crystal") out.push({ x: p.x, y: p.y, r: 26, color: p.data % 2 ? 0xc993e8 : 0xa6dcff, flicker: false });
      else if (p.kind === "lamp" && state && state.lamps & (1 << p.data)) out.push({ x: p.x, y: p.y - 8, r: 40, color: 0xa6dcff, flicker: false });
      else if (p.kind === "plate" && state?.plates.includes(p.index)) out.push({ x: p.x, y: p.y + 6, r: 26, color: 0xa6dcff, flicker: false });
    }
    if (this.portal) out.push({ x: this.portal.x, y: this.portal.y - 14, r: 90, color: 0xc993e8, flicker: true });
    return out;
  }

  destroy(): void {
    safeDestroy(this.floor);
    for (const p of this.props) safeDestroy(p.sprite);
    for (const g of this.gates) safeDestroy(g.sprite);
    if (this.portal) safeDestroy(this.portal);
  }
}
