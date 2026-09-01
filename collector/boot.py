# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
boot.py - decide who owns the filesystem: the MCU or a host PC.

On boards with USB mass storage (S3/S2 Feathers, devkits) the host and the
board cannot both write CIRCUITPY. Whoever is not chosen gets a read-only
view. A hub is a data logger, so the default is **MCU**: the board can
write its readings, and no drive appears on a computer.

Choose with, in order of precedence:

  settings.toml   ENVHUB_USB_DRIVE = "pc"     (or "mcu")
  config.json     "usb_drive_owner": "pc"
  BOOT button     held at power-up -> "pc" for this boot, whatever the
                  settings say. This is the way back in when a hub has
                  taken the drive and you need to copy files onto it.

`storage.disable_usb_drive()` only works here in boot.py -- that is what
makes it safe (nothing is mounted yet, so no host write can be lost). The
runtime fallback in datastore.py exists for boards booted without this
file; it is the "unsafe" variant for exactly that reason.

The C6 has no USB mass storage at all, so none of this applies there and
the calls are simply skipped.
"""

import json
import os

import storage

_DEFAULT = "mcu"


def _nvm_owner():
    """The choice made at runtime over the API.

    It lives in NVM because the filesystem is read-only exactly when the
    request matters -- a PC holding the drive is what you are asking to
    change -- so config.json cannot be written at that moment.
    """
    try:
        import microcontroller
        val = microcontroller.nvm[0]
    except Exception:
        return None
    if val == 0xF0:
        return "mcu"
    if val == 0xF1:
        return "pc"
    return None


def _configured_owner():
    owner = _nvm_owner()
    if owner:
        return owner, "NVM (set over the API)"
    owner = os.getenv("ENVHUB_USB_DRIVE")
    if owner:
        return owner.strip().lower(), "settings.toml"
    try:
        with open("/config.json") as f:
            owner = json.load(f).get("usb_drive_owner")
        if owner:
            return str(owner).strip().lower(), "config.json"
    except (OSError, ValueError):
        pass
    return _DEFAULT, "default"


def _boot_button_held():
    """A held BOOT button forces PC ownership -- the escape hatch."""
    try:
        import board
        import digitalio
        pin = getattr(board, "BUTTON", None) or getattr(board, "BOOT0", None)
        if pin is None:
            return False
        btn = digitalio.DigitalInOut(pin)
        btn.switch_to_input(pull=digitalio.Pull.UP)
        held = not btn.value          # active low
        btn.deinit()
        return held
    except Exception:
        return False


owner, source = _configured_owner()
if _boot_button_held():
    owner, source = "pc", "BOOT button"

if owner == "pc":
    print("boot: filesystem owned by the PC (%s) -- the hub cannot log; "
          'set "usb_drive_owner": "mcu" to swap' % source)
else:
    try:
        storage.disable_usb_drive()
        print("boot: filesystem owned by the MCU (%s) -- no USB drive; "
              "hold BOOT at power-up, or set it to \"pc\", to copy files"
              % source)
    except Exception as exc:      # no MSC on this board (C6), or already off
        print("boot: USB drive not disabled (%s: %s)"
              % (type(exc).__name__, exc))
