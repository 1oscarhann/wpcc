// Phase 12 HUD: progress through the delve you're in, the boss bar, the "E · Pull the lever" prompt,
// the way out, and the Delve Gate's daily leaderboard.
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { roomLink } from "../../net/room";
import { useDelve } from "../../state/delve";
import { useRealm } from "../../state/realm";
import { Icon, Modal } from "../components/kit";

function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function DelveHud({ touch }: { touch: boolean }) {
  const delve = useDelve((s) => s.delve);
  const state = useDelve((s) => s.state);
  const boss = useDelve((s) => s.boss);
  const near = useDelve((s) => s.near);
  const [, tick] = useState(0);
  const [bossHp, setBossHp] = useState(255);
  const [sure, setSure] = useState(false); // leaving mid-run takes a second click
  useEffect(() => {
    if (!sure) return;
    const id = window.setTimeout(() => setSure(false), 3000);
    return () => window.clearTimeout(id);
  }, [sure]);
  useEffect(() => {
    if (!delve) return;
    const id = window.setInterval(() => {
      tick((n) => n + 1);
      if (boss) {
        const e = roomLink.client?.ents.get(boss.id);
        const s = e?.samples[e.samples.length - 1];
        if (s) setBossHp(s.hp);
      }
    }, 250);
    return () => window.clearInterval(id);
  }, [delve, boss]);
  if (!delve || !state) return null;
  const rooms = delve.layout.rooms.length;
  const elapsed = state.clear_ms ?? Date.now() - delve.started_ms;
  return (
    <>
      <div className="delve-hud panel-paper">
        <div className="row" style={{ gap: 6, alignItems: "center" }}>
          <Icon name="map" scale={1.5} />
          <span className="head">{delve.name}</span>
          <span className="small muted">· ring {delve.difficulty}</span>
        </div>
        <div className="small">
          Rooms {state.visited.length}/{rooms} · {state.clear_ms ? "cleared in " : ""}<b>{clock(elapsed)}</b>
        </div>
        <button className={`btn small ${state.portal ? "gold" : "secondary"}`} onClick={() => {
          if (state.portal || sure) roomLink.send?.("DUNGEON", "leave");
          else setSure(true);
        }}>
          {state.portal ? "Head home" : sure ? "Really leave?" : "Leave"}
        </button>
      </div>
      {boss && (
        <div className={`boss-bar ${boss.enraged ? "enraged" : ""}`} role="status" aria-label={`${boss.name} health`}>
          <span className="head">{boss.name}</span>
          {boss.note && <span key={boss.note} className="boss-note small"> {boss.note}</span>}
          <div className="boss-bar-track"><div className="boss-bar-fill" style={{ width: `${(bossHp / 255) * 100}%` }} /></div>
        </div>
      )}
      {near && (
        <button className="btn gold trade-prompt delve-prompt"
          onClick={() => (near.kind === "portal" ? roomLink.send?.("DUNGEON", "portal") : roomLink.send?.("DUNGEON", "use", near.prop))}>
          <Icon name={near.kind === "portal" ? "home" : "star"} /> {touch ? near.label : <><span className="av-key">E</span> {near.label}</>}
        </button>
      )}
    </>
  );
}

interface Board {
  day: string;
  biome: string;
  board: { rank: number; names: string[]; realm: string; clear_ms: number; deaths: number; you: boolean }[];
  your_best_ms: number | null;
}

export function DelvePanel() {
  const open = useDelve((s) => s.panel);
  const [board, setBoard] = useState<Board | null>(null);
  useEffect(() => {
    if (!open) return;
    void api<Board>("/api/dungeons/daily").then(setBoard).catch(() => setBoard(null));
  }, [open]);
  if (!open) return null;
  const close = () => useDelve.getState().set({ panel: false });
  const gate = useRealm.getState().overview?.pois.find((q) => q.kind === "delve");
  return (
    <Modal title="The Delve Gate" onClose={close}>
      <p className="small" style={{ marginTop: 0 }}>
        Today's delve is the same for every realm. Clear it as a party of up to four. The fastest clears make the board.
      </p>
      <div className="col delve-board" style={{ gap: 4 }}>
        {!board ? (
          <span className="small muted">Reading the rune-board…</span>
        ) : board.board.length === 0 ? (
          <span className="small muted">Nobody has cleared today's delve yet. Be first!</span>
        ) : (
          board.board.map((r) => (
            <div key={r.rank} className={`row small delve-row ${r.you ? "you" : ""}`} style={{ gap: 8 }}>
              <span className="head" style={{ width: 22 }}>{r.rank}</span>
              <span className="grow">{r.names.join(", ")} <span className="muted">· {r.realm}</span></span>
              <span className="head">{clock(r.clear_ms)}</span>
            </div>
          ))
        )}
      </div>
      {board?.your_best_ms != null && <p className="small">Your best today: <b>{clock(board.your_best_ms)}</b></p>}
      <div className="row delve-actions">
        <button className="btn secondary" onClick={close}>Not now</button>
        <button className="btn gold" onClick={() => {
          if (gate) roomLink.send?.("INTERACT", gate.index);
          close();
        }}><Icon name="map" /> Enter today's delve</button>
      </div>
    </Modal>
  );
}
