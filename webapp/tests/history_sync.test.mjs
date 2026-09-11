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

const H = new Function(`${dayOf[0]}\n${m[1]}\nreturn {resyncWindow,daysToFetch,` +
  `fmtBytes,fmtProgress,syncFraction,parseBegin,` +
  `relabelActive,relabelFraction,fmtRelabel,fmtRelabelQueued};`)();

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

/* --- progress reporting, which is what makes a BLE sync bearable --- */

group("the hub's #BEGIN line carries the byte count", () => {
  assert.deepEqual(H.parseBegin("#BEGIN 2026-09-11 27140"),
    { day: "2026-09-11", total: 27140 });
  // an older hub sends the day alone: still a valid start, unknown size
  assert.deepEqual(H.parseBegin("#BEGIN 2026-09-11"),
    { day: "2026-09-11", total: null });
  assert.deepEqual(H.parseBegin("#BEGIN 2026-09-11 nonsense"),
    { day: "2026-09-11", total: null });
  // the error JSON the hub sends instead when the day is unknown
  assert.equal(H.parseBegin('{"err": "no such day"}'), null);
  assert.equal(H.parseBegin("#END"), null);
});

group("bytes are readable at every scale", () => {
  assert.equal(H.fmtBytes(0), "0 B");
  assert.equal(H.fmtBytes(512), "512 B");
  assert.equal(H.fmtBytes(2048), "2.0 KB");
  assert.equal(H.fmtBytes(3 * 1048576), "3.0 MB");
});

group("a transfer with a known size reports a percentage", () => {
  const p = { index: 1, count: 4, day: "2026-09-10", received: 5120, total: 10240 };
  assert.equal(H.fmtProgress(p), "day 2/4 · 2026-09-10 · 5.0 KB of 10.0 KB (50%)");
  assert.match(H.fmtProgress({ ...p, ble: true }), /· BLE ·/);
});

group("...and one without still shows movement", () => {
  const p = { index: 0, count: 1, day: "2026-09-11", received: 17612, total: null };
  assert.equal(H.fmtProgress(p), "day 1/1 · 2026-09-11 · 17.2 KB so far");
  assert.equal(H.fmtProgress({ index: 0, count: 1, day: "d", received: 0, total: null }),
    "day 1/1 · d · 0 B so far");
});

group("the bar crosses the whole sync once, not once per day", () => {
  const p = (index, received, total, count = 4) =>
    H.syncFraction({ index, count, received, total });
  assert.equal(p(0, 0, 1000), 0);
  assert.equal(p(0, 500, 1000), 0.125);   // half of the first of four
  assert.equal(p(1, 0, 1000), 0.25);
  assert.equal(p(3, 1000, 1000), 1);
  assert.equal(p(2, 999, null), 0.5);     // unknown size: hold at the day mark
  assert.ok(p(9, 5000, 1000, 4) <= 1);    // never past the end
});

/* --- the hub's clock relabel: a job the page watches, not a reply it waits for --- */

// what /api/storage (and the reply to /api/time) report, at each stage
const IDLE = { state: "idle", pct: 0, bytes_done: 0, bytes_total: 0, rows_done: 0,
  rows_total: null, kept: 0, elapsed_ms: 0, last: null };
const PLANNING = { ...IDLE, state: "planning", pct: 12, bytes_done: 190000, bytes_total: 389120 };
const MOVING = { ...IDLE, state: "moving", pct: 62, bytes_done: 194560, bytes_total: 389120,
  rows_done: 4000, rows_total: 8000 };
const WAITING = { ...MOVING, state: "waiting" };
const DEFERRED = { ...IDLE, state: "deferred", bytes_total: 389120 };
const DONE = { ...IDLE, last: { rows: 8000, kept: 0, torn: 0, span_s: 3 * DAY,
  elapsed_ms: 42100, work_ms: 30500, steps: 1700, rows_per_s: 262, at: NOW } };

group("a sync must wait while the hub is planning, moving, or paused mid-move", () => {
  assert.equal(H.relabelActive(PLANNING), true);
  assert.equal(H.relabelActive(MOVING), true);
  assert.equal(H.relabelActive(WAITING), true);   // storage went read-only: still owed
  assert.equal(H.relabelActive(IDLE), false);
  assert.equal(H.relabelActive(DEFERRED), false); // nothing claimed yet: days are intact
  assert.equal(H.relabelActive(DONE), false);
  assert.equal(H.relabelActive(null), false);     // an older hub sends nothing
  assert.equal(H.relabelActive(undefined), false);
});

group("the bar follows the hub's own percentage, plan pass then move", () => {
  assert.equal(H.relabelFraction(PLANNING), 0.12);
  assert.equal(H.relabelFraction(MOVING), 0.62);
  assert.equal(H.relabelFraction({ ...MOVING, pct: 250 }), 1);   // clamped
  // no pct: fall back to bytes; no bytes: nothing to show
  assert.equal(H.relabelFraction({ state: "moving", bytes_done: 100, bytes_total: 400 }), 0.25);
  assert.equal(H.relabelFraction({ state: "moving" }), 0);
  assert.equal(H.relabelFraction(null), 0);
});

group("the status line says what stage it is at, in bytes and rows", () => {
  assert.equal(H.fmtRelabel(PLANNING),
    "relabelling stored records: reading 185.5 KB of 380.0 KB to plan the move");
  assert.equal(H.fmtRelabel(MOVING),
    "relabelling stored records: 4000 of 8000 rows · 190.0 KB of 380.0 KB (62%)");
  // a job resumed after a power cut from a plan that never counted its rows
  assert.equal(H.fmtRelabel({ ...MOVING, rows_total: null }),
    "relabelling stored records: 4000 rows · 190.0 KB of 380.0 KB (62%)");
  assert.equal(H.fmtRelabel(WAITING),
    "relabel paused at 190.0 KB of 380.0 KB - the hub's storage is read-only");
  assert.equal(H.fmtRelabel(DEFERRED),
    "380.0 KB of pre-clock records wait for writable storage");
});

group("...and, done, what moved and how fast -- the number a bench run compares", () => {
  assert.equal(H.fmtRelabel(DONE), "relabelled 8000 stored records in 42.1 s (262 rows/s)");
  const l = DONE.last;
  assert.equal(H.fmtRelabel({ ...DONE, last: { ...l, kept: 12, torn: 1 } }),
    "relabelled 8000 stored records in 42.1 s (262 rows/s), 12 kept for a later sync, 1 torn rows dropped");
  // nothing was placed: only worth a line if something was kept back
  assert.equal(H.fmtRelabel({ ...DONE, last: { ...l, rows: 0, kept: 3 } }),
    "relabelled 0 stored records in 42.1 s (262 rows/s), 3 kept for a later sync");
  assert.equal(H.fmtRelabel({ ...DONE, last: { ...l, rows: 0 } }), "");
  assert.equal(H.fmtRelabel(IDLE), "");
  assert.equal(H.fmtRelabel(null), "");
});

group("the clock-sync line says what it queued, and nothing when there was nothing", () => {
  assert.equal(H.fmtRelabelQueued(PLANNING), ", 380.0 KB of stored records being relabelled");
  assert.equal(H.fmtRelabelQueued(DEFERRED), ", 380.0 KB of stored records wait for writable storage");
  assert.equal(H.fmtRelabelQueued(IDLE), "");
  assert.equal(H.fmtRelabelQueued(DONE), "");      // an old completion is not this sync's
  assert.equal(H.fmtRelabelQueued(undefined), ""); // an older hub: no field at all
});

group("the completed job widens the re-read window the way the old reply did", () => {
  // the hub says it placed rows reaching 3 days back: the same 4-day window
  // resyncWindow gave for relabelled_span_s in the synchronous reply
  assert.equal(H.resyncWindow(DONE.last.at, 0, DONE.last.span_s), 4);
  assert.equal(H.resyncWindow(NOW, 0, 0), 0);      // nothing moved: nothing to re-read
});

console.log(`\n${groups} test groups passed`);
