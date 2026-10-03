# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
code.py - start the hub. The hub itself is hubmain.

Why this file is (almost) one line: on the ESP32-C6 the *compiled body of
code.py* is resident before its first statement runs, and it is large
enough to deny `esp_wifi_init()` the contiguous internal RAM its `esf_buf`
pool needs. The
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
`hubmain.mpy` by `tools/build_mpy.sh` (or by hand, see the README's
*Deploy* section), and this file is small enough to cost nothing.

**`hubmain.mpy` is not optional on the C6.** Copying `hubmain.py` to the
board as source and letting CircuitPython compile it there fails exactly
the way the old code.py did -- verified on the bench, and note that a soft
reload appears to succeed, so only a hard reset tells you the truth.

**The one check that has to live here**, because it has to run before
hubmain's bytecode is loaded: is there room for the hub at all? A
Raspberry Pi Pico W (RP2040, ~30-40 KB of heap after its firmware) would
load hubmain for a while and then die with a MemoryError somewhere
unhelpful -- so below `_HUB_MIN_FREE` this file says why and idles with the
REPL reachable. The Pico W runs node/ instead. Capability, not board id;
every other gate (no ESP-NOW, no RTC, no user SPI, AP *or* station) is a
`caps` probe inside hubmain, after the radios are up.

Why the floor is only 40 KB, when the hub needs far more than that: on the
Zephyr port `gc.mem_free()` reports the heap's *current* size, not what it
can grow to. A Pico 2 W reads ~70 KB at a bare REPL yet allocates ~208 KB
before MemoryError (measured; see pico_w_zephyr.md), so a gate at the
hub's real need (PR #11 used 128 KB) would refuse the one Pico that can
run it. 40 KB sits under the smallest number a board that can run the hub
reports, and over everything a Pico W can report. Every ESP32 is far above
it (the C6 has ~277 KB here), so on them this is one comparison and then
exactly the line it always was.
"""

import gc

_HUB_MIN_FREE = 40 * 1024

gc.collect()
if gc.mem_free() < _HUB_MIN_FREE:
    import sys
    import time
    print("collector: NOT starting on %s: only %d bytes of heap free, and "
          "the hub needs well over %d just to load. On a Raspberry Pi Pico "
          "W run node/ (node_lite); run the hub on a Pico 2 W or an ESP32."
          % (sys.platform, gc.mem_free(), _HUB_MIN_FREE))
    while True:          # stay reachable on the REPL; no MemoryError cascade
        time.sleep(60)

import hubmain  # noqa: F401,E402
