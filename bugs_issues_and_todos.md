# Bugs, upstream issues & TODOs

Findings from the 2026-08-24 hardware bring-up (Feather ESP32-C6 +
CircuitPython **10.3.0-alpha.4** + eInk Feather Friend #4446 + 3.52" quad
JD79667; node = Feather ESP32-S3 No PSRAM, same CP version).

## Suspected CircuitPython core bugs (worth filing upstream)

### 1. C6: `wifi.radio.start_ap()` hard-faults when called after heavy imports
* **Symptom**: `Hard fault: memory access or instruction error` → safe
  mode, immediately at the `start_ap` call. 100% reproducible in a normal
  boot once `adafruit_httpserver`/`displayio` etc. are imported; the same
  call works in safe-mode REPL, in a fresh-VM REPL, and at the very top of
  `code.py` before any heavy imports.
* **Hypothesis**: softAP init needs large contiguous internal-heap
  allocations; when they fail the port hard-faults instead of raising
  `MemoryError`/`espidf.IDFError`.
* **Workaround**: "EARLY AP START" block at the top of `collector/code.py`.
* **Repro**: flash CP 10.3.0-a4 on `adafruit_feather_esp32c6_4mbflash_nopsram`;
  `import adafruit_httpserver, displayio; import wifi; wifi.radio.start_ap(ssid="X")`
  in code.py (not REPL).

### 2. C6: wifi/socket bring-up corrupts the shared `busio.SPI` lock flag
* **Symptom**: after constructing a `socketpool.SocketPool` + UDP socket
  (captive-portal DNS) with the AP active, the SPI bus used by the eInk
  reads LOCKED forever: `spi.try_lock()` returns False with **no Python
  owner**, and every `EPaperDisplay.refresh()` fails `"Refresh too soon"`
  (misleading message — it's the `displayio_display_bus_is_free` check)
  while `time_to_refresh == 0.0` and `busy == False`.
* **Evidence**: staged `spi.try_lock()` probes: free after ESP-NOW init,
  LOCKED immediately after `CaptivePortal` construction (wifi/socket code
  that never touches SPI).
* **Workaround**: call `spi.unlock()` (ignoring errors) before each
  refresh (`collector/code.py refresh_display`).

### 3. `sdcardio.SDCard()` leaves the SPI bus locked when card-init fails
* **Symptom**: with no card inserted, the failed constructor
  (`OSError: no SD card`) leaves the shared SPI locked → all display
  refreshes blocked (same misleading "Refresh too soon").
* **Workaround**: `spi.unlock()` in the except branch.
* Probably a genuine upstream bug regardless of the C6 flag corruption.

### 4. e-paper + console splash: supervisor auto-refresh starves user refreshes
* **Symptom**: if an `EPaperDisplay` is left showing the splash/console,
  the supervisor auto-refreshes it in the background; user `refresh()`
  calls then collide indefinitely. `root_group = None` re-shows the
  splash, restarting the cycle.
* **Workaround**: assign a real (white) group immediately at construction
  and never set `root_group = None`.
* Docs could warn about this; also `"Refresh too soon"` is raised for
  three unrelated causes (timer, busy, bus-not-free) — separate messages
  would have saved hours.

### 5. C6: BLE alongside softAP — **UNDER TEST, see below**
* Observed once as a clean `_bleio` error `Unknown system firmware error:
  519` (graceful), and one boot with BLE re-enabled ended in a hard fault
  (location not confirmed — needs the retest documented below).
* esptool note: `--after watchdog-reset` is not supported for C6 by
  esptool 5.2.dev4, and RTS reset is a no-op on USB-Serial/JTAG, so a
  flashed C6 sits in download mode until the physical reset button.

### BLE + AP coexistence retest (C6)
Procedure: boot the full collector with `ble_enabled=true`, AP active;
vary WHERE BLE is initialised. Watch for (a) success, (b) clean error,
(c) hard fault.

| Configuration | Boots | Result |
|---|---|---|
| BLE **workflow** (pre-boot) + early AP + late user BLE init | 1 | AP + workflow coexist; user BLE init fails **cleanly** (`Unknown system firmware error: 519`) |
| workflow OFF, early AP, **late** user BLE init (after all imports) | 2 | **HARD FAULT** both boots, exactly at BLE init (last breadcrumb `mem[after http portal]`) |
| workflow OFF, early AP **then** early BLE (before heavy imports) | 1 | catastrophic: USB-Serial/JTAG **wedged** (port opens but blocks; needs physical reset) |
| workflow OFF, early **BLE then AP** (mirrors the workflow ordering) | — | _next test — code deployed as the new default order_ |

Interim conclusion: on C6/CP10.3-a4, initialising BLE from user code while
the softAP is active fails in every ordering tried so far except when the
BLE stack came up FIRST (the workflow case) — hence the BLE-then-AP
ordering now in `collector/code.py`. If that also fails, the fallback is
`ble_enabled=false` on C6 hubs (AP + web portal remain).

## Library bugs
* `adafruit_jd79667` ships **debug prints**: the start-sequence hex dump
  and a stray `AttributeError:` line on every init.
* `adafruit_jd79667` passes no `refresh_time`/`seconds_per_frame`; the
  quad panel takes ~20 s per refresh; the inherited defaults (refresh_time=40, seconds_per_frame=180) are wrong for it, and `time_to_refresh` did not
  reflect the enforced minimum in all states.
* `mpremote fs cp` to a **new** file on CP 10.3-alpha fails with a
  device-side `ENOENT` (overwrites of existing files work) — CP or
  mpremote raw-REPL helper incompatibility.

## TODOs
* [ ] Fill in the BLE retest table above; file upstream issues 1–4 (and 5
      if confirmed) at adafruit/circuitpython + the jd79667 debug prints.
* [ ] Node ↔ collector: verify ESP-NOW discovery end-to-end on the bench
      (S3 node with SCD41 → BASE597BE4), incl. stash retransmission after
      a collector outage and hub-time retro-adjustment.
* [ ] Battery watermark test (unplug), calibration two-step test.
* [ ] QT Py S3 + 2.9" tri-color HIL rig bring-up (profile `tri_2in9`).
* [ ] GitHub Pages deploy of `webapp/` + web-BLE against the S3 node/hub.
* [ ] Adafruit IO upload of averaged subsets (future).
* [ ] Wire the eInk BUSY line (D7?) on a future revision — with no busy
      pin the driver flies blind through 20 s refreshes.
