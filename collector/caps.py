# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
caps - what this board and port can actually do, probed at import time, and
a wall clock that works on ports without an RTC.

This exact file is deployed to BOTH the collector and the nodes (a copy
lives in collector/ and node/ -- keep them identical).

Why this exists: the project was written for the ESP32 family, where
`espnow`, `alarm` (deep sleep), `rtc`, custom-pin `busio` and a softAP all
exist. On the Raspberry Pi Pico W / Pico 2 W running CircuitPython's Zephyr
port (`ports/zephyr-cp`, `sys.platform == "Zephyr"`) none of those do, and
two of the gaps do not announce themselves:

  * `rtc` is absent, and with it the time source behind `time.time()` and
    zero-argument `time.localtime()`: both raise
    `RuntimeError: RTC is not supported on this board` (the weak
    `rtc_get_time_source_time()` in shared-bindings/time is what gets
    linked). `time.localtime(secs)` and `time.mktime()` are pure
    conversions and keep working, so `now()` below keeps its own epoch
    offset against `time.monotonic_ns()` and the rest of the code asks
    this module for the time instead of the `time` module.
  * `wifi.radio.start_ap()` is an empty stub on zephyr-cp: it neither
    starts an access point nor raises, and `wifi.radio.ap_active` stays
    False. Code that trusts start_ap() to have worked believes it is
    serving a captive portal on 192.168.4.1 that does not exist.

Everything here is a probe (module import, a call that raises, a platform
string), not a board-id table, so an ESP32 build missing a module gets the
same treatment as the Pico.
"""

import gc
import sys
import time

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
HAS_NVM = has("microcontroller") and getattr(
    __import__("microcontroller"), "nvm", None) is not None
HAS_ANALOG = has("analogio")
HAS_SDCARD = has("sdcardio")
HAS_DISPLAYIO = has("displayio")


def _rtc_time_works():
    try:
        time.time()
        return True
    except (RuntimeError, NotImplementedError):
        return False


# an `rtc` module alone is not enough: what matters is whether time.time()
# has a source behind it
HAS_RTC = has("rtc") and _rtc_time_works()

# zephyr-cp: start_ap() is a no-op stub (see module docstring). Elsewhere the
# call either works or raises, and the caller re-checks radio.ap_active.
AP_SUPPORTED = HAS_WIFI and not IS_ZEPHYR

# `busio.SPI(clk, mosi, miso)` / `busio.I2C(scl, sda)` on zephyr-cp raise
# NotImplementedError("Use device tree to define SPI devices"): only the
# buses the board's devicetree enables exist, as objects on `board`.
PIN_BUSIO = not IS_ZEPHYR

# How many sockets can be open at once. Zephyr: CONFIG_NET_MAX_CONTEXTS
# (6 on these boards -- listener, every accepted client and every UDP
# socket count). ESP-IDF: LWIP_MAX_SOCKETS (10 in CircuitPython's sdkconfig).
MAX_SOCKETS = 6 if IS_ZEPHYR else 10


def free():
    gc.collect()
    return gc.mem_free()


def i2c():
    """The board's default I2C bus, whichever way this port exposes it.

    ESP32 boards have factories (`board.I2C()`, `board.STEMMA_I2C()`).
    zephyr-cp boards have bus OBJECTS: `board.I2C0` (Pico: SDA GP4, SCL
    GP5), `board.I2C1` (SDA GP6, SCL GP7). Returns None if there is none.
    """
    import board
    for name in ("STEMMA_I2C", "I2C"):
        f = getattr(board, name, None)
        if callable(f):
            try:
                return f()
            except (RuntimeError, ValueError) as exc:
                print("caps: board.%s() failed: %s" % (name, exc))
    for name in ("I2C0", "PICO_I2C", "I2C1"):
        obj = getattr(board, name, None)
        if obj is not None and not callable(obj):
            return obj
    return None


def spi():
    """A user SPI bus for a display / SD card, or None when the port has
    none. On zephyr-cp `board.SPI` is the CYW43439 radio's own PIO bus
    (pio0_spi0) -- putting an eInk or SD card on it would fight the WiFi
    and BLE driver for the bus -- and a custom-pin busio.SPI raises. The
    RP2040/RP2350 hardware SPI0 (GP16-19) exists but is not enabled in the
    board's devicetree, so it would need a firmware overlay first."""
    import board
    f = getattr(board, "SPI", None)
    if callable(f):
        try:
            return f()
        except (RuntimeError, ValueError) as exc:
            print("caps: board.SPI() failed: %s" % exc)
            return None
    if not PIN_BUSIO:
        return None
    return None


# ---------------------------------------------------------------------------
# Wall clock
# ---------------------------------------------------------------------------
_EPOCH_2000 = 946684800   # what an unset CircuitPython RTC reads as
_off_ns = None            # epoch_ns - monotonic_ns once someone set the time


def _mono_ns():
    try:
        return time.monotonic_ns()
    except AttributeError:            # host builds without monotonic_ns
        return int(time.monotonic() * 1e9)


def now():
    """Epoch seconds. Until synced on an RTC-less board this counts from
    2000-01-01 like a fresh RTC would, so `localtime()[0] >= 2025` keeps
    meaning "the clock has been set"."""
    if HAS_RTC:
        return int(time.time())
    if _off_ns is None:
        return _EPOCH_2000 + _mono_ns() // 1000000000
    return (_off_ns + _mono_ns()) // 1000000000


def set_epoch(epoch):
    """Set the clock from an epoch (NTP, a browser, the hub's cfg push)."""
    global _off_ns
    epoch = int(epoch)
    if HAS_RTC:
        import rtc
        rtc.RTC().datetime = time.localtime(epoch)
    else:
        _off_ns = epoch * 1000000000 - _mono_ns()
    return epoch


def localtime(secs=None):
    """time.localtime() that works without an RTC (the one-argument form
    is a pure conversion on every port)."""
    return time.localtime(now() if secs is None else secs)


def synced():
    return localtime()[0] >= 2025


def summary():
    """One dict for the boot log and the status API."""
    import board
    return {
        "platform": sys.platform,
        "board": getattr(board, "board_id", "?"),
        "free": free(),
        "wifi": HAS_WIFI, "ble": HAS_BLE, "espnow": HAS_ESPNOW,
        "alarm": HAS_ALARM, "rtc": HAS_RTC, "ap": AP_SUPPORTED,
        "pin_busio": PIN_BUSIO, "sockets": MAX_SOCKETS,
    }
