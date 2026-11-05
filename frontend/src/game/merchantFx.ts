// The wandering merchant in Avatar Mode: her cart parked in the hub, Tamsin herself idling beside it,
// a bobbing coin bubble, and the "you're close enough to trade" check that drives the HUD prompt.
// Where she stands comes from GET /api/merchant/hub (it changes every rotation).
import gsap from "gsap";
import { Container, Graphics, Rectangle, Sprite, Text, Texture } from "pixi.js";
import type { Appearance, MerchantView } from "../api/types";
import type { RoomEvent } from "../net/room";
import { useMarket } from "../state/market";
import { useSession } from "../state/session";
import type { AvatarWorld, WorldHost } from "./avatarWorld";
import { composeAvatar, frameFor } from "./avatarComposer";
import { safeDestroy } from "./safe";
import { sfx } from "./sfx";
import { iconTex, tex } from "./sprites";

const T = 16;
const INK = 0x2b1e2a;

function tamsinLook(): Appearance {
  const cr = useSession.getState().config!.avatar.creator;
  const pick = (opts: string[], want: string) => (opts.includes(want) ? want : opts[opts.length - 1]);
  return {
    body: pick(cr.bodies, "sturdy"),
    skin: pick(cr.skin_tones, "umber"),
    hair_style: pick(cr.hair_styles, "bun"),
    hair_color: pick(cr.hair_colors, "silver"),
    eyes: pick(cr.eye_styles, "round"),
    eye_color: pick(cr.eye_colors, "green"),
    outfit: pick(cr.outfits, "robe"),
    outfit_color: pick(cr.outfit_colors, "plum"),
  };
}

export class MerchantCart {
  private root = new Container();
  private cart: Sprite;
  private npc = new Sprite();
  private frames: Texture[] | null = null;
  private bubble = new Container();
  private label: Text;
  private time = 0;
  private view: MerchantView | null = null;
  private refetchAt = 0;
  private wasNear = false;
  private destroyed = false;

  constructor(private host: WorldHost, private avatar: AvatarWorld) {
    this.cart = new Sprite(tex("npc.merchant_cart"));
    this.cart.anchor.set(0.5, 0.88);
    this.npc.anchor.set(0.5, 1);
    const shadow = new Graphics().ellipse(0, 0, 5.5, 2.2).fill({ color: INK, alpha: 0.28 });
    const npcRoot = new Container();
    npcRoot.addChild(shadow, this.npc);
    npcRoot.position.set(-30, 4);
    const bg = new Graphics().roundRect(-8, -8, 16, 16, 4).fill({ color: 0xfaf2dd }).stroke({ color: INK, width: 1.5 });
    const coin = new Sprite(iconTex("coins"));
    coin.anchor.set(0.5);
    coin.scale.set(0.75);
    this.bubble.addChild(bg, coin);
    this.bubble.position.set(-30, -34);
    this.root.addChild(this.cart, npcRoot, this.bubble);
    this.root.visible = false;
    this.host.objects.addChild(this.root);
    this.label = new Text({
      text: "",
      style: { fontFamily: "Pixelify Sans", fontSize: 13, fill: 0xf7d66a, stroke: { color: INK, width: 3 }, fontWeight: "600" },
    });
    this.label.anchor.set(0.5, 1);
    this.label.visible = false;
    this.host.screen.addChild(this.label);
    void composeAvatar(tamsinLook()).then((canvas) => {
      if (this.destroyed) return;
      const base = Texture.from(canvas);
      base.source.scaleMode = "nearest";
      this.frames = Array.from({ length: canvas.width / 16 }, (_, i) => new Texture({ source: base.source, frame: new Rectangle(i * 16, 0, 16, 24) }));
    });
    void this.load();
  }

  private async load(): Promise<void> {
    const m = await useMarket.getState().fetchMerchant();
    if (this.destroyed || !m) {
      this.refetchAt = this.time + 15_000;
      return;
    }
    const moved = this.view && (this.view.pos[0] !== m.pos[0] || this.view.pos[1] !== m.pos[1]);
    if (moved) this.host.dust(this.root.x, this.root.y);
    this.view = m;
    this.label.text = m.name;
    const px = m.pos[0] * T;
    const py = m.pos[1] * T;
    this.root.position.set(px, py);
    this.root.zIndex = py;
    if (!this.root.visible || moved) {
      this.root.visible = true;
      this.root.alpha = 0;
      gsap.to(this.root, { alpha: 1, duration: 0.6 });
    }
    const offset = useSession.getState().serverOffsetMs;
    this.refetchAt = this.time + Math.max(5_000, m.ends_at_ms - (Date.now() + offset) + 1500);
  }

  update(dms: number): void {
    this.time += dms;
    if (this.time >= this.refetchAt && this.refetchAt > 0) {
      this.refetchAt = 0;
      void this.load();
    }
    if (!this.view) return;
    if (this.frames) {
      const f = frameFor("right", "idle", this.time);
      this.npc.texture = this.frames[f.index];
      this.npc.scale.x = f.flip ? -1 : 1;
    }
    this.bubble.y = -34 + Math.sin(this.time / 380) * 2;
    const p = this.avatar.client.drawPos();
    const d = Math.hypot(p.x - this.view.pos[0], p.y - this.view.pos[1]);
    const near = d <= this.view.radius;
    if (near !== this.wasNear) {
      this.wasNear = near;
      useMarket.getState().set({ near });
      if (near) sfx("pickup");
      else useMarket.getState().set({ merchantOpen: false });
    }
    this.bubble.scale.set(near ? 1.15 : 1);
    this.label.visible = d < this.view.radius + 4;
    if (this.label.visible) {
      const s = this.host.toScreen(this.root.x - 30, this.root.y - 46);
      this.label.position.set(Math.round(s.x), Math.round(s.y));
    }
  }

  onEvent(_ev: RoomEvent): void {}

  destroy(): void {
    this.destroyed = true;
    gsap.killTweensOf(this.root);
    safeDestroy(this.root);
    this.label.destroy();
    useMarket.getState().set({ near: false, merchantOpen: false });
  }
}
