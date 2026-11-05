// Phase 9: the realm panel. Found or join a realm, see members (trust, kick, hand over), the shared
// stash with its trust rules, and the activity feed.
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { InventoryView, InvSlotView } from "../../api/types";
import { itemIcon, itemName, RARITY_COLOR } from "../../game/items";
import { sfx } from "../../game/sfx";
import { useRealm, type RealmView } from "../../state/realm";
import { serverNow, useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { CharacterPreview, Icon, Modal } from "../components/kit";

async function act<T>(path: string, body?: unknown, method = "POST"): Promise<T | null> {
  try {
    return await api<T>(path, { method, body });
  } catch (e) {
    toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
    return null;
  }
}

function ago(ms: number): string {
  const s = Math.max(0, (serverNow() - ms) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// ── solo: found or join ──────────────────────────────────────────────────────
function SoloOptions({ onDone }: { onDone: (r: RealmView) => void }) {
  const me = useSession((s) => s.me);
  const [name, setName] = useState(`${me?.user.username ?? "Our"}'s Realm`);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const found = async () => {
    setBusy(true);
    const r = await act<{ realm: RealmView }>("/api/realms", { name });
    setBusy(false);
    if (r) {
      sfx("fanfare");
      toast("Your realm is open! Share the invite code with friends.", "good", "banner");
      onDone(r.realm);
    }
  };
  const join = async () => {
    setBusy(true);
    const r = await act<{ realm: RealmView }>("/api/realms/join", { code });
    setBusy(false);
    if (r) {
      toast(`Welcome to ${r.realm.name}! Moving your village…`, "good", "banner");
      window.setTimeout(() => window.location.reload(), 900);
    }
  };
  return (
    <div className="col" style={{ gap: 10 }}>
      <p className="small" style={{ margin: 0 }}>
        You're on your own for now. A realm holds up to 10 villages around one hub: you see each other's homes,
        explore and fight together, and share a stash.
      </p>
      <div className="realm-cards">
        <div className="slot col realm-card">
          <span className="head"><Icon name="banner" scale={1.5} /> Open your realm</span>
          <span className="small muted">Your village stays put. You get an invite code to share.</span>
          <input className="qty-input wide-input" value={name} maxLength={24} onChange={(e) => setName(e.target.value)} aria-label="Realm name" />
          <button className="btn gold small" disabled={busy || name.trim().length < 3} onClick={found}>Open it up</button>
        </div>
        <div className="slot col realm-card">
          <span className="head"><Icon name="party" scale={1.5} /> Join a friend</span>
          <span className="small muted">Your whole village moves to a free plot in their realm.</span>
          <input className="qty-input wide-input code-input" value={code} maxLength={6} placeholder="CODE42"
            onChange={(e) => setCode(e.target.value.toUpperCase())} aria-label="Invite code" />
          <button className="btn small" disabled={busy || code.length !== 6} onClick={join}>Join realm</button>
        </div>
      </div>
    </div>
  );
}

// ── members ──────────────────────────────────────────────────────────────────
function Members({ realm, onChange }: { realm: RealmView; onChange: (r: RealmView) => void }) {
  const me = useSession((s) => s.me);
  const owner = realm.me.role === "owner";
  const [confirm, setConfirm] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(realm.name);
  const run = async (key: string, path: string, body: unknown, after?: () => void) => {
    if (confirm !== key) return setConfirm(key);
    setConfirm(null);
    const r = await act<{ realm: RealmView }>(path, body);
    if (r) {
      onChange(r.realm);
      after?.();
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(realm.invite_code ?? "");
      toast("Invite code copied!", "good", "check");
    } catch {
      toast(`Your code is ${realm.invite_code}`, "good");
    }
  };
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="row realm-head" style={{ gap: 8, flexWrap: "wrap" }}>
        {renaming ? (
          <>
            <input className="qty-input wide-input" value={name} maxLength={24} onChange={(e) => setName(e.target.value)} aria-label="New realm name" />
            <button className="btn small" onClick={async () => {
              const r = await act<{ realm: RealmView }>("/api/realm", { name }, "PATCH");
              if (r) onChange(r.realm);
              setRenaming(false);
            }}>Save</button>
          </>
        ) : (
          <span className="head" style={{ fontSize: 19 }}>
            <Icon name="banner" scale={1.5} /> {realm.name}
            {owner && <button className="link-btn small" style={{ marginLeft: 6 }} onClick={() => setRenaming(true)}>rename</button>}
          </span>
        )}
        <span className="grow" />
        <span className="slot invite-chip row" title="Friends join with this code">
          <span className="small muted">Invite code</span> <b className="head code">{realm.invite_code}</b>
          <button className="btn secondary small" onClick={copy}>Copy</button>
          {owner && (
            <button className="link-btn small" onClick={async () => {
              const r = await act<{ invite_code: string }>("/api/realm/invite-code");
              if (r) onChange({ ...realm, invite_code: r.invite_code });
            }}>new code</button>
          )}
        </span>
      </div>
      <span className="small muted">{realm.members.length} of {realm.max_members} villages</span>
      <div className="col" style={{ gap: 4 }}>
        {realm.members.map((m) => {
          const self = m.user_id === me?.user.id;
          return (
            <div key={m.user_id} className="slot member-row row">
              <span className="member-face"><CharacterPreview look={m.appearance} scale={2} walking={false} /></span>
              <span className="col grow" style={{ gap: 0, minWidth: 0 }}>
                <span className="head row" style={{ gap: 6 }}>
                  <span className={`online-dot ${m.online ? "on" : ""}`} title={m.online ? "Online" : "Away"} />
                  {m.username}{self ? " (you)" : ""}
                  {m.role === "owner" && <span className="tag gold">owner</span>}
                  {m.role !== "owner" && m.trusted && <span className="tag">trusted</span>}
                  {m.newcomer && <span className="tag muted">new</span>}
                </span>
                <span className="small muted">Level {m.level} · plot {m.plot + 1}</span>
              </span>
              <span className="row member-actions" style={{ gap: 4, flexWrap: "wrap", justifyContent: "flex-end" }}>
                {owner && !self && (
                  <>
                    <button className="btn secondary small" onClick={async () => {
                      const r = await act<{ realm: RealmView }>("/api/realm/trust", { user_id: m.user_id, trusted: !m.trusted });
                      if (r) onChange(r.realm);
                    }}>{m.trusted ? "Untrust" : "Trust"}</button>
                    <button className={`btn small ${confirm === `own${m.user_id}` ? "danger" : "secondary"}`}
                      onClick={() => run(`own${m.user_id}`, "/api/realm/transfer", { user_id: m.user_id })}>
                      {confirm === `own${m.user_id}` ? "Sure? Hand over" : "Make owner"}
                    </button>
                    <button className={`btn small ${confirm === `kick${m.user_id}` ? "danger" : "secondary"}`}
                      onClick={() => run(`kick${m.user_id}`, "/api/realm/kick", { user_id: m.user_id })}>
                      {confirm === `kick${m.user_id}` ? "Sure? Kick" : "Kick"}
                    </button>
                  </>
                )}
                {self && (!owner || realm.members.length === 1) && (
                  <button className={`btn small ${confirm === "leave" ? "danger" : "secondary"}`}
                    onClick={() => run("leave", "/api/realm/leave", undefined, () => window.setTimeout(() => window.location.reload(), 700))}>
                    {confirm === "leave" ? "Sure? Leave" : "Leave realm"}
                  </button>
                )}
              </span>
            </div>
          );
        })}
      </div>
      {owner && realm.members.length > 1 && (
        <p className="small muted" style={{ margin: 0 }}>To leave, hand the realm to someone first. Trusted members can take anything from the stash.</p>
      )}
    </div>
  );
}

// ── stash ────────────────────────────────────────────────────────────────────
interface StashView {
  available: boolean;
  capacity: number;
  slots: (InvSlotView & { value: number })[];
  rules: { trusted: boolean; newcomer: boolean; newcomer_until_ms: number | null; daily_cap: number | null; used_today: number };
}

function MiniCell({ s, onClick, title }: { s?: InvSlotView; onClick?: () => void; title?: string }) {
  const color = s?.rarity && s.rarity !== "common" ? RARITY_COLOR[s.rarity] : undefined;
  return (
    <button className="slot av-cell" disabled={!s} onClick={onClick} title={title}
      style={color ? { boxShadow: `inset 0 0 0 2px ${color}` } : undefined}>
      {s && <Icon name={itemIcon(s.item, s.tier)} scale={2} />}
      {s && s.qty > 1 && <span className="av-qty">{s.qty}</span>}
    </button>
  );
}

function Stash() {
  const [stash, setStash] = useState<StashView | null>(null);
  const [bag, setBag] = useState<InventoryView | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [s, b] = await Promise.all([act<StashView>("/api/realm/stash", undefined, "GET"), act<InventoryView>("/api/inventory", undefined, "GET")]);
    if (s) setStash(s);
    if (b) setBag(b);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  if (!stash || !bag) return <p>Opening the stash…</p>;
  const move = async (path: string, slot: number, qty: number) => {
    setBusy(true);
    const r = await act<{ stash: StashView; moved: { item: string; qty: number } }>(path, { slot, quantity: qty });
    setBusy(false);
    if (r) {
      sfx(path.endsWith("deposit") ? "deposit" : "pickup");
      setStash(r.stash);
      const b = await act<InventoryView>("/api/inventory", undefined, "GET");
      if (b) setBag(b);
    }
  };
  const st = new Map(stash.slots.map((s) => [s.slot, s]));
  const inv = new Map(bag.inventory.slots.map((s) => [s.slot, s]));
  const r = stash.rules;
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="slot small stash-rules">
        {r.trusted ? (
          <span><Icon name="check" scale={1} /> You're trusted: take anything you need.</span>
        ) : r.newcomer ? (
          <span><Icon name="lock" scale={1} /> New members can only put things in for now (until {new Date(r.newcomer_until_ms ?? 0).toLocaleString()}).</span>
        ) : (
          <span>
            <Icon name="coins" scale={1} /> Daily take-out limit: {r.used_today} / {r.daily_cap} coins' worth. Ask the owner to trust you for more.
          </span>
        )}
      </div>
      <span className="head small">Realm stash ({stash.slots.length}/{stash.capacity}) · tap to take</span>
      <div className="av-grid stash-grid">
        {Array.from({ length: stash.capacity }, (_, i) => {
          const s = st.get(i);
          return (
            <MiniCell key={i} s={s} title={s ? `${s.name ?? itemName(s.item)} ×${s.qty} (worth ${s.value} each). Tap to take.` : "Empty"}
              onClick={busy || !s ? undefined : () => void move("/api/realm/stash/withdraw", i, s.qty)} />
          );
        })}
      </div>
      <span className="head small">Your bag · tap to share</span>
      <div className="av-grid">
        {Array.from({ length: bag.inventory.capacity }, (_, i) => {
          const s = inv.get(i);
          return (
            <MiniCell key={i} s={s} title={s ? `${s.name ?? itemName(s.item)} ×${s.qty}. Tap to put in the stash.` : "Empty"}
              onClick={busy || !s ? undefined : () => void move("/api/realm/stash/deposit", i, s.qty)} />
          );
        })}
      </div>
    </div>
  );
}

// ── activity ─────────────────────────────────────────────────────────────────
interface ActivityItem {
  id: number;
  kind: string;
  actor: string | null;
  payload: Record<string, unknown>;
  at_ms: number;
}

function line(a: ActivityItem, names: Record<string, string>): { icon: string; text: string } {
  const who = a.actor ?? "Someone";
  const p = a.payload;
  const qty = (p.qty as number) ?? 0;
  const item = p.item ? itemName(p.item as string).toLowerCase() : "";
  switch (a.kind) {
    case "realm_founded": return { icon: "banner", text: `${who} opened the realm "${p.name}".` };
    case "member_joined": return { icon: "party", text: `${who} moved their village in. Say hi!` };
    case "member_left": return { icon: "home", text: `${who} packed up and left.` };
    case "member_kicked": return { icon: "close", text: `${who} asked ${names[p.user_id as string] ?? "someone"} to leave.` };
    case "owner_changed": return { icon: "star", text: `${who} handed the realm to ${names[p.user_id as string] ?? "someone"}.` };
    case "trust_changed": return { icon: "check", text: `${who} ${p.trusted ? "trusted" : "stopped trusting"} ${names[p.user_id as string] ?? "someone"} with the stash.` };
    case "realm_renamed": return { icon: "banner", text: `${who} renamed the realm to "${p.name}".` };
    case "stash_deposit": return { icon: "chest", text: `${who} put ${qty} ${item} in the stash.` };
    case "stash_withdraw": return { icon: "chest", text: `${who} took ${qty} ${item} from the stash.` };
    case "realm_closed": return { icon: "lock", text: `${who} closed the realm to new members.` };
    default: return { icon: "info", text: `${who}: ${a.kind}` };
  }
}

function Activity({ realm }: { realm: RealmView }) {
  const [items, setItems] = useState<ActivityItem[] | null>(null);
  useEffect(() => {
    void act<{ items: ActivityItem[] }>("/api/realm/activity", undefined, "GET").then((r) => r && setItems(r.items));
  }, []);
  const names = Object.fromEntries(realm.members.map((m) => [m.user_id, m.username]));
  if (!items) return <p>Reading the notice board…</p>;
  if (!items.length) return <p className="small muted">Nothing yet. It'll fill up as your realm gets busy.</p>;
  return (
    <div className="col activity-list" style={{ gap: 4 }}>
      {items.map((a) => {
        const l = line(a, names);
        return (
          <div key={a.id} className="row activity-row small" style={{ gap: 6 }}>
            <Icon name={l.icon} scale={1.5} />
            <span className="grow">{l.text}</span>
            <span className="muted">{ago(a.at_ms)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function RealmPanel({ onClose }: { onClose: () => void }) {
  const realm = useRealm((s) => s.realm);
  const tab = useRealm((s) => s.panel) ?? "members";
  const set = useRealm((s) => s.set);
  useEffect(() => {
    void useRealm.getState().load();
  }, []);
  return (
    <Modal title={realm && !realm.solo ? "Realm" : "Friends & realms"} onClose={onClose} wide>
      {!realm ? (
        <p>Looking around…</p>
      ) : realm.solo ? (
        <SoloOptions onDone={(r) => set({ realm: r })} />
      ) : (
        <>
          <div className="row" role="tablist" style={{ gap: 6, marginBottom: 8 }}>
            {(["members", "stash", "activity"] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={`btn small ${tab === t ? "" : "secondary"}`} onClick={() => set({ panel: t })}>
                <Icon name={t === "members" ? "party" : t === "stash" ? "chest" : "book"} scale={1.5} /> {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
          {tab === "members" && <Members realm={realm} onChange={(r) => set({ realm: r })} />}
          {tab === "stash" && <Stash />}
          {tab === "activity" && <Activity realm={realm} />}
        </>
      )}
    </Modal>
  );
}
