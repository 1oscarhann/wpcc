// Phase 18: the perf overlay (F3, or ?perf in the address). Frame rate, frame time, what's on stage,
// entities in view, and the socket's round trip, against the budgets in docs/PERF.md.
import { useEffect, useState } from "react";
import { gameLink } from "../../game/Game";
import { perfLink } from "../../net/ws";

export function PerfOverlay() {
  const [on, setOn] = useState(() => typeof location !== "undefined" && new URLSearchParams(location.search).has("perf"));
  const [s, setS] = useState<{ fps: number; frameMs: number; sprites: number; ents: number; rtt: number } | null>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F3") {
        e.preventDefault();
        setOn((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (!on) return;
    const id = window.setInterval(() => {
      const g = gameLink.game;
      if (g) setS({ ...g.perf(), rtt: perfLink.rtt });
    }, 500);
    return () => window.clearInterval(id);
  }, [on]);
  if (!on || !s) return null;
  const bad = (v: number, limit: number) => (v > limit ? "perf-bad" : "");
  return (
    <div className="perf-overlay panel-dark small" aria-live="off">
      <span className={bad(60 - s.fps, 15)}>{s.fps.toFixed(0)} fps</span>
      <span className={bad(s.frameMs, 22)}>{s.frameMs.toFixed(1)} ms/frame</span>
      <span className={bad(s.sprites, 4000)}>{s.sprites} on stage</span>
      <span>{s.ents} entities</span>
      <span className={bad(s.rtt, 250)}>{Math.round(s.rtt)} ms ping</span>
    </div>
  );
}
