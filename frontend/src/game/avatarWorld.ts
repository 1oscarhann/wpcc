// Avatar Mode rendering: avatars (predicted local + interpolated others), weapon swings, dodge
// afterimages, per-player drops and resource-node feedback. Monsters and combat FX live in combatFx.ts.
import gsap from "gsap";
import { AnimatedSprite, Container, Graphics, Rectangle, Sprite, Text, Texture } from "pixi.js";
import type { Appearance } from "../api/types";
import { ANIM, ENT, EV, type Ent, type RoomClient, type RoomEvent } from "../net/room";
import { currentMove } from "../sim/motion";
import { ATK_ABILITY, ATK_HEAVY, ATK_NONE, moveLength, type MoveRule } from "../sim/rules";
import { useSession } from "../state/session";
import { useAvatar } from "../state/avatar";
import { manifest } from "../assets/manifest";
import { appearanceKey, composeAvatar, frameFor } from "./avatarComposer";
import { safeDestroy } from "./safe";
import { weaponSprite } from "./items";
import { sfx } from "./sfx";
import { hasSprite, iconTex, tex } from "./sprites";

const T = 16;
const INK = 0x2b1e2a;

export interface WorldHost {
  under: Container; // ground-level overlays (telegraphs)
  objects: Container;
  fx: Container;
  screen: Container;
  floatText(wx: number, wy: number, text: string, color: number, delay?: number, size?: number): void;
  dust(x: number, y: number): void;
  sparkles(x: number, y: number): void;
  objectAt(tx: number, ty: number): Sprite | undefined;
  homeAnchor(): { x: number; y: number };
  toScreen(wx: number, wy: number): { x: number; y: number };
  zoom(): number;
  shake(px: number, ms: number): void;
  hitStop(ms: number): void;
  /** World sprites drawn in front of z that overlap the rect (trees, debris, buildings). */
  occluders(x0: number, y0: number, x1: number, y1: number, z: number): Container[];
}

const frameCache = new Map<string, Promise<Texture[]>>();
function avatarFrames(a: Appearance): Promise<Texture[]> {
  const key = appearanceKey(a);
  let p = frameCache.get(key);
  if (!p) {
    p = composeAvatar(a).then((canvas) => {
      const base = Texture.from(canvas);
      base.source.scaleMode = "nearest";
      const n = canvas.width / 16;
      return Array.from({ length: n }, (_, i) => new Texture({ source: base.source, frame: new Rectangle(i * 16, 0, 16, 24) }));
    });
    frameCache.set(key, p);
  }
  return p;
}

function dirOf(fx: number, fy: number): string {
  if (Math.abs(fx) >= Math.abs(fy) * 0.9) return fx < 0 ? "left" : "right";
  return fy < 0 ? "up" : "down";
}

export interface AvatarView {
  root: Container;
  body: Sprite;
  weapon: Sprite;
  shadow: Graphics;
  frames: Texture[] | null;
  label: Text | null;
  /** Phase 16: the title worn under the name ("Slime Slayer") */
  title: Text | null;
  /** Phase 16b: the mount under you and the pet at your heels */
  mount: Sprite | null;
  mountKey: string | null;
  face: number; // 1 = facing left (how mount sprites are drawn), -1 = right
  pet: PetFollow | null;
  lastX: number;
  lastY: number;
  walkMs: number;
  swing: gsap.core.Timeline | null;
  ghostCd: number;
  weaponType: string;
}

interface PetFollow {
  key: string;
  sprite: Sprite;
  x: number;
  y: number;
  walkMs: number;
  moves: number;
  face: number;
}

/** How high the rider sits on each mount (px above the hooves). */
const SADDLE: Record<string, number> = { horse: 13, ram: 11 };

interface DropView {
  root: Container;
  icon: Sprite;
  shadow: Graphics;
  picked: boolean;
  t: number;
}

export class AvatarWorld {
  local: AvatarView;
  private others = new Map<number, AvatarView>();
  private drops = new Map<number, DropView>();
  private picked = new Set<number>(); // picked up: never redraw, even if a snapshot still lists it
  private swapped = new Map<number, { sprite: Sprite; texture: Texture; alpha: number }>();
  private unsub: () => void;
  private time = 0;
  private nodeTimer = 0;
  private faded = new Map<Container, number>(); // occluder → its own alpha
  /** Add-ons that ride the avatar world's lifecycle (combat juice, the merchant cart, …). */
  extras: { update(dms: number): void; onEvent(ev: RoomEvent): void; destroy(): void }[] = [];

  constructor(
    private host: WorldHost,
    readonly client: RoomClient,
    appearance: Appearance,
  ) {
    this.local = this.makeAvatar(appearance, client.info.weapon.type, null);
    const me = client.roster.get(client.eid);
    if (me) {
      this.setPet(this.local, me.pet);
      this.setMount(this.local, me.mount);
    }
    this.unsub = client.on((ev) => this.onEvent(ev));
    this.applyDepleted();
  }

  destroy(): void {
    for (const [o, a] of this.faded) if (!o.destroyed) o.alpha = a;
    this.unsub();
    for (const x of this.extras) x.destroy();
    for (const v of [this.local, ...this.others.values()]) this.destroyAvatar(v);
    for (const d of this.drops.values()) safeDestroy(d.root);
    for (const [nid] of this.swapped) this.restoreNode(nid, false);
  }

  // ── avatars ──────────────────────────────────────────────────────────────
  private makeAvatar(a: Appearance, weaponType: string, name: string | null, titleText: string | null = null): AvatarView {
    const root = new Container();
    const shadow = new Graphics().ellipse(0, 0, 5.5, 2.2).fill({ color: INK, alpha: 0.28 });
    const body = new Sprite();
    body.anchor.set(0.5, 1);
    const weapon = new Sprite(tex(weaponSprite(weaponType, null, 1)));
    weapon.anchor.set(0.15, 0.5);
    weapon.visible = false;
    root.addChild(shadow, body, weapon);
    this.host.objects.addChild(root);
    let label: Text | null = null;
    if (name) {
      label = new Text({
        text: name,
        style: { fontFamily: "Pixelify Sans", fontSize: 13, fill: 0xfaf2dd, stroke: { color: INK, width: 3 }, fontWeight: "600" },
      });
      label.anchor.set(0.5, 1);
      this.host.screen.addChild(label);
    }
    const view: AvatarView = {
      root, body, weapon, shadow, frames: null, label, title: null, lastX: 0, lastY: 0, walkMs: 0, swing: null, ghostCd: 0, weaponType,
      mount: null, mountKey: null, face: 1, pet: null,
    };
    if (name) this.setTitle(view, titleText);
    void avatarFrames(a).then((f) => {
      view.frames = f;
    });
    return view;
  }

  private destroyAvatar(v: AvatarView): void {
    v.swing?.kill();
    safeDestroy(v.root);
    v.label?.destroy();
    v.title?.destroy();
    if (v.pet) safeDestroy(v.pet.sprite);
  }

  // ── Phase 16b: mounts and pets ─────────────────────────────────────────────
  private setMount(v: AvatarView, key: string | null): void {
    if (key === v.mountKey) return;
    v.mountKey = key;
    if (v.mount) {
      v.mount.destroy();
      v.mount = null;
    }
    if (key && hasSprite(`mount.${key}.idle.0`)) {
      const s = new Sprite(tex(`mount.${key}.idle.0`));
      s.anchor.set(0.5, 1);
      s.position.set(0, 1);
      s.zIndex = -2;
      v.root.addChild(s);
      v.mount = s;
      sfx("dodge");
    }
    v.shadow.visible = !v.mount; // the mount brings its own shadow
    if (!v.mount) v.body.y = 0;
  }

  private setPet(v: AvatarView, key: string | null): void {
    if ((v.pet?.key ?? null) === key) return;
    if (v.pet) safeDestroy(v.pet.sprite);
    v.pet = null;
    if (!key || !hasSprite(`pet.${key}.idle.0`)) return;
    const s = new Sprite(tex(`pet.${key}.idle.0`));
    s.anchor.set(0.5, 1);
    this.host.objects.addChild(s);
    v.pet = { key, sprite: s, x: v.root.x + 14, y: v.root.y, walkMs: 0, moves: hasSprite(`pet.${key}.move.3`) ? 4 : 2, face: 1 };
  }

  /** The pet trots after its owner, stopping a step short, and snaps along after a teleport. */
  private updatePet(v: AvatarView, dms: number): void {
    const pt = v.pet;
    if (!pt || pt.sprite.destroyed) return;
    const dx = v.root.x - pt.x;
    const dy = v.root.y - pt.y;
    const d = Math.hypot(dx, dy);
    let moving = false;
    if (d > 240) {
      pt.x = v.root.x + 14;
      pt.y = v.root.y;
    } else if (d > 18) {
      const k = 1 - Math.exp(-dms / 160);
      const step = (d - 14) * k;
      pt.x += (dx / d) * step;
      pt.y += (dy / d) * step;
      moving = step > 0.15;
    }
    if (dx < -2) pt.face = 1;
    else if (dx > 2) pt.face = -1;
    pt.walkMs = moving ? pt.walkMs + dms : 0;
    const name = moving
      ? `pet.${pt.key}.move.${Math.floor(pt.walkMs / 110) % pt.moves}`
      : `pet.${pt.key}.idle.${Math.floor(this.time / 520) % 2}`;
    pt.sprite.texture = tex(name);
    pt.sprite.scale.x = pt.face;
    const hover = pt.key === "owl" ? -5 - Math.sin(this.time / 260) * 1.5 : 0;
    pt.sprite.position.set(Math.round(pt.x), Math.round(pt.y + hover));
    pt.sprite.zIndex = pt.y;
  }

  private setTitle(v: AvatarView, title: string | null): void {
    if (!title) {
      v.title?.destroy();
      v.title = null;
      return;
    }
    if (!v.title) {
      v.title = new Text({
        text: "",
        style: { fontFamily: "Pixelify Sans", fontSize: 11, fill: 0xf7d66a, stroke: { color: INK, width: 3 }, fontWeight: "600" },
      });
      v.title.anchor.set(0.5, 1);
      this.host.screen.addChild(v.title);
    }
    v.title.text = title;
  }

  /** Screen position just above someone's head and nameplate (for chat bubbles). */
  headScreen(eid: number): { x: number; y: number } | null {
    const v = eid === this.client.eid ? this.local : this.others.get(eid);
    if (!v || v.root.destroyed) return null;
    const s = this.host.toScreen(v.root.x, v.root.y - 3 - 26);
    const up = (v.label?.height ?? 0) + (v.title?.height ?? 0);
    return { x: s.x, y: s.y - up - 2 };
  }

  private placeAvatar(v: AvatarView, x: number, y: number, fx: number, fy: number, moving: boolean, dms: number, ko: boolean): void {
    const px = x * T;
    const py = y * T;
    v.root.position.set(px, py + 3);
    v.root.zIndex = py + 3;
    const dir = dirOf(fx, fy);
    v.walkMs = moving ? v.walkMs + dms : 0;
    const riding = v.mount !== null && v.mountKey !== null;
    if (v.frames) {
      // in the saddle you sit still (the mount's legs do the walking)
      const f = frameFor(dir, moving && !riding ? "walk" : "idle", moving && !riding ? v.walkMs : this.time);
      v.body.texture = v.frames[f.index];
      v.body.scale.x = f.flip ? -1 : 1;
    }
    if (riding) {
      if (fx < -0.1) v.face = 1;
      else if (fx > 0.1) v.face = -1;
      const k = v.mountKey!;
      v.mount!.texture = tex(moving ? `mount.${k}.move.${Math.floor(v.walkMs / 85) % 4}` : `mount.${k}.idle.${Math.floor(this.time / 500) % 2}`);
      v.mount!.scale.x = v.face;
      v.body.y = -(SADDLE[k] ?? 12) + (moving && Math.floor(v.walkMs / 170) % 2 ? -1 : 0);
    }
    this.updatePet(v, dms);
    v.body.rotation = ko ? Math.PI / 2 : 0;
    v.body.alpha = ko ? 0.7 : 1;
    // weapon draws behind the body when facing up
    v.weapon.zIndex = dir === "up" ? -1 : 1;
    v.root.sortableChildren = true;
    v.body.zIndex = 0;
    if (v.label) {
      const s = this.host.toScreen(px, py - 26);
      if (v.title) {
        v.title.position.set(Math.round(s.x), Math.round(s.y));
        v.label.position.set(Math.round(s.x), Math.round(s.y - v.title.height + 2));
      } else v.label.position.set(Math.round(s.x), Math.round(s.y));
    }
  }

  /** Swing visuals. Local swings start from prediction (instant); others from SWING events. */
  swingVisual(v: AvatarView, kind: number, idx: number, ax: number, ay: number, weaponType: string, local: boolean): void {
    const rules = this.client.rules.weapons[weaponType] ?? this.client.rules.weapons.sword;
    const mv: MoveRule = kind === ATK_HEAVY ? rules.heavy : kind === ATK_ABILITY ? rules.ability : rules.light[idx] ?? rules.light[0];
    const angle = Math.atan2(ay, ax);
    const w = v.weapon;
    v.swing?.kill();
    w.visible = true;
    const wi = local ? this.client.info.weapon : null;
    w.texture = tex(wi ? weaponSprite(weaponType, wi.key, wi.tier) : weaponSprite(weaponType, null, 1));
    w.position.set(0, -9);
    w.alpha = 1;
    const tl = gsap.timeline({ onComplete: () => void (w.visible = false) });
    const wind = (mv.windup * 50) / 1000;
    const act = (mv.active * 50) / 1000;
    const rec = (mv.recover * 50) / 1000;
    if (mv.shape === "arc") {
      const half = ((mv.arc / 2) * Math.PI) / 180;
      const flip = idx % 2 === 1 ? -1 : 1;
      w.rotation = angle - half * flip;
      tl.to(w, { rotation: angle - half * 1.25 * flip, duration: wind, ease: "power1.out" })
        .to(w, { rotation: angle + half * flip, duration: act, ease: "power3.out" })
        .to(w, { alpha: 0, duration: rec, ease: "power1.in" });
      tl.call(() => this.slash(v, angle, mv, flip, kind === ATK_HEAVY), [], wind);
    } else if (mv.shape === "line") {
      w.rotation = angle;
      const back = { d: 0 };
      const place = () => w.position.set(Math.cos(angle) * back.d, -9 + Math.sin(angle) * back.d);
      tl.to(back, { d: -4, duration: wind, ease: "power1.out", onUpdate: place })
        .to(back, { d: mv.range * T * 0.55, duration: act * 0.6, ease: "power4.out", onUpdate: place })
        .to(back, { d: 0, duration: rec, ease: "power1.inOut", onUpdate: place })
        .to(w, { alpha: 0, duration: 0.08 });
      tl.call(() => this.thrust(v, angle, mv), [], wind);
    } else if (mv.shape === "shot" || mv.shape === "barrier" || mv.shape === "starfall") {
      // draw back, release: the projectile (or wall, or stars) comes from the server
      w.rotation = angle;
      const at = (d: number) => ({ x: Math.cos(angle) * d, y: -9 + Math.sin(angle) * d });
      w.position.set(at(3).x, at(3).y);
      tl.to(w, { ...at(-2), duration: Math.max(0.05, wind), ease: "power1.out" })
        .to(w, { ...at(4), duration: 0.06, ease: "power3.out" })
        .to(w, { alpha: 0, duration: Math.max(0.08, rec), ease: "power1.in" });
      if (mv.shape !== "shot") tl.call(() => this.host.sparkles(v.root.x + Math.cos(angle) * 14, v.root.y - 10 + Math.sin(angle) * 14), [], wind);
      if (kind === ATK_HEAVY && wind > 0.3) {
        // a charged shot: glint while you hold it
        tl.call(() => this.host.sparkles(v.root.x, v.root.y - 12), [], wind * 0.6);
      }
    } else if (mv.shape === "circle" && mv.hits <= 1) {
      // overhead slam: up, then down hard in front of you
      w.rotation = -Math.PI / 2;
      tl.to(w, { rotation: -Math.PI / 2 - 0.4, y: -14, duration: wind, ease: "power1.out" })
        .to(w, { rotation: angle + 0.2, y: -6, duration: Math.max(0.06, act * 0.5), ease: "power4.in" })
        .to(w, { alpha: 0, duration: rec, ease: "power1.in" });
      tl.call(() => gsap.fromTo(v.body.scale, { y: 0.8 }, { y: 1, duration: 0.25, ease: "back.out(3)" }), [], wind + act * 0.5);
    } else if (mv.shape === "spin" || mv.shape === "circle") {
      w.rotation = angle;
      tl.to(w, { rotation: angle + Math.PI * 2 * mv.hits, duration: wind + act, ease: "none" }).to(w, { alpha: 0, duration: rec });
      for (let k = 0; k < mv.hits; k++) tl.call(() => this.spinRing(v, mv), [], wind + (k * mv.interval * 50) / 1000);
    } else {
      // throw: wind up, then the spear leaves your hands (the projectile is drawn from the server)
      w.rotation = angle;
      tl.to(w, { x: -Math.cos(angle) * 5, y: -9 - Math.sin(angle) * 5, duration: wind })
        .to(w, { alpha: 0, duration: 0.05 })
        .to({}, { duration: rec });
    }
    v.swing = tl;
    if (local) sfx(kind === ATK_HEAVY ? "swing_heavy" : "swing");
    // a little forward lean
    gsap.fromTo(v.body.scale, { y: 0.92 }, { y: 1, duration: 0.18, ease: "back.out(3)" });
  }

  private slash(v: AvatarView, angle: number, mv: MoveRule, flip: number, heavy: boolean): void {
    const name = heavy ? "fx.slash_wide" : "fx.slash";
    const a = new AnimatedSprite([0, 1, 2].map((i) => tex(`${name}.${i}`)));
    a.anchor.set(0.5);
    const reach = mv.range * T * 0.5;
    a.position.set(v.root.x + Math.cos(angle) * reach * 0.6, v.root.y - 9 + Math.sin(angle) * reach * 0.6);
    a.rotation = angle;
    a.scale.set((mv.range * T * 1.6) / (heavy ? 34 : 28), ((mv.range * T * 1.6) / (heavy ? 34 : 28)) * flip);
    a.animationSpeed = 0.45;
    a.loop = false;
    a.onComplete = () => safeDestroy(a);
    this.host.fx.addChild(a);
    a.play();
  }

  private thrust(v: AvatarView, angle: number, mv: MoveRule): void {
    const g = new Graphics();
    const len = mv.range * T;
    g.rect(0, -1, len, 2).fill({ color: 0xfaf2dd, alpha: 0.9 });
    g.rect(len * 0.3, -2.5, len * 0.7, 1).fill({ color: 0xfaf2dd, alpha: 0.5 });
    g.position.set(v.root.x, v.root.y - 9);
    g.rotation = angle;
    this.host.fx.addChild(g);
    gsap.to(g, { alpha: 0, duration: 0.18, onComplete: () => safeDestroy(g) });
    gsap.fromTo(g.scale, { x: 0.3 }, { x: 1, duration: 0.08, ease: "power3.out" });
  }

  private spinRing(v: AvatarView, mv: MoveRule): void {
    for (let k = 0; k < 4; k++) {
      const a = new AnimatedSprite([0, 1, 2].map((i) => tex(`fx.slash_wide.${i}`)));
      a.anchor.set(0.5);
      const ang = (k / 4) * Math.PI * 2;
      a.position.set(v.root.x + Math.cos(ang) * mv.range * T * 0.45, v.root.y - 8 + Math.sin(ang) * mv.range * T * 0.45);
      a.rotation = ang;
      a.scale.set(0.8);
      a.animationSpeed = 0.5;
      a.loop = false;
      a.onComplete = () => safeDestroy(a);
      this.host.fx.addChild(a);
      a.play();
    }
  }

  private shieldSprite: Sprite | null = null;

  /** Holding F with a shield: raise it on the side you're facing. */
  private updateShield(c: RoomClient): void {
    const st = useAvatar.getState();
    const show = st.blocking && st.offhand.type === "shield" && !c.ko;
    if (!show) {
      if (this.shieldSprite) this.shieldSprite.visible = false;
      return;
    }
    if (!this.shieldSprite) {
      this.shieldSprite = new Sprite(tex(manifest.sprites[`wpn.shield.t${st.offhand.tier ?? 1}`] ? `wpn.shield.t${st.offhand.tier ?? 1}` : "wpn.shield"));
      this.shieldSprite.anchor.set(0.5, 0.6);
      this.local.root.addChild(this.shieldSprite);
    }
    const sh = this.shieldSprite;
    sh.visible = true;
    sh.position.set(c.me.fx * 6, -9 + c.me.fy * 4);
    sh.zIndex = c.me.fy < -0.3 ? -1 : 2;
    sh.scale.x = c.me.fx < -0.2 ? -1 : 1;
  }

  private afterimage(v: AvatarView): void {
    if (!v.body.texture || v.body.texture === Texture.EMPTY) return;
    const g = new Sprite(v.body.texture);
    g.anchor.set(0.5, 1);
    g.scale.x = v.body.scale.x;
    g.position.set(v.root.x, v.root.y);
    g.zIndex = v.root.zIndex - 1;
    g.tint = 0x94cdeb;
    g.alpha = 0.55;
    this.host.objects.addChild(g);
    gsap.to(g, { alpha: 0, duration: 0.25, onComplete: () => safeDestroy(g) });
  }

  // ── per-frame ────────────────────────────────────────────────────────────
  update(dms: number): void {
    this.time += dms;
    const c = this.client;
    // local avatar: predicted position, interpolated within the 50 ms step
    const p = c.drawPos();
    const moving = Math.abs(c.me.x - c.prev.x) + Math.abs(c.me.y - c.prev.y) > 0.01 && c.me.dodge === 0;
    this.placeAvatar(this.local, p.x, p.y, c.me.fx, c.me.fy, moving && c.me.atk === ATK_NONE, dms, c.ko);
    if (c.me.dodge > 0 && (this.local.ghostCd -= dms) <= 0) {
      this.afterimage(this.local);
      this.local.ghostCd = 40;
    }
    if ((c.flags & 1) !== 0 && c.me.dodge === 0) this.local.body.alpha = Math.floor(this.time / 80) % 2 ? 0.45 : 1;
    this.updateShield(c);
    // the swing animation can't outlive the predicted attack (e.g. a dodge cancelled it)
    if (c.me.atk === ATK_NONE && this.local.swing && this.local.swing.progress() < 0.6 && c.me.dodge > 0) {
      this.local.swing.kill();
      this.local.weapon.visible = false;
      this.local.swing = null;
    }

    const rt = c.renderTick();
    for (const ent of c.ents.values()) {
      if (ent.kind === ENT.avatar) this.updateOther(ent, rt, dms);
      else if (ent.kind === ENT.drop) this.updateDrop(ent, rt, dms);
    }
    for (const x of this.extras) x.update(dms);
    this.fadeOccluders();
    if ((this.nodeTimer -= dms) <= 0) {
      this.nodeTimer = 1000;
      this.applyDepleted();
    }
  }

  /** Trees and roofs in front of you go see-through so you never lose your hero. */
  private fadeOccluders(): void {
    const r = this.local.root;
    const hit = new Set(this.host.occluders(r.x - 6, r.y - 24, r.x + 6, r.y - 2, r.zIndex));
    for (const o of hit) {
      if (o.destroyed) continue;
      if (!this.faded.has(o)) this.faded.set(o, o.alpha);
      o.alpha += (0.42 - o.alpha) * 0.25;
    }
    for (const [o, a] of this.faded) {
      if (hit.has(o)) continue;
      if (o.destroyed) {
        this.faded.delete(o);
        continue;
      }
      o.alpha += (a - o.alpha) * 0.25;
      if (Math.abs(o.alpha - a) < 0.02) {
        o.alpha = a;
        this.faded.delete(o);
      }
    }
  }

  private updateOther(ent: Ent, rt: number, dms: number): void {
    const s = this.client.sampleAt(ent, rt);
    if (!s) return;
    let v = this.others.get(ent.id);
    const r = this.client.roster.get(ent.id);
    if (!v && r) {
      v = this.makeAvatar(r.appearance, r.weapon, r.name, r.title);
      this.others.set(ent.id, v);
      this.setPet(v, r.pet);
      this.setMount(v, r.mount);
    }
    if (!v) return;
    const moving = s.anim === ANIM.walk;
    this.placeAvatar(v, s.x, s.y, s.dx, s.dy, moving, dms, s.anim === ANIM.ko);
    if (s.anim === ANIM.dodge && (v.ghostCd -= dms) <= 0) {
      this.afterimage(v);
      v.ghostCd = 40;
    }
  }

  private updateDrop(ent: Ent, rt: number, dms: number): void {
    const s = this.client.sampleAt(ent, rt) ?? ent.samples[ent.samples.length - 1];
    if (!s) return;
    let d = this.drops.get(ent.id);
    if (!d && this.picked.has(ent.id)) return;
    if (!d) {
      const root = new Container();
      const shadow = new Graphics().ellipse(0, 0, 5, 2).fill({ color: INK, alpha: 0.3 });
      const icon = new Sprite(iconTex(ent.type === "coins" ? "coins" : this.iconFor(ent.type)));
      icon.anchor.set(0.5, 1);
      root.addChild(shadow);
      const cat = useSession.getState().config?.items[ent.type]?.category;
      if (cat === "rare_material") {
        // a soft purple light column so rares are impossible to miss (rarity beam)
        const beam = new Graphics();
        for (let i = 0; i < 6; i++) beam.rect(-3 + i * 0.5, -46 + i * 6, 6 - i, 46 - i * 6).fill({ color: 0xa259ff, alpha: 0.07 });
        beam.rect(-1, -40, 2, 40).fill({ color: 0xd9c4ff, alpha: 0.35 });
        root.addChild(beam);
        gsap.to(beam, { alpha: 0.45, duration: 0.8, yoyo: true, repeat: -1, ease: "sine.inOut" });
      }
      root.addChild(icon);
      root.position.set(s.x * T, s.y * T);
      root.zIndex = s.y * T;
      this.host.objects.addChild(root);
      d = { root, icon, shadow, picked: false, t: Math.random() * 1000 };
      this.drops.set(ent.id, d);
      // pop out of the node/monster
      gsap.fromTo(icon, { y: 0 }, { y: -14, duration: 0.18, ease: "power2.out", yoyo: true, repeat: 1 });
      gsap.fromTo(icon.scale, { x: 0.3, y: 0.3 }, { x: 1, y: 1, duration: 0.25, ease: "back.out(3)" });
    }
    if (d.picked) return;
    d.t += dms;
    if (!gsap.isTweening(d.icon)) d.icon.y = -2 - Math.sin(d.t / 220) * 2;
  }

  private iconFor(key: string): string {
    const cfg = useSession.getState().config;
    return (cfg?.items[key]?.icon ?? cfg?.resources[key]?.icon ?? "icon.info").replace(/^icon\./, "");
  }

  private itemName(key: string): string {
    if (key === "coins") return "Coins";
    const cfg = useSession.getState().config;
    return cfg?.items[key]?.name ?? cfg?.resources[key]?.name ?? key;
  }

  // ── events ───────────────────────────────────────────────────────────────
  private onEvent(ev: RoomEvent): void {
    const kind = ev[0] as number;
    const c = this.client;
    if (kind === -1) {
      const [, atk, idx, ax, ay] = ev as number[];
      this.swingVisual(this.local, atk, idx, ax, ay, c.info.weapon.type, true);
    } else if (kind === -3) {
      const id = ev[1] as number;
      const o = this.others.get(id);
      if (o) {
        this.destroyAvatar(o);
        this.others.delete(id);
      }
      const d = this.drops.get(id);
      if (d && !d.picked) {
        gsap.to(d.root, { alpha: 0, duration: 0.2, onComplete: () => safeDestroy(d.root) });
        this.drops.delete(id);
      }
    } else if (kind === EV.SWING) {
      const [, eid, atk, idx, ax, ay] = ev as number[];
      const v = this.others.get(eid);
      const r = c.roster.get(eid);
      if (v && r) this.swingVisual(v, atk, idx, ax / 100, ay / 100, r.weapon, false);
    } else if (kind === EV.PICKUP) {
      this.pickup(ev[1] as number, ev[2] as string, ev[3] as number);
    } else if (kind === EV.NODE) {
      this.nodeEvent(ev);
    } else if (kind === EV.DEPOSIT) {
      this.deposit(ev[1] as Record<string, number>);
    } else if (kind === EV.XP) {
      const [, amount, level, , , gained] = ev as number[];
      const p = c.drawPos();
      this.host.floatText(p.x * T, p.y * T - 28, `+${amount} XP`, 0x94cdeb, 0.15, 13);
      if (gained) {
        this.host.floatText(p.x * T, p.y * T - 40, `LEVEL ${level}!`, 0xf7d66a, 0, 22);
        for (let i = 0; i < 3; i++) window.setTimeout(() => this.host.sparkles(p.x * T, p.y * T - 12), i * 120);
        sfx("levelup");
      }
    } else if (kind === EV.PLAYER) {
      const eid = ev[1] as number;
      const r = c.roster.get(eid);
      if (eid === c.eid && r) {
        this.local.weaponType = r.weapon;
        c.info.weapon = { ...c.info.weapon, type: r.weapon };
        this.setPet(this.local, r.pet);
        this.setMount(this.local, r.mount);
        useAvatar.getState().set({ riding: r.mount !== null });
      } else if (r) {
        const o = this.others.get(eid);
        if (o) {
          this.setTitle(o, r.title); // a new title, or skills changed their level
          this.setPet(o, r.pet);
          this.setMount(o, r.mount);
        }
      }
    } else if (kind === EV.RESPAWN) {
      const [, x, y] = ev as number[];
      window.setTimeout(() => this.host.sparkles(x * T, y * T - 10), 50);
    }
    for (const x of this.extras) x.onEvent(ev);
  }

  private pickup(id: number, key: string, qty: number): void {
    const d = this.drops.get(id);
    const p = this.client.drawPos();
    this.picked.add(id);
    if (this.picked.size > 500) this.picked.clear();
    if (d && !d.picked) {
      d.picked = true;
      this.drops.delete(id);
      gsap.killTweensOf(d.icon);
      const from = { x: d.root.x, y: d.root.y };
      const st = { t: 0 };
      gsap.to(st, {
        t: 1,
        duration: 0.28,
        ease: "power2.in",
        onUpdate: () => {
          const q = this.client.drawPos();
          const tx = q.x * T;
          const ty = q.y * T - 10;
          d.root.position.set(from.x + (tx - from.x) * st.t, from.y + (ty - from.y) * st.t - Math.sin(st.t * Math.PI) * 10);
          d.root.zIndex = d.root.y + 20;
          d.icon.scale.set(1 - st.t * 0.5);
        },
        onComplete: () => safeDestroy(d.root),
      });
    }
    this.host.floatText(p.x * T, p.y * T - 26, `+${qty} ${this.itemName(key)}`, key === "coins" ? 0xf7d66a : 0xfaf2dd, 0.2, 14);
    sfx(key === "coins" ? "coin" : "pickup");
  }

  private deposit(moved: Record<string, number>): void {
    if (import.meta.env.DEV) {
      const w = window as unknown as { __hfDeposits?: number };
      w.__hfDeposits = (w.__hfDeposits ?? 0) + 1;
    }
    const home = this.host.homeAnchor();
    const p = this.client.drawPos();
    let i = 0;
    for (const [key, qty] of Object.entries(moved)) {
      for (let k = 0; k < Math.min(6, Math.ceil(qty / 4)); k++) {
        const s = new Sprite(iconTex(this.iconFor(key)));
        s.anchor.set(0.5);
        s.position.set(p.x * T, p.y * T - 12);
        s.zIndex = 99999;
        this.host.fx.addChild(s);
        const delay = (i * 6 + k) * 0.05;
        gsap.to(s, { x: home.x + (Math.random() - 0.5) * 12, duration: 0.55, delay, ease: "power1.inOut" });
        gsap.to(s, { y: home.y, duration: 0.55, delay, ease: "back.in(1.4)", onComplete: () => safeDestroy(s) });
      }
      this.host.floatText(home.x, home.y - 6 - i * 13, `+${qty} ${this.itemName(key)}`, 0xf7d66a, 0.55 + i * 0.12, 15);
      i++;
    }
    window.setTimeout(() => this.host.sparkles(home.x, home.y), 600);
    this.host.floatText(p.x * T, p.y * T - 28, "Stored!", 0xf7d66a, 0, 16);
    sfx("deposit");
  }

  private nodeXY(nid: number): [number, number] {
    const size = this.client.grid.size;
    return [nid % size, Math.floor(nid / size)];
  }

  private nodeEvent(ev: RoomEvent): void {
    const [, nid, hits, total, depleted, , sound] = ev as [number, number, number, number, number, number, string];
    const [tx, ty] = this.nodeXY(nid);
    const sprite = this.host.objectAt(tx, ty);
    if (hits === 0 && total === 0) {
      this.restoreNode(nid, true);
      return;
    }
    if (sprite) {
      gsap.killTweensOf(sprite, "rotation");
      gsap.fromTo(sprite, { rotation: 0.12 }, { rotation: 0, duration: 0.35, ease: "elastic.out(1.4, 0.3)" });
      this.chips(sprite, sound);
    }
    sfx(sound === "mine" ? "mine" : sound === "rustle" ? "rustle" : "chop");
    if (depleted && sprite) {
      window.setTimeout(() => this.depleteNode(nid, sprite, sound), 120);
      this.host.dust(sprite.x, sprite.y - 2);
    } else if (sprite) {
      const s = this.host.toScreen(0, 0);
      void s;
      this.host.floatText(sprite.x, sprite.y - sprite.height * 0.6, `${hits}/${total}`, 0xfaf2dd, 0, 11);
    }
  }

  private chips(sprite: Sprite, sound: string): void {
    const n = 5;
    for (let i = 0; i < n; i++) {
      const leaf = sound !== "mine";
      const s = leaf ? new AnimatedSprite([tex("fx.leaf.0"), tex("fx.leaf.1")]) : new Graphics().rect(-1, -1, 2, 2).fill({ color: 0xa2a8b6 });
      if (s instanceof AnimatedSprite) {
        s.animationSpeed = 0.25;
        s.play();
      }
      s.position.set(sprite.x + (Math.random() - 0.5) * 10, sprite.y - (leaf ? sprite.height * 0.55 : 6));
      this.host.fx.addChild(s);
      const dx = (Math.random() - 0.5) * 36;
      gsap.to(s, { x: s.x + dx, duration: 0.6, ease: "power1.out" });
      gsap.to(s, { y: s.y - 10 - Math.random() * 8, duration: 0.2, ease: "power2.out" });
      gsap.to(s, { y: sprite.y + 2, duration: 0.45, delay: 0.2, ease: "bounce.out" });
      gsap.to(s, { alpha: 0, duration: 0.3, delay: 0.55, onComplete: () => safeDestroy(s) });
    }
  }

  private depleteNode(nid: number, sprite: Sprite, sound: string): void {
    if (this.swapped.has(nid) || sprite.destroyed) return;
    this.swapped.set(nid, { sprite, texture: sprite.texture, alpha: sprite.alpha });
    const name = sound === "chop" ? "obj.stump.0" : sound === "mine" ? "obj.pebbles.0" : null;
    if (name) sprite.texture = tex(name);
    else sprite.alpha = 0.3;
    gsap.fromTo(sprite.scale, { x: 1.2, y: 0.7 }, { x: 1, y: 1, duration: 0.3, ease: "back.out(3)" });
  }

  private restoreNode(nid: number, juice: boolean): void {
    const s = this.swapped.get(nid);
    if (!s) return;
    this.swapped.delete(nid);
    if (s.sprite.destroyed) return;
    s.sprite.texture = s.texture;
    s.sprite.alpha = s.alpha;
    if (juice) gsap.fromTo(s.sprite.scale, { x: 0.5, y: 0.5 }, { x: 1, y: 1, duration: 0.4, ease: "back.out(2.5)" });
  }

  /** Re-apply this player's depleted nodes to sprites (chunks may have loaded since). */
  private applyDepleted(): void {
    const now = performance.now();
    for (const [nid, until] of this.client.depleted) {
      if (until <= now || this.swapped.has(nid)) continue;
      const [tx, ty] = this.nodeXY(nid);
      const sprite = this.host.objectAt(tx, ty);
      if (!sprite) continue;
      const name = sprite.label ?? "";
      const sound = /oak|birch|pine|apple/.test(name) ? "chop" : /rock/.test(name) ? "mine" : "rustle";
      this.depleteNode(nid, sprite, sound);
    }
  }

  /** Expose for combat FX. */
  avatarView(eid: number): AvatarView | undefined {
    return eid === this.client.eid ? this.local : this.others.get(eid);
  }

  currentLocalMove(): MoveRule | null {
    const w = this.client.weapon;
    const mv = currentMove(this.client.me, w);
    return mv && this.client.me.atk_t < moveLength(mv) ? mv : null;
  }
}
