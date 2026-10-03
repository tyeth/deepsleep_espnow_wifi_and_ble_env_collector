# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
envadv - one sensor reading packed into a BLE *legacy advertisement*.

This exact file is deployed to BOTH the collector and the nodes (a copy
lives in collector/ and node/ -- keep them identical). It is deliberately
tiny and JSON-free: a Raspberry Pi Pico W node has tens of KB of heap at
most (~16.5 KB by the ELF arithmetic on the CircuitPython-11 rebase of the
firmware) and this is its whole transport.

Why a broadcast and not a connection. The reason this was first written
down -- "the controller allows one BLE connection" -- turned out to be
Zephyr's default CONFIG_BT_MAX_CONN=1, not a CYW43439 limit; the
firmware now builds with 5 (upstream zephyr-cp prj.conf, after the fork's
own 4 in tyeth/circuitpython#19), though more than one at a time has not
yet been run on this controller -- and each one costs a Pico W ~2.9 KB of
static RAM it can ill afford.
What still holds: a node that only advertises needs no connection at
either end, no pairing, and no adafruit_ble on a board whose heap is
counted in tens of KB, and the hub can scan for it while advertising its
own UART service (a combination still to be run on hardware). So this
stays the transport for now, and a connection-based one (with ESP-NOW's message-id + CRC-16 confirmation
back) is the open alternative. The price of broadcast is that it is
fire-and-forget: there is no delivery confirmation and no cfg push back
to the node over this path; the node repeats the same advertisement for
its whole awake window so one missed packet costs nothing, and the hub
de-duplicates by (address, seq).

Layout, all inside one Manufacturer Specific Data AD structure (0xFF) with
the Bluetooth SIG test company id 0xFFFF, plus the standard 3-byte flags:

  offset  size  field
  0       1     MAGIC (0xE7) -- also the hub's scan filter
  1       1     VERSION (1)
  2       1     seq, wraps at 256, one per reading
  3       2     tc * 100      int16  (-32768 = none)
  5       2     rh * 100      uint16 (0xFFFF = none)
  7       2     co2 ppm       uint16
  9       2     pm25 * 10     uint16
  11      2     voc index     uint16
  13      2     nox index     uint16
  15      2     battery mV    uint16
  17      1     sensor type index into TYPES

18 bytes of payload, 22 with the AD header + company id, 25 with the flags
structure: inside the 31-byte legacy PDU with room to spare, and the
controller here cannot do extended advertising anyway (LE features bit 12
clear; CONFIG_BT_EXT_ADV=n).
"""

import struct

COMPANY_ID = 0xFFFF
MAGIC = 0xE7
VERSION = 1
_FMT = "<BBBhHHHHHHB"
SIZE = struct.calcsize(_FMT)                  # 18
# Append only: the index is what goes on air. "sim" is node_sensors'
# SimSensor, kept distinct so invented bench numbers are never mistaken on
# the hub for a measurement.
TYPES = ("?", "scd4x", "scd30", "sen5x", "sen6x", "sim")
_NOVAL = 0xFFFF
_NOTEMP = -0x8000

# What the hub hands _bleio.Adapter.start_scan(prefixes=...): a length byte
# then the start of the AD structure -- type 0xFF, company id, MAGIC.
PREFIX = bytes([4, 0xFF, COMPANY_ID & 0xFF, COMPANY_ID >> 8, MAGIC])
FLAGS_AD = b"\x02\x01\x06"


def _enc(v, scale=1):
    if v is None:
        return _NOVAL
    v = int(v * scale)
    return v if 0 <= v < _NOVAL else _NOVAL


def _dec(raw, scale=1):
    # unscaled fields (co2, voc, nox) stay ints, as they arrive over ESP-NOW
    if raw == _NOVAL:
        return None
    return raw if scale == 1 else raw / scale


def pack(seq, m, vb=None, kind="?"):
    """Payload bytes for one reading (m: envproto metric dict)."""
    tc = m.get("tc")
    try:
        t = TYPES.index(kind)
    except ValueError:
        t = 0
    return struct.pack(
        _FMT, MAGIC, VERSION, seq & 0xFF,
        int(tc * 100) if tc is not None else _NOTEMP,
        _enc(m.get("rh"), 100), _enc(m.get("co2")),
        _enc(m.get("pm25"), 10), _enc(m.get("voc")), _enc(m.get("nox")),
        _enc(vb, 1000) if vb else _NOVAL, t)


def adv_bytes(seq, m, vb=None, kind="?"):
    """The complete advertising data: flags + manufacturer structure."""
    payload = pack(seq, m, vb, kind)
    return (FLAGS_AD
            + bytes([len(payload) + 3, 0xFF, COMPANY_ID & 0xFF, COMPANY_ID >> 8])
            + payload)


def unpack(adv):
    """Parse advertisement bytes. Returns (seq, metrics, vb, kind) or None
    when they are not ours (wrong company id, magic or version)."""
    i = 0
    n = len(adv)
    while i + 1 < n:
        ln = adv[i]
        if ln == 0 or i + 1 + ln > n:
            return None
        if (adv[i + 1] == 0xFF and ln >= SIZE + 3
                and adv[i + 2] | (adv[i + 3] << 8) == COMPANY_ID):
            body = bytes(adv[i + 4:i + 4 + SIZE])
            magic, ver, seq, tc, rh, co2, pm25, voc, nox, vb, t = \
                struct.unpack(_FMT, body)
            if magic != MAGIC or ver != VERSION:
                return None
            m = {"tc": None if tc == _NOTEMP else tc / 100,
                 "rh": _dec(rh, 100), "co2": _dec(co2),
                 "pm25": _dec(pm25, 10), "voc": _dec(voc), "nox": _dec(nox)}
            m = {k: v for k, v in m.items() if v is not None}
            return (seq, m, _dec(vb, 1000),
                    TYPES[t] if t < len(TYPES) else "?")
        i += 1 + ln
    return None


def to_packet(src, seq, m, vb, kind):
    """The envproto 'dat' dict the hub's node-packet path already accepts
    (no 'at': broadcast readings are timestamped on receipt)."""
    pkt = {"v": 1, "k": "dat", "n": src, "t": kind, "sq": seq, "m": m}
    if vb is not None:
        pkt["vb"] = vb
    return pkt
