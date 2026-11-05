// Phase 9: exploration in Avatar Mode. Reveals fog as you walk (same rule as the server), notices when
// you're standing at a waystone (the HUD offers "Travel"), and plays the attune and teleport moments.
import { EV, type RoomEvent } from "../net/room";
import { useRealm } from "../state/realm";
import { useSession } from "../state/session";
import { toast } from "../state/toasts";
import type { AvatarWorld, WorldHost } from "./avatarWorld";
import { sfx } from "./sfx";

const T = 16;

export class Explorer {
  private t = 0;
  private near: number | null = null;
  private nearPoi: number | null = null;

  constructor(private host: WorldHost, private avatar: AvatarWorld) {}

  update(dms: number): void {
    this.t += dms;
    if (this.t < 250) return;
    this.t = 0;
    const p = this.avatar.client.drawPos();
    const store = useRealm.getState();
    store.reveal(p.x, p.y);
    const o = store.overview;
    if (!o) return;
    let near: number | null = null;
    for (const w of o.waystones) {
      if (Math.hypot(w.x + 0.5 - p.x, w.y + 0.5 - p.y) <= o.use_radius) near = w.index;
    }
    if (near !== this.near) {
      this.near = near;
      store.set({ nearWaystone: near });
    }
    let poi: number | null = null;
    let best = Infinity;
    for (const q of o.pois ?? []) {
      const d = Math.hypot(q.x + 0.5 - p.x, q.y + 0.5 - p.y);
      if (d <= o.poi_radius && d < best) {
        best = d;
        poi = q.index;
      }
    }
    if (poi !== this.nearPoi) {
      this.nearPoi = poi;
      store.set({ nearPoi: poi });
    }
  }

  /** Phase 10: what happened when you used a point of interest. */
  private onPoi(index: number, kind: string, data: Record<string, unknown>): void {
    const store = useRealm.getState();
    const q = store.overview?.pois[index];
    const x = ((q?.x ?? 0) + 0.5) * T;
    const y = ((q?.y ?? 0) + 0.5) * T;
    const cfg = useSession.getState().config;
    const name = (k: string) => cfg?.items[k]?.name ?? cfg?.resources[k]?.name ?? k;
    if (kind === "ruins") {
      const loot = Object.entries((data.loot as Record<string, number>) ?? {}).map(([k, n]) => `${n} ${name(k)}`);
      toast(`The chest creaks open: ${data.coins} coins${loot.length ? `, ${loot.join(", ")}` : ""}!`, "good", "chest");
      sfx("reveal");
      this.host.sparkles(x, y - 6);
      store.markPoi(index);
    } else if (kind === "shrine") {
      store.set({ blessing: { name: String(data.name), text: String(data.text), until: Date.now() + Number(data.secs) * 1000 } });
      toast(`${data.name}: ${data.text}`, "good", "sun");
      sfx("shimmer");
      this.host.sparkles(x, y - 14);
      const p = this.avatar.client.drawPos();
      this.host.sparkles(p.x * T, p.y * T - 12);
      store.markPoi(index);
    } else if (kind === "lore_stone") {
      store.set({ lore: { title: String(data.title), text: String(data.text), first: Boolean(data.first), xp: Number(data.xp ?? 0) } });
      sfx("reveal");
      store.markPoi(index);
    } else if (kind === "cave") {
      toast("Planks and old runes seal the cave mouth. Something stirs deep inside… (Dungeons open in a later update.)", "info", "map");
      store.markPoi(index);
    } else if (kind === "merchant") {
      store.set({ wildMerchant: String(data.merchant_id) });
      store.markPoi(index);
    } else if (kind === "lost_villager") {
      toast(`${data.name} thanks you and sets off for your village! (+${data.coins} coins)`, "good", "home");
      sfx("levelup");
      this.host.sparkles(x, y - 8);
      store.markPoi(index);
    }
  }

  onEvent(ev: RoomEvent): void {
    const kind = ev[0] as number;
    if (kind === EV.WAYSTONE) {
      const [, , name, attuned] = ev as [number, number, string, number[]];
      useRealm.getState().attune(attuned);
      toast(`Waystone attuned: ${name}. You can travel here from any other stone.`, "good", "map");
      sfx("shimmer");
      const p = this.avatar.client.drawPos();
      this.host.sparkles(p.x * T, p.y * T - 10);
    } else if (kind === EV.POI) {
      const [, index, pk, data] = ev as [number, number, string, Record<string, unknown>];
      this.onPoi(index, pk, data ?? {});
    } else if (kind === EV.TELEPORT) {
      const [, x, y] = ev as number[];
      sfx("reveal");
      this.host.sparkles(x * T, y * T - 10);
      this.host.dust(x * T, y * T);
      useRealm.getState().set({ mapOpen: false, travelMode: false });
    } else if (kind === EV.PARTY) {
      useRealm.getState().set({ party: (ev[1] as ReturnType<typeof useRealm.getState>["party"]) ?? null });
    } else if (kind === EV.PARTY_INVITE) {
      useRealm.getState().set({ invite: { party: ev[1] as string, from: ev[2] as string } });
      sfx("pickup");
    }
  }

  destroy(): void {
    useRealm.getState().set({ nearWaystone: null, nearPoi: null, party: null, invite: null, travelMode: false });
  }
}
