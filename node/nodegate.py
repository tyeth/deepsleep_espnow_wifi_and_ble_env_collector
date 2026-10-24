# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
nodegate - which node: nodemain (ESP32) or node_lite (Pico W / Pico 2 W).

code.py's one line imports this. It is its own module, and not a few lines
in code.py, for the reason code.py is one line (its docstring): code.py is
compiled ON the device, and on the ESP32-C6 a larger compiled code.py is
resident early enough to deny `esp_wifi_init()` the contiguous internal
RAM it needs. This ships cross-compiled as `nodegate.mpy` like every other
module (tools/build_mpy.sh / tools/build_bundle.sh compile everything but
code.py and boot.py), so the decision costs code.py nothing.

**The one decision made here**: which node. nodemain is the ESP32 node --
ESP-NOW, deep sleep, sleep memory -- and needs `espnow` and `alarm`.
Boards without them (the Raspberry Pi Pico W / Pico 2 W on CircuitPython's
Zephyr port) get `node_lite`: an awake loop that broadcasts each reading
as a BLE advertisement (see node_lite.py for what that costs). This has to
happen before either body is loaded, because loading nodemain is itself
what does not fit on a Pico W. Capability, not board id: an ESP32 build
without espnow gets node_lite too. Both probes are imports of built-in
modules nodemain imports first thing anyway, so on an ESP32 this costs
nothing and changes nothing.

node_lite is imported (which sets it up) and then run(). A MemoryError
from the import means the node does not fit this board's heap -- said
plainly, with the REPL left reachable, rather than as a traceback from
somewhere inside a driver. Deploy `.mpy` there above all: compiling
source on a Pico W's heap (~19.6 KB on the CircuitPython-11 rebase of
its firmware -- node_lite.py's "Budget" note) is the peak that fails
first. Once it is running, run() catches its own cycles' failures.
"""

try:
    import alarm  # noqa: F401
    import espnow  # noqa: F401
    _FULL = True
except ImportError:
    _FULL = False

if _FULL:
    import nodemain  # noqa: F401
else:
    import sys
    import time
    print("node: no espnow/alarm on %s -> node_lite (awake loop, BLE "
          "advertisements)" % sys.platform)
    try:
        import node_lite
    except MemoryError:
        import gc
        gc.collect()
        print("node: node_lite does not fit in this board's heap (%d bytes "
              "free now). Deploy .mpy, not .py (tools/build_mpy.sh), keep "
              "only the one sensor driver you need in lib/, or use a board "
              "with more RAM." % gc.mem_free())
        while True:      # keep the REPL reachable instead of MemoryError spam
            time.sleep(60)
    node_lite.run()
