import { useEffect, useMemo, useState } from "react";
import type { BuildingDef, BuildingState, VillageState } from "../../api/types";
import { canAfford, amountAt } from "../../game/resources";
import { PLACEMENT_TEXT, localPlacementError } from "../../game/placement";
import { itemName, STATION_KEYS } from "../../game/items";
import { enterAvatar } from "../../net/room";
import { useMarket } from "../../state/market";
import { useCrafting } from "../../state/crafting";
import { serverNow, useSession } from "../../state/session";
import { useVillage } from "../../state/village";
import { formatDuration, formatNum, Icon, Panel } from "../components/kit";
import { SpriteThumb } from "../components/SpriteThumb";

export function useTick(ms = 250): number {
  const [t, setT] = useState(() => serverNow());
  useEffect(() => {
    const id = window.setInterval(() => setT(serverNow()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return t;
}

const CATEGORIES: { key: string; label: string }[] = [
  { key: "core", label: "Core" },
  { key: "production", label: "Production" },
  { key: "crafting", label: "Crafting" },
];

function CostChips({ cost, v, now }: { cost: Record<string, number>; v: VillageState; now: number }) {
  const config = useSession((s) => s.config)!;
  const missing = canAfford(cost, v.resources, v.coins, v.at_ms, now);
  const entries = Object.entries(cost);
  if (!entries.length) return <span className="small muted">Free</span>;
  return (
    <span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
      {entries.map(([k, q]) => (
        <span key={k} className="row" style={{ gap: 2, color: missing[k] ? "var(--red)" : undefined }}
          title={k === "coins" ? "Coins" : config.resources[k]?.name ?? k}>
          <Icon name={k === "coins" ? "coins" : config.resources[k]?.icon.replace("icon.", "") ?? k} scale={1.5} />
          <span className="head" style={{ fontSize: 15 }}>{formatNum(q)}</span>
        </span>
      ))}
    </span>
  );
}

function TopBar({ v, now, onSettings }: { v: VillageState; now: number; onSettings: () => void }) {
  const config = useSession((s) => s.config)!;
  const iconScale = window.innerWidth < 640 ? 1.5 : 2;
  const keys = config.hud_order.filter((k) => {
    const r = v.resources[k];
    return r && (r.amount > 0 || r.rate > 0 || ["wood", "stone", "ore", "food"].includes(k));
  });
  return (
    <div className="hud-top">
      <div className="hud-bar hud-resources" role="status" aria-label="Resources">
        {keys.map((k) => {
          const r = v.resources[k];
          const amount = amountAt(r, v.at_ms, now);
          const full = amount >= r.cap;
          return (
            <span key={k} className="hud-res" title={`${config.resources[k].name}: ${Math.floor(amount)} / ${r.cap}` +
              (r.rate ? ` (+${r.rate}/h)` : "")}>
              <Icon name={config.resources[k].icon.replace("icon.", "")} scale={iconScale} />
              <span className="head" style={{ color: full ? "var(--gold-light)" : undefined }}>{formatNum(amount)}</span>
              {r.rate > 0 && <span className="hud-rate">+{formatNum(r.rate)}/h</span>}
            </span>
          );
        })}
        <span className="hud-res" title="Coins">
          <Icon name="coins" scale={iconScale} />
          <span className="head">{formatNum(v.coins ?? 0)}</span>
        </span>
      </div>
      <div className="row" style={{ gap: 6 }}>
        <span className="hud-bar hud-chip" title="Builders busy / available">
          <Icon name="build" scale={1.5} /> {v.queue.used}/{v.queue.slots}
        </span>
        <button className="btn secondary icon-only" onClick={onSettings} aria-label="Settings">
          <Icon name="settings" />
        </button>
      </div>
    </div>
  );
}

function BuildMenu({ v, now, onClose }: { v: VillageState; now: number; onClose: () => void }) {
  const config = useSession((s) => s.config)!;
  const startPlacing = useVillage((s) => s.startPlacing);
  const [cat, setCat] = useState("production");
  const defs = config.buildings;
  const list = Object.entries(defs).filter(([, d]) => d.category === cat);
  return (
    <div className="panel build-menu" role="dialog" aria-label="Build menu">
      <div className="row" style={{ marginBottom: 8 }}>
        <span className="ribbon">Build</span>
        <span className="grow" />
        <button className="btn danger small icon-only" onClick={onClose} aria-label="Close build menu">
          <Icon name="close" />
        </button>
      </div>
      <div className="row tabs" role="tablist">
        {CATEGORIES.map((c) => (
          <button key={c.key} role="tab" aria-selected={cat === c.key}
            className={`btn small ${cat === c.key ? "selected" : "secondary"}`} onClick={() => setCat(c.key)}>
            {c.label}
          </button>
        ))}
      </div>
      <div className="build-grid">
        {list.map(([key, d]) => {
          const count = v.buildings.filter((b) => b.key === key).length;
          const max = d.max_count[v.town_hall_level - 1];
          const locked = d.unlock_town_hall > v.town_hall_level;
          const full = !locked && count >= max;
          const cost = d.levels[0].cost;
          const missing = canAfford(cost, v.resources, v.coins, v.at_ms, now);
          const disabled = locked || full;
          return (
            <button key={key} className={`build-card slot ${disabled ? "is-disabled" : ""}`} disabled={disabled}
              aria-label={`${d.name}${locked ? " (locked)" : ""}`}
              onClick={() => {
                startPlacing({ key, rotation: 0 });
                onClose();
              }}>
              <SpriteThumb name={`building.${key}.a.l1`} box={80} maxScale={3} dim={disabled} />
              <span className="head" style={{ fontSize: 16 }}>{d.name}</span>
              {locked ? (
                <span className="small row" style={{ gap: 4 }}><Icon name="lock" scale={1} /> Town Hall {d.unlock_town_hall}</span>
              ) : (
                <>
                  <CostChips cost={cost} v={v} now={now} />
                  <span className="small muted row" style={{ gap: 4 }}>
                    <Icon name="timer" scale={1} /> {formatDuration(d.levels[0].time_s)} · {count}/{max}
                    {Object.keys(missing).length > 0 && <span style={{ color: "var(--red)" }}> · need more</span>}
                  </span>
                </>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function describeLevel(d: BuildingDef, level: number, config: ReturnType<typeof useSession.getState>["config"]) {
  if (level < 1) return null;
  const lv = d.levels[level - 1];
  const parts = Object.entries(lv.production).map(([k, r]) => `+${r} ${config!.resources[k].name.toLowerCase()}/h`);
  if (lv.storage) parts.push(`${d.name === "Town Hall" ? "" : "+"}${formatNum(lv.storage)} storage`);
  if (lv.housing) parts.push(`houses ${lv.housing}`);
  return parts.join(" · ");
}

function SelectionPanel({ v, b, now }: { v: VillageState; b: BuildingState; now: number }) {
  const config = useSession((s) => s.config)!;
  const { upgrade, cancel, demolish, startPlacing, select, busy } = useVillage();
  const [confirm, setConfirm] = useState(false);
  const d = config.buildings[b.key];
  const working = b.state !== "active";
  const next = b.level < d.max_level ? d.levels[b.level] : null;
  const capped = b.key !== "town_hall" && b.level + 1 > v.town_hall_level;
  useEffect(() => setConfirm(false), [b.id]);
  return (
    <Panel className="selection">
      <div className="row" style={{ gap: 10, alignItems: "flex-start" }}>
        <SpriteThumb name={`building.${b.key}.a.l${Math.max(1, b.level)}`} box={64} />
        <div className="col grow" style={{ gap: 2 }}>
          <div className="row">
            <h3>{d.name}</h3>
            <span className="grow" />
            <button className="btn danger small icon-only" onClick={() => select(null)} aria-label="Close">
              <Icon name="close" scale={1.5} />
            </button>
          </div>
          <span className="small">
            {b.state === "constructing" && b.level === 0 ? "Under construction" : `Level ${b.level}`}
            {working && b.completes_at_ms ? ` · ${formatDuration((b.completes_at_ms - now) / 1000)} left` : ""}
          </span>
          <span className="small muted">{describeLevel(d, b.level, config) || d.description}</span>
          {v.combos.filter((c) => c.buildings.includes(b.id)).map((c) => (
            <span key={c.key + c.buildings.join()} className="small combo-chip" title={`Tier ${c.tier}: the lowest level in the combo`}>
              ✦ {c.name} · forges {c.unlocks.map((u) => itemName(u, c.tier)).join(", ")}
            </span>
          ))}
        </div>
      </div>
      {!working && next && (
        <div className="col" style={{ gap: 4, marginTop: 8 }}>
          <span className="small">
            <b>Level {b.level + 1}:</b> {describeLevel(d, b.level + 1, config) || "a grander look"} ·{" "}
            <Icon name="timer" scale={1} /> {formatDuration(next.time_s)}
          </span>
          <CostChips cost={next.cost} v={v} now={now} />
        </div>
      )}
      <div className="row" style={{ marginTop: 10, flexWrap: "wrap", gap: 6 }}>
        {working ? (
          <button className="btn danger small" disabled={busy} onClick={() => cancel(b.id)}>
            <Icon name="close" scale={1.5} /> Cancel (75% back)
          </button>
        ) : next ? (
          <button className="btn small" disabled={busy || capped} onClick={() => upgrade(b.id)}
            title={capped ? "Upgrade your Town Hall first" : undefined}>
            <Icon name="upgrade" scale={1.5} /> {capped ? "Needs higher Town Hall" : "Upgrade"}
          </button>
        ) : (
          <span className="small head">Max level!</span>
        )}
        {b.key === "market" && b.level >= 1 && (
          <button className="btn gold small" onClick={() => useMarket.getState().set({ marketOpen: true })}>
            <Icon name="market" scale={1.5} /> Trade
          </button>
        )}
        {STATION_KEYS.has(b.key) && b.level >= 1 && (
          <button className="btn gold small" onClick={() => useCrafting.getState().set({ stationId: b.id })}>
            <Icon name="anvil" scale={1.5} /> Craft
            {v.jobs.some((j) => j.station_id === b.id && j.kind === "gear" && j.completes_at_ms <= now) && " (ready!)"}
          </button>
        )}
        <button className="btn secondary small" onClick={() => startPlacing({ key: b.key, rotation: b.rotation, moveId: b.id })}>
          <Icon name="move" scale={1.5} /> Move
        </button>
        {d.demolishable && !working && (
          confirm ? (
            <button className="btn danger small" disabled={busy} onClick={() => demolish(b.id)}>Sure? (50% back)</button>
          ) : (
            <button className="btn secondary small" onClick={() => setConfirm(true)} aria-label="Demolish">
              <Icon name="demolish" scale={1.5} />
            </button>
          )
        )}
      </div>
    </Panel>
  );
}

function ComboHint() {
  const placing = useVillage((s) => s.placing);
  const p = useVillage((s) => s.previewInfo);
  if (!placing || !p || p.x !== placing.x || p.y !== placing.y || p.rotation !== placing.rotation || p.key !== placing.key) {
    return null;
  }
  if (!p.combos.length && !p.mystery) return null;
  return (
    <div className="row combo-hint" style={{ gap: 6, flexWrap: "wrap" }}>
      {p.combos.map((c) => (
        <span key={c.key} className="combo-chip">✦ Forms {c.name}: {c.unlocks.map((u) => itemName(u)).join(", ")}</span>
      ))}
      {p.mystery > 0 && <span className="combo-chip mystery">✨ Something resonates here…</span>}
    </div>
  );
}

function PlacementBar({ v, touch }: { v: VillageState; touch: boolean }) {
  const config = useSession((s) => s.config)!;
  const { placing, rotateGhost, startPlacing, confirmPlacement, busy } = useVillage();
  if (!placing) return null;
  const d = config.buildings[placing.key];
  const err =
    placing.x !== undefined && placing.y !== undefined
      ? localPlacementError(v, config.buildings, placing.key, placing.x, placing.y, placing.rotation, placing.moveId)
      : null;
  return (
    <Panel className="placement-bar">
      <div className="col" style={{ gap: 6 }}>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <span className="head">{placing.moveId ? `Moving ${d.name}` : `Place ${d.name}`}</span>
          <span className="grow" />
          {err ? (
            <span className="small" style={{ color: "var(--red)" }}>{PLACEMENT_TEXT[err]}</span>
          ) : (
            <span className="small muted">
              {touch ? "Tap a spot, then confirm." : "Click to place · R rotate · Esc cancel"}
            </span>
          )}
        </div>
        <ComboHint />
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          <button className="btn secondary small" onClick={rotateGhost}><Icon name="rotate" scale={1.5} /> Rotate</button>
          <button className="btn danger small" onClick={() => startPlacing(null)}>Cancel</button>
          {(touch || placing.moveId) && (
            <button className="btn gold small" disabled={busy || !!err || placing.x === undefined} onClick={confirmPlacement}>
              <Icon name="check" scale={1.5} /> {placing.moveId ? "Move here" : "Place here"}
            </button>
          )}
        </div>
      </div>
    </Panel>
  );
}

function ClearHint({ v }: { v: VillageState }) {
  const [seen, setSeen] = useState(() => {
    try {
      return localStorage.getItem("hf.hint.clear") === "1";
    } catch {
      return false;
    }
  });
  const [startCount] = useState(v.debris.length);
  useEffect(() => {
    if (!seen && v.debris.length < startCount) {
      setSeen(true);
      try {
        localStorage.setItem("hf.hint.clear", "1");
      } catch {
        /* private mode: the hint just shows again next time */
      }
    }
  }, [v.debris.length, startCount, seen]);
  if (seen || v.debris.length === 0) return null;
  return (
    <div className="hud-hint hud-bar small">
      <Icon name="demolish" scale={1.5} /> Tap trees, rocks and bushes on your land to clear them for wood, stone and food.
    </div>
  );
}

export function BuildHud({ onSettings, touch, onZoom }: {
  onSettings: () => void;
  touch: boolean;
  onZoom: (dir: number) => void;
}) {
  const v = useVillage((s) => s.village);
  const selectedId = useVillage((s) => s.selectedId);
  const placing = useVillage((s) => s.placing);
  const undo = useVillage((s) => s.undo);
  const wsConnected = useVillage((s) => s.wsConnected);
  const [menu, setMenu] = useState(false);
  const now = useTick(250);
  const selected = useMemo(() => v?.buildings.find((b) => b.id === selectedId), [v, selectedId]);
  if (!v) return null;
  const undoLeft = v.undo ? Math.ceil((v.undo.expires_at_ms - now) / 1000) : 0;
  return (
    <div className="hud">
      <TopBar v={v} now={now} onSettings={onSettings} />
      <div className="village-name"><span className="ribbon">{v.name}</span></div>
      <ClearHint v={v} />
      {!wsConnected && <div className="panel-dark hud-offline small">Reconnecting… (updates every few seconds)</div>}
      <div className="hud-bottom">
        {placing ? (
          <PlacementBar v={v} touch={touch} />
        ) : selected ? (
          <SelectionPanel v={v} b={selected} now={now} />
        ) : (
          <div className="row hud-actions">
            <button className="btn gold" onClick={() => setMenu(true)} aria-label="Build">
              <Icon name="build" /> Build
            </button>
            <button className="btn secondary" onClick={() => useCrafting.getState().set({ bookOpen: true })} aria-label="Recipe Book" title="Recipe Book">
              <Icon name="book" /> <span className="hide-narrow">Recipes</span>
            </button>
            <button className="btn secondary" onClick={() => useMarket.getState().set({ marketOpen: true })} aria-label="Market" title="Market: sell goods, see the merchant">
              <Icon name="market" /> <span className="hide-narrow">Market</span>
            </button>
            <button className="btn secondary icon-only" onClick={() => useCrafting.getState().set({ bagOpen: true })} aria-label="Bag and bank" title="Bag and bank">
              <Icon name="queue" />
            </button>
            {undoLeft > 0 && (
              <button className="btn secondary" onClick={undo} aria-label="Undo">
                <Icon name="undo" /> Undo <span className="small">({undoLeft}s)</span>
              </button>
            )}
            <span className="grow" />
            <div className="row zoom-buttons" style={{ gap: 4 }}>
              <button className="btn secondary small icon-only" onClick={() => onZoom(-1)} aria-label="Zoom out">−</button>
              <button className="btn secondary small icon-only" onClick={() => onZoom(1)} aria-label="Zoom in">+</button>
            </div>
            <button className="btn gold" onClick={enterAvatar} aria-label="Explore" title="Step outside as your hero">
              <Icon name="avatar" /> <span className="hide-narrow">Explore</span>
            </button>
          </div>
        )}
      </div>
      {menu && <BuildMenu v={v} now={now} onClose={() => setMenu(false)} />}
    </div>
  );
}

