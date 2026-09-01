# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
node_store - write node_config.json from wherever the node is running.

CIRCUITPY is read-only to the board while USB mass storage holds it (S2/S3),
so a save walks three options in order: the normal path, the CPSAVES
partition (which the board can always write), and -- last resort -- ejecting
the USB drive at runtime. The caller reboots after saving, which restores
the drive.

Shared by the first-boot WiFi portal and the BLE config portal so both
persist settings the same way.
"""

import json

DEFAULT_PATH = "/node_config.json"
SAVES_PATH = "/saves/node_config.json"


def save_config(config, path=DEFAULT_PATH):
    """Persist config; returns the path actually written, or None."""
    for target in (path, SAVES_PATH, None):
        if target is None:
            try:
                import storage
                storage.unsafe_disable_usb_drive()
                storage.remount("/", readonly=False)
                target = path
                print("config: USB drive ejected to unlock the flash")
            except (ImportError, AttributeError, RuntimeError, OSError) as exc:
                print("config: usb eject fallback failed:", exc)
                return None
        try:
            with open(target, "w") as f:
                json.dump(config, f)
            return target
        except OSError as exc:
            print("config: save to %s failed: %s" % (target, exc))
    return None
