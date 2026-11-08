// Avatar Mode netcode (docs/PROTOCOL.md §4): fixed 50 ms input steps with local prediction,
// reconciliation on every snapshot (replaying unacked inputs), and a 100 ms interpolation buffer for
// everything else. Rendering never touches the predicted simulation (hit-stop is visual only, D-010).
import { useDefence, type WaveReport } from "../state/defence";
import protocol from "../../../shared/protocol.json";
import { fromList, newMotion, step, type Motion } from "../sim/motion";
import type { ClientGrid } from "../sim/grid";
import { ATK_NONE, type Rules, type WeaponRule } from "../sim/rules";
import { useAvatar, type InvSlot, type Weapon } from "../state/avatar";
import { delveSolid, useDelve, type DelveInfo, type DelveState } from "../state/delve";
import { useSession } from "../state/session";
import { addPing } from "../state/social";
import { useJournal } from "../state/journal";
import { useFishing } from "../state/companions";
import { toast } from "../state/toasts";
import { sfx } from "../game/sfx";
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
  title: string | null;
  pet: string | null; // Phase 16b: the pet trotting after them
  mount: string | null; // the mount they're riding right now (null on foot)
}

export interface RoomInfo {
  level: number;
  xp: number;
  xp_next: number;
  hp_max: number;
  weapon: Weapon;
  offhand?: { key?: string; type?: string; tier?: number };
  mods?: [number, number, number];
  quick: Record<string, [string, number]>;
  inv: InvSlot[];
  inv_capacity: number;
  home: { rect: [number, number, number, number]; door: [number, number] };
  hz: number;
  bosses?: [string, string, number, number, number][]; // Phase 13: awake realm bosses (key, name, x, y, expires)
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
  no_bombs: "Out of bombs: they come back one by one.",
  delve_enter: "You descend into the {name}…",
  delve_ko: "You can't go in while knocked out.",
  delve_full: "That delve is full (four at most).",
  delve_already_in: "You're already in a delve.",
  delve_in_combat: "Not mid-fight! Clear the room first, or find the portal.",
  full_hp: "You're already at full health.",
  poi_too_far: "A little closer…",
  chest_empty: "You've already emptied this chest.",
  shrine_resting: "The shrine is resting. Come back later.",
  villager_home: "They're already on their way to your village.",
  wave_no_wave: "There's no raid on your village right now.",
  wave_busy: "Not now: get back on your feet (or out of the delve) first.",
  wave_no_village: "Your village isn't in this realm.",
  ride_no_mount: "You don't have a mount yet. Get one in the Journal (Pets tab).",
  ride_delve: "No riding in a delve.",
  ride_ko: "Not while you're knocked out.",
  ride_in_combat: "Not mid-fight!",
  fish_no_water: "Stand right next to water to fish.",
  fish_delve: "Nothing to fish for down here.",
  fish_ko: "Not while you're knocked out.",
  fish_in_combat: "Not mid-fight!",
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
  private baseRules: Rules;

  constructor(
    private send: Send,
    joined: unknown[],
    readonly grid: ClientGrid,
    public rules: Rules,
  ) {
    this.baseRules = rules;
    const [, , tick, eid, self, info, blocks, claimed, depleted, roster] = joined as [
      number, string, number, number, number[], RoomInfo, number[][], number[], [number, number][], unknown[][],
    ];
    this.eid = eid;
    this.info = info;
    this.me = fromList(self.slice(0, MOTION_LEN));
    this.prev = { ...this.me };
    this.hp = self[MOTION_LEN];
    this.weapon = rules.weapons[info.weapon.type] ?? rules.weapons.sword;
    if (info.mods) this.applyMods(...info.mods);
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
      offhand: { ...(info.offhand ?? {}), type: info.offhand?.type ?? "", charges: 0, readyAt: 0 },
      buffs: [],
    });
    useDefence.getState().set({
      bosses: (info.bosses ?? []).map(([key, name, x, y, expires_ms]) => ({ key, name, x, y, expires_ms })),
    });
  }

  /** Plate armour, swift food, stamina potions: the server's MOVE_MODS, applied with the same three
   * multiplications it uses, so the predicted movement stays bit-identical (D-079). */
  applyMods(speed: number, dodge: number, regen: number): void {
    const b = this.baseRules;
    this.rules =
      speed === 1 && dodge === 1 && regen === 1
        ? b
        : { ...b, speed_tick: b.speed_tick * speed, dodge_step: b.dodge_step * dodge, st_regen: b.st_regen * regen };
  }

  /** Phase 12: doors, puzzles, the boss and the portal inside the delve you're in. */
  private delveEvent(ev: RoomEvent): void {
    const d = useDelve.getState();
    if (!d.delve || !d.state) return;
    const st: DelveState = { ...d.state };
    const op = ev[1] as string;
    const patch: Partial<ReturnType<typeof useDelve.getState>> = {};
    if (op === "doors") {
      st.locked = ev[2] as number[];
      this.grid.setDelve({ ox: d.delve.origin[0], oy: d.delve.origin[1], w: d.delve.layout.w, h: d.delve.layout.h, solid: delveSolid(d.delve, st) });
    } else if (op === "visit") {
      if (!st.visited.includes(ev[2] as number)) st.visited = [...st.visited, ev[2] as number];
    }
    else if (op === "cleared") {
      st.cleared = [...st.cleared, ev[2] as number];
      toast("Room cleared! The gates lift.", "good", "check");
    } else if (op === "plates") st.plates = ev[2] as number[];
    else if (op === "lamps") {
      st.lamps = ev[2] as number;
      const i = ev[3] as number;
      patch.levers = { ...d.levers, [i]: !d.levers[i] };
    } else if (op === "solved") {
      st.solved = [...st.solved, ev[2] as number];
      toast("Something clicks deep in the stone. The way opens!", "good", "star");
    } else if (op === "boss") patch.boss = { id: ev[2] as number, name: ev[3] as string, note: "wakes!" };
    // phases read out under the boss bar rather than as toasts piling up over the fight
    else if (op === "phase" && d.boss) patch.boss = { ...d.boss, note: "calls for help!" };
    else if (op === "enrage" && d.boss) patch.boss = { ...d.boss, note: "is enraged!", enraged: true };
    else if (op === "portal") {
      st.portal = true;
      st.clear_ms = ev[2] as number;
      patch.boss = null;
      const s = Math.round((ev[2] as number) / 1000);
      toast(`Delve cleared in ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}! A portal home opens.`, "good", "star");
    } else if (op === "chest") patch.chests = [...d.chests, ev[2] as number];
    d.set({ ...patch, state: st });
  }

  /** Phase 13: a raid on a village (yours, or one you're helping). */
  private waveEvent(ev: RoomEvent): void {
    const d = useDefence.getState();
    const mine = ev[1] === useSession.getState().me?.user.id;
    const op = ev[2] as string;
    if (op === "start") {
      if (mine) {
        d.set({ live: { sub: 0, subs: ev[3] as number, stolen: 0 }, wave: d.wave ? { ...d.wave, status: "running" } : d.wave, report: null });
        toast("The horn sounds! Raiders at the gate!", "bad", "info");
      } else toast("A neighbour's village is under attack! Lend a hand?", "info", "info");
    } else if (op === "sub" && mine && d.live) {
      d.set({ live: { ...d.live, sub: ev[3] as number, subs: ev[4] as number } });
    } else if (op === "steal" && mine && d.live) {
      d.set({ live: { ...d.live, stolen: ev[5] as number } });
    } else if (op === "guard_down" && mine) {
      toast(`${ev[3] as string} is down! They'll be back on their feet after the raid.`, "bad", "info");
    } else if (op === "end") {
      const report = ev[3] as WaveReport;
      if (mine) d.set({ wave: null, live: null, report });
      else toast(report.won ? "The raid was beaten off. Thanks for the help!" : "The raiders got away with a haul.", "good", "star");
    }
  }

  /** Phase 13: realm bosses waking, changing phase, opening up and falling. */
  private bossEvent(ev: RoomEvent): void {
    const d = useDefence.getState();
    const op = ev[1] as string;
    if (op === "awake") {
      const [, , key, name, x, y, expires_ms] = ev as [number, string, string, string, number, number, number];
      if (!d.bosses.some((b) => b.key === key)) {
        d.set({ bosses: [...d.bosses, { key, name, x, y, expires_ms }] });
        toast(`${name} has woken! Find it on your map.`, "bad", "info");
      }
      void d.refreshBoss();
    } else if (op === "wake") {
      d.set({ bossNote: { id: ev[4] as number, text: "wakes!", at: Date.now() } });
    } else if (op === "phase") {
      const note = ev[4] as string;
      if (note) d.set({ bossNote: { id: ev[2] as number, text: note, at: Date.now() } });
    } else if (op === "vulnerable") {
      d.set({ vulnerable: { id: ev[2] as number, until: Date.now() + (ev[3] as number) }, bossNote: { id: ev[2] as number, text: "is exposed! Hit it now!", at: Date.now() } });
    } else if (op === "reset") {
      d.set({ bossNote: null });
    } else if (op === "down") {
      const [, , key, name, winners] = ev as [number, string, string, string, string[]];
      d.set({ bosses: d.bosses.filter((b) => b.key !== key), bossNote: null, vulnerable: null });
      toast(`${name} has fallen!${winners.length ? ` Well fought, ${winners.join(", ")}.` : ""}`, "good", "star");
      void d.refreshBoss();
    }
  }

  /** "Defend!": hop home while a raid is coming or on. */
  goHome(): void {
    this.send("WAVE", "home");
  }

  /** Quick-slot 1–4 (Phase 11). */
  useQuick(i: number): void {
    this.send("USE_QUICK", i);
  }

  on(fn: (ev: RoomEvent) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(ev: RoomEvent): void {
    for (const fn of this.listeners) fn(ev);
  }

  private addRoster(r: unknown[]): void {
    const [eid, userId, name, appearance, weapon, level, title, pet, mount] = r as [
      number, string, string, Appearance, string, number, string | null, string | null, string | null,
    ];
    this.roster.set(eid, { eid, userId, name, appearance, weapon, level, title: title ?? null, pet: pet ?? null, mount: mount ?? null });
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
        if (gained) {
          toast(`Level up! You're level ${level}. A new skill point is waiting in your Journal.`, "good", "star");
          void useJournal.getState().fetch();
        }
        break;
      }
      case EV.INVENTORY:
        patch.inv = ev[1] as InvSlot[];
        break;
      case EV.HEAL:
        if (ev[1] === this.eid) patch.quick = ev[3] as Record<string, [string, number]>;
        break;
      case EV.TOAST: {
        const args = (ev[2] ?? {}) as Record<string, string | number>;
        const text = (TOASTS[ev[1] as string] ?? String(ev[1])).replace(/\{(\w+)\}/g, (_, k: string) => String(args[k] ?? ""));
        toast(text, String(ev[1]).startsWith("delve_enter") ? "info" : "bad");
        break;
      }
      case EV.DUNGEON_ENTER: {
        const info = ev[1] as DelveInfo;
        info.layout.tiles = new Uint8Array(info.layout.tiles);
        useDelve.getState().set({ delve: info, state: info.state, boss: null, levers: {}, chests: [], near: null, panel: false });
        this.grid.setDelve({ ox: info.origin[0], oy: info.origin[1], w: info.layout.w, h: info.layout.h, solid: delveSolid(info, info.state) });
        this.pending = [];
        break;
      }
      case EV.DUNGEON_LEFT:
        this.grid.setDelve(null);
        useDelve.getState().set({ delve: null, state: null, boss: null, near: null });
        this.pending = [];
        break;
      case EV.DUNGEON:
        this.delveEvent(ev);
        break;
      case EV.WAVE:
        this.waveEvent(ev);
        break;
      case EV.BOSS:
        this.bossEvent(ev);
        break;
      case EV.LOADOUT: {
        // you equipped something: new moveset timings for the predictor, new icons for the HUD
        const [, weapon, offhand] = ev as [number, Weapon, { key?: string; type?: string; tier?: number }];
        this.info.weapon = weapon;
        this.weapon = this.rules.weapons[weapon.type] ?? this.rules.weapons.sword;
        patch.weapon = weapon;
        patch.abCdMax = this.weapon.ability.cooldown;
        const cur = useAvatar.getState().offhand;
        patch.offhand = { ...cur, ...offhand, type: offhand?.type ?? "" };
        break;
      }
      case EV.MOVE_MODS: {
        const [, s, d, r] = ev as number[];
        this.applyMods(s, d, r);
        break;
      }
      case EV.OFFHAND: {
        const [, type, charges, ms] = ev as [number, string, number, number];
        const cur = useAvatar.getState().offhand;
        patch.offhand = { ...cur, type, charges, readyAt: performance.now() + ms };
        break;
      }
      case EV.BUFF: {
        const [, key, kind, value, ms, quick] = ev as [number, string, string, number, number, Record<string, [string, number]>];
        patch.quick = quick;
        const until = performance.now() + ms;
        const keep = useAvatar.getState().buffs.filter((b) => b.until > performance.now() && b.kind !== kind && !(kind !== "stamina" && b.kind !== "stamina"));
        patch.buffs = [...keep, { key, kind, value, until }];
        const name = useSession.getState().config?.items[key]?.name ?? key;
        const what = kind === "stamina" ? "stamina refilled" : `+${Math.round(value * 100)}% ${kind}`;
        toast(`${name}: ${what}`, "good", "star");
        break;
      }
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
      case EV.FISH:
        this.fishEvent(ev);
        break;
      case EV.PING: {
        // Phase 15: someone (maybe you) pinged the map; the minimap, world map and world show it
        const [, eid, name, x, y, ms] = ev as [number, number, string, number, number, number];
        addPing({ eid, name, x, y, until: performance.now() + ms, mine: eid === this.eid });
        sfx("ping");
        break;
      }
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

  /** Phase 16b: the line goes in, something bites, you land it (or not). */
  private fishEvent(ev: RoomEvent): void {
    const fish = useFishing.getState();
    const op = ev[1] as string;
    if (op === "cast") {
      const [, , id, x, y] = ev as [number, string, number, number, number];
      fish.set({ phase: "waiting", id, x, y });
      sfx("splash");
    } else if (op === "bite") {
      const [, , id, barMs, centerMs, windowMs, rarity] = ev as [number, string, number, number, number, number, string];
      if (id !== fish.id) return;
      fish.set({ phase: "bite", barMs, centerMs, windowMs, rarity, shownAt: performance.now() });
      sfx("telegraph");
    } else if (op === "catch") {
      const [, , , species, grams] = ev as [number, string, number, string, number];
      fish.reset();
      const sp = useSession.getState().config?.fishing.species[species];
      const kg = grams >= 1000 ? `${(grams / 1000).toFixed(grams >= 10000 ? 0 : 1)} kg` : `${grams} g`;
      const big = sp?.rarity === "rare" || sp?.rarity === "legendary";
      sfx(big ? "fanfare" : "pickup");
      toast(`${sp?.rarity === "legendary" ? "LEGENDARY! " : ""}You caught a ${sp?.name ?? species} (${kg})!`, "good", `fish_${species}`);
    } else if (op === "miss") {
      fish.reset();
      toast("It got away!", "bad", "rod");
    } else if (op === "cancel") {
      fish.reset();
    }
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

/** Press while the fishing bar runs: how far along the marker is, by your own clock. */
export function reelNow(): boolean {
  const f = useFishing.getState();
  if (f.phase !== "bite" || !roomLink.send) return false;
  roomLink.send("FISH", "reel", f.id, Math.round(performance.now() - f.shownAt));
  f.set({ phase: "waiting" });
  return true;
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
