import { useEffect, useRef, useState } from "react";
import { Game } from "../../game/Game";
import { GameSocket } from "../../net/ws";
import { useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { onVillageChange, useVillage } from "../../state/village";
import { useAvatar } from "../../state/avatar";
import { useCrafting } from "../../state/crafting";
import { AvatarHud } from "../hud/AvatarHud";
import { Bag } from "../hud/Bag";
import { CraftPanel, DiscoveryCard, RecipeBook, RevealCard } from "../hud/Crafting";
import { BuildHud } from "../hud/BuildHud";
import { MarketPanel, MerchantPanel } from "../hud/Market";
import { AwayCardModal, Guide } from "../hud/Guide";
import { RealmPanel } from "../hud/Realm";
import { JournalPanel } from "../hud/Journal";
import { PhotoBar } from "../hud/Companions";
import { PlazaPanel } from "../hud/Plaza";
import { usePlaza } from "../../state/plaza";
import { SocialPanel, useSocialSync } from "../hud/Social";
import { useJournal } from "../../state/journal";
import { useSocial } from "../../state/social";
import { MapModal } from "../hud/WorldMap";
import { PartyInvite } from "../hud/Party";
import { useRealm } from "../../state/realm";
import { useTutorial } from "../../state/tutorial";
import { useMarket } from "../../state/market";
import { Panel } from "../components/kit";
import { SettingsModal } from "./Settings";

/** Keeps the village fresh: WebSocket pushes, a polling fallback, and a refetch when a timer ends. */
function useVillageSync(ownerId: string) {
  useEffect(() => {
    const store = useVillage.getState();
    store.fetch().catch(() => toast("Couldn't load your village. Retrying…", "bad"));
    const sock = new GameSocket();
    sock.start(ownerId);
    const poll = window.setInterval(() => {
      if (!useVillage.getState().wsConnected) useVillage.getState().fetch().catch(() => undefined);
    }, 8000);
    let timer: number | null = null;
    const scheduleRefetch = () => {
      if (timer) window.clearTimeout(timer);
      const v = useVillage.getState().village;
      const next = v?.buildings
        .filter((b) => b.state !== "active" && b.completes_at_ms)
        .map((b) => b.completes_at_ms!)
        .sort((a, b) => a - b)[0];
      if (!next) return;
      const offset = useSession.getState().serverOffsetMs;
      const wait = Math.max(0, next - (Date.now() + offset)) + 700;
      // the worker pushes completions over the socket; this is the safety net
      timer = window.setTimeout(() => useVillage.getState().fetch().catch(() => undefined), wait + (useVillage.getState().wsConnected ? 1500 : 0));
    };
    const unsub = onVillageChange((prev, next) => {
      scheduleRefetch();
      if (!prev) return;
      for (const b of next.buildings) {
        const old = prev.buildings.find((p) => p.id === b.id);
        if (old && b.level > old.level) {
          const name = useSession.getState().config?.buildings[b.key]?.name ?? b.key;
          toast(old.level === 0 ? `${name} built!` : `${name} reached level ${b.level}!`, "good", "star");
        }
      }
    });
    return () => {
      sock.stop();
      window.clearInterval(poll);
      if (timer) window.clearTimeout(timer);
      unsub();
    };
  }, [ownerId]);
}

export function PlayScreen() {
  const me = useSession((s) => s.me)!;
  const host = useRef<HTMLDivElement>(null);
  const game = useRef<Game | null>(null);
  const [settings, setSettings] = useState(false);
  const [failed, setFailed] = useState(false);
  const village = useVillage((s) => s.village);
  const mode = useAvatar((s) => s.mode);
  const crafting = useCrafting();
  const market = useMarket();
  useVillageSync(me.user.id);
  useEffect(() => {
    void useTutorial.getState().load();
    void useTutorial.getState().loadAway();
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.key === "m" || e.key === "M") {
        const r = useRealm.getState();
        r.set({ mapOpen: !r.mapOpen, travelMode: false });
      }
      if (e.key === "p" || e.key === "P") {
        const a = useAvatar.getState();
        a.set({ photo: !a.photo });
      }
      if (e.key === "j" || e.key === "J") {
        const j = useJournal.getState();
        j.set({ tab: j.tab ? null : "quests" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const realmPanel = useRealm((s) => s.panel);
  const journalTab = useJournal((s) => s.tab);
  const photo = useAvatar((s) => s.photo);
  const plazaTab = usePlaza((s) => s.tab);
  const socialOpen = useSocial((s) => s.open);
  useSocialSync();

  useEffect(() => {
    if (!host.current || !village || game.current) return;
    const g = new Game(host.current);
    game.current = g;
    g.init().catch((e) => {
      console.error(e);
      setFailed(true);
    });
    return undefined;
  }, [village]);

  useEffect(() => () => {
    game.current?.destroy();
    game.current = null;
  }, []);

  return (
    <div className="play">
      <div ref={host} className="game-canvas" aria-label="Your village" />
      <div className="vignette" aria-hidden />
      {!village && (
        <div className="center" style={{ position: "absolute", inset: 0 }}>
          <Panel><div className="head">Unrolling the map…</div></Panel>
        </div>
      )}
      {failed && (
        <div className="center" style={{ position: "absolute", inset: 0 }}>
          <Panel><div className="head">Your browser couldn't start the renderer (WebGL).</div></Panel>
        </div>
      )}
      <PhotoBar />
      {photo ? null : mode === "build" ? (
        <BuildHud onSettings={() => setSettings(true)} touch={game.current?.touchMode ?? matchMedia("(pointer: coarse)").matches}
          onZoom={(d) => game.current?.zoomBy(d)} />
      ) : (
        <AvatarHud onSettings={() => setSettings(true)} touch={game.current?.touchMode ?? matchMedia("(pointer: coarse)").matches} />
      )}
      {mode === "build" && crafting.bagOpen && <Bag onClose={() => crafting.set({ bagOpen: false })} />}
      {crafting.bookOpen && <RecipeBook onClose={() => crafting.set({ bookOpen: false })} />}
      {crafting.stationId && <CraftPanel stationId={crafting.stationId} onClose={() => crafting.set({ stationId: null })} />}
      {mode === "build" && market.marketOpen && <MarketPanel onClose={() => market.set({ marketOpen: false })} />}
      {mode === "avatar" && market.merchantOpen && <MerchantPanel onClose={() => market.set({ merchantOpen: false })} />}
      {realmPanel && mode === "build" && <RealmPanel onClose={() => useRealm.getState().set({ panel: null })} />}
      {socialOpen && <SocialPanel onClose={() => useSocial.getState().set({ open: false, visiting: null })} />}
      {journalTab && <JournalPanel onClose={() => useJournal.getState().set({ tab: null })} />}
      {plazaTab && <PlazaPanel onClose={() => usePlaza.getState().set({ tab: null })} />}
      <MapModal />
      {mode === "avatar" && <PartyInvite />}
      {village && <Guide />}
      <AwayCardModal />
      <DiscoveryCard />
      <RevealCard />
      {settings && <SettingsModal onClose={() => setSettings(false)} />}
    </div>
  );
}
