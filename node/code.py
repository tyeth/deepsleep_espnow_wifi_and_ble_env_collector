# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
Node entry point: pick the node that fits this board, BEFORE loading it.

CircuitPython loads a module's whole bytecode before running a line of it,
so a 47 KB code.py that "checks for espnow first" has already spent the
RAM by the time the check runs. This file stays tiny and only dispatches:

  node_full   ESP32 family: ESP-NOW + deep sleep + sleep memory, the node
              this repo was written around (unchanged, just renamed).
  node_lite   boards without espnow/alarm -- Raspberry Pi Pico W / Pico 2 W
              on the Zephyr port: awake loop, readings broadcast as BLE
              advertisements, optional WiFi POST. See node_lite.py for what
              that costs.

Capability, not board id: an ESP32 build without espnow gets node_lite too.
"""

import gc
import sys
import time

gc.collect()
_free = gc.mem_free()


def _has(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


_LITE_MIN_FREE = 24 * 1024   # node_lite + envadv + node_sensors + one driver

if _has("espnow") and _has("alarm"):
    print("node: espnow + alarm present -> node_full (deep sleep, ESP-NOW)")
    import node_full  # noqa: F401
elif _free < _LITE_MIN_FREE:
    print("node: %d bytes free at boot on %s; even node_lite needs ~%d. "
          "Deploy .mpy files (tools/build_bundle.sh), drop unused libraries "
          "from lib/, or use a board with more RAM." % (_free, sys.platform,
                                                        _LITE_MIN_FREE))
    while True:          # keep the REPL reachable instead of MemoryError spam
        time.sleep(60)
else:
    print("node: no espnow/alarm on %s (%d bytes free) -> node_lite "
          "(awake loop, BLE advertisements)" % (sys.platform, _free))
    import node_lite  # noqa: F401
