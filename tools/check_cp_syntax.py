#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
check_cp_syntax.py - compile every device source with mpy-cross.

    python tools/check_cp_syntax.py
    MPY_CROSS=~/circuitpython/mpy-cross/build/mpy-cross python tools/check_cp_syntax.py

`python -m py_compile` is NOT enough: CPython accepts syntax CircuitPython
does not, and the board only tells you at boot -- as a bare
`SyntaxError: invalid syntax` with a line number, after the deploy. The one
that caught us was `{"err": ..., **state}`: dict-literal ** unpacking
exists in CPython and not in CircuitPython.

mpy-cross is built alongside CircuitPython (`make -C mpy-cross`); point
MPY_CROSS at it, or let this script look in the usual places. On Windows it
is run through WSL when only a Linux binary is available.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEVICE_DIRS = ("collector", "node")

CANDIDATES = (
    os.environ.get("MPY_CROSS"),
    shutil.which("mpy-cross"),
    os.path.expanduser("~/dev-projects/python/circuitpython/circuitpython/"
                       "mpy-cross/build/mpy-cross"),
)
# Paths are built from WSL's own $HOME rather than passed as shell
# variables: the Windows shell layers in between expand them first.
WSL_SUFFIXES = (
    "/dev-projects/python/circuitpython/circuitpython/mpy-cross/build/mpy-cross",
    "/circuitpython/mpy-cross/build/mpy-cross",
)


def _wsl_path(win_path):
    p = win_path.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def _find_via_wsl():
    """mpy-cross is usually a Linux binary in the WSL CircuitPython tree."""
    if not shutil.which("wsl.exe"):
        return None
    home = subprocess.run(["wsl.exe", "--", "printenv", "HOME"],
                          capture_output=True, text=True).stdout.strip()
    if not home:
        return None
    for suffix in WSL_SUFFIXES:
        cand = home + suffix
        out = subprocess.run(["wsl.exe", "--", "test", "-x", cand])
        if out.returncode == 0:
            return cand
    return None


def main():
    sources = []
    for d in DEVICE_DIRS:
        path = os.path.join(REPO, d)
        for name in sorted(os.listdir(path)):
            if name.endswith(".py"):
                sources.append(os.path.join(path, name))

    native = next((c for c in CANDIDATES if c and os.path.exists(c)), None)
    wsl_cmd = None if native else _find_via_wsl()
    if not native and not wsl_cmd:
        print("mpy-cross not found. Build it (make -C mpy-cross) and set "
              "MPY_CROSS, or install it with pip.")
        return 2

    bad = []
    for src in sources:
        if native:
            cmd = [native, "-o", os.devnull, src]
            res = subprocess.run(cmd, capture_output=True, text=True)
        else:
            res = subprocess.run(
                ["wsl.exe", "--", "bash", "-lc",
                 '"%s" -o /tmp/cpcheck.mpy "%s"'
                 % (wsl_cmd, _wsl_path(src))],
                capture_output=True, text=True)
        rel = os.path.relpath(src, REPO).replace("\\", "/")
        if res.returncode:
            bad.append(rel)
            print("  REJECTED %s" % rel)
            for line in (res.stderr or res.stdout).strip().splitlines()[:3]:
                print("      " + line)
        else:
            print("  ok       %s" % rel)

    print()
    if bad:
        print("%d file(s) CircuitPython will not compile: %s"
              % (len(bad), ", ".join(bad)))
        return 1
    print("all %d device sources compile for CircuitPython" % len(sources))
    return 0


if __name__ == "__main__":
    sys.exit(main())
