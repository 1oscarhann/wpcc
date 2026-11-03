// Playwright screenshot runner: `node tools/screenshots.mjs <phase> [baseUrl]`
// Saves desktop (1440×900) and mobile (390×844) shots to docs/screenshots/phase-N/.
// Needs the API + Vite dev server running (see README).
import { mkdirSync } from "node:fs";
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

const browser = await playwright.chromium.launch();
for (const [kind, ctxOpts] of Object.entries(VIEWPORTS)) {
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.error(`[${kind}] page error:`, e.message));
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
