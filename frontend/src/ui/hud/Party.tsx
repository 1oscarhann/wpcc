// Phase 9: parties (Avatar Mode). Frames for your party, an invite card, and a list of nearby players.
import { useState } from "react";
import { roomLink } from "../../net/room";
import { useRealm } from "../../state/realm";
import { Icon } from "../components/kit";

export function PartyFrames() {
  const party = useRealm((s) => s.party);
  const myEid = roomLink.client?.eid;
  if (!party) return null;
  const others = party.members.filter((m) => m.eid !== myEid);
  return (
    <div className="hud-bar party-frames col" aria-label="Your party">
      <div className="row" style={{ gap: 6 }}>
        <Icon name="party" scale={1.5} /> <span className="head small grow">Party</span>
        <button className="link-btn small" onClick={() => roomLink.send?.("PARTY", "leave")}>leave</button>
      </div>
      {others.map((m) => (
        <div key={m.user_id} className="col" style={{ gap: 1 }}>
          <span className="small">{m.name} <span className="muted">Lv {m.level}{m.here ? "" : " · away"}</span></span>
          <span className="av-bar" style={{ height: 6 }}>
            <span className="av-bar-fill" style={{ width: `${(m.hp / m.hp_max) * 100}%`, background: "linear-gradient(#e2735a, #ad433b)" }} />
          </span>
        </div>
      ))}
    </div>
  );
}

export function PartyInvite() {
  const invite = useRealm((s) => s.invite);
  const set = useRealm((s) => s.set);
  if (!invite) return null;
  return (
    <div className="panel party-invite row" role="alertdialog" aria-label="Party invite">
      <Icon name="party" scale={2} />
      <span className="grow"><b>{invite.from}</b> invites you to a party.</span>
      <button className="btn small gold" onClick={() => {
        roomLink.send?.("PARTY", "accept", invite.party);
        set({ invite: null });
      }}>Join</button>
      <button className="btn small secondary" onClick={() => set({ invite: null })}>No thanks</button>
    </div>
  );
}

export function PartyButton() {
  const [open, setOpen] = useState(false);
  const party = useRealm((s) => s.party);
  const c = roomLink.client;
  const players = c ? [...c.roster.values()].filter((r) => r.eid !== c.eid) : [];
  const inParty = new Set(party?.members.map((m) => m.eid) ?? []);
  return (
    <div className="party-pop-wrap">
      <button className="btn secondary icon-only" onClick={() => setOpen(!open)} aria-label="Party" title="Party: play together">
        <Icon name="party" />
      </button>
      {open && (
        <div className="panel party-pop col">
          <span className="head small">Players nearby</span>
          {players.length === 0 && <span className="small muted">Nobody else is out exploring right now.</span>}
          {players.map((r) => (
            <div key={r.eid} className="row small" style={{ gap: 6 }}>
              <span className="grow">{r.name} <span className="muted">Lv {r.level}</span></span>
              {inParty.has(r.eid) ? (
                <span className="muted">in party</span>
              ) : (
                <button className="btn small" onClick={() => roomLink.send?.("PARTY", "invite", r.eid)}>Invite</button>
              )}
            </div>
          ))}
          <span className="small muted">Party members near a kill share its XP.</span>
        </div>
      )}
    </div>
  );
}
