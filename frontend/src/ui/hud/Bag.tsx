// The bag, in both modes: equipment (weapon, armour, potion), the grid, and a details card with
// equip / repair / salvage. Always reads the real inventory over REST (the room only mirrors stacks).
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { InventoryView, InvSlotView, VillageState } from "../../api/types";
import { itemIcon, itemName, modifierText, RARITY_COLOR } from "../../game/items";
import { sfx } from "../../game/sfx";
import { useAvatar } from "../../state/avatar";
import { useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { useVillage } from "../../state/village";
import { Icon } from "../components/kit";

const EQUIP = [
  { slot: 0, label: "Weapon" },
  { slot: 2, label: "Armour" },
  { slot: 4, label: "Potion" },
];

type Kind = "inventory" | "equipment" | "bank";
type Sel = { kind: Kind; s: InvSlotView } | null;

function Cell({ s, onClick, active, label }: { s?: InvSlotView; onClick: () => void; active: boolean; label?: string }) {
  const color = s?.rarity ? RARITY_COLOR[s.rarity] : undefined;
  const dull = s?.max_durability ? (s.durability ?? 0) <= 0 : false;
  return (
    <button className={`slot av-cell ${active ? "picked" : ""}`} onClick={onClick} disabled={!s}
      title={s ? `${s.name ?? itemName(s.item)}${s.qty > 1 ? ` ×${s.qty}` : ""}` : label ?? "Empty"}
      style={color && s?.rarity !== "common" ? { boxShadow: `inset 0 0 0 2px ${color}` } : undefined}>
      {s ? <Icon name={itemIcon(s.item, s.tier)} scale={2} /> : label ? <span className="small muted">{label}</span> : null}
      {s && s.qty > 1 && <span className="av-qty">{s.qty}</span>}
      {s?.max_durability ? (
        <span className="dura" aria-hidden><span style={{ width: `${((s.durability ?? 0) / s.max_durability) * 100}%`, background: dull ? "#ad433b" : "#8fc95c" }} /></span>
      ) : null}
    </button>
  );
}

export function Bag({ onClose }: { onClose: () => void }) {
  const [inv, setInv] = useState<InventoryView | null>(null);
  const [sel, setSel] = useState<Sel>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [tab, setTab] = useState<"inventory" | "bank">("inventory");
  const mode = useAvatar((s) => s.mode);
  const home = mode === "build";
  const roomInv = useAvatar((s) => s.inv);
  const version = useVillage((s) => s.village?.version);
  const config = useSession((s) => s.config)!;
  const load = useCallback(async () => {
    try {
      setInv(await api<InventoryView>("/api/inventory"));
    } catch {
      /* keep the last copy */
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load, roomInv, version]);
  useEffect(() => setConfirm(false), [sel]);

  const eq = new Map((inv?.equipment.slots ?? []).map((s) => [s.slot, s]));
  const bag = new Map((inv?.inventory.slots ?? []).map((s) => [s.slot, s]));
  const bank = new Map((inv?.bank?.slots ?? []).map((s) => [s.slot, s]));
  const cap = inv?.inventory.capacity ?? 24;
  const bankCap = inv?.bank?.capacity ?? 0;
  const firstFree = () => Array.from({ length: cap }, (_, i) => i).find((i) => !bag.has(i));
  const firstFreeBank = () => Array.from({ length: bankCap }, (_, i) => i).find((i) => !bank.has(i));
  const showing: "inventory" | "bank" = home ? tab : "inventory";
  const grid = showing === "bank" ? bank : bag;
  const gridCap = showing === "bank" ? bankCap : cap;
  const exp = showing === "bank" ? inv?.bank?.expand : inv?.inventory.expand;
  const stash = (s: InvSlotView) => {
    const free = firstFreeBank();
    if (free === undefined) return toast("Your bank is full.", "bad");
    void act("/api/inventory/move", { src: { kind: "inventory", slot: s.slot }, dst: { kind: "bank", slot: free } }, () => {
      sfx("deposit");
      return null;
    });
  };
  const takeOut = (s: InvSlotView) => {
    const free = firstFree();
    if (free === undefined) return toast("Your bag is full.", "bad");
    void act("/api/inventory/move", { src: { kind: "bank", slot: s.slot }, dst: { kind: "inventory", slot: free } }, () => {
      sfx("pickup");
      return null;
    });
  };
  const expand = () =>
    act("/api/inventory/expand", { kind: showing }, (r) => {
      sfx("levelup");
      return `${showing === "bank" ? "Bank" : "Bag"} now holds ${r.capacity as number} slots!`;
    });

  const act = async (path: string, body: unknown, ok?: (r: Record<string, unknown>) => string | null) => {
    setBusy(true);
    try {
      const r = await api<Record<string, unknown> & { inventory?: InventoryView; village?: VillageState }>(path, { method: "POST", body });
      // /move answers with the inventory itself; repair/salvage wrap it in `inventory`
      const next = "equipment" in r ? (r as unknown as InventoryView) : ((r.inventory as InventoryView | undefined) ?? null);
      if (next) setInv(next);
      else await load();
      const msg = ok?.(r);
      if (msg) toast(msg, "good");
      setSel(null);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
    } finally {
      setBusy(false);
    }
  };

  const equip = (s: InvSlotView) => {
    const cat = config.items[s.item]?.category;
    const dst = cat === "weapon" ? 0 : cat === "armour" ? 2 : cat === "consumable" ? 4 : null;
    if (dst === null) return;
    void act("/api/inventory/move", { src: { kind: "inventory", slot: s.slot }, dst: { kind: "equipment", slot: dst } }, () => {
      sfx("pickup");
      return null;
    });
  };
  const unequip = (s: InvSlotView) => {
    const free = firstFree();
    if (free === undefined) return toast("Your bag is full.", "bad");
    void act("/api/inventory/move", { src: { kind: "equipment", slot: s.slot }, dst: { kind: "inventory", slot: free } });
  };

  const detail = sel?.s;
  const cat = detail ? config.items[detail.item]?.category : null;
  const isGear = Boolean(detail?.max_durability);
  const forged = isGear && detail && config.recipes.gear[detail.item];
  const damaged = isGear && detail && (detail.durability ?? 0) < (detail.max_durability ?? 0);
  const armour = detail && cat === "armour" && detail.tier ? config.forging.armour[detail.item]?.[detail.tier - 1] : null;

  return (
    <div className="panel av-bag" role="dialog" aria-label="Bag">
      <div className="row" style={{ marginBottom: 8, gap: 6 }}>
        {!home && <span className="ribbon">Bag</span>}
        {!home && <span className="grow" />}
        {home && (
          <span className="row" role="tablist" style={{ gap: 4 }}>
            <button role="tab" aria-selected={tab === "inventory"} className={`btn small ${tab === "inventory" ? "" : "secondary"}`} onClick={() => { setTab("inventory"); setSel(null); }}>
              <Icon name="queue" scale={1.5} /> Bag
            </button>
            <button role="tab" aria-selected={tab === "bank"} className={`btn small ${tab === "bank" ? "" : "secondary"}`} onClick={() => { setTab("bank"); setSel(null); }}>
              <Icon name="chest" scale={1.5} /> Bank
            </button>
          </span>
        )}
        {home && <span className="grow" />}
        <button className="btn danger small icon-only" onClick={onClose} aria-label="Close bag"><Icon name="close" /></button>
      </div>
      {showing === "inventory" && <div className="row av-equip" style={{ gap: 8, marginBottom: 10 }}>
        {EQUIP.map(({ slot, label }) => (
          <div key={slot} className="col" style={{ alignItems: "center", gap: 2 }}>
            <Cell s={eq.get(slot)} label={label} active={sel?.kind === "equipment" && sel.s.slot === slot}
              onClick={() => { const s = eq.get(slot); if (s) setSel({ kind: "equipment", s }); }} />
            <span className="small muted">{label}</span>
          </div>
        ))}
      </div>}
      {detail && (
        <div className="slot bag-detail col" style={{ gap: 4, marginBottom: 10 }}>
          <div className="row" style={{ gap: 8 }}>
            <Icon name={itemIcon(detail.item, detail.tier)} scale={3} />
            <div className="col grow" style={{ gap: 0 }}>
              <span className="head" style={{ fontSize: 17, color: detail.rarity ? RARITY_COLOR[detail.rarity] : undefined }}>
                {detail.name ?? itemName(detail.item)}{detail.qty > 1 ? ` ×${detail.qty}` : ""}
              </span>
              <span className="small">
                {detail.rarity ? `${detail.rarity} · ` : ""}{cat?.replace("_", " ")}
                {armour ? ` · +${armour} defence` : ""}
              </span>
            </div>
          </div>
          {detail.max_durability ? (
            <span className="small">
              Durability {detail.durability}/{detail.max_durability}
              {(detail.durability ?? 0) <= 0 && <b style={{ color: "var(--red)" }}> · Dull (−30% damage, modifiers off)</b>}
            </span>
          ) : null}
          {(detail.modifiers ?? []).map((m, i) => <span key={i} className="small">✦ {modifierText(m)}</span>)}
          <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 4 }}>
            {sel!.kind === "inventory" && ["weapon", "armour", "consumable"].includes(cat ?? "") && (
              <button className="btn small" disabled={busy} onClick={() => equip(detail)}>Equip</button>
            )}
            {sel!.kind === "equipment" && <button className="btn secondary small" disabled={busy} onClick={() => unequip(detail)}>Unequip</button>}
            {home && sel!.kind === "inventory" && (
              <button className="btn secondary small" disabled={busy} onClick={() => stash(detail)}><Icon name="chest" scale={1.5} /> To bank</button>
            )}
            {sel!.kind === "bank" && (
              <button className="btn small" disabled={busy} onClick={() => takeOut(detail)}><Icon name="queue" scale={1.5} /> To bag</button>
            )}
            {damaged && (
              <button className="btn small" disabled={busy}
                onClick={() => act("/api/inventory/repair", { kind: sel!.kind, slot: detail.slot }, (r) => {
                  sfx("clang");
                  const paid = r.paid as Record<string, number>;
                  return `Repaired for ${Object.entries(paid).map(([k, q]) => `${q} ${itemName(k).toLowerCase()}`).join(", ")}.`;
                })}>
                <Icon name="anvil" scale={1.5} /> Repair
              </button>
            )}
            {forged && sel!.kind === "inventory" && (
              confirm ? (
                <button className="btn danger small" disabled={busy}
                  onClick={() => act("/api/inventory/salvage", { slot: detail.slot }, (r) => {
                    const back = r.returned as Record<string, number>;
                    const parts = Object.entries(back).map(([k, q]) => `${q} ${itemName(k).toLowerCase()}`);
                    return parts.length ? `Salvaged: ${parts.join(", ")} back in storage.` : "Salvaged.";
                  })}>
                  Sure? (40% back)
                </button>
              ) : (
                <button className="btn secondary small" onClick={() => setConfirm(true)}>Salvage</button>
              )
            )}
          </div>
        </div>
      )}
      <div className="row" style={{ gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        <span className="small muted grow">
          {grid.size}/{gridCap} slots ·{" "}
          {showing === "bank" ? "Safe at home: nothing in the bank can be lost when you're knocked out." : "Resources go into storage when you walk home."}
        </span>
        {home && exp && exp.next_cost !== null && (
          <button className="btn small gold" disabled={busy} onClick={() => void expand()}
            title={`Up to ${exp.max} slots`}>
            <Icon name="plus" scale={1.5} /> +{exp.step} slots · {exp.next_cost.toLocaleString()} <Icon name="coins" scale={1} />
          </button>
        )}
      </div>
      <div className="av-grid">
        {Array.from({ length: gridCap }, (_, i) => (
          <Cell key={`${showing}${i}`} s={grid.get(i)} active={sel?.kind === showing && sel.s.slot === i}
            onClick={() => { const s = grid.get(i); if (s) setSel({ kind: showing, s }); }} />
        ))}
      </div>
    </div>
  );
}
