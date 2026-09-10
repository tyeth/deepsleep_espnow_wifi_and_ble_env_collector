# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""Host-side checks for the BLE-advertisement reading format (envadv) and
the RTC-less clock (caps). Runs under CPython and under a CircuitPython
unix/native build alike:

    python tools/test_envadv.py
    micropython tools/test_envadv.py     (from the repo root)
"""

import sys
import time

sys.path.insert(0, "collector")
sys.path.insert(0, "node")

if not hasattr(time, "monotonic"):
    # the unix CircuitPython build has ticks_ms but no monotonic(); every
    # real board has both -- shim it for the host only
    class _Time:
        def __getattr__(self, n):
            return getattr(time, n)

        def monotonic(self):
            return time.ticks_ms() / 1000.0

        def monotonic_ns(self):
            return time.ticks_ms() * 1000000
    sys.modules["time"] = _Time()

import envadv  # noqa: E402

FAILURES = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILURES.append(name)


def main():
    print("envadv")
    m = {"tc": 21.37, "rh": 48.2, "co2": 612, "pm25": 3.1, "voc": 101, "nox": 1}
    adv = envadv.adv_bytes(42, m, 3.87, "scd4x")
    check("fits a legacy PDU (31 B): %d" % len(adv), len(adv) <= 31)
    check("starts with the flags structure", adv[:3] == b"\x02\x01\x06")
    # _bleio compares a prefix from the AD *type* byte (after the length):
    # shared-module/_bleio/ScanEntry.c bleio_scanentry_data_matches
    check("prefix filter matches the manufacturer structure",
          adv[4:4 + len(envadv.PREFIX) - 1] == envadv.PREFIX[1:])
    got = envadv.unpack(adv)
    check("unpacks", got is not None)
    seq, mm, vb, kind = got
    check("seq round-trips", seq == 42)
    check("kind round-trips", kind == "scd4x")
    check("battery to 1 mV", vb == 3.87)
    check("tc to 0.01", mm["tc"] == 21.37)
    check("rh to 0.01", mm["rh"] == 48.2)
    check("co2 exact", mm["co2"] == 612)
    check("pm25 to 0.1", mm["pm25"] == 3.1)
    check("voc/nox exact", mm["voc"] == 101 and mm["nox"] == 1)
    adv2 = envadv.adv_bytes(7, {"co2": 500}, None, "sen6x")
    seq2, mm2, vb2, kind2 = envadv.unpack(adv2)
    check("missing metrics are absent, not zero", set(mm2) == {"co2"} and vb2 is None)
    check("negative temperature", envadv.unpack(envadv.adv_bytes(1, {"tc": -4.5}))[1]["tc"] == -4.5)
    check("foreign manufacturer data is rejected",
          envadv.unpack(b"\x02\x01\x06\x05\xff\x4c\x00\x01\x02") is None)
    check("wrong magic is rejected",
          envadv.unpack(adv[:7] + b"\x00" + adv[8:]) is None)
    check("seq wraps at 256", envadv.unpack(envadv.adv_bytes(300, {"co2": 1}))[0] == 44)
    pkt = envadv.to_packet("ble-62AC", seq, mm, vb, kind)
    check("hub packet shape", pkt["k"] == "dat" and pkt["n"] == "ble-62AC"
          and pkt["sq"] == 42 and pkt["m"]["co2"] == 612 and pkt["vb"] == 3.87)

    print("caps clock without an RTC")
    import caps
    caps.HAS_RTC = False           # force the offset path even on a host
    caps._off_ns = None
    y0 = caps.localtime()[0]
    check("unsynced reads as year 2000 (%d)" % y0, y0 == 2000)
    check("not synced", not caps.synced())
    caps.set_epoch(1757400000)
    check("set_epoch takes effect", abs(caps.now() - 1757400000) <= 1)
    check("synced afterwards", caps.synced())
    check("localtime agrees", caps.localtime()[0] == 2025 and caps.localtime()[1] == 9)
    check("explicit localtime(secs)", caps.localtime(946684800)[0] == 2000)

    print("collector and node copies are identical")
    for name in ("envadv.py", "caps.py"):
        with open("collector/" + name, "rb") as f:
            a = f.read()
        with open("node/" + name, "rb") as f:
            b = f.read()
        check(name, a == b)

    print()
    if FAILURES:
        print("FAILED:", ", ".join(FAILURES))
        sys.exit(1)
    print("all checks passed")


main()
