import { useEffect, useRef, useState } from "react";
import { Game } from "../../game/Game";
import { GameSocket } from "../../net/ws";
import { useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { onVillageChange, useVillage } from "../../state/village";
import { BuildHud } from "../hud/BuildHud";
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
  useVillageSync(me.user.id);

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
      <BuildHud onSettings={() => setSettings(true)} touch={game.current?.touchMode ?? matchMedia("(pointer: coarse)").matches}
        onZoom={(d) => game.current?.zoomBy(d)} />
      {settings && <SettingsModal onClose={() => setSettings(false)} />}
    </div>
  );
}
