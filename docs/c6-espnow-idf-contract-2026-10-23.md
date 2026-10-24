# ESP-NOW default-peer behavior — standalone C6 reproduction

The broadcast-only `send(payload, None)` failure is reproduced without
CircuitPython, in a standalone ESP-IDF C app on the same Feather C6. Treat
this as an API documentation discrepancy, not evidence of a new CircuitPython
radio regression or a defect in the receive-buffer synchronization fix.

| Registered peers | NULL before / after explicit calls | Explicit calls |
|---|---|---|
| Broadcast only | `ESP_ERR_ESPNOW_NOT_FOUND` (0x3069), all six calls | Broadcast accepted, all three calls |
| Synthetic unicast only | Accepted, all six calls | Unicast accepted, all three calls |
| Broadcast plus synthetic unicast | Accepted, all six calls | Both explicit addresses accepted, all six calls |

The final paced, buffered capture contains all 30 records across three rounds.
IDF is `29d36039e564db6df505d0582b94b230a17e63f3`; the 872,576-byte diagnostic
image has SHA-256 `925eb18053b5eedd183e11597e9323c3c086b2b5816b048e5f252a27b15bac32`.
There was no BLE, HTTP server, frozen Python library or CircuitPython runtime
in this test. Submission acceptance does not establish delivery. In particular,
the recipients of mixed-list NULL calls were not independently captured.

[MicroPython explicitly documents](https://docs.micropython.org/en/latest/library/espnow.html#broadcast-and-multicast)
that its omitted-address send excludes broadcast and multicast destinations.
The [pinned IDF header](https://github.com/espressif/esp-idf/blob/29d36039e564db6df505d0582b94b230a17e63f3/components/esp_wifi/include/esp_now.h)
still describes NULL as all registered peers, as did the CircuitPython binding.
CircuitPython passes NULL through unchanged. The [documentation correction](https://github.com/tyeth-ai-assisted/circuitpython/commit/e46718f34b321ae8021a19b99d80b45bdcd2a3a7)
in the ESP integration documents the unicast-only default and requires an explicit
registered broadcast/multicast peer. No IDF implementation change or version
regression is claimed; an IDF documentation clarification remains upstreamable.

The diagnostic replaced only application sectors after a fresh 4 MiB backup
and device digest verification in the same bootloader session. It then restored
the original sectors, verified the whole 4 MiB against that backup, rebooted
and confirmed the expected `ea06dcb44e` CircuitPython runtime. No USB imports
remained. Six host failure controls cover partial-write failure, capture
failure, stale preimage, bad backup/bounds, restoration failure and normal
sector-tail/protected-region preservation.

Earlier failures remain separate: the first attempt refused to write because
flash changed after an intervening normal boot; a fresh comparison confined
the differences to NVS, with no application or filesystem difference. The
second ran the C-only test but missed two opening records, so its strict
capture check failed. Its two complete later rounds reproduced the same
behavior, and whole-flash restoration plus runtime verification passed.
A third USB interrupt-console variant panicked before valid radio results;
whole-flash restoration and runtime verification also passed. Its exact ELF
and logs are preserved; a saved address resolves to the USB Serial/JTAG ISR,
but the root cause is unproved. The final probe keeps the original polling
console and buffers measurements for a paced dump after radio shutdown.
Private backups and raw logs remain retained. No latest-IDF or other-chip
hardware coverage is inferred from this C6 result.

[Standalone reproduction](../tools/repro_espnow_default_peer/README.md) ·
[Machine-readable results](c6-espnow-idf-contract-2026-10-23.json).
