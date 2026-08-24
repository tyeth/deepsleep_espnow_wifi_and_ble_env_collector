# ESP-NOW / WiFi / BLE Environmental Collector

A CircuitPython environmental monitoring system:

* **Collector hub** (`collector/`) — Feather ESP32-C6 (bench) / S3 / S2
  with a 3.52" quad-color eInk (black/white/yellow/red) on the eInk
  Feather Friend (#4446) and a local Sensirion SEN66. Receives remote
  nodes over ESP-NOW (WiFi POST fallback), logs to SD/flash, serves a
  WiFi portal + REST API and a BLE UART (web-BLE) interface. Runs its
  **own AP with a captive portal** (join `BASE{mac-hex}`, any page
  redirects to the dashboard) — home WiFi optional. Acts as the mesh's
  **time service** (browser/NTP-synced clock pushed to nodes).
* **Sensor nodes** (`node/`) — headless deep-sleeping Feathers carrying an
  SCD4x, SCD30, SEN5x, or SEN6x. **Fully self-configuring**: discover the
  collector by ESP-NOW broadcast (no MACs to type), first-boot config via
  their own `SENSOR{mac-hex}` portal AP, config pushed back on every
  check-in. Unsent readings are **stashed across deep sleeps** and
  retransmitted with original (retro-adjusted) timestamps.
* **Analyzer web app** (`webapp/`) — a static page hosted by the device
  *and* on GitHub Pages: Plotly charts, threshold/episode analysis,
  Pyodide change detection, and a voice-driven on-device AI assistant
  (Chrome built-in Prompt API). Offline after first load. See
  `webapp/README.md`.

**HIL bench alternative rig**: QT Py ESP32-S3 + EYESPI/eInk BFF + 2.9"
tri-color (PID 1028, 296x128) is supported via display profiles
(`display_profile: "auto"` picks it by board id; tri palette has no yellow,
so warn states render as red accent bars + `!` markers, and there is no SD
slot — RAM-only buffering).

> **CircuitPython:** use the **latest alpha** build (it contains required
> BLE fixes). <https://circuitpython.org/downloads>

## Hardware / pins (collector)

eInk Feather Friend #4446 on the shared SPI bus (`board.SPI()`):

| Signal   | Pin  |
|----------|------|
| SD CS    | D5   |
| SRAM CS  | D6 (unused, held deselected) |
| eInk CS  | D9   |
| eInk DC  | D10  |
| reset / busy | not wired |

3.52" quad-color eInk via FPC: **constructor MUST be 384x184** (the
driver's resolution whitelist) — the panel shows 384x180 of that buffer
(the layout clamps the 184-axis). Driver: `adafruit_jd79667.JD79667`,
`rotation=270`, `busy_pin=None` (timed refreshes). The profile passes
`refresh_time=20, seconds_per_frame=20` — a real quad refresh takes
~20 s, and EPaperDisplay's defaults (40/180 s) are needlessly
conservative for this panel. SEN66 on I2C/STEMMA QT.

## Install

Libraries are staged **into the repo** with circup's `--path` mode (no
CIRCUITPY drive needed — essential for the C6, which has no USB MSC). The
committed `boot_out.txt` in each device folder tells circup which
CircuitPython version to target (keep it in sync with the flashed CP):

```sh
# collector -> collector/lib/
circup --path collector install -r collector/requirements-circup.txt

# node -> node/lib/  (incl. SEN5x driver from the custom bundle)
circup bundle-add good-enough-technology/circuitpython_goodenough_bundle
circup --path node install -r node/requirements-circup.txt
circup --path node install sensirion_i2c_sen5x
```

Then deploy the folder's `*.py`, `config.json`/`node_config.json`,
`settings.toml` (from the example), and `lib/` to the board — via the
CIRCUITPY drive where one exists, or `tools/serial_deploy.py` / the web
workflow on the C6. `lib/` is git-ignored; re-run circup after cloning.

No MACs need copying anywhere: nodes discover the collector by ESP-NOW
broadcast and pin it (MAC + channel) in NVM. `collector_mac` in
`node_config.json` remains as an optional manual override.

## Self-configuration

* **Collector AP**: SSID defaults to `BASE{mac-hex}`; override via
  `settings.toml` (`ENVHUB_AP_SSID`/`ENVHUB_AP_PASSWORD`) or config.json.
* **Node identity**: name defaults to `sensor-{mac-hex}`.
* **Node first boot** (or BOOT button held at power-on): the node raises
  an open AP `SENSOR{mac-hex}` with a captive settings form (name,
  interval, metrics, LED); saving writes `node_config.json` — or
  `/saves/node_config.json` (CPSAVES) when USB MSC holds CIRCUITPY
  read-only — and reboots. Times out after `portal_timeout_s` (180 s) and
  continues, so a node never hangs unconfigured.
* **ESP-NOW discovery**: an unconfigured node broadcasts `dsc` across
  channels 1–13; the collector's unicast `cfg` reply teaches it the MAC +
  channel (persisted in NVM across power loss). If a pinned collector
  stops ACKing, the node forgets it and rediscovers.
* **Config push**: every check-in's `cfg` reply carries interval, enabled
  metrics, ASC-off policy, pending calibration, and the current epoch.

## Time service & clocks

* The hub's clock syncs from **NTP** (when home WiFi is up) or from a
  **browser**: the Analyzer auto-POSTs `/api/time` on connect and has a
  "Sync clock" button (BLE: `time <epoch>`).
* Every ESP-NOW/HTTP `cfg` reply carries the epoch when the hub is
  synced; nodes set their RTC from it (the ESP32 RTC keeps ticking
  through deep sleep).
* Data buffered under a wrong clock is **retro-adjusted on sync**: the
  collector shifts its pending (unwritten) records; nodes shift their
  stashed readings. Node data packets carry an `at` reading-timestamp;
  the collector ignores implausible ones (unsynced clocks) and uses
  receive time.

## Resilience (no data loss)

* **Collector**: every loop section is guarded — a malformed packet,
  sensor glitch, or portal error can't kill the loop; `MemoryError`
  recovers via gc; 20 consecutive loop errors → **flush all buffered
  data to storage, then a clean reset**. Critical host battery forces an
  immediate flush.
* **Nodes**: every wake path is guarded so **deep sleep always happens**
  (no crash-idles draining the battery). Failed sends stash the reading
  in `alarm.sleep_memory` (18-byte packed records; oldest dropped when
  full) and the backlog retransmits — original timestamps intact — once
  the collector is reachable.
* **Storage**: alert transitions force an immediate flush; flash-root
  storage keeps ≥`flash_min_free_kb` free by rotating oldest day files.

## Data flow & storage

* Local SEN66 sampled every `sample_interval_s` (15s) into a **preallocated
  struct-packed RAM ring** (no PSRAM needed, no flash writes) used for
  averaging and trend arrows.
* Averaged records queue in RAM and are **batched to SD** (append + sync,
  one open/close per flush) every `sd_flush_interval_s` (10 min) or
  `sd_flush_max_pending` lines — minimises SD writes.
* **Alert transitions flush immediately** and also append to
  `/sd/events.csv`, so out-of-spec history survives power pulls.
* Storage root falls back **`/sd` → `/saves` (CPSAVES) → `/`** (the flash
  root is writable to code on no-MSC boards like the C6). Layout under
  the root: `data/YYYY-MM-DD.csv` (all sources, one file/day),
  `events.csv` (state transitions with held-duration), `config.json`
  (runtime overrides). On flash the record cadence stretches
  ×`flash_record_multiplier` and ≥`flash_min_free_kb` stays free (oldest
  day rotated out). A tiny crossed-SD glyph shows on the eInk whenever
  storage is not the SD card.

## Display (default every ~3 min, configurable)

* Room values large; **yellow** highlight = warn, **red** = bad.
* Remote nodes in tiny text at the bottom; abnormal node lines highlighted
  and sorted to the top.
* Footer bar: how long each zone has been out of spec.
* **Battery warnings render as watermarks** (big pale text behind the data,
  plus a small `!BATT!` corner tag): host below `host_vcc_unplugged_v`
  (⇒ unplugged) or any node below `node_batt_warn_v`.
* **Refresh policy**: power-on paints a quick **"Loading Data — give it a
  minute…"** boot screen (non-blocking; boot continues while the panel
  flashes) so the user knows the hub is alive. The dashboard follows
  after the `boot_display_delay_s` (60 s) settle window with first data,
  then every `display_interval_s` (120 s). The panel minimum between
  refreshes is `display_min_refresh_s` (25 s — a quad refresh takes
  ~20 s); alerts pull the next refresh forward to that minimum; failures
  back off 30 s. Never re-init the display or soft-reload while a
  refresh is in flight (wedges the panel).

## Access

* **Captive AP**: the hub broadcasts `BASE{mac-hex}` (open by default; set
  `ap_password` ≥8 chars to secure, or `ENVHUB_AP_*` in settings.toml). A
  tiny DNS server answers every lookup with the hub's IP and the OS
  connectivity probes are redirected, so joining the AP pops the portal.
* **WiFi portal**: `http://<hub-ip>/` (AP side: `http://192.168.4.1/`) —
  serves the full Analyzer app when `webapp/` is deployed to `/sd/www/`
  (or flash `/www/`), else a minimal dashboard (always at `/mini`).
  API: `/api/latest`, `/api/battery`, `/api/events`,
  `/api/history?day=YYYY-MM-DD` (CSV), `/api/config` (GET/POST),
  `/api/calibrate` (POST), `/api/time` (POST, browser clock sync),
  `/api/ingest` (node fallback).
* **web-BLE**: advertises as `ENVHUB` (Nordic UART). Text commands:
  `latest`, `battery`, `events`, `config`, `days`, `hist <day>` (streams a
  day's CSV between `#BEGIN`/`#END`), `set <json>`, `cal <src> <1|2>`,
  `time <epoch>`. Works with Adafruit's web bluetooth terminal and the
  Analyzer app. (C6 caveat: BLE + softAP coexistence is under test — see
  `bugs_issues_and_todos.md`.)
* Last resort: unscrew and read the SD card — plain CSV; drag-drop the
  files straight into the Analyzer (or ask its built-in AI about them).

Future: optional upload of averaged subsets to online storage (Adafruit IO)
over an internet-connected link.

## Calibration policy

Every sensor has **automatic self-calibration forced OFF** (collector at
boot; nodes once, then re-asserted via config pushes). Forced CO2
recalibration is a deliberate two-step user action:

1. `POST /api/calibrate {"src": "kitchen", "step": 1}` (or BLE
   `cal kitchen 1`) — arms and returns the warning: *take the sensor
   outside / fresh air ~420ppm for 3+ minutes*.
2. Step 2 — local sensor recalibrates immediately; a remote node receives
   the target in its next config reply, measures outside for
   `cal_measure_s`, recalibrates, and reports the correction back.

## Node behaviour

Wake → (first power-on: config portal, see Self-configuration) → detect
sensor by I2C address (0x62 SCD4x / 0x61 SCD30 / 0x69 SEN5x / 0x6B SEN6x;
SEN5x prefers the `sensirion_i2c_sen5x` bundle lib, minimal built-in
fallback) → read with `pm_warmup_s` fan spin-up for PM sensors → ESP-NOW
unicast to the pinned collector (channel-hunting 1–13; broadcast
discovery when unpinned) → apply the cfg reply (interval / metrics / ASC
/ calibration / **epoch**) → retransmit any stashed backlog / stash this
reading on failure → deep sleep. Falls back to `POST /api/ingest` over
WiFi if configured. Every path ends in deep sleep.

## Repo layout

```
collector/   hub firmware (code.py + modules, config.json, lib/ via circup)
node/        node firmware (code.py, node_sensors.py, node_portal.py, ...)
webapp/      Analyzer web app (device-hosted + GitHub Pages)
examples/    kept references: deep_sleep.py, displayio_basics.py,
             eink_quad_demo.py, learn_quad_exact.py (panel sanity checks)
tools/       serial_deploy.py, serve_webapp.py, gen_sample_data.py
bugs_issues_and_todos.md   upstream-worthy findings + open TODOs
```

`envproto.py` (wire protocol) and `battery.py` are duplicated into both
device folders — keep the copies identical.

## Bring-up state (as of 2026-08-24 evening) — read this to resume

**WORKING**: the C6 collector boots and runs end-to-end: AP `BASE597BE4`
+ captive DNS + HTTP portal (192.168.4.1, no SD card → storage on flash
`/`), ESP-NOW, SEN66 + MAX17048, and the **dashboard rendering on the
quad panel** (~90 KB heap steady, ~66 KB after a screen build; first
refresh at the 60 s settle mark). The Feather S3 node (COM10/11) has the
stash/time firmware on its CIRCUITPY drive.

**Immediately blocked on**: the C6's USB wedged during the BLE
early-after-AP experiment — **press its reset button**, then deploy
`collector/code.py` (new BLE-then-AP early ordering) and run the verdict
boot. Full BLE test matrix in `bugs_issues_and_todos.md`.

Hard-won ESP32-C6 (CP 10.3.0-alpha.4) findings (details + upstream-issue
drafts in `bugs_issues_and_todos.md`):
* `wifi.radio.start_ap()` / BLE init **hard-fault the core unless done at
  the very top of code.py, before the heavy imports** ("EARLY RADIO
  BRING-UP" block). Late BLE alongside the AP hard-faults 2/2.
* The wifi stack **corrupts the shared SPI lock flag** (bus reads LOCKED,
  no owner) → every eInk refresh fails "Refresh too soon"; worked around
  by clearing the stale lock before each refresh. A failed `sdcardio`
  probe (no card) genuinely locks the bus too — unlocked in the handler.
* Never let e-paper show the console splash (supervisor auto-refresh
  starves user refreshes): a white group is assigned at display init.
* eInk: constructor must be **384x184** (driver whitelist; panel shows
  384x180). NEVER re-init the display / soft-reload while a refresh is in
  flight — wedges the panel until a clean power-on.
* mpremote: `fs cp` to a NEW file fails against CP 10.3-alpha (existing
  files OK — create once via exec, then mpremote); auto-reload is
  disabled in code.py so multi-file deploys don't half-restart.
* Device files: `/learn_demo.py` (exact learn example) + ruler bmp kept
  on the C6 for panel sanity checks.

## Earlier bring-up notes

* **Host**: Feather ESP32-C6 on **COM4** (USB VID:PID 303A:1001).
  **CircuitPython 10.3.0-alpha.4 flashed & hash-verified** via
  `esptool write_flash 0x0` (image confirmed: bootloader@0x0, partition
  table@0x8000, app@0x10000).
* **C6 gotchas learned the hard way**:
  * The C6 has **no USB mass storage** — no CIRCUITPY drive will ever
    appear. Deploy with `tools/serial_deploy.py` (raw-REPL file copy,
    *written but not yet tested*) or the web workflow
    (`CIRCUITPY_WEB_API_PASSWORD` in settings.toml).
  * esptool's "hard reset via RTS" does **nothing** over USB-Serial/JTAG
    and `--after watchdog-reset` is *unsupported on C6* (esptool 5.2.dev4)
    — after flashing, the chip sits in download mode (`wait usb download`)
    until the **physical reset button** is pressed.
  * The datastore falls back `/sd → /saves → /` — on the C6 the flash root
    is writable to code (no MSC), keeps ≥50KB free
    (`flash_min_free_kb`), rotates oldest day files, and stretches the
    record interval ×`flash_record_multiplier`. Display shows a tiny
    crossed-SD glyph whenever storage is not the SD card.
* **Collector MAC** (for every node's `node_config.json`):
  `40:4c:ca:59:7b:e4`.
* **HIL camera**: Android IP Webcam at `http://192.168.1.187:8080` — use
  **`/shot.jpg`** only (never `/photo*.jpg`). The phone answered ping but
  the server wasn't started last check — start it in the app first.
* **Next steps**: press reset on the C6 → REPL should appear on COM4 →
  test/fix `tools/serial_deploy.py` → deploy `collector/` *.py +
  config.json + settings.toml + libs (circup bundles to `/lib` over
  serial) → verify SEN66, then display profile on the QT Py tri-color
  bench rig, ESP-NOW channel discovery, captive portal with a phone, BLE
  from the Analyzer page.

## Bring-up test plan (hardware session)

1. Collector alone: eInk refresh (check 384x180-vs-380x180 offset and
   rotation), SEN66 readings, SD write, portal reachable.
2. Verify ESP-NOW: node with SCD4x, check channel discovery locks to the
   AP channel, cfg reply applies interval.
3. BLE from browser (latest alpha CP), battery watermark by unplugging.
4. Threshold trip (breathe on the SEN66) → yellow/red cell, event row,
   early refresh, out-of-spec duration in footer.
