# Pico receive-lock failure investigation — 22 October 2026

The `a0c1485cf5` Pico W two-hour Wi-Fi/BLE soak **failed**, rather than completing.
It started at 15:51:33 UTC and failed at 17:02:09 UTC after 140 completed cycles
and 4,236.05 seconds. The next raw-REPL command acknowledged with `OK` but never
returned its result or end markers. The final completed cycle took 5.729 seconds
and saw 44 Wi-Fi networks and 24 BLE advertisements. There was no USB disconnect
in the inspected failure window. A subsequent passive read and one Ctrl-C
produced no output. Logs and original evidence remain preserved; the unavailable
SWD probe prevented a live RAM/thread capture.

The independent reporter rejects this run as failed and shorter than its
configured 7,200 seconds. Its status SHA256 is
`bafaa2841a50cfc0be9f3acc904bd85cee64ce443925185633c0db1ad3d08434`, and its
cycles SHA256 is `30c2441ba4b17d9f23de10d18ee0023effdfe94b79a3c41f5ca09e6aeae3ee0d`.

## Reproduced source defect

The CYW43 polling thread held the shared Wi-Fi/BLE bus mutex across host receive
buffer allocation and delivery. Allocation may wait indefinitely, while a
consumer that releases a buffer may itself need the bus. The new regression
compiles the actual polling, ring-check and receive functions with a competing
consumer thread. A bounded lock attempt exposes the circular wait without
hanging the test runner.

Seven of twelve cases fail on Zephyr `353bcd30f7`. All twelve pass with
`7379648278ab49e391af00f1a62ec73387d4c519`: controller ring checks and reads stay
locked, while host allocation and delivery occur after unlocking. Error exits,
discardable advertising reports, ACL/ISO packets and the 32-packet drain bound
are covered. The existing 25 bus-wake checks pass; checkpatch reports no errors
or warnings. Both new ELFs independently show the corrected lock/unlock order.

Minimal reproduction, from the integration Zephyr checkout:

```sh
python3 tests/drivers/bluetooth/cyw43_rx_bus_contention.py --root . --baseline 353bcd30f76e1fa140291540dde20334e952e0e6
python3 tests/drivers/bluetooth/cyw43_rx_bus_contention.py --root .
```

The first invocation is expected to fail. This proves a driver lock-contract
defect; it does **not** establish that this exact path caused the physical stall.
The fix is in [Zephyr PR 11](https://github.com/tyeth/zephyr/pull/11), pinned by
[CircuitPython PR 32](https://github.com/tyeth/circuitpython/pull/32).

## Current integration validation

The exact `7d4ef1aac7` / `7379648278` integration was rebuilt and tested after
the receive-lock fix. All ten BLE scan cases pass across the nRF5340 and
nRF54LM20 simulators (39.54 seconds): beacon reception, reload, entry properties,
passive scanning, and preserving an active scan after an unsupported extended
request. All 85 build-tool tests pass (1.20 seconds). Actual checkout pins and
tracked cleanliness were checked before and after, with empty `CP_VERSION`.
See the [command, pins and log digest](pico-rx-integration-tests-2026-10-22.json).
These Nordic simulator checks cover integration behavior; they do not exercise
the CYW43 hardware driver or replace physical qualification.

## New candidate and physical checks

CircuitPython `7d4ef1aac72bf322f1bcead966a8d3eac0acb2af` selects Zephyr
`7379648278ab49e391af00f1a62ec73387d4c519`, HAL Infineon `7f93dc6067` and HAL
RPi Pico `725e9e429e`. Actual clean build checkouts match all manifest pins.
Both boards build with empty `CP_VERSION`; the version falls back to Git.

| Board | BIN bytes | Static RAM bytes | BIN SHA256 |
|---|---:|---:|---|
| Pico W | 1,252,392 | 208,208 | `827d391a777aba31bb9d029d5d7ca6ec3e6b9379448a14dbbe3ebce864883ce2` |
| Pico 2 W | 1,208,788 | 275,756 | `f29892f2a02922090ecde2d4841907ef779ea0c7838590f90d2ea65ec7ad8f52` |

The failed Pico W was recovered using its supported 1200-baud USB bootloader
entry. Its immediate private 2 MiB backup matched the expected old firmware.
Programming, full readback and unchanged bytes beyond the programmed sectors
passed. No shared hub or other DUT was reset. The failed run remains failed.

Physical preflight passed at 17:25:43 UTC: exact new runtime identity, retained
BLE address, 223 advertisements on the original scan after extended-mode
rejection, 226 on a later ordinary scan, Wi-Fi connection, trusted TLS with 55
BLE advertisements, and wrong-hostname rejection. This is Pico W proof only;
Pico 2 W is built and staged, not physically qualified.

The **new two-hour soak passed**: 17:26:05–19:26:05 UTC, 7,200 seconds and
240 Wi-Fi/BLE scan cycles. A separate read-only verification at 19:27 UTC
confirmed the stopped successful service, pinned run/preflight/firmware identity,
matching logs and status, complete duration, and unchanged failed predecessor.
There were no recorded failures or inconsistent evidence. Cycle times ranged
from 5.706 to 6.622 seconds; the largest cycle gap was 30.77 seconds. Every
cycle found Wi-Fi networks (31–80) and BLE advertisements (23–26).

GC allocated bytes ranged from 2,032 to 2,208, ending 16 bytes below the first
sample. The free-memory estimate ranged from 71,264 to 71,440 bytes. These are
observed port estimates, not a proof that all workloads are leak-free.
See the [independent report and evidence hashes](pico-rx-soak-pass-2026-10-22.json).
This is a two-hour Pico W result, not an eight-hour or Pico 2 W pass. It exceeds
the failed predecessor's 71 minutes but does not establish that stall's cause.

The three original eight-hour application, Feather and trusted-HTTPS runs also
passed independent terminal verification at 19:45 UTC: 236 deliveries/true
wakes, 960 Feather scan cycles and 240 HTTPS cycles. Their exact firmware
attribution and the single application startup HTTP error are documented in
[the completed soak report](completed-soaks-2026-10-22.md).

The revised portal rollout gate passed all three full eight-hour runs and the
new Pico two-hour run, including verification that the failed predecessor is
preserved. Subsequent portal/C61 updates require separate runtime checks.
Physical failure/retry injection, remaining board/USB/AP coverage and the final
upstream index remain separate work.
