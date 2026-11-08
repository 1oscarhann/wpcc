// Phase 18: generative background music, synthesized like everything else (D-047) and following the
// Music slider. A soft plucked tune in a major pentatonic over slow chords by day; a sparser minor tune
// at night; a gentle pulse when there's a fight. It never repeats exactly, and it's quiet on purpose.
import { ambienceVolume, audioContext } from "./sfx";

export type Mood = "day" | "night" | "fight";

const MAJOR = [0, 2, 4, 7, 9]; // pentatonic: nothing ever clashes
const MINOR = [0, 3, 5, 7, 10];
const CHORDS_DAY = [[0, 4, 7], [9, 12, 16], [5, 9, 12], [7, 11, 14]]; // I vi IV V
const CHORDS_NIGHT = [[9, 12, 16], [5, 9, 12], [0, 4, 7], [7, 10, 14]];
const ROOT = 261.63; // middle C

const hz = (semis: number, oct = 0) => ROOT * 2 ** (semis / 12 + oct);

export class Music {
  private out: GainNode | null = null;
  private next = 0; // AudioContext time of the next beat
  private beat = 0;
  private mood: Mood = "day";
  private lastNote = 2;

  setMood(m: Mood): void {
    this.mood = m;
  }

  destroy(): void {
    this.out?.disconnect();
    this.out = null;
  }

  /** Call every frame: keeps half a second of music scheduled ahead. */
  update(): void {
    const a = audioContext();
    if (!a) return;
    const { ctx } = a;
    if (!this.out) {
      this.out = ctx.createGain();
      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.value = 2600;
      this.out.connect(lp).connect(ctx.destination);
      this.next = ctx.currentTime + 0.2;
    }
    const vol = ambienceVolume() * 0.55;
    this.out.gain.setTargetAtTime(vol, ctx.currentTime, 0.4);
    if (vol <= 0.001) {
      this.next = ctx.currentTime + 0.2;
      return;
    }
    const spb = this.mood === "fight" ? 0.36 : this.mood === "night" ? 0.62 : 0.48; // seconds per beat
    while (this.next < ctx.currentTime + 0.5) {
      this.play(ctx, this.next, spb);
      this.next += spb;
      this.beat++;
    }
  }

  private play(ctx: AudioContext, t: number, spb: number): void {
    const out = this.out!;
    const night = this.mood === "night";
    const bar = Math.floor(this.beat / 8) % 4;
    const chord = (night ? CHORDS_NIGHT : CHORDS_DAY)[bar];
    const inBar = this.beat % 8;
    if (inBar === 0) {
      // a soft pad: the chord, held for the bar
      for (const s of chord) this.voice(ctx, out, "sine", hz(s, -1), t, spb * 8, night ? 0.035 : 0.045, 0.9);
      this.voice(ctx, out, "triangle", hz(chord[0], -2), t, spb * 8, 0.05, 0.6);
    }
    // the tune: a wandering walk over the scale, with rests (more of them at night)
    if (Math.random() < (night ? 0.45 : 0.68)) {
      const scale = night ? MINOR : MAJOR;
      this.lastNote = Math.max(0, Math.min(9, this.lastNote + [-2, -1, -1, 0, 1, 1, 2][Math.floor(Math.random() * 7)]));
      const deg = this.lastNote;
      const semis = scale[deg % 5] + 12 * Math.floor(deg / 5) + (night ? 9 : 0) - 12;
      this.voice(ctx, out, "triangle", hz(semis, 1), t, spb * (Math.random() < 0.25 ? 2 : 1) * 0.95, night ? 0.05 : 0.07, 0.02);
    }
    if (this.mood === "fight") {
      // a heartbeat on the beat, a lighter one off it
      this.thump(ctx, out, t, inBar % 2 === 0 ? 0.16 : 0.07);
    } else if (!night && inBar === 4 && Math.random() < 0.5) {
      this.voice(ctx, out, "sine", hz(chord[2], 2), t, spb * 2, 0.025, 0.01); // a little bell
    }
  }

  private voice(ctx: AudioContext, out: AudioNode, type: OscillatorType, f: number, t: number, dur: number, gain: number, attack: number) {
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f, t);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + Math.max(0.005, attack * dur));
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(out);
    o.start(t);
    o.stop(t + dur + 0.05);
  }

  private thump(ctx: AudioContext, out: AudioNode, t: number, gain: number) {
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = "sine";
    o.frequency.setValueAtTime(110, t);
    o.frequency.exponentialRampToValueAtTime(48, t + 0.18);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
    o.connect(g).connect(out);
    o.start(t);
    o.stop(t + 0.25);
  }
}
