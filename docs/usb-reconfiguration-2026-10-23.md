# Pico 2 USB reconfiguration — 23 October 2026

**Reinitializing the active USB configuration plus rearming cancelled CDC
receives passes four ordinary Pico 2 MSC/CDC reconnects. Configuration reset
alone fails CDC; the failed candidate is retained below.**
Production was restored exactly afterward. The matched controls narrow the
single-import MSC failure separately from simultaneous endpoint capacity.
The same-configuration source defect is already tracked upstream as
[Zephyr #121843](https://github.com/zephyrproject-rtos/zephyr/issues/121843),
reported on STM32 before this Pico investigation; no duplicate issue is needed.

## Controlled results

Same Pico 2 CircuitPython `9e153ad624`, Zephyr `7379648278`, and bridge
`bec1d71`, with three physical hubs and three powered leaf devices. Only Pico 2
was imported. CDC was admitted first, then MSC; HID remained unauthorized.
Each successful MSC case made two matching uncached 4,096-byte reads from the
2,617,856-byte disk. No filesystem writes were requested.

| Control before each Linux import | Four MSC outcomes | CDC afterward |
|---|---|---|
| No extra session | Pass, pass, fail, fail | All pass |
| Extra session: clear endpoint halt on OUT 0x02 and IN 0x83 | Four passes | All pass |
| Matched extra session: get status of the same endpoints | Pass, fail, fail, fail | All pass |
| Repeat clear-halt control | Four passes | All pass |
| Configuration-only candidate, ordinary import | Not reached | First raw-REPL write times out |
| Combined reconfiguration + CDC rearm candidate, ordinary imports | Four passes | All pass |

The GET_STATUS control used the same extra import, two endpoint-directed
requests and 250 ms delay as the clear-halt control. Both endpoints reported
halt status zero before every attempt. This rules out the extra session alone
as the observed recovery mechanism. It does not directly measure wire toggles.

## Packet and source evidence

The failed baseline and GET_STATUS sessions accept the first 31-byte INQUIRY
CBW, but the subsequent 36-byte bulk IN request never completes before detach.
An earlier successful baseline reimport returns a 13-byte CSW in that data
request and succeeds only after retry. The first clear-halt capture returns
the proper 36-byte INQUIRY data and following 13-byte CSW in all four imports.

Every Linux import sends SET_CONFIGURATION(1) and receives success. The tested
Zephyr `sreq_set_configuration()` returns early when configuration 1 is already
active. That bypasses `usbd_config_set()` and its interface/endpoint reset.
The Pico UDC resets its next data PID when enabling an endpoint or clearing
endpoint halt. The MSC clear-halt callback does not perform a BOT reset; it
only reasserts an already-wedged endpoint. The bridge resets claimed host
endpoint toggles after these standard requests, and new claims start at DATA0.
Together these observations support the endpoint-state mismatch described by
the existing upstream report. No physical DATA0/DATA1 trace was taken.

The rejected diagnostic candidate changes only the same-configuration early return: repeated
nonzero configurations use the existing reset/re-enable path, while the
already-unconfigured zero case remains a no-op. Eleven actual-handler native
checks pass; the old source fails the repeated-selection and backend-error
propagation checks. These mocks validate dispatch and errors, not physical USB.

The physical candidate completes descriptor requests, SET_CONFIGURATION(1),
line coding and control-line-state requests, but the first raw-REPL write
times out. No MSC command is sent. Its capture has 62 commands, including
successful control requests and pending transfers subsequently unlinked.
This is a failed candidate, not a successful MSC fix. At this stage the configuration-only change was rejected. The combined
candidate below subsequently incorporates it with CDC cancellation rearming.

## Combined candidate: cancellation rearm closes the bounded failure

The second candidate adds only a CDC completion change to the configuration
candidate: on an OUT cancellation (`-ECONNABORTED`), return the transfer buffer
before submitting RX work again. Other completion errors keep their existing
handling. The receive worker still enforces enabled/suspended and space gates.
This addresses the enable-before-old-cancellation ordering: enable can find
RX busy, then the old completion clears busy without another receive trigger.
The related source defect is already described by
[Zephyr #122768](https://github.com/zephyrproject-rtos/zephyr/issues/122768).

Twelve actual-completion-handler checks pass; the old source fails the two
cancellation-rearm checks. The combined diagnostic then passes four ordinary
imports without extra clear-halt sessions. Every import has working CDC before
and after MSC and two matching uncached 4 KiB reads. The packet capture confirms
36-byte first-INQUIRY data followed by its 13-byte CSW with tag 1 every time,
so the pass is not hiding the earlier first-command anomaly behind a retry.

Combined image: 1,209,068 bytes, SHA-256
`912447bc7a048477cb0e7511b272cf314a920c8c127a9e59311963c4d3b93b24`.
The configuration hash is identical to the first candidate. Full production
flash was restored exactly; three Wi-Fi/BLE checks passed afterward. The new
commits carry the exact tested source changes in [Zephyr draft #11](https://github.com/tyeth/zephyr/pull/11):
CDC `83219a3ef462e38b9ee76e34dcbb8c2ce255c406`, then configuration
`c6200e80ea6973b092da3c30c672901cc1951fc2`. [CircuitPython draft #32](https://github.com/tyeth/circuitpython/pull/32)
pins them at `6839890534556b06b8b3d7c491e36fd2005b2483`.
Installed production remains the restored `9e153ad624` baseline. This is bounded
Pico 2 qualification, not production rollout, Pico W hardware coverage, or a
long-term reconfiguration/resource-leak result. Full RX retry, suspend/resume,
other completion errors and class shutdown ordering remain outside this fix.

## Provenance and recovery

The candidate is 1,209,028 bytes, SHA-256
`fd46449b5cfacae2ffe5057bb10f88d37a31490a4b94283a6d951d76add4d443`.
The build uses the same CP/Zephyr/HAL pins as production plus the recorded
source patch. The source checkout was restored after building. A fresh full
4 MiB backup preceded a code-region-only update; full-flash readback verified
the diagnostic, followed by an unconditional verified production restoration
and three Wi-Fi/BLE checks. Exact restoration details and artifact hashes are
in the adjacent JSON. Imports, temporary leaf power and authorization defaults
were restored; the C6 remained untouched and the bridge was not rebooted.

Raw captures contain disk and console data and remain private. The strict
USB/IP decoder has six host controls for reassembly, gaps/conflicting overlap,
reply direction, short payloads and unmatched responses. Its results are
protocol evidence, not a substitute for a physical USB analyzer.

The first capture job failed only during PID-file cleanup after two successful
MSC reads; a separate verified cleanup stopped the exact capture process.
That failed record is retained. Later captures fixed the PID-file permission
handling. Neither the intermittently successful baseline nor the workaround
is described as a permanent fix.

## Reproduce

Use the [actual-source harness and candidate patch](../tools/repro_usbd_reconfigure/).
For the physical case, keep hub/device population and firmware fixed, import
the Pico repeatedly with CDC admitted before MSC, read an unmounted disk twice,
check CDC afterward, and detach between rounds. Capture USB/IP TCP traffic to
verify repeated SET_CONFIGURATION and the first INQUIRY exchange. Compare the
same extra control-only session with GET_STATUS versus CLEAR_FEATURE for the
two descriptor-derived MSC endpoints. Keep failed runs and restoration evidence.

This result does not close idle USB failures, mounted-file writes, full composite
endpoint capacity, or long-term reconfiguration/resource-leak checks. The
configuration-only candidate failed qualification. The combined candidate passes the bounded test, but is not deployed as production.

Both production variants build at the new CP/Zephyr pins with clean actual
checkouts verified before and after. Embedded binaries identify CP `6839890534`.
The actual Pico W build subsequently passes a direct-host baseline/candidate
comparison and is restored afterward. See [the direct Pico W result](picow-usb-reconfiguration-2026-10-23.md)
and [build manifest](firmware-pico-usb-683989-2026-10-23.json). Production rollout remains pending.
