// Phase 15: speech bubbles for emotes and quick messages over avatars, and ping rings on the ground.
// Bubbles live in screen space (crisp at any zoom); rings live on the ground layer.
import gsap from "gsap";
import { Container, Graphics, Sprite, Text } from "pixi.js";
import { EV, type RoomEvent } from "../net/room";
import { useSession } from "../state/session";
import type { AvatarWorld, WorldHost } from "./avatarWorld";
import { safeDestroy } from "./safe";
import { sfx } from "./sfx";
import { iconTex } from "./sprites";

const T = 16;
const INK = 0x2b1e2a;
const PAPER = 0xfaf2dd;
const BUBBLE_MS = 3600;

interface Bubble {
  node: Container;
  until: number;
}

interface Ring {
  g: Graphics;
  x: number;
  y: number;
  start: number;
  until: number;
  color: number;
}

interface Bobber {
  g: Graphics;
  x: number;
  y: number;
  bit: boolean;
  t0: number;
}

export class SocialFx {
  private bubbles = new Map<number, Bubble>();
  private rings: Ring[] = [];
  private bobber: Bobber | null = null; // Phase 16b: your fishing line

  constructor(
    private host: WorldHost,
    private world: AvatarWorld,
  ) {}

  onEvent(ev: RoomEvent): void {
    const kind = ev[0] as number;
    if (kind === EV.CHAT) {
      const [, eid, what, key] = ev as [number, number, string, string | number];
      this.bubble(eid, what, key);
    } else if (kind === EV.FISH) {
      const op = ev[1] as string;
      if (op === "cast") {
        const [, , , x, y] = ev as [number, string, number, number, number];
        this.dropBobber();
        const g = new Graphics();
        this.host.fx.addChild(g);
        this.bobber = { g, x: x * T, y: y * T, bit: false, t0: performance.now() };
      } else if (op === "bite" && this.bobber) {
        this.bobber.bit = true;
        this.bobber.t0 = performance.now();
        this.host.dust(this.bobber.x, this.bobber.y + 2);
      } else if (op !== "bite") {
        if (this.bobber && op === "catch") this.host.sparkles(this.bobber.x, this.bobber.y);
        this.dropBobber();
      }
    } else if (kind === EV.PING) {
      const [, eid, , x, y, ms] = ev as [number, number, string, number, number, number];
      this.ring(x, y, ms, eid === this.world.client.eid);
    }
  }

  private bubble(eid: number, what: string, key: string | number): void {
    const old = this.bubbles.get(eid);
    if (old) safeDestroy(old.node);
    const node = new Container();
    const body = new Graphics();
    node.addChild(body);
    let w: number;
    let h: number;
    if (what === "emote") {
      const icon = new Sprite(iconTex(`emote_${key}`));
      icon.scale.set(2);
      icon.anchor.set(0.5, 1);
      w = 32;
      h = 32;
      icon.position.set(0, -10);
      node.addChild(icon);
    } else {
      const phrase = useSession.getState().config?.social.quick[Number(key)] ?? "…";
      const text = new Text({ text: phrase, style: { fontFamily: "Pixelify Sans", fontSize: 14, fill: INK, fontWeight: "600" } });
      text.anchor.set(0.5, 1);
      text.position.set(0, -11);
      w = Math.ceil(text.width);
      h = Math.ceil(text.height) - 2;
      node.addChild(text);
    }
    const pad = 6;
    body.roundRect(-w / 2 - pad, -h - 10 - pad / 2, w + pad * 2, h + pad + 2, 5).fill(PAPER).stroke({ width: 2, color: INK });
    body.poly([-5, -8, 5, -8, 0, -1]).fill(PAPER);
    body.moveTo(-5, -7).lineTo(0, -1).lineTo(5, -7).stroke({ width: 2, color: INK });
    this.host.screen.addChild(node);
    this.bubbles.set(eid, { node, until: performance.now() + BUBBLE_MS });
    gsap.fromTo(node.scale, { x: 0.4, y: 0.4 }, { x: 1, y: 1, duration: 0.22, ease: "back.out(2.5)" });
    this.place(eid, node);
    sfx("chat");
  }

  private ring(x: number, y: number, ms: number, mine: boolean): void {
    const g = new Graphics();
    g.zIndex = 5;
    this.host.under.addChild(g);
    const now = performance.now();
    this.rings.push({ g, x: x * T, y: y * T, start: now, until: now + ms, color: mine ? 0x94cdeb : 0xf7d66a });
  }

  private place(eid: number, node: Container): boolean {
    const p = this.world.headScreen(eid);
    if (!p) return false;
    node.position.set(Math.round(p.x), Math.round(p.y));
    return true;
  }

  private dropBobber(): void {
    if (this.bobber) safeDestroy(this.bobber.g);
    this.bobber = null;
  }

  private drawBobber(now: number): void {
    const b = this.bobber;
    if (!b || b.g.destroyed) return;
    const me = this.world.local.root;
    const t = (now - b.t0) / 1000;
    const dip = b.bit ? 2 + Math.sin(t * 30) * 1.5 : Math.sin(t * 3) * 0.8;
    const hx = me.x + 5;
    const hy = me.y - 16;
    const g = b.g.clear();
    // the line sags a little between the rod tip and the float
    const mx = (hx + b.x) / 2;
    const my = Math.max(hy, b.y) + 6;
    g.moveTo(hx, hy).quadraticCurveTo(mx, my, b.x, b.y - 2 + dip).stroke({ width: 1, color: 0xfaf2dd, alpha: 0.8 });
    const k = (t * 0.8) % 1;
    g.ellipse(b.x, b.y + 1, 3 + k * (b.bit ? 9 : 5), (3 + k * (b.bit ? 9 : 5)) * 0.45).stroke({ width: 1, color: 0xd5f0fa, alpha: (1 - k) * 0.7 });
    g.circle(b.x, b.y - 1 + dip, 2.4).fill(0xfaf2dd).stroke({ width: 1, color: INK });
    g.rect(b.x - 2.4, b.y - 3.4 + dip, 4.8, 2.2).fill(0xe05a47);
  }

  update(_dms: number): void {
    const now = performance.now();
    this.drawBobber(now);
    for (const [eid, b] of this.bubbles) {
      const left = b.until - now;
      if (left <= 0 || !this.place(eid, b.node)) {
        safeDestroy(b.node);
        this.bubbles.delete(eid);
        continue;
      }
      b.node.alpha = Math.min(1, left / 300);
    }
    this.rings = this.rings.filter((r) => {
      if (now >= r.until) {
        safeDestroy(r.g);
        return false;
      }
      const fade = Math.min(1, (r.until - now) / 800);
      const g = r.g.clear();
      for (let i = 0; i < 2; i++) {
        const k = ((now - r.start) / 1100 + i * 0.5) % 1;
        g.ellipse(r.x, r.y, 4 + k * 22, (4 + k * 22) * 0.55).stroke({ width: 2, color: r.color, alpha: (1 - k) * 0.9 * fade });
      }
      // a little diamond marker bobbing over the spot
      const by = r.y - 14 - Math.sin((now - r.start) / 180) * 2;
      g.poly([r.x, by - 5, r.x + 4, by, r.x, by + 5, r.x - 4, by]).fill({ color: r.color, alpha: fade }).stroke({ width: 1.5, color: INK, alpha: fade });
      return true;
    });
  }

  destroy(): void {
    this.dropBobber();
    for (const b of this.bubbles.values()) safeDestroy(b.node);
    for (const r of this.rings) safeDestroy(r.g);
    this.bubbles.clear();
    this.rings = [];
  }
}
