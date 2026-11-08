// Phase 16b: pets and mounts (Journal tab), the Trophy Hall (Journal tab), the fishing prompt and timing
// bar (Avatar Mode), the ride button, and photo mode.
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { gameLink } from "../../game/Game";
import { sfx } from "../../game/sfx";
import { reelNow, roomLink } from "../../net/room";
import { useAvatar } from "../../state/avatar";
import { useCompanions, useFishing, type MountView, type PetView } from "../../state/companions";
import { useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { useVillage } from "../../state/village";
import { Icon } from "../components/kit";
import { SpriteThumb } from "../components/SpriteThumb";

const PERK_TEXT: Record<string, (v: number) => string> = {
  gather_yield: (v) => `+${Math.round(v * 100)}% gathering`,
  rare_odds: (v) => `+${Math.round(v * 100)}% rare finds`,
  coins: (v) => `+${Math.round(v * 100)}% monster coins`,
  defence: (v) => `+${v} defence`,
  damage: (v) => `+${Math.round(v * 100)}% damage`,
};

function Meter({ value, max }: { value: number; max: number }) {
  return (
    <span className="meter" role="meter" aria-valuenow={value} aria-valuemax={max}>
      <span style={{ width: `${Math.min(1, value / Math.max(1, max)) * 100}%`, background: "var(--gold)" }} />
    </span>
  );
}

// ── pets and mounts ──────────────────────────────────────────────────────────

function PetCard({ p, tokens }: { p: PetView; tokens: number }) {
  const act = useCompanions((s) => s.act);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState(p.nickname ?? "");
  const ready = p.unlock ? p.unlock.progress >= p.unlock.target : tokens >= (p.cost?.tokens ?? 0);
  const adopt = async () => {
    if (await act("/api/companions/pets/adopt", { key: p.key })) {
      sfx("fanfare");
      toast(`${p.name} is coming home with you!`, "good", "paw");
    }
  };
  return (
    <div className={`slot pet-card col ${p.active ? "active" : ""} ${p.owned ? "" : "unowned"}`}>
      <div className="row" style={{ gap: 8 }}>
        <span className="pet-thumb"><SpriteThumb name={`pet.${p.key}.idle.0`} box={56} maxScale={3} silhouette={!p.owned && !ready} /></span>
        <span className="col grow" style={{ gap: 1, minWidth: 0 }}>
          <span className="head">{p.nickname ?? p.name}</span>
          {p.nickname && <span className="small muted">{p.name}</span>}
          <span className="small perk">{Object.entries(p.perks).map(([k, v]) => PERK_TEXT[k]?.(v) ?? k).join(" · ")}</span>
        </span>
      </div>
      <span className="small">{p.desc}</span>
      {p.owned ? (
        naming ? (
          <form className="row" style={{ gap: 4 }} onSubmit={async (e) => {
            e.preventDefault();
            if (await act("/api/companions/pets/rename", { key: p.key, name: name.trim() || null })) setNaming(false);
          }}>
            <input className="qty-input wide-input grow" value={name} maxLength={16} placeholder={p.name} aria-label="Pet's name"
              onChange={(e) => setName(e.target.value)} />
            <button className="btn small" type="submit">Save</button>
          </form>
        ) : (
          <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
            {p.active ? (
              <button className="btn small secondary" onClick={() => act("/api/companions/pets/active", { key: null })}>Leave at home</button>
            ) : (
              <button className="btn small gold" onClick={() => act("/api/companions/pets/active", { key: p.key })}>
                <Icon name="paw" scale={1} /> Bring along
              </button>
            )}
            <button className="btn small secondary" onClick={() => setNaming(true)}>Name</button>
            {p.active && <span className="small tag gold">with you</span>}
          </div>
        )
      ) : p.unlock ? (
        <div className="col" style={{ gap: 3 }}>
          <span className="small muted">{p.unlock.hint} · {p.unlock.progress.toLocaleString()} / {p.unlock.target.toLocaleString()}</span>
          <Meter value={p.unlock.progress} max={p.unlock.target} />
          <button className="btn small gold" disabled={!ready} onClick={adopt}>{ready ? "Take home" : <><Icon name="lock" scale={1} /> Not yet</>}</button>
        </div>
      ) : (
        <button className="btn small gold" disabled={!ready} onClick={adopt}>
          Adopt for {p.cost?.tokens} token{p.cost?.tokens === 1 ? "" : "s"}
        </button>
      )}
    </div>
  );
}

function MountCard({ m, tokens, coins }: { m: MountView; tokens: number; coins: number }) {
  const act = useCompanions((s) => s.act);
  const afford = coins >= m.cost.coins && tokens >= m.cost.tokens;
  const price = [m.cost.coins ? `${m.cost.coins.toLocaleString()} coins` : "", m.cost.tokens ? `${m.cost.tokens} tokens` : ""].filter(Boolean).join(" + ");
  return (
    <div className={`slot pet-card mount-card col ${m.active ? "active" : ""} ${m.owned ? "" : "unowned"}`}>
      <div className="row" style={{ gap: 8 }}>
        <span className="pet-thumb"><SpriteThumb name={`mount.${m.key}.idle.0`} box={72} maxScale={2} silhouette={m.locked && !m.owned} /></span>
        <span className="col grow" style={{ gap: 1 }}>
          <span className="head">{m.name}</span>
          <span className="small perk">{Math.round((m.speed - 1) * 100)}% faster</span>
        </span>
      </div>
      <span className="small">{m.desc}</span>
      {m.owned ? (
        m.active ? (
          <span className="small"><span className="tag gold">your ride</span> Press <b>G</b> in the world to climb on.</span>
        ) : (
          <button className="btn small gold" onClick={() => act("/api/companions/mounts/active", { key: m.key })}>
            <Icon name="saddle" scale={1} /> Ride this one
          </button>
        )
      ) : m.locked ? (
        <span className="small muted"><Icon name="lock" scale={1} /> Needs a level {m.town_hall} Town Hall · {price}</span>
      ) : (
        <button className="btn small gold" disabled={!afford} onClick={async () => {
          if (await act("/api/companions/mounts/buy", { key: m.key })) {
            sfx("fanfare");
            toast(`The ${m.name} is yours! Press G in the world to ride.`, "good", "saddle");
            void useVillage.getState().fetch().catch(() => undefined);
          }
        }}>Buy for {price}</button>
      )}
    </div>
  );
}

export function CompanionsTab() {
  const view = useCompanions((s) => s.view);
  const fetch = useCompanions((s) => s.fetch);
  useEffect(() => {
    void fetch();
  }, [fetch]);
  if (!view) return <p>Calling them over…</p>;
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="row small" style={{ gap: 12, flexWrap: "wrap" }}>
        <span><Icon name="star" scale={1} /> <b>{view.tokens}</b> cosmetic token{view.tokens === 1 ? "" : "s"} (from weekly quests and the calendar)</span>
        <span><Icon name="coins" scale={1} /> <b>{view.coins.toLocaleString()}</b></span>
      </div>
      <span className="head"><Icon name="paw" scale={1.5} /> Pets <span className="small muted">one comes along at a time; each gives a small bonus</span></span>
      <div className="pet-grid">{view.pets.map((p) => <PetCard key={p.key} p={p} tokens={view.tokens} />)}</div>
      <span className="head"><Icon name="saddle" scale={1.5} /> Mounts <span className="small muted">ride with G; you hop off to fight, fish or delve</span></span>
      <div className="pet-grid">{view.mounts.map((m) => <MountCard key={m.key} m={m} tokens={view.tokens} coins={view.coins} />)}</div>
    </div>
  );
}

// ── the Trophy Hall ──────────────────────────────────────────────────────────

interface HallView {
  bosses: { key: string; name: string; enemy: string; trophy: string; trophy_name: string; icon: string; kills: number }[];
  fish: { key: string; name: string; rarity: string; caught: number; best_g: number; max_g: number }[];
  totals: Record<string, number>;
}

const TOTALS: [string, string][] = [
  ["kill.any", "monsters defeated"],
  ["kill.realm_boss", "realm bosses"],
  ["delve.cleared", "delves cleared"],
  ["wave.won", "raids beaten"],
  ["fish.any", "fish caught"],
  ["fish.legendary", "legendary fish"],
  ["forge.epic_plus", "Epic+ forged"],
  ["help.given", "neighbours helped"],
];

const kg = (g: number) => (g >= 1000 ? `${(g / 1000).toFixed(g >= 10000 ? 0 : 1)} kg` : `${g} g`);

export function TrophyHallTab() {
  const [h, setH] = useState<HallView | null>(null);
  useEffect(() => {
    api<HallView>("/api/companions/trophies").then(setH).catch(() => toast("The hall is locked for a moment.", "bad"));
  }, []);
  if (!h) return <p>Dusting the shelves…</p>;
  const caught = h.fish.filter((f) => f.caught > 0);
  return (
    <div className="col trophy-hall" style={{ gap: 10 }}>
      <div className="totals-row">
        {TOTALS.map(([k, label]) => (
          <span key={k} className="slot total-chip col"><b className="head">{(h.totals[k] ?? 0).toLocaleString()}</b><span className="small muted">{label}</span></span>
        ))}
      </div>
      <span className="head"><Icon name="trophy" scale={1.5} /> Boss trophies</span>
      <div className="shelf trophy-shelf">
        {h.bosses.map((b) => (
          <div key={b.key} className={`slot shelf-cell col ${b.kills ? "" : "unknown"}`} title={b.kills ? `${b.name}: defeated ${b.kills}×` : `Help defeat ${b.name}`}>
            <span style={{ opacity: b.kills ? 1 : 0.25, filter: b.kills ? undefined : "brightness(0)" }}><Icon name={b.icon.replace(/^icon\./, "")} scale={3} /></span>
            <span className="small shelf-name">{b.kills ? b.trophy_name : "???"}</span>
            <span className="small muted">{b.kills ? `${b.name} ×${b.kills}` : b.name}</span>
          </div>
        ))}
      </div>
      <span className="head"><Icon name="rod" scale={1.5} /> Biggest catches <span className="small muted">{caught.length} of {h.fish.length} species</span></span>
      {caught.length === 0 && <span className="small muted">No fish yet. Stand by water in the world and press E to cast.</span>}
      <div className="col" style={{ gap: 3 }}>
        {caught.sort((a, b) => b.best_g / b.max_g - a.best_g / a.max_g).map((f) => (
          <div key={f.key} className={`slot row record-row rarity-${f.rarity}`} style={{ gap: 8 }}>
            <Icon name={`fish_${f.key}`} scale={2} />
            <span className="col grow" style={{ gap: 2, minWidth: 0 }}>
              <span className="row" style={{ gap: 6 }}>
                <span className="head">{f.name}</span>
                <span className="small muted">{f.rarity} · caught {f.caught}</span>
                <span className="grow" />
                <b className="head">{kg(f.best_g)}</b>
              </span>
              <Meter value={f.best_g} max={f.max_g} />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Avatar Mode: fishing, riding ─────────────────────────────────────────────

/** "E · Fish" while you're on a bank and not already fishing. */
export function FishPrompt({ touch }: { touch: boolean }) {
  const phase = useFishing((s) => s.phase);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const id = window.setInterval(() => setNear(Boolean(gameLink.game?.nearFishable())), 300);
    return () => window.clearInterval(id);
  }, []);
  if (phase !== "idle" || !near) return phase === "waiting" ? <div className="hud-bar small fish-wait"><Icon name="rod" scale={1.5} /> Waiting for a bite…</div> : null;
  return (
    <button className="btn gold trade-prompt" onClick={() => roomLink.send?.("FISH", "cast")}>
      <Icon name="rod" /> {touch ? "Fish" : <><span className="av-key">E</span> Fish</>}
    </button>
  );
}

/** The timing bar: a marker sweeps once; press when it's in the gold zone. */
export function FishingBar({ touch }: { touch: boolean }) {
  const f = useFishing();
  const marker = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (f.phase !== "bite") return;
    let raf = 0;
    const step = () => {
      const t = performance.now() - f.shownAt;
      if (marker.current) marker.current.style.left = `${Math.min(100, (t / f.barMs) * 100)}%`;
      if (t < f.barMs + 200) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [f.phase, f.shownAt, f.barMs]);
  if (f.phase !== "bite") return null;
  const zl = ((f.centerMs - f.windowMs / 2) / f.barMs) * 100;
  const zw = (f.windowMs / f.barMs) * 100;
  return (
    <div className={`panel fish-bar rarity-${f.rarity}`} role="dialog" aria-label="Something's biting!">
      <span className="head">Something's biting! <span className="small muted">{touch ? "Tap Reel when the marker hits gold" : "Press E or Space in the gold"}</span></span>
      <div className="fish-track" onPointerDown={() => reelNow()}>
        <span className="fish-zone" style={{ left: `${zl}%`, width: `${zw}%` }} />
        <span ref={marker} className="fish-marker" />
      </div>
      {touch && <button className="btn gold" onPointerDown={() => reelNow()}><Icon name="rod" /> Reel!</button>}
    </div>
  );
}

/** Climb on or off (G). Only shows once you own a mount. */
export function RideButton() {
  const view = useCompanions((s) => s.view);
  const riding = useAvatar((s) => s.riding);
  const fetch = useCompanions((s) => s.fetch);
  useEffect(() => {
    if (!view) void fetch();
  }, [view, fetch]);
  const mount = view?.mounts.find((m) => m.active);
  if (!mount) return null;
  return (
    <button className={`btn ${riding ? "gold" : "secondary"} icon-only`} onClick={() => roomLink.send?.("RIDE")}
      aria-label={riding ? `Get off the ${mount.name}` : `Ride the ${mount.name}`} aria-pressed={riding} title={`${riding ? "Get off" : "Ride"} (G)`}>
      <Icon name="saddle" />
    </button>
  );
}

// ── photo mode ───────────────────────────────────────────────────────────────

const FILTERS: { key: string; label: string; css: string }[] = [
  { key: "none", label: "Natural", css: "none" },
  { key: "warm", label: "Golden", css: "sepia(0.25) saturate(1.25) brightness(1.05)" },
  { key: "dusk", label: "Dusk", css: "hue-rotate(-12deg) saturate(1.1) brightness(0.92) contrast(1.05)" },
  { key: "sepia", label: "Old map", css: "sepia(0.85) contrast(1.05)" },
  { key: "mono", label: "Ink", css: "grayscale(1) contrast(1.15)" },
];

export function PhotoBar() {
  const photo = useAvatar((s) => s.photo);
  const [filter, setFilter] = useState("none");
  const [names, setNames] = useState(true);
  const [frame, setFrame] = useState(true);
  const css = FILTERS.find((x) => x.key === filter)!.css;
  useEffect(() => {
    const el = document.querySelector<HTMLElement>(".game-canvas");
    if (!photo || !el) return;
    el.style.filter = css === "none" ? "" : css;
    gameLink.game?.setNames(names);
    return () => {
      el.style.filter = "";
      gameLink.game?.setNames(true);
    };
  }, [photo, css, names]);
  if (!photo) return null;
  const save = () => {
    const g = gameLink.game;
    if (!g) return;
    const src = g.snapshot();
    const pad = frame ? Math.round(Math.min(src.width, src.height) * 0.025) : 0;
    const out = document.createElement("canvas");
    out.width = src.width + pad * 2;
    out.height = src.height + pad * 2 + (frame ? pad * 2 : 0);
    const ctx = out.getContext("2d")!;
    if (frame) {
      ctx.fillStyle = "#faf2dd";
      ctx.fillRect(0, 0, out.width, out.height);
    }
    ctx.filter = css;
    ctx.drawImage(src, pad, pad);
    ctx.filter = "none";
    if (frame) {
      ctx.fillStyle = "#4a3a46";
      ctx.font = `600 ${Math.max(14, pad)}px 'Pixelify Sans', sans-serif`;
      const v = useVillage.getState().village;
      ctx.fillText(`${v?.name ?? "Hearthforge"} · ${new Date().toLocaleDateString()}`, pad, out.height - pad);
    }
    out.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `hearthforge-${Date.now()}.png`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      sfx("shimmer");
      toast("Snap! Saved to your downloads.", "good", "camera");
    }, "image/png");
  };
  const name = useSession.getState().me?.user.username;
  return (
    <div className="photo-bar panel row" role="toolbar" aria-label="Photo mode">
      <span className="head"><Icon name="camera" scale={1.5} /> Photo</span>
      <span className="row photo-filters" style={{ gap: 4, flexWrap: "wrap" }}>
        {FILTERS.map((x) => (
          <button key={x.key} className={`btn small ${filter === x.key ? "" : "secondary"}`} onClick={() => setFilter(x.key)}>{x.label}</button>
        ))}
      </span>
      <label className="small row" style={{ gap: 4 }}><input type="checkbox" checked={names} onChange={(e) => setNames(e.target.checked)} /> names</label>
      <label className="small row" style={{ gap: 4 }}><input type="checkbox" checked={frame} onChange={(e) => setFrame(e.target.checked)} /> frame</label>
      <button className="btn gold small" onClick={save} title={name ? `Save a picture of ${name}'s world` : "Save"}><Icon name="camera" scale={1.5} /> Save</button>
      <button className="btn danger small" onClick={() => useAvatar.getState().set({ photo: false })}>Done</button>
    </div>
  );
}
