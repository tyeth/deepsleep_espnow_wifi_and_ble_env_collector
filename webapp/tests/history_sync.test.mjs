// Tests the history-sync helpers in index.html: how far back a sync re-reads
// days it already holds, once the hub's clock has been corrected. A cached day
// that the hub later relabelled (it was logging from its boot clock, or its
// clock had drifted) must be fetched again, or the browser keeps a copy of a
// day whose contents have moved.
// Run: node webapp/tests/history_sync.test.mjs
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const m = html.match(/\/\* --- history sync helpers:[\s\S]*?\*\/\s*\n([\s\S]*?)\/\* --- end history sync helpers --- \*\//);
assert.ok(m, "history sync helper block not found in index.html (markers moved?)");
// the real dayOf from the page, so the day maths under test is the page's
const dayOf = html.match(/^function dayOf\(.*$/m);
assert.ok(dayOf, "dayOf not found in index.html");

const H = new Function(`${dayOf[0]}\n${m[1]}\nreturn {resyncWindow,daysToFetch};`)();

const DAY = 86400;
const NOW = Date.parse("2026-09-11T12:00:00Z") / 1000;
const BOOT = 946684800;

let groups = 0;
const group = (name, fn) => { fn(); groups++; console.log("ok -", name); };

group("a hub whose clock was already right needs no re-read", () => {
  assert.equal(H.resyncWindow(NOW, 0), 0);
  assert.equal(H.resyncWindow(NOW, 12), 0);      // seconds of drift: ignore
  assert.equal(H.resyncWindow(NOW, -30), 0);
});

group("drift on a plausible clock is measured in days, plus one for timezone", () => {
  // 10 minutes out is still a part-day, so: that day, plus the timezone one
  assert.equal(H.resyncWindow(NOW, 600), 2);
  assert.equal(H.resyncWindow(NOW, 2 * DAY), 3);     // 2 days out -> 3 back
  assert.equal(H.resyncWindow(NOW, -2 * DAY), 3);    // ...either direction
  assert.equal(H.resyncWindow(NOW, 2 * DAY + 60), 4);
});

group("a hub that never had a clock re-reads the span it ran without one", () => {
  // delta is huge (2000 -> now); what matters is how long it ran: the
  // records it relabels are spread across exactly that span
  const ran = 3 * DAY;
  const hubNow = NOW;                 // after the sync the hub is on our clock
  const delta = NOW - (BOOT + ran);   // what it reported it had to move
  assert.equal(H.resyncWindow(hubNow, delta), 4);
  assert.equal(H.resyncWindow(NOW, NOW - BOOT), 0);  // booted seconds ago
});

group("the hub's own account of how far back rows moved widens the window", () => {
  // booted 10 min ago with no clock, but the sync also placed three
  // earlier unsynced boots' rows, reaching back 5 days
  const delta = NOW - (BOOT + 600);
  assert.equal(H.resyncWindow(NOW, delta), 2);            // by drift alone: today-ish
  assert.equal(H.resyncWindow(NOW, delta, 5 * DAY), 6);   // 5 days back, plus one
  assert.equal(H.resyncWindow(NOW, 0, 3 * DAY), 4);       // NTP boot: no drift at all
  assert.equal(H.resyncWindow(NOW, 2 * DAY, 60), 3);      // never narrows the drift
});

group("the window is capped so a nonsense clock is not a full re-download", () => {
  assert.equal(H.resyncWindow(NOW, 400 * DAY), 30);
  assert.equal(H.resyncWindow(NOW, -400 * DAY), 30);
});

group("with no correction, only today is re-fetched", () => {
  const days = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"];
  const have = new Set(days);
  assert.deepEqual(H.daysToFetch(days, have, NOW, 0), ["2026-09-11"]);
});

group("days we do not hold are always fetched", () => {
  const days = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"];
  const have = new Set(["2026-09-09"]);
  assert.deepEqual(H.daysToFetch(days, have, NOW, 0),
    ["2026-09-08", "2026-09-10", "2026-09-11"]);
});

group("a corrected clock re-reads that many days back", () => {
  const days = ["2026-09-06", "2026-09-07", "2026-09-08", "2026-09-09",
                "2026-09-10", "2026-09-11"];
  const have = new Set(days);
  assert.deepEqual(H.daysToFetch(days, have, NOW, 3),
    ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]);
});

group("the hub's newest day is re-read even when it is not our today", () => {
  // hub clock still hours behind ours, or its timezone rolls over later
  const days = ["2026-09-08", "2026-09-09", "2026-09-10"];
  const have = new Set(days);
  assert.deepEqual(H.daysToFetch(days, have, NOW, 0), ["2026-09-10"]);
});

group("an empty history asks for nothing", () => {
  assert.deepEqual(H.daysToFetch([], new Set(), NOW, 5), []);
});

console.log(`\n${groups} test groups passed`);
