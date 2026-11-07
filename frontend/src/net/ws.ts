// One WebSocket per tab, msgpack frames (docs/PROTOCOL.md). Reconnects with backoff;
// while it's down the HUD falls back to polling (see useVillageSync).
import { onWaveNotify } from "../state/defence";
import { decode, encode } from "@msgpack/msgpack";
import protocol from "../../../shared/protocol.json";
import { onRealmNotify, useRealm, type MateVillage } from "../state/realm";
import type { VillageState } from "../api/types";
import { gridLink } from "../sim/grid";
import type { Rules } from "../sim/rules";
import { useAvatar } from "../state/avatar";
import { useSession } from "../state/session";
import { toast } from "../state/toasts";
import { useVillage } from "../state/village";
import { RoomClient, roomLink, setRoomClient } from "./room";

const C2S = Object.fromEntries(Object.entries(protocol.client_to_server).map(([k, v]) => [k, parseInt(v, 16)]));
const S2C_NAME = Object.fromEntries(
  Object.entries(protocol.server_to_client).map(([k, v]) => [parseInt(v, 16), k]),
) as Record<number, string>;

/** Dev-only latency injection (PLAN §6: "test at 150 ms before calling it done"): `?lag=150` delays every
 *  frame by half that in each direction, plus a little jitter, without ever reordering. */
const LAG_MS = import.meta.env.DEV ? Number(new URLSearchParams(location.search).get("lag") ?? 0) : 0;

/** One direction of a fake slow link: jittery delay, strictly first-in first-out (like TCP). */
class LagLink {
  private q: { at: number; fn: () => void }[] = [];
  private last = 0;
  private timer = 0;

  push(fn: () => void): void {
    const at = Math.max(this.last, performance.now() + LAG_MS / 2 + Math.random() * LAG_MS * 0.1);
    this.last = at;
    this.q.push({ at, fn });
    this.schedule();
  }

  private pump = (): void => {
    this.timer = 0;
    const now = performance.now();
    while (this.q.length && this.q[0].at <= now + 1) this.q.shift()!.fn();
    this.schedule();
  };

  private schedule(): void {
    if (this.timer || !this.q.length) return;
    this.timer = window.setTimeout(this.pump, Math.max(0, this.q[0].at - performance.now()));
  }
}
const uplink = new LagLink();
const downlink = new LagLink();

export class GameSocket {
  private ws: WebSocket | null = null;
  private retry = 0;
  private closed = false;
  private pingTimer: number | null = null;
  private ownerId: string | null = null;

  constructor(private url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`) {}

  start(ownerId: string): void {
    this.ownerId = ownerId;
    this.closed = false;
    roomLink.send = (op, ...fields) => this.send(op, ...fields);
    this.connect();
  }

  stop(): void {
    this.closed = true;
    roomLink.send = null;
    setRoomClient(null);
    useAvatar.getState().set({ mode: "build" });
    if (this.pingTimer) window.clearInterval(this.pingTimer);
    this.ws?.close();
    this.ws = null;
  }

  private send(op: string, ...fields: unknown[]): void {
    const frame = encode([C2S[op], ...fields]);
    const go = () => {
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(frame);
    };
    if (LAG_MS > 0) uplink.push(go);
    else go();
  }

  private connect(): void {
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      useVillage.getState().setWs(true);
      this.send("HELLO", protocol.version, "web", false);
      if (this.ownerId) this.send("SUB_VILLAGE", this.ownerId);
      for (const id of Object.keys(useRealm.getState().mates)) this.send("SUB_VILLAGE", id); // realm-mates (Phase 9)
      // back in the world after a reconnect (the server keeps the avatar for a 5 s grace)
      const mode = useAvatar.getState().mode;
      if (mode === "avatar" || mode === "entering") this.send("ENTER_AVATAR");
      this.pingTimer = window.setInterval(() => this.send("PING", Date.now()), 5000);
    };
    ws.onmessage = (ev) => {
      if (LAG_MS > 0) downlink.push(() => this.onMessage(ev.data as ArrayBuffer));
      else this.onMessage(ev.data as ArrayBuffer);
    };
    ws.onclose = () => {
      useVillage.getState().setWs(false);
      if (this.pingTimer) window.clearInterval(this.pingTimer);
      if (this.closed) return;
      const delay = Math.min(15000, 500 * 2 ** this.retry++) * (0.75 + Math.random() * 0.5);
      window.setTimeout(() => !this.closed && this.connect(), delay);
    };
    ws.onerror = () => ws.close();
  }

  private onMessage(data: ArrayBuffer): void {
    const msg = decode(new Uint8Array(data)) as unknown[];
    const op = S2C_NAME[msg[0] as number];
    switch (op) {
      case "VILLAGE_STATE": {
        const me = useSession.getState().me?.user.id;
        if (!me || msg[1] === me) useVillage.getState().apply(msg[3] as VillageState);
        else useRealm.getState().applyMate(msg[3] as MateVillage); // a realm-mate's village (Phase 9)
        break;
      }
      case "NOTIFY":
        if (msg[1] === "realm") void onRealmNotify(useRealm.getState().realm?.id ?? null);
        else if (msg[1] === "wave") onWaveNotify(msg[2] as Record<string, unknown>);
        break;
      case "PONG": {
        const [clientMs, serverMs] = [msg[1] as number, msg[2] as number];
        const rtt = Date.now() - clientMs;
        useSession.setState({ serverOffsetMs: serverMs + rtt / 2 - Date.now() });
        break;
      }
      case "SNAPSHOT":
        roomLink.client?.onSnapshot(msg);
        break;
      case "ROOM_JOINED": {
        const grid = gridLink.grid;
        const rules = useSession.getState().config?.sim as Rules | undefined;
        if (!grid || !rules) break;
        setRoomClient(new RoomClient((op, ...f) => this.send(op, ...f), msg, grid, rules));
        break;
      }
      case "ROOM_LEFT":
        if (msg[1] === protocol.room_left.moved) toast("Your village moved realms. Taking you home…", "good", "home");
        setRoomClient(null);
        useAvatar.getState().set({ mode: "build", bagOpen: false });
        break;
      case "BLOCKS":
        roomLink.client?.onBlocks(msg);
        break;
      case "ERROR": {
        const key = msg[2] as string;
        if (key === "err.in_combat") {
          toast("You can't head home mid-fight!", "bad");
          if (useAvatar.getState().mode === "leaving") useAvatar.getState().set({ mode: "avatar" });
        } else if (useAvatar.getState().mode === "entering") {
          toast("Couldn't step out into the world. Try again?", "bad");
          useAvatar.getState().set({ mode: "build" });
        }
        break;
      }
      case "KICK":
        this.closed = true;
        break;
      default:
        break;
    }
  }
}
