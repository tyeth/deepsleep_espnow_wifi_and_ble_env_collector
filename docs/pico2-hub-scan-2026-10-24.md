# Pico 2 hub scan: argument and identity fixes, bounded application pass

The actual Pico 2 W hub boot exposed an application API-contract bug:
`net_blescan.AdvReceiver.poll()` passed the advertisement prefix positionally,
but `_bleio.Adapter.start_scan` accepts keyword arguments only. It now passes
`prefixes=envadv.PREFIX`. The regression fixture uses a keyword-only adapter,
tests decoding/deduplication, throttle and generator cleanup, and injected
errors. The previous source fails all three tests (two failures, one error);
the fix passes all three. The existing 50 protocol checks also pass.

```sh
python tools/test_net_blescan.py
python tools/test_net_blescan.py /path/to/baseline/net_blescan.py
python tools/test_envadv.py
```

The physical rerun gets past the TypeError but exposes another failure:
`BLE scan failed: OSError: [Errno 22] Invalid argument`. That earlier run remains **failed**. The later identity fix and bounded hub
pass are documented below.

## Actual hub startup

The application base is `415710c80b3c` with the one-line scanner patch above.
CircuitPython is `5f73172d46cd`, Zephyr `c6200e80ea69`, HAL Infineon
`7f93dc606751`, and HAL Pico `de12fc2a0f75`. Forty-four files are uploaded
and compared byte-for-byte after readback, including compiled application,
Adafruit BLE 10.1.3, and SEN6x 1.1.0 modules. A real MCU reset and changed USB
device number are checked before capturing the application boot.

Both unpatched and patched boots reach AP active, HTTP listener on port 80,
HTTPS listener using the retained certificate, BLE UART advertising, and
the collector loop. Free heap after scanner creation is 85,424 bytes.
The unpatched scanner reports the positional-argument TypeError; the patched
scanner reports errno 22. Missing I2C sensors and a read-only boot-status
write are recorded separately. These bare-board jobs do not qualify a sensor
rig, persistence, TLS client access, browser assets or API responses. The
boot guard stopped before any HTTP requests in both runs.

The first two attempts failed in the harness before application boot:
`bytes(nvm)` was not iterable (use a slice), then `hashlib.sha256` was absent.
The third attempt also missed an early boot marker during USB reattachment;
its independent scan TypeError is retained. All four jobs remain failed.
Each restores the exact complete pretest 4 MiB image, verifies original
`9e153ad624`, original files and BLE identity, and passes a radio check.
Imports are detached, the original off state is restored, and the bridge
does not reset. This full-image policy intentionally discards temporary
application, NVM and filesystem changes. Private backups remain private.

## Smaller radio controls pass on both images

The same board passes 24 raw scan controls on original `9e153ad624` and 24 on
candidate `5f73172d46cd`. The original control changes no firmware or files;
the candidate uses a temporary verified image and exact full original restore.
The candidate's post-restore Wi-Fi/BLE counts are 68/56.

Each image exercises no advertising, nonconnectable advertising, connectable
advertising, AP plus connectable advertising, AP without advertising, and
after stopping the AP. Each state uses both 100 ms and 50 ms windows, with
an empty prefix or the exact Env Hub manufacturer prefix. All use a 100 ms
interval, one-second timeout, 512-byte buffer, RSSI floor -100, and passive scan.

```python
results = _bleio.adapter.start_scan(
    prefixes=bytes([4, 255, 255, 255, 231]), buffer_size=512,
    timeout=1.0, interval=0.1, window=0.1, minimum_rssi=-100,
    active=False)
try:
    count = sum(1 for entry in results)
finally:
    _bleio.adapter.stop_scan()
```

Original scans finish in 1.018–1.041 seconds; candidate scans in
1.022–1.041 seconds. Unfiltered scans receive 10–31 and 7–34 advertisements
respectively. Every filtered control receives zero matching node packets:
these controls qualify scan startup and deadline behavior, not Env Hub delivery.
The original and candidate CircuitPython adapter sources are identical;
this statement does not equate their complete dependency/build histories.

These passes rule out a universal inability to scan with advertising and an
AP under this small workload. They do not explain the full application's
errno 22. The inspected Zephyr parameter checks accept the stated passive
settings, and lower address/HCI errors can propagate through the same Python
exception. Neither a firmware regression nor a controller limitation is proven.
Further diagnosis must capture the full application's actual input and failing
stage. The JSON companion retains every raw matrix case, job status, restore
checks and hashes of the complete private records.

## Instrumented full hub: exact scan call fails while APIs respond

A fifth temporary application boot adds diagnostic output without a radio
workaround. It records these exact first-scan values:

```text
BLE_SCAN_INPUT 1.0 5.0 -100 04ffffffe7 True True False
BLE scan failed: OSError: [Errno 22] Invalid argument
BLE_SCAN_FAILURE_STAGE start_scan
```

The traceback points to `start_scan`, before consuming its iterator. Values
are scan seconds, scan period, RSSI floor, prefix bytes, adapter enabled,
advertising, and connected. This narrows the failure to starting the scan with
the expected inputs; it does not distinguish host validation, address setup,
or a controller-command error. The 48 passing raw controls remain distinct.

In this diagnostic the harness continues to test the HTTP APIs after recording
the scan error. `/api/config`, `/api/latest`, `/api/battery`, and `/api/cert`
each return HTTP 200 and valid JSON in three cycles (12 checks). Every latest
response reports `ble_rx: 0` and `ble_err: OSError: [Errno 22] Invalid argument`.
These are successful HTTP subchecks, **not** working BLE reception or an overall
application pass. Browser assets and HTTPS client trust were not tested here.

The main job remains failed. It records both the scan failure and a network
cleanup assertion after deleting its temporary connection profile. Its original
4 MiB flash is restored exactly, original files/version/identity are checked,
Wi-Fi/BLE counts are 60/71, imports are detached, the Pico is off, and the bridge
has not reset. A separate read-only postflight confirms Wi-Fi disconnected, the
temporary profile absent, the management route unchanged, no active test units
or imports, and the baseline device/port state. No recovery mutation is needed.
The initial network assertion's observed state was not saved, so its cause is
not established merely by the later clean result.

## Controller trace and reduced ordering reproduction

[Zephyr #12](https://github.com/tyeth/zephyr/issues/12) now tracks the distinct
scan-start failure. A temporary trace-only image built from the same pinned
sources shows callback registration, host validation, address selection and
LE Set Scan Parameters complete, then **LE Set Scan Enable (0x200c)** returns
controller status **0x12** (`BT_HCI_ERR_INVALID_PARAM`). Zephyr maps it to errno22.
The full hub records eight identical failures. This sixth hub job also fails
to join its AP (NetworkManager reports missing key-management configuration),
so it performs no HTTP requests. Do not reuse the fifth run's twelve HTTP passes
as sixth-run results.

The sixth run loses USB while reading runtime descriptors during the transition
to ROM, before writing the original image. It remains a failed job. Separate
recovery restores the complete original 4 MiB byte-for-byte, verifies original
files/version/identity and three Wi-Fi/BLE pairs (62/74, 59/80, 66/81), detaches
imports and powers the Pico off without resetting the bridge. A separate
read-only postflight verifies the network and baseline inventory.

A smaller three-file reproduction removes the hub, Wi-Fi imports and GATT
libraries. After MCU reset with `CIRCUITPY_BLE_WORKFLOW=false`, it observes a
public identity (`address.type == 0`) and runs:

| Sequence | Result | Reports | Time |
|---|---|---:|---:|
| Connectable advertisement before first scan; 0.1 s window | errno22 | — | 0.017 s |
| Same advertisement; 0.05 s window | errno22 | — | 0.017 s |
| Stop advertising, then scan | pass | 22 | 1.029 s |
| Restart same advertisement, then scan | pass | 18 | 1.022 s |

All four calls use a 0.1 s interval, passive scanning and a one-second timeout.
The trace selects scanner address type 1 (random) for all four. The first two
receive HCI status0x12; the last two receive status0. The exact tested
[code.py reproduction](../tools/reproduce_zephyr_scan_order.py) includes console
capture markers. The diagnostic completes and restores the original full flash
exactly, followed by original files/version/identity, Wi-Fi/BLE65/73, off/detach
and another independent baseline postflight. A completed diagnostic does not
turn its first two observed scan failures into passes.

This explains why the earlier 48-case controls did not cover the failure:
they scanned before starting connectable advertising. The suspected source
mismatch is in Zephyr's identity tracking: without privacy, connectable
advertising implicitly uses the identity, while legacy scan address selection
recognizes only the explicitly set identity flag. Existing unit tests cover
public identity with the explicit flag, not this implicit case. This was the working source hypothesis at that stage. The later candidate
comparison below validates the fix; scan priming is not a production workaround.

The first diagnostic build failed at link time because instrumentation was
applied to a separate Zephyr clone. That failure is preserved. The successful
build resolves the actual west checkout, verifies its original source bytes,
exports exact artifact hashes and restores all temporary source edits.

## Validated identity fix and bounded hub pass

[Zephyr PR #11, commit 5bf4230](https://github.com/tyeth/zephyr/pull/11/commits/5bf4230db7fe1e6b27bd866cf1691ff54ac5099d)
now tracks the identity actually used by connectable advertising when privacy is
disabled. Legacy scanning reuses the active advertiser's identity, including a
nondefault identity, instead of assuming identity zero. Explicit privacy and
NRPA choices retain their existing paths. This fixes the observed first-use
public-advertiser/random-scanner mismatch; no scan-priming workaround is added.

The new nondefault-identity unit case fails against the original `id.c` and
passes with the fix. Across five executed configurations, baseline is 19 pass,
1 fail, 35 skip; candidate is 20 pass, 0 fail, 35 skip (none build-only).
Run from the Zephyr checkout with its supported toolchain/environment:

```sh
west twister -T tests/bluetooth/host/id/bt_id_set_scan_own_addr -p unit_testing --inline-logs
```

These unit tests compile `id.c`, not the real advertising implementation.
Physical default-public-identity tests below exercise the actual advertising
path; nondefault identities and privacy modes have unit coverage, not equivalent
physical qualification. The review commit differs from the tested source only
in whitespace/comments; its C tokens are identical and checkpatch reports no
errors or warnings.

The first candidate attempt fails during original-firmware preflight before
any backup, firmware install or filesystem write. A separate no-write startup
control passes six identity/Wi-Fi/BLE commands; it does not establish the
timeout's cause. The next minimal diagnostic records four successful scan
cases (18, 16, 22, 19 reports; address types 0, 0, 1, 0; HCI status zero), but
misses the initial `SCAN_ORDER_BEGIN` capture marker. That job remains **failed**,
despite observing the address-selection correction. Its original full flash,
files, identity and radios are restored, and independent postflight passes.

The subsequent **full hub v8 job passes** on the revised diagnostic image
`b89064c3030f1f367a43f8d235af64a831a8d009c0bb826261f6ecd226dbc671`
(1,209,612 bytes). It uses CP `5f73172d46cd`, Zephyr base `c6200e80ea69` plus
the identity fix and tracing, HAL Infineon `7f93dc606751`, HAL Pico
`de12fc2a0f75`, and the same 44-file application payload. All files match after
readback. A real MCU reset reaches AP, HTTP/HTTPS listeners, BLE UART and the
collector loop. Twelve scan starts use public address type 0 with HCI status 0;
twelve HTTP requests return valid JSON (config/latest/battery/cert, three rounds).
All three captured scanner API states have `ble_rx: 0` and omit `ble_err`.

The original 4,194,304-byte flash is restored byte-for-byte, followed by original
files/version/identity and Wi-Fi/BLE counts 63/85. Temporary networking is
removed, imports detached and original power state restored without a bridge
reset. Two independent read-only postflights pass. Earlier failed jobs retain
their statuses. The prepared v7 helper was never run.

This establishes bounded hub startup, scan-start and HTTP behavior. It does
not establish node-to-hub packet delivery, real sensors, display, SD storage,
physical privacy/nondefault identities, TLS-client validation or a long soak.
The boot capture notes absent I2C/SPI peripherals and ends with a lone partial
`E` after its final complete scan line; no later output is inferred. At this
test, CP's manifest still pins the old Zephyr base; integration and normal-image
builds must be recorded separately from this diagnostic result.

## Normal integration builds

CircuitPython [PR #32](https://github.com/tyeth/circuitpython/pull/32) at
`3254e272628ea1c08977cd753dda8762e8951ac2` now pins the reviewed Zephyr
`5bf4230db7fe1e6b27bd866cf1691ff54ac5099d`. Both normal builds pass with the
actual clean dependency checkouts verified before and after. ELF inspection
confirms the automatic BLE startup/file-transfer/serial workflow symbols and
the absence of scan tracing and forced-error hooks.

| Normal image | Bytes | SHA-256 |
|---|---:|---|
| Pico W | 1,252,848 | `1a0a5bdbbfd69f5c6ef987d074e391e27eb1e03409b676e090319462e047c6be` |
| Pico 2 W | 1,209,228 | `2c6bfb34138e7d9195f495d66fb35dd1ddaf8024e264ea8af165c2715b1cfd89` |

At this stage these were build results; the physical hub run above used the
separately pinned trace image. The later [normal-image paired test](pico-paired-overair-2026-10-24.md)
now verifies actual node reception, twelve HTTP checks and complete restoration. Both production Picos retain
their restored `9e153` images while the independent USB reliability issues
remain open. Machine-readable evidence includes ELF/map/config and log hashes.
