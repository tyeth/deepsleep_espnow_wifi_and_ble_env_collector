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
    NID = 0x62AC
    adv = envadv.adv_bytes(NID, 42, m, 3.87, "scd4x")
    check("payload is 20 B", envadv.SIZE == 20 and len(envadv.pack(NID, 1, m)) == 20)
    check("fits a legacy PDU (31 B): %d = 3 flags + 4 AD header + 20" % len(adv),
          len(adv) == 27 and len(adv) <= 31)
    check("starts with the flags structure", adv[:3] == b"\x02\x01\x06")
    # _bleio compares a prefix from the AD *type* byte (after the length):
    # shared-module/_bleio/ScanEntry.c bleio_scanentry_data_matches
    check("prefix filter matches the manufacturer structure",
          adv[4:4 + len(envadv.PREFIX) - 1] == envadv.PREFIX[1:])
    check("layout: VERSION 2, node id LE at payload offset 2, seq at 4",
          adv[7] == envadv.MAGIC and adv[8] == 2 and adv[9] == 0xAC
          and adv[10] == 0x62 and adv[11] == 42)
    got = envadv.unpack(adv)
    check("unpacks", isinstance(got, tuple))
    nid, seq, mm, vb, kind = got
    check("node id round-trips", nid == NID)
    check("seq round-trips", seq == 42)
    check("kind round-trips", kind == "scd4x")
    check("battery to 1 mV", vb == 3.87)
    check("tc to 0.01", mm["tc"] == 21.37)
    check("rh to 0.01", mm["rh"] == 48.2)
    check("co2 exact", mm["co2"] == 612)
    check("pm25 to 0.1", mm["pm25"] == 3.1)
    check("voc/nox exact", mm["voc"] == 101 and mm["nox"] == 1)
    check("unscaled fields stay ints, as over ESP-NOW",
          all(isinstance(mm[k], int) for k in ("co2", "voc", "nox")))
    # values whose scaled float sits just under the integer: int() put
    # 19.98 / 0.28 / 0.5 on air, round() the reading itself
    r = envadv.unpack(envadv.adv_bytes(1, 1, {"tc": 19.99, "rh": 0.29,
                                              "pm25": 0.57}))
    check("scaled fields rounded, not truncated (tc %r rh %r pm25 %r)"
          % (r[2]["tc"], r[2]["rh"], r[2]["pm25"]),
          r[2]["tc"] == 19.99 and r[2]["rh"] == 0.29 and r[2]["pm25"] == 0.6)
    check("int() would have truncated these (the test is a real one)",
          int(19.99 * 100) == 1998 and int(0.29 * 100) == 28
          and int(0.57 * 10) == 5)
    check("negative temperature rounds too",
          envadv.unpack(envadv.adv_bytes(1, 1, {"tc": -16.15}))[2]["tc"] == -16.15)
    check("out-of-range temperature is 'none', not a struct.error",
          "tc" not in envadv.unpack(envadv.adv_bytes(1, 1, {"tc": 400.0, "co2": 1}))[2])
    check("a simulated sensor says so on air",
          envadv.unpack(envadv.adv_bytes(1, 1, {"co2": 1}, None, "sim"))[4] == "sim")
    adv2 = envadv.adv_bytes(NID, 7, {"co2": 500}, None, "sen6x")
    _, seq2, mm2, vb2, kind2 = envadv.unpack(adv2)
    check("missing metrics are absent, not zero", set(mm2) == {"co2"} and vb2 is None)
    check("negative temperature", envadv.unpack(envadv.adv_bytes(1, 1, {"tc": -4.5}))[2]["tc"] == -4.5)
    check("foreign manufacturer data is rejected",
          envadv.unpack(b"\x02\x01\x06\x05\xff\x4c\x00\x01\x02") is None)
    check("wrong magic is rejected",
          envadv.unpack(adv[:7] + b"\x00" + adv[8:]) is None)
    check("seq wraps at 256", envadv.unpack(envadv.adv_bytes(1, 300, {"co2": 1}))[1] == 44)
    check("node id is 16 bits", envadv.unpack(envadv.adv_bytes(0x162AC, 1, {"co2": 1}))[0] == 0x62AC)
    # a VERSION 1 advertisement, built the way the old envadv built it
    import struct
    v1p = struct.pack("<BBBhHHHHHHB", 0xE7, 1, 42, 2137, 4820, 612, 31,
                      101, 1, 3870, 1)
    v1 = b"\x02\x01\x06" + bytes([len(v1p) + 3, 0xFF, 0xFF, 0xFF]) + v1p
    check("an old (VERSION 1) node is recognised as ours-but-old: %r"
          % (envadv.unpack(v1),), envadv.unpack(v1) == 1)
    check("a truncated current one is not ours", envadv.unpack(adv[:-3]) is None)
    pkt = envadv.to_packet("ble-62AC", seq, mm, vb, kind)
    check("hub packet shape", pkt["k"] == "dat" and pkt["n"] == "ble-62AC"
          and pkt["sq"] == 42 and pkt["m"]["co2"] == 612 and pkt["vb"] == 3.87)

    print("node id from the payload, not the (random) address")
    import net_blescan
    check("src_for is ble-%04X", envadv.src_for(0x62AC) == "ble-62AC"
          and net_blescan.AdvReceiver.src_for(0x00AB) == "ble-00AB")

    class _Adapter:
        enabled = False

        def __init__(self, advs):
            self.advs = advs

        def start_scan(self, *a, **k):
            # each entry from a different NRPA, the way zephyr-cp sends a
            # non-connectable set: a new random address per advertising start
            for i, a in enumerate(self.advs):
                yield type("E", (), {"advertisement_bytes": a, "rssi": -50,
                                     "address": type("A", (), {
                                         "address_bytes": bytes([i, i * 7 & 0xFF, 0x11,
                                                                 0x22, 0x33, 0x40 | i])})})()

        def stop_scan(self):
            pass

    rx = net_blescan.AdvReceiver()      # no _bleio on a host: ok=False
    rx.ok = True
    rx.adapter = _Adapter([envadv.adv_bytes(NID, s, {"co2": 600 + s})
                           for s in (1, 1, 1, 2, 2, 3)] + [v1, v1])
    rx.scan_s = 60
    got = list(rx.poll())
    check("three readings from six advertisements on six addresses: %d" % len(got),
          len(got) == 3 and rx.dup_count == 3)
    check("one source for all of them", set(g[0] for g in got) == {"ble-62AC"})
    check("de-dup state is per node, not per address: %r" % (rx.last_seq,),
          rx.last_seq == {NID: 3})
    check("old-VERSION advertisements dropped and counted", rx.old_count == 2)

    print("caps clock without an RTC")
    import caps
    caps.HAS_RTC = False           # force the offset path even on a host
    caps._off_ns = None
    # 2000-01-01 + uptime, like a fresh RTC. Compared as an epoch: a host's
    # localtime() applies its own zone (CircuitPython's never does), and
    # west of UTC a host up for less than a day would read 1999.
    check("unsynced counts from 2000-01-01",
          946684800 <= caps.now() < 1700000000)
    check("not synced", not caps.synced())
    caps.set_epoch(1757400000)
    check("set_epoch takes effect", abs(caps.now() - 1757400000) <= 1)
    check("synced afterwards", caps.synced())
    check("localtime agrees", caps.localtime()[0] == 2025 and caps.localtime()[1] == 9)
    check("explicit localtime(secs)", caps.localtime(1757400000)[:2] == (2025, 9))
    caps.set_datetime(time.localtime(1757500000))     # what NTP hands over
    check("set_datetime takes a struct_time",
          abs(caps.now() - 1757500000) <= 1)

    print("caps.time: the time module where time.time() cannot work")
    t = caps._NoRtcTime()
    check("time() is caps' clock", abs(t.time() - caps.now()) <= 1)
    check("zero-arg localtime() works", t.localtime()[0] == 2025)
    check("monotonic() is the real one",
          abs(t.monotonic() - time.monotonic()) < 1)
    check("sleep/mktime/struct_time carried over",
          t.sleep is time.sleep and t.mktime is time.mktime
          and t.struct_time is time.struct_time)
    check("on a host with no rtc module, caps.time is the stand-in",
          caps.has("rtc") or isinstance(caps.time, caps._NoRtcTime))

    print("collector and node copies are identical")
    for name in ("envadv.py", "caps.py", "extrtc.py"):
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
