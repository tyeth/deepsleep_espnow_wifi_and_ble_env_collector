# Actual Pico W node to normal Pico 2 hub: bounded BLE reception

The paired experiment passes on the **normal** Pico 2 image from CircuitPython
`3254e272628ea1c08977cd753dda8762e8951ac2`, Zephyr
`5bf4230db7fe1e6b27bd866cf1691ff54ac5099d`. Its 1,209,228-byte binary SHA-256 is
`2c6bfb34138e7d9195f495d66fb35dd1ddaf8024e264ea8af165c2715b1cfd89`.
The Pico W runs the actual node application on its original `9e153ad624`
firmware, using explicitly labelled **simulated** sensor readings, a 10-second
interval, nine-second advertising windows and no Wi-Fi fallback.

Eight node files and 44 hub files are verified exactly after deployment.
A real hub MCU reset reaches AP, HTTP/HTTPS listeners, BLE UART and the
collector loop. Twelve HTTP JSON requests pass: config/latest/battery/cert,
three rounds. Three latest-reading samples match captured node UART sequences
36, 37 and 38 after wire quantization, including changing metric values, type
`sim` and RSSI -54/-56/-41. Scanner receive counts are 4/5/6 with no `ble_err`.
This proves actual node advertisement reception, decoding and HTTP API exposure;
BLE broadcast has no acknowledgement, so it does not prove sender confirmation.
The normal firmware has no HCI tracing or forced-error hooks. The same application
payload used by the prior diagnostic retains its first-scan Python input print.

## Preserved failed predecessors and original-firmware limit

- The first attempt fails in the node harness during USB re-enumeration. Its
  immediate restoration also fails while the serial path is absent. A separate
  recovery restores all 520,704 original disk bytes and verifies original code.
  The harness subsequently waits for the exact expected by-id identity, without
  treating a temporarily absent console as a permanent identity mismatch.
- The next attempt stops at the original Pico 2's combined identity/radio
  preflight, before candidate installation. The node logs eight advertisements
  and restores exactly.
- Separating the original preflight commands then localizes the timeout to
  `import wifi`, after the identity command succeeds. A separate no-sender
  control reproduces the same timeout. Both captures receive raw-REPL `OK` but
  no end-of-transmission marker. These runs write no hub firmware or files and
  restore imports/power. The sender is not required for the timeout; its cause
  remains unknown. Earlier original-firmware controls also passed, so no stable
  failure-rate or root-cause claim follows.

Minimal observation on the affected original build: enter raw REPL, execute
`import sys, board; print(sys.version, board.board_id)`, then execute
`import wifi; print("WIFI_IMPORTED")` and retain the raw response. The identity
command completes; the Wi-Fi command receives `OK` without completion within
25 seconds in these controls. Do not equate this automatically with CP #42's
closed-console MSC stall.

For the successful normal-image experiment, the original preflight uses exact
USB/board/version identity and the known full-flash SHA-256, rather than repeating
the independently failing radio import. The complete 4 MiB backup matches the
known original before any candidate write; code installation and complete
expected-image readback pass before application deployment.

## Restoration and qualification limits

The original Pico 2 4,194,304-byte flash is restored byte-for-byte, with original
board/version and files verified. The node's complete 520,704-byte disk is also
restored exactly, followed by original code/version/autoreload verification.
Temporary networking is removed, imports detached and original port state
restored without restarting the bridge; independent read-only postflight passes.
Original **radio health is not certified** by restoration: the known Wi-Fi-import
timeout above is retained, and the result uses `runtime_identity_restored`, not
a radio-health pass. Both Picos retain original `9e153` firmware after the test.

The boot reports no I2C bus, no local sensor, no SD card, an unsynchronized clock
and RAM storage. A boot-status write fails on the intentionally read-only test
filesystem. Display is disabled. This is not real SCD41/RTC/display/SD coverage,
outage replay, multi-sender stress, battery/deep-sleep testing or a long soak.
HTTPS listener startup is observed; these twelve requests use HTTP and do not
add TLS qualification. The new normal Pico W image remains build-only in this
experiment. Earlier eight-hour passes retain their original build attribution.

See [machine-readable evidence](pico-paired-overair-2026-10-24.json),
[the scan identity comparison](pico2-hub-scan-2026-10-24.md), and
[the complete coverage ledger](issue-investigation-coverage-2026-10-22.md).
