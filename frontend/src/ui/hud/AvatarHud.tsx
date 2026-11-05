import { useEffect, useRef, useState } from "react";
import { leaveAvatar, roomLink } from "../../net/room";
import { touchInput } from "../../net/touch";
import { BTN } from "../../sim/motion";
import { useAvatar } from "../../state/avatar";
import { useSession } from "../../state/session";
import { itemIcon } from "../../game/items";
import { formatDuration, Icon } from "../components/kit";
import { Bag } from "./Bag";
import { TradePrompt } from "./Market";
import { BlessingChip, LoreModal, PoiPrompt, WildMerchantPanel } from "./Poi";
import { WorldChip } from "./WorldChip";
import { MiniMap, WaystonePrompt } from "./WorldMap";
import { PartyButton, PartyFrames } from "./Party";
import { useTutorial } from "../../state/tutorial";

const KO_FLAG = 2;

function Bar({ value, max, color, label, height = 14 }: { value: number; max: number; color: string; label?: string; height?: number }) {
  const pct = Math.max(0, Math.min(1, max > 0 ? value / max : 0));
  return (
    <div className="av-bar" style={{ height }} role="meter" aria-valuenow={Math.round(value)} aria-valuemax={max} aria-label={label}>
      <div className="av-bar-fill" style={{ width: `${pct * 100}%`, background: color }} />
      {label && <span className="av-bar-text">{label}</span>}
    </div>
  );
}

function Status() {
  const hp = useAvatar((s) => s.hp);
  const hpMax = useAvatar((s) => s.hpMax);
  const st = useAvatar((s) => s.st);
  const stMax = useAvatar((s) => s.stMax);
  const level = useAvatar((s) => s.level);
  const xp = useAvatar((s) => s.xp);
  const xpNext = useAvatar((s) => s.xpNext);
  const name = useSession((s) => s.me?.user.username);
  const low = hp / hpMax < 0.3;
  return (
    <div className="hud-bar av-status">
      <div className="row" style={{ gap: 8, alignItems: "center" }}>
        <span className="av-level head" title={`Level ${level}`}>{level}</span>
        <span className="head av-name">{name}</span>
      </div>
      <div className={low ? "av-low" : undefined}>
        <Bar value={hp} max={hpMax} color="linear-gradient(#e2735a, #ad433b)" label={`${Math.ceil(hp)} / ${hpMax}`} height={16} />
      </div>
      <Bar value={st} max={stMax} color="linear-gradient(#bfe08a, #64aa4c)" height={8} />
      <Bar value={xp} max={xpNext} color="linear-gradient(#94cdeb, #3b80ba)" height={6} />
    </div>
  );
}

function Cooldown({ left, max }: { left: number; max: number }) {
  if (left <= 0 || max <= 0) return null;
  const pct = Math.min(1, left / max);
  return <span className="av-cd" style={{ height: `${pct * 100}%` }} aria-hidden />;
}

const ABILITY_ICON: Record<string, string> = {
  spin: "rotate", throw: "spear", circle: "build", shot: "star", starfall: "star", barrier: "crystal",
};

function weaponIcons(weapon: { key: string | null; type: string; tier: number }) {
  const config = useSession.getState().config!;
  const base = weapon.key ? itemIcon(weapon.key, weapon.tier) : weapon.type === "spear" ? "spear" : "sword";
  const kind = config.combat?.weapons[weapon.type]?.ability ?? "spin";
  const ability = kind === "throw" || kind === "shot" ? base : ABILITY_ICON[kind] ?? "rotate";
  const name: Record<string, string> = {
    spin: "Spin attack", throw: "Spear throw", circle: "Ground ability", shot: "Volley", starfall: "Starfall", barrier: "Crystal barrier",
  };
  return { base, ability, abilityName: name[kind] ?? "Skill" };
}

/** Seconds-left overlay for things timed in wall-clock ms (offhand, quick-slot groups). */
function MsCooldown({ until, total }: { until: number; total: number }) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (until <= performance.now()) return;
    const id = window.setInterval(() => tick((n) => n + 1), 200);
    return () => window.clearInterval(id);
  }, [until]);
  const left = until - performance.now();
  if (left <= 0 || total <= 0) return null;
  return <span className="av-cd" style={{ height: `${Math.min(1, left / total) * 100}%` }} aria-hidden />;
}

function useOffhand() {
  const off = useAvatar((s) => s.offhand);
  const config = useSession((s) => s.config)!;
  if (!off.type) return null;
  const icon = off.type === "shield" ? "shield" : off.type === "bombs" ? "bomb" : "tome";
  const label = off.type === "shield" ? "Hold to block" : off.type === "bombs" ? "Throw a bomb" : "Cast a spell";
  const total = (off.type === "bombs" ? config.combat.offhands.bombs.recharge_s : config.combat.offhands.tome.cooldown_s) * 1000;
  return { ...off, icon, label, total };
}

function QuickSlots({ touch }: { touch: boolean }) {
  const quick = useAvatar((s) => s.quick);
  const config = useSession((s) => s.config)!;
  return (
    <>
      {[0, 1, 2, 3].map((i) => {
        const q = quick[String(4 + i)];
        const it = q ? config.items[q[0]] : undefined;
        if (touch && !q) return null;
        return (
          <button key={i} className={`av-slot quick ${q ? "" : "empty"}`} title={it ? `${it.name} (${i + 1})` : `Quick-slot ${i + 1}: drag a potion or food here in your bag`}
            onClick={() => q && roomLink.client?.useQuick(i)} aria-label={it ? `Use ${it.name}` : `Empty quick-slot ${i + 1}`}>
            {q ? <Icon name={itemIcon(q[0])} scale={touch ? 1.5 : 2} /> : <span className="small muted">+</span>}
            {!touch && <span className="av-key">{i + 1}</span>}
            {q && <span className="av-count">{q[1]}</span>}
          </button>
        );
      })}
    </>
  );
}

function Hotbar({ touch }: { touch: boolean }) {
  const weapon = useAvatar((s) => s.weapon);
  const abCd = useAvatar((s) => s.abCd);
  const abCdMax = useAvatar((s) => s.abCdMax);
  const dodgeCd = useAvatar((s) => s.dodgeCd);
  const off = useOffhand();
  if (touch) return null;
  const { base, ability, abilityName } = weaponIcons(weapon);
  const slot = (key: string, icon: string, label: string, hint: string, extra?: React.ReactNode) => (
    <div className="av-slot" key={key} title={label}>
      <Icon name={icon} scale={2} />
      <span className="av-key">{hint}</span>
      {extra}
    </div>
  );
  return (
    <div className="hud-bar av-hotbar" role="toolbar" aria-label="Actions">
      {slot("light", base, "Attack / gather", "LMB")}
      {slot("heavy", base, "Heavy attack (stamina)", "RMB", <span className="av-tag">!!</span>)}
      {slot("ability", ability, abilityName, "Q", <Cooldown left={abCd} max={abCdMax} />)}
      {slot("dodge", "move", "Dodge roll", "SPACE", <Cooldown left={dodgeCd} max={13} />)}
      {off && slot("offhand", off.icon, off.label, "F", <>
        {off.type === "bombs" && <span className="av-count">{off.charges}</span>}
        {off.type !== "shield" && <MsCooldown until={off.readyAt} total={off.total} />}
      </>)}
      <span className="av-sep" aria-hidden />
      <QuickSlots touch={false} />
    </div>
  );
}

/** Food and stamina buffs, under the minimap. */
export function BuffChips() {
  const buffs = useAvatar((s) => s.buffs);
  const config = useSession((s) => s.config);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!buffs.length) return;
    const id = window.setInterval(() => {
      tick((n) => n + 1);
      const now = performance.now();
      if (buffs.some((b) => b.until <= now)) useAvatar.getState().set({ buffs: buffs.filter((b) => b.until > now) });
    }, 1000);
    return () => window.clearInterval(id);
  }, [buffs]);
  const now = performance.now();
  return (
    <>
      {buffs.filter((b) => b.until > now).map((b) => (
        <div key={b.key + b.kind} className="blessing-chip buff-chip" title={config?.items[b.key]?.name}>
          <Icon name={itemIcon(b.key)} scale={1.5} />
          <span className="small">
            <b>{b.kind === "stamina" ? "Second wind" : `+${Math.round(b.value * 100)}% ${b.kind}`}</b> · {formatDuration((b.until - now) / 1000)}
          </span>
        </div>
      ))}
    </>
  );
}

function Stick() {
  const base = useRef<HTMLDivElement>(null);
  const [knob, setKnob] = useState({ x: 0, y: 0 });
  const id = useRef<number | null>(null);
  const update = (e: React.PointerEvent) => {
    const r = base.current!.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const max = r.width / 2;
    let dx = (e.clientX - cx) / max;
    let dy = (e.clientY - cy) / max;
    const l = Math.hypot(dx, dy);
    if (l > 1) {
      dx /= l;
      dy /= l;
    }
    const dead = l < 0.18;
    touchInput.active = true;
    touchInput.mx = dead ? 0 : dx;
    touchInput.my = dead ? 0 : dy;
    setKnob({ x: dx * max * 0.6, y: dy * max * 0.6 });
  };
  const end = () => {
    id.current = null;
    touchInput.active = false;
    touchInput.mx = touchInput.my = 0;
    setKnob({ x: 0, y: 0 });
  };
  return (
    <div ref={base} className="av-stick" aria-label="Move"
      onPointerDown={(e) => {
        id.current = e.pointerId;
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        update(e);
      }}
      onPointerMove={(e) => id.current === e.pointerId && update(e)}
      onPointerUp={end} onPointerCancel={end}>
      <div className="av-knob" style={{ transform: `translate(${knob.x}px, ${knob.y}px)` }} />
    </div>
  );
}

function TouchButton({ label, icon, bit, hold, big, extra }: { label: string; icon: string; bit: number; hold?: boolean; big?: boolean; extra?: React.ReactNode }) {
  return (
    <button className={`av-tbtn ${big ? "big" : ""}`} aria-label={label}
      onPointerDown={(e) => {
        e.preventDefault();
        try {
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
        } catch {
          /* synthetic events (tests) have no live pointer */
        }
        touchInput.latched |= bit;
        if (hold) touchInput.held |= bit;
      }}
      onPointerUp={() => void (touchInput.held &= ~bit)}
      onPointerCancel={() => void (touchInput.held &= ~bit)}>
      <Icon name={icon} scale={big ? 3 : 2} />
      {extra}
    </button>
  );
}

function TouchControls() {
  const weapon = useAvatar((s) => s.weapon);
  const abCd = useAvatar((s) => s.abCd);
  const abCdMax = useAvatar((s) => s.abCdMax);
  const off = useOffhand();
  const { base, ability } = weaponIcons(weapon);
  return (
    <>
      <Stick />
      <div className="av-tbtns">
        <TouchButton label="Attack" icon={base} bit={BTN.light} hold big />
        <TouchButton label="Dodge" icon="move" bit={BTN.dodge} />
        <TouchButton label="Heavy attack" icon={base} bit={BTN.heavy} extra={<span className="av-tag">!!</span>} />
        <TouchButton label="Skill" icon={ability} bit={BTN.ability} extra={<Cooldown left={abCd} max={abCdMax} />} />
        {off && <TouchButton label={off.label} icon={off.icon} bit={BTN.offhand} hold={off.type === "shield"}
          extra={off.type === "bombs" ? <span className="av-count">{off.charges}</span> : off.type === "tome" ? <MsCooldown until={off.readyAt} total={off.total} /> : undefined} />}
      </div>
      <div className="av-quick-touch"><QuickSlots touch /></div>
    </>
  );
}

function FirstHint({ touch }: { touch: boolean }) {
  const tutorial = useTutorial((s) => s.tut?.active);
  return tutorial ? null : <FirstHintInner touch={touch} />;
}

function FirstHintInner({ touch }: { touch: boolean }) {
  const [show, setShow] = useState(() => {
    try {
      return localStorage.getItem("hf.hint.avatar") !== "1";
    } catch {
      return true;
    }
  });
  useEffect(() => {
    if (!show) return;
    const t = window.setTimeout(() => {
      setShow(false);
      try {
        localStorage.setItem("hf.hint.avatar", "1");
      } catch {
        /* fine */
      }
    }, 14000);
    return () => window.clearTimeout(t);
  }, [show]);
  if (!show) return null;
  return (
    <div className="hud-hint hud-bar small av-hint">
      <Icon name="info" scale={1.5} />
      {touch
        ? "Drag the stick to walk, tap the sword to chop trees and fight. Walk home to store what you gather."
        : "WASD to walk · click to swing (chop trees, break rocks) · Space to dodge · walk home to store your haul."}
    </div>
  );
}

export function AvatarHud({ touch, onSettings }: { touch: boolean; onSettings: () => void }) {
  const mode = useAvatar((s) => s.mode);
  const bagOpen = useAvatar((s) => s.bagOpen);
  const flags = useAvatar((s) => s.flags);
  const inCombat = useAvatar((s) => s.inCombat);
  const inv = useAvatar((s) => s.inv);
  const set = useAvatar((s) => s.set);
  const carrying = inv.filter((s) => useSession.getState().config?.resources[s[1]]).reduce((n, s) => n + s[2], 0);
  if (mode === "entering") {
    return <div className="hud"><div className="center grow"><div className="hud-bar head">Stepping outside…</div></div></div>;
  }
  return (
    <div className="hud av-hud">
      <div className="hud-top">
        <Status />
        <div className="row" style={{ gap: 6 }}>
          {carrying > 0 && (
            <span className="hud-bar hud-chip" title="Resources you're carrying: walk home to store them">
              <Icon name="wood" scale={1.5} /> {carrying}
            </span>
          )}
          <PartyButton />
          <button className="btn secondary icon-only" onClick={() => set({ bagOpen: !bagOpen })} aria-label="Bag" title="Bag (B)">
            <Icon name="queue" />
          </button>
          <button className="btn gold" onClick={leaveAvatar} disabled={inCombat || mode === "leaving"} aria-label="Back to village" data-tut-target="home"
            title={inCombat ? "Not while fighting!" : "Back to Build Mode (H)"}>
            <Icon name="home" /> <span className="hide-narrow">Village</span>
          </button>
          <button className="btn secondary icon-only" onClick={onSettings} aria-label="Settings">
            <Icon name="settings" />
          </button>
        </div>
      </div>
      <FirstHint touch={touch} />
      {(flags & KO_FLAG) !== 0 && (
        <div className="av-ko center"><div className="panel head" style={{ fontSize: 24 }}>Knocked out! Waking up at home…</div></div>
      )}
      <div className="minimap-slot"><MiniMap small={touch} /><WorldChip /><BlessingChip /><BuffChips /></div>
      <PartyFrames />
      <div className="hud-bottom">
        <TradePrompt touch={touch} />
        <WaystonePrompt touch={touch} />
        <PoiPrompt touch={touch} />
        <Hotbar touch={touch} />
      </div>
      {touch && <TouchControls />}
      {bagOpen && <Bag onClose={() => set({ bagOpen: false })} />}
      <LoreModal />
      <WildMerchantPanel />
    </div>
  );
}
