// Shared UI primitives. Everything is pixel-themed; no default browser widgets.
import { useEffect, useRef, type ReactNode } from "react";
import type { Appearance } from "../../api/types";
import { iconIndex, manifest } from "../../assets/manifest";
import { composeAvatar, frameFor } from "../../game/avatarComposer";
import { useToasts } from "../../state/toasts";

export function Icon({ name, scale = 2, title }: { name: string; scale?: number; title?: string }) {
  const i = iconIndex(name);
  const { size, cols } = manifest.icons;
  const s = size * scale;
  const rows = Math.ceil(Object.keys(manifest.icons.names).length / cols);
  return (
    <span
      className="icon"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      title={title}
      style={{
        width: s,
        height: s,
        backgroundPosition: `${-(i % cols) * s}px ${-Math.floor(i / cols) * s}px`,
        backgroundSize: `${cols * s}px ${rows * s}px`,
      }}
    />
  );
}

export function Panel({ children, className = "", dark = false, style }: {
  children: ReactNode;
  className?: string;
  dark?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <div className={`${dark ? "panel-dark" : "panel"} ${className}`} style={style}>
      {children}
    </div>
  );
}

export function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`panel modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="row" style={{ marginBottom: 10 }}>
          <span className="ribbon">{title}</span>
          <span className="grow" />
          <button className="btn danger small icon-only" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Toasts() {
  const toasts = useToasts((s) => s.toasts);
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="panel toast row" style={{ padding: "2px 6px" }}>
          <Icon name={t.icon ?? (t.tone === "bad" ? "close" : t.tone === "good" ? "check" : "info")} />
          <span>{t.text}</span>
        </div>
      ))}
    </div>
  );
}

/** Animated character preview on a crisp, integer-scaled canvas. */
export function CharacterPreview({ look, scale = 8, dir = "down", walking = true }: {
  look: Appearance;
  scale?: number;
  dir?: string;
  walking?: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [fw, fh] = manifest.chars.frame;
  useEffect(() => {
    let raf = 0;
    let alive = true;
    composeAvatar(look).then((strip) => {
      const draw = (t: number) => {
        if (!alive || !ref.current) return;
        const ctx = ref.current.getContext("2d")!;
        ctx.imageSmoothingEnabled = false;
        ctx.clearRect(0, 0, ref.current.width, ref.current.height);
        const f = frameFor(dir, walking ? "walk" : "idle", t);
        // soft shadow
        ctx.fillStyle = "rgba(43,30,42,0.25)";
        ctx.beginPath();
        ctx.ellipse((fw * scale) / 2, (fh - 0.8) * scale, 5 * scale, 1.5 * scale, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.save();
        if (f.flip) {
          ctx.translate(fw * scale, 0);
          ctx.scale(-1, 1);
        }
        ctx.drawImage(strip, f.index * fw, 0, fw, fh, 0, 0, fw * scale, fh * scale);
        ctx.restore();
        raf = requestAnimationFrame(draw);
      };
      raf = requestAnimationFrame(draw);
    });
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
    };
  }, [look, scale, dir, walking, fw, fh]);
  return <canvas ref={ref} width={fw * scale} height={fh * scale} className="pixel" aria-label="Character preview" />;
}

export function Stepper({ label, value, options, onChange }: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  const i = Math.max(0, options.indexOf(value));
  const step = (d: number) => onChange(options[(i + d + options.length) % options.length]);
  return (
    <div className="field">
      <label>{label}</label>
      <div className="stepper">
        <button type="button" className="btn secondary small" onClick={() => step(-1)} aria-label={`Previous ${label}`}>
          ◀
        </button>
        <span className="value">{value.replace(/_/g, " ")}</span>
        <button type="button" className="btn secondary small" onClick={() => step(1)} aria-label={`Next ${label}`}>
          ▶
        </button>
      </div>
    </div>
  );
}

export function Swatches({ label, value, options, colors, onChange }: {
  label: string;
  value: string;
  options: string[];
  colors: Record<string, string[]>;
  onChange: (v: string) => void;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <div className="swatches" role="radiogroup" aria-label={label}>
        {options.map((o) => {
          const ramp = colors[o] ?? ["#888", "#888", "#aaa", "#ccc"];
          return (
            <button
              key={o}
              type="button"
              className="swatch"
              title={o}
              aria-label={o}
              aria-pressed={value === o}
              onClick={() => onChange(o)}
              style={{ background: `linear-gradient(135deg, ${ramp[3]} 0 35%, ${ramp[2]} 35% 70%, ${ramp[1]} 70%)` }}
            />
          );
        })}
      </div>
    </div>
  );
}

export function ResourceAmount({ icon, value, cap, title }: { icon: string; value: number; cap?: number; title: string }) {
  const full = cap !== undefined && value >= cap;
  return (
    <span className="row" style={{ gap: 4 }} title={title}>
      <Icon name={icon} />
      <span className="head" style={{ color: full ? "var(--gold-light)" : undefined, minWidth: 34 }}>
        {formatNum(value)}
      </span>
    </span>
  );
}

export function formatNum(n: number): string {
  const v = Math.floor(n);
  if (v >= 100_000) return `${Math.floor(v / 1000)}k`;
  if (v >= 10_000) return `${(v / 1000).toFixed(1)}k`;
  return String(v);
}

export function formatDuration(s: number): string {
  s = Math.max(0, Math.ceil(s));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
