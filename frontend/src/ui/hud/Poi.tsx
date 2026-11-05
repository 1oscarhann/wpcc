// Phase 10 points of interest in Avatar Mode: the "E · Open chest" prompt, the lore stone reading,
// your shrine blessing, and a wandering trader's stall.
import { useEffect, useState } from "react";
import { roomLink } from "../../net/room";
import { useMarket } from "../../state/market";
import { useRealm, type PoiInfo } from "../../state/realm";
import { useAvatar } from "../../state/avatar";
import { formatDuration, Icon, Modal } from "../components/kit";
import { MerchantStock } from "./Market";

const VERB: Record<PoiInfo["kind"], [string, string]> = {
  ruins: ["chest", "Open the chest"],
  shrine: ["sun", "Pray at the shrine"],
  lore_stone: ["scroll", "Read the stone"],
  cave: ["map", "Inspect the cave"],
  merchant: ["cart", "Trade"],
  lost_villager: ["home", "Help them home"],
};

export function PoiPrompt({ touch }: { touch: boolean }) {
  const near = useRealm((s) => s.nearPoi);
  const nearStone = useRealm((s) => s.nearWaystone);
  const poi = useRealm((s) => (s.nearPoi !== null ? s.overview?.pois[s.nearPoi] : undefined));
  const busy = useRealm((s) => s.mapOpen || s.lore !== null || s.wildMerchant !== null);
  const trade = useMarket((s) => s.near);
  const mode = useAvatar((s) => s.mode);
  if (near === null || !poi || nearStone !== null || trade || busy || mode !== "avatar") return null;
  const [icon, verb] = VERB[poi.kind];
  const label = poi.used && poi.kind === "ruins" ? "Empty chest" : poi.used && poi.kind === "lost_villager" ? "" : verb;
  if (!label) return null;
  return (
    <button className="btn gold trade-prompt" onClick={() => roomLink.send?.("INTERACT", near)}>
      <Icon name={icon} /> {touch ? label : <><span className="av-key">E</span> {label}</>}
    </button>
  );
}

export function LoreModal() {
  const lore = useRealm((s) => s.lore);
  if (!lore) return null;
  const close = () => useRealm.getState().set({ lore: null });
  return (
    <Modal title={lore.title} onClose={close}>
      <div className="lore-text">
        <p>{lore.text}</p>
      </div>
      {lore.first && <p className="small muted">New lore discovered · +{lore.xp} XP</p>}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn gold" onClick={close}>Close</button>
      </div>
    </Modal>
  );
}

export function BlessingChip() {
  const blessing = useRealm((s) => s.blessing);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!blessing) return;
    const id = window.setInterval(() => {
      tick((n) => n + 1);
      if (Date.now() > blessing.until) useRealm.getState().set({ blessing: null });
    }, 1000);
    return () => window.clearInterval(id);
  }, [blessing]);
  if (!blessing) return null;
  return (
    <div className="blessing-chip" title={blessing.text}>
      <Icon name="sun" scale={1.5} />
      <span className="small">
        <b>{blessing.name}</b> · {formatDuration((blessing.until - Date.now()) / 1000)}
      </span>
    </div>
  );
}

export function WildMerchantPanel() {
  const id = useRealm((s) => s.wildMerchant);
  if (!id) return null;
  return (
    <Modal title="Wandering trader" onClose={() => useRealm.getState().set({ wildMerchant: null })} wide>
      <MerchantStock mode="buy" merchantId={id} />
    </Modal>
  );
}
