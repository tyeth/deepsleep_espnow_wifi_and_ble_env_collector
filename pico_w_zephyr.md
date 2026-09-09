# Raspberry Pi Pico W / Pico 2 W (CircuitPython Zephyr port)

What this repo does and does not do on the two Pico W boards, with the
numbers behind each claim. Firmware: `tyeth/circuitpython`
`ci/pico2w-ble-assets` @ `94bfd47b5f`, prerelease
[`zephyr-cp-ble-ci-20260909`](https://github.com/tyeth/circuitpython/releases/tag/zephyr-cp-ble-ci-20260909)
(UF2 + unstripped ELF for both boards; umbrella tyeth/circuitpython#15,
why the reviewable PRs cannot link in CI: tyeth/circuitpython#16).

**Nothing in this document was run on hardware.** Everything below comes
from the firmware build (`.elf`, `.config`, generated board info), from
compiling every source with the matching `mpy-cross`, from executing the
pure-logic modules and the two entry points on the unix CircuitPython
build with stubbed radios, and from measuring import costs there. The
bench plan at the end is what turns "should" into "does".

## The short version

| | Pico W (RP2040) | Pico 2 W (RP2350) |
|---|---|---|
| role | **node** (`node_lite`) | **hub** (`hub_main`), or a node |
| heap after the firmware's static RAM | **42,292 B** (264 KB − 228,044) | **303,336 B** (520 KB − 229,144) |
| node → hub transport | BLE advertisement broadcast | receives BLE advertisements; WiFi `POST /api/ingest` |
| phone / browser access | none (no RAM for the BLE UART portal, no softAP) | BLE UART (web-BLE) + HTTP portal **on your home WiFi** |
| deep sleep | no — awake loop | no — the hub never slept anyway |
| ESP-NOW | no (module absent) | no |
| eInk / SD card | no (no user SPI bus) | no (same) |
| storage | CIRCUITPY flash, ~508 KB | CIRCUITPY flash, ~2.5 MB |

The repo's name promises deep sleep and ESP-NOW. On these boards it delivers
neither, and the code now says so at boot instead of dying at `import`.

## What the firmware actually provides

From the generated board info (identical for both boards) and the port
sources, checked at `94bfd47b5f`:

| module | state | consequence |
|---|---|---|
| `espnow` | **absent** (not in the table at all) | no mesh; `net_espnow` is not loaded (`caps.HAS_ESPNOW`) |
| `alarm` | false | no deep sleep, no `sleep_memory`; the node is an awake loop |
| `rtc` | false | **`time.time()` and `time.localtime()` raise** `RuntimeError: RTC is not supported on this board` — the weak `rtc_get_time_source_time()` is what the ELF links (`nm` shows it as `W`). `time.localtime(secs)` and `time.mktime()` still work. `caps.now()` keeps an offset against `time.monotonic_ns()` |
| `analogio`, `pwmio`, `neopixel_write`, `watchdog` | false | battery ADC path degrades (guarded); LED blink is a no-op |
| `wifi` | true, **station only** | `wifi.radio.start_ap()` is an **empty stub**: it returns without starting anything and `ap_active` stays False (`common-hal/wifi/Radio.c`, body commented out). No softAP, no captive portal, no `SENSOR{mac}` setup AP. The hub now checks `ap_active` after the call instead of trusting it |
| `busio` | true, **devicetree buses only** | `busio.SPI(clk, mosi, miso)` / `busio.I2C(scl, sda)` raise `NotImplementedError("Use device tree to define ...")`. `board.SPI` is the CYW43439 radio's own PIO bus (`pio0_spi0`) — never put a display or SD card on it. `board.I2C0` (SDA **GP4**, SCL **GP5**) and `board.I2C1` (SDA **GP6**, SCL **GP7**) are the sensor buses. Hardware SPI0 (GP16–19) exists but is not enabled in the board's devicetree; enabling it is a firmware overlay change, not a Python one |
| `_bleio` | true | legacy advertising only (`CONFIG_BT_EXT_ADV=n`, controller has no extended advertising); one connection (`CONFIG_BT_MAX_CONN=1`); `start_advertising(timeout=…)` and `anonymous=True` raise NotImplementedError — `adafruit_ble` passes neither by default |
| `socketpool`, `ssl` | true | server sockets, TLS server side (`load_cert_chain`) present. **`CONFIG_NET_MAX_CONTEXTS=6`**: six sockets in total, counting the listener and any UDP socket — `net_wifi` caps client connections at `caps.MAX_SOCKETS - 2 = 4` here |
| `storage`, `supervisor` | true | `disable_usb_drive`, `unsafe_disable_usb_drive`, `remount`, `runtime.ble_workflow`, `runtime.usb_connected` all present (checked in the ELF) — `boot.py` and the filesystem handover work as on the S3 |
| `nvm` | true, 4 KB | |
| `os.getenv` / `settings.toml` | present | `CIRCUITPY_WIFI_SSID` auto-connect works |
| `displayio`, `epaperdisplay`, `fourwire`, `sdcardio` | true | but useless without a user SPI bus (above) |

Every import in both trees, classified against that table, by
`tools/board_budget.py` (CPython `ast`, no hardware):

```
$ MPY_CROSS=.../mpy-cross python tools/board_budget.py collector/hub_main.py node/node_lite.py node/node_full.py
collector/hub_main.py   HARD: none.  soft: analogio (battery, guarded), espidf (net_wifi, guarded),
                        espnow (hub_main guarded / net_espnow conditional), rtc (caps.set_epoch, deferred)
node/node_lite.py       HARD: none.  soft: analogio (guarded), rtc (deferred)
node/node_full.py       HARD: alarm (node_full:26), espnow (node_full:29), rtc (node_full:39)
                        -> this is the ESP32 node; node/code.py never loads it on a board without espnow+alarm
```

## RAM, measured rather than assumed

Free RAM after the firmware's static allocation, from the build's `.elf`
(bss 220,701 B + data + noinit; the CI runs report the same 229,144 /
228,044 B "used"):

| | total | firmware static | left for CircuitPython |
|---|---|---|---|
| Pico W | 264 KB = 270,336 B | 228,044 B (84.4%) | **42,292 B** |
| Pico 2 W | 520 KB = 532,480 B | 229,144 B (43.0%) | **303,336 B** |

That 42 KB is the *outer* heap (zephyr-cp builds a TLSF heap over what the
linker left; the Python heap grows into it with `MICROPY_GC_SPLIT_HEAP_AUTO`).
The supervisor's own allocations — USB CDC buffers, the BLE workflow's
packet buffers, filesystem work areas — come out of the same pool, so
`gc.mem_free()` at a bare REPL will read *less* than 42 KB. **Step 0 of the
bench plan is to read that number**; every estimate below is against the
42 KB ceiling and gets worse by whatever the supervisor takes.

Import cost of the pure-Python modules, measured on the 64-bit unix
CircuitPython build (`gc.mem_free()` delta after `import` + `gc.collect()`)
and scaled to 32 bits. Calibration: across this project's modules the
64-bit cost is 1.4–2.6× (median ~2.0×) the module's `.mpy` size, so a
32-bit target holds ~1.2× the `.mpy` size; that is the factor
`tools/board_budget.py` uses.

| module / chain | `.mpy` | 64-bit measured | 32-bit estimate |
|---|---|---|---|
| `adafruit_ble` + `advertising.standard` + `services.nordic` (what `net_ble` needs) | 17.8 KB | **50.8 KB** | **~30 KB** |
| `net_ble` (incl. the above) | 4.1 KB | 53.9 KB | ~32 KB |
| `adafruit_requests` + `adafruit_connection_manager` | 10.6 KB | 19.5 KB | ~12 KB |
| `adafruit_sen6x` | 9.2 KB | 22.0 KB | ~13 KB |
| `adafruit_scd4x` | 4.1 KB | 11.5 KB | ~7 KB |
| `adafruit_bus_device.i2c_device` | 2.0 KB | 3.6 KB | ~2.2 KB |
| `node_sensors` | 4.4 KB | 11.4 KB | ~7 KB |
| `envproto` | 2.4 KB | 5.8 KB | ~3.5 KB |
| `envadv` (new, the BLE reading format) | 1.3 KB | — | ~1.6 KB |
| `caps` (new) | 1.7 KB | — | ~2 KB |
| collector tree without `hub_main`, display and BLE | — | 94.7 KB | ~57 KB |

### Pico W: why the node is `node_lite` and not the existing node

* `node/code.py` as it stood: 46.9 KB of source → 15.3 KB `.mpy` → ~18 KB
  of heap for the module alone, plus `net_ble`'s ~32 KB when the BLE
  portal opens. Over budget before a sensor driver loads — and compiling
  a 47 KB source *on* the board needs several times the source size in
  RAM, so it would not even get to the ImportError on `alarm`.
* `adafruit_ble` alone is ~30 KB of the 42 KB. **There is no version of
  the BLE UART portal that fits a Pico W.**
* `node_lite` + `caps` + `envadv` + `node_sensors` + `net_bleadv`: 12.4 KB
  of `.mpy` → **~15 KB** of heap, leaving ~27 KB for a sensor driver
  (SCD4x ~9 KB with bus_device; SEN6x ~15 KB) and the working set. SCD4x
  nodes should fit with ~15 KB to spare; a SEN6x node is marginal; the
  WiFi POST path (another ~12 KB + `envproto` 3.5 KB + TLS/socket buffers)
  does not fit alongside a SEN6x and is gated on `wifi_min_free` (40 KB by
  default, i.e. off on a Pico W).
* Deploy **`.mpy`**, not `.py` (`tools/build_bundle.sh` on PR #10 does
  this). Compilation peaks are the thing that kills a 40 KB board.

### Pico 2 W: the hub fits

`hub_main` tree: 71.2 KB of `.mpy` → ~85 KB; `adafruit_ble` chain ~30 KB;
`adafruit_sen6x` ~13 KB; stores, ring (2.4 KB), HTTP connections and TLS
working set on top. Roughly 150–180 KB against 303 KB. The C6 runs this
code in ~200 KB with the display; the Pico 2 W has no display to pay for.

## What changed in the code

* **`collector/code.py` / `node/code.py` are now gates.** CircuitPython
  loads a module's whole bytecode before running its first line, so the
  capability check has to live in a file small enough to load anywhere.
  The collector body moved verbatim to `hub_main.py` and is imported only
  when `gc.mem_free() >= 128 KB` and `wifi`/`socketpool` exist; below that
  the gate prints the reason and idles (REPL stays reachable). The node
  gate loads `node_full.py` (the unchanged ESP32 node) when `espnow` and
  `alarm` exist, `node_lite.py` otherwise. Capability and free memory,
  not board ids.
* **`caps.py`** (both trees, identical): the probes, and the wall clock.
  Every `time.time()` / zero-arg `time.localtime()` in the collector went
  through `caps.now()` / `caps.localtime()`; `rtc.RTC().datetime = …`
  became `caps.set_epoch()`. On a board with an RTC nothing changes.
* **softAP is verified, not trusted**: `hub_main` and `net_captive` raise
  if `wifi.radio.ap_active` is False after `start_ap()`, and skip the
  attempt entirely where `caps.AP_SUPPORTED` is False, with a message that
  says to use `CIRCUITPY_WIFI_SSID` instead.
* **ESP-NOW is optional**: `net_espnow` is imported only when the module
  exists; otherwise a `_NoHub` stand-in keeps the counters and API so the
  status page and the main loop are unchanged.
* **No SPI → no display, no SD**, decided before the display modules are
  imported (`caps.PIN_BUSIO`, `caps.spi()`); I2C comes from `caps.i2c()`
  (`board.I2C0` on the Picos).
* **New transport: BLE advertisement broadcast** — `envadv.py` (18-byte
  reading in a manufacturer-data structure, 25 bytes on air),
  `node/net_bleadv.py` (raw `_bleio`, non-connectable), and
  `collector/net_blescan.py` (1 s passive scan every 5 s with the AD
  prefix as filter; de-duplicates by address + seq; hands the reading to
  the same `take_node_packet()` the ESP-NOW path uses, with `mac=None` so
  nothing is sent back). Nodes appear as `ble-XXXX` (last two address
  bytes); map them to names in `zones`. No confirmation, no cfg push on
  this path — by design and documented in both files.
* `net_wifi` caps client connections at `caps.MAX_SOCKETS - 2` and syncs
  the clock through `caps.set_epoch(time.mktime(ntp.datetime))`.
* `tools/board_budget.py` and `tools/test_envadv.py` are new; the latter
  passes under CPython and under the unix CircuitPython build (26 checks),
  as does `tools/test_envproto.py` (21).

## Power, honestly

Neither board deep-sleeps under this firmware. A `node_lite` cycle is
read → advertise `ble_adv_s` (20 s) → `time.sleep()` for the rest of
`interval_s`, with the RP2040/RP2350 clocked and the CYW43439 powered
throughout. Expect on the order of **tens of mA** average (RP2040 ~20 mA
idle at full clock + CYW43 BLE idle a few mA; measure it — `tools/powerlog.sh`
if you have the rig), against **tens of µA** for the ESP32 nodes in deep
sleep. That is a 3-order-of-magnitude gap: a 500 mAh cell lasts about a
day, not months. These are mains/USB nodes. `time.sleep()` is the
lowest-power idle the port exposes; there is no `alarm.light_sleep` either.

## Configuring for the Picos

Hub (Pico 2 W), `collector/config.json` + `settings.toml`:

```
CIRCUITPY_WIFI_SSID / CIRCUITPY_WIFI_PASSWORD   required: no softAP, the portal lives on your LAN
"ap_enabled": false          (true is harmless: the hub detects the stub and says so)
"display_enabled": false     (also auto-detected: no SPI)
"ble_enabled": true          BLE UART portal for web-BLE
"ble_scan_nodes": true       receive node advertisements; "ble_scan_s" 1.0, "ble_scan_every_s" 5.0
"zones": {"ble-62AC": "Kitchen"}
```

Node (Pico W), `node/node_config.json`:

```
"sensor": ""                 auto-detect on I2C0 (GP4/GP5), or "sim" for a bench run
"interval_s": 120, "ble_adv_s": 20
"wifi_fallback": false       true + "collector_url" only where RAM allows (Pico 2 W)
```

Deploy `.mpy`. From PR #10's `tools/build_bundle.sh`:
`MPY_CROSS=… tools/build_bundle.sh`, then copy `build/node/*.mpy` (or
`build/collector/*.mpy`), the JSON config, `settings.toml`, and only the
`lib/` entries the tree actually imports (for a Pico W SCD4x node:
`adafruit_scd4x.mpy`, `adafruit_bus_device/`). **Keep `code.py` as `.py`**:
CircuitPython only runs `code.py`/`code.txt`/`main.py`, and the gate is
2 KB.

## Bench plan (nothing here was run)

Flashing either board **reformats CIRCUITPY** — copy anything off first.

**Step 0 — the budget.** Hold BOOTSEL, plug in, copy the board's UF2 from
the prerelease. When CIRCUITPY appears, at the REPL:

```py
import gc; gc.collect(); gc.mem_free()
import sys; sys.platform                      # 'Zephyr'
import time; time.time()                      # expect RuntimeError: RTC is not supported
import wifi; wifi.radio.start_ap("x"); wifi.radio.ap_active   # expect False, no exception
import board; board.I2C0, board.SPI           # bus objects; SPI is the radio's
```

Write the Pico W `gc.mem_free()` down: `node_lite` needs ~15 KB plus its
driver. If it reads under ~25 KB before any user code, the node does not
fit and this document is wrong by that much.

**Step 1 — Pico 2 W hub.** Copy `collector/` as `.mpy` + `code.py` +
`config.json` + `settings.toml` (WiFi creds) + `lib/`. Watch the REPL for,
in order:

```
collector: NNNNNN bytes free on Zephyr -> hub_main
platform: {... 'rtc': False, 'ap': False, 'espnow': False, 'pin_busio': False, 'sockets': 6 ...}
CircuitPython BLE workflow off (ours takes the radio)
early BLE advertising as HUB-XXXX
ESP-NOW not available on this port: ...
softAP not available on this port: ...
no user SPI bus on this board: eInk dashboard skipped; ...
WiFi up: 192.168.x.y channel N
NTP synced
bring-up: BLE node scan on
collector running; portal: http://192.168.x.y/
```

Then from a phone: connect to `HUB-XXXX` with a web-BLE UART console,
send `latest`, `mem`, `time <epoch>`. From a browser on the same LAN:
`http://192.168.x.y/api/latest` and the page. Failure signatures that
falsify the design:

* `BLE scan failed: ... -16` / `EBUSY` / `-EINVAL` every 5 s → this
  controller will not scan while advertising. Fallback: set
  `ble_scan_nodes` false and use WiFi POST from a Pico 2 W node, or
  alternate advertising and scanning (not implemented).
* `early BLE failed` → `_bleio`/`adafruit_ble` on this port (see the
  `start_advertising` NotImplementedError cases above).
* `HTTP portal start failed` or accept errors after the 4th connection →
  the socket ceiling; `CONFIG_NET_MAX_CONTEXTS` needs raising in the
  board `.conf` (a 6-minute firmware rebuild).
* Any `MemoryError` in the boot log on the Pico 2 W → the estimates
  above are wrong; report `mem[...]` lines.
* `Controller unresponsive, command opcode 0x…` / a halt with no Python
  traceback → `CONFIG_BT_ASSERT=y` in release builds; a controller
  timeout stops the board rather than raising (known, tyeth/circuitpython#15).

**Step 2 — Pico W node.** Copy `node/` as `.mpy` + `code.py` +
`node_config.json` with `"sensor": "sim"` first, `lib/` with only the
driver you need. REPL:

```
node: no espnow/alarm on Zephyr (NNNNN bytes free) -> node_lite (awake loop, BLE advertisements)
node_lite: ble-XXXX reset: ... free: NNNNN
SIMULATED sensor: ...
read sq=1: {...} batt=None free=NNNNN
BLE advertising sq=1 for 20s
idle 100s (awake: no deep sleep on this port)
```

On the hub, within ~5 s: `dat sq=1 crc=… from ble-XXXX: accepted,
confirming` and the source in `latest`. Then swap `"sensor": ""` and a
real SCD4x on GP4/GP5. Falsifiers:

* `MemoryError` at the gate or in `node_lite`'s first cycle → the Pico W
  budget is smaller than the ELF arithmetic says; report the Step 0
  number and the `free:` lines.
* `BLE beacon start failed` → advertising on this port (the hub uses the
  same call through `adafruit_ble`, so if Step 1 advertised, this should
  too).
* The hub never logs the node while a phone's nRF Connect shows the
  advertisement (company id `FF FF`, first payload byte `E7`) → the hub's
  scan filter or the scan/advertise coexistence; try `ble_scan_s: 3`.
* Watch `free:` across 50 cycles: a downward trend is a leak in the
  awake loop and would eventually MemoryError.

**Step 3 — Pico 2 W as a node** (optional): same files as Step 2; with
~300 KB it can add `"wifi_fallback": true, "collector_url":
"http://<hub-ip>"` and gets the hub's cfg reply (interval, time) back.

## Firmware notes

* Both board builds are green in CI on `ci/pico2w-ble-assets`
  (`raspberrypi_rpi_pico2_w_zephyr` run 34287512362,
  `raspberrypi_rpi_pico_w_zephyr` run 34287514167) and the binaries are on
  the prerelease above. `zephyr-tests / zephyr` is green on a branch off
  current `main` (tyeth/circuitpython#5, run 34282151673) — the red job
  recorded in PR #10 came from a branch 229 commits behind `main`.
* WiFi and BLE sharing the CYW43439 gSPI bus at the same time — a
  connected station serving HTTP while advertising and scanning — is the
  configuration this repo needs and the one nobody has run. The existing
  BLE work sized `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE=4096`,
  `CONFIG_BT_TX_PROCESSOR_STACK_SIZE=4096` and (Pico 2 W)
  `CONFIG_HW_STACK_PROTECTION=y`, so an overflow faults cleanly instead of
  corrupting a neighbour. If Step 1 hard-faults with both radios busy,
  the ELF on the prerelease is unstripped: `arm-zephyr-eabi-addr2line -e
  ….elf <pc>`.
* `CONFIG_NET_MAX_CONTEXTS=6` is the one deterministic limit found: see
  the socket row above and `net_wifi._MAX_CONNS`. Branch
  `zephyr-cp-pico2w-net-contexts` on tyeth/circuitpython (one commit on top
  of `ci/pico2w-ble-assets`) raises the Pico 2 W to
  `CONFIG_NET_MAX_CONTEXTS=12` / `CONFIG_NET_MAX_CONN=16`; it builds
  (FLASH unchanged at 1,146,096 B, RAM 229,144 → 231,112 B, +1,968 B) and
  is not run on hardware. With that firmware set `"max_sockets": 12` in
  `collector/config.json` so `net_wifi` allows six client connections
  again instead of four. The prerelease UF2s do **not** include it.
* No other firmware change was made. The WiFi+BLE stack sizing already in
  place (`SYSTEM_WORKQUEUE_STACK_SIZE=4096`, `BT_TX_PROCESSOR_STACK_SIZE=
  4096`, `HW_STACK_PROTECTION=y`) was left as is: nothing here can show it
  is insufficient without running the concurrent case, and guessing larger
  numbers would only hide the fault that proves it.
