# BLE + ESP-NOW test plan

Goal: prove the two transports that remain after parking the C6 softAP
(`bugs_issues_and_todos.md` item 0): **BLE UART portal** (user access) and
**ESP-NOW** (node mesh). Written for the next bench session, where the
controller is expected to be a **Raspberry Pi** — Linux BlueZ + Python
`bleak` gives fully scriptable BLE (scan/connect/notify) with none of the
Windows BLE quirks, and the Pi's USB ports host the dev boards' serial
consoles (`/dev/ttyACM*`) with `mpremote` for deploys.

## Rig

| Piece | Role |
|---|---|
| Raspberry Pi (or any Linux box with BT) | controller: `bleak` BLE client, `mpremote`, serial log capture, pytest runner |
| Feather ESP32-C6 (bench, sensorless ok) | collector under test (`ap_enabled=false, ble_enabled=true`) |
| Feather ESP32-S3 (bench, SCD41 or sensorless) | node under test |
| optional 3rd dev board | **ESP-NOW sniffer**: tiny CP script printing every espnow packet (mac/rssi/payload) to serial — the Pi tails it for mesh-level assertions |
| optional | self-compiled CircuitPython builds for the softAP/BLE-memory debugging (issues 0/5/7) |

Controller setup: `pip install bleak mpremote pyserial pytest`.
Starter client: `tools/ble_smoke.py` (works on Windows too, best on Pi).

## Status from the 2026-08-24 bench (Pi controller, rpi-hil003b)
* BLE GATT connect had failed from **three independent stacks** (WinRT,
  Android nRF Connect, BlueZ) — root cause was **C6 memory starvation**,
  not the BLE core: a minimal BLE-only code.py (227 KB free) connected
  instantly. Fixed by the `HTTP_WANTED` gate (don't load the HTTP stack
  in BLE-only mode) → ~72 KB free. See bugs item 7 (RESOLVED).
* **BLE suite items 1+2 PASS from the Pi**: scan, connect, full command
  matrix (`mem latest battery config days events`, `time <epoch>` incl.
  pending-record adjust), disconnect → re-advertise cycles, all with the
  eInk dashboard refreshing normally (issue 7 gone).
* **New issue 8**: C6 `_bleio` silently drops outgoing notifications
  (TX queue ~5 packets). `net_ble` paces TX (20 B / 50 ms) and
  `ble_smoke.py` retries on incomplete lines; occasional drops persist —
  quantify drop rate vs eInk-refresh timing in the longrun test.
* **New issue 9**: the proper fix (`_bleio.PacketBuffer` TX — real flow
  control, verified no drops while connected) wedges the main loop when
  the client disconnects mid-reply (`write()` never returns). Opt-in via
  `"ble_tx_pktbuf": true` until the core aborts writes on disconnect.
* **Node bench mode**: `"deep_sleep": false` in node_config.json keeps
  the node awake between reports (USB console stays alive; sleep_memory
  still carries stash/seq across the supervisor reload each cycle).
* **ESP-NOW suite items 1-5 PASS** (evening session, `ble_enabled=false`):
  broadcast discovery + NVM pin (no re-hunt on later wakes), data path
  with live alerts on the eInk, hub time push (`clock set from hub`,
  stash timestamps retro-adjusted), config push (`interval -> 120`), and
  stash retransmission (36 backlogged readings drained 20+16 across two
  wakes, original timestamps kept). Node ran in the new bench mode
  (`"deep_sleep": false`).
* **BLE and ESP-NOW are mutually exclusive on the C6** (issue 10): BLE
  resident → every espnow TX fails 0x3067 NO_MEM (RX still works), even
  after deinit/re-init. The BLE-suite coexistence test (item 5) is
  therefore an expected FAIL on C6 until the core slims down; run the
  coexistence tests on a PSRAM board or after tuned self-builds.
  config.json ships `ble_enabled=false` (node mesh mode); flip to true
  for a BLE-access hub.
* All of today's findings (0-10 + the S3 USB-wedge) need re-validation on
  C6/S3 **devkits (dual USB)** with **debug-logging self-built CP** —
  see the validation matrix in bugs_issues_and_todos.md.
* Pi bench notes: BT adapter starts soft-blocked —
  `/usr/sbin/rfkill unblock bluetooth` (no sudo needed) then
  `bluetoothctl power on`. esptool 5.3.1 cannot watchdog-reset a C6 and
  RTS is a no-op on USB-Serial/JTAG: reset by injecting
  `\x03` + `import microcontroller` + `microcontroller.reset()` straight
  into `/dev/ttyACM0` (or mpremote exec) instead.

## BLE test suite (scriptable with bleak)

1. **Scan/advertise**: `ENVHUB` visible; Nordic UART service UUID
   (`6e400001-…`) in the advertisement; note RSSI. Re-appears within 5 s
   of a client disconnect (net_ble re-advertises).
2. **Command matrix** (connect, subscribe TX notify, send line, expect one
   JSON line back): `latest`, `battery`, `events`, `config`, `days`,
   `mem`, `time <epoch>` (verify `delta_s` and that a later `latest` has
   sane `ts`), `set {"display_interval_s":40}` (verify via `config`),
   bogus command → `{"err": "unknown cmd", …}`.
3. **`hist <day>` streaming**: `#BEGIN d` … CSV … `#END` framing intact,
   row count matches `/data/d.csv` on the device, measure throughput.
4. **Reconnect robustness**: 10× connect/command/disconnect cycles; then a
   held connection for 30 min polling `latest` + `mem` every 30 s —
   `free` must not trend downward (leak watch).
5. **Coexistence**: while a BLE client is connected, the node reports over
   ESP-NOW → next `latest` shows the node entry (both radios truly live).
6. **Calibration UX**: `cal <node> 1` returns the go-outside warning;
   `cal <node> 2` arms; node executes at next check-in; `events` shows
   `cal_ok`.

## ESP-NOW test suite

1. **Discovery**: clear a node's NVM (`microcontroller.nvm[0]=0`) →
   power-cycle → node broadcasts `dsc`, hunts channels, learns the
   collector MAC+channel from the `cfg` reply ("discovery from …" on the
   collector console); NVM pin survives a power cycle (no re-hunt).
2. **Data path**: `dat` every interval; visible in BLE `latest` (zone,
   values, `age` resetting); recorded to the collector's day CSV.
3. **Time service**: sync the hub clock via BLE `time`; next node check-in
   gets `t` in its cfg; node console prints "clock set from hub"; record
   timestamps become sane (post-2023) including the node's `at` values.
4. **Config push**: BLE `set {"node_intervals":{"<name>":30}}` → node's
   next cfg reply carries `int:30` → node sleeps 30 s cycles.
5. **Stash & retransmit**: power the collector OFF for ~10 min while the
   node keeps waking ("stashed reading (N held)" on node console) → power
   the collector ON → backlog arrives ("retransmitted N stashed"), day
   CSV contains the missed readings with their original timestamps.
6. **Channel agility**: give the collector STA creds (channel moves to the
   router's) → node's pinned channel goes stale → it re-hunts and repins.
7. **Sniffer assertions** (optional 3rd board): every `dat` gets a `cfg`
   reply ≤100 ms; payloads ≤250 B; no packet storms.

## Pass criteria
All numbered items above green, plus: collector uptime ≥12 h in BLE mode
with stable `mem`, zero safe-mode entries, node battery... (battery-power
soak once sensors return). Findings go into `bugs_issues_and_todos.md`;
upstream issues get filed with the self-built CP evidence.
