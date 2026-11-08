// Phase 15: friends (requests, blocks), the mailbox, gifts, and visiting a friend's village to like it
// and help with a build. The visit view is a plain 2D canvas drawn from the same sprite atlas.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { InventoryView, VillageState } from "../../api/types";
import { itemIcon, itemName } from "../../game/items";
import { rotatedFootprint, usableBounds } from "../../game/placement";
import { sfx } from "../../game/sfx";
import { buildingLook } from "../../game/sprites";
import { roomLink } from "../../net/room";
import { serverNow, useSession } from "../../state/session";
import { useJournal } from "../../state/journal";
import { socialDot, useSocial, type FriendView, type MailView, type VisitView } from "../../state/social";
import { toast } from "../../state/toasts";
import { CharacterPreview, formatDuration, Icon, Modal } from "../components/kit";
import { loadAtlasForDom } from "../components/SpriteThumb";

const T = 16;

function ago(ms: number): string {
  const s = Math.max(0, (serverNow() - ms) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function Face({ f }: { f: { look: FriendView["look"] } }) {
  return <span className="member-face">{f.look ? <CharacterPreview look={f.look} scale={2} walking={false} /> : <Icon name="avatar" />}</span>;
}

export function TitleTag({ title }: { title: string | null | undefined }) {
  return title ? <span className="tag gold title-tag">{title}</span> : null;
}

// ── friends ──────────────────────────────────────────────────────────────────

function FriendRow({ f, onGift }: { f: FriendView; onGift: (f: FriendView) => void }) {
  const act = useSocial((s) => s.act);
  const [confirm, setConfirm] = useState<"remove" | "block" | null>(null);
  const [more, setMore] = useState(false);
  return (
    <div className="slot member-row row friend-row">
      <Face f={f} />
      <span className="col grow" style={{ gap: 0, minWidth: 0 }}>
        <span className="head row" style={{ gap: 6, flexWrap: "wrap" }}>
          <span className={`online-dot ${f.online ? "on" : ""}`} title={f.online ? "Online" : "Away"} />
          {f.name} <TitleTag title={f.title} />
        </span>
        <span className="small muted">
          Level {f.level}{f.realm ? ` · ${f.realm}` : ""} · <Icon name="heart" scale={1} /> {f.likes}
        </span>
      </span>
      <span className="row member-actions" style={{ gap: 4, flexWrap: "wrap", justifyContent: "flex-end" }}>
        <button className="btn small" onClick={() => useSocial.getState().set({ visiting: f.id })}>
          <Icon name="home" scale={1.5} /> Visit
        </button>
        <button className="btn secondary small" onClick={() => onGift(f)} aria-label={`Send ${f.name} a gift`} title="Send a gift">
          <Icon name="gift" scale={1.5} />
        </button>
        {more ? (
          <>
            <button className={`btn small ${confirm === "remove" ? "danger" : "secondary"}`} onClick={async () => {
              if (confirm !== "remove") return setConfirm("remove");
              await act("/api/social/remove", { user_id: f.id });
            }}>{confirm === "remove" ? "Sure? Unfriend" : "Unfriend"}</button>
            <button className={`btn small ${confirm === "block" ? "danger" : "secondary"}`} onClick={async () => {
              if (confirm !== "block") return setConfirm("block");
              if (await act("/api/social/block", { user_id: f.id })) toast(`Blocked ${f.name}.`, "good", "lock");
            }}>{confirm === "block" ? "Sure? Block" : "Block"}</button>
          </>
        ) : (
          <button className="btn secondary small" onClick={() => setMore(true)} aria-label={`More for ${f.name}`}>⋯</button>
        )}
      </span>
    </div>
  );
}

function AddFriend() {
  const act = useSocial((s) => s.act);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    const r = await act<{ result: string }>("/api/social/request", { name: name.trim() });
    setBusy(false);
    if (!r) return;
    setName("");
    if (r.result === "accepted") {
      sfx("fanfare");
      toast("They'd already asked you. You're friends now!", "good", "party");
    } else toast("Request sent!", "good", "check");
  };
  return (
    <form className="row add-friend" style={{ gap: 6 }} onSubmit={(e) => {
      e.preventDefault();
      if (name.trim()) void send();
    }}>
      <input className="qty-input wide-input grow" value={name} maxLength={40} placeholder="Their username"
        onChange={(e) => setName(e.target.value)} aria-label="Friend's username" />
      <button className="btn small gold" disabled={busy || !name.trim()} type="submit"><Icon name="plus" scale={1.5} /> Add friend</button>
    </form>
  );
}

function FriendsTab({ onGift }: { onGift: (f: FriendView) => void }) {
  const view = useSocial((s) => s.view)!;
  const act = useSocial((s) => s.act);
  return (
    <div className="col" style={{ gap: 8 }}>
      <AddFriend />
      {view.incoming.length > 0 && (
        <div className="col" style={{ gap: 4 }}>
          <span className="head small">Wants to be friends</span>
          {view.incoming.map((f) => (
            <div key={f.id} className="slot member-row row friend-row incoming">
              <Face f={f} />
              <span className="col grow" style={{ gap: 0 }}>
                <span className="head">{f.name} <TitleTag title={f.title} /></span>
                <span className="small muted">Level {f.level}{f.realm ? ` · ${f.realm}` : ""}</span>
              </span>
              <button className="btn small gold" onClick={async () => {
                if (await act("/api/social/respond", { user_id: f.id, accept: true })) {
                  sfx("fanfare");
                  toast(`You and ${f.name} are friends!`, "good", "party");
                }
              }}><Icon name="check" scale={1.5} /> Accept</button>
              <button className="btn small secondary" onClick={() => act("/api/social/respond", { user_id: f.id, accept: false })}>Decline</button>
            </div>
          ))}
        </div>
      )}
      <span className="small muted">{view.friends.length} of {view.max} friends · friends can visit, like and help each other's villages</span>
      {view.friends.length === 0 && (
        <p className="small muted" style={{ margin: 0 }}>No friends yet. Add someone by their username, or befriend your realm-mates.</p>
      )}
      <div className="col" style={{ gap: 4 }}>
        {view.friends.map((f) => <FriendRow key={f.id} f={f} onGift={onGift} />)}
      </div>
      {view.outgoing.length > 0 && (
        <div className="col" style={{ gap: 4 }}>
          <span className="head small">Waiting for an answer</span>
          {view.outgoing.map((f) => (
            <div key={f.id} className="row small" style={{ gap: 6 }}>
              <Icon name="timer" scale={1} /> <b>{f.name}</b> <span className="grow" />
              <button className="link-btn small" onClick={() => act("/api/social/remove", { user_id: f.id })}>cancel</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── mail ─────────────────────────────────────────────────────────────────────

function ItemChips({ items, coins }: { items: Record<string, number>; coins?: number }) {
  return (
    <span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
      {Object.entries(items).map(([k, q]) => (
        <span key={k} className="row" style={{ gap: 2 }} title={itemName(k)}>
          <Icon name={itemIcon(k)} scale={1.5} /> <span className="head">{q}</span>
        </span>
      ))}
      {coins ? <span className="row" style={{ gap: 2 }}><Icon name="coins" scale={1.5} /> <span className="head">{coins}</span></span> : null}
    </span>
  );
}

const MAIL_ICON: Record<string, string> = { gift: "gift", boss: "trophy", system: "calendar" };

function MailTab() {
  const view = useSocial((s) => s.view)!;
  const [busy, setBusy] = useState<string | null>(null);
  const claim = async (m: MailView) => {
    setBusy(m.id);
    try {
      const r = await api<{ got: Record<string, number>; mail: MailView[] }>(`/api/social/mail/${m.id}/claim`, { method: "POST" });
      useSocial.setState((s) => ({ view: s.view ? { ...s.view, mail: r.mail } : s.view }));
      sfx("deposit");
      const left = r.mail.find((x) => x.id === m.id);
      toast(left ? "Your bag is full. The rest waits in the parcel." : "Parcel opened!", left ? "bad" : "good", "mail");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "The parcel won't open.", "bad");
    } finally {
      setBusy(null);
    }
  };
  if (!view.mail.length) return <p className="small muted">Your mailbox is empty. Gifts from friends and boss loot you missed land here.</p>;
  return (
    <div className="col" style={{ gap: 4 }}>
      {view.mail.map((m) => (
        <div key={m.id} className="slot row mail-row" style={{ gap: 8 }}>
          <Icon name={MAIL_ICON[m.kind] ?? "mail"} scale={2} />
          <span className="col grow" style={{ gap: 2, minWidth: 0 }}>
            <span className="head">{m.kind === "gift" ? `A gift from ${m.from}` : m.from}</span>
            {m.note && m.note !== `A gift from ${m.from}` && <span className="small muted">{m.note}</span>}
            <ItemChips items={m.items} coins={m.coins} />
          </span>
          <span className="col" style={{ gap: 2, alignItems: "flex-end" }}>
            <span className="small muted">{ago(m.at_ms)}</span>
            <button className="btn small gold" disabled={busy === m.id} onClick={() => claim(m)}>Claim</button>
          </span>
        </div>
      ))}
    </div>
  );
}

function BlockedTab() {
  const view = useSocial((s) => s.view)!;
  const act = useSocial((s) => s.act);
  if (!view.blocked.length) return <p className="small muted">Nobody's blocked. Blocking someone ends a friendship and hides their chat from you, both ways.</p>;
  return (
    <div className="col" style={{ gap: 4 }}>
      {view.blocked.map((b) => (
        <div key={b.id} className="slot row" style={{ gap: 8 }}>
          <Icon name="lock" scale={1.5} /> <span className="head grow">{b.name}</span>
          <button className="btn small secondary" onClick={() => act("/api/social/unblock", { user_id: b.id })}>Unblock</button>
        </div>
      ))}
    </div>
  );
}

// ── gifts ────────────────────────────────────────────────────────────────────

function GiftDialog({ to, onClose }: { to: FriendView; onClose: () => void }) {
  const config = useSession((s) => s.config)!;
  const rules = config.social.gifts;
  const [inv, setInv] = useState<InventoryView | null>(null);
  const [pick, setPick] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<InventoryView>("/api/inventory").then(setInv).catch(() => toast("Couldn't open your bag.", "bad"));
  }, []);
  const have = useMemo(() => {
    const out: Record<string, number> = {};
    for (const s of inv?.inventory.slots ?? []) {
      const d = config.items[s.item];
      if (!d?.stackable || d.category === "gear" || d.category === "cosmetic") continue;
      out[s.item] = (out[s.item] ?? 0) + s.qty;
    }
    return out;
  }, [inv, config]);
  const keys = Object.keys(pick).filter((k) => pick[k] > 0);
  const setQty = (k: string, q: number) => {
    const n = Math.max(0, Math.min(have[k] ?? 0, Math.floor(q)));
    if (n > 0 && !(k in pick) && keys.length >= rules.max_stacks) return toast(`Up to ${rules.max_stacks} kinds of thing per gift.`, "bad");
    setPick((p) => ({ ...p, [k]: n }));
  };
  const send = async () => {
    setBusy(true);
    try {
      const items = Object.fromEntries(keys.map((k) => [k, pick[k]]));
      await api("/api/social/gift", { method: "POST", body: { to: to.id, items } });
      sfx("deposit");
      toast(`Sent ${to.name} a gift! It's in their mailbox.`, "good", "gift");
      onClose();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "The courier dropped it. Try again?", "bad");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={`Gift for ${to.name}`} onClose={onClose}>
      <div className="col" style={{ gap: 8 }}>
        <span className="small muted">
          Materials, food and potions only. One gift per friend a day, worth up to about {rules.value_cap} coins.
        </span>
        {!inv ? <p>Opening your bag…</p> : Object.keys(have).length === 0 ? (
          <p className="small muted">Nothing giftable in your bag. Gather or craft something first!</p>
        ) : (
          <div className="col gift-list" style={{ gap: 4 }}>
            {Object.entries(have).map(([k, n]) => (
              <div key={k} className={`slot row gift-row ${pick[k] ? "picked" : ""}`} style={{ gap: 8 }}>
                <Icon name={itemIcon(k)} scale={2} />
                <span className="col grow" style={{ gap: 0 }}>
                  <span className="head">{itemName(k)}</span>
                  <span className="small muted">you have {n}</span>
                </span>
                <button className="btn small secondary icon-only" onClick={() => setQty(k, (pick[k] ?? 0) - 1)} aria-label={`One less ${itemName(k)}`}>−</button>
                <input className="qty-input" type="number" min={0} max={n} value={pick[k] ?? 0} aria-label={`${itemName(k)} to give`}
                  onChange={(e) => setQty(k, Number(e.target.value) || 0)} />
                <button className="btn small secondary icon-only" onClick={() => setQty(k, (pick[k] ?? 0) + 1)} aria-label={`One more ${itemName(k)}`}>+</button>
              </div>
            ))}
          </div>
        )}
        <button className="btn gold" disabled={busy || keys.length === 0} onClick={send}>
          <Icon name="gift" /> Send {keys.length ? `${keys.reduce((a, k) => a + pick[k], 0)} item${keys.reduce((a, k) => a + pick[k], 0) === 1 ? "" : "s"}` : "gift"}
        </button>
      </div>
    </Modal>
  );
}

// ── visiting ─────────────────────────────────────────────────────────────────

type Draw = { z: number; name: string; x: number; y: number; flip?: boolean };

function hash(x: number, y: number): number {
  let h = (x * 374761393 + y * 668265263) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return (h ^ (h >>> 16)) >>> 0;
}

/** 8-neighbour blob mask, the same as tools/artgen (a corner only counts when both its sides do). */
function blobMask(has: (x: number, y: number) => boolean, x: number, y: number): number {
  const N = has(x, y - 1), E = has(x + 1, y), S = has(x, y + 1), W = has(x - 1, y);
  let m = (N ? 1 : 0) | (E ? 4 : 0) | (S ? 16 : 0) | (W ? 64 : 0);
  if (N && E && has(x + 1, y - 1)) m |= 2;
  if (S && E && has(x + 1, y + 1)) m |= 8;
  if (S && W && has(x - 1, y + 1)) m |= 32;
  if (N && W && has(x - 1, y - 1)) m |= 128;
  return m;
}

/** Someone's village, drawn once into a canvas: grass, pond, paths, fence, buildings and wild growth. */
export function VillageCanvas({ v, highlight }: { v: VisitView["village"] | VillageState; highlight?: string | null }) {
  const config = useSession((s) => s.config)!;
  const ref = useRef<HTMLCanvasElement>(null);
  const [lo, hi] = usableBounds(v.frame, v.size);
  const x0 = lo - 2;
  const y0 = lo - 4;
  const cols = hi + 2 - x0;
  const rows = hi + 2 - y0;
  useEffect(() => {
    let alive = true;
    loadAtlasForDom().then(({ img, frames }) => {
      const c = ref.current;
      if (!alive || !c) return;
      const ctx = c.getContext("2d")!;
      ctx.imageSmoothingEnabled = false;
      const blit = (name: string, x: number, y: number, flip = false) => {
        const f = frames[name]?.frame;
        if (!f) return;
        const dx = Math.round(x - x0 * T);
        const dy = Math.round(y - y0 * T);
        if (flip) {
          ctx.save();
          ctx.translate(dx + f.w, dy);
          ctx.scale(-1, 1);
          ctx.drawImage(img, f.x, f.y, f.w, f.h, 0, 0, f.w, f.h);
          ctx.restore();
        } else ctx.drawImage(img, f.x, f.y, f.w, f.h, dx, dy, f.w, f.h);
      };
      // ground: grass everywhere, the pond on top
      for (let ty = y0; ty < y0 + rows; ty++) for (let tx = x0; tx < x0 + cols; tx++) blit(`tile.grass.${hash(tx, ty) % 4}`, tx * T, ty * T);
      const water = new Set<string>();
      for (const [wx, wy, ww, wh] of v.water) for (let y = wy; y < wy + wh; y++) for (let x = wx; x < wx + ww; x++) water.add(`${x},${y}`);
      const isWater = (x: number, y: number) => water.has(`${x},${y}`);
      for (const k of water) {
        const [x, y] = k.split(",").map(Number);
        const m = blobMask(isWater, x, y);
        blit(frames[`tile.water.${m}`] ? `tile.water.${m}` : "tile.water.255", x * T, y * T);
      }
      // flat paths first, then everything else back-to-front
      const flat: Draw[] = [];
      const objs: Draw[] = [];
      for (const b of v.buildings) {
        const def = config.buildings[b.key];
        if (!def) continue;
        const look = buildingLook(b.key, def.footprint as [number, number], b);
        const [, h] = rotatedFootprint(def.footprint as [number, number], b.rotation);
        const d = { z: (b.y + h) * T, name: look.name, x: b.x * T, y: b.y * T - look.anchorTop, flip: look.mirror };
        (def.walkable && b.key.startsWith("path") ? flat : objs).push(d);
      }
      for (const [, kind, variant, x, y] of v.debris) {
        const name = config.debris[kind]?.sprites[variant] ?? "obj.bush.0";
        const f = frames[name]?.frame;
        if (!f) continue;
        objs.push({ z: y * T + T - 1, name, x: x * T + T / 2 - f.w / 2, y: y * T + T - 1 - f.h });
      }
      // the fence, open at the gate (mirrors Game.drawFence)
      const [gx, gy, side] = v.gate;
      const gap = new Set(side === "N" || side === "S" ? [`${gx},${gy}`, `${gx + 1},${gy}`] : [`${gx},${gy}`, `${gx},${gy + 1}`]);
      const fh = (n: string) => frames[n]?.frame.h ?? 16;
      for (let x = lo - 1; x <= hi; x++) {
        for (const y of [lo - 1, hi]) {
          if (gap.has(`${x},${y}`)) continue;
          const wy = (y + 1) * T;
          const post = x === lo - 1 || x === hi;
          const n = post ? "obj.fence.post" : "obj.fence.h";
          objs.push({ z: wy - 1, name: n, x: x * T + (post ? 5 : 0), y: wy - 2 - fh(n) });
        }
      }
      for (let y = lo; y < hi; y++) {
        for (const x of [lo - 1, hi]) {
          if (gap.has(`${x},${y}`)) continue;
          const wy = (y + 1) * T;
          objs.push({ z: wy, name: "obj.fence.v", x: x * T + 5, y: wy + 2 - fh("obj.fence.v") });
        }
      }
      const posts = side === "N" || side === "S" ? [[gx - 1, gy], [gx + 2, gy]] : [[gx, gy - 1], [gx, gy + 2]];
      for (const [px, py] of posts) {
        const wy = (py + 1) * T;
        const f = frames["obj.fence.gate"]?.frame;
        objs.push({ z: wy + 1, name: "obj.fence.gate", x: px * T + 8 - (f?.w ?? 16) / 2, y: wy - (f?.h ?? 16) });
      }
      for (const d of flat) blit(d.name, d.x, d.y, d.flip);
      objs.sort((a, b) => a.z - b.z);
      for (const d of objs) blit(d.name, d.x, d.y, d.flip);
      // a soft ring under the building picked in the list
      const hb = highlight ? v.buildings.find((b) => b.id === highlight) : null;
      if (hb) {
        const def = config.buildings[hb.key];
        const [w, h] = rotatedFootprint(def.footprint as [number, number], hb.rotation);
        ctx.strokeStyle = "#f7d66a";
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 3]);
        ctx.strokeRect((hb.x - x0) * T + 1, (hb.y - y0) * T + 1, w * T - 2, h * T - 2);
      }
    });
    return () => {
      alive = false;
    };
  }, [v, config, highlight, lo, hi, x0, y0, cols, rows]);
  return (
    <div className="visit-canvas-wrap">
      <canvas ref={ref} width={cols * T} height={rows * T} className="pixel visit-canvas" style={{ aspectRatio: `${cols} / ${rows}` }}
        aria-label={`${v.name}, seen from above`} />
    </div>
  );
}

function VisitPanel({ ownerId }: { ownerId: string }) {
  const config = useSession((s) => s.config)!;
  const [vis, setVis] = useState<VisitView | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pick, setPick] = useState<string | null>(null);
  const [, force] = useState(0);
  const load = useCallback(async () => {
    try {
      setVis(await api<VisitView>(`/api/social/visit/${ownerId}`));
    } catch (e) {
      setFailed(e instanceof ApiError ? e.message : "Couldn't find the way there.");
    }
  }, [ownerId]);
  useEffect(() => {
    void load();
    const id = window.setInterval(() => force((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [load]);
  const back = () => useSocial.getState().set({ visiting: null });
  if (failed) {
    return (
      <div className="col" style={{ gap: 8 }}>
        <p>{failed}</p>
        <button className="btn secondary small" onClick={back}>Back</button>
      </div>
    );
  }
  if (!vis) return <p>Walking over…</p>;
  const now = serverNow();
  const working = vis.village.buildings
    .filter((b) => b.state !== "active" && (b.completes_at_ms ?? 0) > now)
    .sort((a, b) => (a.completes_at_ms ?? 0) - (b.completes_at_ms ?? 0));
  const like = async () => {
    setBusy(true);
    try {
      const r = await api<{ likes: number; counted: boolean }>(`/api/social/like/${ownerId}`, { method: "POST" });
      setVis({ ...vis, likes: r.likes, liked: true });
      sfx("like");
      toast(r.counted ? `You liked ${vis.village.name}!` : "Liked! It'll count once you're level 5 or your account is a day old.", "good", "heart");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
    } finally {
      setBusy(false);
    }
  };
  const help = async (id: string, name: string) => {
    setBusy(true);
    try {
      const r = await api<{ saved: number; coins: number }>("/api/social/help", { method: "POST", body: { building_id: id } });
      sfx("coin");
      toast(`You saved ${vis.owner.name} ${formatDuration(r.saved)} on the ${name}! +${r.coins} coins`, "good", "heart");
      await load();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="col visit" style={{ gap: 8 }}>
      <div className="row visit-head" style={{ gap: 10, flexWrap: "wrap" }}>
        <button className="btn secondary small" onClick={back} aria-label="Back to friends">←</button>
        <Face f={vis.owner} />
        <span className="col grow" style={{ gap: 0, minWidth: 0 }}>
          <span className="head" style={{ fontSize: 19 }}>{vis.village.name}</span>
          <span className="small muted row" style={{ gap: 6, flexWrap: "wrap" }}>
            {vis.owner.name} · level {vis.owner.level} <TitleTag title={vis.owner.title} /> · Town Hall {vis.village.town_hall_level}
            {" · "}{vis.village.villagers.length} villager{vis.village.villagers.length === 1 ? "" : "s"}
          </span>
        </span>
        <button className={`btn small ${vis.liked ? "secondary" : "gold"} like-btn`} disabled={busy || vis.liked || vis.mine} onClick={like}
          aria-pressed={vis.liked} title={vis.mine ? "Your own village" : vis.liked ? "You've liked this village" : "Like this village"}>
          <Icon name="heart" scale={1.5} /> {vis.likes} {vis.liked ? "Liked" : "Like"}
        </button>
      </div>
      <div className="visit-body">
      <VillageCanvas v={vis.village} highlight={pick} />
      <div className="col visit-side" style={{ gap: 4 }}>
        <span className="head small row" style={{ gap: 6 }}>
          <Icon name="build" scale={1} /> Building right now
          <span className="grow" />
          {!vis.mine && <span className="small muted">{vis.helps_left} help{vis.helps_left === 1 ? "" : "s"} left today</span>}
        </span>
        {working.length === 0 && <span className="small muted">Nothing under construction. Come back later to lend a hand!</span>}
        {working.map((b) => {
          const name = config.buildings[b.key]?.name ?? b.key;
          const helped = vis.helped_today.includes(b.id);
          const left = ((b.completes_at_ms ?? now) - now) / 1000;
          return (
            <div key={b.id} className={`slot row help-row ${pick === b.id ? "picked" : ""}`} style={{ gap: 8 }}
              onPointerEnter={() => setPick(b.id)} onPointerLeave={() => setPick(null)}>
              <Icon name={b.state === "upgrading" ? "upgrade" : "build"} scale={1.5} />
              <span className="col grow" style={{ gap: 0 }}>
                <span className="head">{name} {b.state === "upgrading" ? `→ level ${b.level + 1}` : ""}</span>
                <span className="small muted"><Icon name="timer" scale={1} /> {formatDuration(left)} left</span>
              </span>
              {!vis.mine && (
                <button className="btn small gold" disabled={busy || helped || vis.helps_left <= 0} onClick={() => help(b.id, name)}
                  title={helped ? "Someone already helped this one today" : `Take ${Math.round(config.social.help.cut * 100)}% off the time left`}>
                  {helped ? <><Icon name="check" scale={1.5} /> Helped</> : <><Icon name="heart" scale={1.5} /> Help</>}
                </button>
              )}
            </div>
          );
        })}
        {!vis.mine && (
          <span className="small muted" style={{ marginTop: 4 }}>
            Each help takes {Math.round(config.social.help.cut * 100)}% off the time left. One help per building a day, and you
            earn a few coins for it.
          </span>
        )}
      </div>
      </div>
    </div>
  );
}

// ── the panel ────────────────────────────────────────────────────────────────

type Tab = "friends" | "mail" | "blocked";

export function SocialPanel({ onClose }: { onClose: () => void }) {
  const view = useSocial((s) => s.view);
  const visiting = useSocial((s) => s.visiting);
  const fetch = useSocial((s) => s.fetch);
  const [tab, setTab] = useState<Tab>(() => (useSocial.getState().view?.mail.length ? "mail" : "friends"));
  const [gift, setGift] = useState<FriendView | null>(null);
  useEffect(() => {
    void fetch();
  }, [fetch]);
  const tabs: { key: Tab; label: string; icon: string; dot: number }[] = [
    { key: "friends", label: "Friends", icon: "party", dot: view?.incoming.length ?? 0 },
    { key: "mail", label: "Mail", icon: "mail", dot: view?.mail.length ?? 0 },
    { key: "blocked", label: "Blocked", icon: "lock", dot: 0 },
  ];
  return (
    <Modal title={visiting ? "Visiting" : "Friends"} onClose={onClose} wide>
      {visiting ? (
        <VisitPanel ownerId={visiting} />
      ) : (
        <>
          <div className="row tabs" role="tablist" style={{ gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
            {tabs.map((t) => (
              <button key={t.key} role="tab" aria-selected={tab === t.key} className={`btn small ${tab === t.key ? "" : "secondary"}`} onClick={() => setTab(t.key)}>
                <Icon name={t.icon} scale={1.5} /> {t.label}
                {t.dot > 0 && <span className="dot-count">{t.dot}</span>}
              </button>
            ))}
          </div>
          {!view ? <p>Asking around…</p> : tab === "friends" ? <FriendsTab onGift={setGift} /> : tab === "mail" ? <MailTab /> : <BlockedTab />}
        </>
      )}
      {gift && <GiftDialog to={gift} onClose={() => setGift(null)} />}
    </Modal>
  );
}

// ── Avatar Mode: emotes and quick messages (T) ───────────────────────────────

export function ChatWheel({ touch }: { touch: boolean }) {
  const open = useSocial((s) => s.chatOpen);
  const config = useSession((s) => s.config)!;
  if (!open) return null;
  const say = (kind: "emote" | "say", key: string | number) => {
    roomLink.send?.("SOCIAL", kind, key);
    useSocial.getState().set({ chatOpen: false });
  };
  return (
    <div className="panel chat-wheel" role="dialog" aria-label="Emotes and quick messages">
      <div className="row" style={{ gap: 6, marginBottom: 6 }}>
        <span className="head small">Say something</span>
        <span className="grow" />
        {!touch && <span className="small muted">T to close</span>}
        <button className="btn danger small icon-only" onClick={() => useSocial.getState().set({ chatOpen: false })} aria-label="Close">
          <Icon name="close" scale={1.5} />
        </button>
      </div>
      <div className="row emote-row" style={{ gap: 4, flexWrap: "wrap" }}>
        {config.social.emotes.map((e) => (
          <button key={e} className="btn secondary small icon-only emote-btn" onClick={() => say("emote", e)} aria-label={e} title={e}>
            <Icon name={`emote_${e}`} scale={2} />
          </button>
        ))}
      </div>
      <div className="quick-grid">
        {config.social.quick.map((q, i) => (
          <button key={q} className="btn secondary small" onClick={() => say("say", i)}>{q}</button>
        ))}
      </div>
    </div>
  );
}

export function FriendsButton() {
  const view = useSocial((s) => s.view);
  const n = socialDot(view);
  return (
    <button className="btn secondary icon-only has-dot" onClick={() => useSocial.getState().set({ open: true, visiting: null })}
      aria-label={`Friends and mail${n ? ` (${n} new)` : ""}`} title="Friends and mail">
      <Icon name="party" />
      {n > 0 && <span className="dot-count">{n}</span>}
    </button>
  );
}

/** Keeps the HUD dots honest: friends/mail and the journal, on load, on a slow poll and on focus. */
export function useSocialSync(): void {
  useEffect(() => {
    const load = () => {
      void useSocial.getState().fetch();
      void useJournal.getState().fetch();
    };
    load();
    const id = window.setInterval(load, 90_000);
    window.addEventListener("focus", load);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", load);
    };
  }, []);
}
