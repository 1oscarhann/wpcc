import { useState } from "react";
import { useSession } from "../../state/session";
import { CharacterPreview, Icon, Panel } from "../components/kit";
import { SettingsModal } from "./Settings";

// Phase 2 placeholder: Build Mode lands in Phase 3.
export function PlayScreen() {
  const me = useSession((s) => s.me)!;
  const [settings, setSettings] = useState(false);
  return (
    <div className="title-bg">
      <Panel style={{ width: "min(460px, 100%)" }}>
        <div className="col" style={{ alignItems: "center", gap: 10 }}>
          <span className="ribbon">{me.village.name}</span>
          <CharacterPreview look={me.avatar.appearance} scale={8} />
          <p className="center" style={{ textAlign: "center" }}>
            Welcome, <b>{me.user.username}</b>! Your village is ready in <b>{me.realm.name}</b>.
          </p>
          <button className="btn secondary" onClick={() => setSettings(true)}>
            <Icon name="settings" /> Settings
          </button>
        </div>
      </Panel>
      {settings && <SettingsModal onClose={() => setSettings(false)} />}
    </div>
  );
}
