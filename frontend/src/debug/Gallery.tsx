// Hidden /debug page: every sprite, tile, character layer, icon, UI component, rarity colour and font.
import { useEffect, useRef, useState } from "react";
import type { Appearance } from "../api/types";
import { manifest } from "../assets/manifest";
import { useSession } from "../state/session";
import { CharacterPreview, Icon, Panel } from "../ui/components/kit";

interface AtlasFrame {
  frame: { x: number; y: number; w: number; h: number };
}

function useAtlas() {
  const [atlas, setAtlas] = useState<{ img: HTMLImageElement; frames: Record<string, AtlasFrame> } | null>(null);
  useEffect(() => {
    (async () => {
      const json = await (await fetch(manifest.atlases.world)).json();
      const img = new Image();
      img.src = manifest.atlases.world.replace(/[^/]+$/, json.meta.image);
      await img.decode();
      setAtlas({ img, frames: json.frames });
    })();
  }, []);
  return atlas;
}

function Sprite({ atlas, name, scale }: { atlas: NonNullable<ReturnType<typeof useAtlas>>; name: string; scale: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const f = atlas.frames[name]?.frame;
  useEffect(() => {
    if (!f || !ref.current) return;
    const ctx = ref.current.getContext("2d")!;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(atlas.img, f.x, f.y, f.w, f.h, 0, 0, f.w * scale, f.h * scale);
  }, [atlas, f, scale]);
  if (!f) return <span className="hint bad">missing {name}</span>;
  return <canvas ref={ref} width={f.w * scale} height={f.h * scale} className="pixel" title={name} />;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Panel style={{ marginBottom: 16 }}>
      <h2 style={{ marginBottom: 8 }}>{title}</h2>
      {children}
    </Panel>
  );
}

const grid: React.CSSProperties = { display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-end" };

export function DebugGallery() {
  const atlas = useAtlas();
  const config = useSession((s) => s.config);
  const loadConfig = useSession((s) => s.loadConfig);
  useEffect(() => {
    loadConfig().catch(() => undefined);
  }, [loadConfig]);
  const names = Object.keys(manifest.sprites);
  const group = (prefix: string) => names.filter((n) => n.startsWith(prefix));
  const looks: Appearance[] = [];
  if (config) {
    const cr = config.avatar.creator;
    for (let i = 0; i < 8; i++) {
      looks.push({
        body: cr.bodies[i % cr.bodies.length], skin: cr.skin_tones[i % cr.skin_tones.length],
        hair_style: cr.hair_styles[i % cr.hair_styles.length], hair_color: cr.hair_colors[(i * 3) % cr.hair_colors.length],
        eyes: cr.eye_styles[i % cr.eye_styles.length], eye_color: cr.eye_colors[i % cr.eye_colors.length],
        outfit: cr.outfits[i % cr.outfits.length], outfit_color: cr.outfit_colors[(i * 5) % cr.outfit_colors.length],
      });
    }
  }
  const tiers = ["common", "uncommon", "rare", "epic", "legendary"];
  return (
    <div style={{ padding: 16, background: "var(--grass-dark)", minHeight: "100%" }}>
      <h1 style={{ color: "var(--paper-light)", marginBottom: 12 }}>Debug gallery</h1>
      <Section title="Fonts">
        <div className="col">
          <div className="head" style={{ fontSize: 40 }}>Pixelify Sans — Hearthforge 0123</div>
          <div className="head" style={{ fontSize: 22 }}>Pixelify Sans 22 — The quick brown fox</div>
          <div style={{ fontSize: 20 }}>Fredoka 20 — The quick brown fox jumps over the lazy dog.</div>
          <div style={{ fontSize: 15 }}>Fredoka 15 — Small print for tooltips and hints.</div>
        </div>
      </Section>
      <Section title="Rarity colours">
        <div className="row" style={{ flexWrap: "wrap" }}>
          {tiers.map((t) => (
            <span key={t} className="rarity" style={{ background: `var(--rarity-${t})`, textTransform: "capitalize" }}>{t}</span>
          ))}
        </div>
      </Section>
      <Section title="Buttons & widgets">
        <div className="row" style={{ flexWrap: "wrap" }}>
          <button className="btn">Primary</button>
          <button className="btn secondary">Secondary</button>
          <button className="btn danger">Danger</button>
          <button className="btn gold">Gold</button>
          <button className="btn" disabled>Disabled</button>
          <button className="btn small secondary">Small</button>
          <button className="btn icon-only small" aria-label="Build"><Icon name="build" /></button>
          <span className="ribbon">Ribbon title</span>
          <span className="panel-dark">Dark panel</span>
        </div>
        <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
          <input className="input" placeholder="Text field" style={{ maxWidth: 220 }} />
          <input type="range" className="slider" style={{ maxWidth: 200 }} defaultValue={60} />
          <input type="checkbox" className="toggle" defaultChecked />
          <span className="slot center" style={{ width: 60, height: 60 }}><Icon name="sword" scale={3} /></span>
        </div>
      </Section>
      <Section title="Icons">
        <div style={grid}>
          {Object.keys(manifest.icons.names).map((n) => (
            <span key={n} className="col" style={{ alignItems: "center", gap: 2 }}>
              <Icon name={n} scale={3} />
              <span className="small">{n}</span>
            </span>
          ))}
        </div>
      </Section>
      <Section title="Characters (random looks, all directions)">
        <div style={grid}>
          {looks.map((l, i) => (
            <span key={i} className="row" style={{ gap: 2 }}>
              {(["down", "left", "up", "right"] as const).map((d) => (
                <CharacterPreview key={d} look={l} scale={4} dir={d} />
              ))}
            </span>
          ))}
        </div>
      </Section>
      {atlas && (
        <>
          <Section title="Buildings (levels 1–5, rotations, scaffolds)">
            <div style={grid}>{group("building.").map((n) => <Sprite key={n} atlas={atlas} name={n} scale={2} />)}</div>
          </Section>
          <Section title="Nature & props">
            <div style={grid}>{group("obj.").map((n) => <Sprite key={n} atlas={atlas} name={n} scale={3} />)}</div>
          </Section>
          <Section title="Terrain tiles (grass, flowers, path/water/cobble autotiles)">
            <div style={{ ...grid, gap: 2 }}>{group("tile.").map((n) => <Sprite key={n} atlas={atlas} name={n} scale={2} />)}</div>
          </Section>
          <Section title="FX">
            <div style={grid}>{group("fx.").map((n) => <Sprite key={n} atlas={atlas} name={n} scale={4} />)}</div>
          </Section>
        </>
      )}
    </div>
  );
}
