# ESP sleep-memory reload verification — 23 October 2026

The upstream [CircuitPython #11274 fix](https://github.com/adafruit/circuitpython/pull/11274)
is already an ancestor of alpha.2 and the current ESP integration. A physical
C5 running `e46718f34b` now adds bounded verification of the reload behavior.
The exact build enables `CONFIG_SOC_RTC_FAST_MEM_SUPPORTED=1`, so this uses
the reset-reason guard and RTC memory path, not the no-RTC fallback.

After startup the chip reports `ResetReason.POWER_ON`, the reset reason that
previously caused memory clearing on every reload. Each of three rounds fills
all 4,096 bytes of `alarm.sleep_memory` with a different deterministic pattern,
then sends empty Ctrl-D in raw REPL to reload the VM. Each round observes the
soft-reboot/raw-REPL response, verifies that a deliberately set Python global
has disappeared, confirms the chip reset reason remains POWER_ON, and compares
all memory bytes exactly. All three preservation checks pass. The original
4,096 bytes were saved privately and restored with exact comparison.

No firmware, NVM or application files were written. Source inspection of
`main.c` and `shared/runtime/pyexec.c` confirms the raw-REPL reload bypasses
`code.py`; the test additionally refuses an existing `repl.py` to avoid a
startup-script confound. This does not test fake/true deep sleep, battery
retention, brownout, or power-loss persistence.

The overall job remains **failed**: after the successful memory restoration,
the combined final port/topology/import assertion failed. That assertion did
not retain the individual failing values, so its cause is not established.
Two subsequent read-only inspections show the expected inventory and empty
imports; the second explicitly confirms the C5 port off, desired off, not
pending and disconnected. No recovery mutation was needed. The later pass
does not rewrite the failed job. [Sanitized results](c5-sleep-memory-reload-2026-10-23.json)
retain both outcomes.

## Minimal reproduction

Use a board with RTC-backed sleep memory after a power-on reset, and keep one
serial handle open. Require `microcontroller.cpu.reset_reason` to be POWER_ON
and check that `repl.py` is absent. Save the original memory bytes on the host.
In raw REPL, write a nonzero pattern and a Python global:

```python
import alarm
_reload_marker = True
alarm.sleep_memory[:8] = bytes([11, 22, 33, 44, 55, 66, 77, 88])
```

At the next empty raw prompt, send Ctrl-D. Wait for `soft reboot` and the new
raw prompt, then execute:

```python
assert "_reload_marker" not in globals()
import alarm, microcontroller
assert microcontroller.cpu.reset_reason is microcontroller.ResetReason.POWER_ON
assert bytes(alarm.sleep_memory[:8]) == bytes([11, 22, 33, 44, 55, 66, 77, 88])
```

Restore the saved bytes from the host and verify them before leaving the
session. The actual test above exercised all 4,096 bytes with three patterns;
these eight bytes are the smaller reproducer. No additional fork patch or
new upstream issue is needed for this resolved defect.
