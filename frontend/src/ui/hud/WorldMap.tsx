// Phase 9: the mini-map (corner) and the full map (modal). One coloured pixel-block per chunk, fog over
// what you haven't seen, plots with their owners, waystones, the merchant, you and your party.
// At a waystone the full map opens in travel mode: tap an attuned stone to go there.
import { useDefence } from "../../state/defence";
import { useEffect, useRef } from "react";
import { roomLink } from "../../net/room";
import { useAvatar } from "../../state/avatar";
import { useMarket } from "../../state/market";
import { isRevealed, useRealm, type Overview } from "../../state/realm";
import { useVillage } from "../../state/village";
import { Icon, Modal } from "../components/kit";

const COLORS = ["#3b80ba", "#5fa447", "#2f6a3d", "#bf8d58", "#a2a8b6", "#82c055"]; // water grass forest path hub plot
const FOG = "rgba(43,30,42,0.86)";

interface DrawOpts {
  px: number; // pixels per chunk
  me: { x: number; y: number } | null; // tiles
  showLabels: boolean;
  travel: boolean;
  hover?: number | null;
}

function draw(ctx: CanvasRenderingContext2D, o: Overview, opts: DrawOpts): { x: number; y: number; index: number }[] {
  const { px } = opts;
  const n = o.n;
  const tile = px / o.chunk_size; // pixels per tile
  ctx.clearRect(0, 0, n * px, n * px);
  for (let cy = 0; cy < n; cy++) {
    for (let cx = 0; cx < n; cx++) {
      ctx.fillStyle = COLORS[o.data[cy * n + cx]] ?? COLORS[1];
      ctx.fillRect(cx * px, cy * px, px, px);
    }
  }
  const map = useVillage.getState().map;
  // fog, except over the hub and claimed plots (you always know where your realm-mates live)
  for (let cy = 0; cy < n; cy++) {
    for (let cx = 0; cx < n; cx++) {
      if (isRevealed(o, cx, cy)) continue;
      const tx = cx * o.chunk_size + o.chunk_size / 2;
      const ty = cy * o.chunk_size + o.chunk_size / 2;
      const inPlot = map?.plots.some((p) => p.owner && tx >= p.origin[0] && tx < p.origin[0] + 48 && ty >= p.origin[1] && ty < p.origin[1] + 48);
      const hub = map ? Math.hypot(tx - map.hub.center, ty - map.hub.center) < map.hub.radius + 4 : false;
      if (inPlot || hub) continue;
      ctx.fillStyle = FOG;
      ctx.fillRect(cx * px, cy * px, px, px);
    }
  }
  // plots
  for (const p of map?.plots ?? []) {
    if (!p.owner) continue;
    const mine = p.index === map?.my_plot;
    ctx.strokeStyle = mine ? "#f7d66a" : "#faf2dd";
    ctx.lineWidth = mine ? 2 : 1;
    ctx.strokeRect(p.origin[0] * tile + 0.5, p.origin[1] * tile + 0.5, 48 * tile - 1, 48 * tile - 1);
    if (opts.showLabels) {
      ctx.font = `600 ${Math.max(10, px * 1.4)}px "Pixelify Sans", sans-serif`;
      ctx.textAlign = "center";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "#2b1e2a";
      ctx.fillStyle = mine ? "#f7d66a" : "#faf2dd";
      const lx = (p.origin[0] + 24) * tile;
      const ly = (p.origin[1] + 24) * tile;
      ctx.strokeText(p.owner, lx, ly);
      ctx.fillText(p.owner, lx, ly);
    }
  }
  // waystones
  const hits: { x: number; y: number; index: number }[] = [];
  for (const w of o.waystones) {
    const cx = Math.floor(w.x / o.chunk_size);
    const cy = Math.floor(w.y / o.chunk_size);
    const attuned = o.attuned.includes(w.index);
    if (!attuned && !isRevealed(o, cx, cy)) continue;
    const x = w.x * tile;
    const y = w.y * tile;
    const r = Math.max(3, px * (opts.hover === w.index ? 1.1 : 0.75));
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r, y);
    ctx.lineTo(x, y + r);
    ctx.lineTo(x - r, y);
    ctx.closePath();
    ctx.fillStyle = attuned ? "#94cdeb" : "#7a8092";
    ctx.fill();
    ctx.lineWidth = opts.travel && attuned ? 2 : 1;
    ctx.strokeStyle = opts.travel && attuned ? "#f7d66a" : "#2b1e2a";
    ctx.stroke();
    hits.push({ x, y, index: w.index });
    if (opts.showLabels && (attuned || opts.hover === w.index)) {
      ctx.font = `600 ${Math.max(10, px * 1.2)}px "Pixelify Sans", sans-serif`;
      ctx.textAlign = "center";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "#2b1e2a";
      ctx.fillStyle = "#d5f0fa";
      ctx.strokeText(w.name, x, y - r - 3);
      ctx.fillText(w.name, x, y - r - 3);
    }
  }
  // points of interest you've seen (Phase 10)
  const POI_COLORS: Record<string, string> = {
    ruins: "#c58a52", shrine: "#94cdeb", lore_stone: "#a6cfe6", cave: "#585c6e", merchant: "#e0ad3c", lost_villager: "#f2bb97",
  };
  for (const q of o.pois ?? []) {
    if (!isRevealed(o, Math.floor(q.x / o.chunk_size), Math.floor(q.y / o.chunk_size))) continue;
    if (q.used && q.kind === "lost_villager") continue;
    const x = q.x * tile;
    const y = q.y * tile;
    const r = Math.max(2, px * 0.45);
    ctx.fillStyle = q.used && q.kind === "ruins" ? "#7a8092" : POI_COLORS[q.kind] ?? "#faf2dd";
    ctx.strokeStyle = "#2b1e2a";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  // the merchant
  const m = useMarket.getState().merchant;
  if (m && isRevealed(o, Math.floor(m.pos[0] / o.chunk_size), Math.floor(m.pos[1] / o.chunk_size))) {
    ctx.fillStyle = "#e0ad3c";
    ctx.strokeStyle = "#2b1e2a";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(m.pos[0] * tile, m.pos[1] * tile, Math.max(2.5, px * 0.6), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  // an awake realm boss (Phase 13): a red diamond, shown even through the fog (the whole realm hears it)
  const def = useDefence.getState();
  const bosses = def.bosses.length
    ? def.bosses
    : def.boss && def.boss.status === "waiting" && def.boss.spawns_at_ms <= Date.now() ? [def.boss] : [];
  for (const b of bosses) {
    const x = b.x * tile;
    const y = b.y * tile;
    const r = Math.max(4, px * 1.1);
    ctx.fillStyle = "#e2735a";
    ctx.strokeStyle = "#2b1e2a";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r, y);
    ctx.lineTo(x, y + r);
    ctx.lineTo(x - r, y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#faf2dd";
    ctx.fillRect(x - 1, y - 1, 2, 2);
  }
  // party
  const party = useRealm.getState().party;
  const myEid = roomLink.client?.eid;
  for (const pm of party?.members ?? []) {
    if (pm.x === null || pm.y === null || pm.eid === myEid) continue;
    ctx.fillStyle = "#8fc95c";
    ctx.strokeStyle = "#2b1e2a";
    ctx.beginPath();
    ctx.arc(pm.x * tile, pm.y * tile, Math.max(2.5, px * 0.6), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  // you
  if (opts.me) {
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#2b1e2a";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(opts.me.x * tile, opts.me.y * tile, Math.max(3, px * 0.8), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  return hits;
}

function myPosition(): { x: number; y: number } | null {
  const c = roomLink.client;
  if (c) return c.drawPos();
  const v = useVillage.getState().village;
  if (!v) return null;
  return { x: v.origin[0] + v.frame / 2, y: v.origin[1] + v.frame / 2 };
}

/** The corner map is a local window around you (the whole realm is the full map's job). */
export function MiniMap({ small }: { small: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const overview = useRealm((s) => s.overview);
  const px = small ? 5 : 7; // pixels per chunk
  const size = small ? 104 : 148;
  useEffect(() => {
    if (!overview) return;
    const off = document.createElement("canvas");
    off.width = off.height = overview.n * px;
    const tick = () => {
      const ctx = ref.current?.getContext("2d");
      const o = useRealm.getState().overview;
      const oc = off.getContext("2d");
      if (!ctx || !o || !oc) return;
      const me = myPosition();
      draw(oc, o, { px, me, showLabels: false, travel: false });
      const tile = px / o.chunk_size;
      const sx = Math.max(0, Math.min(off.width - size, (me?.x ?? o.n * o.chunk_size / 2) * tile - size / 2));
      const sy = Math.max(0, Math.min(off.height - size, (me?.y ?? o.n * o.chunk_size / 2) * tile - size / 2));
      ctx.clearRect(0, 0, size, size);
      ctx.drawImage(off, sx, sy, size, size, 0, 0, size, size);
    };
    tick();
    const id = window.setInterval(tick, 300);
    return () => window.clearInterval(id);
  }, [overview, px, size]);
  if (!overview) return null;
  return (
    <button className="minimap" onClick={() => useRealm.getState().set({ mapOpen: true, travelMode: false })} aria-label="Open the map (M)" title="Map (M)">
      <canvas ref={ref} width={size} height={size} style={{ width: size, height: size }} />
    </button>
  );
}

export function MapModal() {
  const open = useRealm((s) => s.mapOpen);
  const travel = useRealm((s) => s.travelMode);
  const overview = useRealm((s) => s.overview);
  const ref = useRef<HTMLCanvasElement>(null);
  const hits = useRef<{ x: number; y: number; index: number }[]>([]);
  const hover = useRef<number | null>(null);
  const px = typeof window !== "undefined" && window.innerWidth < 520 ? 7 : 9;
  useEffect(() => {
    if (!open || !overview) return;
    const tick = () => {
      const ctx = ref.current?.getContext("2d");
      const o = useRealm.getState().overview;
      if (ctx && o) hits.current = draw(ctx, o, { px, me: myPosition(), showLabels: true, travel, hover: hover.current });
    };
    tick();
    const id = window.setInterval(tick, 250);
    return () => window.clearInterval(id);
  }, [open, overview, travel, px]);
  if (!open || !overview) return null;
  const close = () => useRealm.getState().set({ mapOpen: false, travelMode: false });
  const go = (index: number) => {
    roomLink.send?.("TRAVEL", index);
  };
  const pick = (e: React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * ref.current!.width;
    const y = ((e.clientY - r.top) / r.height) * ref.current!.height;
    let best: { index: number; d: number } | null = null;
    for (const h of hits.current) {
      const d = Math.hypot(h.x - x, h.y - y);
      if (d < px * 2.2 && (!best || d < best.d)) best = { index: h.index, d };
    }
    return best?.index ?? null;
  };
  const size = overview.n * px;
  const near = useRealm.getState().nearWaystone;
  return (
    <Modal title={travel ? "Waystone: where to?" : "Map"} onClose={close} wide>
      <div className="map-body">
        <canvas ref={ref} width={size} height={size} className="full-map" style={{ width: size, height: size, maxWidth: "100%" }}
          onMouseMove={(e) => (hover.current = pick(e))}
          onClick={(e) => {
            const i = pick(e);
            if (i !== null && travel && overview.attuned.includes(i) && i !== near) go(i);
          }} />
        <div className="col map-side" style={{ gap: 6 }}>
          <span className="small muted">
            {travel ? "Tap an attuned stone (blue) to travel there." : "Walk up to a waystone to attune it. Then travel between attuned stones for free."}
          </span>
          <div className="col" style={{ gap: 3 }}>
            {overview.waystones.filter((w) => overview.attuned.includes(w.index)).map((w) => {
              const attuned = true;
              return (
                <div key={w.index} className="row small" style={{ gap: 6 }}>
                  <span className={`way-dot ${attuned ? "on" : ""}`} />
                  <span className="grow">{attuned ? w.name : "???"}</span>
                  {travel && attuned && w.index !== near && (
                    <button className="btn small gold" onClick={() => go(w.index)}>Go</button>
                  )}
                  {w.index === near && <span className="muted">you're here</span>}
                </div>
              );
            })}
            {overview.waystones.length > overview.attuned.length && (
              <div className="row small muted" style={{ gap: 6 }}>
                <span className="way-dot" /> {overview.waystones.length - overview.attuned.length} more waystones to find
              </div>
            )}
          </div>
          <div className="map-legend small col" style={{ gap: 2 }}>
            <span><span className="leg" style={{ background: "#ffffff" }} /> you</span>
            <span><span className="leg" style={{ background: "#8fc95c" }} /> party</span>
            <span><span className="leg" style={{ background: "#e0ad3c" }} /> wandering merchant</span>
            <span><span className="leg diamond" /> waystone</span>
            <span><span className="leg round" style={{ background: "#c58a52" }} /> ruins · <span className="leg round" style={{ background: "#94cdeb" }} /> shrine</span>
            <span><span className="leg round" style={{ background: "#a6cfe6" }} /> lore stone · <span className="leg round" style={{ background: "#585c6e" }} /> cave</span>
            <span><span className="leg round" style={{ background: "#f2bb97" }} /> lost villager</span>
          </div>
        </div>
      </div>
    </Modal>
  );
}

/** "Waystone · Travel" while standing at one (Avatar Mode). */
export function WaystonePrompt({ touch }: { touch: boolean }) {
  const near = useRealm((s) => s.nearWaystone);
  const open = useRealm((s) => s.mapOpen);
  const trade = useMarket((s) => s.near);
  const mode = useAvatar((s) => s.mode);
  if (near === null || open || trade || mode !== "avatar") return null;
  return (
    <button className="btn gold trade-prompt" onClick={() => useRealm.getState().set({ mapOpen: true, travelMode: true })}>
      <Icon name="map" /> {touch ? "Travel" : <><span className="av-key">E</span> Waystone: travel</>}
    </button>
  );
}
