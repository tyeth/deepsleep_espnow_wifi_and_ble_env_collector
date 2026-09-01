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

import calref
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


def mem_get_u32(off):
    return mem_get_u16(off) | (mem_get_u16(off + 2) << 16)


def mem_set_u32(off, val):
    mem_set_u16(off, val & 0xFFFF)
    mem_set_u16(off + 2, (val >> 16) & 0xFFFF)


MEM_STASH_N = 8      # count of stashed (unsent) readings
# scheduled reference calibration (survives deep sleep until it runs)
MEM_CAL_TGT = 9      # uint16 LE target ppm; bit15 = dry, bit14 = ASC mode
                     # (MEM_CAL_DURM below is in 15-minute units: 48 h ASC fits)
MEM_CAL_AT = 11      # uint32 LE epoch the window starts
MEM_CAL_DURM = 15    # uint8 window minutes
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
    "cal_measure_s": 180,          # fallback window when the hub sends none
    "cal_max_spread_ppm": 60,      # stability gate over the last 15 min
    "cal_min_batt_v": 3.7,         # refuse a long awake window on a low cell
    "wifi_fallback": False,
    "collector_url": "",          # e.g. "http://192.168.1.50"
    "deep_sleep": True,            # False = bench mode: stay awake between
                                   # reports (USB/console stays alive)
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
    if not config.get("deep_sleep", True):
        # bench mode: keep USB/console alive, then rerun the wake cycle.
        # sleep_memory (stash/seq/channel) survives a supervisor reload.
        print("awake wait %ds (deep_sleep disabled)" % seconds)
        time.sleep(seconds)
        import supervisor
        supervisor.reload()
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
# what the hub must echo back for this reading to count as delivered
packet_crc = envproto.crc16(packet)


def _try_send(e, peer, payload):
    """Send and report MAC-layer ACK using the phy counters when available.

    The ACK callback that bumps send_success/send_failure is ASYNC -- read
    immediately after send() it hasn't fired yet and every send looks
    failed (node then re-discovers every wake and stashes delivered
    readings). Poll the counters briefly instead."""
    before_ok = getattr(e, "send_success", None)
    before_bad = getattr(e, "send_failure", None)
    try:
        e.send(payload, peer)
    except (RuntimeError, OSError, ValueError) as exc:
        print("send raised:", exc)
        return False
    if before_ok is None:
        return True  # no counters on this port; assume sent
    for _ in range(20):  # up to ~0.2s for the ACK callback
        if e.send_success > before_ok:
            return True
        if before_bad is not None and e.send_failure > before_bad:
            return False
        time.sleep(0.01)
    return True  # counters never moved; assume sent


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


def next_msg_id():
    """Allocate the next message id (persists across deep sleep)."""
    nid = (mem_get_u16(MEM_SEQ) + 1) % 65536
    mem_set_u16(MEM_SEQ, nid)
    return nid


def _listen_reply(e, timeout, msg_id=None, crc=None):
    """Wait for a hub reply ('cfg' or bare 'ack').

    Returns (obj, sender_mac, confirmed). When msg_id/crc are given,
    confirmed means the hub echoed OUR message id and the CRC-16 of the
    bytes it received matched what we sent -- i.e. the packet arrived
    intact and was accepted, which the MAC-layer ACK does not tell us.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(e):
            pkt = e.read()
            obj = envproto.decode(pkt.msg) if pkt else None
            if obj and obj.get("k") in ("cfg", "ack"):
                if msg_id is None:
                    return obj, bytes(pkt.mac), True
                if envproto.ack_ok(obj, msg_id, crc):
                    return obj, bytes(pkt.mac), True
                if "ac" not in obj:
                    # hub firmware predates confirmations: the reply itself
                    # is the only evidence we are going to get
                    print("hub reply carries no confirmation (old firmware?)")
                    return obj, bytes(pkt.mac), True
                if int(obj.get("aq", -1)) == int(msg_id):
                    print("hub confirmed sq=%s with crc %s, we sent %s"
                          % (msg_id, obj.get("ac"), crc))
                    return obj, bytes(pkt.mac), False
                # a late reply to an earlier packet: keep waiting
        time.sleep(0.02)
    return None, None, False


def _listen_cfg(e, timeout):
    """Back-compat wrapper: any reply, no confirmation check."""
    obj, mac, _ = _listen_reply(e, timeout)
    return obj, mac


def _send_confirmed(e, peer, payload, msg_id, tries=2, listen_s=1.5):
    """Send and wait for the hub's confirmation. Returns (ok, cfg_or_None).

    Retries resend the IDENTICAL bytes, so a hub that did receive the packet
    but whose confirmation was lost recognises the duplicate, re-confirms
    and does not store the reading twice.
    """
    crc = envproto.crc16(payload)
    for attempt in range(tries):
        if not _try_send(e, peer, payload):
            print("send %d/%d: no MAC ack" % (attempt + 1, tries))
            continue
        obj, _mac, confirmed = _listen_reply(e, listen_s, msg_id, crc)
        if confirmed:
            return True, (obj if obj and obj.get("k") == "cfg" else None)
        if obj is None:
            print("send %d/%d: no confirmation within %.1fs"
                  % (attempt + 1, tries, listen_s))
    return False, None


def _channels(prefer):
    return ([prefer] if prefer else []) + [
        c for c in range(1, 14) if c != prefer]


def _unicast_hunt(e, mac, payload, prefer_ch):
    """Find the hub's channel: unicast until the MAC layer ACKs. Returns
    (channel, peer) or (0, None).

    The payload really is transmitted here (that is the probe), so a hunt
    that walks several channels can deliver it more than once -- always as
    identical bytes, which the hub's duplicate check re-confirms instead of
    storing twice."""
    peer = None
    for ch in _channels(prefer_ch):
        peer = _mk_peer(e, peer, mac, ch)
        if _try_send(e, peer, payload):
            return ch, peer
    return 0, None


def _discover(e):
    """Broadcast 'dsc' across channels; the collector's unicast 'cfg' reply
    reveals its MAC + channel. Returns (mac, channel, cfg) or (None, 0, None)."""
    dsc = envproto.make_discovery_packet(config["name"], None, seq=next_msg_id())
    peer = None
    for ch in _channels(alarm.sleep_memory[MEM_CHANNEL]):
        peer = _mk_peer(e, peer, envproto.BROADCAST_MAC, ch)
        try:
            e.send(dsc, peer)
        except (RuntimeError, OSError, ValueError):
            continue
        # the collector replies from its main loop, which can be seconds
        # away (eInk SPI refresh, BLE work) -- 0.25s missed every reply
        cfg, mac = _listen_cfg(e, 1.5)
        if cfg and mac:
            print("discovered collector %s on ch%d"
                  % (envproto.mac_str(mac), ch))
            return mac, ch, cfg
    return None, 0, None


def espnow_report():
    """Fully self-configuring report. Returns (delivered, cfg_dict_or_None).

    delivered is the HUB's confirmation (message id + CRC of the bytes it
    received), never just the radio's ACK -- an unconfirmed reading goes to
    the WiFi fallback and, failing that, into the stash.
    """
    e = espnow.ESPNow()
    try:
        # who's the collector? config pin > NVM > (later) discovery
        mac = COLLECTOR_MAC
        prefer_ch = alarm.sleep_memory[MEM_CHANNEL]
        if mac is None:
            mac, nvm_ch = nvm_collector()
            prefer_ch = prefer_ch or nvm_ch
        if mac is not None:
            ch, peer = _unicast_hunt(e, mac, packet, prefer_ch)
            if ch:
                # the hunt's last send is attempt 1: its confirmation may
                # already be in flight
                obj, _m, confirmed = _listen_reply(e, 1.5, seq, packet_crc)
                if not confirmed:
                    confirmed, obj = _send_confirmed(e, peer, packet, seq)
                if confirmed:
                    alarm.sleep_memory[MEM_CHANNEL] = ch
                    nvm_save_collector(mac, ch)
                    return True, (obj if obj and obj.get("k") == "cfg" else None)
                print("collector on ch%d did not confirm; rediscovering..." % ch)
            else:
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
        confirmed, cfg2 = _send_confirmed(e, peer, packet, seq)
        return confirmed, cfg2 or cfg
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
        # same rule as ESP-NOW: HTTP 200 is not delivery, the hub echoing
        # our message id and CRC is
        if cfg and "ac" not in cfg:
            print("hub reply carries no confirmation (old firmware?)")
            return True, cfg
        if not envproto.ack_ok(cfg, seq, packet_crc):
            print("wifi fallback: hub did not confirm the packet")
            return False, cfg
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
            mid = next_msg_id()
            pkt = envproto.make_data_packet(
                config["name"], sensor.kind, mid, vb, m, at=ts)
            # only drop a stashed reading the hub has actually confirmed
            confirmed, _cfg = _send_confirmed(e, peer, pkt, mid, listen_s=0.8)
            if not confirmed:
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
    if cfg.get("cal"):
        # user armed a reference calibration: schedule it (or run now)
        try:
            cal_schedule(int(cfg["cal"]), int(cfg.get("cat") or 0),
                         int(cfg.get("cdur") or config["cal_measure_s"]),
                         bool(cfg.get("cdry")), bool(cfg.get("casc")))
        except (TypeError, ValueError) as exc:
            print("bad cal fields in cfg:", exc)

blink(sent)

# --------------------------------------------------------------------------
# Reference calibration (ASC is OFF: this is the sensor's only correction).
# The hub schedules a window (default next 04:00 local, 60 min); we keep it
# in sleep memory, sleep until then, stay awake measuring through it, gate
# on stability (calref.evaluate) and only then write the FRC.
# --------------------------------------------------------------------------

def cal_schedule(target, at, dur_s, dry, asc=False):
    now = int(time.time())
    if at and at > now + 30:
        mem_set_u16(MEM_CAL_TGT, (target & 0x3FFF) | (0x8000 if dry else 0)
                    | (0x4000 if asc else 0))
        mem_set_u32(MEM_CAL_AT, at)
        alarm.sleep_memory[MEM_CAL_DURM] = max(2, min(255, dur_s // 60))
        print("CAL scheduled: %d ppm%s at +%ds for %d min"
              % (target, " ASC" if asc else (" DRY" if dry else ""),
                 at - now, dur_s // 60))
    else:
        run_calibration(target, dur_s, dry, asc)


def cal_pending():
    raw = mem_get_u16(MEM_CAL_TGT)
    if not raw:
        return None
    return (raw & 0x3FFF, mem_get_u32(MEM_CAL_AT),
            alarm.sleep_memory[MEM_CAL_DURM] * 900, bool(raw & 0x8000),
            bool(raw & 0x4000))


def cal_clear():
    mem_set_u16(MEM_CAL_TGT, 0)


def _nap(seconds):
    """Low-power wait that keeps the sensor measuring: light sleep when the
    port allows it (I2C sensor runs on its own), plain sleep otherwise."""
    try:
        alarm.light_sleep_until_alarms(
            alarm.time.TimeAlarm(monotonic_time=time.monotonic() + seconds))
    except (NotImplementedError, RuntimeError, ValueError, AttributeError):
        time.sleep(seconds)


def _send_cal_result(ok, corr, ref, why, ref0=None):
    mid = next_msg_id()
    pkt = envproto.make_cal_result_packet(config["name"], ok, corr, ref, why,
                                          ref0, seq=mid)
    mac = COLLECTOR_MAC or nvm_collector()[0]
    if not mac:
        print("cal result not sent (no collector known)")
        return
    e2 = espnow.ESPNow()
    try:
        p2 = espnow.Peer(mac=mac, channel=alarm.sleep_memory[MEM_CHANNEL] or 1)
        e2.peers.append(p2)
        # a calibration result is expensive to reproduce: insist on the hub's
        # confirmation, with more retries than a routine reading gets
        confirmed, _cfg = _send_confirmed(e2, p2, pkt, mid, tries=3)
        if not confirmed:
            print("cal result NOT confirmed by the hub")
    except (RuntimeError, OSError, ValueError) as exc:
        print("cal result send failed:", exc)
    finally:
        e2.deinit()


def run_calibration(target, dur_s, dry, asc=False):
    """Measure through the window, then FRC (gated on stability), or in
    ASC mode let the sensor self-calibrate with ASC ON, then OFF again."""
    cal_clear()
    vb = batt.voltage()
    if vb is not None and vb < config["cal_min_batt_v"]:
        why = "battery %.2fV < %.2fV" % (vb, config["cal_min_batt_v"])
        print("CAL refused:", why)
        _send_cal_result(False, None, None, why)
        return
    print("CAL: %s window %d min, target %d ppm -- keep me in fresh air"
          % ("ASC" if asc else ("DRY-RUN" if dry else "reference"),
             dur_s // 60, target))
    if asc:
        try:
            sensor.set_asc(True)
            alarm.sleep_memory[MEM_ASC_DONE] = 0   # re-assert OFF afterwards
        except (OSError, RuntimeError) as exc:
            print("CAL: could not enable ASC:", exc)
    samples = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < dur_s:
        try:
            m = sensor.read(timeout_s=15)
        except (OSError, RuntimeError):
            m = None   # transient I2C error: keep going, never skip sleep
        if m and m.get("co2"):
            samples.append((time.monotonic(), m["co2"]))
        if len(samples) % 30 == 1:
            print("CAL: %d samples, last %s" % (len(samples), samples[-1][1]))
        blink(True)
        _nap(10)
    if asc:
        try:
            sensor.set_asc(False)
            alarm.sleep_memory[MEM_ASC_DONE] = 1
        except (OSError, RuntimeError) as exc:
            print("CAL: could not disable ASC again:", exc)
        head = [v for _, v in samples[:30]]
        tail = [v for _, v in samples[-30:]]
        ref0 = calref._median(head) if head else None
        ref = calref._median(tail) if tail else None
        ok = ref is not None
        print("CAL ASC result: start ~%s -> end ~%s ppm" % (ref0, ref))
        _send_cal_result(ok, None, ref, "" if ok else "no samples", ref0)
        blink(ok)
        return
    ok, ref, spread, why = calref.evaluate(
        samples, target, config["cal_max_spread_ppm"])
    corr = None
    if ok and not dry:
        try:
            corr = sensor.force_recal(target)
            print("CAL: recalibrated to %d ppm (was ~%d), correction %s"
                  % (target, ref, corr))
        except (OSError, RuntimeError, AttributeError) as exc:
            ok, why = False, "FRC failed: %s" % exc
    print("CAL result: ok=%s ref=%s spread=%s %s%s"
          % (ok, ref, spread, why, " (dry)" if dry else ""))
    _send_cal_result(ok, corr, ref, why)
    blink(ok)


_pending = cal_pending()
if _pending:
    _tgt, _at, _dur, _dry, _asc = _pending
    _now = int(time.time())
    if _now >= _at - 15:
        run_calibration(_tgt, _dur, _dry, _asc)
    else:
        # sleep straight to the window (but keep checking in as usual)
        interval = max(10, min(interval, _at - _now))
        print("CAL pending in %ds; next wake in %ds" % (_at - _now, interval))

# --------------------------------------------------------------------------
# Sleep
# --------------------------------------------------------------------------
try:
    sensor.stop()
except (OSError, RuntimeError):
    pass

if not sent and not _pending:
    # back off but never disappear for long when unreachable
    interval = min(interval, 300)
go_to_sleep(interval)
