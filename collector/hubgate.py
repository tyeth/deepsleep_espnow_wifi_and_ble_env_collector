# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
hubgate - is there room for the hub at all? Then start it (import hubmain).

code.py's one line imports this, and this imports hubmain. It is its own
module, and not a few lines in code.py, for the reason code.py is one line:
code.py is compiled ON the device, and on the ESP32-C6 a larger compiled
code.py is resident early enough to deny `esp_wifi_init()` the contiguous
internal RAM it needs (code.py's docstring has the bench numbers). This
file ships cross-compiled as `hubgate.mpy` like every other module
(tools/build_mpy.sh / tools/build_bundle.sh compile everything but code.py
and boot.py), so the gate costs code.py nothing.

**The one check that has to run before hubmain's bytecode is loaded**: a
Raspberry Pi Pico W (RP2040, ~19.6 KB of heap after its current firmware)
would load hubmain for a while and then die with a MemoryError somewhere
unhelpful -- so below `_HUB_MIN_FREE` this says why and idles with the REPL
reachable. The Pico W runs node/ instead. Capability, not board id; every
other gate (no ESP-NOW, no RTC, no user SPI, AP *or* station) is a `caps`
probe inside hubmain, after the radios are up.

Why the floor is only 40 KB, when the hub needs far more than that: on the
Zephyr port `gc.mem_free()` reports the heap's *current* size, not what it
can grow to. A Pico 2 W reads ~70 KB at a bare REPL yet allocates ~208 KB
before MemoryError (measured on the firmware before the CircuitPython-11
rebase, which costs it ~31 KB more static RAM; see pico_w_zephyr.md), so a
gate at the hub's real need (PR #11 used 128 KB) would refuse the one Pico
that can run it. 40 KB sits under the smallest number a board that can run
the hub reports, and over everything a Pico W can report. Every ESP32 is
far above it (the C6 has ~277 KB here), so on them this is one comparison
and then exactly the `import hubmain` it always was.
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
