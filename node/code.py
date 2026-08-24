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

import struct

import alarm
import board
import digitalio
import espnow
import microcontroller
import rtc
import wifi

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


MEM_STASH_N = 8      # count of stashed (unsent) readings
STASH_START = 16
# stashed reading: ts(I) tc*100(h) rh*100(H) co2(H) pm25*10(H) voc(H)
#                  nox(H) vb_mv(H) -- 18 bytes
_STASH_FMT = "<IhHHHHHH"
_STASH_REC = struct.calcsize(_STASH_FMT)
STASH_MAX = max(0, (len(alarm.sleep_memory) - STASH_START) // _STASH_REC)
_NOVAL = 0xFFFF

if alarm.sleep_memory[MEM_MAGIC] != MAGIC:
    for i in range(STASH_START):
        alarm.sleep_memory[i] = 0
    alarm.sleep_memory[MEM_MAGIC] = MAGIC

alarm.sleep_memory[MEM_BOOTS] = (alarm.sleep_memory[MEM_BOOTS] + 1) % 256
print("wake:", alarm.wake_alarm, "boot#", alarm.sleep_memory[MEM_BOOTS],
      "stash:", alarm.sleep_memory[MEM_STASH_N])


# ---------------------------------------------------------------------------
# Reading stash: unsent readings survive deep sleep in alarm.sleep_memory
# and are retransmitted (with their original timestamps) once the collector
# is reachable again. Timestamps are RTC-based -- the ESP32 RTC keeps
# ticking through deep sleep -- and get retro-adjusted when the hub's time
# service reaches us (cfg "t").
# ---------------------------------------------------------------------------

def _enc(v, scale=1):
    if v is None:
        return _NOVAL
    v = int(v * scale)
    return v if 0 <= v < _NOVAL else _NOVAL


def _dec(raw, scale=1):
    return None if raw == _NOVAL else raw / scale


def stash_put(ts, m, vb):
    n = alarm.sleep_memory[MEM_STASH_N]
    if n >= STASH_MAX:  # full: drop the OLDEST, keep the freshest data
        buf = bytes(alarm.sleep_memory[STASH_START + _STASH_REC:
                                       STASH_START + n * _STASH_REC])
        alarm.sleep_memory[STASH_START:STASH_START + len(buf)] = buf
        n -= 1
    tc = m.get("tc")
    rec = struct.pack(
        _STASH_FMT, int(ts),
        int(tc * 100) if tc is not None else -0x8000,
        _enc(m.get("rh"), 100), _enc(m.get("co2")),
        _enc(m.get("pm25"), 10), _enc(m.get("voc")), _enc(m.get("nox")),
        _enc(vb, 1000) if vb else _NOVAL,
    )
    off = STASH_START + n * _STASH_REC
    alarm.sleep_memory[off:off + _STASH_REC] = rec
    alarm.sleep_memory[MEM_STASH_N] = n + 1
    print("stashed reading (%d held)" % (n + 1))


def stash_get(i):
    off = STASH_START + i * _STASH_REC
    ts, tc, rh, co2, pm25, voc, nox, vb = struct.unpack(
        _STASH_FMT, bytes(alarm.sleep_memory[off:off + _STASH_REC]))
    m = {"tc": None if tc == -0x8000 else tc / 100,
         "rh": _dec(rh, 100), "co2": _dec(co2), "pm25": _dec(pm25, 10),
         "voc": _dec(voc), "nox": _dec(nox)}
    return ts, {k: v for k, v in m.items() if v is not None}, _dec(vb, 1000)


def stash_drop_first(count):
    n = alarm.sleep_memory[MEM_STASH_N]
    keep = n - count
    if keep > 0:
        buf = bytes(alarm.sleep_memory[STASH_START + count * _STASH_REC:
                                       STASH_START + n * _STASH_REC])
        alarm.sleep_memory[STASH_START:STASH_START + len(buf)] = buf
    alarm.sleep_memory[MEM_STASH_N] = max(0, keep)


def stash_shift_time(delta):
    """Retro-adjust stashed timestamps after a clock sync."""
    n = alarm.sleep_memory[MEM_STASH_N]
    for i in range(n):
        off = STASH_START + i * _STASH_REC
        (ts,) = struct.unpack_from("<I", bytes(
            alarm.sleep_memory[off:off + 4]))
        alarm.sleep_memory[off:off + 4] = struct.pack("<I",
                                                      max(0, ts + delta))
    if n:
        print("stash: %d timestamps adjusted by %+ds" % (n, delta))


def apply_hub_time(epoch):
    """Set the RTC from the hub's time service; fix stashed timestamps."""
    delta = int(epoch) - int(time.time())
    if abs(delta) > 5:
        rtc.RTC().datetime = time.localtime(int(epoch))
        stash_shift_time(delta)
        print("clock set from hub: %+ds" % delta)

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
DEFAULTS = {
    "name": "",                    # "" = auto "sensor-{mac-hex}"
    "collector_mac": "",          # optional pin; blank = ESP-NOW discovery
    "interval_s": 120,
    "metrics": None,               # None = send everything the sensor has
    "pm_warmup_s": 20,             # extra fan spin-up for SEN5x/SEN6x PM
    "cal_measure_s": 180,          # measurement time before forced recal
    "wifi_fallback": False,
    "collector_url": "",          # e.g. "http://192.168.1.50"
    "led": False,
    "configured": False,           # portal sets this; True skips the portal
    "portal_timeout_s": 180,
}

config = dict(DEFAULTS)
# /saves (CPSAVES) takes priority: it's where the portal saves when USB MSC
# holds CIRCUITPY read-only on S2/S3 boards.
for _path in ("/node_config.json", "/saves/node_config.json"):
    try:
        with open(_path) as f:
            config.update(json.load(f))
    except (OSError, ValueError):
        pass
if not config.get("configured"):
    print("node unconfigured (no config file found or portal never run)")

SHORT_MAC = envproto.short_mac(wifi.radio.mac_address)
if not config.get("name"):
    config["name"] = "sensor-" + SHORT_MAC
print("node:", config["name"])

# ---------------------------------------------------------------------------
# First-boot / on-demand config portal (AP "SENSOR{mac-hex}"): power-on
# reset with the node unconfigured, or with the BOOT button held.
# ---------------------------------------------------------------------------

def _boot_button_held():
    for pin_name in ("BUTTON", "BOOT", "BOOT0", "D0"):
        pin = getattr(board, pin_name, None)
        if pin is None:
            continue
        try:
            btn = digitalio.DigitalInOut(pin)
            btn.switch_to_input(pull=digitalio.Pull.UP)
            held = not btn.value
            btn.deinit()
            return held
        except (ValueError, RuntimeError):
            continue
    return False


if alarm.wake_alarm is None and (
        _boot_button_held() or not config.get("configured")):
    import node_portal
    node_portal.run(config, ssid="SENSOR" + SHORT_MAC,
                    timeout_s=config.get("portal_timeout_s", 180))
    # (reboots on save; falls through here on timeout)

# ---------------------------------------------------------------------------
# Collector identity: config pin > NVM (survives power loss) > discovery.
# NVM layout: [0]=0xE6 magic, [1:7]=collector MAC, [7]=channel.
# ---------------------------------------------------------------------------
NVM = microcontroller.nvm


def nvm_collector():
    if NVM is None or NVM[0] != 0xE6:
        return None, 0
    return bytes(NVM[1:7]), NVM[7]


def nvm_save_collector(mac, channel):
    if NVM is None:
        return
    if bytes(NVM[1:7]) != mac or NVM[7] != channel or NVM[0] != 0xE6:
        NVM[0:8] = bytes([0xE6]) + mac + bytes([channel & 0xFF])
        print("collector pinned: %s ch%d" % (envproto.mac_str(mac), channel))


def nvm_forget_collector():
    if NVM is not None:
        NVM[0] = 0


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
reading_ts = int(time.time())   # RTC-based; hub-synced or retro-adjusted
print("read:", metrics, "batt:", batt_v)

# --------------------------------------------------------------------------
# ESP-NOW: send + channel discovery + cfg reply
# --------------------------------------------------------------------------
seq = (mem_get_u16(MEM_SEQ) + 1) % 65536
mem_set_u16(MEM_SEQ, seq)
packet = envproto.make_data_packet(
    config["name"], sensor.kind, seq, batt_v, metrics, at=reading_ts
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


def _mk_peer(e, old_peer, mac, ch):
    """Create or retune a peer to a channel (ports differ on mutability)."""
    if old_peer is None:
        peer = espnow.Peer(mac=mac, channel=ch)
        e.peers.append(peer)
        return peer
    try:
        old_peer.channel = ch
        return old_peer
    except (AttributeError, ValueError):
        e.peers.remove(old_peer)
        peer = espnow.Peer(mac=mac, channel=ch)
        e.peers.append(peer)
        return peer


def _listen_cfg(e, timeout):
    """Wait for a 'cfg' packet; returns (cfg_dict, sender_mac) or (None, None)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(e):
            pkt = e.read()
            obj = envproto.decode(pkt.msg) if pkt else None
            if obj and obj.get("k") == "cfg":
                return obj, bytes(pkt.mac)
        time.sleep(0.02)
    return None, None


def _channels(prefer):
    return ([prefer] if prefer else []) + [
        c for c in range(1, 14) if c != prefer]


def _unicast_hunt(e, mac, payload, prefer_ch):
    """Send unicast, hunting channels until the MAC ACKs. Returns channel or 0."""
    peer = None
    for ch in _channels(prefer_ch):
        peer = _mk_peer(e, peer, mac, ch)
        if _try_send(e, peer, payload):
            return ch
    return 0


def _discover(e):
    """Broadcast 'dsc' across channels; the collector's unicast 'cfg' reply
    reveals its MAC + channel. Returns (mac, channel, cfg) or (None, 0, None)."""
    dsc = envproto.make_discovery_packet(config["name"], None)
    peer = None
    for ch in _channels(alarm.sleep_memory[MEM_CHANNEL]):
        peer = _mk_peer(e, peer, envproto.BROADCAST_MAC, ch)
        try:
            e.send(dsc, peer)
        except (RuntimeError, OSError, ValueError):
            continue
        cfg, mac = _listen_cfg(e, 0.25)
        if cfg and mac:
            print("discovered collector %s on ch%d"
                  % (envproto.mac_str(mac), ch))
            return mac, ch, cfg
    return None, 0, None


def espnow_report():
    """Fully self-configuring report. Returns (sent_ok, cfg_dict_or_None)."""
    e = espnow.ESPNow()
    try:
        # who's the collector? config pin > NVM > (later) discovery
        mac = COLLECTOR_MAC
        prefer_ch = alarm.sleep_memory[MEM_CHANNEL]
        if mac is None:
            mac, nvm_ch = nvm_collector()
            prefer_ch = prefer_ch or nvm_ch
        if mac is not None:
            ch = _unicast_hunt(e, mac, packet, prefer_ch)
            if ch:
                alarm.sleep_memory[MEM_CHANNEL] = ch
                nvm_save_collector(mac, ch)
                cfg, _ = _listen_cfg(e, 0.5)
                return True, cfg
            print("known collector unreachable; rediscovering...")
            nvm_forget_collector()
        # discovery: learn MAC + channel from the cfg reply, then send data
        mac, ch, cfg = _discover(e)
        if mac is None:
            alarm.sleep_memory[MEM_CHANNEL] = 0
            return False, None
        alarm.sleep_memory[MEM_CHANNEL] = ch
        nvm_save_collector(mac, ch)
        peer = espnow.Peer(mac=mac, channel=ch)
        e.peers.append(peer)
        sent = _try_send(e, peer, packet)
        cfg2, _ = _listen_cfg(e, 0.5)
        return sent, cfg2 or cfg
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


def drain_stash(limit=20):
    """Retransmit stashed readings with their original timestamps."""
    n = alarm.sleep_memory[MEM_STASH_N]
    if not n:
        return
    mac = COLLECTOR_MAC or nvm_collector()[0]
    ch = alarm.sleep_memory[MEM_CHANNEL] or 1
    if not mac:
        return
    e = espnow.ESPNow()
    try:
        peer = espnow.Peer(mac=mac, channel=ch)
        e.peers.append(peer)
        done = 0
        for i in range(min(n, limit)):
            ts, m, vb = stash_get(i)
            pkt = envproto.make_data_packet(
                config["name"], sensor.kind, 0, vb, m, at=ts)
            if not _try_send(e, peer, pkt):
                break
            done += 1
            time.sleep(0.05)
        if done:
            stash_drop_first(done)
            print("retransmitted %d stashed (%d left)"
                  % (done, alarm.sleep_memory[MEM_STASH_N]))
    finally:
        e.deinit()


# never let a transport error kill the wake -- data gets stashed instead
sent, cfg = False, None
try:
    sent, cfg = espnow_report()
except Exception as exc:
    print("espnow error:", type(exc).__name__, exc)
if not sent:
    try:
        sent, cfg = wifi_report()
    except Exception as exc:
        print("wifi fallback error:", type(exc).__name__, exc)

# --------------------------------------------------------------------------
# Apply collector config
# --------------------------------------------------------------------------
if cfg and cfg.get("t"):
    try:
        apply_hub_time(cfg["t"])   # hub time service -> RTC + stash fix-up
    except Exception as exc:
        print("time apply failed:", exc)

# stash on failure / retransmit backlog on success -- guarded so a bug
# here can never prevent the deep sleep (battery safety)
try:
    if sent:
        drain_stash()
    elif metrics:
        stash_put(reading_ts, metrics, batt_v)
except Exception as exc:
    print("stash error:", type(exc).__name__, exc)

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
    cal_target = None
    try:
        cal_target = cfg.get("cal")
    except AttributeError:
        pass
    if cal_target:
        # User armed forced recalibration (they were warned to go outside at
        # step 1). Measure in fresh air for cal_measure_s, then recalibrate.
        print("FORCED RECAL to %dppm: measuring %ds first..."
              % (cal_target, config["cal_measure_s"]))
        end = time.monotonic() + config["cal_measure_s"]
        while time.monotonic() < end:
            try:
                sensor.read(timeout_s=5)
            except (OSError, RuntimeError):
                pass  # transient I2C error: keep measuring, never skip sleep
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
        cal_mac = COLLECTOR_MAC or nvm_collector()[0]
        if cal_mac:
            e2 = espnow.ESPNow()
            try:
                ch = alarm.sleep_memory[MEM_CHANNEL] or 1
                p2 = espnow.Peer(mac=cal_mac, channel=ch)
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
