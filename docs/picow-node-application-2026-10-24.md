# Pico W node application boot — 24 October 2026

The actual `code.py → nodegate.mpy → node_lite.mpy` application from
[PR #11](https://github.com/tyeth/deepsleep_espnow_wifi_and_ble_env_collector/pull/11)
head `aed85946600c7ddd1e44fc5055564a00bd0bc95f` runs on the physical Pico W
with CircuitPython `11.0.0-alpha.2-32-g9e153ad624`.

Two MCU resets each produced five reading/advertising/idle cycles. USB device
re-enumeration was asserted after each reset; this is not an electrical power-cycle
test. Both boots used the same board-derived payload identity. The node reported
77,616 bytes free at startup and 77,280–77,312 after readings. These are actual
`gc.mem_free()` observations, not total RAM capacity or maximum allocation sizes.
They supersede the historical ~19.6 KB estimate for this tested build/path.

The sensor was explicitly **simulated**. The configuration selected a five-second
interval, two-second advertisement window, no Wi-Fi fallback and the default
board-derived node ID. The source's normal entry point and loop were used; no
application control-flow patch was needed. Transmit API success is not proof
of over-air reception. This does not qualify Pico 2 hub startup, two-board identity
uniqueness, Wi-Fi POST, a real sensor, phone provisioning, or latest `0d545efdcf`
application runtime.

## Evidence and restoration

Both full 1,298-byte UART captures have SHA-256
`d87f8d980b0b8addf616ad7128528cea73c6621d23ada12e2fbc655e4b6dcc7f`.
Their identical contents include sequences 1–5, successful advertisement starts,
the synthetic-sensor notice and idle intervals. A sanitized transcript is linked
below; device identity is redacted there, so its hash differs.

The 520,704-byte filesystem was backed up twice before changes. All eight deployed
files were read back exactly. After testing, the entire original disk matched
SHA-256 `18d471d9170495a7fce4958d1b7103f73231a51533bdc365a4f8fb7957736977`.
Another MCU reset verified the original `Hello World!` application and firmware.
No firmware was written. Autoreload was restored and the bench had no remaining
lease. Private filesystem backups and complete transcripts are retained privately.

An earlier test remains **failed**: its assertion incorrectly inspected
`sys.modules` after CircuitPython had exited the application and cleared the VM
on entry to REPL. That boot still logged five actual advertisement cycles.
Its restoration first hit a busy-device guard; a separate restore then exposed
a real firmware defect: a multi-sector write starting at synthetic MBR LBA 0
was silently rejected. Only sectors 2, 5 and 6 differed (325 bytes). Partition-only
restoration produced an exact whole-disk match, followed by a separate successful
original-code check. One recovery wrapper also failed because its fixed three-second
USB enumeration wait was too short; the independent check passed after enumeration.
All these failed records remain preserved. The corrected successful transaction
uses partition-only writes and bounded enumeration polling.

The firmware defect is [CircuitPython #43](https://github.com/tyeth/circuitpython/issues/43),
with source pointers and a minimal reproduction. It is separate from #42 and
Pico 2/S31 transfer-size delays. No firmware fix is claimed here.

## Local integration checks

PR #11 was integrated into the refresh branch. Its sole conflict was I2C selection:
the result preserves both Zephyr devicetree buses and the C5 external-PSRAM pin guard.
The automatic certificate merge adds `caps.time` and retains the full-chain fix.

- 50 advertisement/identity/clock checks and 102 RTC checks pass on the host.
- All 19 collector and 15 node modules compile with the existing CircuitPython
  `mpy-cross`; `code.py` and `boot.py` deliberately remain source. Output totals
  are 90,202 and 48,972 bytes, respectively; compiled size is not runtime heap use.
- Existing certificate BLE, datastore sync, early config, protocol, HTTP headers,
  timezone and serial-deploy regression scripts pass. Certificate-renew initially
  failed because its isolated loader lacked the new `caps` dependency path;
  adding the real collector module path restores its passing regression test.
- The existing certificate failure reproduction still reproduces application #38;
  it remains an open defect, not a passing install path.

[Machine-readable result](picow-node-application-2026-10-24.json) ·
[Sanitized boot transcript](picow-node-application-2026-10-24.log)
