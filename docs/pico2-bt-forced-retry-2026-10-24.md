# Pico 2 W forced BLE startup failures and retry

The current production ready-firmware guard passes the previously unqualified
Pico 2 W three-error/retry control. A temporary diagnostic forces successful
ready, buffer-init and awake operations to return errors, one at a time. Each
import raises the expected target errno, Wi-Fi remains usable, and the fourth
unarmed import completes BLE startup with a stable identity and three scans.

| Stage | Expected errno | Wi-Fi results after error | Consumed faults | Firmware downloads |
| --- | --- | ---: | ---: | ---: |
| Ready (3) | EIO | 59 | 1 | 1 |
| Buffer init (4) | ETIMEDOUT | 62 | 2 | 1 |
| Awake (5) | ETIMEDOUT | 61 | 3 | 1 |

Final counters show four attempts, three consumed faults, one firmware download,
one completed initialization and Bluetooth ready. BLE scans return 79/82/88
reports. These are forced software return paths after actual successful hardware
work; they do not emulate electrical faults or measure natural-fault recovery.

## Exact build and restoration

CircuitPython `0d545efdcf74fdefef66190236f8707ac2b545c5`, Zephyr
`c6200e80ea6973b092da3c30c672901cc1951fc2`, HAL Infineon
`7f93dc60675126a63358ffa0780648d94fd2d634`, HAL Pico
`de12fc2a0f756d889cc13c129622ddb663025d29`. The guard is already in the HAL;
the diagnostic does not add it again. Raw binary: 1,204,980 bytes, SHA-256
`5ce862f5dc41150f58fb16f870266fc3e584b79c88160c365d634e5a31b76891`.

ELF hooks and source/artifact hashes are verified. Generated preprocessing shows
empty automatic BLE startup/stop bodies. Exact compiler argv was not retained
in the external CircuitPython make build's Zephyr compilation database; the
initial verifier incorrectly expected a CircuitPython row there and failed.
The corrected verifier uses the actual preprocessed bodies. Build warnings
remain in the private log; this is not a warning-free-build claim.

The transaction made a fresh 4 MiB backup, wrote only the 1,212,416-byte code
span and verified the whole expected flash. It then restored original production
code `9e153ad624` and verified the entire expected flash again, retaining runtime
data. The result differs from pretest flash; it is not an exact pretest-image
claim. Three restored Wi-Fi/BLE checks return 54/82, 52/75 and 57/80. Imports
are detached, original port state is restored, the bridge did not restart,
and no recovery remains required. The controller job passes. Eight transaction
rollback/geometry controls also pass.

## Minimal reproduction and limits

Use the exact pins above in a disposable checkout; apply
`tools/repro_picow_bt_startup/pico2-current-diagnostic.patch`, build
`BOARD=raspberrypi_rpi_pico2_w_zephyr`, and retain the ELF and recovery image.
The patch's three output hashes were independently reconstructed and compared
with the build manifest. Do not run the older ready-guard transformer on this
source: the production guard is already present.

From a fresh boot execute `probe_pico2_current.py` in one raw-REPL session,
retaining output after each section without soft-resetting. Do not import
`_bleio` before injection. The recorded run sends the initial state, each of
the three stages, and the final retry as separate commands in the same VM.
Compare BLE identity to a pretest original-firmware observation. Use a guarded
backup/restore process; a diagnostic import can halt a board.

Automatic BLE file/serial workflows are deliberately disabled. Earlier normal
startup checks remain separate. Natural faults, workflow client transfers,
USB large reads and long-run reliability are not qualified by this pass.
The prior Pico W failures and matched guard comparison remain preserved in
[the earlier report](picow-bt-retry-ready-guard-2026-10-23.md).
