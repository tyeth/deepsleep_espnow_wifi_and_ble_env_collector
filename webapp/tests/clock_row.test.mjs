// Tests the clock row in index.html: what it says about where the hub's time
// comes from, and when it offers to save an auto-detected RTC by name.
// Run: node webapp/tests/clock_row.test.mjs
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const m = html.match(/\/\* --- where the hub's clock comes from[\s\S]*?\*\/\s*\n([\s\S]*?)\/\* --- the hub's clock relabel, watched --- \*\//);
assert.ok(m, "clock row block not found in index.html (markers moved?)");

// just enough DOM for clockShow: three elements and the page's setStatus
function page() {
  const el = () => ({ hidden: true, textContent: "", title: "", dataset: {}, err: false });
  const els = { "clock-row": el(), "clock-note": el(), "btn-rtc-pin": el() };
  const $ = (id) => els[id];
  const setStatus = (id, msg, busy = false, err = false) => {
    els[id].textContent = msg; els[id].err = !!err;
  };
  const H = new Function("$", "setStatus", `${m[1]}\nreturn {clockShow};`)($, setStatus);
  return { els, show: (latest) => { H.clockShow(latest); return els; } };
}

let groups = 0;
const group = (name, fn) => { fn(); groups++; console.log("ok -", name); };
const NOW = 1790000000;

group("an older hub that sends no clock: the row stays hidden", () => {
  const e = page().show({ ts: NOW, sources: {} });
  assert.equal(e["clock-row"].hidden, true);
});

// the hub names chips in lower case (extrtc.CHIPS); the page shows them in
// upper case and saves exactly what the hub said
group("auto-detected chip: say so and offer to save it by name", () => {
  const e = page().show({ clock: { synced: true, now: NOW, rtc: "pcf85063a",
    addr: 0x51, rtc_now: NOW + 2, drift_s: 2, rtc_config: "auto" } });
  assert.equal(e["clock-row"].hidden, false);
  assert.match(e["clock-note"].textContent, /PCF85063A at 0x51 \(auto-detected\), \+2s/);
  assert.equal(e["clock-note"].err, false);
  assert.equal(e["btn-rtc-pin"].hidden, false);
  assert.equal(e["btn-rtc-pin"].dataset.rtc, "pcf85063a");
  assert.equal(e["btn-rtc-pin"].textContent, "Save RTC as PCF85063A");
});

group("a config without the key, or true, means auto too", () => {
  for (const rtc_config of [undefined, null, true, "AUTO"]) {
    const e = page().show({ clock: { synced: true, rtc: "ds3231", addr: 0x68, rtc_config } });
    assert.equal(e["btn-rtc-pin"].dataset.rtc, "ds3231", String(rtc_config));
  }
});

group("chip already named in config: nothing to offer", () => {
  const e = page().show({ clock: { synced: true, rtc: "pcf8563", addr: 0x51,
    rtc_config: "pcf8563", drift_s: -1 } });
  assert.match(e["clock-note"].textContent, /\(from config\), -1s/);
  assert.equal(e["btn-rtc-pin"].hidden, true);
});

group("named chip that did not answer: an error, and the way back to auto", () => {
  const e = page().show({ clock: { synced: true, rtc: null, rtc_config: "ds3231" } });
  assert.match(e["clock-note"].textContent, /names RTC "ds3231" but it did not answer/);
  assert.equal(e["clock-note"].err, true);
  assert.equal(e["btn-rtc-pin"].dataset.rtc, "auto");
  assert.equal(e["btn-rtc-pin"].textContent, "Detect RTC at boot");
});

group("switched off, or none found: no button", () => {
  for (const rtc_config of ["off", false, "none"]) {
    const e = page().show({ clock: { synced: true, rtc: null, rtc_config } });
    assert.match(e["clock-note"].textContent, /off in config/, String(rtc_config));
    assert.equal(e["btn-rtc-pin"].hidden, true);
  }
  const e = page().show({ clock: { synced: true, rtc: null, rtc_config: "auto" } });
  assert.match(e["clock-note"].textContent, /no RTC found at the last boot/);
  assert.equal(e["btn-rtc-pin"].hidden, true);
});

group("a chip that lost power, and a hub with no time, are both called out", () => {
  const e = page().show({ clock: { synced: false, rtc: "pcf85063a", addr: 0x51,
    lost_power: true, rtc_config: "auto" } });
  assert.match(e["clock-note"].textContent, /lost power - the next clock sync sets it; hub clock NOT set/);
  assert.equal(e["clock-note"].err, true);
  // still worth pinning: which chip it is does not depend on its battery
  assert.equal(e["btn-rtc-pin"].dataset.rtc, "pcf85063a");
});

console.log(`\n${groups} test groups passed`);
