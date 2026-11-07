// Playwright screenshot runner: `node tools/screenshots.mjs <phase> [baseUrl]`
// Saves desktop (1440×900) and mobile (390×844) shots to docs/screenshots/phase-N/.
// Needs the API + Vite dev server running (see README).
import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
let playwright;
try {
  playwright = require("playwright");
} catch {
  playwright = require("/opt/node22/lib/node_modules/playwright");
}

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const phase = process.argv[2] ?? "2";
const BASE = process.argv[3] ?? "http://127.0.0.1:5173";
const OUT = join(ROOT, "docs", "screenshots", `phase-${phase}`);
mkdirSync(OUT, { recursive: true });

const VIEWPORTS = {
  // 1× keeps the committed screenshots small; the art is pixel art at integer zoom, so nothing is lost
  desktop: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
  mobile: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true },
};

async function shot(page, name, kind, opts = {}) {
  await page.waitForTimeout(opts.wait ?? 350);
  // JPEG q90: the soft lighting gradients make PNGs ~1 MB each; this keeps docs light
  const file = join(OUT, `${name}-${kind}.jpg`);
  await page.screenshot({ path: file, fullPage: opts.fullPage ?? false, type: "jpeg", quality: 90 });
  console.log("saved", file);
}

async function signupFlow(page, kind) {
  const name = `Shot${kind === "mobile" ? "M" : "D"}${Date.now() % 100000}`;
  await page.goto(`${BASE}/`);
  await page.getByText("Found a new village").waitFor();
  await shot(page, "01-login", kind);
  await page.getByText("Found a new village").click();
  await page.getByLabel("Pick a name").fill(name);
  await page.getByLabel("Password").fill("cozy village 123");
  await page.getByText("That name is free!").waitFor();
  await shot(page, "02-signup", kind);
  await page.getByText("Next: create your hero").click();
  await page.getByText("Create your hero").waitFor();
  await page.getByRole("button", { name: "Next Hair" }).click();
  await page.getByRole("button", { name: "ginger" }).click();
  await page.getByRole("button", { name: "sky" }).click();
  await shot(page, "03-creator", kind, { wait: 700 });
  await page.getByText("Found my village").click();
  await page.getByText("Your recovery codes").waitFor();
  await shot(page, "04-recovery-codes", kind);
  await page.getByText("I saved them").click();
  await page.getByText("Enter your village").click();
  await page.waitForURL("**/play");
  return name;
}

const PHASES = {
  async 2(page, kind) {
    await signupFlow(page, kind);
    await page.locator("canvas").first().waitFor();
    await shot(page, "05-play", kind, { wait: 2000 });
    await page.getByRole("button", { name: "Settings" }).click();
    await shot(page, "06-settings", kind);
    await page.goto(`${BASE}/debug`);
    await page.getByText("Debug gallery").waitFor();
    await shot(page, "07-debug-gallery", kind, { fullPage: true, wait: 1500 });
  },
  async 3(page, kind) {
    await signupFlow(page, kind);
    await page.locator("canvas").first().waitFor();
    await page.waitForFunction(() => window.__hfGame);
    await shot(page, "01-village", kind, { wait: 2500 });
    // screen position of a frame tile, straight from the renderer
    const at = (tx, ty) => page.evaluate(([x, y]) => window.__hfGame.frameTileToScreen(x, y), [tx, ty]);
    const canvas = page.locator("canvas").first();
    const box = await canvas.boundingBox();
    // clear a tree near the middle of the view
    const v = await page.evaluate(() => fetch("/api/village").then((r) => r.json()));
    const trees = v.village.debris.filter((d) => ["oak", "big_oak", "birch", "pine", "apple"].includes(d[1]));
    let target = null;
    for (const d of trees) {
      const p = await at(d[3] + 0.5, d[4] + 0.6);
      if (p.x > 40 && p.x < box.width - 40 && p.y > 120 && p.y < box.height - 120) { target = p; break; }
    }
    if (target) {
      await page.mouse.click(box.x + target.x, box.y + target.y);
      await shot(page, "02-clearing", kind, { wait: 450 });
    }
    await page.getByRole("button", { name: /^Build/ }).click();
    await shot(page, "03-build-menu", kind, { wait: 500 });
    await page.getByRole("button", { name: /Lumber Camp/ }).click();
    const spot = await at(28.5, 21.5); // centre of a free 3×3 at (27,20), inside the always-clear radius
    await page.mouse.move(box.x + spot.x, box.y + spot.y);
    if (kind === "mobile") {
      await page.mouse.click(box.x + spot.x, box.y + spot.y);
      await shot(page, "04-placing", kind, { wait: 500 });
      await page.getByRole("button", { name: "Place here" }).click();
    } else {
      await shot(page, "04-placing", kind, { wait: 500 });
      await page.mouse.click(box.x + spot.x, box.y + spot.y);
    }
    await shot(page, "05-constructing", kind, { wait: 900 });
    await page.waitForTimeout(11000);
    await shot(page, "06-built", kind, { wait: 600 });
    const th = await at(24, 21);
    await page.mouse.click(box.x + th.x, box.y + th.y);
    await shot(page, "07-selected", kind, { wait: 600 });
    await page.keyboard.press("Escape");
    await page.evaluate(() => window.__hfGame.zoomBy(-1));
    await shot(page, "08-overview", kind, { wait: 1200 });
  },
};

// ── Phase 4: Avatar Mode ─────────────────────────────────────────────────
async function enterAvatar(page) {
  await page.getByRole("button", { name: "Explore" }).click();
  await page.waitForFunction(() => window.__hfGame?.avatar?.client);
  await page.waitForTimeout(900); // camera tween
}

const walk = (page, x, y) => page.evaluate(([tx, ty]) => window.__hfGame.devWalkTo(tx, ty), [x, y]);

async function chop(page, kind, presses) {
  const found = await page.evaluate((k) => window.__hfGame.devFindNode(k), kind);
  if (!found) return false;
  await walk(page, found.stand[0], found.stand[1]);
  const box = await page.locator("canvas").first().boundingBox();
  const target = await page.evaluate(([x, y]) => {
    const g = window.__hfGame;
    return g.worldHost.toScreen((x + 0.5) * 16, (y + 0.5) * 16);
  }, found.node);
  if (presses.mouse) {
    await page.mouse.move(box.x + target.x, box.y + target.y);
    await page.mouse.down();
    await page.waitForTimeout(presses.ms);
    await page.mouse.up();
  } else {
    for (let i = 0; i < presses.taps; i++) {
      await page.getByRole("button", { name: "Attack", exact: true }).dispatchEvent("pointerdown");
      await page.waitForTimeout(60);
      await page.getByRole("button", { name: "Attack", exact: true }).dispatchEvent("pointerup");
      await page.waitForTimeout(330);
    }
  }
  return true;
}

async function forestSpot(page) {
  return page.evaluate(() => {
    const g = window.__hfGame;
    const m = g.map;
    const plot = m.plots[m.my_plot];
    const c = m.hub.center;
    const px = plot.origin[0] + 24;
    const py = plot.origin[1] + 24;
    const l = Math.hypot(px - c, py - c);
    for (let r = 188; r < 205; r++) {
      const x = Math.round(c + ((px - c) / l) * r);
      const y = Math.round(c + ((py - c) / l) * r);
      if (!g.grid.solid(x, y)) return [x, y];
    }
    return null;
  });
}

PHASES[4] = async (page, kind) => {
  await signupFlow(page, kind);
  await page.locator("canvas").first().waitFor();
  await page.waitForFunction(() => window.__hfGame);
  await page.waitForTimeout(2000);
  await enterAvatar(page);
  await shot(page, "01-explore", kind, { wait: 600 });
  const mobile = kind === "mobile";
  await chop(page, "tree", mobile ? { taps: 2 } : { mouse: true, ms: 420 });
  await shot(page, "02-chopping", kind, { wait: 80 });
  await chop(page, "tree", mobile ? { taps: 4 } : { mouse: true, ms: 1200 });
  await shot(page, "03-loot", kind, { wait: 250 });
  await chop(page, "rock", mobile ? { taps: 5 } : { mouse: true, ms: 1500 });
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: "Bag" }).click();
  await shot(page, "04-bag", kind, { wait: 500 });
  await page.getByRole("button", { name: "Close bag" }).click();
  if (!mobile) {
    const spot = await forestSpot(page);
    if (spot) {
      await walk(page, spot[0], spot[1]);
      await shot(page, "05-forest", kind, { wait: 600 });
      await chop(page, "tree", { mouse: true, ms: 900 });
      await shot(page, "06-forest-chop", kind, { wait: 200 });
    }
  }
  const door = await page.evaluate(() => window.__hfGame.avatar.client.info.home.door);
  const home = walk(page, Math.floor(door[0]), Math.floor(door[1]) + 1);
  await page.waitForFunction(() => (window.__hfDeposits ?? 0) > 0, null, { timeout: 120000 }).catch(() => undefined);
  await shot(page, "07-deposit", kind, { wait: 650 });
  await home;
  await page.getByRole("button", { name: "Back to village" }).click();
  await shot(page, "08-back-home", kind, { wait: 1200 });
};

// ── Phase 5: combat ──────────────────────────────────────────────────────
async function ringSpot(page, r) {
  return page.evaluate((radius) => {
    const g = window.__hfGame;
    const m = g.map;
    const plot = m.plots[m.my_plot];
    const c = m.hub.center;
    const px = plot.origin[0] + 24;
    const py = plot.origin[1] + 24;
    const l = Math.hypot(px - c, py - c);
    for (let k = 0; k < 40; k++) {
      const rr = radius + (k % 2 ? k : -k) * 0.5;
      const x = Math.round(c + ((px - c) / l) * rr);
      const y = Math.round(c + ((py - c) / l) * rr);
      if (!g.grid.solid(x, y)) return [x, y];
    }
    return null;
  }, r);
}

async function findMonster(page, maxMs = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    const m = await page.evaluate(() => window.__hfGame.devNearestMonster());
    if (m && m.d < 14) return m;
    await page.waitForTimeout(500);
  }
  return null;
}

PHASES[5] = async (page, kind) => {
  await signupFlow(page, kind);
  await page.locator("canvas").first().waitFor();
  await page.waitForFunction(() => window.__hfGame);
  await page.waitForTimeout(2000);
  await enterAvatar(page);
  const mobile = kind === "mobile";
  // meadow between the plots and the hub: slimes (try a few spots until some are in view)
  let m = null;
  for (const r of [62, 52, 72, 44]) {
    const spot = await ringSpot(page, r);
    if (spot) await walk(page, spot[0], spot[1]);
    m = await findMonster(page, 8000);
    if (m) break;
  }
  if (m) {
    const fight = page.evaluate(() => window.__hfGame.devFight(6000));
    await shot(page, "01-slimes", kind, { wait: 500 });
    await shot(page, "02-hit", kind, { wait: 250 });
    await shot(page, "03-swing", kind, { wait: 250 });
    await fight;
    await shot(page, "04-loot", kind, { wait: 200 });
  }
  if (!mobile) {
    const forest = await ringSpot(page, 196);
    if (forest) await walk(page, forest[0], forest[1]);
    m = await findMonster(page, 25000);
    if (m) {
      await shot(page, "05-forest-monsters", kind, { wait: 200 });
      const fight = page.evaluate(() => window.__hfGame.devFight(7000, 9));
      await shot(page, "06-forest-fight", kind, { wait: 1600 });
      await shot(page, "07-forest-fight-2", kind, { wait: 1500 });
      await fight;
      await shot(page, "08-after", kind, { wait: 300 });
    }
  }
  await page.getByRole("button", { name: "Bag" }).click();
  await shot(page, "09-bag", kind, { wait: 600 });
};

// ── Phase 6: combos & forging ────────────────────────────────────────────
function hf(args) {
  execSync(`uv run hf ${args}`, { cwd: join(ROOT, "backend"), env: { ...process.env, UV_SYSTEM_CERTS: "1" }, stdio: "ignore" });
}

const refresh = (page) => page.evaluate(() => window.__hfVillage.getState().fetch());

async function apiPost(page, path, body) {
  return page.evaluate(
    async ([p, b]) => {
      const csrf = document.cookie.split("; ").find((c) => c.startsWith("hf_csrf="))?.split("=")[1];
      const headers = { "content-type": "application/json", "x-csrf-token": csrf, "idempotency-key": crypto.randomUUID() };
      const r = await fetch(p, { method: "POST", headers, body: JSON.stringify(b) });
      return r.json();
    },
    [path, body],
  );
}

async function tapTile(page, tx, ty) {
  const box = await page.locator("canvas").first().boundingBox();
  const p = await page.evaluate(([x, y]) => window.__hfGame.frameTileToScreen(x, y), [tx, ty]);
  return { x: box.x + p.x, y: box.y + p.y };
}

PHASES[6] = async (page, kind) => {
  const mobile = kind === "mobile";
  const name = await signupFlow(page, kind);
  hf(`test-account ${name}`);
  hf(`grant ${name} --coins 3000 --res wood=1200 --res stone=1200 --res ore=300 --item ironbark=2`);
  await page.reload();
  await page.waitForFunction(() => window.__hfGame && window.__hfVillage?.getState().village);
  await page.waitForTimeout(1500);
  // a free spot for a forge with room for a lumber camp right beside it
  const spot = await page.evaluate(async () => {
    const ok = async (k, x, y) => (await (await fetch(`/api/village/preview?key=${k}&x=${x}&y=${y}`)).json()).valid;
    for (let y = 25; y <= 33; y++) {
      for (let x = 10; x <= 27; x++) {
        if ((await ok("forge", x, y)) && (await ok("lumber_camp", x + 3, y))) return [x, y];
      }
    }
    return null;
  });
  if (!spot) throw new Error("no spot for the forge");
  const [fx, fy] = spot;
  await apiPost(page, "/api/village/buildings", { key: "forge", x: fx, y: fy, rotation: 0 });
  hf(`fast-forward ${name} 30s`);
  await refresh(page);
  await page.evaluate(([x, y]) => window.__hfGame.devFocusTile?.(x, y), [fx + 3, fy + 1]);
  await page.waitForTimeout(800);

  // the ghost of a lumber camp beside the forge resonates
  await page.getByRole("button", { name: /^Build/ }).click();
  await page.getByRole("button", { name: /Lumber Camp/ }).click();
  const at = await tapTile(page, fx + 4.5, fy + 1.5);
  if (mobile) await page.mouse.click(at.x, at.y);
  else await page.mouse.move(at.x, at.y);
  await page.waitForTimeout(700);
  await shot(page, "01-resonance", kind, { wait: 300 });
  if (mobile) await page.getByRole("button", { name: "Place here" }).click();
  else await page.mouse.click(at.x, at.y);
  await page.waitForTimeout(500);
  hf(`fast-forward ${name} 30s`);
  await refresh(page);
  await shot(page, "02-discovery", kind, { wait: 950 });
  await page.getByText("Combo discovered!").first().waitFor({ timeout: 8000 });
  await shot(page, "03-discovery-card", kind, { wait: 700 });
  await page.getByRole("button", { name: "Amazing!" }).click();

  await page.getByRole("button", { name: "Recipe Book" }).click();
  await page.getByText(/Found \d of \d combos/).waitFor();
  await shot(page, "04-recipe-book", kind, { wait: 600 });
  await page.keyboard.press("Escape");

  // the forge: combo chip, craft panel, forge with an ironbark
  const fc = await tapTile(page, fx + 1.5, fy + 1.2);
  await page.mouse.click(fc.x, fc.y);
  await shot(page, "05-forge-selected", kind, { wait: 600 });
  await page.getByRole("button", { name: /^Craft/ }).click();
  await page.getByText("Forge gear").waitFor();
  await page.getByRole("button", { name: /Heavy/ }).first().click();
  await shot(page, "06-craft-panel", kind, { wait: 500 });
  await page.getByRole("button", { name: /Forge!/ }).click();
  await page.waitForTimeout(500);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await shot(page, "07-forging", kind, { wait: 1500 });
  hf(`fast-forward ${name} 20s`);
  await refresh(page);
  await shot(page, "08-ready", kind, { wait: 1200 });
  await page.mouse.click(fc.x, fc.y);
  await page.getByRole("button", { name: /^Craft/ }).click();
  await page.getByRole("button", { name: /Collect/ }).click();
  await page.getByText("Fresh from the forge").waitFor();
  await shot(page, "09-reveal", kind, { wait: 900 });
  await page.getByRole("button", { name: "Nice!" }).click();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Bag", exact: true }).click();
  await page.locator('button[title^="Copper Spear"]').first().click();
  await shot(page, "10-bag-gear", kind, { wait: 500 });
};

// ── Phase 7: market, merchant, bank ──────────────────────────────────────
let seeded = false;
PHASES[7] = async (page, kind) => {
  const mobile = kind === "mobile";
  if (!seeded) {
    hf("market seed --yes"); // DEV ONLY: 24 h of made-up realm sales so sparklines have a story
    seeded = true;
  }
  const name = await signupFlow(page, kind);
  hf(`test-account ${name}`);
  hf(`grant ${name} --coins 6000 --res wood=900 --res stone=900 --res ore=200 --item slime_gel=40 --item wolf_fang=12 --item ironbark=3`);
  await page.reload();
  await page.waitForFunction(() => window.__hfGame && window.__hfVillage?.getState().village);
  await page.waitForTimeout(1200);
  const spot = await page.evaluate(async () => {
    const ok = async (x, y) => (await (await fetch(`/api/village/preview?key=market&x=${x}&y=${y}`)).json()).valid;
    for (let y = 24; y <= 33; y++) for (let x = 12; x <= 28; x++) if (await ok(x, y)) return [x, y];
    return null;
  });
  if (!spot) throw new Error("no spot for the market");
  const [mx, my] = spot;
  await apiPost(page, "/api/village/buildings", { key: "market", x: mx, y: my, rotation: 0 });
  hf(`fast-forward ${name} 30s`);
  await refresh(page);
  await page.evaluate(([x, y]) => window.__hfGame.devFocusTile?.(x, y), [mx + 2, my + 1]);
  await page.waitForTimeout(900);
  const mc = await tapTile(page, mx + 2, my + 1.5);
  await page.mouse.click(mc.x, mc.y);
  await shot(page, "01-market-selected", kind, { wait: 600 });
  await page.getByRole("button", { name: /^Trade/ }).click();
  await page.locator(".market-row").first().waitFor();
  await page.getByRole("button", { name: "All", exact: true }).click();
  await page.locator(".market-row", { hasText: "Wood" }).first().click();
  await shot(page, "02-market", kind, { wait: 600 });
  if (!mobile) {
    const sb = await page.locator(".sell-box .spark svg").boundingBox();
    await page.mouse.move(sb.x + sb.width * 0.35, sb.y + sb.height / 2);
    await shot(page, "03-sparkline-hover", kind, { wait: 300 });
  }
  await page.getByRole("button", { name: "I have", exact: true }).click();
  await page.locator(".market-row", { hasText: "Wood" }).first().click();
  await page.locator(".sell-box").getByRole("button", { name: "100", exact: true }).click();
  await page.locator(".sell-box").getByRole("button", { name: /^Sell / }).click();
  await shot(page, "04-sold", kind, { wait: 700 });
  await page.locator(".market-row", { hasText: "Ironbark" }).first().click();
  await page.locator(".sell-box").getByRole("button", { name: /^All/ }).click();
  await shot(page, "05-sell-rare", kind, { wait: 400 });
  await page.getByRole("tab", { name: /Wandering merchant/ }).click();
  await page.locator(".stock-card").first().waitFor();
  await shot(page, "06-merchant-peek", kind, { wait: 500 });
  await page.keyboard.press("Escape");

  // the bank lives at home
  await page.getByRole("button", { name: "Bag and bank" }).click();
  await page.locator('button[title^="Slime Gel"]').first().click();
  await page.getByRole("button", { name: /To bank/ }).click();
  await page.waitForTimeout(500);
  await page.getByRole("tab", { name: /Bank/ }).click();
  await shot(page, "07-bank", kind, { wait: 500 });
  await page.getByRole("button", { name: "Close bag" }).click();

  // walk to the merchant's cart in the hub
  const m = await page.evaluate(() => fetch("/api/merchant/hub").then((r) => r.json()));
  await enterAvatar(page);
  const ok = await walk(page, Math.floor(m.pos[0]) - 1, Math.floor(m.pos[1]) + 2);
  if (!ok) await walk(page, Math.floor(m.pos[0]) - 1, Math.floor(m.pos[1]) + 2);
  await page.waitForTimeout(800);
  await page.locator(".trade-prompt").waitFor({ timeout: 8000 });
  await shot(page, "08-merchant-cart", kind, { wait: 400 });
  await page.locator(".trade-prompt").click({ force: true });
  await page.locator(".stock-card").first().waitFor();
  await shot(page, "09-merchant-buy", kind, { wait: 500 });
  const hint = page.locator(".stock-card", { hasText: "Recipe Hint" }).getByRole("button", { name: "Buy" });
  const target = (await hint.count()) ? hint : page.locator(".stock-card").getByRole("button", { name: "Buy" }).first();
  await target.click();
  await shot(page, "10-bought", kind, { wait: 700 });
  await page.keyboard.press("Escape");
  if (await hint.count()) {
    await page.keyboard.press("h");
    await page.waitForFunction(() => !window.__hfGame?.avatar);
    await page.waitForTimeout(900);
    await page.getByRole("button", { name: "Recipe Book" }).click();
    await page.getByText(/Found \d of \d combos/).waitFor();
    await shot(page, "11-hint-in-book", kind, { wait: 600 });
  }
};

// ── Phase 8: the whole tutorial, end to end (and timed) ──────────────────
async function freeSpot(page, key, near, extra) {
  return page.evaluate(
    async ([k, n, ex]) => {
      const ok = async (kk, x, y) => (await (await fetch(`/api/village/preview?key=${kk}&x=${x}&y=${y}`)).json()).valid;
      const cands = [];
      for (let y = 9; y <= 36; y++) for (let x = 9; x <= 36; x++) cands.push([x, y]);
      if (n) cands.sort((a, b) => Math.hypot(a[0] - n[0], a[1] - n[1]) - Math.hypot(b[0] - n[0], b[1] - n[1]));
      for (const [x, y] of cands) {
        if (!(await ok(k, x, y))) continue;
        if (ex && !(await ok(ex.key, x + ex.dx, y + ex.dy))) continue;
        return [x, y];
      }
      return null;
    },
    [key, near, extra],
  );
}

async function placeViaUI(page, kind, key, label, x, y) {
  const [fw, fh] = await page.evaluate((k) => window.__hfGame.defs[k].footprint, key);
  // tuck Juniper away so her card can't swallow the click (she pops back up when a step completes)
  if (await page.getByRole("button", { name: "Hide guide" }).count()) await page.getByRole("button", { name: "Hide guide" }).click();
  await page.evaluate(([tx, ty]) => window.__hfGame.devFocusTile?.(tx, ty), [x + fw / 2, y + fh / 2]);
  await page.waitForTimeout(250);
  await page.getByRole("button", { name: /^Build/ }).click();
  const tab = { lumber_camp: "Production", quarry: "Production", market: "Core", forge: "Crafting" }[key];
  if (tab) await page.locator(".build-menu").getByRole("tab", { name: tab, exact: true }).click();
  await page.locator(".build-menu").getByRole("button", { name: new RegExp(`^${label}`) }).first().click();
  // the pointer holds the footprint's centre tile: origin + floor((size − 1) / 2)
  const at = await tapTile(page, x + Math.floor((fw - 1) / 2) + 0.5, y + Math.floor((fh - 1) / 2) + 0.5);
  if (kind === "mobile") {
    await page.mouse.click(at.x, at.y);
    await page.getByRole("button", { name: "Place here" }).click();
  } else {
    await page.mouse.move(at.x, at.y);
    await page.waitForTimeout(150);
    await page.mouse.click(at.x, at.y);
  }
  await page.waitForTimeout(400);
}

const guideTitle = (page) => page.locator(".guide-card .head").nth(1).textContent().catch(() => "");
async function waitStep(page, title, ms = 60000) {
  await page.locator(".guide-card", { hasText: title }).waitFor({ timeout: ms });
}

PHASES[8] = async (page, kind) => {
  const mobile = kind === "mobile";
  const t0 = Date.now();
  const times = {};
  const mark = (k) => {
    times[k] = Math.round((Date.now() - t0) / 1000);
    console.log(`[${kind}] ${k} at ${times[k]}s`);
  };
  const name = await signupFlow(page, kind);
  await page.waitForFunction(() => window.__hfGame && window.__hfVillage?.getState().village);
  const tStart = Date.now();
  await page.locator(".guide-card").waitFor();
  await shot(page, "05-juniper", kind, { wait: 1800 });
  while (await page.getByRole("button", { name: "Next ›" }).count()) await page.getByRole("button", { name: "Next ›" }).click();
  await page.getByRole("button", { name: "Let's go!" }).click();
  await waitStep(page, "Wood and stone");
  await shot(page, "06-step-build", kind, { wait: 1500 });
  if (mobile) {
    // the phone run only checks the guide's layout; the full flow is timed on desktop
    await page.getByRole("button", { name: "Hide guide" }).click();
    await shot(page, "07-guide-minimized", kind, { wait: 400 });
    hf(`test-account ${name}`);
    return;
  }
  // 1. lumber camp (with room for a forge right beside it) and a quarry
  const lc = await freeSpot(page, "lumber_camp", [27, 21], { key: "forge", dx: 3, dy: 0 });
  await placeViaUI(page, kind, "lumber_camp", "Lumber Camp", lc[0], lc[1]);
  const q = await freeSpot(page, "quarry", [20, 27]);
  await placeViaUI(page, kind, "quarry", "Quarry", q[0], q[1]);
  await waitStep(page, "Get your hands dirty");
  mark("built camp + quarry");
  // 2. chop trees
  await enterAvatar(page);
  await shot(page, "08-explore-step", kind, { wait: 500 });
  for (let i = 0; i < 8 && (await guideTitle(page)) === "Get your hands dirty"; i++) {
    await chop(page, "tree", { mouse: true, ms: 1500 });
  }
  await waitStep(page, "Slime trouble", 30000);
  mark("chopped wood");
  // 3. two slimes
  const radii = [62, 52, 72, 44, 82, 58, 68, 48, 78, 62, 52, 72];
  for (let i = 0; i < radii.length && (await guideTitle(page)) === "Slime trouble"; i++) {
    const m = await findMonster(page, 3000);
    const me = await page.evaluate(() => { const c = window.__hfGame.avatar.client; return [c.me.x.toFixed(1), c.me.y.toFixed(1), window.__hfGame.avatar.client.ents.size]; });
    console.log(`[${kind}] slime hunt ${i}: me=${me} monster=${m ? `${m.key}@${m.x.toFixed(1)},${m.y.toFixed(1)} d=${m.d.toFixed(1)}` : "none"}`);
    if (m) {
      // path around the trees first; the fight autopilot only charges in a straight line
      await Promise.race([walk(page, Math.floor(m.x), Math.floor(m.y)), page.waitForTimeout(6000)]);
      await page.evaluate(() => window.__hfGame.devFight(8000));
      await page.waitForTimeout(1500); // let the room write the kill counter
      continue;
    }
    const spot = await ringSpot(page, radii[i]);
    if (spot) await walk(page, spot[0], spot[1]);
  }
  await waitStep(page, "Coin for your trouble", 30000);
  mark("slimes");
  await shot(page, "09-step-market", kind, { wait: 400 });
  for (let i = 0; i < 12 && (await page.evaluate(() => Boolean(window.__hfGame?.avatar))); i++) {
    await page.keyboard.press("h"); // refused for a few seconds after a fight (combat lock)
    await page.waitForTimeout(1500);
  }
  await page.waitForFunction(() => !window.__hfGame?.avatar, null, { timeout: 15000 });
  await page.waitForTimeout(1000);
  // 4. build a market and sell something
  const mk = await freeSpot(page, "market", [16, 14]);
  await placeViaUI(page, kind, "market", "Market", mk[0], mk[1]);
  await page.waitForTimeout(11000);
  await page.getByRole("button", { name: "Market", exact: true }).click();
  await page.locator(".sell-box").getByRole("button", { name: /^Sell / }).click();
  await page.keyboard.press("Escape");
  await waitStep(page, "Buildings that work together", 20000);
  mark("sold");
  // 5. the forge beside the lumber camp: the combo
  await placeViaUI(page, kind, "forge", "Forge", lc[0] + 3, lc[1]);
  await page.getByText("Combo discovered!").first().waitFor({ timeout: 30000 });
  await shot(page, "10-discovery", kind, { wait: 600 });
  await page.getByRole("button", { name: "Amazing!" }).click();
  await waitStep(page, "Your first spear", 20000);
  mark("combo");
  // 6. forge a spear
  const fc = await tapTile(page, lc[0] + 4.5, lc[1] + 1.5);
  await page.mouse.click(fc.x, fc.y);
  await page.getByRole("button", { name: /^Craft/ }).click();
  await page.getByRole("button", { name: /Forge!/ }).click();
  await page.waitForTimeout(6000);
  await page.getByRole("button", { name: /Collect/ }).click();
  await page.getByText("Fresh from the forge").waitFor();
  await page.getByRole("button", { name: "Nice!" }).click();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await waitStep(page, "You're a natural", 20000);
  mark("spear");
  await shot(page, "11-done", kind, { wait: 1800 });
  await page.getByRole("button", { name: "Thanks, Juniper!" }).click();
  await page.locator(".guide-card").waitFor({ state: "detached" });
  const total = Math.round((Date.now() - tStart) / 1000);
  times.total_tutorial_s = total;
  writeFileSync(join(OUT, "e2e-timings.json"), JSON.stringify(times, null, 2));
  console.log(`[${kind}] tutorial finished in ${total}s`);
  if (total >= 300) throw new Error(`tutorial took ${total}s (budget 300s)`);

  // the away card: snapshot as if we'd left 3 hours ago
  hf(`test-account ${name}`);
  await page.goto("about:blank"); // leaving closes the socket, which snapshots the village
  await page.waitForTimeout(1500);
  hf(`fast-forward ${name} 3h`);
  await page.goto(`${BASE}/play`);
  await page.getByText("While you were away").waitFor({ timeout: 15000 });
  await shot(page, "12-away-card", kind, { wait: 700 });
};

// ── Phase 9: two players in one realm ────────────────────────────────────
async function freshPlayer(page, kind) {
  const name = await signupFlow(page, kind);
  await page.waitForFunction(() => window.__hfGame && window.__hfVillage?.getState().village);
  await apiPost(page, "/api/tutorial/skip", {});
  await page.reload();
  await page.waitForFunction(() => window.__hfGame && window.__hfVillage?.getState().village);
  await page.waitForTimeout(1500);
  return name;
}

async function walkTo(page, x, y, ms = 60000) {
  // pathfinding only sees loaded chunks, so long trips go in short hops toward the target
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const hop = await page.evaluate(([tx, ty]) => {
      const g = window.__hfGame;
      const c = g.avatar.client;
      const dx = tx + 0.5 - c.me.x;
      const dy = ty + 0.5 - c.me.y;
      const d = Math.hypot(dx, dy);
      if (d < 2.2) return null;
      const k = Math.min(1, 16 / d);
      for (let r = 0; r < 6; r++) {
        for (const [ox, oy] of [[0, 0], [r, 0], [-r, 0], [0, r], [0, -r], [r, r], [-r, -r], [r, -r], [-r, r]]) {
          const hx = Math.floor(c.me.x + dx * k) + ox;
          const hy = Math.floor(c.me.y + dy * k) + oy;
          if (!g.grid.solid(hx, hy)) return [hx, hy];
        }
      }
      return [Math.floor(c.me.x + dx * k), Math.floor(c.me.y + dy * k)];
    }, [x, y]);
    if (!hop) return true;
    const ok = await Promise.race([walk(page, hop[0], hop[1]), page.waitForTimeout(8000).then(() => false)]);
    if (!ok) await page.waitForTimeout(400);
  }
  return false;
}

PHASES[9] = async (page, kind) => {
  const mobile = kind === "mobile";
  const ada = await freshPlayer(page, kind);
  await page.getByRole("button", { name: "Realm", exact: true }).click();
  await page.getByText("Open your realm").waitFor();
  await shot(page, "01-realm-solo", kind, { wait: 600 });
  await page.getByLabel("Realm name").fill("Hearth Hollow");
  await page.getByRole("button", { name: "Open it up" }).click();
  await page.locator(".invite-chip .code").waitFor();
  await shot(page, "02-realm-open", kind, { wait: 600 });
  const code = (await page.locator(".invite-chip .code").textContent()).trim();
  if (mobile) {
    await page.keyboard.press("Escape");
    await enterAvatar(page);
    await shot(page, "03-minimap-avatar", kind, { wait: 900 });
    await page.keyboard.press("m");
    await shot(page, "04-map", kind, { wait: 700 });
    return;
  }

  // a second player joins with the code
  const ctx2 = await page.context().browser().newContext(VIEWPORTS[kind]);
  const p2 = await ctx2.newPage();
  p2.on("pageerror", (e) => console.error(`[bram] page error:`, e.message));
  const bram = await freshPlayer(p2, kind);
  await p2.getByRole("button", { name: "Realm", exact: true }).click();
  await p2.getByLabel("Invite code").fill(code);
  await p2.getByRole("button", { name: "Join realm" }).click();
  await p2.waitForTimeout(2500); // the page reloads into the new realm
  await p2.waitForFunction(() => window.__hfGame && window.__hfVillage?.getState().village);
  await p2.waitForTimeout(1500);
  await shot(p2, "03-bram-joined", kind, { wait: 400 });

  // the owner sees Bram arrive (pushed over the socket)
  await page.locator(".member-row", { hasText: bram }).waitFor({ timeout: 15000 });
  await shot(page, "04-members-owner", kind, { wait: 500 });

  // the stash
  hf(`grant ${ada} --item ironbark=6 --item slime_gel=12`);
  await page.getByRole("tab", { name: /Stash/ }).click();
  await page.locator('button[title^="Ironbark"]').first().click();
  await page.waitForTimeout(500);
  await page.locator('button[title^="Slime Gel"]').first().click();
  await page.waitForTimeout(500);
  await shot(page, "05-stash-owner", kind, { wait: 400 });
  await p2.getByRole("button", { name: "Realm", exact: true }).click();
  await p2.getByRole("tab", { name: /Stash/ }).click();
  await p2.locator(".stash-rules").waitFor();
  await shot(p2, "06-stash-newcomer", kind, { wait: 500 });
  await p2.keyboard.press("Escape");
  await page.getByRole("tab", { name: /Activity/ }).click();
  await page.locator(".activity-row").first().waitFor();
  await shot(page, "07-activity", kind, { wait: 500 });
  await page.keyboard.press("Escape");

  // Bram's village, seen from Ada's
  const look = await page.evaluate(() => {
    const m = window.__hfVillage.getState().map;
    const mine = m.plots[m.my_plot].origin;
    const theirs = m.plots.find((p) => p.owner && p.index !== m.my_plot).origin;
    return [theirs[0] - mine[0] + 24, theirs[1] - mine[1] + 24];
  });
  await page.evaluate(([x, y]) => window.__hfGame.devFocusTile(x, y), look);
  await shot(page, "08-neighbour-village", kind, { wait: 1800 });

  // a party
  await enterAvatar(page);
  await enterAvatar(p2);
  await page.getByRole("button", { name: "Party", exact: true }).click();
  await page.locator(".party-pop").getByRole("button", { name: "Invite" }).first().click();
  await p2.locator(".party-invite").waitFor({ timeout: 10000 });
  await shot(p2, "09-party-invite", kind, { wait: 300 });
  await p2.getByRole("button", { name: "Join", exact: true }).click();
  await page.locator(".party-frames").waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "Party", exact: true }).click();
  await shot(page, "10-party", kind, { wait: 800 });

  // waystones: attune the one by the well, walk out along a trail to a meadow stone, then travel back
  const ov = await page.evaluate(() => fetch("/api/realm/overview").then((r) => r.json()));
  await page.locator(".party-pop").waitFor({ state: "detached", timeout: 1000 }).catch(() => page.getByRole("button", { name: "Party", exact: true }).click());
  const hub = ov.waystones[0];
  await walkTo(page, hub.x, hub.y + 1, 200000);
  await page.waitForTimeout(900);
  await shot(page, "11-waystone-attuned", kind, { wait: 200 });
  const meadow = ov.waystones.slice(1, 6).sort((a, b) => Math.hypot(a.x - hub.x, a.y - hub.y) - Math.hypot(b.x - hub.x, b.y - hub.y))[0];
  await walkTo(page, meadow.x, meadow.y + 1, 200000);
  await page.waitForTimeout(900);
  await page.keyboard.press("m");
  await shot(page, "12-map", kind, { wait: 700 });
  await page.getByRole("button", { name: "Close" }).last().click();
  await page.keyboard.press("e");
  await page.getByText("Waystone: where to?").waitFor({ timeout: 8000 });
  await shot(page, "13-travel", kind, { wait: 600 });
  await page.locator(".map-side").getByRole("button", { name: "Go" }).first().click();
  await page.waitForTimeout(1600);
  await shot(page, "14-teleported", kind, { wait: 300 });
  await ctx2.close();
};

PHASES["9v"] = async (page, kind) => {
  await freshPlayer(page, kind);
  await apiPost(page, "/api/realms", { name: "Neighbourly" });
  const code = (await page.evaluate(() => fetch("/api/realm").then((r) => r.json()))).realm.invite_code;
  const ctx2 = await page.context().browser().newContext(VIEWPORTS[kind]);
  const p2 = await ctx2.newPage();
  await freshPlayer(p2, kind);
  await apiPost(p2, "/api/realms/join", { code });
  await page.waitForTimeout(3000);
  console.log("mates drawn:", await page.evaluate(() => window.__hfGame.mates.drawn.size));
  await enterAvatar(page);
  const gate = await page.evaluate(() => {
    const m = window.__hfVillage.getState().map;
    const p = m.plots.find((q) => q.owner && q.index !== m.my_plot);
    return [p.origin[0] + p.gate[0], p.origin[1] + p.gate[1] + 2];
  });
  await walkTo(page, gate[0], gate[1], 150000);
  await shot(page, "15-mate-village", kind, { wait: 800 });
  await ctx2.close();
};

PHASES[10] = async (page, kind) => {
  await freshPlayer(page, kind);
  await page.waitForFunction(() => window.__hfSky);
  await page.evaluate(() => window.__hfSky("day,clear,spring"));
  await shot(page, "01-village-day", kind, { wait: 1500 });
  await page.evaluate(() => window.__hfSky("dusk,0.5,autumn"));
  await shot(page, "02-village-dusk", kind, { wait: 900 });
  await page.evaluate(() => window.__hfSky("night,clear"));
  await shot(page, "03-village-night", kind, { wait: 900 });
  await page.evaluate(() => window.__hfSky("day,rain,autumn"));
  await page.locator(".world-chip").click();
  await shot(page, "04-rain-forecast", kind, { wait: 1400 });
  await page.locator(".world-chip").click();
  await page.evaluate(() => window.__hfSky("day,clear,summer"));
  await enterAvatar(page);
  const tour = [
    ["05-forest-storm", 192, "day,storm,summer"],
    ["06-stonepeak", 233, "day,clear,summer"],
    ["07-swamp-fog", 273, "day,fog,autumn"],
    ["08-frozen-snow", 313, "day,snow,winter"],
    ["09-ashen", 352, "day,clear,summer"],
    ["10-ashen-night", 352, "night,clear,summer"],
  ];
  for (const [name, r, sky] of tour) {
    const spot = await ringSpot(page, r);
    await apiPost(page, "/api/dev/teleport", { x: spot[0], y: spot[1] });
    await page.evaluate((q) => window.__hfSky(q), sky);
    await page.waitForTimeout(4000); // chunks load, spawn points wake
    await shot(page, name, kind, { wait: 300 });
  }
  // points of interest
  await page.evaluate(() => window.__hfSky("day,clear,summer"));
  const ov = await page.evaluate(async () => (await fetch("/api/realm/overview")).json());
  const pick = (k) => ov.pois.find((q) => q.kind === k && (q.biome ?? "") !== "ashen" && Math.hypot(q.x - 384, q.y - 384) < 260) ?? ov.pois.find((q) => q.kind === k);
  const visits = [
    ["11-ruins-chest", "ruins"],
    ["12-shrine", "shrine"],
    ["13-lore-stone", "lore_stone"],
    ["14-trader", "merchant"],
    ["15-lost-villager", "lost_villager"],
    ["16-sealed-cave", "cave"],
  ];
  for (const [name, k] of visits) {
    const q = pick(k);
    await apiPost(page, "/api/dev/teleport", { x: q.x, y: q.y + 2 });
    await page.waitForTimeout(2800);
    await page.keyboard.press("e");
    await page.waitForTimeout(900);
    await shot(page, name, kind, { wait: 300 });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
  }
  await page.keyboard.press("m");
  await shot(page, "17-map-pois", kind, { wait: 1200 });
  await page.keyboard.press("Escape");
};

// Phase 11: find a base tile where a whole cluster of buildings fits (each checked with the server preview)
async function placeCluster(page, members) {
  const base = await page.evaluate(async (ms) => {
    const ok = async (k, x, y) => (await (await fetch(`/api/village/preview?key=${k}&x=${x}&y=${y}`)).json()).valid;
    for (let y = 9; y <= 34; y++) {
      for (let x = 9; x <= 34; x++) {
        let all = true;
        for (const [k, dx, dy] of ms) {
          if (!(await ok(k, x + dx, y + dy))) {
            all = false;
            break;
          }
        }
        if (all) return [x, y];
      }
    }
    return null;
  }, members);
  if (!base) return false;
  for (const [key, dx, dy] of members) {
    for (let attempt = 0; attempt < 4; attempt++) {
      const r = await apiPost(page, "/api/village/buildings", { key, x: base[0] + dx, y: base[1] + dy, rotation: 0 });
      if (r.error?.code === "queue_full") {
        await page.waitForTimeout(5500); // two builders: wait for one to finish
        continue;
      }
      if (r.error) console.log("place", key, JSON.stringify(r.error).slice(0, 160));
      break;
    }
  }
  return base;
}

async function equipFromBag(page, key, dst) {
  return page.evaluate(async ([k, d]) => {
    const inv = await (await fetch("/api/inventory")).json();
    const s = inv.inventory.slots.find((x) => x.item === k);
    if (!s) return false;
    const csrf = document.cookie.split("; ").find((c) => c.startsWith("hf_csrf="))?.split("=")[1];
    await fetch("/api/inventory/move", {
      method: "POST",
      headers: { "content-type": "application/json", "x-csrf-token": csrf },
      body: JSON.stringify({ src: { kind: "inventory", slot: s.slot }, dst: { kind: "equipment", slot: d } }),
    });
    return true;
  }, [key, dst]);
}

PHASES[11] = async (page, kind) => {
  await freshPlayer(page, kind);
  await apiPost(page, "/api/dev/kit", { town_hall: 3, tier: 2 });
  const a = await placeCluster(page, [["forge", 0, 0], ["wizard_tower", 3, 0], ["quarry", 5, 0], ["lumber_camp", 0, 3]]);
  await placeCluster(page, [["alchemist", 0, 0], ["herb_garden", 2, 0], ["workshop", 0, 3], ["tavern", 3, 3]]);
  await page.waitForTimeout(12500); // the builds finish
  await page.reload();
  await page.waitForFunction(() => window.__hfGame && window.__hfVillage?.getState().village);
  await page.waitForTimeout(2500);
  if (a) await page.evaluate(([x, y]) => window.__hfGame.devFocusTile?.(x, y), [a[0] + 4, a[1] + 3]);
  await shot(page, "01-new-buildings-and-combos", kind, { wait: 900 });
  // gear up: shield + quick-slots
  await equipFromBag(page, "shield", 1);
  for (const [k, q] of [["healing_potion", 4], ["stamina_potion", 5], ["warrior_stew", 6], ["swift_tart", 7]]) await equipFromBag(page, k, q);
  await enterAvatar(page);
  await page.keyboard.press("b");
  await shot(page, "02-bag-offhand-quickslots", kind, { wait: 900 });
  await page.keyboard.press("b");
  const spot = await ringSpot(page, 190);
  const tour = [
    ["03-warhammer-quake", "warhammer", "q"],
    ["04-bow-volley", "bow", "q"],
    ["05-staff-barrier", "crystal_staff", "q"],
    ["06-enchanted-burst", "enchanted_sword", "q"],
    ["07-harpoon-whirlpool", "harpoon", "q"],
    ["08-arcane-starfall", "arcane_bow", "q"],
  ];
  for (const [name, weapon, key] of tour) {
    await equipFromBag(page, weapon, 0);
    await apiPost(page, "/api/dev/teleport", { x: spot[0], y: spot[1] });
    await page.waitForTimeout(1800);
    await page.keyboard.press(key);
    await page.waitForTimeout(weapon === "harpoon" || weapon === "arcane_bow" ? 650 : 380);
    await shot(page, name, kind, { wait: 0 });
    await page.waitForTimeout(600);
    // put it back so the next weapon can come out
    await page.evaluate(async () => {
      const csrf = document.cookie.split("; ").find((c) => c.startsWith("hf_csrf="))?.split("=")[1];
      const inv = await (await fetch("/api/inventory")).json();
      const used = new Set(inv.inventory.slots.map((x) => x.slot));
      let free = 0;
      while (used.has(free)) free++;
      await fetch("/api/inventory/move", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf },
        body: JSON.stringify({ src: { kind: "equipment", slot: 0 }, dst: { kind: "inventory", slot: free } }),
      });
    });
  }
  // offhands: bombs away, then a shield block
  await equipFromBag(page, "warhammer", 0);
  await page.evaluate(async () => {
    const csrf = document.cookie.split("; ").find((c) => c.startsWith("hf_csrf="))?.split("=")[1];
    const inv = await (await fetch("/api/inventory")).json();
    const used = new Set(inv.inventory.slots.map((x) => x.slot));
    let free = 0;
    while (used.has(free)) free++;
    await fetch("/api/inventory/move", {
      method: "POST",
      headers: { "content-type": "application/json", "x-csrf-token": csrf },
      body: JSON.stringify({ src: { kind: "equipment", slot: 1 }, dst: { kind: "inventory", slot: free } }),
    });
  });
  await equipFromBag(page, "barrel_bombs", 1);
  await apiPost(page, "/api/dev/teleport", { x: spot[0], y: spot[1] });
  await page.waitForTimeout(1800);
  await page.keyboard.press("f");
  await page.waitForTimeout(1350);
  await shot(page, "09-barrel-bomb", kind, { wait: 0 });
  await page.keyboard.press("3");
  await shot(page, "10-food-buff-hotbar", kind, { wait: 700 });
};

// ── Phase 12: delves ─────────────────────────────────────────────────────
// centre (world tile) of the first room of a role in the delve you're in
const delveRoom = (page, role) =>
  page.evaluate((k) => {
    const d = window.__hfDelve.getState().delve;
    const r = d?.layout.rooms.find((q) => q[1] === k);
    if (!d || !r) return null;
    const [id, , x, y, w, h, , puzzle] = r;
    return { id, puzzle, x: d.origin[0] + x + Math.floor(w / 2), y: d.origin[1] + y + Math.floor(h / 2) };
  }, role);

const delveProp = (page, room, kind, data) =>
  page.evaluate(([rid, k, dd]) => {
    const d = window.__hfDelve.getState().delve;
    const p = d?.layout.props.find((q) => q[0] === k && q[3] === rid && (dd === null || q[4] === dd));
    return p ? { x: d.origin[0] + p[1], y: d.origin[1] + p[2] } : null;
  }, [room, kind, data]);

const hop = async (page, x, y, ms = 1800) => {
  await apiPost(page, "/api/dev/teleport", { x, y });
  await page.waitForTimeout(ms);
};

PHASES[12] = async (page, kind) => {
  await freshPlayer(page, kind);
  await apiPost(page, "/api/dev/kit", { town_hall: 3, tier: 3 });
  await equipFromBag(page, "enchanted_sword", 0);
  await enterAvatar(page);
  const gate = await page.evaluate(() => window.__hfRealm.getState().overview?.pois.find((q) => q.kind === "delve"));
  if (!gate) throw new Error("no Delve Gate in the overview");
  await hop(page, gate.x, gate.y + 2);
  await shot(page, "01-delve-gate", kind, { wait: 300 });
  if (kind === "mobile") await page.locator(".trade-prompt").first().click({ force: true });
  else await page.keyboard.press("e");
  await page.getByText("Today's delve is the same").waitFor();
  await shot(page, "02-gate-leaderboard", kind, { wait: 900 });
  await page.getByRole("button", { name: /Enter today's delve/ }).click();
  await page.waitForFunction(() => window.__hfDelve.getState().delve);
  await shot(page, "03-entrance", kind, { wait: 1800 });
  // a combat room: the pack wakes and the gates slam down
  const combat = await delveRoom(page, "combat");
  if (combat) {
    await hop(page, combat.x, combat.y, 2200);
    await shot(page, "04-combat-room-locked", kind, { wait: 0 });
    const fight = page.evaluate(() => window.__hfGame.devFight(5000, 4));
    await shot(page, "05-delve-fight", kind, { wait: 1600 });
    await fight;
  }
  // a puzzle: step on the first rune plate, or stand by a lever
  const puzzle = await delveRoom(page, "puzzle");
  if (puzzle) {
    const plate = puzzle.puzzle === "plates" ? await delveProp(page, puzzle.id, "plate", 0) : null;
    const lever = plate ? null : await delveProp(page, puzzle.id, "lever", null);
    const at = plate ?? (lever ? { x: lever.x, y: lever.y + 1 } : puzzle);
    await hop(page, at.x, at.y, 1500);
    await shot(page, "06-puzzle-room", kind, { wait: 300 });
  }
  // the boss: shove it down to its last phase so the run reaches the portal in screenshot time
  const boss = await delveRoom(page, "boss");
  if (boss) {
    await hop(page, boss.x, boss.y + 3, 2600);
    await shot(page, "07-boss", kind, { wait: 0 });
    await apiPost(page, "/api/dev/delve-weaken", { frac: 0.3 });
    const fight = page.evaluate(() => window.__hfGame.devFight(6000, 3));
    await shot(page, "08-boss-fight", kind, { wait: 2600 });
    await fight;
    for (let i = 0; i < 8; i++) {
      if (await page.evaluate(() => window.__hfDelve.getState().state?.portal)) break;
      await apiPost(page, "/api/dev/delve-weaken", { frac: 0.02 });
      await apiPost(page, "/api/dev/teleport", { x: boss.x, y: boss.y + 3 }); // a fresh grace window
      await page.evaluate(() => window.__hfGame.devFight(5000));
    }
    await page.waitForFunction(() => window.__hfDelve.getState().state?.portal, null, { timeout: 20000 });
    await shot(page, "09-portal", kind, { wait: 1500 });
    await page.getByRole("button", { name: "Head home" }).click();
    await page.waitForFunction(() => !window.__hfDelve.getState().delve);
    await page.waitForTimeout(6000); // the run is saved on the next flush
    await page.evaluate(() => window.__hfDelve.getState().set({ panel: true }));
    await page.getByText("Today's delve is the same").waitFor();
    await shot(page, "10-on-the-board", kind, { wait: 1200 });
  }
};

// ── Phase 13: raids and realm bosses ─────────────────────────────────────
const villageNow = (page) => page.evaluate(() => window.__hfVillage.getState().village);

async function reloadVillage(page) {
  await page.reload();
  await page.waitForFunction(() => window.__hfGame && window.__hfVillage?.getState().village);
  await page.waitForTimeout(2000);
}

async function fightFor(page, ms, heavy = 4) {
  await page.evaluate(([t, h]) => window.__hfGame.devFight(t, h), [ms, heavy]);
}

PHASES[13] = async (page, kind) => {
  await freshPlayer(page, kind);
  await apiPost(page, "/api/dev/kit", { town_hall: 3, tier: 3 });
  const base = await placeCluster(page, [["storehouse", 0, 0], ["guard_post", 4, 0], ["watchtower", 3, 3], ["watchtower", 7, 1]]);
  await page.waitForTimeout(12000);
  await reloadVillage(page);
  await page.evaluate(async () => {
    const st = window.__hfVillage.getState();
    const gp = st.village.buildings.find((b) => b.key === "guard_post");
    if (gp && st.village.villagers[0]) await st.assignVillager(st.village.villagers[0].id, gp.id);
  });
  if (base) await page.evaluate(([x, y]) => window.__hfGame.devFocusTile?.(x, y), [base[0] + 4, base[1] + 2]);
  await shot(page, "01-defences", kind, { wait: 1200 });
  await apiPost(page, "/api/dev/wave", { warning: 25, town_hall: 2 });
  await page.getByText("Raiders approaching").waitFor({ timeout: 15000 });
  await shot(page, "02-raid-warning", kind, { wait: 800 });
  await page.getByRole("button", { name: /Defend!/ }).click();
  await page.waitForFunction(() => window.__hfGame?.avatar?.client);
  await page.waitForTimeout(2500);
  await shot(page, "03-defend-hop", kind, { wait: 0 });
  await page.getByText("Raid on your village!").waitFor({ timeout: 60000 });
  await page.waitForTimeout(7000); // the first band marches in through the gate
  await shot(page, "04-raid-marching", kind, { wait: 0 });
  const t0 = Date.now();
  let fought = false;
  while (Date.now() - t0 < 200000) {
    const done = await page.getByText(/Raid beaten off|Flawless defence|Overrun/).count();
    if (done) break;
    const m = await page.evaluate(() => window.__hfGame.devNearestMonster());
    if (m && m.d < 12) {
      const f = fightFor(page, 5000);
      if (!fought) {
        fought = true;
        await shot(page, "05-raid-fight", kind, { wait: 1800 });
      }
      await f;
    } else await page.waitForTimeout(1500);
  }
  await page.getByText(/Raid beaten off|Flawless defence|Overrun/).waitFor({ timeout: 30000 });
  await shot(page, "06-raid-report", kind, { wait: 900 });
  await page.getByRole("button", { name: "Back to it" }).click();
  // realm bosses, out in the meadow
  const spot = await ringSpot(page, 150);
  await apiPost(page, "/api/dev/teleport", { x: spot[0], y: spot[1] });
  await page.waitForTimeout(1500);
  await apiPost(page, "/api/dev/boss", { key: "grubmaw", distance: 5 });
  await page.waitForTimeout(3500);
  await shot(page, "07-grubmaw", kind, { wait: 0 });
  const f1 = fightFor(page, 4000, 3);
  await shot(page, "08-boss-fight", kind, { wait: 2600 });
  await f1;
  await apiPost(page, "/api/dev/delve-weaken", { frac: 0.3 });
  await apiPost(page, "/api/dev/teleport", { x: spot[0], y: spot[1] });
  await page.waitForTimeout(2200);
  await shot(page, "09-grubmaw-slimelings", kind, { wait: 0 });
  if (kind !== "mobile") {
    await page.keyboard.press("m");
    await shot(page, "10-boss-on-the-map", kind, { wait: 900 });
    await page.keyboard.press("Escape");
  }
  for (const [i, key] of ["stone_colossus", "swamp_hydra", "frost_matriarch", "cinder_tyrant"].entries()) {
    await apiPost(page, "/api/dev/teleport", { x: spot[0], y: spot[1] });
    await page.waitForTimeout(800);
    await apiPost(page, "/api/dev/boss", { key, distance: 5 });
    await page.waitForTimeout(3500);
    if (key === "frost_matriarch" || key === "cinder_tyrant") {
      await apiPost(page, "/api/dev/delve-weaken", { frac: 0.14 });
      await page.waitForTimeout(1600);
    }
    await shot(page, `${11 + i}-${key.replace(/_/g, "-")}`, kind, { wait: 0 });
    if (kind === "mobile" && i >= 1) break;
  }
};

// ── Phase 14: villagers and beauty ──────────────────────────────────────
async function decorate(page, list) {
  for (const [key, x, y] of list) {
    let r = await apiPost(page, "/api/village/buildings", { key, x, y, rotation: 0 });
    if (r.error?.code === "debris") {
      // a tree or rock in the way: clear it and try again
      const v = await villageNow(page);
      for (const d of v.debris.filter((d) => Math.abs(d[3] - x) <= 2 && Math.abs(d[4] - y) <= 2)) {
        await apiPost(page, `/api/village/debris/${d[0]}/clear`, {});
      }
      r = await apiPost(page, "/api/village/buildings", { key, x, y, rotation: 0 });
    }
    if (r.error) console.log("decor", key, x, y, r.error.code);
  }
}

PHASES[14] = async (page, kind) => {
  const name = await freshPlayer(page, kind);
  await apiPost(page, "/api/dev/kit", { town_hall: 4, tier: 2 });
  hf(`test-account ${name}`);
  hf(`grant ${name} --coins 6000 --res stone=1500 --res wood=1500 --res food=600`);
  // homes, food and a tavern so the village is lively and content (TH at 22,19; house at 17,20)
  await decorate(page, [["house", 13, 20], ["farm", 9, 25], ["tavern", 27, 20]]);
  await page.waitForTimeout(6000);
  await decorate(page, [["house", 17, 15], ["lumber_camp", 30, 15]]);
  await page.waitForTimeout(12000);
  // paths from the Town Hall door, flowers, lamps, benches, a fountain and a statue
  const path = [];
  for (let y = 23; y <= 29; y++) path.push(["path_stone", 24, y], ["path_stone", 23, y]);
  for (let x = 17; x <= 22; x++) path.push(["path_dirt", x, 23]);
  for (let x = 25; x <= 29; x++) path.push(["path_dirt", x, 26]);
  await decorate(page, path);
  await decorate(page, [
    ["flower_bed", 22, 25], ["flower_bed", 25, 25], ["flower_bed", 22, 27], ["flower_bed", 25, 28],
    ["lantern", 22, 29], ["lantern", 25, 29], ["bench", 21, 26], ["hedge", 26, 23], ["hedge", 27, 23],
    ["fountain", 19, 27], ["statue", 26, 28], ["young_tree", 15, 25], ["young_tree", 16, 28],
    ["well", 29, 27], ["banner", 21, 22], ["market_stall", 27, 30], ["pumpkins", 30, 30],
  ]);
  hf(`fast-forward ${name} 1h`);
  await reloadVillage(page);
  await page.waitForFunction(() => window.__hfSky);
  await page.evaluate(() => window.__hfSky("day,clear,summer")); // a bright summer's day for the village shots
  await page.evaluate(() => window.__hfGame.devFocusTile?.(24, 26));
  await page.waitForTimeout(4000); // villagers walk out to work
  await shot(page, "01-decorated-village", kind, { wait: 500 });
  await page.evaluate(() => window.__hfGame.villagerLife?.devSay("What a lovely day."));
  await shot(page, "02-speech-bubble", kind, { wait: 600 });
  await page.getByRole("button", { name: /^Build/ }).click();
  await page.getByRole("tab", { name: "Decor" }).click();
  await shot(page, "03-decor-menu", kind, { wait: 600 });
  await page.keyboard.press("Escape");
  await page.locator(".build-menu button[aria-label='Close build menu']").click().catch(() => undefined);
  await page.getByRole("button", { name: "Villagers" }).click();
  await shot(page, "04-villagers-panel", kind, { wait: 1200 });
  await page.keyboard.press("Escape");
  await enterAvatar(page);
  const v = await villageNow(page);
  await page.evaluate(([x, y]) => window.__hfGame.devWalkTo(x, y), [v.origin[0] + 24, v.origin[1] + 26]);
  await page.waitForTimeout(3500);
  await shot(page, "05-avatar-among-villagers", kind, { wait: 0 });
};

const browser = await playwright.chromium.launch();
for (const [kind, ctxOpts] of Object.entries(VIEWPORTS).filter(([k]) => !process.env.ONLY || process.env.ONLY === k)) {
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.error(`[${kind}] page error:`, e.message, process.env.STACK ? e.stack : ""));
  page.on("console", (m) => m.type() === "error" && console.error(`[${kind}] console:`, m.text()));
  try {
    await PHASES[phase](page, kind);
  } catch (e) {
    await page.screenshot({ path: join(OUT, `FAILED-${kind}.jpg`), type: "jpeg", quality: 80 });
    console.error(`[${kind}] flow failed:`, e.message);
    process.exitCode = 1;
  }
  await ctx.close();
}
await browser.close();
