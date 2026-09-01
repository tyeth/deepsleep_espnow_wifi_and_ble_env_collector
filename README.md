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

## Web app assets on the hub (offline, no internet on the AP)

The analyzer is served by the hub from `/sd/www` (preferred) or `/www` on
flash, per file: an SD card copy of any file overrides the flash copy, so big
or frequently updated pieces go on the card. Vendor bundles are loaded from
`vendor/` first and only fall back to the CDN when that fails:

| File | Where | Notes |
|---|---|---|
| `www/vendor/plotly.min.js` | flash (1.1 MB, plotly-**basic**) or SD | charts are line traces; the basic dist suffices |
| `www/vendor/pyodide/pyodide.js` + the rest of the Pyodide `full/` tree | SD only (tens of MB) | change detection / future offline Python |
| `certs/fullchain.pem`, `certs/key.pem` | SD (`/sd/certs`) first, then flash `/certs` | HTTPS certificate for `192dot168dot4dot1.gundryconsultancy.com`; renewable via the page's *sync cert* / *upload* or auto when online |

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
* **web-BLE**: advertises as `ENVHUB-xxxx` (xxxx = last two MAC bytes, so
  several hubs on one site stay distinct; override via `ENVHUB_BLE_NAME` in
  `settings.toml` or `ble_name` in config.json) with the Nordic UART
  service. Text commands:
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
boot; nodes once, then re-asserted in every config push). That makes the
user-run **reference calibration the sensor's only correction**, so it is
a deliberate, scheduled, stability-gated two-step action (shared logic in
`calref.py`, identical in `collector/` and `node/`):

1. **Step 1 — arm & guidance.** `POST /api/calibrate {"src":"kitchen",
   "step":1}` / BLE `cal kitchen 1` / the web app's *Step 1* button. Returns
   the setup, power and timing guide: sensor OUTSIDE (shaded, sheltered) or
   at a wide-open window, away from people/vents/plants/traffic; **power**
   — the sensor stays awake for the whole window, so a node needs USB or a
   charged battery (≥ `cal_min_batt_v` 3.7 V) and the hub must stay on;
   **timing** — urban outdoor CO2 is nearest the ~420 ppm background at
   **04:00–05:00 local**, so step 2 defaults to the next 04:00.
2. **Step 2 — schedule the window.** `{"src":"kitchen","step":2,
   "when":"4am"|"now"|<epoch>,"duration_s":3600,"target_ppm":420,
   "dry":false}` / BLE `cal kitchen 2 [4am|now|<epoch>] [dur_s] [dry]`.
   Default = next 04:00 local for `cal_window_s` (60 min); `now` = a
   `cal_now_window_s` (3 min) window for when you are genuinely outdoors.
   `dry` runs the window and the stability check but never writes the
   calibration (a rehearsal). Scheduling needs a synced hub clock.
   * **Hub SEN66**: the main loop collects CO2 samples through the window
     (status line shows `CAL:wait`/`CAL:run`).
   * **Node**: the plan travels in the next cfg reply (`cal`/`cat`/`cdur`/
     `cdry`), is held in sleep memory, the node sleeps straight to the
     window, stays awake sampling every 10 s, refuses on a low battery.
   * **Alternative `"mode":"asc"`** (BLE `... asc`, webapp *overnight ASC*):
     instead of a forced value, the sensor's own automatic self-calibration
     is switched **on** for `cal_asc_window_s` (default **48 h** — SCD4x
     needs ~44 h of continuous operation for its first adjustment, SCD30
     about a week) and **off** again afterwards, so the no-ASC policy still
     holds. **Warning (also returned by step 1)**: ASC assumes the *lowest*
     CO2 seen in the period is fresh air, so the room must be ventilated —
     window wide open at least overnight (6–8 h) *every* night of the
     window — or the sensor calibrates itself wrong. Nodes stay awake the
     whole time (light-sleeping between 10 s reads): **USB power only**.
     The before → after readings (`ref_start` → `ref`, `shift`) are
     reported; logged as `cal_asc`.
3. **Gate, then FRC.** `calref.evaluate()` takes the median of the last
   15 min as the observed reference and requires spread ≤
   `cal_max_spread_ppm` (60), reference ≤ target+250 ("not fresh air")
   and ≥ target−200. Only then is the forced recalibration written. The
   result (`ok`, `ref` observed ppm, `corr`, `why`) is logged to the events
   CSV as `cal_ok` / `cal_dry` / `cal_fail`, shown in `GET /api/calibrate`
   / BLE `cal`, and in the web app's calibration status.

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

A reading counts as **delivered only when the hub confirms it** — the hub
echoes the packet's message id and the CRC-16 of the bytes it received,
after storing it. The ESP-NOW MAC-layer ACK alone proves nothing about the
hub having the data, so an unconfirmed reading is retried, then sent over
the WiFi fallback, then stashed. (`require_confirmation: false` reverts to
the old MAC-ACK behaviour for a hub that can receive but not transmit.)

**Three ways to configure a node**, all of them optional extras on top of
the self-configuring default:

* **ESP-NOW** — the hub's cfg push on every check-in (interval, metrics,
  ASC policy, calibration window, epoch). This is the normal path.
* **BLE** — `"ble_config_s": <seconds>` serves the same Nordic-UART portal
  the hub does, advertising as `SENSOR-xxxxxx`, for that long after each
  wake (bench mode holds it open for the whole wait). A phone gets
  `latest`, `config`, `set <json>` and `time <epoch>`; anything the node
  does not implement is answered with the list of what it does. Off by
  default: the window is awake time a battery node pays for.
* **Web API** — the hub's `/api/config`, which reaches the node in the next
  ESP-NOW cfg push.

plus the first-boot WiFi portal (`node_portal.py`) for naming a brand-new
node. BLE and the WiFi portal both persist through `node_store.py`, which
copes with USB mass storage holding CIRCUITPY read-only.

## CircuitPython gotchas (learned the hard way on this project)

Behaviours that cost real bench time. Firmware-level suspicions and the
upstream-worthy ones live in `bugs_issues_and_todos.md`; these are the
practical ones you need before touching the boards.

**Radios**

* **Importing `adafruit_ble` starts the BLE controller.** On an ESP32 with
  the wifi stack already up there may not be a large enough contiguous
  *internal* block left, and the import fails with
  `espidf.IDFError: Invalid state` (IDF log: `BLE_INIT: controller init
  failed`, e.g. `idf_free=5892 largest=3584`). Free the radio *before* the
  import — `wifi.radio.enabled = False` — and turn it back on afterwards.
* **On the C6, order is everything at boot**: BLE first, then ESP-NOW, then
  the softAP. Creating `espnow.ESPNow()` while a user softAP is up kills the
  AP; `wifi.radio.start_ap()` after heavy imports hard-faults rather than
  raising `MemoryError`. A resident BLE stack also starves the ESP-NOW
  *transmit* path (`0x3067 ESP_ERR_ESPNOW_NO_MEM`) — receive is unaffected.
* **ESP-NOW error codes worth knowing**: `0x3067` = out of internal memory
  (the coexistence problem above); `0x306d` = *peer channel is not equal to
  the home channel* (ordinary channel hunting, not a fault).
* **`ESPNow.send()`'s ACK counters are asynchronous.** Reading
  `send_success` / `send_failure` immediately after `send()` reads the state
  from *before* the callback fired, so every send looks failed. Poll them
  for a few ms instead.
* **The MAC-layer ACK is not delivery** — see the confirmation scheme in
  *Node behaviour*.
* **`_bleio`'s outgoing notification queue is ~5 packets deep and drops
  silently** on the C6: long replies truncate at exactly 100 bytes unless
  you pace them (`net_ble.py` sends 20 B every 50 ms). `PacketBuffer.write`
  gives real flow control but blocks forever if the client disconnects, so
  it is opt-in (`ble_tx_pktbuf`).

**Storage and state**

* **`alarm.sleep_memory` survives deep sleep but NOT `supervisor.reload()`.**
  A bench-mode node (deep sleep disabled) came up `boot# 1 stash: 0` every
  cycle until it mirrored the state through `microcontroller.nvm`.
* **`open(path, "w").write(...)` without closing does not flush.** Reading
  the file back in the same breath gets you a truncated file (`ValueError:
  syntax error in JSON`). Use `with`, or call `close()`.
* **CIRCUITPY is read-only to the board while USB mass storage holds it**
  (S2/S3). Write to `/saves` (CPSAVES) instead, or call
  `storage.unsafe_disable_usb_drive()` and remount — `node_store.py` walks
  all three.
* **Flashing a full `firmware.bin` WIPES CIRCUITPY.** Have the deploy ready
  before you flash: code, modules, `lib/`, `certs/`, `www/`.
* **`.mpy` beats `.py` for RAM**, materially on the C6 — cross-compile with
  a matching `mpy-cross` (`mpy-cross -o x.mpy x.py`).

**Talking to a board**

* **The USB console only writes while a host holds DTR asserted.** Open the
  port with `dtr=True`; a capture that attaches late (or a tool that opens
  and closes) loses everything the board printed in between.
* **Never toggle RTS on the C6's USB-Serial/JTAG** — it resets the chip
  (`rst:0x15`). Opening a devkit's *UART bridge* port resets the board too
  (the auto-reset circuit), which also makes the native USB port
  re-enumerate and kills any capture on it.
* **A devkit's two ports carry different things**: CircuitPython's console
  and REPL on the chip's native USB, ESP-ROM + IDF debug logs on the UART
  bridge. A hard fault or a `BLE_INIT` failure shows up only on the latter.
* **Entering the REPL disables auto-reload**, so a board parked at the
  "Press any key" prompt ignores file changes until it is reset.
* **`supervisor.get_previous_traceback()`** recovers the crash you missed
  because nothing was attached to the console. Invaluable.
* **`mpremote fs cp` is broken for new files** on the 10.3 alphas, and
  `fs ls` trips over `ilistdir`. `tools/serial_deploy.py` (raw REPL,
  base64, 3 KB per round trip) is the reliable path, and
  `tools/hil_bench.py` drives the two-board rig.
* **esptool cannot reset a C6 out of the download stub** (`--after
  watchdog-reset` is unsupported, RTS is a no-op on USB-JTAG): press the
  button, or inject `microcontroller.reset()` at the REPL. A wedged S3
  needs a 1200 bps touch to reach the ROM bootloader.

**Sensors**

* **Sensirion sensors refuse configuration while measuring**: SEN66 answers
  `Cannot set CO2 ASC while measuring`. Stop, set, restart — and check the
  result, because a driver that swallows the error will happily report a
  calibration it never performed.

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

**WORKING (2026-08-24 evening, Pi HIL bench)**: full ESP-NOW pipeline
verified end-to-end — node broadcast discovery + NVM pin, data with live
eInk alerts, hub-time push (stash timestamps retro-adjusted), config
push, and a 36-reading stash retransmitted after an outage. BLE UART
portal verified end-to-end from BlueZ/bleak (full command matrix, with
TX pacing + client retries around core notify drops). SEN66 + MAX17048 +
quad dashboard all live (~70 KB heap steady in either mode).

**C6 mode pick (memory ceiling, see bugs 5/7/10)**: the collector runs
EITHER as the node mesh hub (`ble_enabled=false`, default — ESP-NOW two-
way + display) OR as a BLE-access hub (`ble_enabled=true` — espnow
receive-only: TX dies 0x3067 NO_MEM with BLE resident). The softAP is
parked outright (item 0). PSRAM boards should manage everything at once.

Node bench mode: `"deep_sleep": false` in `node_config.json` keeps USB
alive between reports (supervisor reload instead of deep sleep;
sleep_memory still carries the stash/seq/channel).

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
