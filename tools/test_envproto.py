# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""Host-side checks for the wire protocol (no hardware, no CircuitPython).

    python tools/test_envproto.py

Covers the delivery-confirmation scheme: CRC-16 against the standard test
vector, the collector's confirmation matching the node's expectation, and
the mismatch cases the node must treat as "not delivered".
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
import envproto  # noqa: E402

FAILURES = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILURES.append(name)


def main():
    print("crc16")
    check("standard vector 123456789 -> 0x29B1",
          envproto.crc16(b"123456789") == 0x29B1)
    check("str and bytes agree", envproto.crc16("abc") == envproto.crc16(b"abc"))
    check("single bit flip changes the crc",
          envproto.crc16(b"abc") != envproto.crc16(b"abd"))

    print("collector and node copies are identical")
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "..", "collector", "envproto.py"), "rb") as f:
        a = f.read()
    with open(os.path.join(here, "..", "node", "envproto.py"), "rb") as f:
        b = f.read()
    check("collector/envproto.py == node/envproto.py", a == b)

    print("data packet + confirmation")
    pkt = envproto.make_data_packet("kitchen", "sen66", 42, 3.87,
                                    {"co2": 612, "tc": 21.4, "rh": 48.2},
                                    at=1787595725)
    crc = envproto.crc16(pkt)
    check("fits an ESP-NOW frame", len(pkt) <= 250)
    check("decodes", envproto.decode(pkt)["sq"] == 42)
    cfg = envproto.decode(envproto.make_config_packet(
        120, epoch=1787595725, ack_id=42, ack_crc=crc))
    check("cfg confirms the packet", envproto.ack_ok(cfg, 42, crc))
    check("wrong crc is not a confirmation", not envproto.ack_ok(cfg, 42, crc ^ 1))
    check("wrong id is not a confirmation", not envproto.ack_ok(cfg, 41, crc))

    print("hub says it could not store it")
    nakcfg = envproto.decode(envproto.make_config_packet(
        120, ack_id=42, ack_crc=crc, ack_ok_flag=False))
    check("cfg with ok=0 is not a confirmation",
          not envproto.ack_ok(nakcfg, 42, crc))
    check("ok is omitted when all is well", "ok" not in cfg)

    print("hub rejection and bare acks")
    nak = envproto.decode(envproto.make_ack_packet(42, crc, ok=False,
                                                   why="store full"))
    check("ok=0 is not a confirmation", not envproto.ack_ok(nak, 42, crc))
    ack = envproto.decode(envproto.make_ack_packet(7, 0x1234))
    check("bare ack confirms", envproto.ack_ok(ack, 7, 0x1234))
    check("ack kind survives decode", ack["k"] == "ack")

    print("a cfg with no confirmation fields (old hub)")
    old = envproto.decode(envproto.make_config_packet(120))
    check("is not treated as a confirmation", not envproto.ack_ok(old, 1, 1))
    check("has no aq/ac to mistake", "aq" not in old and "ac" not in old)

    print("other node -> hub kinds carry a message id")
    dsc = envproto.decode(envproto.make_discovery_packet("kitchen", seq=9))
    check("dsc has sq", dsc.get("sq") == 9)
    cal = envproto.decode(envproto.make_cal_result_packet(
        "kitchen", True, correction=-23, ref=431, seq=11))
    check("cal has sq", cal.get("sq") == 11)

    print("full cfg with calibration fields still fits")
    big = envproto.make_config_packet(
        120, metrics=["co2", "tc", "rh", "pm25", "voc", "nox"],
        epoch=1787595725, cal_target=420, cal_at=1787630400, cal_dur=3600,
        cal_dry=True, cal_asc=True, ack_id=65535, ack_crc=65535, channel=13)
    check("cfg <= 250 bytes (%d)" % len(big), len(big) <= 250)
    check("cfg carries the hub channel", envproto.decode(big).get("ch") == 13)
    check("no channel field when unknown",
          "ch" not in envproto.decode(envproto.make_config_packet(120)))

    print()
    if FAILURES:
        print("%d FAILED: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
