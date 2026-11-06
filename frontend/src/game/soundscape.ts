// Ambient audio per biome, time of day and weather (Phase 10), synthesized like the SFX (D-047): a
// wind bed and a rain bed (filtered noise) that crossfade, plus small scheduled critters — birds by
// day, crickets and owls at night, frogs in the swamp, eagles and pebbles up in Stonepeak, ice creaks
// in the north and crackling embers in the Ashen Wastes. Follows the Music slider.
import { ambienceVolume, audioContext } from "./sfx";
import type { Weather } from "../state/world";

interface Bed {
  src: AudioBufferSourceNode;
  filter: BiquadFilterNode;
  gain: GainNode;
}

const WIND: Record<string, { f: number; q: number; g: number }> = {
  meadow: { f: 500, q: 0.4, g: 0.05 },
  forest: { f: 650, q: 0.5, g: 0.06 },
  stonepeak: { f: 900, q: 0.9, g: 0.1 },
  swamp: { f: 350, q: 0.4, g: 0.05 },
  frozen: { f: 1200, q: 1.6, g: 0.16 },
  ashen: { f: 180, q: 0.6, g: 0.12 },
  cave: { f: 260, q: 0.5, g: 0.05 }, // Phase 12: a low draught through the delve
};

export class Soundscape {
  private master: GainNode | null = null;
  private wind: Bed | null = null;
  private rain: Bed | null = null;
  private acc = 0;
  private t = 0;
  private enabled = true;

  destroy(): void {
    for (const b of [this.wind, this.rain]) b?.src.stop();
    this.master?.disconnect();
    this.master = null;
  }

  private ensure(): AudioContext | null {
    const a = audioContext();
    if (!a) return null;
    const { ctx, noise } = a;
    if (!this.master) {
      this.master = ctx.createGain();
      this.master.gain.value = 0;
      this.master.connect(ctx.destination);
      const bed = (type: BiquadFilterType, f: number): Bed => {
        const src = ctx.createBufferSource();
        src.buffer = noise;
        src.loop = true;
        const filter = ctx.createBiquadFilter();
        filter.type = type;
        filter.frequency.value = f;
        const gain = ctx.createGain();
        gain.gain.value = 0;
        src.connect(filter).connect(gain).connect(this.master!);
        src.start();
        return { src, filter, gain };
      };
      this.wind = bed("bandpass", 500);
      this.rain = bed("highpass", 1400);
    }
    return ctx;
  }

  /** Call every frame; cheap. */
  update(dt: number, biome: string, night: boolean, weather: Weather): void {
    const vol = ambienceVolume();
    if (vol <= 0 && !this.master) return;
    const ctx = this.ensure();
    if (!ctx || !this.master || !this.wind || !this.rain) return;
    const now = ctx.currentTime;
    this.master.gain.setTargetAtTime(this.enabled ? vol : 0, now, 0.4);
    this.t += dt;
    this.acc += dt;
    if (this.acc < 0.25) return;
    this.acc = 0;
    // beds
    const w = WIND[biome] ?? WIND.meadow;
    const gust = 0.75 + Math.sin(this.t * 0.31) * 0.2 + Math.sin(this.t * 0.83) * 0.1;
    const stormy = weather === "storm" ? 1.8 : weather === "snow" ? 1.3 : 1;
    this.wind.filter.Q.setTargetAtTime(w.q, now, 0.5);
    this.wind.filter.frequency.setTargetAtTime(w.f * (0.85 + gust * 0.3), now, 0.8);
    this.wind.gain.gain.setTargetAtTime(w.g * gust * stormy, now, 0.8);
    const wet = biome === "ashen" || biome === "frozen" ? 0 : weather === "rain" ? 0.18 : weather === "storm" ? 0.3 : 0;
    this.rain.gain.gain.setTargetAtTime(wet, now, 1.2);
    // critters (a few chances per second, so calls feel irregular)
    if (weather === "storm") return;
    const r = Math.random();
    const out = this.master;
    if (biome === "meadow" || biome === "forest") {
      if (!night && weather === "clear" && r < (biome === "forest" ? 0.09 : 0.06)) this.bird(ctx, out);
      if (night && r < 0.3) this.cricket(ctx, out);
      if (night && biome === "forest" && r > 0.985) this.owl(ctx, out);
    } else if (biome === "swamp") {
      if (r < (night ? 0.16 : 0.07)) this.frog(ctx, out);
      if (r > 0.97) this.drip(ctx, out);
    } else if (biome === "stonepeak") {
      if (!night && r < 0.015) this.eagle(ctx, out);
      if (r > 0.96) this.pebbles(ctx, out);
    } else if (biome === "frozen") {
      if (r < 0.025) this.creak(ctx, out);
    } else if (biome === "ashen") {
      if (r < 0.35) this.crackle(ctx, out);
    } else if (biome === "cave") {
      if (r < 0.12) this.drip(ctx, out);
      if (r > 0.993) this.creak(ctx, out);
    }
  }

  // ── little voices ─────────────────────────────────────────────────────────
  private osc(ctx: AudioContext, out: AudioNode, type: OscillatorType, f0: number, f1: number, t: number, dur: number, g: number, pan = 0): void {
    const o = ctx.createOscillator();
    const gain = ctx.createGain();
    const p = ctx.createStereoPanner();
    p.pan.value = pan;
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(g, t + Math.min(0.02, dur / 3));
    gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(gain).connect(p).connect(out);
    o.start(t);
    o.stop(t + dur + 0.05);
  }

  private bird(ctx: AudioContext, out: AudioNode): void {
    const t = ctx.currentTime + 0.02;
    const base = 2200 + Math.random() * 1600;
    const pan = Math.random() * 1.6 - 0.8;
    const n = 2 + Math.floor(Math.random() * 4);
    for (let i = 0; i < n; i++) {
      const f = base * (1 + (Math.random() - 0.4) * 0.3);
      this.osc(ctx, out, "sine", f, f * (i % 2 ? 1.25 : 0.8), t + i * 0.11, 0.08, 0.05, pan);
    }
  }

  private cricket(ctx: AudioContext, out: AudioNode): void {
    const t = ctx.currentTime + 0.02;
    const pan = Math.random() * 1.6 - 0.8;
    for (let i = 0; i < 3; i++) this.osc(ctx, out, "triangle", 4600, 4500, t + i * 0.05, 0.03, 0.025, pan);
  }

  private owl(ctx: AudioContext, out: AudioNode): void {
    const t = ctx.currentTime + 0.02;
    this.osc(ctx, out, "sine", 420, 380, t, 0.35, 0.06, -0.4);
    this.osc(ctx, out, "sine", 400, 360, t + 0.5, 0.5, 0.06, -0.4);
  }

  private frog(ctx: AudioContext, out: AudioNode): void {
    const t = ctx.currentTime + 0.02;
    const pan = Math.random() * 1.6 - 0.8;
    const f = 110 + Math.random() * 60;
    for (let i = 0; i < 2 + Math.floor(Math.random() * 2); i++) this.osc(ctx, out, "sawtooth", f, f * 0.8, t + i * 0.16, 0.12, 0.035, pan);
  }

  private drip(ctx: AudioContext, out: AudioNode): void {
    const t = ctx.currentTime + 0.02;
    this.osc(ctx, out, "sine", 1400, 2600, t, 0.07, 0.04, Math.random() - 0.5);
  }

  private eagle(ctx: AudioContext, out: AudioNode): void {
    const t = ctx.currentTime + 0.02;
    this.osc(ctx, out, "sawtooth", 1500, 900, t, 0.6, 0.02, 0.5);
  }

  private pebbles(ctx: AudioContext, out: AudioNode): void {
    const t = ctx.currentTime + 0.02;
    for (let i = 0; i < 4; i++) this.osc(ctx, out, "square", 900 + Math.random() * 600, 500, t + i * (0.06 + Math.random() * 0.08), 0.02, 0.02, -0.3);
  }

  private creak(ctx: AudioContext, out: AudioNode): void {
    const t = ctx.currentTime + 0.02;
    this.osc(ctx, out, "triangle", 300, 620, t, 0.5, 0.025, Math.random() - 0.5);
  }

  private crackle(ctx: AudioContext, out: AudioNode): void {
    const t = ctx.currentTime + Math.random() * 0.2;
    this.osc(ctx, out, "square", 2400 + Math.random() * 2000, 300, t, 0.015, 0.03, Math.random() - 0.5);
  }
}
