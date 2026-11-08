// Phase 18: gamepads (the browser's "standard" layout: Xbox, PlayStation and Switch Pro all map to it).
// Polled once a frame in Avatar Mode. The left stick walks, the right stick aims; buttons follow the
// on-screen touch layout. Build Mode stays pointer-and-keyboard.
import { BTN } from "../sim/motion";

export const PAD_HELP: [string, string][] = [
  ["Left stick", "walk"],
  ["Right stick", "aim"],
  ["A / Cross, or RT", "attack (hold)"],
  ["B / Circle", "dodge"],
  ["X / Square", "heavy attack"],
  ["Y / Triangle", "weapon ability"],
  ["LB / L1", "shield, bombs or tome"],
  ["RB / R1", "potion"],
  ["LT / L2", "talk, trade, fish, use"],
  ["D-pad", "quick slots 1–4"],
  ["Start", "bag"],
  ["Back / Select", "map"],
];

export interface PadState {
  mx: number;
  my: number;
  ax: number;
  ay: number;
  held: number; // BTN bits held this frame
  latched: number; // BTN bits pressed this frame
  pressed: Set<string>; // other buttons pressed this frame: "interact", "bag", "map", "quick1"…
  active: boolean;
}

const DEAD = 0.22;
let prev: boolean[] = [];

function axis(v: number): number {
  return Math.abs(v) < DEAD ? 0 : Math.sign(v) * Math.min(1, (Math.abs(v) - DEAD) / (1 - DEAD));
}

export function readPad(): PadState | null {
  const pads = typeof navigator !== "undefined" && navigator.getGamepads ? navigator.getGamepads() : [];
  const gp = Array.from(pads ?? []).find((p) => p && p.connected && p.mapping === "standard") ?? null;
  if (!gp) return null;
  const b = gp.buttons.map((x) => x.pressed);
  const edge = (i: number) => Boolean(b[i]) && !prev[i];
  const out: PadState = {
    mx: axis(gp.axes[0] ?? 0),
    my: axis(gp.axes[1] ?? 0),
    ax: axis(gp.axes[2] ?? 0),
    ay: axis(gp.axes[3] ?? 0),
    held: (b[0] || b[7] ? BTN.light : 0) | (b[4] ? BTN.offhand : 0),
    latched: (edge(1) ? BTN.dodge : 0) | (edge(2) ? BTN.heavy : 0) | (edge(3) ? BTN.ability : 0) | (edge(5) ? BTN.potion : 0),
    pressed: new Set<string>(),
    active: b.some(Boolean) || gp.axes.some((v) => Math.abs(v) > DEAD),
  };
  if (edge(6)) out.pressed.add("interact");
  if (edge(9)) out.pressed.add("bag");
  if (edge(8)) out.pressed.add("map");
  if (edge(12)) out.pressed.add("quick1");
  if (edge(15)) out.pressed.add("quick2");
  if (edge(13)) out.pressed.add("quick3");
  if (edge(14)) out.pressed.add("quick4");
  prev = b;
  return out;
}
