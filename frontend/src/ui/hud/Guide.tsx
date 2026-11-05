// Phase 8: Juniper, the guide. A small card with her portrait, the current step, its progress, and a
// skip link. The server decides when a step is done; this component only nudges it to check.
import { useEffect, useRef, useState } from "react";
import { useAvatar } from "../../state/avatar";
import { useSession } from "../../state/session";
import { useTutorial, type AwayCard } from "../../state/tutorial";
import { useVillage } from "../../state/village";
import { CharacterPreview, formatDuration, Icon, Modal } from "../components/kit";
import { itemIcon, itemName } from "../../game/items";

function useTypewriter(text: string, cps = 55): string {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    if (document.documentElement.dataset.reduceMotion === "1") {
      setN(text.length);
      return;
    }
    const id = window.setInterval(() => setN((v) => (v >= text.length ? v : v + 2)), 2000 / cps);
    return () => window.clearInterval(id);
  }, [text, cps]);
  return text.slice(0, n);
}

/** Keeps asking the server whether the current goal is met: on village changes, room events, and a slow tick. */
function useTutorialNudges() {
  const tut = useTutorial((s) => s.tut);
  const check = useTutorial((s) => s.check);
  const version = useVillage((s) => s.village?.version);
  const discovered = useVillage((s) => s.village?.discovered.length);
  const xp = useAvatar((s) => s.xp);
  const inv = useAvatar((s) => s.inv);
  const mode = useAvatar((s) => s.mode);
  const active = Boolean(tut?.active && tut.step && tut.step.kind !== "confirm");
  useEffect(() => {
    if (!active) return;
    const id = window.setTimeout(() => void check(), 700);
    return () => window.clearTimeout(id);
  }, [active, version, discovered, xp, inv, mode, check]);
  useEffect(() => {
    if (!active || tut?.step?.kind !== "stat") return;
    const id = window.setInterval(() => void check(), 3500); // the room writes counters a few seconds late
    return () => window.clearInterval(id);
  }, [active, tut?.step?.kind, check]);
}

export function Guide() {
  const tut = useTutorial((s) => s.tut);
  const minimized = useTutorial((s) => s.minimized);
  const set = useTutorial((s) => s.set);
  const check = useTutorial((s) => s.check);
  const skip = useTutorial((s) => s.skip);
  const [line, setLine] = useState(0);
  const [sure, setSure] = useState(false);
  const step = tut?.step;
  useTutorialNudges();
  useEffect(() => {
    setLine(0);
    setSure(false);
  }, [step?.key]);
  // the HUD control this step is about pulses (CSS: body[data-tut] [data-tut-target])
  useEffect(() => {
    const target = tut?.active && !minimized ? step?.highlight ?? "" : "";
    document.body.dataset.tut = target;
    return () => {
      document.body.dataset.tut = "";
    };
  }, [tut?.active, step?.highlight, minimized]);
  const text = useTypewriter(step?.lines[line] ?? "");
  const lastRef = useRef<string | null>(null);
  lastRef.current = step?.key ?? null;
  if (!tut?.active || !step) return null;
  const more = line < step.lines.length - 1;
  const [have, need] = step.progress;
  if (minimized) {
    return (
      <button className="guide-mini" onClick={() => set({ minimized: false })} aria-label={`${tut.guide.name}: ${step.title}`}>
        <CharacterPreview look={tut.guide.look} scale={2} walking={false} />
        <span className="guide-dot head">!</span>
      </button>
    );
  }
  return (
    <div className="panel guide-card" role="dialog" aria-label={`${tut.guide.name}, your guide`}>
      <div className="row" style={{ gap: 10, alignItems: "flex-start" }}>
        <div className="guide-portrait">
          <CharacterPreview look={tut.guide.look} scale={3} walking={false} />
        </div>
        <div className="col grow" style={{ gap: 4, minWidth: 0 }}>
          <div className="row" style={{ gap: 6 }}>
            <span className="head guide-name">{tut.guide.name}</span>
            <span className="small muted">step {tut.index + 1} of {tut.total}</span>
            <span className="grow" />
            <button className="btn secondary small icon-only" onClick={() => set({ minimized: true })} aria-label="Hide guide">–</button>
          </div>
          <span className="head" style={{ fontSize: 16 }}>{step.title}</span>
          <p className="guide-text" aria-live="polite">{text}</p>
          {step.kind !== "confirm" && !more && (
            <div className="row" style={{ gap: 6 }}>
              <span className="meter grow" role="meter" aria-valuenow={have} aria-valuemax={need} aria-label="Progress">
                <span style={{ width: `${(have / need) * 100}%`, background: "var(--leaf)" }} />
              </span>
              <span className="small head">{have}/{need}</span>
            </div>
          )}
          {Object.keys(step.reward).length > 0 && !more && (
            <span className="small muted row" style={{ gap: 4, flexWrap: "wrap" }}>
              Reward:{" "}
              {Object.entries(step.reward).map(([k, v]) => (
                <span key={k} className="row" style={{ gap: 2 }}>
                  <Icon name={k === "coins" ? "coins" : k} scale={1} /> {v}
                </span>
              ))}
            </span>
          )}
          <div className="row" style={{ gap: 6, marginTop: 2, flexWrap: "wrap" }}>
            {more ? (
              <button className="btn small" onClick={() => setLine(line + 1)}>Next ›</button>
            ) : step.kind === "confirm" ? (
              <button className="btn small gold" onClick={() => void check(step.key)}>{step.button ?? "OK"}</button>
            ) : null}
            <span className="grow" />
            {sure ? (
              <button className="btn danger small" onClick={() => void skip()}>Skip the tutorial?</button>
            ) : (
              <button className="link-btn small" onClick={() => setSure(true)}>skip</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function AwayCardModal() {
  const away = useTutorial((s) => s.away);
  const ack = useTutorial((s) => s.ackAway);
  const config = useSession((s) => s.config);
  if (!away || !config) return null;
  return <AwayBody away={away} onClose={() => void ack()} config={config} />;
}

function AwayBody({ away, onClose, config }: { away: AwayCard; onClose: () => void; config: NonNullable<ReturnType<typeof useSession.getState>["config"]> }) {
  const gained = Object.entries(away.gained).sort((a, b) => b[1] - a[1]);
  return (
    <Modal title="While you were away" onClose={onClose}>
      <div className="col" style={{ gap: 10 }}>
        <div className="row" style={{ gap: 10, alignItems: "center" }}>
          <div className="guide-portrait"><CharacterPreview look={away.guide.look} scale={3} walking={false} /></div>
          <div className="col" style={{ gap: 2 }}>
            <span className="head">You were gone {formatDuration(away.away_s)}.</span>
            <span className="small" style={{ fontStyle: "italic" }}>“{away.quip}” · {away.guide.name}</span>
          </div>
        </div>
        {gained.length > 0 && (
          <div className="col" style={{ gap: 4 }}>
            <span className="head small">Your village made</span>
            <div className="away-grid">
              {gained.map(([k, v]) => (
                <span key={k} className="slot away-chip row">
                  <Icon name={k} scale={2} /> <b>+{v.toLocaleString()}</b>
                  {away.full.includes(k) && <span className="small" style={{ color: "var(--red)" }}> full!</span>}
                </span>
              ))}
            </div>
          </div>
        )}
        {away.finished.length > 0 && (
          <span className="small">
            <Icon name="build" scale={1} /> Finished: {away.finished.map((b) => `${config.buildings[b.key]?.name ?? b.key} (level ${b.level})`).join(", ")}
          </span>
        )}
        {Object.keys(away.crafted).length > 0 && (
          <span className="small">
            <Icon name="anvil" scale={1} /> Crafted: {Object.entries(away.crafted).map(([k, q]) => `${q} ${itemName(k).toLowerCase()}`).join(", ")}
          </span>
        )}
        {away.gear_ready > 0 && (
          <span className="small"><Icon name={itemIcon("spear", 1)} scale={1} /> {away.gear_ready} forged item{away.gear_ready > 1 ? "s are" : " is"} waiting at the anvil!</span>
        )}
        {away.coins !== 0 && <span className="small"><Icon name="coins" scale={1} /> Coins {away.coins > 0 ? "+" : ""}{away.coins.toLocaleString()}</span>}
        {away.full.length > 0 && (
          <span className="small" style={{ color: "var(--red)" }}>Some storage is full. Upgrade the Storehouse or sell the extra at the Market.</span>
        )}
        {away.merchant_moved && <span className="small"><Icon name="cart" scale={1} /> Tamsin the Tinker has moved her cart, with fresh stock.</span>}
        <button className="btn gold" onClick={onClose}>Back to work!</button>
      </div>
    </Modal>
  );
}
