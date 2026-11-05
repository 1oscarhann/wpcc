import { useState } from "react";
import { api } from "../../api/client";
import type { Appearance, AudioSettings } from "../../api/types";
import { useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { Icon, Modal } from "../components/kit";
import { CharacterCreator } from "./Auth";

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const me = useSession((s) => s.me)!;
  const patchMe = useSession((s) => s.patchMe);
  const logout = useSession((s) => s.logout);
  const [audio, setAudio] = useState<AudioSettings>(me.settings.audio);
  const [editingLook, setEditingLook] = useState(false);
  const [look, setLook] = useState<Appearance>(me.avatar.appearance);

  async function save(next: AudioSettings) {
    setAudio(next);
    try {
      localStorage.setItem("hf.audio", JSON.stringify(next));
    } catch {
      /* storage unavailable: server copy is the source of truth */
    }
    await api("/api/me/settings", { method: "PUT", body: { audio: next } });
    patchMe((m) => ({ ...m, settings: { ...m.settings, audio: next } }));
  }

  const reduceMotion = Boolean((me.settings.graphics as { reduce_motion?: boolean } | undefined)?.reduce_motion);
  async function saveGraphics(next: Record<string, unknown>) {
    document.documentElement.dataset.reduceMotion = next.reduce_motion ? "1" : "0";
    patchMe((m) => ({ ...m, settings: { ...m.settings, graphics: next } }));
    await api("/api/me/settings", { method: "PUT", body: { graphics: next } });
  }

  if (editingLook) {
    return (
      <div className="modal-backdrop">
        <CharacterCreator look={look} setLook={setLook} onBack={() => setEditingLook(false)} doneLabel="Save look"
          onDone={async () => {
            await api("/api/avatar/appearance", { method: "PUT", body: { appearance: look } });
            patchMe((m) => ({ ...m, avatar: { ...m.avatar, appearance: look } }));
            toast("Looking good!", "good");
            setEditingLook(false);
          }} />
      </div>
    );
  }

  const slider = (key: "master" | "music" | "sfx", label: string) => (
    <div className="field" key={key}>
      <label htmlFor={`vol-${key}`}>{label}: {Math.round(audio[key] * 100)}%</label>
      <input id={`vol-${key}`} type="range" className="slider" min={0} max={1} step={0.05} value={audio[key]}
        onChange={(e) => setAudio({ ...audio, [key]: Number(e.target.value) })}
        onPointerUp={() => save(audio)} onKeyUp={() => save(audio)} />
    </div>
  );

  return (
    <Modal title="Settings" onClose={onClose}>
      <div className="col" style={{ gap: 14 }}>
        <h3>Sound</h3>
        {slider("master", "Master")}
        {slider("music", "Music & ambience")}
        {slider("sfx", "Effects")}
        <label className="row">
          <input type="checkbox" className="toggle" checked={audio.muted}
            onChange={(e) => save({ ...audio, muted: e.target.checked })} />
          <Icon name={audio.muted ? "mute" : "sound"} /> Mute everything
        </label>
        <h3>Motion</h3>
        <label className="row">
          <input type="checkbox" className="toggle" checked={reduceMotion}
            onChange={(e) => void saveGraphics({ ...(me.settings.graphics ?? {}), reduce_motion: e.target.checked })} />
          Reduce screen shake and hit-stop
        </label>
        <h3>Hero</h3>
        <button className="btn secondary" onClick={() => setEditingLook(true)}>Change my look</button>
        <h3>Account</h3>
        <p className="small muted" style={{ margin: 0 }}>Signed in as <b>{me.user.username}</b></p>
        <button className="btn danger" onClick={logout}>Log out</button>
      </div>
    </Modal>
  );
}
