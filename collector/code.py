# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
code.py - start the hub. The hub itself is hubmain.

Why this file is one line: on the ESP32-C6 the *compiled body of code.py* is
resident before its first statement runs, and it is large enough to deny
`esp_wifi_init()` the contiguous internal RAM its `esf_buf` pool needs. The
hub stopped booting at `import wifi` with

    W (4103) wifi:esf_buf_setup_static: alloc eb fail(10)
    MemoryError: Failed to allocate Wifi memory

**with 242 KB of heap still free** -- so this is contiguity, not exhaustion.
Measured on the bench (2026-09-11): a code.py that does nothing but
`import wifi` leaves 277 KB free and succeeds; the real one leaves 242 KB
and fails. Hoisting `import wifi` to the first line does not help, and nor
does stripping the comments out -- a 48.7 KB code.py fails too.

What does help is never compiling it on the device. A module ships as
`.mpy`: no compiler peak, and far more compact bytecode (67 KB of source ->
23 KB). So the hub lives in `hubmain.py`, is cross-compiled to
`hubmain.mpy` by `tools/build_bundle.sh` (or by hand, see the README's
*Deploy* section), and this file is small enough to cost nothing.

**`hubmain.mpy` is not optional on the C6.** Copying `hubmain.py` to the
board as source and letting CircuitPython compile it there fails exactly
the way the old code.py did -- verified on the bench, and note that a soft
reload appears to succeed, so only a hard reset tells you the truth.
"""

import hubmain  # noqa: F401
