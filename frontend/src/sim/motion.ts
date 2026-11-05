// Line-for-line twin of backend/src/hearthforge/sim/motion.py (checked by motion.test.ts against
// /shared/golden/movement.json). Same determinism rules: + − × ÷ and sqrt only, same operation order.
import world from "../../../shared/world.json";
import { ATK_ABILITY, ATK_HEAVY, ATK_LIGHT, ATK_NONE, moveLength, type MoveRule, type Rules, type WeaponRule } from "./rules";

export const BTN = world.buttons as { light: number; heavy: number; ability: number; dodge: number; potion: number; offhand: number };
export type Solid = (x: number, y: number) => boolean;

export interface Motion {
  x: number;
  y: number;
  st: number;
  st_max: number;
  fx: number;
  fy: number;
  st_delay: number;
  dodge: number;
  ddx: number;
  ddy: number;
  dodge_cd: number;
  atk: number;
  atk_i: number;
  atk_t: number;
  ax: number;
  ay: number;
  combo: number;
  combo_t: number;
  ab_cd: number;
  kbx: number;
  kby: number;
}

export const MOTION_FIELDS: (keyof Motion)[] = [
  "x", "y", "st", "st_max", "fx", "fy", "st_delay", "dodge", "ddx", "ddy", "dodge_cd",
  "atk", "atk_i", "atk_t", "ax", "ay", "combo", "combo_t", "ab_cd", "kbx", "kby",
];

export function fromList(v: number[]): Motion {
  const m = {} as Motion;
  MOTION_FIELDS.forEach((k, i) => (m[k] = v[i]));
  return m;
}

export function toList(m: Motion): number[] {
  return MOTION_FIELDS.map((k) => m[k]);
}

export function newMotion(x: number, y: number, st: number): Motion {
  return fromList([x, y, st, st, 0, 1, 0, 0, 0, 0, 0, ATK_NONE, 0, 0, 0, 1, 0, 0, 0, 0, 0]);
}

export function currentMove(m: Motion, w: WeaponRule): MoveRule | null {
  if (m.atk === ATK_LIGHT) return w.light[m.atk_i];
  if (m.atk === ATK_HEAVY) return w.heavy;
  if (m.atk === ATK_ABILITY) return w.ability;
  return null;
}

function unit(x: number, y: number): [number, number, number] {
  const l2 = x * x + y * y;
  if (l2 <= 0) return [0, 0, 0];
  const ln = Math.sqrt(l2);
  return [x / ln, y / ln, l2];
}

function slideX(x: number, y: number, dx: number, r: Rules, solid: Solid): number {
  if (dx === 0) return x;
  const nx = x + dx;
  const r0 = Math.floor(y - r.hh);
  const r1 = Math.ceil(y + r.hh) - 1;
  if (dx > 0) {
    const cur = Math.ceil(x + r.hw) - 1;
    const nw = Math.ceil(nx + r.hw) - 1;
    for (let col = cur + 1; col <= nw; col++) {
      for (let row = r0; row <= r1; row++) if (solid(col, row)) return col - r.hw - r.skin;
    }
  } else {
    const cur = Math.floor(x - r.hw);
    const nw = Math.floor(nx - r.hw);
    for (let col = cur - 1; col >= nw; col--) {
      for (let row = r0; row <= r1; row++) if (solid(col, row)) return col + 1 + r.hw + r.skin;
    }
  }
  return nx;
}

function slideY(x: number, y: number, dy: number, r: Rules, solid: Solid): number {
  if (dy === 0) return y;
  const ny = y + dy;
  const c0 = Math.floor(x - r.hw);
  const c1 = Math.ceil(x + r.hw) - 1;
  if (dy > 0) {
    const cur = Math.ceil(y + r.hh) - 1;
    const nw = Math.ceil(ny + r.hh) - 1;
    for (let row = cur + 1; row <= nw; row++) {
      for (let col = c0; col <= c1; col++) if (solid(col, row)) return row - r.hh - r.skin;
    }
  } else {
    const cur = Math.floor(y - r.hh);
    const nw = Math.floor(ny - r.hh);
    for (let row = cur - 1; row >= nw; row--) {
      for (let col = c0; col <= c1; col++) if (solid(col, row)) return row + 1 + r.hh + r.skin;
    }
  }
  return ny;
}

function clamp(v: number, lim: number): number {
  return v > lim ? lim : v < -lim ? -lim : v;
}

/** Advance one tick; returns the attack kind that started this tick (0 if none). Mutates `m`. */
export function step(
  m: Motion, mx: number, my: number, ax: number, ay: number, buttons: number, r: Rules, w: WeaponRule, solid: Solid,
): number {
  let vx = mx / r.input_max;
  let vy = my / r.input_max;
  const l2 = vx * vx + vy * vy;
  const moving = l2 > r.deadzone2;
  if (l2 > 1.0) {
    const ln = Math.sqrt(l2);
    vx = vx / ln;
    vy = vy / ln;
  }
  let [aux, auy, al2] = unit(ax, ay);
  if (al2 <= 0) {
    aux = m.fx;
    auy = m.fy;
  }

  if (m.dodge_cd > 0) m.dodge_cd -= 1;
  if (m.ab_cd > 0) m.ab_cd -= 1;
  if (m.combo_t > 0) {
    m.combo_t -= 1;
    if (m.combo_t === 0) m.combo = 0;
  }

  if (m.atk !== ATK_NONE) {
    m.atk_t += 1;
    const mv = currentMove(m, w);
    if (mv !== null && m.atk_t >= moveLength(mv)) {
      if (m.atk === ATK_LIGHT) {
        m.combo_t = w.combo_window;
        if (m.combo_t === 0) m.combo = 0;
      }
      m.atk = ATK_NONE;
      m.atk_t = 0;
    }
  }

  let started = ATK_NONE;
  if (buttons & BTN.dodge && m.dodge === 0 && m.dodge_cd === 0 && m.st >= r.dodge_cost) {
    let dx: number;
    let dy: number;
    if (moving) [dx, dy] = unit(vx, vy);
    else [dx, dy] = [m.fx, m.fy];
    m.dodge = r.dodge_ticks;
    m.ddx = dx * r.dodge_step;
    m.ddy = dy * r.dodge_step;
    m.st -= r.dodge_cost;
    m.st_delay = r.st_delay;
    m.dodge_cd = r.dodge_cd;
    m.atk = ATK_NONE;
    m.atk_t = 0;
  } else if (m.dodge === 0 && m.atk === ATK_NONE) {
    if (buttons & BTN.ability && m.ab_cd === 0) {
      started = ATK_ABILITY;
      m.ab_cd = w.ability.cooldown;
    } else if (buttons & BTN.heavy && m.st >= w.heavy.stamina) {
      started = ATK_HEAVY;
      m.st -= w.heavy.stamina;
      m.st_delay = r.st_delay;
    } else if (buttons & BTN.light) {
      started = ATK_LIGHT;
      m.atk_i = m.combo_t > 0 ? m.combo : 0;
      m.combo = (m.atk_i + 1) % w.light.length;
      m.combo_t = 0;
    }
    if (started !== ATK_NONE) {
      m.atk = started;
      m.atk_t = 0;
      m.ax = aux;
      m.ay = auy;
      m.fx = aux;
      m.fy = auy;
    }
  }

  let px: number;
  let py: number;
  if (m.dodge > 0) {
    px = m.ddx;
    py = m.ddy;
    m.dodge -= 1;
  } else {
    const mv = currentMove(m, w);
    if (mv !== null && mv.dash_step > 0 && mv.windup <= m.atk_t && m.atk_t < mv.windup + mv.active) {
      px = m.ax * mv.dash_step;
      py = m.ay * mv.dash_step;
    } else {
      const sp = r.speed_tick * (m.atk !== ATK_NONE ? r.slow : 1.0);
      if (moving) {
        px = vx * sp;
        py = vy * sp;
      } else {
        px = 0;
        py = 0;
      }
      if (moving && m.atk === ATK_NONE) [m.fx, m.fy] = unit(vx, vy);
    }
  }
  px += m.kbx;
  py += m.kby;
  m.kbx *= r.kb_decay;
  m.kby *= r.kb_decay;
  if (m.kbx * m.kbx + m.kby * m.kby < 1e-6) {
    m.kbx = 0;
    m.kby = 0;
  }
  px = clamp(px, r.max_step);
  py = clamp(py, r.max_step);
  m.x = slideX(m.x, m.y, px, r, solid);
  m.y = slideY(m.x, m.y, py, r, solid);

  if (m.st_delay > 0) m.st_delay -= 1;
  else if (m.st < m.st_max) m.st = Math.min(m.st_max, m.st + r.st_regen);
  return started;
}
