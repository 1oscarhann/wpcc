// Avatar Mode netcode (docs/PROTOCOL.md §4): fixed 50 ms input steps with local prediction,
// reconciliation on every snapshot (replaying unacked inputs), and a 100 ms interpolation buffer for
// everything else. Rendering never touches the predicted simulation (hit-stop is visual only, D-010).
import protocol from "../../../shared/protocol.json";
import { fromList, newMotion, step, type Motion } from "../sim/motion";
import type { ClientGrid } from "../sim/grid";
import { ATK_NONE, type Rules, type WeaponRule } from "../sim/rules";
import { useAvatar, type InvSlot, type Weapon } from "../state/avatar";
import { useSession } from "../state/session";
import { toast } from "../state/toasts";
import type { Appearance } from "../api/types";

export const EV = protocol.events;
export const ENT = protocol.entity_kinds;
export const ANIM = protocol.anims;
export const SELF_FLAG = protocol.self_flags;
const Q = 64;
const INTERP_TICKS = 2; // 100 ms
const MOTION_LEN = 21;

export interface Sample {
  tick: number;
  x: number;
  y: number;
  dx: number;
  dy: number;
  anim: number;
  at: number;
  hp: number;
  flags: number;
}

export interface Ent {
  id: number;
  kind: number;
  type: string;
  extra: number;
  samples: Sample[];
}

export interface RosterEntry {
  eid: number;
  userId: string;
  name: string;
  appearance: Appearance;
  weapon: string;
  level: number;
}

export interface RoomInfo {
  level: number;
  xp: number;
  xp_next: number;
  hp_max: number;
  weapon: Weapon;
  quick: Record<string, [string, number]>;
  inv: InvSlot[];
  inv_capacity: number;
  home: { rect: [number, number, number, number]; door: [number, number] };
  hz: number;
}

export type RoomEvent = unknown[];
type Send = (op: string, ...fields: unknown[]) => void;

const TOASTS: Record<string, string> = {
  bag_full: "Your bag is full! Head home to drop things off.",
  storage_full: "Storage is full. Upgrade your Storehouse!",
  no_potions: "No potions left.",
  weapon_dull: "Your weapon has gone dull (−30% damage). Repair it at your Forge.",
  party_no_player: "They've wandered off.",
  party_party_full: "Your party is full.",
  party_already_in: "They're already in your party.",
  party_invite_expired: "That invite has expired.",
  travel_ko: "You can't travel while knocked out.",
  travel_in_combat: "Not mid-fight! Shake them off first.",
  travel_not_attuned: "You haven't attuned that waystone yet. Walk up to it once.",
  travel_not_at_waystone: "Stand next to a waystone to travel.",
  poi_too_far: "A little closer…",
  chest_empty: "You've already emptied this chest.",
  shrine_resting: "The shrine is resting. Come back later.",
  villager_home: "They're already on their way to your village.",
};

export class RoomClient {
  eid: number;
  me: Motion;
  prev: Motion;
  weapon: WeaponRule;
  info: RoomInfo;
  ents = new Map<number, Ent>();
  roster = new Map<number, RosterEntry>();
  offset = { x: 0, y: 0 };
  input = { mx: 0, my: 0, ax: 0, ay: 0, held: 0, latched: 0 };
  hp: number;
  flags = 0;
  depleted = new Map<number, number>(); // node id → local ms when it regrows
  alpha = 0;
  private pending: { seq: number; inp: [number, number, number, number, number] }[] = [];
  private seq = 0;
  private ctick = 0;
  private acc = 0;
  private base: number | null = null; // local ms of server tick 0 (smoothed)
  private listeners = new Set<(ev: RoomEvent) => void>();
  private snapshots = 0;

  constructor(
    private send: Send,
    joined: unknown[],
    readonly grid: ClientGrid,
    readonly rules: Rules,
  ) {
    const [, , tick, eid, self, info, blocks, claimed, depleted, roster] = joined as [
      number, string, number, number, number[], RoomInfo, number[][], number[], [number, number][], unknown[][],
    ];
    this.eid = eid;
    this.info = info;
    this.me = fromList(self.slice(0, MOTION_LEN));
    this.prev = { ...this.me };
    this.hp = self[MOTION_LEN];
    this.weapon = rules.weapons[info.weapon.type] ?? rules.weapons.sword;
    grid.setBlocks(blocks, claimed);
    const now = performance.now();
    for (const [nid, ms] of depleted) this.depleted.set(nid, now + ms);
    for (const r of roster) this.addRoster(r);
    this.base = now - tick * 50;
    useAvatar.getState().set({
      mode: "avatar",
      hp: this.hp,
      hpMax: info.hp_max,
      st: this.me.st,
      stMax: this.me.st_max,
      level: info.level,
      xp: info.xp,
      xpNext: info.xp_next,
      weapon: info.weapon,
      quick: info.quick,
      inv: info.inv,
      invCap: info.inv_capacity,
      abCdMax: this.weapon.ability.cooldown,
    });
  }

  on(fn: (ev: RoomEvent) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(ev: RoomEvent): void {
    for (const fn of this.listeners) fn(ev);
  }

  private addRoster(r: unknown[]): void {
    const [eid, userId, name, appearance, weapon, level] = r as [number, string, string, Appearance, string, number];
    this.roster.set(eid, { eid, userId, name, appearance, weapon, level });
  }

  get ko(): boolean {
    return (this.flags & SELF_FLAG.ko) !== 0;
  }

  /** Estimated server tick being displayed for other entities (interpolated 100 ms back). */
  renderTick(now = performance.now()): number {
    return this.base === null ? 0 : (now - this.base) / 50 - INTERP_TICKS;
  }

  // ── fixed step ───────────────────────────────────────────────────────────
  update(dms: number): void {
    this.acc += Math.min(dms, 250);
    while (this.acc >= 50) {
      this.acc -= 50;
      this.fixedStep();
    }
    this.alpha = this.acc / 50;
    const k = Math.exp(-dms / 60); // corrections fade over ~100 ms
    this.offset.x *= k;
    this.offset.y *= k;
  }

  private fixedStep(): void {
    const { ax, ay } = this.input;
    // rooted by a summoner's circle: the server ignores movement, so predict (and send) none
    const rooted = (this.flags & SELF_FLAG.rooted) !== 0;
    const mx = rooted ? 0 : this.input.mx;
    const my = rooted ? 0 : this.input.my;
    const b = this.input.held | this.input.latched;
    this.input.latched = 0;
    if (this.ko) {
      this.pending = [];
      this.prev = { ...this.me };
      return;
    }
    this.seq += 1;
    this.ctick += 1;
    this.send("INPUT", this.seq, this.ctick, Math.max(0, Math.floor(this.renderTick())), mx, my, ax, ay, b);
    const inp: [number, number, number, number, number] = [mx, my, ax, ay, b];
    this.pending.push({ seq: this.seq, inp });
    if (this.pending.length > 80) this.pending.shift();
    this.prev = { ...this.me };
    const started = step(this.me, mx, my, ax, ay, b, this.rules, this.weapon, this.grid.solid);
    if (started !== ATK_NONE) this.emit([-1, started, this.me.atk_i, this.me.ax, this.me.ay]); // predicted swing
  }

  /** Where to draw the local avatar this frame (tiles). */
  drawPos(): { x: number; y: number } {
    const a = this.alpha;
    return {
      x: this.prev.x + (this.me.x - this.prev.x) * a + this.offset.x,
      y: this.prev.y + (this.me.y - this.prev.y) * a + this.offset.y,
    };
  }

  // ── server messages ──────────────────────────────────────────────────────
  onSnapshot(msg: unknown[]): void {
    const [, tick, ack, self, ents, evs] = msg as [number, number, number, number[], unknown[][], RoomEvent[]];
    const now = performance.now();
    const cand = now - tick * 50;
    if (this.base === null) this.base = cand;
    // jump earlier quickly (a fast packet is the best clock estimate), drift later slowly (jitter)
    else this.base += (cand - this.base) * (cand < this.base ? 0.25 : 0.02);
    this.snapshots++;

    // reconcile the local avatar
    const server = fromList(self.slice(0, MOTION_LEN));
    this.hp = self[MOTION_LEN];
    const hpMax = self[MOTION_LEN + 1];
    const wasKo = this.ko;
    this.flags = self[MOTION_LEN + 2];
    this.pending = this.pending.filter((p) => p.seq > ack);
    const replay = { ...server };
    for (const p of this.pending) step(replay, ...p.inp, this.rules, this.weapon, this.grid.solid);
    const ex = replay.x - this.me.x;
    const ey = replay.y - this.me.y;
    if (ex * ex + ey * ey > 4 || this.ko !== wasKo) {
      this.offset.x = this.offset.y = 0;
      this.prev = { ...replay };
    } else {
      this.offset.x -= ex;
      this.offset.y -= ey;
      this.prev.x += ex;
      this.prev.y += ey;
    }
    this.me = replay;

    // everything else goes into the interpolation buffer
    const seen = new Set<number>();
    for (const e of ents) {
      const [id, kind, type, xq, yq, dx, dy, anim, at, hp, flags] = e as [
        number, number, string, number, number, number, number, number, number, number, number,
      ];
      seen.add(id);
      let ent = this.ents.get(id);
      if (!ent) {
        ent = { id, kind, type, extra: 0, samples: [] };
        this.ents.set(id, ent);
        this.emit([-2, id]); // entity appeared
      }
      ent.type = type;
      ent.extra = kind === ENT.drop ? flags : 0;
      ent.samples.push({ tick, x: xq / Q, y: yq / Q, dx: dx / 100, dy: dy / 100, anim, at, hp, flags });
      if (ent.samples.length > 12) ent.samples.shift();
    }
    for (const id of [...this.ents.keys()]) {
      if (!seen.has(id)) {
        this.ents.delete(id);
        this.emit([-3, id]); // entity gone
      }
    }

    const store = useAvatar.getState();
    const patch: Partial<ReturnType<typeof useAvatar.getState>> = {
      hp: this.hp,
      hpMax,
      st: this.me.st,
      stMax: this.me.st_max,
      flags: this.flags,
      abCd: this.me.ab_cd,
      dodgeCd: this.me.dodge_cd,
      inCombat: (this.flags & SELF_FLAG.in_combat) !== 0,
    };
    for (const ev of evs) this.handleEvent(ev, patch);
    store.set(patch);
  }

  private handleEvent(ev: RoomEvent, patch: Partial<ReturnType<typeof useAvatar.getState>>): void {
    const kind = ev[0] as number;
    switch (kind) {
      case EV.XP: {
        const [, , level, xp, xpNext, gained, hpMax] = ev as number[];
        Object.assign(patch, { level, xp, xpNext, hpMax });
        if (gained) toast(`Level up! You're level ${level}.`, "good", "star");
        break;
      }
      case EV.INVENTORY:
        patch.inv = ev[1] as InvSlot[];
        break;
      case EV.HEAL:
        if (ev[1] === this.eid) patch.quick = ev[3] as Record<string, [string, number]>;
        break;
      case EV.TOAST:
        toast(TOASTS[ev[1] as string] ?? String(ev[1]), "bad");
        break;
      case EV.PLAYER: {
        this.addRoster(ev.slice(1));
        const r = this.roster.get(ev[1] as number);
        if (r && r.eid === this.eid) {
          const w = useAvatar.getState().weapon;
          this.weapon = this.rules.weapons[r.weapon] ?? this.weapon;
          patch.abCdMax = this.weapon.ability.cooldown;
          if (w.type !== r.weapon) patch.weapon = { ...w, type: r.weapon };
        }
        break;
      }
      case EV.PLAYER_LEFT:
        this.roster.delete(ev[1] as number);
        break;
      case EV.NODE: {
        const [, nid, , , depleted, ms] = ev as number[];
        if (depleted) this.depleted.set(nid, performance.now() + ms);
        else if (ev[2] === 0) this.depleted.delete(nid);
        break;
      }
      case EV.RESPAWN:
      case EV.TELEPORT:
        this.pending = [];
        break;
      case EV.DEPOSIT: {
        const cfg = useSession.getState().config;
        const parts = Object.entries(ev[1] as Record<string, number>).map(
          ([k, q]) => `${q} ${(cfg?.resources[k]?.name ?? k).toLowerCase()}`,
        );
        toast(`Stored ${parts.join(", ")} at home.`, "good", "home");
        break;
      }
      default:
        break;
    }
    this.emit(ev);
  }

  onBlocks(msg: unknown[]): void {
    this.grid.setBlocks(msg[1] as number[][], msg[2] as number[]);
  }

  /** Interpolated state of another entity at the render tick (null until it has a sample). */
  sampleAt(ent: Ent, rt: number): Sample | null {
    const s = ent.samples;
    if (!s.length) return null;
    if (rt <= s[0].tick) return s[0];
    for (let i = s.length - 1; i >= 0; i--) {
      if (s[i].tick <= rt) {
        const a = s[i];
        const b = s[i + 1];
        if (!b) return a;
        const t = (rt - a.tick) / (b.tick - a.tick);
        return { ...b, x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, at: a.at + (b.at - a.at) * t };
      }
    }
    return s[s.length - 1];
  }

  static spawnMotion(x: number, y: number): Motion {
    return newMotion(x, y, 100);
  }
}

/** The one live room client (null in Build Mode) and the socket's send. */
export const roomLink: { client: RoomClient | null; send: Send | null; listeners: Set<(c: RoomClient | null) => void> } = {
  client: null,
  send: null,
  listeners: new Set(),
};

export function setRoomClient(c: RoomClient | null): void {
  roomLink.client = c;
  for (const fn of roomLink.listeners) fn(c);
}

export function enterAvatar(): void {
  const st = useAvatar.getState();
  if (st.mode !== "build" || !roomLink.send) return;
  st.set({ mode: "entering" });
  roomLink.send("ENTER_AVATAR");
}

export function leaveAvatar(): void {
  const st = useAvatar.getState();
  if (st.mode !== "avatar" || !roomLink.send) return;
  if (st.inCombat) {
    toast("You can't head home mid-fight!", "bad");
    return;
  }
  st.set({ mode: "leaving", bagOpen: false });
  roomLink.send("LEAVE_AVATAR");
}
