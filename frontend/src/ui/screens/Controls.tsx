// Phase 18: rebind keys (press the new one), reset to the defaults, and the gamepad layout.
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { PAD_HELP } from "../../game/gamepad";
import { ACTIONS, current, DEFAULTS, keyLabel, loadKeymap, overrides, type Action } from "../../game/keymap";
import { useSession } from "../../state/session";
import { toast } from "../../state/toasts";

export function ControlsSection() {
  const patchMe = useSession((s) => s.patchMe);
  const [map, setMap] = useState<Record<Action, string[]>>(current);
  const [listening, setListening] = useState<Action | null>(null);
  const [pad, setPad] = useState(false);

  useEffect(() => {
    const on = () => setPad(Array.from(navigator.getGamepads?.() ?? []).some((g) => g?.connected));
    on();
    window.addEventListener("gamepadconnected", on);
    window.addEventListener("gamepaddisconnected", on);
    return () => {
      window.removeEventListener("gamepadconnected", on);
      window.removeEventListener("gamepaddisconnected", on);
    };
  }, []);

  const save = async (next: Record<Action, string[]>) => {
    setMap(next);
    const keybinds = overrides(next);
    loadKeymap(keybinds);
    patchMe((m) => ({ ...m, settings: { ...m.settings, keybinds } }));
    try {
      await api("/api/me/settings", { method: "PUT", body: { keybinds } });
    } catch {
      toast("Couldn't save your keys. They'll work until you reload.", "bad");
    }
  };

  useEffect(() => {
    if (!listening) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const k = e.key.toLowerCase();
      if (k === "escape") return setListening(null);
      const next = { ...map };
      for (const a of Object.keys(next) as Action[]) next[a] = next[a].filter((x) => x !== k); // one action per key
      next[listening] = [k, ...map[listening].filter((x) => x !== k)].slice(0, 2);
      setListening(null);
      void save(next);
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  });

  const groups = ["Move", "Fight", "World"] as const;
  return (
    <div className="col controls" style={{ gap: 8 }}>
      <p className="small muted" style={{ margin: 0 }}>Click a key, then press the new one. Each key does one thing.</p>
      {groups.map((g) => (
        <div key={g} className="col" style={{ gap: 2 }}>
          <span className="head small">{g}</span>
          {ACTIONS.filter((a) => a.group === g).map((a) => (
            <div key={a.key} className="row control-row">
              <span className="grow small">{a.label}</span>
              <button className={`btn small ${listening === a.key ? "gold" : "secondary"} keycap`} onClick={() => setListening(listening === a.key ? null : a.key)}
                aria-label={`${a.label}: ${map[a.key].map(keyLabel).join(" or ") || "unbound"}`}>
                {listening === a.key ? "Press a key…" : map[a.key].map(keyLabel).join(" / ") || "—"}
              </button>
            </div>
          ))}
        </div>
      ))}
      <button className="btn secondary small" style={{ alignSelf: "flex-start" }} onClick={() => void save({ ...DEFAULTS })}>Reset to defaults</button>
      <span className="head small">Gamepad {pad ? <span className="tag gold">connected</span> : <span className="small muted">(plug one in and press a button)</span>}</span>
      <div className="col" style={{ gap: 1 }}>
        {PAD_HELP.map(([b, what]) => <span key={b} className="small row control-row"><span className="grow muted">{b}</span>{what}</span>)}
      </div>
    </div>
  );
}
