# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
Deep-sleeping environmental sensor node.

Built on the repo's deep_sleep.py pattern: wake -> read sensor -> report ->
deep sleep, with state carried across sleeps in alarm.sleep_memory.

Transport: ESP-NOW unicast to the collector's MAC (with automatic WiFi
channel discovery -- the node hunts 1..13 until the collector's radio ACKs,
then remembers the channel in sleep memory). Optional WiFi POST fallback.

After every report the node listens briefly for the collector's 'cfg' reply
and applies it: sleep interval, enabled metrics, ASC policy (always off),
and -- when the user has armed it via the hub -- a forced CO2 recalibration
(node must already be outside per the step-1 warning).

Config: node_config.json (no display; WiFi/files only, per spec).
"""

import json
import time

import alarm
import board
import espnow

import envproto
import node_sensors
from battery import BatteryMonitor

# --------------------------------------------------------------------------
# sleep_memory layout
# --------------------------------------------------------------------------
MEM_MAGIC = 0        # 0xE7 when initialised
MEM_CHANNEL = 1      # discovered WiFi channel (0 = unknown)
MEM_INTERVAL = 2     # uint16 LE, collector-pushed interval (0 = use config)
MEM_SEQ = 4          # uint16 LE packet sequence
MEM_ASC_DONE = 6     # ASC has been forced off on the sensor
MEM_BOOTS = 7        # wrap-around boot counter
MAGIC = 0xE7


def mem_get_u16(off):
    return alarm.sleep_memory[off] | (alarm.sleep_memory[off + 1] << 8)


def mem_set_u16(off, val):
    alarm.sleep_memory[off] = val & 0xFF
    alarm.sleep_memory[off + 1] = (val >> 8) & 0xFF


if alarm.sleep_memory[MEM_MAGIC] != MAGIC:
    for i in range(8):
        alarm.sleep_memory[i] = 0
    alarm.sleep_memory[MEM_MAGIC] = MAGIC

alarm.sleep_memory[MEM_BOOTS] = (alarm.sleep_memory[MEM_BOOTS] + 1) % 256
print("wake:", alarm.wake_alarm, "boot#", alarm.sleep_memory[MEM_BOOTS])

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
DEFAULTS = {
    "name": "node1",
    "collector_mac": "",          # REQUIRED: "aa:bb:cc:dd:ee:ff"
    "interval_s": 120,
    "metrics": None,               # None = send everything the sensor has
    "pm_warmup_s": 20,             # extra fan spin-up for SEN5x/SEN6x PM
    "cal_measure_s": 180,          # measurement time before forced recal
    "wifi_fallback": False,
    "collector_url": "",          # e.g. "http://192.168.1.50"
    "led": False,
}

config = dict(DEFAULTS)
try:
    with open("/node_config.json") as f:
        config.update(json.load(f))
except (OSError, ValueError) as exc:
    print("node_config.json missing/bad, using defaults:", exc)

COLLECTOR_MAC = bytes(
    int(x, 16) for x in config["collector_mac"].split(":")
) if config["collector_mac"] else None

interval = mem_get_u16(MEM_INTERVAL) or config["interval_s"]


def blink(ok=True):
    if not config.get("led"):
        return
    try:
        import neopixel
        px = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.05)
        px[0] = (0, 255, 0) if ok else (255, 0, 0)
        time.sleep(0.15)
        px[0] = (0, 0, 0)
        px.deinit()
    except (ImportError, AttributeError):
        pass


def go_to_sleep(seconds):
    print("deep sleep %ds" % seconds)
    t = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + seconds)
    alarm.exit_and_deep_sleep_until_alarms(t)


# --------------------------------------------------------------------------
# Sensor
# --------------------------------------------------------------------------
i2c = board.I2C()
sensor = node_sensors.detect(i2c)
if sensor is None:
    print("no sensor found; retrying in %ds" % interval)
    blink(False)
    go_to_sleep(interval)

print("sensor:", sensor.kind)

# Project policy: automatic self calibration OFF. Done once (flag in sleep
# memory) -- some sensors persist this setting and repeated writes are wear.
if not alarm.sleep_memory[MEM_ASC_DONE]:
    try:
        sensor.set_asc(False)
        alarm.sleep_memory[MEM_ASC_DONE] = 1
        print("ASC disabled")
    except (OSError, RuntimeError) as exc:
        print("ASC disable failed (will retry next wake):", exc)

try:
    sensor.begin()
except (OSError, RuntimeError) as exc:
    print("sensor begin failed:", exc)

warmup = config["pm_warmup_s"] if sensor.kind in ("sen5x", "sen6x") else 0
if warmup:
    time.sleep(warmup)

metrics = sensor.read()
if metrics is None:
    print("sensor read timed out")
    metrics = {}

# metric filtering (collector/user chooses what this node reports)
enabled = config.get("metrics")
if enabled:
    metrics = {k: v for k, v in metrics.items() if k in enabled}

batt = BatteryMonitor(i2c)
batt_v = batt.voltage()
print("read:", metrics, "batt:", batt_v)

# --------------------------------------------------------------------------
# ESP-NOW: send + channel discovery + cfg reply
# --------------------------------------------------------------------------
seq = (mem_get_u16(MEM_SEQ) + 1) % 65536
mem_set_u16(MEM_SEQ, seq)
packet = envproto.make_data_packet(
    config["name"], sensor.kind, seq, batt_v, metrics
)


def _try_send(e, peer, payload):
    """Send and report MAC-layer ACK using the phy counters when available."""
    before = getattr(e, "send_success", None)
    try:
        e.send(payload, peer)
    except (RuntimeError, OSError, ValueError) as exc:
        print("send raised:", exc)
        return False
    after = getattr(e, "send_success", None)
    if before is None or after is None:
        return True  # no counters on this port; assume sent
    return after > before


def espnow_report():
    """Returns (sent_ok, cfg_dict_or_None)."""
    if COLLECTOR_MAC is None:
        print("no collector_mac configured!")
        return False, None
    e = espnow.ESPNow()
    try:
        saved = alarm.sleep_memory[MEM_CHANNEL]
        channels = ([saved] if saved else []) + [
            c for c in range(1, 14) if c != saved
        ]
        peer = None
        sent = False
        for ch in channels:
            if peer is None:
                peer = espnow.Peer(mac=COLLECTOR_MAC, channel=ch)
                e.peers.append(peer)
            else:
                try:
                    peer.channel = ch
                except (AttributeError, ValueError):
                    # port doesn't allow mutating channel: rebuild peer
                    e.peers.remove(peer)
                    peer = espnow.Peer(mac=COLLECTOR_MAC, channel=ch)
                    e.peers.append(peer)
            if _try_send(e, peer, packet):
                if alarm.sleep_memory[MEM_CHANNEL] != ch:
                    alarm.sleep_memory[MEM_CHANNEL] = ch
                    print("locked channel", ch)
                sent = True
                break
        if not sent:
            alarm.sleep_memory[MEM_CHANNEL] = 0
            return False, None
        # listen briefly for the collector's cfg reply
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if len(e):
                pkt = e.read()
                obj = envproto.decode(pkt.msg) if pkt else None
                if obj and obj.get("k") == "cfg":
                    return True, obj
            time.sleep(0.02)
        return True, None
    finally:
        e.deinit()


def wifi_report():
    """Fallback: POST the same packet to the collector's HTTP API."""
    if not (config.get("wifi_fallback") and config.get("collector_url")):
        return False, None
    try:
        import os
        import wifi
        import socketpool
        import adafruit_connection_manager
        import adafruit_requests
        ssid = os.getenv("CIRCUITPY_WIFI_SSID") or os.getenv("WIFI_SSID")
        pw = os.getenv("CIRCUITPY_WIFI_PASSWORD") or os.getenv("WIFI_PASSWORD")
        if not wifi.radio.connected:
            wifi.radio.connect(ssid, pw or "", timeout=15)
        pool = socketpool.SocketPool(wifi.radio)
        ssl_ctx = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
        requests = adafruit_requests.Session(pool, ssl_ctx)
        resp = requests.post(config["collector_url"] + "/api/ingest",
                             data=packet, timeout=10)
        cfg = None
        try:
            cfg = resp.json().get("cfg")
        except (ValueError, AttributeError):
            pass
        resp.close()
        return True, cfg
    except Exception as exc:
        print("wifi fallback failed:", exc)
        return False, None


sent, cfg = espnow_report()
if not sent:
    sent, cfg = wifi_report()

# --------------------------------------------------------------------------
# Apply collector config
# --------------------------------------------------------------------------
if cfg:
    new_int = int(cfg.get("int", 0))
    if 10 <= new_int <= 65535 and new_int != interval:
        mem_set_u16(MEM_INTERVAL, new_int)
        interval = new_int
        print("interval ->", new_int)
    if cfg.get("asc") == 0 and not alarm.sleep_memory[MEM_ASC_DONE]:
        try:
            sensor.set_asc(False)
            alarm.sleep_memory[MEM_ASC_DONE] = 1
        except (OSError, RuntimeError):
            pass
    cal_target = cfg.get("cal")
    if cal_target:
        # User armed forced recalibration (they were warned to go outside at
        # step 1). Measure in fresh air for cal_measure_s, then recalibrate.
        print("FORCED RECAL to %dppm: measuring %ds first..."
              % (cal_target, config["cal_measure_s"]))
        end = time.monotonic() + config["cal_measure_s"]
        while time.monotonic() < end:
            sensor.read(timeout_s=5)
            time.sleep(5)
        ok = True
        corr = None
        try:
            corr = sensor.force_recal(cal_target)
            print("recal done, correction:", corr)
        except (OSError, RuntimeError, AttributeError) as exc:
            ok = False
            print("recal failed:", exc)
        result = envproto.make_cal_result_packet(config["name"], ok, corr)
        e2 = espnow.ESPNow()
        try:
            ch = alarm.sleep_memory[MEM_CHANNEL] or 1
            p2 = espnow.Peer(mac=COLLECTOR_MAC, channel=ch)
            e2.peers.append(p2)
            e2.send(result, p2)
        except (RuntimeError, OSError, ValueError) as exc:
            print("cal result send failed:", exc)
        finally:
            e2.deinit()

blink(sent)

# --------------------------------------------------------------------------
# Sleep
# --------------------------------------------------------------------------
try:
    sensor.stop()
except (OSError, RuntimeError):
    pass

if not sent:
    # back off but never disappear for long when unreachable
    interval = min(interval, 300)
go_to_sleep(interval)
