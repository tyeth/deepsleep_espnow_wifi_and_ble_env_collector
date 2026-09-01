# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
envproto - shared wire protocol between the collector hub and sensor nodes.

This exact file is deployed to BOTH the collector and the nodes (a copy lives
in collector/ and node/ -- keep them identical).

Transport: ESP-NOW (primary, <=250 byte payloads) or HTTP POST /api/ingest
(fallback). Payloads are compact JSON so they stay human-debuggable.

Packet kinds ("k"):
  "dsc"  node -> broadcast   collector discovery ("any BASE out there?")
  "dat"  node -> collector   sensor readings
  "cfg"  collector -> node   config push (reply to a "dat" OR a "dsc" --
                             the node learns the collector's MAC + channel
                             from the reply, making ESP-NOW self-configuring)
                             and the delivery confirmation for that packet
  "ack"  collector -> node   bare delivery confirmation (kinds with no cfg)
  "cal"  node -> collector   forced-recalibration result

Every node -> collector packet carries "sq", a message id unique per
TRANSMISSION (not per reading: a stashed reading retransmitted later gets a
fresh id). The collector confirms with "aq" (that id) + "ac" (CRC-16/CCITT
of the bytes it received) + "ok". See "Delivery confirmation" below.

Data packet (node -> collector):
  {"v":1,"k":"dat","n":"kitchen","t":"scd4x","sq":42,"vb":3.87,
   "m":{"co2":612,"tc":21.4,"rh":48.2,"pm25":3.1,"voc":101,"nox":1}}

Config reply (collector -> node, unicast to the node's MAC):
  {"v":1,"k":"cfg","int":120,"asc":0,"m":["co2","tc","rh"],"t":1787595725,
   "cal":420,"cat":1787630400,"cdur":3600,"cdry":0,
   "aq":42,"ac":51966,"ok":1}
  "int" sleep seconds, "asc" 0/1 automatic self calibration (always 0),
  "m" enabled metric keys, "t" hub epoch (time service). Calibration
  fields are ONLY present while the user has armed a reference
  calibration: "cal" target ppm, "cat" epoch at which the measurement
  window starts (absent/0 = now), "cdur" window length in seconds,
  "cdry" 1 = dry run (measure + stability check, never write the FRC),
  "casc" 1 = ASC mode: enable the sensor's automatic self-calibration for
  the window (keep measuring), then disable it again -- no FRC written.

Calibration result (node -> collector):
  {"v":1,"k":"cal","n":"kitchen","ok":1,"corr":-23,"ref":431,"why":""}
  "ref" = median CO2 the sensor saw in the window (its idea of fresh
  air), "why" = failure reason (unstable / not fresh air / battery / ...)
"""

import json

PROTO_VERSION = 1

# Canonical metric keys (short to keep ESP-NOW payloads small)
# tc: temperature C, rh: humidity %, co2: ppm, pm*: ug/m3,
# voc/nox: Sensirion index, vb: battery volts
METRICS = ("tc", "rh", "co2", "pm1", "pm25", "pm4", "pm10", "voc", "nox")

METRIC_LABELS = {
    "tc": "Temp",
    "rh": "Humid",
    "co2": "CO2",
    "pm1": "PM1.0",
    "pm25": "PM2.5",
    "pm4": "PM4.0",
    "pm10": "PM10",
    "voc": "VOC",
    "nox": "NOx",
    "vb": "Batt",
}

METRIC_UNITS = {
    "tc": "C",
    "rh": "%",
    "co2": "ppm",
    "pm1": "ug",
    "pm25": "ug",
    "pm4": "ug",
    "pm10": "ug",
    "voc": "",
    "nox": "",
    "vb": "V",
}


def encode(obj) -> bytes:
    """Encode a packet dict to wire bytes. Raises ValueError if oversized."""
    obj["v"] = PROTO_VERSION
    raw = json.dumps(obj).encode()
    if len(raw) > 250:
        raise ValueError("packet too large for ESP-NOW: %d bytes" % len(raw))
    return raw


def decode(raw):
    """Decode wire bytes to a dict, or None if not one of ours."""
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("v") != PROTO_VERSION:
        return None
    if obj.get("k") not in ("dsc", "dat", "cfg", "cal", "ack"):
        return None
    return obj


# --------------------------------------------------------------------------
# Delivery confirmation
#
# The ESP-NOW MAC-layer ACK only proves a frame reached the hub's radio -- it
# says nothing about whether the hub decoded, accepted and stored the packet
# (a truncated frame, a JSON error, a full SD card and a busy main loop all
# look "delivered" to the sender). So every node->hub packet carries a
# message id ("sq") and the hub answers with that id plus the CRC-16 of the
# bytes it actually received. The node only counts a reading as delivered --
# and only then drops it from the stash -- when id AND CRC match what it
# sent. Anything else is a retry, then the WiFi fallback.
# --------------------------------------------------------------------------

# CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF), nibble table: 16 entries
# instead of 256 (kind to node RAM) and ~4x faster than the bitwise loop.
_CRC_TAB = (
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
    0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
)


def crc16(data) -> int:
    """CRC-16/CCITT-FALSE over bytes (or a str, which is encoded first)."""
    if isinstance(data, str):
        data = data.encode()
    crc = 0xFFFF
    for byte in data:
        crc = ((crc << 4) & 0xFFFF) ^ _CRC_TAB[((crc >> 12) ^ (byte >> 4)) & 0x0F]
        crc = ((crc << 4) & 0xFFFF) ^ _CRC_TAB[((crc >> 12) ^ (byte & 0x0F)) & 0x0F]
    return crc


def make_ack_packet(msg_id, crc, ok=True, why=None) -> bytes:
    """Bare confirmation (used for packet kinds that get no 'cfg' reply)."""
    pkt = {"k": "ack", "aq": int(msg_id or 0), "ac": int(crc),
           "ok": 1 if ok else 0}
    if why:
        pkt["why"] = why[:40]
    return encode(pkt)


def ack_ok(obj, msg_id, crc) -> bool:
    """True if obj confirms OUR packet: right id, right CRC, hub says ok."""
    if not obj:
        return False
    if obj.get("k") not in ("cfg", "ack"):
        return False
    if "aq" not in obj or "ac" not in obj:
        return False   # hub too old to confirm -- caller decides
    return (int(obj["aq"]) == int(msg_id or 0)
            and int(obj["ac"]) == int(crc)
            and bool(obj.get("ok", 1)))


BROADCAST_MAC = b"\xff\xff\xff\xff\xff\xff"


def make_discovery_packet(name, sensor_type=None, seq=None) -> bytes:
    pkt = {"k": "dsc", "n": name, "sq": int(seq or 0)}
    if sensor_type:
        pkt["t"] = sensor_type
    return encode(pkt)


def make_data_packet(name, sensor_type, seq, batt_v, measurements,
                     at=None) -> bytes:
    """Node-side helper: build a 'dat' packet, dropping None values.

    at: epoch seconds the reading was TAKEN (may differ from send time for
    stashed/retransmitted readings). The collector ignores implausible
    values (unsynced node clocks) and falls back to receive time.
    """
    m = {}
    for key, val in measurements.items():
        if val is None or key not in METRICS:
            continue
        # round floats to keep payload small
        m[key] = round(val, 2) if isinstance(val, float) else val
    pkt = {"k": "dat", "n": name, "t": sensor_type, "sq": seq, "m": m}
    if batt_v is not None:
        pkt["vb"] = round(batt_v, 3)
    if at:
        pkt["at"] = int(at)
    return encode(pkt)


def make_config_packet(interval_s, metrics=None, asc=False, cal_target=None,
                       epoch=None, cal_at=None, cal_dur=None, cal_dry=False,
                       cal_asc=False, ack_id=None, ack_crc=None,
                       ack_ok_flag=True) -> bytes:
    """Collector-side helper: build a 'cfg' reply for a node.

    epoch: hub's current time (only sent when the hub clock is synced via
    NTP or the browser) -- the time service for the whole mesh: nodes set
    their RTC from it and retro-adjust any stashed readings.

    ack_id/ack_crc: confirmation of the packet this is a reply to (message
    id + CRC-16 of the received bytes). The cfg reply doubles as the ack so
    a check-in stays one packet each way.
    """
    pkt = {"k": "cfg", "int": int(interval_s), "asc": 1 if asc else 0}
    if ack_crc is not None:
        pkt["aq"] = int(ack_id or 0)
        pkt["ac"] = int(ack_crc)
        pkt["ok"] = 1 if ack_ok_flag else 0
    if metrics:
        pkt["m"] = list(metrics)
    if cal_target:
        pkt["cal"] = int(cal_target)
        if cal_at:
            pkt["cat"] = int(cal_at)
        if cal_dur:
            pkt["cdur"] = int(cal_dur)
        if cal_dry:
            pkt["cdry"] = 1
        if cal_asc:
            pkt["casc"] = 1
    if epoch:
        pkt["t"] = int(epoch)
    return encode(pkt)


# node clocks tick from 2020 when unsynced; anything before this is bogus
PLAUSIBLE_EPOCH = 1700000000  # 2023-11


def make_cal_result_packet(name, ok, correction=None, ref=None,
                           reason=None, ref0=None, seq=None) -> bytes:
    pkt = {"k": "cal", "n": name, "ok": 1 if ok else 0, "sq": int(seq or 0)}
    if ref0 is not None:
        pkt["ref0"] = int(ref0)
    if correction is not None:
        pkt["corr"] = correction
    if ref is not None:
        pkt["ref"] = int(ref)
    if reason:
        pkt["why"] = reason[:40]
    return encode(pkt)


def mac_str(mac_bytes) -> str:
    return ":".join("%02x" % b for b in mac_bytes)


def short_mac(mac_bytes) -> str:
    """Last 3 MAC bytes as uppercase hex -- used in default SSIDs/names
    (BASE{mac-hex} for the collector AP, SENSOR{mac-hex} for node portals,
    sensor-{mac-hex} for default node names)."""
    return "".join("%02X" % b for b in mac_bytes[-3:])
