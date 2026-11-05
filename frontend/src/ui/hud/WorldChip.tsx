// Phase 10 HUD: time of day, weather and season under the minimap. Tap for the forecast and what the
// weather is doing to your village and the wilds.
import { useEffect, useState } from "react";
import { serverNow } from "../../state/session";
import { dayPhase, useWorld, type Weather } from "../../state/world";
import { formatDuration, Icon } from "../components/kit";

const WEATHER_ICON: Record<Weather, string> = { clear: "sun", rain: "rain", snow: "snowfall", fog: "fog", storm: "storm" };
const WEATHER_NAME: Record<Weather, string> = { clear: "Clear", rain: "Rain", snow: "Snow", fog: "Fog", storm: "Storm" };
const PHASE_NAME: Record<string, string> = { dawn: "Dawn", day: "Day", dusk: "Dusk", night: "Night" };
const SEASON_NAME: Record<string, string> = { spring: "Spring", summer: "Summer", autumn: "Autumn", winter: "Winter" };

function effectLines(weather: Weather, effects: ReturnType<typeof useWorld.getState>["effects"]): string[] {
  const out: string[] = [];
  if (!effects) return out;
  for (const [k, m] of Object.entries(effects.production)) {
    const pct = Math.round((m - 1) * 100);
    out.push(`${k[0].toUpperCase()}${k.slice(1)} production ${pct > 0 ? "+" : ""}${pct}%`);
  }
  if (effects.aggro < 1) out.push("Monsters notice you from less far away");
  for (const k of Object.keys(effects.rare_node)) out.push(`${k.replace(/_/g, " ")}s yield more`);
  if (weather === "storm") out.push("Storm Elementals roam — they drop storm glass");
  return out;
}

export function WorldChip() {
  const { season, seasonEnds, weather, forecast, effects, loaded } = useWorld();
  const [open, setOpen] = useState(false);
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 5000);
    return () => window.clearInterval(id);
  }, []);
  if (!loaded) return null;
  const ph = dayPhase();
  const night = ph.name === "night";
  const sky = night && weather === "clear" ? "moon" : WEATHER_ICON[weather];
  const now = serverNow();
  const lines = effectLines(weather, effects);
  return (
    <div className="world-chip-wrap">
      <button
        className={`world-chip ${night ? "is-night" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`${PHASE_NAME[ph.name]}, ${WEATHER_NAME[weather]}, ${SEASON_NAME[season] ?? season}. Show forecast`}
        title="Weather and forecast"
      >
        <Icon name={sky} scale={1.5} />
        <span className="world-chip-text">
          <span className="head">{PHASE_NAME[ph.name]}</span>
          <span className="small">{WEATHER_NAME[weather]} · {SEASON_NAME[season] ?? season}</span>
        </span>
      </button>
      {open && (
        <div className="world-pop panel-paper" role="dialog" aria-label="Forecast">
          <div className="head" style={{ fontSize: 15 }}>Forecast</div>
          <div className="forecast-row">
            {forecast.map((f, i) => (
              <div key={f.starts_ms} className="forecast-cell" title={WEATHER_NAME[f.weather]}>
                <Icon name={WEATHER_ICON[f.weather]} scale={1.5} />
                <span className="small">{i === 0 ? "now" : `+${Math.max(1, Math.round((f.starts_ms - now) / 60000))}m`}</span>
              </div>
            ))}
          </div>
          {lines.length > 0 && (
            <ul className="small world-effects">
              {lines.map((l) => <li key={l}>{l}</li>)}
            </ul>
          )}
          {night && <p className="small muted">Night: monsters are tougher, drop more, and moonpetals bloom.</p>}
          <p className="small muted">{SEASON_NAME[season] ?? season} ends in {formatDuration(Math.max(0, seasonEnds - now) / 1000)}</p>
        </div>
      )}
    </div>
  );
}
