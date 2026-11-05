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
  private root: Graphics | null = null;
  private telegraphs = new Map<number, { g: Graphics; tween: gsap.core.Tween }>();
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
    for (const ent of c.ents.values()) {
      if (ent.kind === ENT.monster) this.updateMonster(ent, rt, dms);
      else if (ent.kind === ENT.projectile) this.updateProjectile(ent, rt);
    }
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
    const sc = v.elite ? 1.3 : 1;
    v.body.scale.x = flip * sc;
    // wind-up: shiver and redden so the attack reads at 16 px
    if (s.anim === ANIM.windup) {
      v.body.x = Math.floor(v.t / 40) % 2 ? 0.7 : -0.7;
      v.body.tint = Math.floor(v.t / 90) % 2 ? 0xff9a8a : 0xffffff;
    } else {
      v.body.x = 0;
      v.body.tint = v.night ? 0xe6dcff : 0xffffff;
    }
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
      v.bar.rect(-w / 2, top, (w * s.hp) / 255, 2).fill({ color: v.elite ? 0xf7d66a : 0xe2735a });
    }
  }

  private updateProjectile(ent: Ent, rt: number): void {
    const s = this.world.client.sampleAt(ent, rt + 1) ?? ent.samples[ent.samples.length - 1];
    if (!s) return;
    let sp = this.projectiles.get(ent.id);
    const monster = (s.flags & MONSTER_SHOT) !== 0;
    if (!sp) {
      sp = new Sprite(tex(monster ? `fx.shot.${ent.type}` : "wpn.spear"));
      sp.anchor.set(monster ? 0.7 : 0.6, 0.5);
      this.host.objects.addChild(sp);
      this.projectiles.set(ent.id, sp);
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
      case EV.HIT:
        this.hit(ev as number[]);
        break;
      case EV.DEATH: {
        const [, mid, x, y, , how] = ev as [number, number, number, number, string, number];
        if (how === 2) this.fade(mid, x, y);
        else this.death(mid, x, y, (ev[4] as string) ?? "", Boolean(how));
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

  /** Chain lightning: a jagged bolt that flickers twice. */
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
