// One WebSocket per tab, msgpack frames (docs/PROTOCOL.md). Reconnects with backoff;
// while it's down the HUD falls back to polling (see useVillageSync).
import { decode, encode } from "@msgpack/msgpack";
import protocol from "../../../shared/protocol.json";
import type { VillageState } from "../api/types";
import { useSession } from "../state/session";
import { useVillage } from "../state/village";

const C2S = Object.fromEntries(Object.entries(protocol.client_to_server).map(([k, v]) => [k, parseInt(v, 16)]));
const S2C_NAME = Object.fromEntries(
  Object.entries(protocol.server_to_client).map(([k, v]) => [parseInt(v, 16), k]),
) as Record<number, string>;

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
    this.connect();
  }

  stop(): void {
    this.closed = true;
    if (this.pingTimer) window.clearInterval(this.pingTimer);
    this.ws?.close();
    this.ws = null;
  }

  private send(op: string, ...fields: unknown[]): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(encode([C2S[op], ...fields]));
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
      this.pingTimer = window.setInterval(() => this.send("PING", Date.now()), 5000);
    };
    ws.onmessage = (ev) => this.onMessage(ev.data as ArrayBuffer);
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
      case "VILLAGE_STATE":
        useVillage.getState().apply(msg[3] as VillageState);
        break;
      case "PONG": {
        const [clientMs, serverMs] = [msg[1] as number, msg[2] as number];
        const rtt = Date.now() - clientMs;
        useSession.setState({ serverOffsetMs: serverMs + rtt / 2 - Date.now() });
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
