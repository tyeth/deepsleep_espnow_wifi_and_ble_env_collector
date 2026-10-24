# Direct Pico W USB recurrence — 23 October 2026

The final inventory check failed at 04:48 UTC because the directly attached
Pico W was absent. Kernel logs show repeated descriptor timeouts (`-110`),
address failures (`-71`, `-22`), temporary re-enumeration at 04:39:06, and failed
enumeration by 04:41:55. No direct Pico test or firmware operation was requested
during that interval. The exact onset and cause have not been established.

The S31 `bec1d71` API remained healthy, with uptime 708 seconds, its original
downstream Pico 2 inventory, no USB/IP imports and no active soak units. The
successful selective-interface comparison used that downstream Pico 2 and an S3;
this later inventory failure concerns a different Pico connected directly to
the host. It does not turn either recorded comparison into a broader USB pass.

A guarded ganged-hub off/on request restored the three expected direct USB
identities. The guard checked for active tests, imports, serial readers and
mounted downstream filesystems, and restored all affected ports to on.
Subsequent raw-REPL checks passed on Pico W `9e153ad624` and Feather ESP32 V2
`ea06dcb44e`. S31 uptime reached 922 seconds without a reset relative to the
previous snapshot. The S31 diagnostic UART was not opened.

The recovered Pico reported monotonic time 12,805.66 seconds; the Feather
reported 5.148 seconds. Do not infer a cold boot from the hub power status, or
assume UART line settings guarantee no MCU reset. No flash writes were part of
this recovery. The original failed inventory and kernel evidence are preserved.

USB/MSC and host-hub failure isolation remain open. The endpoint-capacity fix,
Pico station-lifecycle checks and older successful soaks retain their limited
scope; none proves this recurrence is resolved. Next targeted work should
separate CDC-only operation from MSC polling and capture the first failure,
before assigning the cause to firmware, stack size, the host or the hub.

See [sanitized result and private evidence hashes](picow-idle-usb-recurrence-2026-10-23.json).
