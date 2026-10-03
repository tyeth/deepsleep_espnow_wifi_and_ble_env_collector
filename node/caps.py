# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
caps - what this board and port can actually do, probed at import time, and
a wall clock that works on ports without an RTC.

This exact file is deployed to BOTH the collector and the nodes (a copy
lives in collector/ and node/ -- keep them identical; tools/test_envadv.py
checks).

Why this exists: the project was written for the ESP32 family, where
`espnow`, `alarm` (deep sleep), `rtc`, custom-pin `busio` and an AP that
runs beside a station all exist. On the Raspberry Pi Pico W / Pico 2 W
running CircuitPython's Zephyr port (`ports/zephyr-cp`,
`sys.platform == "Zephyr"`) several of those do not, and two of the gaps
do not announce themselves:

  * On the Pico 2 W `rtc` is absent, and with it the time source behind
    `time.time()` and zero-argument `time.localtime()`: both raise
    `RuntimeError: RTC is not supported on this board` (confirmed on the
    board). `time.localtime(secs)` and `time.mktime()` are pure
    conversions and keep working, so `now()` below keeps its own epoch
    offset against `time.monotonic_ns()`, and `caps.time` is a stand-in
    for the `time` module whose `time()` and `localtime()` read it. The
    Pico W is different since the fork was rebased onto CircuitPython 11
    (ci/pico2w-ble-assets @ 393be068ab): upstream gave it an `rtc` module
    from its devicetree RTC node, which the Pico 2 W's devicetree lacks.
    So this is probed, never assumed per board: where `rtc` imports AND
    time.time() works, caps simply uses them.
  * `wifi.radio.start_ap()` on zephyr-cp depends on the firmware. Before
    tyeth/circuitpython#22 it was an empty stub: it returned without error
    and `wifi.radio.ap_active` stayed False, so code that trusted the call
    believed it was serving a captive portal that did not exist. From #22
    on it is real (192.168.4.1/24, DHCP server auto-started). Python cannot
    tell the two firmwares apart before calling it, so on this port the
    callers start the AP and then CHECK `ap_active` (`AP_VERIFY`).
    Separately, the CYW43439's AIROC driver runs the AP and the station on
    one interface: AP+STA together returns -EBUSY (`APSTA`). The hub picks
    one -- see hubmain's early AP block.

On a board with an RTC (every ESP32) `caps.time` IS the `time` module and
`set_epoch()` is the `rtc.RTC().datetime = ...` it replaces, so nothing
changes there. Every probe is a module import, a call that raises, or the
platform string -- an ESP32 build missing a module gets the same
treatment as the Pico.
"""

import gc
import sys
import time as _time

IS_ZEPHYR = sys.platform == "Zephyr"


def has(name):
    """True if `import name` works on this build."""
    try:
        __import__(name)
        return True
    except ImportError:
        return False


HAS_WIFI = has("wifi")
HAS_BLE = has("_bleio")
HAS_ESPNOW = has("espnow")
HAS_ALARM = has("alarm")          # deep sleep + alarm.sleep_memory


def _rtc_time_works():
    try:
        _time.time()
        return True
    except (RuntimeError, NotImplementedError):
        return False


# an `rtc` module alone is not enough: what matters is whether time.time()
# has a source behind it
HAS_RTC = has("rtc") and _rtc_time_works()

# zephyr-cp: start_ap() may be the old no-op stub; start it, then believe
# wifi.radio.ap_active rather than the call. Not done on the ESP32 port,
# where ap_active comes up asynchronously from the IDF event task and can
# still read False straight after a start_ap() that worked.
AP_VERIFY = IS_ZEPHYR
# zephyr-cp/AIROC: one net_if for AP and station; starting one while the
# other is up returns -EBUSY. ESP32 runs both (the AP follows the
# station's channel).
APSTA = not IS_ZEPHYR

# `busio.SPI(clk, mosi, miso)` / `busio.I2C(scl, sda)` on zephyr-cp raise
# NotImplementedError("Use device tree to define ... devices"): only the
# buses the board's devicetree enables exist, as callables on `board`.
# And `board.SPI` there is the CYW43439 radio's own PIO bus -- never a bus
# for a display or an SD card.
PIN_BUSIO = not IS_ZEPHYR

# How many sockets can be open at once. Zephyr: CONFIG_NET_MAX_CONTEXTS
# (6 on these boards -- the listener, every accepted client and every UDP
# socket count). ESP-IDF: LWIP_MAX_SOCKETS (10 in CircuitPython's
# sdkconfig). Firmware with a raised ceiling cannot be detected from
# Python: config.json "max_sockets" overrides this (hubmain sets it).
MAX_SOCKETS = 6 if IS_ZEPHYR else 10


def free():
    gc.collect()
    return gc.mem_free()


def i2c():
    """The board's default I2C bus, whichever way this port exposes it.

    ESP32 boards have `board.STEMMA_I2C()` / `board.I2C()`. zephyr-cp
    boards expose the devicetree buses by number instead: `board.I2C0`
    (Pico: SDA GP4, SCL GP5) and `board.I2C1` (SDA GP6, SCL GP7) -- as
    callables on the Pico 2 W tested, so both forms are accepted.
    Returns None if there is none.
    """
    import board
    for name in ("STEMMA_I2C", "I2C", "I2C0", "PICO_I2C", "I2C1"):
        obj = getattr(board, name, None)
        if obj is None:
            continue
        if not callable(obj):
            return obj
        try:
            return obj()
        except (RuntimeError, ValueError) as exc:
            print("caps: board.%s() failed: %s" % (name, exc))
    return None


# ---------------------------------------------------------------------------
# Wall clock
# ---------------------------------------------------------------------------
_EPOCH_2000 = 946684800   # what an unset CircuitPython RTC reads as
_off_ns = None            # epoch_ns - monotonic_ns once someone set the time


def _mono_ns():
    try:
        return _time.monotonic_ns()
    except AttributeError:            # host builds without monotonic_ns
        return int(_time.monotonic() * 1e9)


def now():
    """Epoch seconds (UTC, like every clock in this project). Until synced
    on an RTC-less board this counts from 2000-01-01 the way a fresh RTC
    would, so `localtime()[0] >= 2025` keeps meaning "the clock is set"."""
    if HAS_RTC:
        return int(_time.time())
    if _off_ns is None:
        return _EPOCH_2000 + _mono_ns() // 1000000000
    return (_off_ns + _mono_ns()) // 1000000000


def set_epoch(epoch):
    """Set the clock from an epoch (NTP, a browser, an RTC chip, the hub's
    cfg push). On a board with an RTC this is exactly the
    `rtc.RTC().datetime = time.localtime(epoch)` it replaces."""
    global _off_ns
    epoch = int(epoch)
    if HAS_RTC:
        import rtc
        rtc.RTC().datetime = _time.localtime(epoch)
    else:
        _off_ns = epoch * 1000000000 - _mono_ns()
    return epoch


def set_datetime(st):
    """set_epoch() for a struct_time (adafruit_ntp hands over one). With an
    RTC the struct goes to it untouched, as before."""
    if HAS_RTC:
        import rtc
        rtc.RTC().datetime = st
        return
    set_epoch(_time.mktime(st))


def localtime(secs=None):
    """time.localtime() that works without an RTC (the one-argument form
    is a pure conversion on every port)."""
    return _time.localtime(now() if secs is None else secs)


def synced():
    return localtime()[0] >= 2025


class _NoRtcTime:
    """The `time` module for a port without an RTC: everything is the real
    module's except time() and zero-argument localtime(), which read the
    offset clock above. Attributes are copied in rather than forwarded by
    __getattr__, so a call costs what it costs on the real module."""

    def __init__(self):
        for name in ("monotonic", "monotonic_ns", "sleep", "mktime",
                     "struct_time", "gmtime"):
            f = getattr(_time, name, None)
            if f is not None:
                setattr(self, name, f)

    @staticmethod
    def time():
        return now()

    @staticmethod
    def localtime(secs=None):
        return localtime(secs)


# What the collector's modules use as `time` (`time = caps.time`). On every
# ESP32 this is the time module itself -- same object, same calls.
time = _time if HAS_RTC else _NoRtcTime()


def summary():
    """One dict for the boot log."""
    import board
    return {
        "platform": sys.platform,
        "board": getattr(board, "board_id", "?"),
        "free": free(),
        "wifi": HAS_WIFI, "ble": HAS_BLE, "espnow": HAS_ESPNOW,
        "alarm": HAS_ALARM, "rtc": HAS_RTC, "apsta": APSTA,
        "pin_busio": PIN_BUSIO, "sockets": MAX_SOCKETS,
    }
