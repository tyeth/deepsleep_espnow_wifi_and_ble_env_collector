# Pico W Bluetooth startup error-return reproduction

This is diagnostic instrumentation, not a proposed production patch. It reproduces
the [physical failed retry](../../docs/picow-bt-startup-failure-2026-10-23.md).

Use CircuitPython `6839890534556b06b8b3d7c491e36fd2005b2483`, Zephyr
`c6200e80ea6973b092da3c30c672901cc1951fc2`, HAL Infineon
`7f93dc60675126a63358ffa0780648d94fd2d634`, and HAL Pico
`725e9e429eab65eda01762a1af9016426dee00ac`. These are the fork integration
revisions in CP #32 / Zephyr #11, not stock upstream firmware.

1. In a clean disposable checkout with these exact dependencies, apply
   `patch -p1 < /path/to/diagnostic.patch` from the CircuitPython root. The patch
   also changes the nested HAL checkout. Build the Pico W Zephyr board using
   the checkout's configured toolchain and dependencies; retain the ELF.
2. Back up the device and have an independent SWD/ROM recovery path ready.
   Install the raw `zephyr.bin` through the board's supported flasher, preserving
   its storage layout. Do not confuse the compressed update package with a raw
   flash image. This test has halted a real board and required SWD restoration.
3. From a fresh boot, execute `probe.py` in one REPL session with no soft reset
   between sections. The recorded run submitted each of the five top-level
   sections separately, preserving output after each; the final import halted.
   Do not import `_bleio` before the initial assertion. The patch disables
   automatic BLE file/serial workflows so application imports initiate startup.
4. Stages 3/4/5 replace a successful ready/buffer-init/awake return with
   `CYBT_ERR_TIMEOUT`, once per arm. This forces software error returns after
   real hardware work; it does not create electrical faults or actual timeouts
   in those three operations. Expected Python errno values come from the target.
5. Require the fourth unarmed import to succeed, retain the expected identity,
   and complete three BLE scans. The recorded candidate fails this requirement.
   Preserve evidence and restore the original firmware independently of the
   failed test result.

Counter fields: attempts, consumed faults, armed stage, last forced stage,
last actual return, forced return, download-finish count, completed-init count,
then the live `bt_is_ready()` value added by the Python binding. RAM contains
only the first eight counters. Do not infer the ninth from the saved counter block.

The diagnostic patch was reapplied to copies of all three exact original files;
all resulting source hashes match the physically tested build. An unfaulted
control with the same workflow-disabled configuration and separate single-fault
retries remain necessary before attributing the timeout to retry cleanup.


## Ready-firmware guard comparison

The [follow-up](../../docs/picow-bt-retry-ready-guard-2026-10-23.md) compares
unfaulted startup, one failed ready operation followed by retry, and the full
three-failure sequence. The original diagnostic starts normally without faults
but still halts after a single ready-stage forced error and retry.

For the candidate, first apply the original `diagnostic.patch` above, then run
`python ready_guard.py /path/to/circuitpython/ports/zephyr-cp/modules/hal/rpi_pico/src/rp2_common/pico_cyw43_driver/cybt_shared_bus/cybt_shared_bus.c`.
The transformer refuses any input except the exact instrumented HAL source
and verifies the exact physically tested output hash. Binding and workflow
configuration stay unchanged. Build and install with the same backup/recovery
precautions, then use `probe_ready_guard.py`. The expected firmware-download
count is now one throughout the sequence. On a separate fresh boot use
`probe_unfaulted.py` to exercise first startup without any injection.

This is a diagnostic comparison, not a production release. Both candidate
controls pass; normal automatic workflows and Pico 2 still need qualification.


Production integration and bounded normal startup on Pico W are now covered
by [the follow-up qualification](../../docs/pico-normal-ble-ready-guard-2026-10-23.md). Pico 2 candidate
qualification stopped at original-firmware preflight without a firmware write.
That was the initial result; the subsequent recorded qualification passes normal
startup on Pico 2 and restores original code, verifies the full expected image,
and passes radio and port/import-state checks. Earlier preflight failures remain
unexplained. Pico 2 forced-error checks now pass in [the current diagnostic](../../docs/pico2-bt-forced-retry-2026-10-24.md); natural faults and workflow client
transfers remain open. No client framing fix is claimed.

For current Pico 2 pins use `pico2-current-diagnostic.patch` and `probe_pico2_current.py` as described in that report. The production guard is already present; do not apply `ready_guard.py` again.
