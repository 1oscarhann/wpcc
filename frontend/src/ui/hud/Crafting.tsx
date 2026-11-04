// Phase 6 panels: the Recipe Book, a station's crafting panel, the discovery card and the forge reveal.
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { ForgedItem, InventoryView, VillageState } from "../../api/types";
import { amountAt } from "../../game/resources";
import { itemIcon, itemName, modifierText, RARITY_COLOR } from "../../game/items";
import { sfx } from "../../game/sfx";
import { useCrafting } from "../../state/crafting";
import { serverNow, useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { useVillage } from "../../state/village";
import { formatDuration, formatNum, Icon, Modal } from "../components/kit";
import { SpriteThumb } from "../components/SpriteThumb";

function resIcon(k: string): string {
  if (k === "coins") return "coins";
  return itemIcon(k);
}

function Cost({ cost, v, times = 1 }: { cost: Record<string, number>; v: VillageState; times?: number }) {
  const now = serverNow();
  return (
    <span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
      {Object.entries(cost).map(([k, q]) => {
        const need = q * times;
        const have = k === "coins" ? v.coins ?? 0 : v.resources[k] ? amountAt(v.resources[k], v.at_ms, now) : 0;
        return (
          <span key={k} className="row" style={{ gap: 2, color: have < need ? "var(--red)" : undefined }} title={itemName(k)}>
            <Icon name={resIcon(k)} scale={1.5} />
            <span className="head" style={{ fontSize: 15 }}>{formatNum(need)}</span>
          </span>
        );
      })}
    </span>
  );
}

// ── Recipe Book ────────────────────────────────────────────────────────────
interface BookCombo {
  id: string;
  discovered: boolean;
  name?: string;
  buildings?: string[];
  unlocks?: string[];
  hint: string;
  size?: number;
  legendary_eligible?: boolean;
}

export function RecipeBook({ onClose }: { onClose: () => void }) {
  const [book, setBook] = useState<{ combos: BookCombo[]; found: number; total: number } | null>(null);
  const config = useSession((s) => s.config)!;
  useEffect(() => {
    api<{ combos: BookCombo[]; found: number; total: number }>("/api/crafting/book").then(setBook).catch(() => toast("Couldn't open the book.", "bad"));
  }, []);
  return (
    <Modal title="Recipe Book" onClose={onClose} wide>
      {!book ? (
        <p>Opening…</p>
      ) : (
        <div className="col" style={{ gap: 10 }}>
          <p className="small muted" style={{ margin: 0 }}>
            Buildings that <b>touch edge to edge</b> work together. Found {book.found} of {book.total} combos.
          </p>
          <div className="book-grid">
            {book.combos.map((c) =>
              c.discovered ? (
                <div key={c.id} className="slot book-card found">
                  <div className="row" style={{ gap: 4, justifyContent: "center" }}>
                    {c.buildings!.map((b, i) => (
                      <span key={b} className="row" style={{ gap: 4 }}>
                        {i > 0 && <span className="head">+</span>}
                        <SpriteThumb name={`building.${b}.a.l1`} box={44} maxScale={1} />
                      </span>
                    ))}
                  </div>
                  <span className="head" style={{ fontSize: 18 }}>{c.name}</span>
                  <span className="small">
                    {c.buildings!.map((b) => config.buildings[b]?.name ?? b).join(" + ")}
                  </span>
                  <span className="row small" style={{ gap: 6, justifyContent: "center" }}>
                    Forges {c.unlocks!.map((u) => (
                      <span key={u} className="row" style={{ gap: 2 }}><Icon name={itemIcon(u, 1)} scale={1.5} /> {itemName(u)}</span>
                    ))}
                  </span>
                  {c.legendary_eligible && <span className="small" style={{ color: RARITY_COLOR.legendary }}>Legendary possible</span>}
                </div>
              ) : (
                <div key={c.id} className="slot book-card secret">
                  <div className="row" style={{ gap: 6, justifyContent: "center" }}>
                    {Array.from({ length: c.size ?? 2 }, (_, i) => (
                      <span key={i} className="row" style={{ gap: 6 }}>
                        {i > 0 && <span className="head">+</span>}
                        <span className="book-q head">?</span>
                      </span>
                    ))}
                  </div>
                  <span className="head" style={{ fontSize: 18 }}>???</span>
                  <span className="small" style={{ fontStyle: "italic" }}>“{c.hint}”</span>
                </div>
              ),
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

// ── Station panel ──────────────────────────────────────────────────────────
interface StationOptions {
  station_id: string;
  key: string;
  slots: number;
  intermediates: { recipe: string; inputs: Record<string, number>; seconds_per_unit: number; max_batch: number }[];
  gear: {
    recipe: string;
    name: string;
    tier: number;
    combo: string;
    combo_name: string;
    bill: Record<string, number>;
    seconds: number;
    legendary_eligible: boolean;
    odds: number[][];
  }[];
  rare_materials: Record<string, { modifier: string; range: [number, number] }>;
  jobs: { id: string; kind: string; recipe: string; quantity: number; tier: number | null; started_at_ms: number; completes_at_ms: number }[];
}

function Odds({ odds }: { odds: number[] }) {
  const keys = ["common", "uncommon", "rare", "epic", "legendary"];
  return (
    <div className="odds" title="Rarity odds">
      {odds.map((p, i) =>
        p > 0 ? <span key={keys[i]} style={{ width: `${p * 100}%`, background: RARITY_COLOR[keys[i]] }} title={`${keys[i]} ${(p * 100).toFixed(1)}%`} /> : null,
      )}
    </div>
  );
}

export function CraftPanel({ stationId, onClose }: { stationId: string; onClose: () => void }) {
  const v = useVillage((s) => s.village)!;
  const apply = useVillage((s) => s.apply);
  const config = useSession((s) => s.config)!;
  const [opts, setOpts] = useState<StationOptions | null>(null);
  const [inv, setInv] = useState<InventoryView | null>(null);
  const [qty, setQty] = useState<Record<string, number>>({});
  const [rares, setRares] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(serverNow());
  const load = useCallback(async () => {
    try {
      const [o, i] = await Promise.all([
        api<StationOptions>(`/api/crafting/stations/${stationId}`),
        api<InventoryView>("/api/inventory"),
      ]);
      setOpts(o);
      setInv(i);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't open the station.", "bad");
    }
  }, [stationId]);
  useEffect(() => {
    void load();
  }, [load, v.version]);
  useEffect(() => {
    const id = window.setInterval(() => setNow(serverNow()), 250);
    return () => window.clearInterval(id);
  }, []);
  const station = v.buildings.find((b) => b.id === stationId);
  const name = station ? config.buildings[station.key]?.name : "Station";
  const jobs = v.jobs.filter((j) => j.station_id === stationId);
  const full = opts ? jobs.length >= opts.slots : true;
  const rareStock: Record<string, number> = {};
  for (const s of inv?.inventory.slots ?? []) if (opts?.rare_materials[s.item]) rareStock[s.item] = (rareStock[s.item] ?? 0) + s.qty;

  const run = async (path: string, body?: unknown) => {
    setBusy(true);
    try {
      const r = await api<{ village: VillageState; item?: ForgedItem; refunded?: Record<string, number> }>(path, { method: "POST", body });
      apply(r.village);
      if (r.item) {
        sfx("reveal");
        useCrafting.getState().set({ reveal: r.item });
      }
      await load();
      return r;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
      return null;
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={name ?? "Station"} onClose={onClose} wide>
      {!opts ? (
        <p>Lighting the fire…</p>
      ) : (
        <div className="col craft" style={{ gap: 12 }}>
          {jobs.length > 0 && (
            <div className="col" style={{ gap: 6 }}>
              <h3 style={{ margin: 0 }}>Working on</h3>
              {jobs.map((j) => {
                const total = j.completes_at_ms - j.started_at_ms;
                const left = Math.max(0, j.completes_at_ms - now);
                const done = left <= 0;
                return (
                  <div key={j.id} className="row slot craft-job" style={{ gap: 8 }}>
                    <Icon name={itemIcon(j.recipe, j.tier)} scale={2} />
                    <div className="col grow" style={{ gap: 2 }}>
                      <span className="head">{j.kind === "gear" ? itemName(j.recipe, j.tier) : `${itemName(j.recipe)} ×${j.quantity}`}</span>
                      <div className="av-bar" style={{ height: 8 }}>
                        <div className="av-bar-fill" style={{ width: `${(1 - left / Math.max(1, total)) * 100}%`, background: "linear-gradient(#ffc04d, #d4542e)" }} />
                      </div>
                    </div>
                    {done && j.kind === "gear" ? (
                      <button className="btn gold small" disabled={busy} onClick={() => run(`/api/crafting/jobs/${j.id}/collect`)}>
                        <Icon name="star" scale={1.5} /> Collect
                      </button>
                    ) : done ? (
                      <span className="small head">Stored!</span>
                    ) : (
                      <>
                        <span className="small">{formatDuration(left / 1000)}</span>
                        <button className="btn danger small icon-only" disabled={busy} title="Cancel (75% back)"
                          onClick={() => run(`/api/crafting/jobs/${j.id}/cancel`)}>
                          <Icon name="close" scale={1.5} />
                        </button>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {opts.intermediates.length > 0 && (
            <div className="col" style={{ gap: 6 }}>
              <h3 style={{ margin: 0 }}>Make goods <span className="small muted">(go straight into storage)</span></h3>
              {opts.intermediates.map((r) => {
                const n = qty[r.recipe] ?? 5;
                return (
                  <div key={r.recipe} className="row slot craft-row" style={{ gap: 8, flexWrap: "wrap" }}>
                    <Icon name={itemIcon(r.recipe)} scale={2} />
                    <span className="head" style={{ minWidth: 70 }}>{itemName(r.recipe)}</span>
                    <div className="row stepper" style={{ gap: 4 }}>
                      <button className="btn secondary small icon-only" onClick={() => setQty({ ...qty, [r.recipe]: Math.max(1, n - 1) })} aria-label="Fewer">−</button>
                      <span className="value head">{n}</span>
                      <button className="btn secondary small icon-only" onClick={() => setQty({ ...qty, [r.recipe]: Math.min(r.max_batch, n + 1) })} aria-label="More">+</button>
                    </div>
                    <Cost cost={r.inputs} v={v} times={n} />
                    <span className="small"><Icon name="timer" scale={1} /> {formatDuration(r.seconds_per_unit * n)}</span>
                    <span className="grow" />
                    <button className="btn small" disabled={busy || full} onClick={() => run("/api/crafting/jobs", { station_id: stationId, recipe: r.recipe, quantity: n })}>
                      Make
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          <div className="col" style={{ gap: 6 }}>
            <h3 style={{ margin: 0 }}>Forge gear</h3>
            {opts.gear.length === 0 ? (
              <p className="small muted" style={{ margin: 0 }}>
                Nothing to forge here yet. Gear needs this station to <b>touch the right buildings</b>. The Recipe Book has hints.
              </p>
            ) : (
              opts.gear.map((g) => {
                const picked = rares[g.recipe] ?? [];
                const odds = g.odds[Math.min(picked.length, g.odds.length - 1)];
                return (
                  <div key={g.recipe} className="col slot craft-gear" style={{ gap: 6 }}>
                    <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                      <Icon name={itemIcon(g.recipe, g.tier)} scale={3} />
                      <div className="col" style={{ gap: 0 }}>
                        <span className="head" style={{ fontSize: 18 }}>{g.name}</span>
                        <span className="small">from your {g.combo_name} · tier {g.tier}{g.legendary_eligible ? " · legendary possible" : ""}</span>
                      </div>
                      <span className="grow" />
                      <Cost cost={g.bill} v={v} />
                      <span className="small"><Icon name="timer" scale={1} /> {formatDuration(g.seconds)}</span>
                    </div>
                    <Odds odds={odds} />
                    <div className="row small" style={{ gap: 6, flexWrap: "wrap" }}>
                      <span className="muted">Rare materials: +luck, a guaranteed modifier, at least Uncommon.</span>
                      {Object.entries(opts.rare_materials).map(([rk, m]) => {
                        const have = (rareStock[rk] ?? 0) - picked.filter((x) => x === rk).length;
                        const on = picked.filter((x) => x === rk).length;
                        return (
                          <button key={rk} className={`btn small ${on ? "selected" : "secondary"}`} disabled={have <= 0 && !on}
                            title={`${itemName(rk)}: ${m.modifier}. You have ${rareStock[rk] ?? 0}.`}
                            onClick={() => {
                              const next = on ? picked.filter((_, i) => i !== picked.lastIndexOf(rk)) : [...picked, rk];
                              if (next.length <= config.forging.max_rare_inputs) setRares({ ...rares, [g.recipe]: next });
                            }}>
                            <Icon name={itemIcon(rk)} scale={1.5} /> {m.modifier}{on ? ` ×${on}` : ""}
                          </button>
                        );
                      })}
                    </div>
                    <div className="row">
                      <span className="grow" />
                      <button className="btn gold" disabled={busy || full}
                        onClick={async () => {
                          const r = await run("/api/crafting/jobs", { station_id: stationId, recipe: g.recipe, rares: picked });
                          if (r) {
                            sfx("clang");
                            setRares({ ...rares, [g.recipe]: [] });
                          }
                        }}>
                        <Icon name="anvil" scale={2} /> Forge!
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
          {full && <p className="small muted" style={{ margin: 0 }}>This station is busy. It can run {opts.slots} job{opts.slots > 1 ? "s" : ""} at once.</p>}
        </div>
      )}
    </Modal>
  );
}

// ── the discovery card and the forge reveal ────────────────────────────────
export function DiscoveryCard() {
  const d = useCrafting((s) => s.discovery);
  const config = useSession((s) => s.config)!;
  if (!d) return null;
  const close = () => useCrafting.getState().set({ discovery: null });
  return (
    <div className="modal-backdrop reveal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="panel reveal-card discovery" role="dialog" aria-label="Combo discovered">
        <div className="reveal-rays" aria-hidden />
        <span className="ribbon">Combo discovered!</span>
        <div className="row" style={{ gap: 6, justifyContent: "center", marginTop: 12 }}>
          {d.buildings.map((b, i) => (
            <span key={`${b}${i}`} className="row" style={{ gap: 6 }}>
              {i > 0 && <span className="head" style={{ fontSize: 24 }}>+</span>}
              <SpriteThumb name={`building.${b}.a.l1`} box={64} maxScale={1} />
            </span>
          ))}
        </div>
        <h2 className="head" style={{ margin: "8px 0 2px" }}>{d.name}</h2>
        <p className="small" style={{ margin: 0 }}>{d.buildings.map((b) => config.buildings[b]?.name ?? b).join(" + ")}</p>
        <div className="row" style={{ gap: 8, justifyContent: "center", margin: "10px 0 4px" }}>
          <span>Unlocks</span>
          {d.unlocks.map((u) => (
            <span key={u} className="row combo-chip" style={{ gap: 4 }}><Icon name={itemIcon(u, 1)} scale={1.5} /> {itemName(u)}</span>
          ))}
        </div>
        <p className="small" style={{ margin: "0 0 12px" }}>
          Forge it at the station in this combo. Higher-level buildings forge better tiers.
        </p>
        <button className="btn gold" onClick={close} autoFocus>Amazing!</button>
      </div>
    </div>
  );
}

export function RevealCard() {
  const it = useCrafting((s) => s.reveal);
  if (!it) return null;
  const color = RARITY_COLOR[it.rarity] ?? "#fff";
  const close = () => useCrafting.getState().set({ reveal: null });
  return (
    <div className="modal-backdrop reveal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className={`panel reveal-card rarity-${it.rarity}`} role="dialog" aria-label="Forged item" style={{ ["--rc" as string]: color }}>
        <div className="reveal-rays" aria-hidden />
        <span className="ribbon">Fresh from the forge</span>
        <div className="reveal-item">
          <Icon name={itemIcon(it.item, it.tier)} scale={6} />
        </div>
        <h2 className="head" style={{ margin: "4px 0 0", color }}>{it.name}</h2>
        <span className="rarity-chip head" style={{ background: color }}>{it.rarity}</span>
        <div className="col small" style={{ gap: 2, margin: "10px 0" }}>
          {it.modifiers.length === 0 ? <span className="muted">No modifiers</span> : it.modifiers.map((m, i) => <span key={i}>✦ {modifierText(m)}</span>)}
          <span>Durability {it.durability}/{it.max_durability}</span>
        </div>
        <p className="small muted" style={{ margin: "0 0 10px" }}>It's in your bag. Equip it from the Bag.</p>
        <button className="btn gold" onClick={close} autoFocus>Nice!</button>
      </div>
    </div>
  );
}
