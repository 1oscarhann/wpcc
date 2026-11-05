// Item display helpers: tier-tinted icons and sprites, names, rarity colours.
import { manifest } from "../assets/manifest";
import { useSession } from "../state/session";

export const RARITY_COLOR: Record<string, string> = {
  common: "#9aa0a6",
  uncommon: "#4caf50",
  rare: "#3d8bfd",
  epic: "#a259ff",
  legendary: "#ff9f1c",
};

export const STATION_KEYS = new Set(["forge", "workshop", "tannery", "alchemist", "wizard_tower", "tavern"]);

/** Icon name for an item (tiered gear gets its tier's palette, P7). */
export function itemIcon(key: string, tier?: number | null): string {
  const cfg = useSession.getState().config;
  const base = (cfg?.items[key]?.icon ?? cfg?.resources[key]?.icon ?? "icon.info").replace(/^icon\./, "");
  if (tier && cfg?.recipes.gear[key]) {
    const t = `${base}_${tier}`;
    if (manifest.icons.names[t] !== undefined) return t;
  }
  return base;
}

export function itemName(key: string, tier?: number | null): string {
  const cfg = useSession.getState().config;
  if (key === "coins") return "Coins";
  const base = cfg?.items[key]?.name ?? cfg?.resources[key]?.name ?? key;
  if (tier && cfg?.recipes.gear[key]) return `${cfg.forging.tiers[tier - 1]?.name ?? ""} ${base}`.trim();
  return base;
}

/** World sprite for a held weapon: tiered for forged gear, plain for training gear. */
export function weaponSprite(type: string, key: string | null, tier: number): string {
  const kind = manifest.sprites[`wpn.${type}`] ? type : type === "spear" ? "spear" : "sword";
  const cfg = useSession.getState().config;
  if (key && cfg?.recipes.gear[key] && manifest.sprites[`wpn.${kind}.t${tier}`]) return `wpn.${kind}.t${tier}`;
  return `wpn.${kind}`;
}

export function modifierText(m: { key: string; name: string; effect: string; value: number }): string {
  if (m.effect === "crit") return `${m.name}: +${Math.round(m.value * 100)}% crit chance`;
  if (m.effect === "knockback") return `${m.name}: +${Math.round(m.value * 100)}% knockback`;
  if (m.effect === "venom") return `${m.name}: ${Math.round(m.value * 100)}% chance to poison`;
  if (m.effect === "frost") return `${m.name}: ${Math.round(m.value * 100)}% chance to slow`;
  if (m.effect === "fire") return `${m.name}: ${Math.round(m.value * 100)}% chance to burn`;
  if (m.effect === "lifesteal") return `${m.name}: heal ${Math.round(m.value * 100)}% of damage dealt`;
  if (m.effect === "chain") return `${m.name}: ${Math.round(m.value * 100)}% chance of chain lightning`;
  return `${m.name}: +${Math.round(m.value * 100)}% damage`;
}
