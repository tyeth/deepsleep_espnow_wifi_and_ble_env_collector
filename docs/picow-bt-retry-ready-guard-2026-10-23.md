# Pico W Bluetooth retry: ready-firmware download guard

The unfaulted original diagnostic starts normally, but one forced ready-stage
error followed by retry is sufficient to reproduce the fatal HCI address-read
timeout. A narrow guard that skips patch-RAM download when the controller already
reports firmware-ready passes the original three-error sequence and a separate
unfaulted-start control. This is a tested candidate, not a production rollout.

## Matched evidence

All controls use CP `6839890534`, Zephyr `c6200e80ea`, HAL Infineon `7f93dc6067`
and HAL Pico `725e9e429e`, with temporary automatic BLE workflows disabled.
The original image is `0e6e568a`; the guard image is `f44ef03f`.
Full hashes and exact [sanitized results](picow-bt-retry-ready-guard-2026-10-23.json)
are retained. No reset occurs between errors and retry within each test.

| Control | Outcome |
|---|---|
| Original diagnostic, no injection | First startup passes; counters `(1,0,0,0,0,0,1,1,True)`; same identity; BLE scans 78/68/74 |
| Original diagnostic, one ready error | Expected EIO (5), Wi-Fi scan 58; next clean import halts |
| Original diagnostic, three errors | Earlier failed run retained; all error returns pass but final retry halts |
| Guard candidate, three errors | EIO/ETIMEDOUT/ETIMEDOUT, Wi-Fi scans 65/63/71; clean retry passes, same identity, BLE scans 80/88/86 |
| Guard candidate, no injection | First startup and three BLE scans pass; counts recorded in JSON |

The single-error no-reset SWD capture reaches the same exact-ELF HCI
`Read_BD_ADDR` (`0x1009`) timeout assertion as the earlier three-error run.
The saved PSP frame has PC `0x10014e24`, immediately after its `svc 2`;
the caller resolves to `hci_cyw43_setup`. HAL counters are
`(2,1,0,3,0,179,2,1)`: the second transport initialization completed, after
downloading firmware again. This is not evidence for a NULL work handler.

## What changes

The original init path always downloads patch RAM, even when a previous attempt
already reached firmware-ready and only failed later. The candidate wraps the
download/temporary-buffer allocation and cleanup in `if (!cybt_ready())`.
It still polls ready, initializes rings, waits for awake, and announces host-ready.
It uses the current controller register, not a permanent software cached flag.

After three forced errors the candidate's final counters are
`(4,3,0,5,0,179,1,1,True)`: four attempts and only one firmware download.
The matched failure/pass comparison supports avoiding repeated download as a
fix for this reproduction. It does not establish every internal controller
failure mechanism or qualify actual electrical faults. The hooks force software
returns only after the real hardware operation succeeds.

Twelve native exact-function ready/error cases, including two retries, pass
with UBSan. Eight flash transaction controls cover protected-region preservation,
write/readback failure, rollback and recovery-required outcomes. The
[deterministic source transformer and target probes](../tools/repro_picow_bt_startup/README.md)
recreate the tested candidate from the published original diagnostic patch.
The transformer output hash matches the physically tested HAL source.

## Restoration and remaining work

The failed single-error test remains failed. Its absent console prevented
automatic restoration; an independent no-reset capture and subsequent SWD
restore recovered original 9e153 code with full expected-image verification and
three radio checks. Both successful candidate controls also restore original
code, verify the complete expected image, pass radio checks, restore bindings,
and leave the S31 untouched. Full images are not claimed bit-identical to
pretest backups because runtime build-version metadata changed.

Production HAL integration, normal automatic BLE workflows, Pico 2 retry
qualification and natural hardware-fault recovery remain open. The separate
Pico console-close USB defect is not addressed by this guard. Both original
failed runs and private recovery captures are preserved.


Follow-up: the guard is now in HAL #8 and CP #32. Both Pico boards pass
[normal production-build startup checks](pico-normal-ble-ready-guard-2026-10-23.md),
with verified original-code restoration. Two earlier Pico 2 original-firmware
preflight failures remain preserved and unexplained. Pico 2 forced-error retries
and natural hardware faults remain outside that pass.
