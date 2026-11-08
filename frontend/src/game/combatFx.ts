// Phase 5 visuals: monsters (interpolated), telegraphs, projectiles, damage numbers, hit sparks,
// hit-stop and shake (visual only, D-010), death poofs, KO and heals.
import gsap from "gsap";
import { AnimatedSprite, Container, Graphics, Sprite } from "pixi.js";
import { ANIM, ENT, EV, SELF_FLAG, type Ent, type RoomEvent } from "../net/room";
import type { AvatarWorld, WorldHost } from "./avatarWorld";
import { safeDestroy } from "./safe";
import { sfx } from "./sfx";
import { hasSprite, tex } from "./sprites";

const T = 16;
const INK = 0x2b1e2a;
const MOVE_FRAMES = new Map<string, number>();
/** Quadrupeds, bipeds and flyers have 4 move frames; blobs and plants have 2. */
function moveFrames(key: string): number {
  let n = MOVE_FRAMES.get(key);
  if (n === undefined) {
    n = hasSprite(`mon.${key}.move.3`) ? 4 : 2;
    MOVE_FRAMES.set(key, n);
  }
  return n;
}
const SQUISHY = new Set(["slime", "big_slime", "pebbling", "leechling", "toad_spitter", "bog_lurker"]);
const NIGHT = 16;
const FRIENDLY = 128; // a guard (Phase 13)
const VULNERABLE = 256; // a realm boss with its guard down
const BLIZZARD = 512;
const WORLD = 1024; // the world boss (Phase 17)
const MONSTER_SHOT = 1;

interface MonsterView {
  root: Container;
  body: Sprite;
  shadow: Graphics;
  bar: Graphics;
  crown: Sprite | null;
  glow: Graphics | null;
  night: Graphics | null;
  key: string;
  elite: boolean;
  t: number;
  lastHp: number;
  flash: number;
  dying: boolean;
}

export class CombatFx {
  private monsters = new Map<number, MonsterView>();
  private projectiles = new Map<number, Sprite>();
  private statusTint = new Map<number, { color: number; until: number }>();
  private root: Graphics | null = null;
  private telegraphs = new Map<number, { g: Graphics; tween: gsap.core.Tween }>();
  blizzard = false; // Phase 13: a Frost Matriarch nearby has called her blizzard
  private time = 0;
  private lastLocalHit = -1e9;

  constructor(
    private host: WorldHost,
    private world: AvatarWorld,
  ) {}

  destroy(): void {
    for (const m of this.monsters.values()) safeDestroy(m.root);
    for (const p of this.projectiles.values()) safeDestroy(p);
    if (this.root) safeDestroy(this.root);
    for (const t of this.telegraphs.values()) {
      t.tween.kill();
      t.g.destroy();
    }
  }

  update(dms: number): void {
    this.time += dms;
    const c = this.world.client;
    const rt = c.renderTick();
    let blizzard = false;
    for (const ent of c.ents.values()) {
      if (ent.kind === ENT.monster) {
        this.updateMonster(ent, rt, dms);
        const last = ent.samples[ent.samples.length - 1];
        if (last && (last.flags & BLIZZARD) !== 0 && Math.abs(last.x - c.me.x) < 22 && Math.abs(last.y - c.me.y) < 22) blizzard = true;
      } else if (ent.kind === ENT.projectile) this.updateProjectile(ent, rt);
    }
    this.blizzard = blizzard;
    this.updateRoot();
  }

  /** Rooted by a summoner: thorny vines wrap the avatar's feet until it wears off. */
  private updateRoot(): void {
    const c = this.world.client;
    const rooted = (c.flags & SELF_FLAG.rooted) !== 0;
    const av = rooted ? this.world.avatarView(c.eid) : undefined;
    if (!av) {
      if (this.root) this.root.visible = false;
      return;
    }
    if (!this.root) {
      this.root = new Graphics();
      this.host.objects.addChild(this.root);
    }
    const g = this.root;
    g.visible = true;
    g.clear();
    const wob = Math.sin(this.time / 120) * 0.6;
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2 + this.time / 900;
      const x = Math.cos(a) * 7;
      const y = Math.sin(a) * 2.6;
      g.moveTo(x, y).quadraticCurveTo(x * 0.6 + wob, y - 7, x * 0.2, y - 11 - (i % 2) * 3);
    }
    g.stroke({ width: 1.6, color: 0x3f7d3a, alpha: 0.95 });
    g.ellipse(0, 0, 8, 3).stroke({ width: 1, color: 0x8cc663, alpha: 0.7 });
    g.position.set(av.root.x, av.root.y);
    g.zIndex = av.root.zIndex + 1;
  }

  private frame(key: string, anim: number, at: number, t: number): string {
    if (anim === ANIM.windup) return `mon.${key}.windup.0`;
    if (anim === ANIM.active) return `mon.${key}.attack.0`;
    if (anim === ANIM.walk) {
      const n = moveFrames(key);
      return `mon.${key}.move.${Math.floor(t / (n === 4 ? 100 : 160)) % n}`;
    }
    void at;
    return `mon.${key}.idle.${Math.floor(t / 420) % 2}`;
  }

  private updateMonster(ent: Ent, rt: number, dms: number): void {
    const s = this.world.client.sampleAt(ent, rt);
    if (!s) return;
    let v = this.monsters.get(ent.id);
    const elite = (s.flags & 1) !== 0;
    if (!v) {
      const root = new Container();
      root.sortableChildren = true;
      const shadow = new Graphics().ellipse(0, 0, 6, 2.2).fill({ color: INK, alpha: 0.3 });
      const body = new Sprite(tex(`mon.${ent.type}.idle.0`));
      body.anchor.set(0.5, 1);
      const bar = new Graphics();
      let glow: Graphics | null = null;
      let crown: Sprite | null = null;
      let night: Graphics | null = null;
      if ((s.flags & NIGHT) !== 0) {
        // spawned after dark: a violet haze around its feet
        night = new Graphics().ellipse(0, 0, 11, 4.5).fill({ color: 0x9b7fd6, alpha: 0.32 });
        root.addChild(night);
      }
      if (elite) {
        glow = new Graphics().ellipse(0, 0, 10, 4).fill({ color: 0xf7d66a, alpha: 0.35 });
        root.addChild(glow);
        body.scale.set(1.3);
        if (ent.type === "slime" || ent.type === "big_slime") {
          crown = new Sprite(tex("mon.crown"));
          crown.anchor.set(0.5, 1);
        }
      }
      root.addChild(shadow, body, bar);
      if (crown) root.addChild(crown);
      this.host.objects.addChild(root);
      v = { root, body, shadow, bar, crown, glow, night, key: ent.type, elite, t: Math.random() * 1000, lastHp: s.hp, flash: 0, dying: false };
      this.monsters.set(ent.id, v);
      gsap.fromTo(body, { alpha: 0 }, { alpha: 1, duration: 0.3 });
    }
    if (v.dying) return;
    v.t += dms;
    const hidden = s.anim === ANIM.hidden;
    v.root.position.set(s.x * T, s.y * T + 4);
    v.root.zIndex = s.y * T + 4;
    const name = this.frame(v.key, s.anim, s.at, v.t);
    v.body.texture = tex(name);
    const flip = s.dx > 0.05 ? -1 : 1;
    const world = (s.flags & WORLD) !== 0; // Phase 17: the world boss, bigger and moonlit
    const sc = world ? 1.45 : v.elite ? 1.3 : 1;
    v.body.scale.x = flip * sc;
    if (world) v.body.scale.y = sc;
    // wind-up: shiver and redden so the attack reads at 16 px
    if (s.anim === ANIM.windup) {
      v.body.x = Math.floor(v.t / 40) % 2 ? 0.7 : -0.7;
      v.body.tint = Math.floor(v.t / 90) % 2 ? 0xff9a8a : 0xffffff;
    } else {
      v.body.x = 0;
      v.body.tint = v.night ? 0xe6dcff : 0xffffff;
    }
    const st = this.statusTint.get(ent.id);
    if (st && st.until > this.time && s.anim !== ANIM.windup) v.body.tint = st.color;
    if (world && s.anim !== ANIM.windup) v.body.tint = 0xd8c8ff;
    if ((s.flags & VULNERABLE) !== 0) v.body.tint = Math.floor(v.t / 120) % 2 ? 0xfff6c0 : 0xffd27a; // its core is open
    if (v.flash > 0) {
      v.flash -= dms;
      v.body.tint = 0xfff4d8;
      v.body.alpha = 1;
    }
    // ambushers hide: only a faint shimmer gives them away
    v.body.alpha = hidden ? 0.12 + Math.abs(Math.sin(v.t / 260)) * 0.1 : 1;
    v.shadow.alpha = hidden ? 0.2 : 1;
    if (v.crown) v.crown.position.set(0, -v.body.texture.height * sc + 6);
    if (v.glow) v.glow.alpha = 0.55 + Math.sin(v.t / 300) * 0.25;
    if (v.night) v.night.alpha = hidden ? 0.15 : 0.6 + Math.sin(v.t / 450) * 0.3;
    v.bar.clear();
    if (s.hp < 255 && !hidden) {
      const w = v.elite ? 22 : 14;
      const top = -v.body.texture.height * sc - 4;
      v.bar.rect(-w / 2 - 1, top - 1, w + 2, 4).fill({ color: INK });
      const friendly = (s.flags & FRIENDLY) !== 0;
      v.bar.rect(-w / 2, top, (w * s.hp) / 255, 2).fill({ color: friendly ? 0x8fc95c : v.elite ? 0xf7d66a : 0xe2735a });
    }
  }

  private updateProjectile(ent: Ent, rt: number): void {
    const s = this.world.client.sampleAt(ent, rt + 1) ?? ent.samples[ent.samples.length - 1];
    if (!s) return;
    let sp = this.projectiles.get(ent.id);
    const monster = (s.flags & MONSTER_SHOT) !== 0;
    const bomb = (s.flags & 2) !== 0;
    if (!sp) {
      const name = bomb ? "fx.bomb.0" : ent.type === "spear" ? "wpn.spear" : `fx.shot.${ent.type}`;
      sp = new Sprite(tex(name));
      sp.anchor.set(bomb ? 0.5 : monster ? 0.7 : 0.6, bomb ? 0.9 : 0.5);
      this.host.objects.addChild(sp);
      this.projectiles.set(ent.id, sp);
      if (bomb) gsap.fromTo(sp, { y: s.y * T - 18 }, { y: s.y * T + 2, duration: 0.25, ease: "bounce.out" });
    }
    if (bomb) {
      sp.texture = tex(`fx.bomb.${Math.floor(this.time / 120) % 2}`);
      sp.x = s.x * T;
      sp.zIndex = s.y * T + 2;
      return;
    }
    sp.position.set(s.x * T, s.y * T - (monster ? 7 : 8));
    sp.zIndex = s.y * T + 8;
    sp.rotation = Math.atan2(s.dy, s.dx);
  }

  // ── events ───────────────────────────────────────────────────────────────
  onEvent(ev: RoomEvent): void {
    const kind = ev[0] as number;
    const c = this.world.client;
    if (kind === -3) {
      const id = ev[1] as number;
      const v = this.monsters.get(id);
      if (v && !v.dying) {
        this.monsters.delete(id);
        gsap.to(v.root, { alpha: 0, duration: 0.4, onComplete: () => safeDestroy(v.root) });
      }
      const p = this.projectiles.get(id);
      if (p) {
        this.projectiles.delete(id);
        safeDestroy(p);
      }
      return;
    }
    switch (kind) {
      case EV.TELEGRAPH:
        this.telegraph(ev as number[]);
        break;
      case EV.TOWER: {
        const [, x0, y0, x1, y1, ms] = ev as number[];
        this.arrow(x0 * T, y0 * T, x1 * T, y1 * T, ms);
        break;
      }
      case EV.WAVE:
        if (ev[2] === "steal") this.steal((ev[3] as number) * T, (ev[4] as number) * T);
        break;
      case EV.HIT:
        this.hit(ev as number[]);
        break;
      case EV.DEATH: {
        const [, mid, x, y, , how] = ev as [number, number, number, number, string, number];
        if (how === 2) this.fade(mid, x, y);
        else this.death(mid, x, y, (ev[4] as string) ?? "", Boolean(how));
        break;
      }
      case EV.IMPACT: {
        const [, x, y, r, kind] = ev as [number, number, number, number, string];
        this.impact(x * T, y * T, r * T, kind);
        break;
      }
      case EV.BARRIER: {
        const [, , x0, y0, x1, y1, ms] = ev as number[];
        this.barrier(x0 * T, y0 * T - 6, x1 * T, y1 * T - 6, ms);
        break;
      }
      case EV.STATUS: {
        const [, mid, kind] = ev as [number, number, string];
        const color = kind === "burn" ? 0xffb07a : kind === "slow" ? 0xa6dcff : kind === "poison" ? 0xb4f08c : 0xffffff;
        this.statusTint.set(mid, { color, until: this.time + 1200 });
        break;
      }
      case EV.ZAP: {
        const [, x0, y0, x1, y1] = ev as number[];
        this.zap(x0 * T, y0 * T - 10, x1 * T, y1 * T - 10);
        break;
      }
      case EV.PROJECTILE_END: {
        const [, id, x, y] = ev as number[];
        const p = this.projectiles.get(id);
        if (p) {
          this.projectiles.delete(id);
          gsap.to(p, { alpha: 0, duration: 0.15, onComplete: () => safeDestroy(p) });
        }
        this.host.dust(x * T, y * T);
        break;
      }
      case EV.KO: {
        const eid = ev[1] as number;
        if (eid === c.eid) {
          sfx("ko");
          this.host.shake(4, 220);
        }
        const v = this.world.avatarView(eid);
        if (v) gsap.fromTo(v.body, { rotation: 0 }, { rotation: Math.PI / 2, duration: 0.35, ease: "bounce.out" });
        break;
      }
      case EV.HEAL: {
        const [, eid, amount] = ev as number[];
        const v = this.world.avatarView(eid);
        if (v) {
          this.host.floatText(v.root.x, v.root.y - 30, `+${amount}`, 0x8fc95c, 0, 16);
          this.host.sparkles(v.root.x, v.root.y - 12);
          gsap.fromTo(v.body, { tint: 0x9cff9c }, { tint: 0xffffff, duration: 0.5 });
        }
        if (eid === c.eid) sfx("potion");
        break;
      }
      case EV.SFX: {
        const [, name, x, y] = ev as [number, string, number, number];
        const me = c.me;
        if ((x - me.x) ** 2 + (y - me.y) ** 2 < 18 * 18) sfx(name);
        break;
      }
      default:
        break;
    }
  }

  private telegraph(ev: number[]): void {
    const [, mid, shape, x, y, dx, dy, range, width, warnMs] = ev;
    const prev = this.telegraphs.get(mid);
    if (prev) {
      prev.tween.kill();
      safeDestroy(prev.g);
    }
    const g = new Graphics();
    g.position.set(x * T, y * T);
    const state = { p: 0 };
    const draw = () => {
      g.clear();
      if (shape === 0) {
        g.circle(0, 0, range * T).fill({ color: 0xe05a47, alpha: 0.16 }).stroke({ width: 1, color: 0xe05a47, alpha: 0.75 });
        g.circle(0, 0, range * T * state.p).fill({ color: 0xe05a47, alpha: 0.28 });
      } else if (shape === 2) {
        // ring: safe inside `width` (the inner radius) and outside `range`
        const inner = width * T;
        const outer = range * T;
        g.circle(0, 0, outer).circle(0, 0, inner).cut();
        g.circle(0, 0, outer).fill({ color: 0x7fc6ff, alpha: 0.16 }).stroke({ width: 1, color: 0x7fc6ff, alpha: 0.8 });
        g.circle(0, 0, inner).fill({ color: 0x2b1e2a, alpha: 0.0 }).stroke({ width: 1, color: 0xfaf2dd, alpha: 0.9 });
        g.circle(0, 0, inner + (outer - inner) * state.p).stroke({ width: 2, color: 0x7fc6ff, alpha: 0.6 });
      } else if (shape === 3) {
        // cone: `width` is the angle in degrees
        const a0 = Math.atan2(dy, dx);
        const half = ((width / 2) * Math.PI) / 180;
        const len = range * T;
        g.moveTo(0, 0).arc(0, 0, len, a0 - half, a0 + half).lineTo(0, 0)
          .fill({ color: 0x8fd05c, alpha: 0.16 }).stroke({ width: 1, color: 0x8fd05c, alpha: 0.8 });
        g.moveTo(0, 0).arc(0, 0, len * state.p, a0 - half, a0 + half).lineTo(0, 0).fill({ color: 0x8fd05c, alpha: 0.28 });
      } else {
        const len = range * T;
        const w = width * T;
        g.rotation = Math.atan2(dy, dx);
        g.rect(0, -w / 2, len, w).fill({ color: 0xe05a47, alpha: 0.16 }).stroke({ width: 1, color: 0xe05a47, alpha: 0.75 });
        g.rect(0, -w / 2, len * state.p, w).fill({ color: 0xe05a47, alpha: 0.3 });
      }
    };
    draw();
    this.host.under.addChild(g);
    const tween = gsap.to(state, {
      p: 1,
      duration: warnMs / 1000,
      ease: "none",
      onUpdate: draw,
      onComplete: () => {
        gsap.to(g, { alpha: 0, duration: 0.18, delay: 0.08, onComplete: () => safeDestroy(g) });
        if (this.telegraphs.get(mid)?.g === g) this.telegraphs.delete(mid);
      },
    });
    this.telegraphs.set(mid, { g, tween });
    const me = this.world.client.me;
    if ((x - me.x) ** 2 + (y - me.y) ** 2 < 49) sfx("telegraph");
  }

  private hit(ev: number[]): void {
    const [, src, dst, dmg, crit, kind] = ev;
    const c = this.world.client;
    const mv = this.monsters.get(dst);
    if (mv) {
      // we hit a monster
      mv.flash = 90;
      const x = mv.root.x;
      const y = mv.root.y - mv.body.texture.height * (mv.elite ? 1.3 : 1) * 0.6;
      const spark = new AnimatedSprite([0, 1, 2].map((i) => tex(`fx.hit.${i}`)));
      spark.anchor.set(0.5);
      spark.position.set(x + (Math.random() - 0.5) * 6, y);
      spark.animationSpeed = 0.5;
      spark.loop = false;
      spark.zIndex = 99999;
      spark.onComplete = () => safeDestroy(spark);
      this.host.objects.addChild(spark);
      spark.play();
      gsap.fromTo(mv.body.scale, { y: mv.elite ? 1.0 : 0.75 }, { y: mv.elite ? 1.3 : 1, duration: 0.2, ease: "back.out(3)" });
      this.host.floatText(x, y - 8, crit ? `${dmg}!` : `${dmg}`, crit ? 0xf7d66a : 0xfaf2dd, 0, crit ? 20 : 15);
      if (src === c.eid) {
        this.lastLocalHit = performance.now();
        sfx(crit ? "crit" : SQUISHY.has(mv.key) ? "squish" : "hit");
        this.host.hitStop(crit ? 60 : kind === 3 ? 55 : 40);
        if (crit || kind === 3) this.host.shake(2, 120);
      }
      return;
    }
    const av = this.world.avatarView(dst);
    if (!av) return;
    const x = av.root.x;
    const y = av.root.y - 26;
    if (dmg === 0 && kind === 2) {
      this.host.floatText(x, y, "dodged!", 0x94cdeb, 0, 14);
      return;
    }
    if (kind === 4) {
      this.host.floatText(x, y - 10, "blocked!", 0xf7d66a, 0, 13);
      if (dst === c.eid) sfx("clang");
    }
    this.host.floatText(x, y, `-${dmg}`, kind === 1 ? 0x8fc95c : 0xe2735a, 0, dst === c.eid ? 17 : 13);
    gsap.fromTo(av.body, { tint: kind === 1 ? 0x9cff9c : 0xff6a5a }, { tint: 0xffffff, duration: 0.25 });
    if (dst === c.eid) {
      sfx("hurt");
      this.host.shake(kind === 1 ? 0.5 : 2, 120);
      if (kind !== 1) this.host.hitStop(45);
    }
  }

  /** Night-only spawns at dawn, storm spawns when the storm passes, minions with their summoner. */
  private fade(mid: number, x: number, y: number): void {
    const v = this.monsters.get(mid);
    if (v) {
      v.dying = true;
      this.monsters.delete(mid);
      v.bar.clear();
      gsap.to(v.root, { alpha: 0, duration: 0.8, onComplete: () => safeDestroy(v.root) });
      gsap.to(v.root, { y: v.root.y - 6, duration: 0.8 });
    }
    this.host.sparkles(x * T, y * T - 8);
  }

  /** Phase 11: slams, quakes, bursts, whirlpools, bomb blasts and falling stars. */
  private impact(x: number, y: number, r: number, kind: string): void {
    const color =
      kind === "burst" ? 0xc993e8 : kind === "whirl" ? 0x94cdeb : kind === "boom" ? 0xffc04d : kind === "star" ? 0xfff1b0 : 0xe0cfab;
    const g = new Graphics();
    g.position.set(x, y);
    g.zIndex = y + 1;
    const ring = { r: r * 0.2, a: 0.9 };
    const draw = () => {
      g.clear();
      g.ellipse(0, 0, ring.r, ring.r * 0.55).stroke({ width: kind === "quake" ? 3 : 2, color, alpha: ring.a });
      if (kind === "boom" || kind === "star" || kind === "burst") g.ellipse(0, 0, ring.r * 0.6, ring.r * 0.33).fill({ color, alpha: ring.a * 0.35 });
    };
    draw();
    this.host.objects.addChild(g);
    const dur = kind === "whirl" ? 0.5 : kind === "quake" ? 0.55 : 0.32;
    gsap.to(ring, { r, a: 0, duration: dur, ease: "power2.out", onUpdate: draw, onComplete: () => safeDestroy(g) });
    if (kind === "star") {
      const s = new Graphics().rect(-1, -40, 2, 40).fill({ color: 0xfff1b0, alpha: 0.9 });
      s.position.set(x, y);
      s.zIndex = y + 2;
      this.host.objects.addChild(s);
      gsap.fromTo(s, { y: y - 30, alpha: 1 }, { y, alpha: 0, duration: 0.18, ease: "power2.in", onComplete: () => safeDestroy(s) });
    }
    const me = this.world.client.me;
    const near = (x / T - me.x) ** 2 + (y / T - me.y) ** 2 < 20 * 20;
    if (near) {
      if (kind === "boom" || kind === "quake") this.host.shake(kind === "boom" ? 3 : 2.5, 160);
      else if (kind === "slam") this.host.shake(1.5, 100);
      this.host.dust(x, y);
      sfx(kind === "boom" ? "boom" : kind === "whirl" ? "splash" : kind === "star" ? "zap" : "slam");
    }
  }

  /** The crystal staff's wall: shimmering until it fades. */
  private barrier(x0: number, y0: number, x1: number, y1: number, ms: number): void {
    const g = new Graphics();
    const len = Math.hypot(x1 - x0, y1 - y0);
    g.position.set(x0, y0);
    g.rotation = Math.atan2(y1 - y0, x1 - x0);
    g.zIndex = Math.max(y0, y1) + 8;
    g.rect(0, -2, len, 4).fill({ color: 0x94cdeb, alpha: 0.35 });
    for (let i = 0; i < len; i += 5) {
      const h = 7 + ((i * 7) % 4);
      g.poly([i, 0, i + 2.5, -h, i + 5, 0, i + 2.5, h * 0.5]).fill({ color: 0xa6cfe6, alpha: 0.9 }).stroke({ width: 1, color: 0xd5f0fa });
    }
    this.host.objects.addChild(g);
    gsap.fromTo(g.scale, { y: 0.2 }, { y: 1, duration: 0.2, ease: "back.out(3)" });
    gsap.to(g, { alpha: 0, duration: 0.4, delay: Math.max(0, ms / 1000 - 0.4), onComplete: () => safeDestroy(g) });
    sfx("shimmer");
  }

  /** Chain lightning: a jagged bolt that flickers twice. */
  /** Phase 13: a watchtower arrow arcing onto a raider. */
  private arrow(x0: number, y0: number, x1: number, y1: number, ms: number): void {
    const s = new Sprite(tex("fx.shot.arrow"));
    s.anchor.set(0.5);
    s.zIndex = 99997;
    this.host.objects.addChild(s);
    const st = { t: 0 };
    const arc = Math.min(28, Math.hypot(x1 - x0, y1 - y0) * 0.35);
    const place = () => {
      const t = st.t;
      const x = x0 + (x1 - x0) * t;
      const y = y0 + (y1 - y0) * t - Math.sin(t * Math.PI) * arc;
      const nt = Math.min(1, t + 0.05);
      const ny = y0 + (y1 - y0) * nt - Math.sin(nt * Math.PI) * arc;
      s.rotation = Math.atan2(ny - y, x0 + (x1 - x0) * nt - x);
      s.position.set(x, y);
    };
    place();
    gsap.to(st, { t: 1, duration: Math.max(0.12, ms / 1000), ease: "none", onUpdate: place, onComplete: () => safeDestroy(s) });
    sfx("shoot");
  }

  /** Phase 13: a raider made it to the storehouse and legs it with a sack. */
  private steal(x: number, y: number): void {
    const s = new Sprite(tex(hasSprite("fx.sack") ? "fx.sack" : "fx.shot.arrow"));
    s.anchor.set(0.5, 1);
    s.position.set(x, y);
    s.zIndex = 99997;
    this.host.objects.addChild(s);
    gsap.to(s, { y: y - 26, alpha: 0, duration: 0.9, ease: "power1.out", onComplete: () => safeDestroy(s) });
    this.host.floatText(x, y - 20, "Stolen!", 0xe2735a, 0, 14);
    sfx("poof");
  }

  private zap(x0: number, y0: number, x1: number, y1: number): void {
    const g = new Graphics();
    const seg = 6;
    const draw = (j: number) => {
      g.clear();
      g.moveTo(x0, y0);
      for (let i = 1; i < seg; i++) {
        const t = i / seg;
        const nx = -(y1 - y0);
        const ny = x1 - x0;
        const l = Math.hypot(nx, ny) || 1;
        const off = (Math.sin(i * 12.9898 + j * 78.233) * 43758.5453) % 1;
        g.lineTo(x0 + (x1 - x0) * t + (nx / l) * off * 5, y0 + (y1 - y0) * t + (ny / l) * off * 5);
      }
      g.lineTo(x1, y1);
      g.stroke({ width: 2.5, color: 0xfbe68a, alpha: 0.95 }).stroke({ width: 1, color: 0xffffff, alpha: 1 });
    };
    draw(0);
    g.zIndex = 99998;
    this.host.objects.addChild(g);
    gsap.delayedCall(0.06, () => draw(1));
    gsap.to(g, { alpha: 0, duration: 0.25, delay: 0.1, onComplete: () => safeDestroy(g) });
    sfx("zap");
  }

  private death(mid: number, x: number, y: number, key: string, elite: boolean): void {
    const v = this.monsters.get(mid);
    if (v) {
      v.dying = true;
      this.monsters.delete(mid);
      v.bar.clear();
      gsap.to(v.body.scale, { x: v.body.scale.x * 1.4, y: 0.3, duration: 0.14, ease: "power2.in" });
      gsap.to(v.root, { alpha: 0, duration: 0.16, delay: 0.06, onComplete: () => safeDestroy(v.root) });
    }
    const poof = new AnimatedSprite([0, 1, 2, 3].map((i) => tex(`fx.poof.${i}`)));
    poof.anchor.set(0.5, 0.8);
    poof.position.set(x * T, y * T + 2);
    poof.zIndex = y * T + 50;
    poof.animationSpeed = 0.3;
    poof.loop = false;
    poof.scale.set(elite ? 1.5 : 1);
    poof.onComplete = () => safeDestroy(poof);
    this.host.objects.addChild(poof);
    poof.play();
    if (performance.now() - this.lastLocalHit < 400) this.host.hitStop(60);
    sfx(SQUISHY.has(key) ? "squish" : "poof");
    if (elite) {
      this.host.sparkles(x * T, y * T - 10);
      this.host.shake(3, 160);
    }
  }
}
