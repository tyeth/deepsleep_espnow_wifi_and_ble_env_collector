# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
envadv - one sensor reading packed into a BLE *legacy advertisement*.

This exact file is deployed to BOTH the collector and the nodes (a copy
lives in collector/ and node/ -- keep them identical). It is deliberately
tiny and JSON-free: a Raspberry Pi Pico W node has ~40 KB of heap in total
and this is its whole transport.

Why a broadcast and not a connection: the CYW43439 controller on the Pico W
/ Pico 2 W is built with CONFIG_BT_MAX_CONN=1, so a hub that connected to
its nodes could not also serve a phone over the BLE UART. A node that only
advertises consumes no connection at either end, needs no pairing and no
adafruit_ble (whose import alone costs more heap than the Pico W has), and
the hub can keep scanning while it advertises its own UART service. The
price: broadcast is fire-and-forget. There is no delivery confirmation and
no cfg push back to the node over this path; the node repeats the same
advertisement for its whole awake window so one missed packet costs
nothing, and the hub de-duplicates by (address, seq).

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
TYPES = ("?", "scd4x", "scd30", "sen5x", "sen6x")
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
    return None if raw == _NOVAL else raw / scale


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
