# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
node_lite - the sensor node for boards WITHOUT ESP-NOW or deep sleep:
Raspberry Pi Pico W (RP2040, ~40 KB of heap) and Pico 2 W (RP2350) on
CircuitPython's Zephyr port. node/code.py picks this over node_full when
`espnow` or `alarm` is missing.

What it does, every `interval_s`:
  1. read the sensor (auto-detected on the board's I2C bus, or "sim")
  2. pack the reading into a BLE advertisement (envadv) and broadcast it
     for `ble_adv_s` seconds -- the hub's net_blescan picks it up
  3. optionally POST the same reading to the hub over WiFi (`wifi_fallback`
     + `collector_url`), which is the only path that brings the hub's cfg
     reply (interval, time) back to this node -- and the only one with a
     delivery confirmation
  4. stop advertising and time.sleep() the rest of the interval

What it does NOT do, honestly:
  * deep sleep. `alarm` does not exist on these boards, so the node is an
    awake loop: the RP2040/RP2350 and the CYW43439 stay powered. Expect
    tens of mA continuously (the ESP32 nodes sleep at tens of uA) -- this
    is a mains/USB-powered node, or a big battery for days, not months.
    `time.sleep()` is the lowest-power idle this port offers.
  * stash unsent readings. Broadcast is fire-and-forget: the hub either
    heard the window or it did not. The WiFi POST path keeps its
    confirmation check but there is no sleep memory to stash into; a
    failed POST is simply retried with the next reading.
  * the BLE UART config portal / the WiFi setup portal. The first needs
    adafruit_ble (more heap than a Pico W has); the second needs a softAP,
    which zephyr-cp does not implement. Configure by editing
    node_config.json on CIRCUITPY (or over the hub's WiFi POST cfg reply).

Deploy as .mpy (tools/build_bundle.sh): compiling this file from source on
a 40 KB heap is exactly the kind of peak that fails at boot.
"""

import gc
import json
import time

import microcontroller
import supervisor

import caps
import envadv
import node_sensors

supervisor.runtime.autoreload = False

DEFAULTS = {
    "name": "",
    "interval_s": 120,
    "metrics": None,
    "sensor": "",             # "" auto-detect, "sim" synthetic (bench)
    "pm_warmup_s": 20,
    "ble_adv_s": 20,          # how long each reading is on air
    "wifi_fallback": False,
    "collector_url": "",      # e.g. "http://192.168.1.50"
    "wifi_min_free": 40 * 1024,   # never try WiFi POST below this much heap
}

config = dict(DEFAULTS)
for _path in ("/node_config.json", "/saves/node_config.json"):
    try:
        with open(_path) as f:
            config.update(json.load(f))
    except (OSError, ValueError):
        pass


def _tail(b):
    return "%02X%02X" % (b[-2], b[-1])


def _mac_tail():
    """Last two bytes of the BLE address -- the same id the hub derives
    from the advertisement (net_blescan.src_for). The WiFi MAC is a
    fallback only: on the CYW43439 the BD_ADDR is the WiFi MAC + 1."""
    try:
        import _bleio
        return _tail(_bleio.adapter.address.address_bytes)
    except Exception:
        try:
            import wifi
            return _tail(wifi.radio.mac_address)
        except Exception:
            return "0000"


if not config.get("name"):
    config["name"] = "ble-" + _mac_tail()   # what the hub calls us too

print("node_lite:", config["name"], "reset:", microcontroller.cpu.reset_reason,
      "free:", caps.free())
print("  no espnow/alarm on this port: awake loop, BLE advertisement "
      "transport%s" % (" + WiFi POST" if config.get("wifi_fallback") else ""))

# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------
i2c = None
if config.get("sensor") == "sim":
    sensor = node_sensors.SimSensor()
    print("SIMULATED sensor: readings below are synthetic, not measurements")
else:
    i2c = caps.i2c()          # board.I2C0 on the Pico: SDA GP4, SCL GP5
    if i2c is None:
        print("no I2C bus on this board")
    sensor = node_sensors.detect(i2c) if i2c is not None else None


def _start_sensor():
    if sensor is None:
        return
    try:
        sensor.set_asc(False)     # project policy: no automatic self-cal
    except (OSError, RuntimeError, AttributeError) as exc:
        print("ASC disable failed:", exc)
    try:
        sensor.begin()
    except (OSError, RuntimeError) as exc:
        print("sensor begin failed:", exc)
    if sensor.kind in ("sen5x", "sen6x") and config["pm_warmup_s"]:
        print("PM sensor warm-up %ds" % config["pm_warmup_s"])
        time.sleep(config["pm_warmup_s"])


if sensor is None:
    print("no sensor found; will retry every %ds" % config["interval_s"])
else:
    print("sensor:", sensor.kind)
    # awake node: keep the sensor measuring instead of stop/start per cycle
    _start_sensor()

# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------
beacon = None
if caps.HAS_BLE:
    import net_bleadv
    beacon = net_bleadv.Beacon()
    if not beacon.ok:
        beacon = None
if beacon is None:
    print("BLE beacon off: no _bleio on this build")

_batt = None
if i2c is not None:
    try:
        import battery
        _batt = battery.BatteryMonitor(i2c)
        print("battery source:", _batt.source)
    except Exception as exc:
        print("battery monitor off:", exc)

_wifi_ok = bool(config.get("wifi_fallback") and config.get("collector_url"))


def wifi_post(packet_bytes, seq):
    """POST the envproto packet to the hub. Returns the cfg dict or None.
    Imports lazily: adafruit_requests + connection_manager cost ~12 KB of
    heap on a 32-bit build, so a Pico W only gets here when RAM allows."""
    global _wifi_ok
    if caps.free() < config["wifi_min_free"]:
        print("wifi post skipped: %d free < %d" % (caps.free(),
                                                   config["wifi_min_free"]))
        return None
    try:
        import os
        import wifi
        import socketpool
        import adafruit_connection_manager
        import adafruit_requests
        import envproto
        if not wifi.radio.connected:
            wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID") or os.getenv("WIFI_SSID"),
                               os.getenv("CIRCUITPY_WIFI_PASSWORD") or os.getenv("WIFI_PASSWORD") or "",
                               timeout=15)
        pool = socketpool.SocketPool(wifi.radio)
        ssl_ctx = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
        requests = adafruit_requests.Session(pool, ssl_ctx)
        resp = requests.post(config["collector_url"] + "/api/ingest",
                             data=packet_bytes, timeout=10)
        cfg = None
        try:
            cfg = resp.json().get("cfg")
        finally:
            resp.close()
        if not envproto.ack_ok(cfg, seq, envproto.crc16(packet_bytes)):
            print("wifi post: hub did not confirm sq=%d" % seq)
            return cfg
        print("wifi post: confirmed sq=%d" % seq)
        return cfg
    except MemoryError:
        print("wifi post: MemoryError; disabling WiFi POST for this run")
        _wifi_ok = False
    except Exception as exc:
        print("wifi post failed: %s: %s" % (type(exc).__name__, exc))
    return None


def apply_cfg(cfg):
    if not cfg:
        return
    try:
        if cfg.get("t"):
            delta = int(cfg["t"]) - caps.now()
            if abs(delta) > 5:
                caps.set_epoch(int(cfg["t"]))
                print("clock set from hub: %+ds" % delta)
        new_int = int(cfg.get("int", 0))
        if 10 <= new_int <= 65535 and new_int != config["interval_s"]:
            config["interval_s"] = new_int
            print("interval ->", new_int)
    except (TypeError, ValueError) as exc:
        print("bad cfg:", exc)


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------
seq = 0
while True:
    t0 = time.monotonic()
    metrics = {}
    if sensor is None:
        if i2c is not None:
            sensor = node_sensors.detect(i2c)
            if sensor is not None:
                print("sensor:", sensor.kind)
                _start_sensor()
    if sensor is not None:
        try:
            metrics = sensor.read() or {}
        except (OSError, RuntimeError) as exc:
            print("sensor read failed:", exc)
            metrics = {}
        if not metrics:
            print("sensor read timed out")
    enabled = config.get("metrics")
    if enabled:
        metrics = {k: v for k, v in metrics.items() if k in enabled}
    vb = _batt.voltage() if _batt is not None else None
    seq = (seq + 1) & 0xFF
    kind = sensor.kind if sensor is not None else "?"
    print("read sq=%d: %s batt=%s free=%d" % (seq, metrics, vb, caps.free()))

    on_air = False
    if beacon is not None and metrics:
        on_air = beacon.start(envadv.adv_bytes(seq, metrics, vb, kind))
        if on_air:
            print("BLE advertising sq=%d for %ds" % (seq, config["ble_adv_s"]))

    if _wifi_ok and metrics:
        try:
            import envproto
            pkt = envproto.make_data_packet(config["name"], kind, seq, vb,
                                            metrics, at=caps.now()
                                            if caps.synced() else None)
            apply_cfg(wifi_post(pkt, seq))
        except MemoryError:
            print("envproto/WiFi path does not fit in RAM here; BLE only")
            _wifi_ok = False
        except Exception as exc:
            print("wifi path error: %s: %s" % (type(exc).__name__, exc))

    # keep the advertisement up for its window, then go quiet
    window = config["ble_adv_s"] if on_air else 0
    while on_air and time.monotonic() - t0 < window:
        time.sleep(1)
    if beacon is not None:
        beacon.stop()

    gc.collect()
    rest = config["interval_s"] - (time.monotonic() - t0)
    if rest > 0:
        print("idle %ds (awake: no deep sleep on this port)" % int(rest))
        time.sleep(rest)
