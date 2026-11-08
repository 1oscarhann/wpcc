// Core SFX, synthesized at runtime with WebAudio (original, zero download, D-047). Every sound is a
// few oscillators/noise bursts with short envelopes: chiptune-adjacent, soft, never shrill.
import { useSession } from "../state/session";

let ctx: AudioContext | null = null;
let noiseBuf: AudioBuffer | null = null;
const last = new Map<string, number>();

function audio(): AudioContext | null {
  if (typeof window === "undefined" || !("AudioContext" in window)) return null;
  if (!ctx) {
    ctx = new AudioContext();
    const len = ctx.sampleRate;
    noiseBuf = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0);
    let seed = 1234567;
    for (let i = 0; i < len; i++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      d[i] = (seed / 0x7fffffff) * 2 - 1;
    }
  }
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

/** Shared with the soundscape (ambient beds use the same context and noise buffer). */
export function audioContext(): { ctx: AudioContext; noise: AudioBuffer } | null {
  const c = audio();
  return c && noiseBuf ? { ctx: c, noise: noiseBuf } : null;
}

/** Ambience follows the "Music" slider. */
export function ambienceVolume(): number {
  const a = useSession.getState().me?.settings.audio as { master?: number; music?: number; muted?: boolean } | undefined;
  if (!a) return 0.4;
  if (a.muted) return 0;
  return (a.master ?? 1) * (a.music ?? 0.6) * 0.5;
}

function volume(): number {
  const a = useSession.getState().me?.settings.audio as { master?: number; sfx?: number; muted?: boolean } | undefined;
  if (!a) return 0.5;
  if (a.muted) return 0;
  return (a.master ?? 1) * (a.sfx ?? 0.8) * 0.6;
}

function tone(c: AudioContext, out: AudioNode, type: OscillatorType, f0: number, f1: number, t: number, dur: number, gain: number) {
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = type;
  o.frequency.setValueAtTime(f0, t);
  o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(gain, t + 0.005);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(out);
  o.start(t);
  o.stop(t + dur + 0.02);
}

function noise(c: AudioContext, out: AudioNode, t: number, dur: number, gain: number, type: BiquadFilterType, f0: number, f1: number, q = 1) {
  const s = c.createBufferSource();
  s.buffer = noiseBuf;
  const f = c.createBiquadFilter();
  f.type = type;
  f.Q.value = q;
  f.frequency.setValueAtTime(f0, t);
  f.frequency.exponentialRampToValueAtTime(Math.max(40, f1), t + dur);
  const g = c.createGain();
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(gain, t + 0.004);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  s.connect(f).connect(g).connect(out);
  s.start(t, Math.random() * 0.5);
  s.stop(t + dur + 0.02);
}

const SOUNDS: Record<string, (c: AudioContext, o: AudioNode, t: number) => void> = {
  // Phases 15/16: a chat bubble pops up, a map ping, a like
  chat: (c, o, t) => tone(c, o, "sine", 660, 990, t, 0.07, 0.05),
  ping: (c, o, t) => [880, 1320].forEach((f, i) => tone(c, o, "sine", f, f, t + i * 0.09, 0.16, 0.06)),
  like: (c, o, t) => [784, 1047].forEach((f, i) => tone(c, o, "triangle", f, f * 1.02, t + i * 0.06, 0.12, 0.08)),
  // Phase 13: the raid horn (two long low notes) and a boss's roar
  horn: (c, o, t) => {
    tone(c, o, "sawtooth", 196, 190, t, 0.7, 0.13);
    tone(c, o, "sawtooth", 147, 140, t + 0.75, 1.0, 0.13);
    tone(c, o, "triangle", 392, 380, t, 0.7, 0.05);
  },
  roar: (c, o, t) => {
    noise(c, o, t, 0.9, 0.5, "lowpass", 600, 180, 0.8);
    tone(c, o, "sawtooth", 110, 55, t, 0.9, 0.16);
  },
  swing: (c, o, t) => noise(c, o, t, 0.12, 0.35, "bandpass", 1800, 4200, 1.2),
  swing_heavy: (c, o, t) => noise(c, o, t, 0.22, 0.45, "bandpass", 700, 2600, 1.0),
  ability: (c, o, t) => {
    noise(c, o, t, 0.3, 0.35, "bandpass", 900, 3800, 1.5);
    tone(c, o, "triangle", 520, 880, t, 0.25, 0.12);
  },
  dodge: (c, o, t) => noise(c, o, t, 0.16, 0.25, "highpass", 3000, 900, 0.7),
  chop: (c, o, t) => {
    tone(c, o, "square", 180, 90, t, 0.08, 0.18);
    noise(c, o, t, 0.06, 0.3, "lowpass", 1400, 400);
  },
  mine: (c, o, t) => {
    tone(c, o, "triangle", 1300, 1100, t, 0.18, 0.14);
    tone(c, o, "square", 260, 140, t, 0.05, 0.12);
  },
  rustle: (c, o, t) => noise(c, o, t, 0.18, 0.22, "bandpass", 2500, 1500, 0.8),
  pickup: (c, o, t) => {
    tone(c, o, "square", 660, 660, t, 0.06, 0.08);
    tone(c, o, "square", 990, 990, t + 0.055, 0.08, 0.08);
  },
  coin: (c, o, t) => {
    tone(c, o, "square", 1320, 1320, t, 0.05, 0.07);
    tone(c, o, "square", 1760, 1760, t + 0.05, 0.12, 0.07);
  },
  deposit: (c, o, t) => [523, 659, 784, 1047].forEach((f, i) => tone(c, o, "triangle", f, f, t + i * 0.07, 0.14, 0.12)),
  levelup: (c, o, t) => [523, 659, 784, 1047, 1319].forEach((f, i) => tone(c, o, "square", f, f, t + i * 0.08, 0.2, 0.08)),
  hit: (c, o, t) => {
    noise(c, o, t, 0.08, 0.5, "lowpass", 2600, 500);
    tone(c, o, "square", 220, 70, t, 0.09, 0.2);
  },
  crit: (c, o, t) => {
    noise(c, o, t, 0.12, 0.55, "lowpass", 4200, 600);
    tone(c, o, "square", 330, 60, t, 0.14, 0.22);
    tone(c, o, "triangle", 1500, 900, t, 0.1, 0.08);
  },
  hurt: (c, o, t) => {
    tone(c, o, "sawtooth", 300, 90, t, 0.18, 0.18);
    noise(c, o, t, 0.1, 0.3, "lowpass", 1200, 300);
  },
  squish: (c, o, t) => {
    tone(c, o, "sine", 420, 120, t, 0.14, 0.22);
    noise(c, o, t, 0.08, 0.2, "lowpass", 900, 300);
  },
  growl: (c, o, t) => {
    tone(c, o, "sawtooth", 110, 80, t, 0.32, 0.12);
    noise(c, o, t, 0.3, 0.12, "lowpass", 500, 250, 2);
  },
  hiss: (c, o, t) => noise(c, o, t, 0.3, 0.2, "highpass", 5000, 3000, 0.5),
  poof: (c, o, t) => {
    noise(c, o, t, 0.3, 0.35, "lowpass", 1600, 200);
    tone(c, o, "triangle", 300, 600, t, 0.12, 0.06);
  },
  ko: (c, o, t) => [392, 330, 262, 196].forEach((f, i) => tone(c, o, "triangle", f, f * 0.98, t + i * 0.12, 0.2, 0.12)),
  potion: (c, o, t) => [0, 1, 2, 3].forEach((i) => tone(c, o, "sine", 400 + i * 160, 700 + i * 160, t + i * 0.06, 0.08, 0.1)),
  throw: (c, o, t) => noise(c, o, t, 0.25, 0.3, "bandpass", 2400, 900, 2),
  clang: (c, o, t) => {
    tone(c, o, "triangle", 1560, 1480, t, 0.22, 0.06);
    tone(c, o, "square", 780, 760, t, 0.06, 0.04);
    noise(c, o, t, 0.04, 0.12, "highpass", 3000, 2000);
  },
  saw: (c, o, t) => noise(c, o, t, 0.2, 0.12, "bandpass", 1200, 1800, 3),
  fanfare: (c, o, t) => {
    [523, 659, 784].forEach((f, i) => tone(c, o, "square", f, f, t + i * 0.11, 0.16, 0.07));
    [1047, 1319, 1568].forEach((f) => tone(c, o, "triangle", f, f, t + 0.36, 0.7, 0.06));
  },
  reveal: (c, o, t) => {
    noise(c, o, t, 0.5, 0.15, "bandpass", 600, 4000, 1.5);
    [784, 988, 1175, 1568].forEach((f, i) => tone(c, o, "triangle", f, f, t + 0.25 + i * 0.07, 0.25, 0.07));
  },
  shimmer: (c, o, t) => [1760, 2093, 2637].forEach((f, i) => tone(c, o, "sine", f, f * 1.01, t + i * 0.05, 0.18, 0.03)),
  telegraph: (c, o, t) => tone(c, o, "triangle", 880, 700, t, 0.1, 0.05),
  thunder: (c, o, t) => {
    noise(c, o, t, 1.6, 0.5, "lowpass", 260, 60, 0.7);
    noise(c, o, t + 0.15, 1.1, 0.35, "lowpass", 160, 50, 0.9);
  },
  boom: (c, o, t) => {
    noise(c, o, t, 0.6, 0.6, "lowpass", 900, 80, 0.8);
    tone(c, o, "sine", 120, 40, t, 0.4, 0.2);
  },
  slam: (c, o, t) => {
    noise(c, o, t, 0.25, 0.45, "lowpass", 600, 90, 1);
    tone(c, o, "triangle", 110, 55, t, 0.2, 0.15);
  },
  splash: (c, o, t) => noise(c, o, t, 0.4, 0.3, "bandpass", 1600, 400, 0.7),
  shoot: (c, o, t) => noise(c, o, t, 0.14, 0.22, "bandpass", 3200, 1200, 2.5),
  zap: (c, o, t) => {
    noise(c, o, t, 0.18, 0.3, "highpass", 6000, 2500, 0.8);
    tone(c, o, "sawtooth", 1400, 300, t, 0.12, 0.05);
  },
  summon: (c, o, t) => [330, 415, 494].forEach((f, i) => tone(c, o, "sine", f, f * 1.5, t + i * 0.07, 0.22, 0.06)),
  split: (c, o, t) => {
    tone(c, o, "sine", 300, 140, t, 0.16, 0.12);
    tone(c, o, "sine", 360, 180, t + 0.06, 0.14, 0.1);
  },
};

/** Play a named sound (rate-limited per name so swarms don't clip). */
export function sfx(name: string): void {
  const fn = SOUNDS[name] as ((c: AudioContext, o: AudioNode, t: number) => void) | undefined;
  const c = fn ? audio() : null;
  const v = volume();
  if (!fn || !c || v <= 0) return;
  const now = performance.now();
  if (now - (last.get(name) ?? 0) < 35) return;
  last.set(name, now);
  const g = c.createGain();
  g.gain.value = v;
  g.connect(c.destination);
  fn(c, g, c.currentTime + 0.005);
}
