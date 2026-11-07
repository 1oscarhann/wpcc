// Phase 14: the villagers panel (who lives here, what they do), the happiness chip, and how the village
// scores on beauty. Drag a villager card onto a building on the map to put them to work there.
import { useEffect, useState } from "react";
import { create } from "zustand";
import type { Appearance, VillageState, VillagerView } from "../../api/types";
import { composeAvatar } from "../../game/avatarComposer";
import { serverNow, useSession } from "../../state/session";
import { useVillage } from "../../state/village";
import { formatDuration, Icon, Modal } from "../components/kit";

export const useVillagersUi = create<{ open: boolean; dragging: boolean; set: (p: { open?: boolean; dragging?: boolean }) => void }>(
  (set) => ({ open: false, dragging: false, set: (p) => set(p) }),
);

const MOOD_FACE: Record<string, string> = {
  happy: "😊", hungry: "😋", crowded: "😣", ugly: "😕", bored: "🥱", leaving: "😢",
};
const MOOD_TEXT: Record<string, string> = {
  happy: "Everyone's content.",
  hungry: "They're hungry: more Farms or Fishing Docks.",
  crowded: "It's cramped: build or upgrade Houses.",
  ugly: "It's a bit drab: decorations, paths and greenery help.",
  bored: "Nothing to do after work: a Tavern near the homes.",
  leaving: "They're miserable. Someone will move away soon!",
};

const portraits = new Map<string, string>();
function usePortrait(id: string, look: Appearance): string | null {
  const [url, setUrl] = useState<string | null>(() => portraits.get(id) ?? null);
  useEffect(() => {
    if (portraits.has(id)) return;
    let alive = true;
    void composeAvatar(look).then((strip) => {
      const c = document.createElement("canvas");
      c.width = 32;
      c.height = 32;
      const g = c.getContext("2d")!;
      g.imageSmoothingEnabled = false;
      g.drawImage(strip, 0, 0, 16, 16, 0, 0, 32, 32); // head and shoulders of the first frame
      const u = c.toDataURL();
      portraits.set(id, u);
      if (alive) setUrl(u);
    });
    return () => {
      alive = false;
    };
  }, [id, look]);
  return url;
}

export function HappinessChip({ v }: { v: VillageState }) {
  const h = v.happiness;
  if (!h) return null;
  const low = h.value < (useSession.getState().config?.villagers.leave_below ?? 20);
  return (
    <button className={`hud-bar hud-chip happy-chip ${low ? "sad" : ""}`} onClick={() => useVillagersUi.getState().set({ open: true })}
      title={`Happiness ${h.value} · Beauty ${v.beauty.score} · ${v.housing.used}/${v.housing.cap} villagers`} aria-label="Villagers">
      <span aria-hidden>{MOOD_FACE[h.mood] ?? "🙂"}</span> {h.value}
      <span className="hide-narrow"> · <Icon name="home" scale={1.5} /> {v.housing.used}/{v.housing.cap}</span>
    </button>
  );
}

function Factor({ label, value, weight }: { label: string; value: number; weight: number }) {
  return (
    <div className="row small factor" style={{ gap: 6 }}>
      <span style={{ width: 70 }}>{label}</span>
      <div className="factor-track grow"><div className="factor-fill" style={{ width: `${Math.round(value * 100)}%` }} /></div>
      <span className="muted" style={{ width: 34, textAlign: "right" }}>{Math.round(weight * 100)}%</span>
    </div>
  );
}

function VillagerCard({ v, info }: { v: VillageState; info: VillagerView }) {
  const config = useSession((s) => s.config)!;
  const assign = useVillage((s) => s.assignVillager);
  const url = usePortrait(info.id, info.look);
  const name = (id: string | null) => {
    const b = id ? v.buildings.find((x) => x.id === id) : undefined;
    return b ? config.buildings[b.key]?.name ?? b.key : null;
  };
  const options = Object.entries(v.job_slots)
    .map(([id, s]) => ({ id, s, name: name(id) ?? "?" }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return (
    <div className="villager-card" draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/villager", info.id);
        e.dataTransfer.effectAllowed = "move";
        useVillagersUi.getState().set({ dragging: true });
      }}
      onDragEnd={() => useVillagersUi.getState().set({ dragging: false })}>
      <div className="villager-portrait">{url && <img src={url} alt="" width={32} height={32} />}</div>
      <div className="col grow" style={{ gap: 2, minWidth: 0 }}>
        <span className="head" style={{ fontSize: 15 }}>{info.name}</span>
        <span className="small muted">
          {name(info.home) ? `Lives in a ${name(info.home)}` : "No bed!"}
          {info.traits.length ? ` · ${info.traits.map((t) => t.replace(/_/g, " ")).join(", ")}` : ""}
        </span>
      </div>
      <select className="job-select" aria-label={`Job for ${info.name}`} value={info.job ?? ""}
        onChange={(e) => void assign(info.id, e.target.value || null)}>
        <option value="">Day off</option>
        {options.map((o) => (
          <option key={o.id} value={o.id} disabled={o.id !== info.job && o.s.workers >= o.s.slots}>
            {o.name} ({o.s.workers}/{o.s.slots})
          </option>
        ))}
      </select>
    </div>
  );
}

export function VillagersPanel() {
  const open = useVillagersUi((s) => s.open);
  const dragging = useVillagersUi((s) => s.dragging);
  const v = useVillage((s) => s.village);
  const config = useSession((s) => s.config);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!open) return;
    const id = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [open]);
  if (!open || !v || !config || !v.happiness) return null;
  const close = () => useVillagersUi.getState().set({ open: false });
  const h = v.happiness;
  const w = config.villagers.weights;
  const now = serverNow();
  return (
    <div className={dragging ? "villagers-dragging" : ""}>
      <Modal title="Villagers" onClose={close} wide>
        <div className="villagers-top">
          <div className="col" style={{ gap: 4, minWidth: 0 }}>
            <div className="row" style={{ gap: 8, alignItems: "baseline" }}>
              <span className="head" style={{ fontSize: 28 }}>{MOOD_FACE[h.mood]} {h.value}</span>
              <span className="small">{MOOD_TEXT[h.mood]}</span>
            </div>
            <Factor label="Beauty" value={h.beauty} weight={w.beauty} />
            <Factor label="Housing" value={h.housing} weight={w.housing} />
            <Factor label="Food" value={h.food} weight={w.food} />
            <Factor label="Tavern" value={h.tavern} weight={w.tavern} />
          </div>
          <div className="col small beauty-box" style={{ gap: 2 }}>
            <span className="head">Beauty {v.beauty.score}</span>
            <span>Decorations +{v.beauty.decor}</span>
            <span>Variety +{v.beauty.variety}</span>
            <span>Linked by paths +{v.beauty.connected} <span className="muted">({v.beauty.linked})</span></span>
            <span>Nature +{v.beauty.nature}</span>
          </div>
        </div>
        <p className="small" style={{ margin: "8px 0" }}>
          <Icon name="home" scale={1.5} /> {v.housing.used}/{v.housing.cap} beds · eats {v.food_demand} food/h
          {v.next_arrival_ms ? ` · someone new arrives in ${formatDuration(Math.max(0, (v.next_arrival_ms - now) / 1000))}` : v.housing.used >= v.housing.cap ? " · no room for newcomers" : ` · newcomers want happiness ${config.villagers.min_happiness}+`}
          {h.leave_at_ms ? <b style={{ color: "var(--red)" }}> · someone leaves in {formatDuration(Math.max(0, (h.leave_at_ms - now) / 1000))}!</b> : null}
        </p>
        <div className="villager-list">
          {v.villagers.length === 0 ? (
            <span className="small muted">Nobody lives here yet. Build a House and they'll come.</span>
          ) : (
            v.villagers.map((x) => <VillagerCard key={x.id} v={v} info={x} />)
          )}
        </div>
        <p className="small muted" style={{ marginBottom: 0 }}>
          Workers add {Math.round(config.villagers.production_bonus * 100)}% output each at production buildings and speed up
          crafting stations. Guards at a Guard Post fight off raids. Tip: drag a villager onto a building on the map.
        </p>
      </Modal>
    </div>
  );
}
