# Raspberry Pi Pico W / Pico 2 W (CircuitPython Zephyr port)

What this repo does and does not do on the two Pico W boards, with the
numbers behind each claim, and how to find out where they are wrong.

**Firmware.** `tyeth/circuitpython` branch `ci/pico2w-ble-assets`, now
rebased onto upstream CircuitPython `main` 35210c2e (after 11.0.0-alpha.1)
at `393be068ab`. Both boards build green in CI —
[Pico 2 W run 37126091753](https://github.com/tyeth/circuitpython/actions/runs/37126091753),
[Pico W run 37126093209](https://github.com/tyeth/circuitpython/actions/runs/37126093209).
The Pico W was then rebuilt with `CONFIG_BT_MAX_CONN=2` in its board
`.conf` at `3501030d6c` —
[Pico W run 37127295820](https://github.com/tyeth/circuitpython/actions/runs/37127295820),
the one to flash.
There is no prerelease of it yet. TODO(fw-11): link the prerelease UF2s
here once they exist. Upstream 11.0.0-alpha.1 itself still builds both
boards with `_bleio = false`, so it cannot run the BLE parts of this.

History, because several numbers below were measured on it: PR #11 was
written against `94bfd47b5f` (prerelease
[`zephyr-cp-ble-ci-20260909`](https://github.com/tyeth/circuitpython/releases/tag/zephyr-cp-ble-ci-20260909)),
and the hardware results posted on PR #11 come from the stack on top of it
(tyeth/circuitpython#19 → #23).

**What has run on hardware, and what has not.** The firmware facts marked
*measured* were measured on a Pico 2 W (some on a Pico W) on the pre-rebase
stack. **Nothing in this repo's code has run on either board**, and
nothing at all has run on the rebased firmware: its numbers here are from
the build (`.elf` / CI). The code was checked by compiling every source
with `mpy-cross`, by `tools/board_budget.py`, and by running the hub and
the node under CPython with stub modules shaped like the port (`sys.platform
== "Zephyr"`, no `espnow`/`alarm`/`rtc`, `time.time()` raising, a
`start_scan` that ignores its timeout). The bench plan at the end turns
"should" into "does".

## The short version

| | Pico W (RP2040) | Pico 2 W (RP2350) |
|---|---|---|
| role | **node** (`node_lite`) — *if it fits, see RAM* | **hub** (`hubmain`), or a node |
| heap (rebased firmware) | **~19.6 KB** by the ELF (264 KB − 250,224 B) | ~270 KB by the ELF; budget **~180 KB** (see RAM) |
| node → hub transport | BLE advertisement broadcast | receives BLE advertisements; WiFi `POST /api/ingest` |
| phone / browser access | none (no RAM for the BLE UART portal) | BLE UART (web-BLE) + HTTP portal on home WiFi, **or** on its own setup AP — not both |
| clock | `rtc` module (SoC counter, from upstream) | **no `rtc`**: `caps` keeps an offset clock; an RTC chip on I2C sets it |
| deep sleep | no — awake loop | no — the hub never slept anyway |
| ESP-NOW | no (module absent) | no |
| eInk / SD card | no (no user SPI bus) | no (same) |

The repo's name promises deep sleep and ESP-NOW. On these boards it delivers
neither, and the code says so at boot instead of dying at `import`.

## What the firmware provides

| module | state | consequence |
|---|---|---|
| `espnow` | **absent** (not in the module table) | no mesh; `net_espnow` is not loaded (`caps.HAS_ESPNOW`), a `_NoHub` keeps the counters |
| `alarm` | false (upstream zephyr-cp has none) | no deep sleep, no `sleep_memory`; the node is an awake loop |
| `rtc` | **Pico W: true** (new with the CircuitPython-11 rebase — upstream reads the board's devicetree RTC node). **Pico 2 W: false** (no such node) | on the Pico 2 W `time.time()` and zero-arg `time.localtime()` **raise** `RuntimeError: RTC is not supported on this board` (*measured*); `time.localtime(secs)` / `time.mktime()` still work. `caps` probes `rtc` + a working `time.time()` and only then trusts them, so each board gets the right clock without a board table |
| `wifi` | station **and** softAP + DHCPv4 server | softAP was an empty stub before tyeth/circuitpython#22 (it returned, and `ap_active` stayed False); it is real now (192.168.4.1/24, DHCP auto-started, *measured*: a C6 joined in 7 s). **AP and station cannot run together**: AIROC uses one `net_if`, AP+STA returns `-EBUSY` (*measured*). `max_connections` is not honoured |
| `busio` | devicetree buses only | `busio.SPI(...)` / `busio.I2C(scl, sda)` raise `NotImplementedError("Use device tree to define ...")` (*measured*). `board.SPI` is the CYW43439 radio's own PIO bus — never a display or SD bus. Sensors on `board.I2C0` (SDA **GP4**, SCL **GP5**) or `board.I2C1` (GP6/GP7), which are callables (*measured*) |
| `_bleio` | true | legacy advertising only (`CONFIG_BT_EXT_ADV=n`; no extended advertising on the controller). **`CONFIG_BT_MAX_CONN=5`** on the Pico 2 W (upstream `prj.conf`; was Zephyr's default 1 when PR #11 was written), **2** on the Pico W (its board `.conf`, for RAM), `BT_MAX_PAIRED=3`. More than one connection at once has **not** been run. `start_scan(timeout=)` was **ignored** before tyeth/circuitpython#20 (see below). Reception works (*measured*: 925 reports from 20 devices in one scan) |
| `socketpool`, `ssl` | true | `CONFIG_NET_TCP` was **off** until tyeth/circuitpython#21 — before it no `SOCK_STREAM` socket ever worked, and the error read "Out of sockets". TLS 1.2 with an RSA-2048 cert works since (*measured*: `200 OK` in 2.0 s). `CONFIG_NET_MAX_CONTEXTS=6` sockets in total |
| frozen modules | Pico W: 20 `adafruit_ble` modules | cheaper than `.mpy` from CIRCUITPY (*measured* on the first version: 10,384 B frozen vs 21,792 B) — still most of a Pico W |
| `storage`, `supervisor`, `nvm` | true | `boot.py`, the filesystem handover and the hub's NVM radio mirror work as on the S3 |
| `displayio`, `epaperdisplay`, `sdcardio` | true | useless without a user SPI bus |

Every import in both trees against that table (`tools/board_budget.py`, CPython `ast`):

```
$ python tools/board_budget.py         (from the module each code.py imports)
collector/hubgate.py   HARD: none.  soft: analogio (battery, guarded), espidf (net_wifi, guarded),
                       espnow (hubmain guarded / net_espnow conditional), rtc (extrtc / caps deferred)
node/nodegate.py       HARD: none.  soft: alarm, espnow (nodegate's own probes, guarded),
  (not following       analogio (battery, guarded), rtc (caps deferred)
   nodemain)
```

`node/nodegate.py~nodemain` leaves out the ESP32 branch a Pico never takes;
pass `node/nodemain.py` to see what stops it there.

## Corrections to PR #11, and where each went

PR #11 was written before any of it ran. The hardware results posted on it
moved five premises; this branch carries all five.

1. **`start_scan(timeout=)` was silently ignored** — Zephyr's
   `start_le_scan_legacy()` never reads it, so scans never ended; PR #11's
   hub would have sat in its first `poll()` forever. Fixed in firmware by
   tyeth/circuitpython#20. In the code: `net_blescan` keeps its own
   deadline (`scan_s` + 0.5 s), stops the scan itself and counts
   `overruns` (printed once). In a room with *no* advertisements at all the
   unfixed firmware can still block between reports — only #20 cures that.
2. **`BT_MAX_CONN=1` was Zephyr's default**, not the controller; it is 5
   now on the Pico 2 W and 2 on the Pico W. The broadcast transport stays (no connection, no `adafruit_ble` on
   a node), but it is no longer forced: a connection with ESP-NOW's
   message-id + CRC-16 confirmation is the open alternative. The docstrings
   (`envadv`, `net_bleadv`) say this instead of the old reason.
3. **softAP works now (#22), APSTA does not.** `caps.AP_VERIFY`: on this
   port the AP is started and believed only if `wifi.radio.ap_active` says
   so (older firmware still has the stub). `caps.APSTA = False`: with home
   WiFi credentials in `settings.toml` the hub joins the station and skips
   the early AP; if the join fails, `net_captive` brings the setup AP up
   instead. Without credentials the AP comes up as on an ESP32.
4. **`CONFIG_NET_TCP` had never been on** before #21, so no HTTP or TLS path
   had executed on these boards. Nothing in the code can check for it; the
   bench plan does. `net_wifi` allows `caps.MAX_SOCKETS − 3` clients (two
   listeners + captive DNS out of 6), `"max_sockets"` in `config.json`
   overrides.
5. **The heap table was wrong** both ways — see RAM. The hub gate in
   `collector/hubgate.py` is 40 KB of `gc.mem_free()`, not PR #11's 128 KB,
   which would have refused the Pico 2 W.

## RAM

Static RAM from the rebased firmware's builds, and what that leaves:

| | total | firmware static | left by the ELF | budget used |
|---|---|---|---|---|
| Pico W (`BT_MAX_CONN=2`) | 270,336 B | **250,224 B (92.56 %)** | **~19.6 KB** | 20,112 B |
| Pico 2 W | 532,480 B | 260,680 B (48.96 %) | ~271.8 KB | ~181,000 B |

(Pre-rebase, for comparison: Pico W 228,044 B static → 42,292 B; with TCP
238,996 B → ~31 KB. Pico 2 W 229,144 B → 303,336 B. The Pico W's first
rebased build, at upstream's 5 connections, was 253,516 B → 16,820 B.)

**The ELF number is not the heap.** *Measured* on the pre-rebase Pico 2 W:
`gc.mem_free()` at a bare REPL read ~70,700 B (the *initial* heap — it
grows on demand, rising to 103,808 B mid-allocation), cumulative
`bytearray(8192)` allocations reached **212,992 B** before `MemoryError`
against an ELF figure of 303,336 B, and the largest single allocation that
succeeded was between 50,000 and 100,000 B. `port_heap_init()` skips its
TLSF pool when picolibc's malloc arena covers the region, so allocations
go through Zephyr `malloc` in chunks: object count is fine, single large
buffers are not. Applying that ~90 KB overhead to the rebase gives the
~181 KB budget. TODO(fw-11): re-measure both numbers on the rebased
firmware.

Two consequences in the code:

* `gc.mem_free()` under-reads on this port, so no gate may demand what the
  hub really needs: `collector/hubgate.py` refuses only below 40 KB (under the
  ~70 KB a Pico 2 W reports, over anything a Pico W can), and node_lite's
  `wifi_min_free` (40 KB) keeps a Pico W off the WiFi POST path while
  letting a Pico 2 W on.
* Budget the Pico 2 W hub against ~180 KB with nothing over ~50 KB in one
  piece. `hubmain` + its modules come to ~108 KB loaded (`board_budget.py`,
  `.mpy` × 1.2) before data; no display tree to pay for.

### Pico W: the risk

`nodegate` + `node_lite` + `caps` + `envadv` + `node_sensors` +
`net_bleadv` (+ the guarded `battery`/`envproto`) come to ~16.1 KB of
`.mpy`, **~19.3 KB loaded** — just inside the rebased Pico W's whole
~19.6 KB, and nowhere near it once a sensor driver (`adafruit_scd4x` +
`bus_device` ~9 KB) and the supervisor's own allocations arrive. **As
built, the Pico W node does not fit.** `node/nodegate.py` catches the
`MemoryError` from loading it and says so, with the REPL left up.
(`board_budget.py` compiles each module by its bare name, as
`build_mpy.sh` does; it used to pass the full path, which `mpy-cross`
stores in the `.mpy`, and over-counted ~100 B a module.)

Connections are not where it is won back. The Pico W already builds with
`CONFIG_BT_MAX_CONN=2`, and going from upstream's 5 to 2 gave back
**3,292 B — ~1.1 KB a connection** (measured from the two builds'
static RAM), so 1 would add ~1.1 KB more. The bigger loss is the ~22 KB
between the 20260909 prerelease (42,292 B) and the rebase, which is not
yet accounted for: comparing the two builds' memory maps (`zephyr.map`,
largest `.bss`/`.noinit` symbols) is the next step. Short of that: drop
`node_sensors` drivers the board does not need, or freeze `node_lite`'s
modules. TODO(fw-11): measure `gc.mem_free()` and a cumulative-allocation
run on a flashed Pico W before believing any of this.

The BLE UART portal on a Pico W stays out of reach: frozen `adafruit_ble`
is ~10 KB of a ~19.6 KB heap.

## What changed in the code

* **Entry points.** Both `code.py` files are still one line — the C6
  compiles `code.py` on the device and a bigger one denies `esp_wifi_init`
  its contiguous RAM — so the new logic lives in two tiny modules shipped
  as `.mpy` like the rest. `collector/code.py` imports `hubgate`: below
  40 KB of `gc.mem_free()` it says the board is too small and idles, else
  `import hubmain`. `node/code.py` imports `nodegate`: `nodemain` (the
  ESP32 node, unchanged) when `espnow` and `alarm` import, else `node_lite`
  and its `run()`; a `MemoryError` from that import is reported as "does
  not fit". `run()` catches each cycle's own failures (a battery-monitor
  `OSError`, a driver's `ValueError`, a `MemoryError`), logs them and
  carries on at the next interval.
* **`caps.py`** (identical in both trees): probes and the clock.
  `caps.time` is the `time` module wherever `rtc` exists and `time.time()`
  works — every ESP32, and now the Pico W — and otherwise a stand-in whose
  `time()`/`localtime()` read an offset against `time.monotonic_ns()`. The
  collector's modules use `time = caps.time` instead of `import time`, so
  no call site changed; `rtc.RTC().datetime = …` became
  `caps.set_epoch()` / `caps.set_datetime()`, which are that same write
  where there is an RTC.
* **`extrtc`** uses `caps` only when `time.time()` raises: a coin cell on a
  Pico 2 W sets caps' clock at boot and is written from it after NTP or a
  browser sync. An ESP32 node never loads `caps`.
* **The hub's gates** (all in `hubmain`, all after the early radio block —
  nothing is imported above it): no ESP-NOW → `_NoHub`; softAP verified on
  this port; AP *or* station (above); no user SPI → no display and no SD,
  decided before their modules import; I2C from `caps.i2c()`.
* **BLE advertisement transport.** `envadv.py` (a 20-byte reading in a
  manufacturer-data structure, 27 bytes on air of the legacy PDU's 31),
  `node/net_bleadv.py` (raw `_bleio`, non-connectable),
  `collector/net_blescan.py` (1 s passive scan every 5 s, prefix filter,
  de-dup by node id + seq, its own deadline, into
  `take_node_packet(mac=None)` — nothing is sent back). Nodes appear as
  `ble-XXXX`; map them in `zones`. The hub scans by default only where it
  has no ESP-NOW; `"ble_scan_nodes": true` turns it on elsewhere — and on
  an ESP32 only if BLE came up in the early block (`"ble_enabled": true`),
  since enabling the adapter after the softAP is the C6 hard fault; it is
  refused with a log line otherwise.
* **The node id is in the payload** (envadv `VERSION` 2). The advertiser
  address is useless as an id: zephyr-cp's `Adapter.c` advertises with
  `options=0`, so for a non-connectable set Zephyr's
  `bt_id_set_adv_own_addr()` picks a fresh non-resolvable private address
  at every advertising start — once per reading. Keyed by address, every
  reading was a new source, the datastore's 256-source cap filled in
  ~8.5 h, and the node's WiFi POST never matched its advertisement. Now
  `node_lite` derives a 16-bit id from its identity address (the last two
  printed bytes; `"node_id"` in `node_config.json` overrides), puts it in
  every advertisement and names its POST `ble-%04X` from the same number;
  the hub ignores the address. A VERSION 1 advertisement is dropped with
  one log line (`ignoring advertisements in envadv VERSION 1`) and counted.

  | offset | size | field |
  |---|---|---|
  | 0 | 1 | MAGIC `0xE7` (the scan filter) |
  | 1 | 1 | VERSION `2` |
  | 2 | 2 | node id, uint16 LE → `ble-%04X` |
  | 4 | 1 | seq (wraps at 256) |
  | 5 | 2 | tc × 100, int16 (−32768 = none) |
  | 7 | 2 | rh × 100 |
  | 9 | 2 | co2 ppm |
  | 11 | 2 | pm2.5 × 10 |
  | 13 | 2 | VOC index |
  | 15 | 2 | NOx index |
  | 17 | 2 | battery mV |
  | 19 | 1 | sensor type |

  uint16 fields use `0xFFFF` for none; scaled values are rounded, not
  truncated. 20 + 4 (AD length, type, company id `0xFFFF`) + 3 (flags) =
  27 bytes.
* **When a node sends both.** A `node_lite` with `wifi_fallback` sends
  each reading as an advertisement *and* a POST, and the POST is the
  richer copy (pm1/pm4/pm10 and the node's `at`). The datastore is
  append-only, so the hub cannot merge one into the other: instead, once a
  node has POSTed since the hub booted, its BLE copies are held up to 30 s
  for the POST, which replaces them; a copy whose POST never comes is
  stored when the 30 s run out. A failed store forgets the reading's seq,
  so the next copy of it is taken rather than dropped as a duplicate.

## Power, honestly

Neither board deep-sleeps under this firmware. A `node_lite` cycle is
read → advertise `ble_adv_s` (20 s) → `time.sleep()` for the rest of
`interval_s`, with the MCU clocked and the CYW43439 powered throughout.
Expect **tens of mA** average against **tens of µA** for an ESP32 node in
deep sleep: a 500 mAh cell lasts about a day, not months. These are
mains/USB nodes.

## Configuring

Hub (Pico 2 W), `collector/config.json` + `settings.toml`:

```
CIRCUITPY_WIFI_SSID / _PASSWORD   the station; with these set the hub does NOT start its setup AP
                                  unless the join fails (no AP+STA on this radio)
"ap_enabled": true                setup AP when there are no credentials, or the join failed
"ble_enabled": true               BLE UART portal for web-BLE
"ble_scan_nodes"                  default on where there is no ESP-NOW; "ble_scan_s" 1.0, "ble_scan_every_s" 5.0
"max_sockets"                     only with firmware built with a larger CONFIG_NET_MAX_CONTEXTS
"rtc": "auto"                     a coin-cell RTC on I2C0 gives the Pico 2 W a clock across power cuts
"zones": {"ble-62AC": "Kitchen"}
```

Node, `node/node_config.json`:

```
"sensor": ""                 auto-detect on I2C0 (GP4/GP5), or "sim" for a bench run
"interval_s": 120, "ble_adv_s": 20
"wifi_fallback": false       true + "collector_url" only where RAM allows (Pico 2 W)
"name": ""                   leave empty: the POST then uses the advertised ble-XXXX
"node_id": 0                 0 = from the board's address; set only to part two colliding nodes
```

Deploy `.mpy` (`tools/build_mpy.sh`, or `tools/build_bundle.sh` — both
compile `hubgate`/`nodegate` with everything else), keep
`code.py` as source, and copy only the `lib/` entries the tree imports
(for an SCD4x node: `adafruit_scd4x.mpy`, `adafruit_bus_device/`).

## Bench plan

Flashing either board **reformats CIRCUITPY** — copy anything off first.
Use the rebased firmware (TODO(fw-11): the prerelease, once made; until
then the CI artifacts of the runs above). Release images before the USB
stack fix in tyeth/circuitpython#19 dropped off USB under BLE load; and
BLE bring-up after a *warm* SWD reset has been seen to halt on
`BT_ASSERT` — if that still happens, stop: nothing below is runnable.

**Step 0 — the facts, per board.** At the REPL:

```py
import gc; gc.collect(); gc.mem_free()
import sys; sys.platform                     # 'Zephyr'
import time; time.time()                     # Pico 2 W: RuntimeError (no RTC). Pico W: a number now
import wifi; wifi.radio.start_ap("x"); wifi.radio.ap_active   # True on #22+ firmware
import _bleio, time as t; a = _bleio.adapter; s = t.monotonic()
for e in a.start_scan(timeout=1): pass
t.monotonic() - s                            # ~1.0 s. If this never returns: pre-#20 firmware
```

Then, on a Pico W, a cumulative-allocation run (`x=[]` then
`x.append(bytearray(1024))` until `MemoryError`) — **that** number, not the
ELF's, decides whether `node_lite` fits.

**Step 1 — Pico 2 W hub.** `collector/` as `.mpy` + `code.py` +
`config.json` + `settings.toml` (WiFi credentials) + `lib/`. Expect, in
order:

```
ESP-NOW not available on this port: ...
softAP deferred: this port cannot run an AP beside a station ...
no user SPI bus on this port: eInk dashboard skipped; ...
platform: {'platform': 'Zephyr', ..., 'espnow': False, 'rtc': False, 'apsta': False, 'pin_busio': False, 'sockets': 6}
no user SPI bus on this port: no SD card; flash buffering
WiFi up: 192.168.x.y channel N
NTP synced (UTC)
clock: synced
bring-up: ESP-NOW wrapper (enabled=False)
bring-up: BLE node scan on
collector running; portal: http://192.168.x.y/
```

Then a phone on web-BLE (`HUB-XXXX`: `latest`, `mem`) and a browser on the
LAN (`/api/latest`, the page). Repeat with the WiFi credentials wrong: the
hub should print `WiFi connect failed`, then `AP up: BASE… @ 192.168.4.1`
from `net_captive`. Falsifiers:

* `BLE scan failed: ... -16` / `EBUSY` / `-EINVAL` every 5 s → this
  controller will not scan while advertising. Fallback: `ble_scan_nodes`
  false and WiFi POST from a Pico 2 W node, or alternate advertising and
  scanning (not implemented).
* `BLE scan: timeout= not honoured` → pre-#20 firmware; it keeps working
  while reports arrive, and can hang in a silent room.
* `HTTP portal start failed`, or accept errors from the 4th connection →
  TCP or the socket ceiling.
* Any `MemoryError` on the Pico 2 W → the budget above is wrong; report
  the `mem[...]` lines.
* A halt with no traceback → `CONFIG_BT_ASSERT=y`; a controller timeout
  stops the board rather than raising.

**Step 2 — a node.** `node/` as `.mpy` + `code.py` + `node_config.json`
with `"sensor": "sim"`, `lib/` with only the driver you need. Expect:

```
node: no espnow/alarm on Zephyr -> node_lite (awake loop, BLE advertisements)
node_lite: ble-XXXX reset: ... free: NNNNN
SIMULATED sensor: ...
read sq=1: {...} batt=None free=NNNNN
BLE advertising sq=1 for 20s
idle 100s (awake: no deep sleep on this port)
```

and on the hub within ~5 s: `dat sq=1 crc=… from ble-XXXX: accepted`,
with the **same** `ble-XXXX` the node printed, and the same one again at
`sq=2`, `sq=3` — a new id per reading means the hub is reading the
(random) address, i.e. an old `envadv` on one side. On a
Pico W the likely first result is `node: node_lite does not fit in this
board's heap` — that is the RAM section above, and the fix is in the
firmware (finding the ~22 KB the rebase took). Run Step 2 on a Pico 2 W first to prove
the transport. Watch `free:` across 50 cycles for a leak.

**Step 3 — Pico 2 W node with WiFi** (optional): add `"wifi_fallback":
true, "collector_url": "http://<hub-ip>"` and it gets the hub's cfg reply
(interval, time) back — the one path with a confirmation.

## Firmware notes

* Socket ceiling: `CONFIG_NET_MAX_CONTEXTS=6`. Branch
  `zephyr-cp-pico2w-net-contexts` (one commit on the pre-rebase
  `ci/pico2w-ble-assets`) raised the Pico 2 W to 12 / `NET_MAX_CONN=16`
  for +1,968 B of RAM; set `"max_sockets": 12` with such firmware.
  TODO(fw-11): carry it onto the rebased branch or drop it.
* The Pico W's RAM is the binding constraint. Its board `.conf` already
  sets `CONFIG_BT_MAX_CONN=2` (~3.3 KB back from 5; tyeth/circuitpython
  `b610e43` on `zephyr-picow-ble`); the single most useful firmware change
  left is finding the ~22 KB the CircuitPython-11 rebase took. TODO(fw-11).
* WiFi and BLE sharing the CYW43439 gSPI bus at the same time — a station
  serving HTTP while advertising and scanning — is the configuration the
  hub needs and the one nobody has run. The existing stack sizing
  (`SYSTEM_WORKQUEUE_STACK_SIZE=4096`, `BT_TX_PROCESSOR_STACK_SIZE=4096`,
  `HW_STACK_PROTECTION=y` on the Pico 2 W) was left as is.
