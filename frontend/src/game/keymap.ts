// Phase 18: every keyboard action in one place, rebindable from Settings (saved with your account).
// Keys are KeyboardEvent.key lowercased (" " is Space).

export type Action =
  | "up" | "down" | "left" | "right"
  | "attack" | "heavy" | "ability" | "dodge" | "offhand" | "potion"
  | "quick1" | "quick2" | "quick3" | "quick4"
  | "interact" | "bag" | "emote" | "journal" | "map" | "ride" | "photo" | "home";

export const ACTIONS: { key: Action; label: string; group: "Move" | "Fight" | "World" }[] = [
  { key: "up", label: "Walk up", group: "Move" },
  { key: "down", label: "Walk down", group: "Move" },
  { key: "left", label: "Walk left", group: "Move" },
  { key: "right", label: "Walk right", group: "Move" },
  { key: "attack", label: "Attack (also left mouse)", group: "Fight" },
  { key: "heavy", label: "Heavy attack (also right mouse)", group: "Fight" },
  { key: "ability", label: "Weapon ability", group: "Fight" },
  { key: "dodge", label: "Dodge roll", group: "Fight" },
  { key: "offhand", label: "Shield / bombs / tome", group: "Fight" },
  { key: "potion", label: "Drink a potion", group: "Fight" },
  { key: "quick1", label: "Quick slot 1", group: "Fight" },
  { key: "quick2", label: "Quick slot 2", group: "Fight" },
  { key: "quick3", label: "Quick slot 3", group: "Fight" },
  { key: "quick4", label: "Quick slot 4", group: "Fight" },
  { key: "interact", label: "Talk, trade, fish, use", group: "World" },
  { key: "bag", label: "Bag", group: "World" },
  { key: "emote", label: "Emotes and quick messages", group: "World" },
  { key: "journal", label: "Journal", group: "World" },
  { key: "map", label: "Map", group: "World" },
  { key: "ride", label: "Ride your mount", group: "World" },
  { key: "photo", label: "Photo mode", group: "World" },
  { key: "home", label: "Back to your village", group: "World" },
];

export const DEFAULTS: Record<Action, string[]> = {
  up: ["w", "arrowup"],
  down: ["s", "arrowdown"],
  left: ["a", "arrowleft"],
  right: ["d", "arrowright"],
  attack: ["j"],
  heavy: ["k"],
  ability: ["q"],
  dodge: [" ", "shift"],
  offhand: ["f"],
  potion: ["r"],
  quick1: ["1"],
  quick2: ["2"],
  quick3: ["3"],
  quick4: ["4"],
  interact: ["e"],
  bag: ["b", "i", "tab"],
  emote: ["t"],
  journal: ["l"], // J is the keyboard attack, so the journal is L for "log"
  map: ["m"],
  ride: ["g"],
  photo: ["p"],
  home: ["h"],
};

let map: Record<Action, string[]> = { ...DEFAULTS };

/** Load saved overrides (from /api/me settings.keybinds); unknown actions and junk are ignored. */
export function loadKeymap(saved: Record<string, unknown> | undefined): void {
  map = { ...DEFAULTS };
  for (const [a, keys] of Object.entries(saved ?? {})) {
    if (a in DEFAULTS && Array.isArray(keys) && keys.every((k) => typeof k === "string" && k.length <= 12)) {
      map[a as Action] = (keys as string[]).slice(0, 3);
    }
  }
}

export function keysFor(a: Action): string[] {
  return map[a];
}

export function isKey(k: string, a: Action): boolean {
  return map[a].includes(k);
}

export function anyDown(down: Set<string>, a: Action): boolean {
  return map[a].some((k) => down.has(k));
}

/** The overrides worth saving (only actions that differ from the defaults). */
export function overrides(next: Record<Action, string[]>): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const a of Object.keys(DEFAULTS) as Action[]) {
    if (next[a].join("|") !== DEFAULTS[a].join("|")) out[a] = next[a];
  }
  return out;
}

export function current(): Record<Action, string[]> {
  return { ...map };
}

export function keyLabel(k: string): string {
  if (k === " ") return "Space";
  if (k.startsWith("arrow")) return { arrowup: "↑", arrowdown: "↓", arrowleft: "←", arrowright: "→" }[k] ?? k;
  return k.length === 1 ? k.toUpperCase() : k[0].toUpperCase() + k.slice(1);
}
