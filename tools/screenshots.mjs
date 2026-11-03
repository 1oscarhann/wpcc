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
  desktop: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 },
  mobile: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
};

async function shot(page, name, kind, opts = {}) {
  await page.waitForTimeout(opts.wait ?? 350);
  const file = join(OUT, `${name}-${kind}.png`);
  await page.screenshot({ path: file, fullPage: opts.fullPage ?? false });
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
    await shot(page, "05-play", kind, { wait: 800 });
    await page.getByText("Settings").click();
    await shot(page, "06-settings", kind);
    await page.goto(`${BASE}/debug`);
    await page.getByText("Debug gallery").waitFor();
    await shot(page, "07-debug-gallery", kind, { fullPage: true, wait: 1500 });
  },
  async 3(page, kind) {
    await signupFlow(page, kind);
    await page.locator("canvas").first().waitFor();
    await shot(page, "01-village", kind, { wait: 1500 });
    await page.getByRole("button", { name: /^Build/ }).click();
    await shot(page, "02-build-menu", kind, { wait: 500 });
    await page.getByRole("button", { name: /Lumber Camp/ }).click();
    const canvas = page.locator("canvas").first();
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width * 0.62, box.y + box.height * 0.42);
    await shot(page, "03-placing", kind, { wait: 500 });
    if (kind === "mobile") {
      await page.mouse.click(box.x + box.width * 0.62, box.y + box.height * 0.42);
      await page.getByRole("button", { name: "Place here" }).click();
    } else {
      await page.mouse.click(box.x + box.width * 0.62, box.y + box.height * 0.42);
    }
    await shot(page, "04-constructing", kind, { wait: 900 });
    await page.waitForTimeout(11000);
    await shot(page, "05-built", kind, { wait: 600 });
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5 - 20);
    await shot(page, "06-selected", kind, { wait: 600 });
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
    await page.screenshot({ path: join(OUT, `FAILED-${kind}.png`) });
    console.error(`[${kind}] flow failed:`, e.message);
    process.exitCode = 1;
  }
  await ctx.close();
}
await browser.close();
