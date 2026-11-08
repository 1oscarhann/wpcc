// Phase 18 performance budgets for the shipped bundle (run after `vite build`; CI fails if any is over).
// Mobile on 4G is the target: first load under ~1 MB transferred, the main script under 350 KB gzipped.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const DIST = process.argv[2] ?? "frontend/dist";
const KB = 1024;
const BUDGETS = [
  { name: "main script (gzip)", limit: 350 * KB, measure: () => gz(largest(".js")) },
  { name: "all scripts (gzip)", limit: 520 * KB, measure: () => files(".js").reduce((a, f) => a + gz(f), 0) },
  { name: "world atlas (png)", limit: 700 * KB, measure: () => size(join(DIST, "assets/gen/world.png")) },
  { name: "characters + icons (png)", limit: 160 * KB, measure: () => size(join(DIST, "assets/gen/chars.png")) + size(join(DIST, "assets/gen/icons.png")) },
  { name: "first load (gzip js + png + fonts)", limit: 1300 * KB, measure: () => files(".js").reduce((a, f) => a + gz(f), 0) + walk(join(DIST, "assets/gen")).filter((f) => f.endsWith(".png")).reduce((a, f) => a + size(f), 0) + walk(join(DIST, "assets/fonts")).reduce((a, f) => a + size(f), 0) },
];

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) => (d.isDirectory() ? walk(join(dir, d.name)) : [join(dir, d.name)]));
}
function files(ext) {
  return readdirSync(join(DIST, "assets")).filter((f) => f.endsWith(ext)).map((f) => join(DIST, "assets", f));
}
function largest(ext) {
  return files(ext).sort((a, b) => size(b) - size(a))[0];
}
function size(f) {
  return statSync(f).size;
}
function gz(f) {
  return gzipSync(readFileSync(f), { level: 9 }).length;
}

let failed = false;
for (const b of BUDGETS) {
  const v = b.measure();
  const ok = v <= b.limit;
  failed ||= !ok;
  console.log(`${ok ? "ok  " : "OVER"} ${b.name.padEnd(36)} ${(v / KB).toFixed(0).padStart(5)} KB / ${(b.limit / KB).toFixed(0)} KB`);
}
process.exit(failed ? 1 : 0);
