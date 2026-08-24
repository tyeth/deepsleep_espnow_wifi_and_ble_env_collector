# ESP-NOW / WiFi / BLE Environmental Collector

A CircuitPython environmental monitoring system:

* **Collector hub** (`collector/`) — Feather ESP32-S3 (default; C6/S2 also
  supported, S2 has no BLE) with a 3.52" quad-color eInk (black/white/
  yellow/red) on the eInk Feather Friend (#4446) and a local Sensirion
  SEN66. Receives remote nodes over ESP-NOW (WiFi POST fallback), logs to
  SD, serves a WiFi portal + REST API and a BLE UART (web-BLE) interface.
  Also runs its **own AP with a captive portal** (join `ENVHUB`, any page
  redirects to the dashboard) — home WiFi optional.
* **Sensor nodes** (`node/`) — headless deep-sleeping Feathers carrying an
  SCD4x, SCD30, SEN5x, or SEN6x. Wake, read, report, apply config pushed
  back by the collector, deep sleep.
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

3.52" quad-color eInk via FPC: **constructor takes 384x180** (driver /
displayio quirk) though the panel is physically 380x180. Driver:
`adafruit_jd79667.JD79667`, `rotation=270`, `busy_pin=None` (timed
refreshes). SEN66 on I2C/STEMMA QT.

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

The collector prints its MAC on the console at boot (and on the eInk footer
until a node is heard) — put it in each node's `node_config.json`.

## Data flow & storage

* Local SEN66 sampled every `sample_interval_s` (15s) into a **preallocated
  struct-packed RAM ring** (no PSRAM needed, no flash writes) used for
  averaging and trend arrows.
* Averaged records queue in RAM and are **batched to SD** (append + sync,
  one open/close per flush) every `sd_flush_interval_s` (10 min) or
  `sd_flush_max_pending` lines — minimises SD writes.
* **Alert transitions flush immediately** and also append to
  `/sd/events.csv`, so out-of-spec history survives power pulls.
* SD layout: `/sd/data/YYYY-MM-DD.csv` (all sources, one file/day),
  `/sd/events.csv` (state transitions with held-duration), `/sd/config.json`
  (runtime config overrides — CIRCUITPY flash is never written).

## Display (every 2 min, configurable)

* Room values large; **yellow** highlight = warn, **red** = bad.
* Remote nodes in tiny text at the bottom; abnormal node lines highlighted
  and sorted to the top.
* Footer bar: how long each zone has been out of spec.
* **Battery warnings render as watermarks** (big pale text behind the data,
  plus a small `!BATT!` corner tag): host below `host_vcc_unplugged_v`
  (4.35 V ⇒ unplugged) or any node below `node_batt_warn_v`.
* An alert transition forces an early refresh (min 30s apart; quad-color
  refreshes take ~20s).

## Access

* **Captive AP**: the hub broadcasts `ENVHUB` (open by default; set
  `ap_password` ≥8 chars in config to secure). A tiny DNS server answers
  every lookup with the hub's IP and the OS connectivity probes are
  redirected, so joining the AP pops the portal automatically.
* **WiFi portal**: `http://<hub-ip>/` — serves the full Analyzer app when
  `webapp/` is deployed to `/sd/www/` (or flash `/www/`), else a minimal
  dashboard (always at `/mini`).
  API: `/api/latest`, `/api/battery`, `/api/events`,
  `/api/history?day=YYYY-MM-DD` (CSV), `/api/config` (GET/POST),
  `/api/calibrate` (POST), `/api/ingest` (node fallback).
* **web-BLE**: advertises as `ENVHUB` (Nordic UART). Text commands:
  `latest`, `battery`, `events`, `config`, `days`, `hist <day>` (streams a
  day's CSV between `#BEGIN`/`#END`), `set <json>`, `cal <src> <1|2>`.
  Works with Adafruit's web bluetooth terminal and the Analyzer app.
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

Wake → detect sensor by I2C address (0x62 SCD4x / 0x61 SCD30 / 0x69 SEN5x /
0x6B SEN6x; SEN5x uses a minimal built-in driver) → read (PM sensors get
`pm_warmup_s` fan spin-up) → ESP-NOW unicast to the collector, hunting WiFi
channels 1–13 until the collector ACKs (channel cached in sleep memory) →
listen ~0.5s for the config reply (interval / metrics / ASC / calibration)
→ deep sleep. Falls back to `POST /api/ingest` over WiFi if configured.

## Repo layout

```
collector/   hub firmware (code.py + modules, config.json, requirements)
node/        node firmware (code.py, node_sensors.py, node_config.json)
examples/    kept references: deep_sleep.py, displayio_basics.py
```

`envproto.py` (wire protocol) and `battery.py` are duplicated into both
device folders — keep the copies identical.

## Bring-up state (as of 2026-08-24) — read this to resume

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
