import { describe, expect, it } from "vitest";
import { anyDown, current, DEFAULTS, isKey, keyLabel, loadKeymap, overrides } from "../../src/game/keymap";

describe("keymap", () => {
  it("defaults keep attack and journal apart (J attacks, L opens the journal)", () => {
    loadKeymap(undefined);
    expect(isKey("j", "attack")).toBe(true);
    expect(isKey("j", "journal")).toBe(false);
    expect(isKey("l", "journal")).toBe(true);
  });

  it("loads saved overrides and ignores junk", () => {
    loadKeymap({ dodge: ["c"], nonsense: ["x"], heavy: [42] as unknown as string[] });
    expect(isKey("c", "dodge")).toBe(true);
    expect(isKey(" ", "dodge")).toBe(false);
    expect(isKey("k", "heavy")).toBe(true); // the bad override was dropped
    expect(anyDown(new Set(["c"]), "dodge")).toBe(true);
  });

  it("saves only what changed", () => {
    loadKeymap(undefined);
    const next = { ...current(), ride: ["v"] };
    expect(overrides(next)).toEqual({ ride: ["v"] });
    expect(overrides({ ...DEFAULTS })).toEqual({});
  });

  it("labels keys for people", () => {
    expect(keyLabel(" ")).toBe("Space");
    expect(keyLabel("arrowleft")).toBe("←");
    expect(keyLabel("shift")).toBe("Shift");
    expect(keyLabel("q")).toBe("Q");
  });
});
