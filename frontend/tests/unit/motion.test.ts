import { describe, expect, it } from "vitest";
import golden from "../../../shared/golden/movement.json";
import { fromList, MOTION_FIELDS, step, toList } from "../../src/sim/motion";
import type { Rules } from "../../src/sim/rules";

describe("shared movement step", () => {
  it("replays the Python golden vectors bit-for-bit", () => {
    expect(golden.fields).toEqual(MOTION_FIELDS);
    const r = golden.rules as unknown as Rules;
    for (const c of golden.cases) {
      const solid = new Set(c.solid.map(([x, y]) => `${x},${y}`));
      const w = r.weapons[c.weapon];
      const m = fromList(c.start);
      c.steps.forEach((s, i) => {
        const st = s as { in: number[]; kb?: number[] };
        if (st.kb) [m.kbx, m.kby] = st.kb;
        const [mx, my, ax, ay, b] = st.in;
        const started = step(m, mx, my, ax, ay, b, r, w, (x, y) => solid.has(`${x},${y}`));
        const got = [...toList(m), started];
        if (JSON.stringify(got) !== JSON.stringify(c.expect[i])) {
          throw new Error(`${c.weapon} diverged at step ${i}: ${JSON.stringify(got)} vs ${JSON.stringify(c.expect[i])}`);
        }
      });
    }
  });
});
