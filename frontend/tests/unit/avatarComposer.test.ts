import { describe, expect, it } from "vitest";
import { composePixels, frameFor } from "../../src/game/avatarComposer";

const KEYS: [number, number, number][] = [[0x40, 0x40, 0x40], [0x70, 0x70, 0x70], [0xa0, 0xa0, 0xa0], [0xd0, 0xd0, 0xd0]];
const RAMP: [number, number, number][] = [[10, 0, 0], [20, 0, 0], [30, 0, 0], [40, 0, 0]];

function px(w: number, h: number, set: Record<string, [number, number, number, number]>) {
  const d = new Uint8ClampedArray(w * h * 4);
  for (const [k, v] of Object.entries(set)) {
    const [x, y] = k.split(",").map(Number);
    d.set(v, (y * w + x) * 4);
  }
  return d;
}

describe("composePixels", () => {
  it("recolours shade keys and keeps fixed colours", () => {
    const layer = px(4, 4, { "1,1": [0xa0, 0xa0, 0xa0, 255], "2,1": [99, 98, 97, 255] });
    const out = composePixels([{ data: layer, ramp: RAMP }], KEYS, 4, 4, 4);
    expect(Array.from(out.slice((1 * 4 + 1) * 4, (1 * 4 + 1) * 4 + 4))).toEqual([30, 0, 0, 255]);
    expect(Array.from(out.slice((1 * 4 + 2) * 4, (1 * 4 + 2) * 4 + 4))).toEqual([99, 98, 97, 255]);
  });

  it("stacks later layers on top", () => {
    const a = px(2, 1, { "0,0": [0x40, 0x40, 0x40, 255] });
    const b = px(2, 1, { "0,0": [0xd0, 0xd0, 0xd0, 255] });
    const out = composePixels([{ data: a, ramp: RAMP }, { data: b, ramp: RAMP }], KEYS, 2, 1, 2);
    expect(out[0]).toBe(40);
  });

  it("adds an outline that never crosses into the next frame", () => {
    // 2 frames of width 3; a pixel at the right edge of frame 0
    const layer = px(6, 3, { "2,1": [0x70, 0x70, 0x70, 255] });
    const out = composePixels([{ data: layer, ramp: RAMP }], KEYS, 6, 3, 3);
    const alpha = (x: number, y: number) => out[(y * 6 + x) * 4 + 3];
    expect(alpha(1, 1)).toBe(255); // outline left
    expect(alpha(2, 0)).toBe(255); // outline above
    expect(alpha(3, 1)).toBe(0); // frame 1 untouched
  });
});

describe("frameFor", () => {
  it("mirrors right from the side frames and cycles walk frames", () => {
    const a = frameFor("right", "walk", 0);
    const b = frameFor("left", "walk", 0);
    expect(a.index).toBe(b.index);
    expect(a.flip).toBe(true);
    expect(frameFor("down", "walk", 130).index).not.toBe(frameFor("down", "walk", 0).index);
  });
});
