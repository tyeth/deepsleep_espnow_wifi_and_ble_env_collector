# Legacy BLE scan timeout — direct hardware reproduction

Pico 2 W reproduces [Zephyr fork issue 9](https://github.com/tyeth/zephyr/issues/9)
in a standalone Zephyr diagnostic, without CircuitPython's interpreter or its
host-side deadline workaround. Two requests for a three-second scan returned
success and continued delivering reports after six seconds. Neither called
the timeout callback. An unlimited-scan control behaved similarly. Explicit
stop succeeded and no new reports arrived during the post-stop observation.

| Case | Timeout (10 ms units) | Reports | Reports after 3.5 s | Timeout callbacks | Reports after stop settling |
|---:|---:|---:|---:|---:|---:|
| 0 | 300 | 58 | 23 | 0 | 0 |
| 1 | 0 | 54 | 23 | 0 | 0 |
| 2 | 300 | 57 | 26 | 0 | 0 |

Each case observed six one-second samples, called `bt_le_scan_stop()`, allowed
250 ms for in-flight delivery, then counted additional reports for 750 ms.
Scanning was passive, privacy disabled, with duplicate filtering disabled.
`CONFIG_BT_EXT_ADV=n` selected the legacy HCI path. Nearby advertisements
supplied the traffic; no packet payloads or device addresses are published.

## Source contract and current upstream

The hardware used Zephyr `7379648278`, HAL Pico `725e9e429e` and HAL Infineon
`7f93dc6067`. The standalone image is 413,456 bytes. Its configuration has no
filesystem or persistent Bluetooth settings enabled. The former CircuitPython
image's source revision identifies the integration workspace, not this
diagnostic's application runtime.

Current upstream `76280bce2a050376d57e14240687b5c283dea0e7` still documents a
[timeout callback](https://github.com/zephyrproject-rtos/zephyr/blob/76280bce2a050376d57e14240687b5c283dea0e7/include/zephyr/bluetooth/bluetooth.h#L2541)
without a legacy exception, while its
[legacy start function](https://github.com/zephyrproject-rtos/zephyr/blob/76280bce2a050376d57e14240687b5c283dea0e7/subsys/bluetooth/host/scan.c#L346)
does not use the timeout field. The tested and current functions are **not
byte-identical**: current source factors out scan filter policy and extends
option validation. This is a current-source finding plus a physical result
on the pinned integration; current upstream main was not flashed.

The existing CircuitPython host deadline remains necessary. This experiment
does not implement a Zephyr fix. The upstream API should either enforce the
deadline or explicitly reject a timed request that the selected path cannot
honour; silent acceptance is the reproduced problem.

## Firmware restoration and preserved failure

Installation used a fresh 4 MiB backup, bounded code-only writing and full
flash readback. Before Bluetooth was started, the independent serial ROM
command was tested and the diagnostic image read back exactly.

After all three successful reproductions, the automatic final ROM transition
did not complete, so the main job is recorded as failed. A separate recovery
waited for the complete console-ready banner, sent the ROM command while
keeping serial open, verified the installed image and restored production.
The final 4 MiB flash matched the original backup exactly, production identity
and three Wi-Fi/BLE cycles passed, and imports were detached. No bridge reset
was observed. The first transition's cause is not proved by that successful
recovery; the failed manifest and raw console remain preserved.

[Minimal reproducible application](../tools/repro_legacy_scan_timeout/README.md)
and [measured results, hashes and source comparison](legacy-ble-scan-timeout-2026-10-23.json).
