// Phase 18: the admin panel (role=admin). The live server at a glance, players (search, detail, grant, ban,
// test flag), the economy (coin supply, faucets vs sinks), events (start a world boss) and the audit log.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { itemIcon } from "../../game/items";
import { useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { Icon, Panel } from "../components/kit";
import { Sparkline } from "../hud/Market";

const n = (v: number) => v.toLocaleString();
const when = (ms: number | null) => (ms ? new Date(ms).toLocaleString() : "never");

async function post<T>(path: string, body: unknown): Promise<T | null> {
  try {
    return await api<T>(path, { method: "POST", body });
  } catch (e) {
    toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
    return null;
  }
}

interface Overview {
  players: number;
  online: number;
  active_7d: number;
  realms: number;
  coin_supply: number;
  listings: number;
  trades_24h: number;
  rooms: { realm_id: string; players: number; monsters: number; tick_ms: { p50?: number; p99?: number; max?: number } }[];
  world_boss: null | { name: string; status: string; hp: number; hp_max: number; ends_ms: number };
  festival: string | null;
  config_hash: string;
}
interface PlayerRow { id: string; username: string; role: string; level: number; coins: number; realm: string | null; created_ms: number; last_seen_ms: number | null; online: boolean; test: boolean; banned: boolean }
interface PlayerDetail { id: string; username: string; level: number; xp: number; title: string | null; coins: number; test: boolean; banned: boolean; created_ms: number; last_seen_ms: number | null; stats: Record<string, number>; ledger: { at_ms: number; reason: string; asset: string; item: string | null; delta: number; actor: string }[]; bag: { item: string; qty: number }[] }
interface Economy { coin_supply: number; wallets: number; mean_coins: number; series: { at_ms: number; supply: number }[]; day: { faucets: Record<string, number>; sinks: Record<string, number>; net: number }; week: { net: number } }
interface Audit { at_ms: number; actor: string; action: string; target: string | null; payload: Record<string, unknown> }

function Card({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="slot admin-card col">
      <span className="small muted">{label}</span>
      <span className="head" style={{ fontSize: 24 }}>{typeof value === "number" ? n(value) : value}</span>
      {sub && <span className="small muted">{sub}</span>}
    </div>
  );
}

function PlayerPanel({ id, onChange }: { id: string; onChange: () => void }) {
  const [p, setP] = useState<PlayerDetail | null>(null);
  const [coins, setCoins] = useState(0);
  const [item, setItem] = useState("");
  const [qty, setQty] = useState(1);
  const load = useCallback(async () => setP(await api<PlayerDetail>(`/api/admin/players/${id}`).catch(() => null)), [id]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!p) return <Panel className="admin-detail"><p>Loading…</p></Panel>;
  const grant = async () => {
    const items = item ? { [item.trim()]: qty } : {};
    if (await post("/api/admin/grant", { user_id: p.id, coins, items })) {
      toast(`Granted to ${p.username}.`, "good", "check");
      setCoins(0);
      setItem("");
      void load();
      onChange();
    }
  };
  return (
    <Panel className="admin-detail col">
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <span className="head" style={{ fontSize: 20 }}>{p.username}</span>
        <span className="small muted">level {p.level}{p.title ? ` · “${p.title}”` : ""} · {n(p.coins)} coins · joined {when(p.created_ms)} · seen {when(p.last_seen_ms)}</span>
        <span className="grow" />
        <button className={`btn small ${p.test ? "" : "secondary"}`} onClick={async () => { if (await post("/api/admin/test-account", { user_id: p.id, enable: !p.test })) { void load(); onChange(); } }}>
          {p.test ? "Test account ✓" : "Mark as test"}
        </button>
        <button className={`btn small ${p.banned ? "secondary" : "danger"}`} onClick={async () => { if (await post("/api/admin/ban", { user_id: p.id, enable: !p.banned })) { void load(); onChange(); } }}>
          {p.banned ? "Unban" : "Ban"}
        </button>
      </div>
      <div className="row admin-grant" style={{ gap: 6, flexWrap: "wrap" }}>
        <span className="small head">Grant</span>
        <input className="qty-input" type="number" min={0} value={coins} onChange={(e) => setCoins(Math.max(0, Number(e.target.value) || 0))} aria-label="Coins" /> coins
        <input className="qty-input wide-input" placeholder="item key (e.g. ironbark)" value={item} onChange={(e) => setItem(e.target.value)} aria-label="Item key" />
        <input className="qty-input" type="number" min={1} value={qty} onChange={(e) => setQty(Math.max(1, Number(e.target.value) || 1))} aria-label="Quantity" />
        <button className="btn small gold" disabled={!coins && !item} onClick={grant}>Grant</button>
      </div>
      <div className="admin-cols">
        <div className="col" style={{ gap: 2 }}>
          <span className="head small">Counters</span>
          {Object.entries(p.stats).map(([k, v]) => <span key={k} className="small row"><span className="grow muted">{k}</span><b>{n(v)}</b></span>)}
          <span className="head small" style={{ marginTop: 6 }}>Bag</span>
          <span className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            {p.bag.map((s, i) => <span key={i} className="row small" style={{ gap: 2 }} title={s.item}><Icon name={itemIcon(s.item)} scale={1.5} />{s.qty}</span>)}
          </span>
        </div>
        <div className="col" style={{ gap: 2 }}>
          <span className="head small">Ledger (latest 25)</span>
          {p.ledger.map((t, i) => (
            <span key={i} className="small row admin-ledger">
              <span className="muted">{new Date(t.at_ms).toLocaleTimeString()}</span>
              <span className="grow">{t.reason}{t.item ? ` · ${t.item}` : ""}</span>
              <b style={{ color: t.delta < 0 ? "var(--red)" : "var(--leaf)" }}>{t.delta > 0 ? "+" : ""}{n(t.delta)}{t.asset === "coin" ? "c" : ""}</b>
            </span>
          ))}
        </div>
      </div>
    </Panel>
  );
}

export function AdminScreen() {
  const me = useSession((s) => s.me);
  const [o, setO] = useState<Overview | null>(null);
  const [eco, setEco] = useState<Economy | null>(null);
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<PlayerRow[]>([]);
  const [pick, setPick] = useState<string | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [hp, setHp] = useState(300000);
  const [denied, setDenied] = useState(false);
  const refresh = useCallback(async () => {
    try {
      setO(await api<Overview>("/api/admin/overview"));
      setEco(await api<Economy>("/api/admin/economy"));
      setAudit((await api<{ entries: Audit[] }>("/api/admin/audit")).entries);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setDenied(true);
    }
  }, []);
  const search = useCallback(async () => {
    setRows((await api<{ players: PlayerRow[] }>(`/api/admin/players?q=${encodeURIComponent(q)}`).catch(() => ({ players: [] }))).players);
  }, [q]);
  useEffect(() => {
    void refresh();
    const id = window.setInterval(refresh, 10000);
    return () => window.clearInterval(id);
  }, [refresh]);
  useEffect(() => {
    const t = window.setTimeout(search, 250);
    return () => window.clearTimeout(t);
  }, [search]);
  if (denied || (me && me.user.role !== "admin")) {
    return (
      <div className="title-bg center" style={{ minHeight: "100vh" }}>
        <Panel><p className="head">Admins only.</p><Link to="/play" className="btn small">Back to the game</Link></Panel>
      </div>
    );
  }
  const faucets = Object.entries(eco?.day.faucets ?? {}).sort((a, b) => b[1] - a[1]);
  const sinks = Object.entries(eco?.day.sinks ?? {}).sort((a, b) => b[1] - a[1]);
  return (
    <div className="admin col">
      <div className="row" style={{ gap: 10 }}>
        <span className="ribbon">Hearthforge admin</span>
        <span className="small muted">config {o?.config_hash.slice(0, 8)}</span>
        <span className="grow" />
        <Link to="/play" className="btn secondary small">Back to the game</Link>
      </div>
      {o && (
        <div className="admin-cards">
          <Card label="Players" value={o.players} sub={`${n(o.active_7d)} active this week`} />
          <Card label="Online now" value={o.online} sub={`${o.rooms.reduce((a, r) => a + r.players, 0)} in the world`} />
          <Card label="Realms" value={o.realms} sub={`${o.rooms.length} rooms running`} />
          <Card label="Coin supply" value={o.coin_supply} sub={eco ? `net ${eco.day.net >= 0 ? "+" : ""}${n(eco.day.net)} today` : undefined} />
          <Card label="Player market" value={o.listings} sub={`listings · ${n(o.trades_24h)} trades today`} />
          <Card label="Events" value={o.festival ?? "—"} sub={o.world_boss ? `${o.world_boss.name}: ${o.world_boss.status} ${Math.round((o.world_boss.hp / o.world_boss.hp_max) * 100)}%` : "no world boss"} />
        </div>
      )}
      <div className="admin-cols">
        <Panel className="col">
          <span className="head">Rooms</span>
          {o?.rooms.length === 0 && <span className="small muted">No realm rooms running.</span>}
          {o?.rooms.map((r) => (
            <span key={r.realm_id} className="small row admin-ledger">
              <span className="grow muted">{r.realm_id.slice(0, 8)}</span>
              {r.players} players · {r.monsters} monsters · tick p50 <b>{r.tick_ms.p50?.toFixed(2) ?? "—"}</b> / p99 <b>{r.tick_ms.p99?.toFixed(2) ?? "—"}</b> ms
            </span>
          ))}
          <span className="small muted">Budget: p99 under 10 ms at 20 Hz (half the 50 ms tick).</span>
        </Panel>
        <Panel className="col">
          <span className="head">Economy (24 h)</span>
          {eco && eco.series.length > 1 && <Sparkline values={eco.series.map((s) => s.supply)} trend={Math.sign(eco.week.net)} w={300} h={48} interactive label="Coin supply, 7 days" />}
          <div className="admin-cols">
            <div className="col">{faucets.slice(0, 8).map(([k, v]) => <span key={k} className="small row"><span className="grow muted">{k}</span><b style={{ color: "var(--leaf)" }}>+{n(v)}</b></span>)}</div>
            <div className="col">{sinks.slice(0, 8).map(([k, v]) => <span key={k} className="small row"><span className="grow muted">{k}</span><b style={{ color: "var(--red)" }}>−{n(v)}</b></span>)}</div>
          </div>
        </Panel>
      </div>
      <Panel className="col">
        <div className="row" style={{ gap: 8 }}>
          <span className="head">Players</span>
          <input className="qty-input wide-input grow" placeholder="Search by name…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search players" />
        </div>
        <div className="admin-table">
          {rows.map((r) => (
            <button key={r.id} className={`slot row admin-row ${pick === r.id ? "picked" : ""}`} onClick={() => setPick(pick === r.id ? null : r.id)}>
              <span className={`online-dot ${r.online ? "on" : ""}`} />
              <span className="head grow" style={{ textAlign: "left" }}>{r.username} {r.role === "admin" && <span className="tag gold">admin</span>} {r.test && <span className="tag">test</span>} {r.banned && <span className="tag" style={{ background: "var(--red)", color: "var(--paper-light)" }}>banned</span>}</span>
              <span className="small muted">{r.realm ?? "—"}</span>
              <span className="small">lv {r.level}</span>
              <span className="small">{n(r.coins)}c</span>
              <span className="small muted">{when(r.last_seen_ms)}</span>
            </button>
          ))}
        </div>
        {pick && <PlayerPanel id={pick} onChange={() => { void search(); void refresh(); }} />}
      </Panel>
      <div className="admin-cols">
        <Panel className="col">
          <span className="head">World boss</span>
          <span className="small muted">Starts one now for 2 hours (ends any that's running). Weekends open their own.</span>
          <span className="row" style={{ gap: 6 }}>
            HP <input className="qty-input" type="number" min={1000} step={10000} value={hp} onChange={(e) => setHp(Math.max(1000, Number(e.target.value) || 1000))} aria-label="World boss HP" />
            <button className="btn small gold" onClick={async () => { if (await post("/api/admin/worldboss", { hours: 2, hp })) { toast("The world boss is awake.", "good", "globe"); void refresh(); } }}>Start</button>
          </span>
        </Panel>
        <Panel className="col">
          <span className="head">Audit log</span>
          {audit.length === 0 && <span className="small muted">Nothing yet.</span>}
          {audit.slice(0, 12).map((a, i) => (
            <span key={i} className="small row admin-ledger">
              <span className="muted">{new Date(a.at_ms).toLocaleString()}</span>
              <span className="grow"><b>{a.actor}</b> {a.action} {a.target ? a.target.slice(0, 8) : ""}</span>
            </span>
          ))}
        </Panel>
      </div>
    </div>
  );
}
