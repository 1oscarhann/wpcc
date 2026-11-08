// Phase 17: the Plaza. The player market (buy, sell, your listings), global leaderboards, the world boss
// weekend and the festival shop. Also the HUD button and the little festival / world boss chips.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import { itemIcon, itemName } from "../../game/items";
import { sfx } from "../../game/sfx";
import { enterAvatar } from "../../net/room";
import { useAvatar } from "../../state/avatar";
import { usePlaza, type PlazaTab } from "../../state/plaza";
import { serverNow, useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { useVillage } from "../../state/village";
import { formatDuration, Icon, Modal } from "../components/kit";
import { SpriteThumb } from "../components/SpriteThumb";
import { Sparkline } from "./Market";
import { TitleTag } from "./Social";

async function post<T>(path: string, body?: unknown): Promise<T | null> {
  try {
    return await api<T>(path, { method: "POST", body });
  } catch (e) {
    toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
    return null;
  }
}

const n = (v: number) => v.toLocaleString();
const left = (ms: number) => formatDuration(Math.max(0, (ms - serverNow()) / 1000));

// ── the player market ────────────────────────────────────────────────────────

interface Summary { item: string; name: string; category: string; lowest: number; quantity: number; listings: number; last: number | null; reference: number }
interface ListingRow { id: string; item: string; quantity: number; listed: number; unit_price: number; seller: string; mine: boolean; status: string; expires_ms: number }
interface Sellable { item: string; name: string; have: number; reference: number; band: [number, number]; lowest: number | null }
interface MarketView { items: Summary[]; listings: ListingRow[]; sellable: Sellable[]; fee: number; max_listings: number; hours: number; gate_ok: boolean }
interface ItemView { item: string; name: string; reference: number; band: [number, number]; listings: ListingRow[]; history: { day: string; avg: number; volume: number }[]; recent: { qty: number; price: number; at_ms: number }[] }

function BuyRow({ ls, onDone }: { ls: ListingRow; onDone: () => void }) {
  const [qty, setQty] = useState(Math.min(ls.quantity, 10));
  const [busy, setBusy] = useState(false);
  const coins = useVillage((s) => s.village?.coins ?? 0);
  const buy = async () => {
    setBusy(true);
    const r = await post<{ cost: number; fee: number; mailed: Record<string, number> }>(`/api/pmarket/listings/${ls.id}/buy`, { quantity: qty });
    setBusy(false);
    if (!r) return;
    sfx("coin");
    toast(`Bought ${qty} ${itemName(ls.item)} for ${n(r.cost)} coins${Object.keys(r.mailed).length ? " (some went to your mail)" : ""}.`, "good", "market");
    void useVillage.getState().fetch().catch(() => undefined);
    onDone();
  };
  return (
    <div className={`slot row listing-row ${ls.mine ? "mine" : ""}`} style={{ gap: 8 }}>
      <span className="col grow" style={{ gap: 0 }}>
        <span className="head">{n(ls.unit_price)} <Icon name="coins" scale={1} /> <span className="small muted">each</span></span>
        <span className="small muted">{n(ls.quantity)} from {ls.seller} · {left(ls.expires_ms)} left</span>
      </span>
      {ls.mine ? <span className="tag">yours</span> : (
        <>
          <input className="qty-input" type="number" min={1} max={ls.quantity} value={qty} aria-label="How many"
            onChange={(e) => setQty(Math.max(1, Math.min(ls.quantity, Math.floor(Number(e.target.value) || 1))))} />
          <button className="btn small gold" disabled={busy || coins < qty * ls.unit_price} onClick={buy}>
            Buy for {n(qty * ls.unit_price)}
          </button>
        </>
      )}
    </div>
  );
}

function ItemDetail({ item, onChange }: { item: string; onChange: () => void }) {
  const [v, setV] = useState<ItemView | null>(null);
  const load = useCallback(async () => {
    setV(await api<ItemView>(`/api/pmarket/item/${item}`).catch(() => null));
  }, [item]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!v) return <div className="slot pm-detail"><p>Looking at the stalls…</p></div>;
  const spark = v.history.map((h) => h.avg);
  return (
    <div className="slot pm-detail col" style={{ gap: 6 }}>
      <div className="row" style={{ gap: 8 }}>
        <Icon name={itemIcon(v.item)} scale={3} />
        <span className="col grow" style={{ gap: 0 }}>
          <span className="head" style={{ fontSize: 19 }}>{v.name}</span>
          <span className="small muted">worth about {n(v.reference)} · players can ask {n(v.band[0])}–{n(v.band[1])}</span>
        </span>
      </div>
      {spark.length > 1 && <Sparkline values={spark} trend={Math.sign(spark[spark.length - 1] - spark[0])} w={300} h={44} interactive label={`${v.name}: player-market prices, last ${spark.length} days`} />}
      {v.listings.length === 0 && <span className="small muted">Nobody's selling this right now.</span>}
      <div className="col" style={{ gap: 3 }}>
        {v.listings.map((ls) => <BuyRow key={ls.id} ls={ls} onDone={() => { void load(); onChange(); }} />)}
      </div>
      {v.recent.length > 0 && (
        <span className="small muted">Recent sales: {v.recent.slice(0, 6).map((t) => `${t.qty}×${t.price}`).join(" · ")}</span>
      )}
    </div>
  );
}

function SellForm({ s, view, onDone }: { s: Sellable; view: MarketView; onDone: () => void }) {
  const [qty, setQty] = useState(Math.min(s.have, 10));
  const [price, setPrice] = useState(() => Math.max(s.band[0], Math.min(s.band[1], s.lowest ?? s.reference)));
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setQty(Math.min(s.have, 10));
    setPrice(Math.max(s.band[0], Math.min(s.band[1], s.lowest ?? s.reference)));
  }, [s.item, s.have, s.band, s.lowest, s.reference]);
  const gross = qty * price;
  const fee = Math.max(1, Math.floor(gross * view.fee));
  const list = async () => {
    setBusy(true);
    const r = await post<{ listing: string }>("/api/pmarket/listings", { item: s.item, quantity: qty, unit_price: price });
    setBusy(false);
    if (!r) return;
    sfx("deposit");
    toast(`Listed ${qty} ${s.name} at ${n(price)} each.`, "good", "market");
    onDone();
  };
  return (
    <div className="slot col pm-sell" style={{ gap: 6 }}>
      <div className="row" style={{ gap: 8 }}>
        <Icon name={itemIcon(s.item)} scale={3} />
        <span className="col grow" style={{ gap: 0 }}>
          <span className="head" style={{ fontSize: 19 }}>{s.name}</span>
          <span className="small muted">you have {n(s.have)} · worth about {n(s.reference)}{s.lowest ? ` · cheapest listing ${n(s.lowest)}` : ""}</span>
        </span>
      </div>
      <label className="row small" style={{ gap: 6 }}>How many
        <input className="qty-input" type="number" min={1} max={s.have} value={qty} onChange={(e) => setQty(Math.max(1, Math.min(s.have, Math.floor(Number(e.target.value) || 1))))} />
      </label>
      <label className="row small" style={{ gap: 6 }}>Price each
        <input className="qty-input" type="number" min={s.band[0]} max={s.band[1]} value={price} onChange={(e) => setPrice(Math.floor(Number(e.target.value) || 0))} />
        <span className="muted">({n(s.band[0])}–{n(s.band[1])})</span>
      </label>
      <span className="small">Buyers pay <b>{n(gross)}</b>; you get <b>{n(gross - fee)}</b> after the {Math.round(view.fee * 100)}% fee. Unsold goods come back by mail after {view.hours} h.</span>
      <button className="btn gold" disabled={busy || !view.gate_ok || price < s.band[0] || price > s.band[1]} onClick={list}>
        <Icon name="market" /> List {n(qty)} for {n(price)} each
      </button>
      {!view.gate_ok && <span className="small" style={{ color: "var(--red)" }}>New accounts can list once they reach level 5 or are a day old.</span>}
    </div>
  );
}

function MarketTab() {
  const [view, setView] = useState<MarketView | null>(null);
  const [mode, setMode] = useState<"buy" | "sell" | "mine">("buy");
  const [pick, setPick] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const load = useCallback(async () => {
    setView(await api<MarketView>("/api/pmarket").catch(() => null));
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const items = useMemo(() => (view?.items ?? []).filter((i) => i.name.toLowerCase().includes(q.toLowerCase())), [view, q]);
  useEffect(() => {
    if (!view) return;
    if (mode === "buy" && (!pick || !items.some((i) => i.item === pick))) setPick(items[0]?.item ?? null);
    if (mode === "sell" && (!pick || !view.sellable.some((s) => s.item === pick))) setPick(view.sellable[0]?.item ?? null);
  }, [mode, view, items, pick]);
  if (!view) return <p>Setting up the stalls…</p>;
  const active = view.listings.filter((l) => l.status === "active");
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        {(["buy", "sell", "mine"] as const).map((m) => (
          <button key={m} className={`btn small ${mode === m ? "" : "secondary"}`} onClick={() => setMode(m)}>
            {m === "buy" ? "Buy" : m === "sell" ? "Sell" : `My listings (${active.length}/${view.max_listings})`}
          </button>
        ))}
        <span className="grow" />
        {mode === "buy" && <input className="qty-input wide-input" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the market" />}
      </div>
      {mode === "mine" ? (
        <div className="col" style={{ gap: 3 }}>
          {view.listings.length === 0 && <p className="small muted">You haven't listed anything yet. Try the Sell tab.</p>}
          {view.listings.map((ls) => (
            <div key={ls.id} className={`slot row listing-row ${ls.status}`} style={{ gap: 8 }}>
              <Icon name={itemIcon(ls.item)} scale={2} />
              <span className="col grow" style={{ gap: 0 }}>
                <span className="head">{itemName(ls.item)} · {n(ls.unit_price)} each</span>
                <span className="small muted">
                  {ls.status === "active" ? `${n(ls.listed - ls.quantity)} of ${n(ls.listed)} sold · ${left(ls.expires_ms)} left` : `${ls.status} · ${n(ls.listed - ls.quantity)} of ${n(ls.listed)} sold`}
                </span>
              </span>
              {ls.status === "active" && (
                <button className="btn small secondary" onClick={async () => {
                  if (await post(`/api/pmarket/listings/${ls.id}/cancel`)) {
                    toast("Taken down. What didn't sell is in your mail.", "good", "mail");
                    void load();
                  }
                }}>Take down</button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="pm-body">
          <div className="pm-list col">
            {mode === "buy" && items.length === 0 && <p className="small muted">Nothing for sale{q ? " matches that" : " yet. Be the first to list something!"}.</p>}
            {mode === "sell" && view.sellable.length === 0 && <p className="small muted">Nothing in your bag can be listed. Materials, food, potions, fish and trophies can.</p>}
            {mode === "buy"
              ? items.map((i) => (
                <button key={i.item} className={`slot market-row ${pick === i.item ? "picked" : ""}`} onClick={() => setPick(i.item)}>
                  <Icon name={itemIcon(i.item)} scale={2} />
                  <span className="col market-name" style={{ gap: 0 }}>
                    <span className="head">{i.name}</span>
                    <span className="small muted">{n(i.quantity)} for sale · {i.listings} seller{i.listings === 1 ? "" : "s"}</span>
                  </span>
                  <span className="col market-price" style={{ gap: 0 }}>
                    <span className="head">from {n(i.lowest)} <Icon name="coins" scale={1} /></span>
                    <span className="small muted">{i.last ? `last ${n(i.last)}` : `worth ~${n(i.reference)}`}</span>
                  </span>
                </button>
              ))
              : view.sellable.map((s) => (
                <button key={s.item} className={`slot market-row ${pick === s.item ? "picked" : ""}`} onClick={() => setPick(s.item)}>
                  <Icon name={itemIcon(s.item)} scale={2} />
                  <span className="col market-name" style={{ gap: 0 }}>
                    <span className="head">{s.name}</span>
                    <span className="small muted">have {n(s.have)}</span>
                  </span>
                  <span className="small muted">~{n(s.reference)}</span>
                </button>
              ))}
          </div>
          {pick && mode === "buy" && <ItemDetail item={pick} onChange={load} />}
          {pick && mode === "sell" && view.sellable.find((s) => s.item === pick) && (
            <SellForm s={view.sellable.find((s) => s.item === pick)!} view={view} onDone={() => { void load(); setMode("mine"); }} />
          )}
        </div>
      )}
    </div>
  );
}

// ── leaderboards ─────────────────────────────────────────────────────────────

interface Board { key: string; name: string; unit: string; rows: { rank: number; user_id: string; name: string; realm: string | null; level: number; title: string | null; value: number }[]; me: { rank: number; value: number } | null }

function BoardsTab() {
  const [list, setList] = useState<{ key: string; name: string; unit: string }[]>([]);
  const [key, setKey] = useState("likes");
  const [b, setB] = useState<Board | null>(null);
  const me = useSession((s) => s.me?.user.id);
  useEffect(() => {
    api<{ boards: { key: string; name: string; unit: string }[] }>("/api/leaderboards").then((r) => setList(r.boards)).catch(() => undefined);
  }, []);
  useEffect(() => {
    setB(null);
    api<Board>(`/api/leaderboards/${key}`).then(setB).catch(() => toast("Couldn't read the boards.", "bad"));
  }, [key]);
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
        {list.map((x) => (
          <button key={x.key} className={`btn small ${key === x.key ? "" : "secondary"}`} onClick={() => setKey(x.key)}>{x.name}</button>
        ))}
      </div>
      {!b ? <p>Counting…</p> : (
        <div className="col" style={{ gap: 2 }}>
          {b.rows.length === 0 && <p className="small muted">Nobody's on this board yet.</p>}
          {b.rows.map((r) => (
            <div key={r.user_id} className={`slot row board-row ${r.user_id === me ? "me" : ""} rank-${Math.min(r.rank, 4)}`} style={{ gap: 8 }}>
              <span className="head board-rank">#{r.rank}</span>
              <span className="col grow" style={{ gap: 0, minWidth: 0 }}>
                <span className="head">{r.name} <TitleTag title={r.title} /></span>
                <span className="small muted">{r.realm ?? "a lone village"} · level {r.level}</span>
              </span>
              <span className="head">{n(r.value)} <span className="small muted">{b.unit}</span></span>
            </div>
          ))}
          {b.me && !b.rows.some((r) => r.user_id === me) && (
            <div className="slot row board-row me" style={{ gap: 8 }}>
              <span className="head board-rank">#{b.me.rank}</span>
              <span className="head grow">You</span>
              <span className="head">{n(b.me.value)} <span className="small muted">{b.unit}</span></span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── the world boss ───────────────────────────────────────────────────────────

function WorldTab() {
  const w = usePlaza((s) => s.world);
  const config = useSession((s) => s.config)!;
  useEffect(() => {
    void usePlaza.getState().refresh();
    const id = window.setInterval(() => void usePlaza.getState().refresh(), 5000);
    return () => window.clearInterval(id);
  }, []);
  if (!w) return <p>Listening for rumbles…</p>;
  const ev = w.event;
  const enemy = config.bosses[w.boss]?.enemy ?? "stone_colossus";
  const share = ev ? ev.hp_remaining / Math.max(1, ev.hp_max) : 1;
  return (
    <div className="col world-tab" style={{ gap: 10 }}>
      <div className="slot row world-card" style={{ gap: 12 }}>
        <span className="world-boss-art"><SpriteThumb name={`mon.${enemy}.idle.0`} box={96} maxScale={3} /></span>
        <span className="col grow" style={{ gap: 4, minWidth: 0 }}>
          <span className="head" style={{ fontSize: 22 }}>{w.name}</span>
          {!ev ? (
            <span className="small">Wakes every weekend. Every realm fights it together, with one health bar for the whole world.
              {w.next_ms ? <> Next in <b>{left(w.next_ms)}</b>.</> : null}</span>
          ) : (
            <>
              <span className="small">
                {ev.status === "active" ? <>Awake at every realm's hub · <b>{left(ev.ends_ms)}</b> left</>
                  : ev.status === "defeated" ? <b>Defeated by the world! Rewards are in everyone's mail.</b>
                  : <b>It slipped away. Rewards for everyone who fought are in the mail.</b>}
              </span>
              <span className="world-hp" role="meter" aria-valuenow={ev.hp_remaining} aria-valuemax={ev.hp_max} aria-label="World boss health">
                <span style={{ width: `${share * 100}%` }} />
                <b>{n(ev.hp_remaining)} / {n(ev.hp_max)}</b>
              </span>
              {ev.status === "active" && useAvatar.getState().mode === "build" && (
                <button className="btn gold small" style={{ alignSelf: "flex-start" }} onClick={() => { usePlaza.getState().set({ tab: null }); enterAvatar(); }}>
                  <Icon name="avatar" scale={1.5} /> Head to the hub and fight
                </button>
              )}
            </>
          )}
        </span>
      </div>
      <div className="world-cols">
        <div className="col" style={{ gap: 4 }}>
          <span className="head">Your rewards <span className="small muted">by your own damage{ev ? ` · you've dealt ${n(ev.me.damage)}` : ""}</span></span>
          {w.tiers.map((t, i) => {
            const got = ev ? ev.me.tier > i : false;
            return (
              <div key={i} className={`slot row tier-row ${got ? "got" : ""}`} style={{ gap: 6 }}>
                <Icon name={got ? "check" : "lock"} scale={1.5} />
                <span className="grow small"><b>{n(t.damage)}+</b> damage</span>
                <span className="small row" style={{ gap: 6 }}>
                  {n(t.coins)} <Icon name="coins" scale={1} />
                  {Object.entries(t.items).map(([k, q]) => <span key={k} className="row" style={{ gap: 1 }} title={itemName(k)}><Icon name={itemIcon(k)} scale={1} />{q}</span>)}
                </span>
              </div>
            );
          })}
          <span className="small muted">Coins ×1.5 if the world brings it down. Fighters from the top {w.top_realms} realms earn the title “{w.title}”.</span>
        </div>
        <div className="col" style={{ gap: 4 }}>
          <span className="head">Top realms</span>
          {!ev || ev.realms.length === 0 ? <span className="small muted">No damage yet. Be the first!</span> : ev.realms.map((r, i) => (
            <div key={r.realm_id} className="slot row board-row" style={{ gap: 6 }}>
              <span className="head board-rank">#{i + 1}</span>
              <span className="grow">{r.name} <span className="small muted">· {r.fighters} fighter{r.fighters === 1 ? "" : "s"}</span></span>
              <b>{n(r.damage)}</b>
            </div>
          ))}
          {ev && ev.players.length > 0 && (
            <span className="small muted">Top fighters: {ev.players.slice(0, 5).map((p) => `${p.name} (${n(p.damage)})`).join(" · ")}</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── festivals ────────────────────────────────────────────────────────────────

function FestivalTab() {
  const f = usePlaza((s) => s.festival);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void usePlaza.getState().refresh();
  }, []);
  if (!f) return <p>Checking the calendar…</p>;
  const a = f.active;
  if (!a) {
    return (
      <div className="slot col" style={{ gap: 6, padding: 12 }}>
        <span className="head" style={{ fontSize: 20 }}>No festival right now</span>
        {f.next && <span>Next up: <b>{f.next.name}</b>, in {left(f.next.starts_ms)}.</span>}
      </div>
    );
  }
  const buy = async (index: number, name: string) => {
    setBusy(true);
    const r = await post("/api/festival/buy", { index });
    setBusy(false);
    if (!r) return;
    sfx("fanfare");
    toast(`${name}: yours!`, "good", a.token);
    void usePlaza.getState().refresh();
  };
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="slot col festival-banner" style={{ gap: 4, ["--fest" as string]: a.color }}>
        <span className="head" style={{ fontSize: 24 }}>{a.name}</span>
        <span>{a.desc}</span>
        <span className="small muted">Ends in {left(a.ends_ms)} · monsters drop {a.token_name}s ({Math.round(a.drop_chance * 100)}% a kill, double from elites)</span>
        <span className="head row" style={{ gap: 4 }}><Icon name={a.token} scale={2} /> {n(a.have)} {a.token_name}{a.have === 1 ? "" : "s"}</span>
      </div>
      <div className="stock-grid">
        {a.shop.map((e) => (
          <div key={e.index} className={`slot stock-card col ${e.owned ? "sold" : ""}`}>
            <Icon name={e.item ? itemIcon(e.item) : "star"} scale={3} />
            <span className="head" style={{ fontSize: 16 }}>{e.item ? `${e.name}${e.qty > 1 ? ` ×${e.qty}` : ""}` : e.name}</span>
            <span className="small row" style={{ gap: 3 }}>{e.cost} <Icon name={a.token} scale={1} /></span>
            <button className="btn small gold" disabled={busy || e.owned || a.have < e.cost} onClick={() => buy(e.index, e.name)}>
              {e.owned ? "Owned" : "Buy"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── the panel, the button, the chips ─────────────────────────────────────────

const TABS: { key: PlazaTab; label: string; icon: string }[] = [
  { key: "market", label: "Player market", icon: "market" },
  { key: "boards", label: "Leaderboards", icon: "star" },
  { key: "world", label: "World boss", icon: "globe" },
  { key: "festival", label: "Festival", icon: "calendar" },
];

export function PlazaPanel({ onClose }: { onClose: () => void }) {
  const tab = usePlaza((s) => s.tab) ?? "market";
  return (
    <Modal title="Plaza" onClose={onClose} wide>
      <div className="row tabs plaza-tabs" role="tablist" style={{ gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} aria-label={t.label} title={t.label}
            className={`btn small ${tab === t.key ? "" : "secondary"}`} onClick={() => usePlaza.getState().set({ tab: t.key })}>
            <Icon name={t.icon} scale={1.5} /> <span className="tab-label">{t.label}</span>
          </button>
        ))}
      </div>
      {tab === "market" ? <MarketTab /> : tab === "boards" ? <BoardsTab /> : tab === "world" ? <WorldTab /> : <FestivalTab />}
    </Modal>
  );
}

export function PlazaButton({ iconOnly = true }: { iconOnly?: boolean }) {
  const live = usePlaza((s) => s.world?.event?.status === "active");
  return (
    <button className={`btn secondary has-dot ${iconOnly ? "icon-only" : ""}`} onClick={() => usePlaza.getState().set({ tab: live ? "world" : "market" })}
      aria-label="Plaza: player market, leaderboards, world boss, festivals" title="Plaza: player market, leaderboards, world boss, festivals">
      <Icon name="globe" />
      {live && <span className="dot-count">!</span>}
    </button>
  );
}

/** Under the mini-map: the festival that's on, and the world boss if it's awake. */
export function GlobalChips() {
  const f = usePlaza((s) => s.festival?.active);
  const ev = usePlaza((s) => s.world?.event);
  const name = usePlaza((s) => s.world?.name);
  useEffect(() => {
    void usePlaza.getState().refresh();
    const id = window.setInterval(() => void usePlaza.getState().refresh(), 30_000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <>
      {f && (
        <button className="hud-bar hud-chip festival-chip" style={{ ["--fest" as string]: f.color }} onClick={() => usePlaza.getState().set({ tab: "festival" })}
          title={`${f.name}: ends in ${left(f.ends_ms)}`}>
          <Icon name={f.token} scale={1.5} /> <span className="small">{f.name}</span>
        </button>
      )}
      {ev && ev.status === "active" && (
        <button className="hud-bar hud-chip world-chip" onClick={() => usePlaza.getState().set({ tab: "world" })} title={`${name}: the whole world is fighting it`}>
          <Icon name="globe" scale={1.5} /> <span className="small">{Math.ceil((ev.hp_remaining / Math.max(1, ev.hp_max)) * 100)}%</span>
        </button>
      )}
    </>
  );
}
