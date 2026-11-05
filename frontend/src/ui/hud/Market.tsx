// Phase 7: the Market (sell to the NPC market with live prices, sparklines, trends and your daily
// soft cap) and the wandering merchant's cart (peek from home, buy when you're standing at it).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { InventoryView, MarketItem, MarketView, MerchantSlot, SaleResult, VillageState } from "../../api/types";
import { enterAvatar } from "../../net/room";
import { sfx } from "../../game/sfx";
import { useMarket } from "../../state/market";
import { serverNow, useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { useVillage } from "../../state/village";
import { formatDuration, Icon, Modal } from "../components/kit";

const fmt = (n: number) => (n >= 100 ? Math.round(n).toLocaleString() : n >= 10 ? n.toFixed(1) : n.toFixed(2));

/** What a sale pays, using the server's formula (rounds down once for the whole sale). */
export function payoutPreview(it: MarketItem, qty: number): { coins: number; over: number } {
  const full = Math.max(0, Math.min(qty, it.soft_cap - it.sold_today));
  const over = qty - full;
  const mult = it.price > 0 ? it.over_price / it.price : 0.5;
  return { coins: Math.floor(it.price * full + it.price * mult * over + 1e-9), over };
}

// ── sparkline ────────────────────────────────────────────────────────────────

/** A muted 2px line with the live price as an accent dot. `interactive` adds a hover readout. */
export function Sparkline({ values, trend, w = 84, h = 24, interactive = false, label }: {
  values: number[];
  trend: number;
  w?: number;
  h?: number;
  interactive?: boolean;
  label: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);
  const pts = values.length > 1 ? values : [values[0] ?? 0, values[0] ?? 0];
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const pad = 3;
  const span = hi - lo || hi * 0.1 || 1;
  const xy = pts.map((v, i) => [pad + (i / (pts.length - 1)) * (w - pad * 2), pad + (1 - (v - lo) / span) * (h - pad * 2)] as const);
  const d = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const area = `${d}L${xy[xy.length - 1][0].toFixed(1)},${h}L${xy[0][0].toFixed(1)},${h}Z`;
  const accent = trend > 0 ? "var(--leaf)" : trend < 0 ? "var(--red)" : "var(--ink)";
  const last = xy[xy.length - 1];
  const onMove = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const f = (e.clientX - r.left) / r.width;
    setHover(Math.max(0, Math.min(pts.length - 1, Math.round(f * (pts.length - 1)))));
  };
  const hoursAgo = hover === null ? 0 : Math.round(((pts.length - 1 - hover) / (pts.length - 1)) * 24);
  return (
    <span className="spark" style={{ width: w, height: h }}>
      <svg ref={ref} width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label}
        onPointerMove={interactive ? onMove : undefined} onPointerLeave={interactive ? () => setHover(null) : undefined}>
        <path d={area} fill="var(--ink)" opacity={0.07} />
        <path d={d} fill="none" stroke="var(--ink-soft)" strokeWidth={interactive ? 2 : 1.5} strokeLinejoin="round" strokeLinecap="round" opacity={0.75} />
        <circle cx={last[0]} cy={last[1]} r={interactive ? 3.5 : 2.5} fill={accent} stroke="var(--paper-light)" strokeWidth={1.5} />
        {hover !== null && (
          <>
            <line x1={xy[hover][0]} x2={xy[hover][0]} y1={0} y2={h} stroke="var(--ink)" strokeWidth={1} opacity={0.35} />
            <circle cx={xy[hover][0]} cy={xy[hover][1]} r={3} fill="var(--gold)" stroke="var(--ink)" strokeWidth={1} />
          </>
        )}
      </svg>
      {hover !== null && (
        <span className="spark-tip small" style={{ left: Math.min(w - 60, Math.max(0, xy[hover][0] - 30)) }}>
          {hoursAgo ? `${hoursAgo}h ago` : "now"} · <b>{fmt(pts[hover])}</b>
        </span>
      )}
    </span>
  );
}

function Trend({ it }: { it: MarketItem }) {
  if (it.trend === 0) return <span className="small muted trend">— steady</span>;
  const pct = `${Math.abs(it.change * 100).toFixed(0)}%`;
  return (
    <span className={`small trend ${it.trend > 0 ? "up" : "down"}`} title="Change over the last hour">
      <Icon name={it.trend > 0 ? "trend_up" : "trend_down"} scale={1} /> {it.trend > 0 ? "up" : "down"} {pct}
    </span>
  );
}

// ── the sell box ─────────────────────────────────────────────────────────────

function SellBox({ it, market, onSold }: { it: MarketItem; market: MarketView; onSold: (r: SaleResult) => void }) {
  const [qty, setQty] = useState(() => Math.min(it.have, 10));
  const [busy, setBusy] = useState(false);
  useEffect(() => setQty((q) => Math.max(0, Math.min(q || Math.min(it.have, 10), it.have, market.max_sell))), [it.key, it.have, market.max_sell]);
  const max = Math.min(it.have, market.max_sell);
  const preview = payoutPreview(it, qty);
  const capLeft = Math.max(0, it.soft_cap - it.sold_today);
  const usage = Math.min(1, it.sold_today / it.soft_cap);
  const sell = async () => {
    setBusy(true);
    try {
      const r = await api<{ village: VillageState; sale: SaleResult; inventory?: InventoryView }>("/api/market/sell", {
        method: "POST",
        body: { item: it.key, quantity: qty },
      });
      useVillage.getState().apply(r.village);
      sfx("coin");
      window.setTimeout(() => sfx("deposit"), 90);
      onSold(r.sale);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "The market's closed for a moment.", "bad");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="slot sell-box col">
      <div className="row" style={{ gap: 10, alignItems: "flex-start" }}>
        <Icon name={it.icon.replace(/^icon\./, "")} scale={3} />
        <div className="col grow" style={{ gap: 2, minWidth: 0 }}>
          <span className="head" style={{ fontSize: 19 }}>{it.name}</span>
          <span className="small">
            <b>{fmt(it.price)}</b> <Icon name="coins" scale={1} /> each · <Trend it={it} />
          </span>
          <span className="small muted">
            {it.units_24h.toLocaleString()} sold realm-wide today · normal is ~{Math.round(it.baseline).toLocaleString()}
          </span>
        </div>
      </div>
      <Sparkline values={it.spark} trend={it.trend} w={300} h={54} interactive label={`${it.name} price over the last 24 hours`} />
      <div className="col" style={{ gap: 2 }}>
        <span className="small">
          Your daily limit: {it.sold_today.toLocaleString()} / {it.soft_cap.toLocaleString()}
          {capLeft === 0 && <b style={{ color: "var(--red)" }}> · past it, you get half price until tomorrow</b>}
        </span>
        <span className="meter" role="meter" aria-valuenow={it.sold_today} aria-valuemax={it.soft_cap} aria-label="Sold today">
          <span style={{ width: `${usage * 100}%`, background: usage >= 1 ? "var(--red)" : "var(--gold)" }} />
        </span>
      </div>
      <div className="row qty-row" style={{ gap: 6, flexWrap: "wrap" }}>
        {[1, 10, 100].filter((n) => n < max).map((n) => (
          <button key={n} className={`btn small ${qty === n ? "" : "secondary"}`} onClick={() => setQty(n)}>{n}</button>
        ))}
        {capLeft > 0 && capLeft < max && (
          <button className={`btn small ${qty === capLeft ? "" : "secondary"}`} onClick={() => setQty(capLeft)} title="Up to your daily limit">
            To limit ({capLeft})
          </button>
        )}
        <button className={`btn small ${qty === max ? "" : "secondary"}`} onClick={() => setQty(max)} disabled={max <= 0}>All ({max})</button>
        <input className="qty-input" type="number" min={1} max={max} value={qty} aria-label="Quantity"
          onChange={(e) => setQty(Math.max(0, Math.min(max, Math.floor(Number(e.target.value) || 0))))} />
      </div>
      <button className="btn gold" disabled={busy || qty <= 0 || !market.has_market || preview.coins < 1} onClick={sell}>
        <Icon name="coins" /> Sell {qty.toLocaleString()} for {preview.coins.toLocaleString()} coins
        {preview.over > 0 && <span className="small"> ({preview.over} at half price)</span>}
      </button>
    </div>
  );
}

// ── the market panel ─────────────────────────────────────────────────────────

function MarketRow({ it, active, onClick }: { it: MarketItem; active: boolean; onClick: () => void }) {
  return (
    <button className={`slot market-row ${active ? "picked" : ""} ${it.have ? "" : "empty"}`} onClick={onClick}>
      <Icon name={it.icon.replace(/^icon\./, "")} scale={2} />
      <span className="col market-name" style={{ gap: 0 }}>
        <span className="head">{it.name}</span>
        <span className="small muted">have {it.have.toLocaleString()}</span>
      </span>
      <Sparkline values={it.spark} trend={it.trend} label={`${it.name}: ${fmt(it.spark[0])} → ${fmt(it.price)} over 24 hours`} />
      <span className="col market-price" style={{ gap: 0 }}>
        <span className="head">{fmt(it.price)} <Icon name="coins" scale={1} /></span>
        <Trend it={it} />
      </span>
    </button>
  );
}

export function MarketPanel({ onClose }: { onClose: () => void }) {
  const [market, setMarket] = useState<MarketView | null>(null);
  const [tab, setTab] = useState<"sell" | "merchant">("sell");
  const [picked, setPicked] = useState<string | null>(null);
  const [filter, setFilter] = useState<"mine" | "all">("mine");
  const load = useCallback(async () => {
    try {
      setMarket(await api<MarketView>("/api/market"));
    } catch {
      toast("Couldn't reach the market.", "bad");
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  // reload when the worker reprices (every 10 min)
  useEffect(() => {
    if (!market) return;
    const wait = Math.max(3000, market.next_recalc_ms - serverNow() + 4000);
    const id = window.setTimeout(() => void load(), wait);
    return () => window.clearTimeout(id);
  }, [market, load]);
  const items = useMemo(() => {
    const all = market?.items ?? [];
    return filter === "mine" ? all.filter((i) => i.have > 0) : all;
  }, [market, filter]);
  useEffect(() => {
    if (!market) return;
    if (!picked || !items.some((i) => i.key === picked)) setPicked(items[0]?.key ?? null);
  }, [items, picked, market]);
  const sel = items.find((i) => i.key === picked) ?? null;
  const onSold = (r: SaleResult) => {
    toast(`Sold ${r.sold.toLocaleString()} for ${r.coins.toLocaleString()} coins!`, "good", "coins");
    void load();
  };
  const nextIn = market ? Math.max(0, (market.next_recalc_ms - serverNow()) / 1000) : 0;
  return (
    <Modal title="Market" onClose={onClose} wide>
      <div className="row tabs" role="tablist" style={{ gap: 6, marginBottom: 8 }}>
        <button role="tab" aria-selected={tab === "sell"} className={`btn small ${tab === "sell" ? "" : "secondary"}`} onClick={() => setTab("sell")}>
          <Icon name="market" scale={1.5} /> Sell
        </button>
        <button role="tab" aria-selected={tab === "merchant"} className={`btn small ${tab === "merchant" ? "" : "secondary"}`} onClick={() => setTab("merchant")}>
          <Icon name="cart" scale={1.5} /> Wandering merchant
        </button>
      </div>
      {tab === "merchant" ? (
        <MerchantStock mode="peek" />
      ) : !market ? (
        <p>Counting coins…</p>
      ) : (
        <div className="col" style={{ gap: 8 }}>
          <div className="row market-head small" style={{ gap: 10, flexWrap: "wrap" }}>
            {market.has_market ? (
              <span>Market <b>level {market.market_level}</b>{market.bonus > 0 ? ` · +${Math.round(market.bonus * 100)}% on every sale` : ""}</span>
            ) : (
              <span style={{ color: "var(--red)" }}><b>Build a Market</b> in your village to sell. Prices are shown so you can plan.</span>
            )}
            <span className="muted">Prices move with what everyone sells · update in {formatDuration(nextIn)}</span>
            <span className="grow" />
            <span className="row" style={{ gap: 4 }}>
              <button className={`btn small ${filter === "mine" ? "" : "secondary"}`} onClick={() => setFilter("mine")}>I have</button>
              <button className={`btn small ${filter === "all" ? "" : "secondary"}`} onClick={() => setFilter("all")}>All</button>
            </span>
          </div>
          <div className="market-body">
            <div className="market-list col">
              {items.length === 0 && <p className="small muted">Nothing to sell yet. Gather, craft or fight, then come back!</p>}
              {items.map((it) => <MarketRow key={it.key} it={it} active={it.key === picked} onClick={() => setPicked(it.key)} />)}
            </div>
            {sel && <SellBox it={sel} market={market} onSold={onSold} />}
          </div>
        </div>
      )}
    </Modal>
  );
}

// ── the wandering merchant ───────────────────────────────────────────────────

function StockCard({ s, canBuy, busy, onBuy }: { s: MerchantSlot; canBuy: boolean; busy: boolean; onBuy: () => void }) {
  const left = s.limit - s.bought;
  return (
    <div className={`slot stock-card col ${s.sold_out ? "sold" : ""} ${s.deal ? "deal" : ""}`}>
      {s.deal && <span className="deal-tag small head">Deal!</span>}
      <Icon name={s.icon.replace(/^icon\./, "")} scale={3} />
      <span className="head" style={{ fontSize: 16 }}>{s.name}</span>
      {s.blurb && <span className="small muted">{s.blurb}</span>}
      {s.kind === "resource" && <span className="small muted">into your storehouse</span>}
      <span className="small">
        {s.deal && <s className="muted">{s.list_price}</s>} <b>{s.price.toLocaleString()}</b> <Icon name="coins" scale={1} />
      </span>
      <span className="small muted">{s.sold_out ? (s.kind === "hint" && s.bought === 0 ? "Nothing left to hint" : "Sold out for you") : `${left} left for you`}</span>
      {canBuy && (
        <button className="btn small gold" disabled={busy || s.sold_out} onClick={onBuy}>Buy</button>
      )}
    </div>
  );
}

export function MerchantStock({ mode }: { mode: "peek" | "buy" }) {
  const merchant = useMarket((s) => s.merchant);
  const fetchMerchant = useMarket((s) => s.fetchMerchant);
  const near = useMarket((s) => s.near);
  const coins = useVillage((s) => s.village?.coins ?? 0);
  const config = useSession((s) => s.config)!;
  const [busy, setBusy] = useState(false);
  const [, force] = useState(0);
  useEffect(() => {
    void fetchMerchant();
    const id = window.setInterval(() => force((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [fetchMerchant]);
  useEffect(() => {
    if (merchant && merchant.ends_at_ms <= serverNow()) void fetchMerchant();
  });
  if (!merchant) return <p>Looking for her cart…</p>;
  const ends = Math.max(0, (merchant.ends_at_ms - serverNow()) / 1000);
  const buy = async (s: MerchantSlot) => {
    setBusy(true);
    try {
      const r = await api<{ village: VillageState; purchase: { got: Record<string, unknown> } }>(`/api/merchant/hub/buy`, {
        method: "POST",
        body: { slot: s.slot, rotation: merchant.rotation },
      });
      useVillage.getState().apply(r.village);
      sfx("coin");
      const got = r.purchase.got;
      if (Array.isArray(got.hint)) {
        sfx("reveal");
        const names = (got.hint as string[]).map((b) => config.buildings[b]?.name ?? b).join(" + ");
        toast(`The page reads: “${names}”. Check your Recipe Book!`, "good", "scroll");
      } else toast(`Bought ${s.name}!`, "good", "cart");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "She shrugs. Try again?", "bad");
    } finally {
      setBusy(false);
      await useMarket.getState().fetchMerchant();
    }
  };
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="row merchant-head" style={{ gap: 10, alignItems: "flex-start" }}>
        <Icon name="cart" scale={3} />
        <div className="col grow" style={{ gap: 2 }}>
          <span className="head" style={{ fontSize: 19 }}>{merchant.name}</span>
          <span className="small" style={{ fontStyle: "italic" }}>“{merchant.greeting}”</span>
          <span className="small muted">Packs up and moves on in {formatDuration(ends)} · you have {coins.toLocaleString()} <Icon name="coins" scale={1} /></span>
        </div>
      </div>
      {mode === "peek" && (
        <div className="slot small row" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className="grow">Her cart is parked in the <b>hub</b>, the cobbled square at the middle of the realm. Walk over to trade.</span>
          <button className="btn small gold" onClick={() => {
            useMarket.getState().set({ marketOpen: false });
            void enterAvatar();
          }}><Icon name="avatar" scale={1.5} /> Head out</button>
        </div>
      )}
      <div className="stock-grid">
        {merchant.slots.map((s) => (
          <StockCard key={s.slot} s={s} canBuy={mode === "buy" && near} busy={busy} onBuy={() => void buy(s)} />
        ))}
      </div>
    </div>
  );
}

export function MerchantPanel({ onClose }: { onClose: () => void }) {
  return (
    <Modal title="Wandering merchant" onClose={onClose} wide>
      <MerchantStock mode="buy" />
    </Modal>
  );
}

/** The "E · Trade" button that appears in Avatar Mode while you stand at her cart. */
export function TradePrompt({ touch }: { touch: boolean }) {
  const near = useMarket((s) => s.near);
  const open = useMarket((s) => s.merchantOpen);
  const merchant = useMarket((s) => s.merchant);
  if (!near || open) return null;
  return (
    <button className="btn gold trade-prompt" onClick={() => useMarket.getState().set({ merchantOpen: true })}>
      <Icon name="cart" /> {touch ? "Trade" : <><span className="av-key">E</span> Trade with {merchant?.name.split(" ")[0] ?? "her"}</>}
    </button>
  );
}
