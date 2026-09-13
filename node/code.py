# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
code.py - start the node. The node itself is nodemain.

Why this file is one line: the same reason `collector/code.py` is. On the
ESP32-C6 the *compiled body of code.py* is resident before its first
statement runs, and a large one denies `esp_wifi_init()` the contiguous
internal RAM its `esf_buf` pool needs -- the hub died at `import wifi` with

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
"""

import nodemain  # noqa: F401
