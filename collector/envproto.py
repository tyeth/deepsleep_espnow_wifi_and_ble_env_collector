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
  "cal"  node -> collector   forced-recalibration result

Data packet (node -> collector):
  {"v":1,"k":"dat","n":"kitchen","t":"scd4x","sq":42,"vb":3.87,
   "m":{"co2":612,"tc":21.4,"rh":48.2,"pm25":3.1,"voc":101,"nox":1}}

Config reply (collector -> node, unicast to the node's MAC):
  {"v":1,"k":"cfg","int":120,"asc":0,"m":["co2","tc","rh"],"cal":420}
  "int" sleep seconds, "asc" 0/1 automatic self calibration,
  "m" enabled metric keys, "cal" ONLY present when a forced CO2
  recalibration to that ppm target has been armed by the user.

Calibration result (node -> collector):
  {"v":1,"k":"cal","n":"kitchen","ok":1,"corr":-23}
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
    if obj.get("k") not in ("dsc", "dat", "cfg", "cal"):
        return None
    return obj


BROADCAST_MAC = b"\xff\xff\xff\xff\xff\xff"


def make_discovery_packet(name, sensor_type=None) -> bytes:
    pkt = {"k": "dsc", "n": name}
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
                       epoch=None) -> bytes:
    """Collector-side helper: build a 'cfg' reply for a node.

    epoch: hub's current time (only sent when the hub clock is synced via
    NTP or the browser) -- the time service for the whole mesh: nodes set
    their RTC from it and retro-adjust any stashed readings.
    """
    pkt = {"k": "cfg", "int": int(interval_s), "asc": 1 if asc else 0}
    if metrics:
        pkt["m"] = list(metrics)
    if cal_target:
        pkt["cal"] = int(cal_target)
    if epoch:
        pkt["t"] = int(epoch)
    return encode(pkt)


# node clocks tick from 2020 when unsynced; anything before this is bogus
PLAUSIBLE_EPOCH = 1700000000  # 2023-11


def make_cal_result_packet(name, ok, correction=None) -> bytes:
    pkt = {"k": "cal", "n": name, "ok": 1 if ok else 0}
    if correction is not None:
        pkt["corr"] = correction
    return encode(pkt)


def mac_str(mac_bytes) -> str:
    return ":".join("%02x" % b for b in mac_bytes)


def short_mac(mac_bytes) -> str:
    """Last 3 MAC bytes as uppercase hex -- used in default SSIDs/names
    (BASE{mac-hex} for the collector AP, SENSOR{mac-hex} for node portals,
    sensor-{mac-hex} for default node names)."""
    return "".join("%02X" % b for b in mac_bytes[-3:])
