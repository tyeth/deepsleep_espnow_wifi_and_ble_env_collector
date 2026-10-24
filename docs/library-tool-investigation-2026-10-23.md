# Library and deployment-tool investigation — 23 October 2026

## mpremote new-file failure: reproduced and fixed in a review draft

This matches existing upstream [MicroPython #17752](https://github.com/micropython/micropython/issues/17752),
which remains open. No duplicate issue was filed. Pinned upstream source is
`b70ae1aca657bb93e2857dac4e2a2d21a3803200`.

On the real Feather ESP32 V2 running custom CircuitPython
`11.0.0-alpha.2-16-gea06dcb44e-dirty`, the actual mpremote copy and transport
functions fail when the destination does not exist. The filesystem is writable.
CircuitPython returns `OSError: [Errno 2] No such file/directory`; the converter
does not recognize it, so the existence check aborts before writing. Direct
creation works, and the unchanged copy function then overwrites and reads back
the correct contents. This is not evidence of filesystem corruption.

The first candidate recognized bracketed errno values but still failed on the
actual UART traceback, whose CR CR LF ending left a blank final line. That failed
attempt is retained. The final candidate trims trailing whitespace and maps
bracketed numeric codes through the existing remote errno table. It passes fresh
file creation, overwrite and exact SHA-256 readback on the same board. Unknown
and malformed errors are preserved. Every physical attempt removed its unique
disposable file and synced; no firmware write, reset or remount was requested.

Three host tests cover 40 supported format/line-ending combinations plus
unknown/malformed errors and missing-path controls. Ruff format/check passes.
See [structured physical evidence](mpremote-new-file-comparison-2026-10-23.json)
and [fork draft PR #1](https://github.com/tyeth-ai-assisted/circuitpython/pull/1)
at `9a9f267b3a2d6af31e2b4045ab8a89bb712c9f4a`.

The initial physical harness executed pinned real functions through a custom
raw-REPL adapter. A separate full CLI comparison now passes at 06:31 UTC using
`python -B -m mpremote connect <device> resume ...` and the unmodified stock
`SerialTransport` on the same Feather. Baseline new-file copy exits 1 with the
reported errno traceback and leaves the destination absent. The candidate exits
0 for new-file copy, overwrite, both remote-to-local readbacks and cleanup; the
two distinct payloads match byte-for-byte. Explicit sync and final absence
checks pass. Board uptime advances from 5947.024 to 5950.568 seconds. No soft
reset or firmware write was requested; this does not qualify every serial-line
reset behavior or the matching-firmware MicroPython hardware suite.

The first CLI attempt stopped before device access because `platformdirs` was
missing. That failure is preserved; version 4.5.1 was then installed in an
isolated target directory without changing the existing environment. The full
package is pinned to the same upstream/candidate sources; only `transport.py`
differs between the two CLI variants. See [CLI evidence](mpremote-cli-comparison-2026-10-23.json).

GitHub reused the existing CircuitPython fork network; the draft uses an
isolated MicroPython baseline branch. Human review remains pending before
upstream submission.

Minimal reproduction: on a writable CircuitPython board, copy a small local file
to a unique missing destination. Compare with a destination created directly via
`open(path, "wb")`. The baseline fails only the first case; the candidate passes
both. Verify contents and remove the disposable file afterwards.

## JD79667 diagnostics and timing defaults

Upstream and the existing frozen library both match revision
`4a5ce53302152058cac151cef6d5c528304d3437`, source SHA-256
`bdab0a5a3f5a8651177632d683863d085bef87a0dbfc10d40e26c852d69ffe0c`.
Executing that exact constructor with host substitutes reproduces the unsolicited
58-byte start-sequence hex dump in four reset-pin/timing-option combinations.
Removing only the print silences all four controls. The reported stray
`AttributeError` is not reproduced in those controls; this does not exclude an
error in the real display stack.

No timing options are supplied unless the caller supplies them. The unchanged
CircuitPython argument table defaults to 40 seconds for refresh and 180 seconds
between frames; explicit 20/20 values pass through unchanged. Actual panel timing
and `time_to_refresh` behavior still require the physical panel.

See [host evidence](jd79667-investigation-2026-10-23.json),
[the reproducible checker](../tools/check_jd79667_reports.py),
[the minimal print-removal patch](jd79667-remove-debug-print.patch), and
[pinned upstream source](https://github.com/adafruit/Adafruit_CircuitPython_JD79667/blob/4a5ce53302152058cac151cef6d5c528304d3437/adafruit_jd79667.py).
Run the checker with that downloaded source and `--output result.json`.
The patch has not been deployed or submitted as a library PR.
