# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
Collector entry point: refuse to start on a board that cannot run the hub,
BEFORE the hub's 60 KB of code is loaded.

The hub (hub_main.py) needs, measured on a 32-bit build: ~30 KB for the
adafruit_ble stack, ~20 KB for the HTTP portal, ~27 KB for hub_main itself,
~40 KB for the other modules, plus the stores, the display tree where there
is one, and working room for TLS. That is fine on the ESP32 family
(150-230 KB free at boot) and on a Raspberry Pi Pico 2 W (~300 KB), and it
is not fine on a Pico W (RP2040, ~40 KB): there it would import for a
while and then die with a MemoryError somewhere unhelpful. So this file
checks and says why. The Pico W runs the node (node/), not the hub.

Capability checks, not board ids: free heap and module presence.
"""

import gc
import sys
import time

gc.collect()
_free = gc.mem_free()

_MIN_FREE = 128 * 1024

_why = []
if _free < _MIN_FREE:
    _why.append("only %d bytes of heap free at boot; the hub needs about "
                "%d (BLE stack + HTTP portal + stores). An RP2040 has ~40 KB: "
                "run node/ on it, the hub on a Pico 2 W or an ESP32."
                % (_free, _MIN_FREE))
for _mod in ("wifi", "socketpool"):
    try:
        __import__(_mod)
    except ImportError:
        _why.append("no '%s' module in this CircuitPython build" % _mod)
try:
    __import__("_bleio")
except ImportError:
    print("collector: no _bleio in this build -- BLE UART portal and BLE "
          "node scanning will be off (WiFi only)")

if _why:
    print("collector: NOT starting on %s:" % sys.platform)
    for _w in _why:
        print("  -", _w)
    while True:          # stay reachable on the REPL; no MemoryError cascade
        time.sleep(60)

print("collector: %d bytes free on %s -> hub_main" % (_free, sys.platform))
import hub_main  # noqa: E402,F401
