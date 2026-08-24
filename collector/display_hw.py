# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
display_hw - eInk hardware profiles.

Two supported rigs (config "display_profile": "auto" picks by board id):

  quad_3in52  Feather (S3/C6/S2) + eInk Feather Friend #4446 + 3.52"
              quad-color (black/white/yellow/red). Constructor takes
              384x180 (driver/displayio quirk; panel is 380x180).
              CS=D9 DC=D10, no reset/busy. Driver: adafruit_jd79667.

  tri_2in9    QT Py S3 + EYESPI/eInk BFF + 2.9" tri-color (PID 1028,
              black/white/red, 296x128) -- the HIL test bench rig.
              CS=TX DC=RX (BFF default), no reset/busy.
              Driver: adafruit_il0373.

Both return (display, palette_mode) where palette_mode is "quad" or "tri";
display_ui uses it to pick warn/bad rendering (tri has no yellow).
"""

import time

import board
from fourwire import FourWire

PROFILES = {
    "quad_3in52": {
        "driver": "jd79667",
        "width": 384,
        "height": 180,
        "rotation": 270,
        "palette": "quad",
        "cs": "D9",
        "dc": "D10",
    },
    "tri_2in9": {
        "driver": "il0373",
        "width": 296,
        "height": 128,
        "rotation": 270,
        "palette": "tri",
        "cs": "TX",
        "dc": "RX",
    },
}


def auto_profile():
    bid = getattr(board, "board_id", "")
    if "qtpy" in bid or "qt_py" in bid:
        return "tri_2in9"
    return "quad_3in52"


def resolve(name):
    if not name or name == "auto":
        name = auto_profile()
    return name, PROFILES.get(name, PROFILES["quad_3in52"])


def init_display(spi, profile_name="auto", overrides=None):
    """Init the eInk for the profile. Returns (display, palette_mode).

    overrides: optional dict from config.json ("display" key) to tweak any
    profile field (width/height/rotation/cs/dc) without code changes during
    bring-up.
    """
    name, prof = resolve(profile_name)
    prof = dict(prof)
    if overrides:
        prof.update(overrides)
    cs = getattr(board, prof["cs"])
    dc = getattr(board, prof["dc"])
    bus = FourWire(spi, command=dc, chip_select=cs, reset=None,
                   baudrate=1000000)
    time.sleep(1)
    if prof["driver"] == "jd79667":
        import adafruit_jd79667
        display = adafruit_jd79667.JD79667(
            bus,
            width=prof["width"],
            height=prof["height"],
            busy_pin=None,
            rotation=prof["rotation"],
            colstart=0,
            highlight_color=0xFFFF00,
            highlight_color2=0xFF0000,
        )
    else:
        import adafruit_il0373
        display = adafruit_il0373.IL0373(
            bus,
            width=prof["width"],
            height=prof["height"],
            busy_pin=None,
            rotation=prof["rotation"],
            highlight_color=0xFF0000,
        )
    print("eInk '%s' ready %dx%d (%s palette)"
          % (name, display.width, display.height, prof["palette"]))
    return display, prof["palette"]
