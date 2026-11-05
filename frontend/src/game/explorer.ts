// Phase 9: exploration in Avatar Mode. Reveals fog as you walk (same rule as the server), notices when
// you're standing at a waystone (the HUD offers "Travel"), and plays the attune and teleport moments.
import { EV, type RoomEvent } from "../net/room";
import { useRealm } from "../state/realm";
import { toast } from "../state/toasts";
import type { AvatarWorld, WorldHost } from "./avatarWorld";
import { sfx } from "./sfx";

const T = 16;

export class Explorer {
  private t = 0;
  private near: number | null = null;

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
    useRealm.getState().set({ nearWaystone: null, party: null, invite: null, travelMode: false });
  }
}
