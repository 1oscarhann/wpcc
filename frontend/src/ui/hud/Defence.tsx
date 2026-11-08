// Phase 13 HUD: the raid countdown and "Defend!" button (both modes), the raid report, and the realm
// boss bar when you're near one.
import { useEffect, useState } from "react";
import { enterAvatar, roomLink } from "../../net/room";
import { useAvatar } from "../../state/avatar";
import { useDefence } from "../../state/defence";
import { useDelve } from "../../state/delve";
import { serverNow, useSession } from "../../state/session";
import { formatDuration, Icon, Modal } from "../components/kit";

/** Fetch the current raid and realm boss once, when the HUD mounts. */
export function useDefenceSync(): void {
  useEffect(() => {
    void useDefence.getState().refresh();
    void useDefence.getState().refreshBoss();
  }, []);
}

/** Hop home to defend: from Build Mode we step into the world first. */
export function defend(): void {
  if (roomLink.client) {
    roomLink.client.goHome();
    return;
  }
  enterAvatar();
  const t0 = Date.now();
  const id = window.setInterval(() => {
    if (roomLink.client) {
      roomLink.client.goHome();
      window.clearInterval(id);
    } else if (Date.now() - t0 > 10000) window.clearInterval(id);
  }, 200);
}

export function WaveChip() {
  const wave = useDefence((s) => s.wave);
  const live = useDefence((s) => s.live);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!wave) return;
    const id = window.setInterval(() => tick((n) => n + 1), 500);
    return () => window.clearInterval(id);
  }, [wave]);
  if (!wave) return null;
  const running = wave.status === "running" || live !== null;
  const left = Math.max(0, ((wave.starts_at_ms ?? 0) - serverNow()) / 1000);
  return (
    <div className={`wave-chip panel-paper ${running ? "live" : ""}`} role="status" aria-live="polite">
      <Icon name="sword" scale={1.5} />
      <div className="col" style={{ gap: 0 }}>
        <span className="head">{running ? "Raid on your village!" : "Raiders approaching"}</span>
        <span className="small">
          {running
            ? live && live.subs
              ? `Wave ${Math.max(1, live.sub)}/${live.subs}${live.stolen ? ` · ${live.stolen} got through` : ""}`
              : "Hold the line!"
            : `They'll reach your gate in ${formatDuration(left)}`}
        </span>
      </div>
      <button className="btn gold small" onClick={defend}>
        <Icon name="home" scale={1.5} /> Defend!
      </button>
    </div>
  );
}

const OUTCOME: Record<string, string> = { flawless: "Flawless defence!", held: "Raid beaten off", overrun: "Overrun!" };

export function WaveReportModal() {
  const report = useDefence((s) => s.report);
  const config = useSession((s) => s.config);
  if (!report || !config) return null;
  const close = () => useDefence.getState().set({ report: null });
  const name = (k: string) => (k === "coins" ? "coins" : config.resources[k]?.name ?? config.items[k]?.name ?? k);
  const icon = (k: string) => (k === "coins" ? "coins" : (config.resources[k]?.icon ?? config.items[k]?.icon ?? "").replace("icon.", ""));
  return (
    <Modal title={OUTCOME[report.outcome] ?? "Raid report"} onClose={close}>
      <p className="lore-text" style={{ marginTop: 0 }}>“{report.line}”</p>
      <div className="row wave-stats" style={{ gap: 14, flexWrap: "wrap" }}>
        <span><b>{report.killed}</b> <span className="small muted">defeated</span></span>
        <span><b>{report.through}</b> <span className="small muted">got through</span></span>
        <span><b>{report.guards_left}/{report.guards}</b> <span className="small muted">guards standing</span></span>
        {report.towers > 0 && <span><b>{report.towers}</b> <span className="small muted">{report.towers === 1 ? "tower" : "towers"}</span></span>}
      </div>
      {Object.keys(report.stolen).length > 0 && (
        <div className="col" style={{ gap: 4, marginTop: 10 }}>
          <span className="small head">Stolen</span>
          <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
            {Object.entries(report.stolen).map(([k, q]) => (
              <span key={k} className="row small" style={{ gap: 3, color: "var(--red)" }} title={name(k)}>
                <Icon name={icon(k)} scale={1.5} /> −{q}
              </span>
            ))}
          </div>
        </div>
      )}
      {(Object.keys(report.rewards).length > 0 || Object.keys(report.rare).length > 0) && (
        <div className="col" style={{ gap: 4, marginTop: 10 }}>
          <span className="small head">Rewards</span>
          <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
            {Object.entries({ ...report.rewards, ...report.rare }).map(([k, q]) => (
              <span key={k} className="row small" style={{ gap: 3 }} title={name(k)}>
                <Icon name={icon(k)} scale={1.5} /> +{q}
              </span>
            ))}
          </div>
        </div>
      )}
      {report.helpers.length > 0 && (
        <p className="small" style={{ marginBottom: 0 }}>
          Thanks to {report.helpers.map(([n, k]) => `${n} (${k})`).join(", ")} for lending a hand.
        </p>
      )}
      {!report.won && (
        <p className="small muted" style={{ marginBottom: 0 }}>
          Tip: post villagers at a Guard Post and build Watchtowers near the gate.
        </p>
      )}
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 10 }}>
        <button className="btn gold" onClick={close}>Back to it</button>
      </div>
    </Modal>
  );
}

/** A realm boss's health, when you're close enough to be fighting it (delves have their own bar). */
export function BossBar() {
  const inDelve = useDelve((s) => s.delve !== null);
  const note = useDefence((s) => s.bossNote);
  const mode = useAvatar((s) => s.mode);
  const config = useSession((s) => s.config);
  const [boss, setBoss] = useState<{ id: number; key: string; hp: number; flags: number } | null>(null);
  useEffect(() => {
    if (mode !== "avatar" || inDelve) {
      setBoss(null);
      return;
    }
    const id = window.setInterval(() => {
      const c = roomLink.client;
      if (!c) return setBoss(null);
      let best: { id: number; key: string; hp: number; flags: number; d: number } | null = null;
      for (const e of c.ents.values()) {
        const s = e.samples[e.samples.length - 1];
        if (!s || (s.flags & 64) === 0) continue;
        const d = Math.hypot(s.x - c.me.x, s.y - c.me.y);
        if (d < 16 && (!best || d < best.d)) best = { id: e.id, key: e.type, hp: s.hp, flags: s.flags, d };
      }
      setBoss(best ? { id: best.id, key: best.key, hp: best.hp, flags: best.flags } : null);
    }, 250);
    return () => window.clearInterval(id);
  }, [mode, inDelve]);
  if (!boss || !config) return null;
  const name = boss.flags & 1024 ? config.world_boss.name : Object.values(config.bosses).find((b) => b.enemy === boss.key)?.name ?? boss.key;
  const fresh = note && note.id === boss.id && Date.now() - note.at < 6000 ? note.text : null;
  const enraged = (fresh ?? "").includes("enraged") || (boss.flags & 512) !== 0;
  return (
    <div className={`boss-bar ${enraged ? "enraged" : ""} ${boss.flags & 256 ? "exposed" : ""} ${boss.flags & 1024 ? "world" : ""}`} role="status" aria-label={`${name} health`}>
      <span className="head">{name}</span>
      {fresh && <span key={fresh} className="boss-note small"> {fresh}</span>}
      {boss.flags & 1024 ? <span className="small world-note"> · one health bar for every realm</span> : null}
      <div className="boss-bar-track"><div className="boss-bar-fill" style={{ width: `${(boss.hp / 255) * 100}%` }} /></div>
    </div>
  );
}
