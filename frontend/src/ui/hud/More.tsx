// Phase 18: phones don't fit every HUD button in a row. The key ones stay; the rest go in a "More" popover
// that carries their notification dots.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "../components/kit";

export function useNarrow(px = 640): boolean {
  const q = `(max-width: ${px}px)`;
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [q]);
  return narrow;
}

/** One labelled row inside the More popover. */
export function MoreItem({ icon, label, dot, onClick }: { icon: string; label: string; dot?: number | string; onClick: () => void }) {
  return (
    <button className="btn secondary small more-item" onClick={onClick}>
      <Icon name={icon} scale={1.5} /> <span className="grow">{label}</span>
      {dot ? <span className="dot-count">{dot}</span> : null}
    </button>
  );
}

export function MoreMenu({ dot, children, up = true }: { dot?: number; children: ReactNode; up?: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", off);
    return () => window.removeEventListener("pointerdown", off);
  }, [open]);
  return (
    <div className="more-wrap" ref={ref}>
      <button className="btn secondary icon-only has-dot" onClick={() => setOpen(!open)} aria-label="More" aria-expanded={open} title="More">
        <Icon name="more" />
        {dot ? <span className="dot-count">{dot}</span> : null}
      </button>
      {open && (
        <div className={`panel more-pop col ${up ? "up" : "down"}`} role="menu" onClick={() => setOpen(false)}>
          {children}
        </div>
      )}
    </div>
  );
}
