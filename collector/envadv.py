# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
envadv - one sensor reading packed into a BLE *legacy advertisement*.

This exact file is deployed to BOTH the collector and the nodes (a copy
lives in collector/ and node/ -- keep them identical). It is deliberately
tiny and JSON-free: a Raspberry Pi Pico W node has tens of KB of heap at
most (~19.6 KB by the ELF arithmetic on the CircuitPython-11 rebase of the
firmware) and this is its whole transport.

Why a broadcast and not a connection. The reason this was first written
down -- "the controller allows one BLE connection" -- turned out to be
Zephyr's default CONFIG_BT_MAX_CONN=1, not a CYW43439 limit; upstream
zephyr-cp's prj.conf now sets 5 (the Pico 2 W builds with that), and the
Pico W board .conf brings it back to 2, though more than one at a time has
not yet been run on this controller -- and each one costs a Pico W ~1.1 KB
of static RAM it can ill afford.
What still holds: a node that only advertises needs no connection at
either end, no pairing, and no adafruit_ble on a board whose heap is
counted in tens of KB, and the hub can scan for it while advertising its
own UART service (a combination still to be run on hardware). So this
stays the transport for now, and a connection-based one (with ESP-NOW's message-id + CRC-16 confirmation
back) is the open alternative. The price of broadcast is that it is
fire-and-forget: there is no delivery confirmation and no cfg push back
to the node over this path; the node repeats the same advertisement for
its whole awake window so one missed packet costs nothing, and the hub
de-duplicates by (node id, seq).

**Who sent it is in the payload, not the address.** VERSION 1 left the node
to be named from the advertiser address, and that address is not the
board's: zephyr-cp's Adapter.c starts advertising with options=0, so for a
non-connectable set Zephyr's bt_id_set_adv_own_addr() picks a fresh
non-resolvable private address (NRPA) every time advertising starts
(BT_PRIVACY unset, no extended advertising to hold one per set). Every
reading arrived from a new "node" -- a new source every interval on the
hub, its 256-source cap reached in hours, and the node's WiFi POST (named
from its identity address) never matched its own advertisement. VERSION 2
carries the node id: 16 bits that the node takes from its own identity
address (node_lite._node_id), the same number it names its WiFi POST
from, so both paths land on the hub as the one source "ble-XXXX". The hub
ignores the advertiser address entirely.

Layout, all inside one Manufacturer Specific Data AD structure (0xFF) with
the Bluetooth SIG test company id 0xFFFF, plus the standard 3-byte flags:

  offset  size  field
  0       1     MAGIC (0xE7) -- also the hub's scan filter
  1       1     VERSION (2)
  2       2     node id       uint16 -- the hub's source is "ble-%04X"
  4       1     seq, wraps at 256, one per reading
  5       2     tc * 100      int16  (-32768 = none)
  7       2     rh * 100      uint16 (0xFFFF = none)
  9       2     co2 ppm       uint16
  11      2     pm25 * 10     uint16
  13      2     voc index     uint16
  15      2     nox index     uint16
  17      2     battery mV    uint16
  19      1     sensor type index into TYPES

Scaled fields are rounded, not truncated: 21.37 * 100 is 2136.9999... in
binary floating point, and int() would put 21.36 on air.

20 bytes of payload; + 4 for the AD structure's length and type bytes and
the 2-byte company id = 24; + 3 for the flags structure = 27 of the
31-byte legacy PDU. The controller here cannot do extended advertising
anyway (LE features bit 12 clear; CONFIG_BT_EXT_ADV=n), so the 4 bytes
left are the whole margin for any future field.
"""

import struct

COMPANY_ID = 0xFFFF
MAGIC = 0xE7
VERSION = 2
_FMT = "<BBHBhHHHHHHB"
SIZE = struct.calcsize(_FMT)                  # 20
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
    v = round(v * scale)      # round(float) is an int, here and on CPython
    return v if 0 <= v < _NOVAL else _NOVAL


def _enct(tc):
    # signed, and the one field that can be negative: out of int16 range
    # (a broken sensor's 400 C) is "none", as _enc does, not a struct.error
    if tc is None:
        return _NOTEMP
    v = round(tc * 100)
    return v if _NOTEMP < v < 0x8000 else _NOTEMP


def _dec(raw, scale=1):
    # unscaled fields (co2, voc, nox) stay ints, as they arrive over ESP-NOW
    if raw == _NOVAL:
        return None
    return raw if scale == 1 else raw / scale


def pack(node_id, seq, m, vb=None, kind="?"):
    """Payload bytes for one reading (m: envproto metric dict; node_id: the
    16-bit id the hub names this node by -- see the top of this file)."""
    try:
        t = TYPES.index(kind)
    except ValueError:
        t = 0
    return struct.pack(
        _FMT, MAGIC, VERSION, node_id & 0xFFFF, seq & 0xFF,
        _enct(m.get("tc")),
        _enc(m.get("rh"), 100), _enc(m.get("co2")),
        _enc(m.get("pm25"), 10), _enc(m.get("voc")), _enc(m.get("nox")),
        _enc(vb, 1000) if vb else _NOVAL, t)


def adv_bytes(node_id, seq, m, vb=None, kind="?"):
    """The complete advertising data: flags + manufacturer structure."""
    payload = pack(node_id, seq, m, vb, kind)
    return (FLAGS_AD
            + bytes([len(payload) + 3, 0xFF, COMPANY_ID & 0xFF, COMPANY_ID >> 8])
            + payload)


def src_for(node_id):
    """The hub's source name for a node id -- and the name node_lite gives
    its own WiFi POST, so the two paths are one source."""
    return "ble-%04X" % node_id


def unpack(adv):
    """Parse advertisement bytes. Returns (node_id, seq, metrics, vb, kind)
    for ours; None when they are not ours (wrong company id or magic) or
    are cut short; and a bare int -- the VERSION it carries -- when it is
    ours but a layout this copy cannot read (a node not yet updated, or a
    newer one), so the hub can say so instead of silently hearing nothing."""
    i = 0
    n = len(adv)
    while i + 1 < n:
        ln = adv[i]
        if ln == 0 or i + 1 + ln > n:
            return None
        if (adv[i + 1] == 0xFF and ln >= 5
                and adv[i + 2] | (adv[i + 3] << 8) == COMPANY_ID
                and adv[i + 4] == MAGIC):
            # the version before the length: VERSION 1 was 2 bytes shorter
            if adv[i + 5] != VERSION:
                return adv[i + 5]
            if ln < SIZE + 3:
                return None
            body = bytes(adv[i + 4:i + 4 + SIZE])
            _, _, nid, seq, tc, rh, co2, pm25, voc, nox, vb, t = \
                struct.unpack(_FMT, body)
            m = {"tc": None if tc == _NOTEMP else tc / 100,
                 "rh": _dec(rh, 100), "co2": _dec(co2),
                 "pm25": _dec(pm25, 10), "voc": _dec(voc), "nox": _dec(nox)}
            m = {k: v for k, v in m.items() if v is not None}
            return (nid, seq, m, _dec(vb, 1000),
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
