# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""Host-side checks for the hub's early radio config (no hardware).

    python tools/test_early_cfg.py

hubmain decides whether to start BLE, the AP and the display before the
SD card is mounted, so it can only read /config.json -- while a hub with a
card saves its overrides to /sd/config.json. The NVM mirror of EARLY_KEYS
bridges that. hubmain.py cannot be imported on a PC (it is the whole hub),
so the two functions and their constants are lifted out of its source with
`ast` and run against a fake filesystem and a bytearray standing in for
microcontroller.nvm.
"""

import ast
import json
import os
import sys

SRC = os.path.join(os.path.dirname(__file__), "..", "collector", "hubmain.py")
NAMES = {"EARLY_KEYS", "_EARLY_NVM_AT", "_EARLY_NVM_MAGIC", "_EARLY_NVM_MAX",
         "_early_cfg", "_mirror_early"}

FAILURES = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILURES.append(name)


class FakeMicrocontroller:
    def __init__(self):
        self.nvm = bytearray(8192)


def load(files, mc):
    """The lifted functions, with open() reading from `files`."""
    tree = ast.parse(open(SRC, encoding="utf-8").read())
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in NAMES:
            keep.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in NAMES for t in node.targets):
            keep.append(node)
    found = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id
             for n in keep}
    assert found == NAMES, "hubmain no longer defines %s" % (NAMES - found)

    def fake_open(path, mode="r"):
        if path not in files:
            raise OSError(2, "ENOENT")
        import io
        return io.StringIO(files[path])

    ns = {"json": json, "microcontroller": mc, "open": fake_open,
          "print": lambda *a: None}
    exec(compile(ast.Module(body=keep, type_ignores=[]), SRC, "exec"), ns)
    return ns


def main():
    shipped = json.dumps({"ap_enabled": True, "ble_enabled": True,
                          "display_enabled": True, "rtc": "auto"})
    mc = FakeMicrocontroller()
    files = {"/config.json": shipped}
    hub = load(files, mc)

    print("no mirror")
    check("blank NVM: the shipped file alone",
          hub["_early_cfg"]()["ap_enabled"] is True)

    print("a hub with a card saves ap_enabled=false from the web UI")
    saved = {"ap_enabled": False, "ble_enabled": True, "display_enabled": True,
             "rtc": "PCF85063A", "thresholds": {"co2": [800, 1200]}}
    hub["_mirror_early"](saved)
    cfg = hub["_early_cfg"]()
    check("the next boot's early block sees it", cfg["ap_enabled"] is False)
    check("non-radio keys stay out of NVM",
          b"thresholds" not in bytes(mc.nvm[:300])
          and b"rtc" not in bytes(mc.nvm[:300]))
    check("keys only in the shipped file survive", cfg["rtc"] == "auto")

    print("writes only on a change")
    before = bytes(mc.nvm)
    writes = []

    class Spy(bytearray):
        def __setitem__(self, k, v):
            writes.append(k)
            bytearray.__setitem__(self, k, v)
    mc.nvm = Spy(before)
    hub["_mirror_early"](dict(saved))
    check("an identical save does not touch NVM", writes == [])
    hub["_mirror_early"](dict(saved, ap_enabled=True))
    check("a changed one does", writes != [])
    check("...and is read back", hub["_early_cfg"]()["ap_enabled"] is True)

    print("the override moves back to the flash root")
    hub["_mirror_early"](None)
    files["/config.json"] = json.dumps({"ap_enabled": False})
    check("a cleared mirror cannot outvote a hand edit of /config.json",
          hub["_early_cfg"]()["ap_enabled"] is False)

    print("damage")
    hub["_mirror_early"](saved)
    mc.nvm[17] = 3          # length no longer matches the JSON
    check("a torn mirror falls back to the shipped file",
          hub["_early_cfg"]() == json.loads(files["/config.json"]))
    hub["_mirror_early"](saved)                     # a good mirror again
    hub["_mirror_early"](dict(saved, ap_enabled=True, ap_ssid="x" * 300))
    cfg = hub["_early_cfg"]()
    check("an oversized one is refused, not truncated: the last good "
          "mirror stands", cfg["ap_enabled"] is False and "ap_ssid" not in cfg)
    mc.nvm = None
    hub["_mirror_early"](saved)
    check("a board with no NVM just reads the file",
          hub["_early_cfg"]() == json.loads(files["/config.json"]))

    print()
    if FAILURES:
        print("%d FAILED" % len(FAILURES))
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
