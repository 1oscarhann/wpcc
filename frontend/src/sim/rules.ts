// Tick-based rules for the shared step, exactly as the server resolved them (config bundle `sim`).
export interface MoveRule {
  dmg: number;
  windup: number;
  active: number;
  recover: number;
  shape: "arc" | "line" | "spin" | "throw" | "circle" | "shot" | "starfall" | "barrier";
  range: number;
  arc: number;
  width: number;
  knockback: number;
  stamina: number;
  dash_step: number;
  hits: number;
  interval: number;
  cooldown: number;
  speed: number;
  // Phase 11, server-side (the client only uses them for visuals)
  pierce?: boolean;
  aoe?: number;
  count?: number;
  spread?: number;
  sprite?: string;
  impact?: string;
}

export interface WeaponRule {
  light: MoveRule[];
  combo_window: number;
  heavy: MoveRule;
  ability: MoveRule;
}

export interface Rules {
  hz: number;
  dt: number;
  speed_tick: number;
  slow: number;
  st_regen: number;
  st_delay: number;
  dodge_ticks: number;
  dodge_step: number;
  dodge_cost: number;
  dodge_cd: number;
  dodge_iframes: number;
  kb_decay: number;
  hw: number;
  hh: number;
  max_step: number;
  skin: number;
  deadzone2: number;
  input_max: number;
  weapons: Record<string, WeaponRule>;
}

export const ATK_NONE = 0;
export const ATK_LIGHT = 1;
export const ATK_HEAVY = 2;
export const ATK_ABILITY = 3;

export function moveLength(m: MoveRule): number {
  return m.windup + m.active + m.recover;
}
