# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
code.py - start the node. The node itself is nodemain (or, on a board
without ESP-NOW and deep sleep, node_lite -- see the end of this text).

Why this file is (almost) one line: the same reason `collector/code.py`
is. On the ESP32-C6 the *compiled body of code.py* is resident before its
first statement runs, and a large one denies `esp_wifi_init()` the
contiguous internal RAM its `esf_buf` pool needs -- the hub died at
`import wifi` with

    W (4103) wifi:esf_buf_setup_static: alloc eb fail(10)
    MemoryError: Failed to allocate Wifi memory

**with 242 KB of heap still free**, so it is contiguity, not exhaustion.
The bench measured the cliff on the hub, not here: a comment-stripped
48.7 KB code.py failed it, and the node's was 46.9 KB -- under the number
that failed, over the 62 KB one that used to boot, which is to say the
node was sitting in the band where placement decides it. It has not been
seen to fail; this is the structural fix applied before it does, and it is
what lets a node run on a C6 at all.

So the body lives in `nodemain.py`, ships cross-compiled as `nodemain.mpy`
(no compiler peak on the device, and far more compact bytecode), and this
file costs nothing:

    mpy-cross -o nodemain.mpy node/nodemain.py

Deploy `nodemain.mpy` -- **not** `nodemain.py` -- alongside this file.
`code.py` itself must stay **source**: CircuitPython looks for
`code.py`/`code.txt`/`main.py`/`main.txt` and never for `code.mpy`.

One node-specific trap when you test this: the node keeps its unsent
readings, its message-id counter and its discovered channel in
`alarm.sleep_memory`, which a **soft reload wipes** -- and a soft reload is
also what hides the memory fault (the source version boots fine under
Ctrl-D; only a hard reset tells the truth). Hard-reset to test, and expect
the first wake afterwards to re-discover its collector.

**The one decision made here**: which node. nodemain is the ESP32 node --
ESP-NOW, deep sleep, sleep memory -- and needs `espnow` and `alarm`.
Boards without them (the Raspberry Pi Pico W / Pico 2 W on CircuitPython's
Zephyr port) get `node_lite`: an awake loop that broadcasts each reading
as a BLE advertisement (see node_lite.py for what that costs). This has to
happen here, before either body is loaded, because loading nodemain is
itself what does not fit on a Pico W. Capability, not board id: an ESP32
build without espnow gets node_lite too. Both probes are imports of
built-in modules nodemain imports first thing anyway, so on an ESP32 this
costs nothing and changes nothing.

node_lite is imported (which sets it up) and then run(). A MemoryError
from the import means the node does not fit this board's heap -- said
plainly, with the REPL left reachable, rather than as a traceback from
somewhere inside a driver. Deploy `.mpy` there above all: compiling
source on a 30-40 KB heap is the peak that fails first.
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
