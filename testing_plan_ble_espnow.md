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

## Status from the 2026-08-24 bench (Windows controller)
* BLE **advertising verified**: `tools/ble_smoke.py` scan finds
  `ENVHUB [40:4C:CA:59:7B:E6]` from the PC.
* BLE **GATT connect fails from Windows/WinRT** (service-discovery
  timeout, 3 retries) — retest first thing from the Pi (BlueZ) and/or a
  phone (Bluefruit Connect app → UART → `latest`); if BlueZ also fails,
  the C6 alpha's connection path is implicated, not the client.
* ESP-NOW end-to-end still pending a node power-cycle against the
  BLE-mode collector.

## Known blockers to clear first
* **Issue 7**: with BLE resident on the C6, eInk refreshes fail
  (`SPI configuration failed`, internal-heap starvation). Either accept
  display-off during BLE longruns, test BLE on the S3 instead, or tune a
  self-built CP. BLE *advertising and the UART portal* work regardless.

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
