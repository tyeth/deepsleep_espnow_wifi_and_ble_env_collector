# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
Environmental collector hub.

Hardware:
  * Adafruit Feather ESP32-S3 (default; ESP32-C6 / ESP32-S2 also work,
    S2 has no BLE) -- run the LATEST CircuitPython ALPHA (BLE fixes).
  * eInk Feather Friend / FeatherWing (#4446): shared SPI,
    SD CS = D5, SRAM CS = D6 (unused, held deselected),
    eInk CS = D9, eInk DC = D10, no reset / no busy wired.
  * 3.52" quad-color eInk over FPC: constructor MUST be 384x184 (driver
    whitelist); the panel shows 384x180 of that buffer.
  * Sensirion SEN66 on I2C (STEMMA QT).

Responsibilities: sample local SEN66, receive remote nodes over ESP-NOW
(+ WiFi POST fallback), push config/calibration back to nodes, batch data to
SD, track out-of-spec durations, drive the eInk dashboard, and serve the
WiFi portal + BLE UART for web-BLE.
"""

import gc
import json
import os
import time

gc.collect()

import board
import digitalio
import displayio
import microcontroller
import rtc
import sdcardio
import storage
import supervisor
import wifi

# deploys copy several files: don't restart on each write, half-updated.
# Reset (Ctrl-D / button / microcontroller.reset()) when the copy is done.
supervisor.runtime.autoreload = False

import envproto  # tiny; needed for the early AP SSID

# ---------------------------------------------------------------------------
# EARLY RADIO BRING-UP -- BLE first, then the AP, both BEFORE the heavy
# imports below. Each needs large contiguous internal-heap buffers; done
# late (or in the other order) they hard-fault the C6 core on CP 10.3-a4.
# BLE-before-AP mirrors the one configuration proven to coexist: the BLE
# workflow (which boots before user code) alongside our early AP.
# Full evidence in bugs_issues_and_todos.md. ESP-NOW is light; it waits.
# ---------------------------------------------------------------------------
def _early_cfg():
    try:
        with open("/config.json") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

_ecfg = _early_cfg()
AP_SSID = (os.getenv("ENVHUB_AP_SSID")
           or _ecfg.get("ap_ssid")
           or "BASE" + envproto.short_mac(wifi.radio.mac_address))
AP_PASSWORD = (os.getenv("ENVHUB_AP_PASSWORD")
               or _ecfg.get("ap_password", ""))
# BLE controller AND advertising first (before the AP -- mirroring the
# BLE-workflow case, the only proven BLE+AP coexistence on C6). If any
# step fails, tear BLE down completely: a half-up BLE stack costs ~65KB
# of heap for zero function and starves the screen builds.
_ble_radio = None
_ble_uart = None
_ble_adv = None
if _ecfg.get("ble_enabled", True):
    try:
        from adafruit_ble import BLERadio
        from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
        from adafruit_ble.services.nordic import UARTService
        _ble_radio = BLERadio()
        _ble_radio.name = "ENVHUB"
        _ble_uart = UARTService()
        _ble_adv = ProvideServicesAdvertisement(_ble_uart)
        _ble_adv.complete_name = "ENVHUB"
        _ble_radio.start_advertising(_ble_adv)
        print("early BLE advertising as ENVHUB")
    except Exception as exc:
        print("early BLE failed (%s: %s); reclaiming its memory"
              % (type(exc).__name__, exc))
        try:
            import _bleio
            _bleio.adapter.enabled = False
        except Exception:
            pass
        _ble_radio = _ble_uart = _ble_adv = None
        import sys as _sys
        for _mod in list(_sys.modules):
            if "ble" in _mod:
                del _sys.modules[_mod]
        gc.collect()
# ESP-NOW before the AP: initialising ESP-NOW while a user softAP is
# active silently kills the AP (phones can then never associate) and can
# wedge USB outright. The object lives forever and is handed to
# net_espnow.EspNowHub later.
_espnow_obj = None
try:
    import espnow as _espnow_mod
    wifi.radio.enabled = True
    _espnow_obj = _espnow_mod.ESPNow()
    print("early ESP-NOW up")
except Exception as exc:
    print("early ESP-NOW failed:", type(exc).__name__, exc)

ap_started = False
if _ecfg.get("ap_enabled", True):
    try:
        wifi.radio.enabled = True
        if AP_PASSWORD and len(AP_PASSWORD) >= 8:
            wifi.radio.start_ap(ssid=AP_SSID, password=AP_PASSWORD)
        else:
            wifi.radio.start_ap(ssid=AP_SSID)
        ap_started = True
        print("early AP up: %s @ %s" % (AP_SSID, wifi.radio.ipv4_address_ap))
    except Exception as exc:
        print("early AP failed:", exc)

del _ecfg

import alerts
import battery
import datastore
import display_hw
import display_ui
import net_captive
import net_espnow
import net_wifi
import sensors_local
# (adafruit_ble was already imported in the early block when enabled;
# net_ble itself is wired up after the handlers exist)

# ---------------------------------------------------------------------------
# Display + storage pins. eInk pins live in display_hw profiles (Feather +
# wing: CS=D9/DC=D10; QT Py + BFF: CS=TX/DC=RX). SD/SRAM only exist on the
# Feather wing -- getattr keeps QT Py (no D5/D6) working.
# ---------------------------------------------------------------------------
SD_CS = getattr(board, "D5", None)
SRAM_CS = getattr(board, "D6", None)

CONFIG_FLASH = "/config.json"  # shipped defaults; runtime overrides live on
                               # the datastore root (/sd, /saves, or /)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _mem(tag):
    gc.collect()
    print("mem[%s]: %d free" % (tag, gc.mem_free()))


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _deep_merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


config = _load_json(CONFIG_FLASH)

# ---------------------------------------------------------------------------
# Bus + storage bring-up
# ---------------------------------------------------------------------------
displayio.release_displays()
spi = board.SPI()

# SRAM on the FeatherWing is unused -- hold its CS deselected so it never
# answers on the shared bus.
if SRAM_CS is not None:
    _sram_cs = digitalio.DigitalInOut(SRAM_CS)
    _sram_cs.switch_to_output(value=True)

# ---------------------------------------------------------------------------
# Display (profile-based: 3.52" quad on Feather wing / 2.9" tri on QT Py BFF)
# ---------------------------------------------------------------------------
display = None
palette_mode = "quad"
try:
    display, palette_mode = display_hw.init_display(
        spi,
        profile_name=config.get("display_profile", "auto"),
        overrides=config.get("display"),
    )
except (ValueError, OSError, RuntimeError, AttributeError, ImportError) as exc:
    print("Display init failed:", exc)

# Build the persistent dashboard NOW, while the heap is still roomy --
# later (with the BLE stack + portals resident) there is not enough
# contiguous memory left to construct its ~40 display objects. Refreshes
# only mutate it in place from here on.
_dashboard = None
if display is not None:
    try:
        gc.collect()
        _dashboard = display_ui.Dashboard(
            180 if display.width == 184 else display.width,
            180 if display.height == 184 else display.height,
            palette_mode,
            lite=gc.mem_free() < 60000,  # C6 with BLE resident: slim tree
        )
        # attach now: the boot-screen group (already on the panel) becomes
        # garbage and its RAM comes back; the panel itself keeps showing
        # "Loading Data" until the first dashboard refresh
        display.root_group = _dashboard.root
        gc.collect()
        print("dashboard tree built (mem %d)" % gc.mem_free())
    except (MemoryError, ValueError) as exc:
        print("dashboard build failed:", exc)

sd_mounted = False
if SD_CS is not None:
    try:
        _sd = sdcardio.SDCard(spi, SD_CS)
        storage.mount(storage.VfsFat(_sd), "/sd")
        sd_mounted = True
        print("SD mounted")
    except (OSError, ValueError) as exc:
        print("SD mount failed:", exc)
        # a failed SDCard() leaves the shared SPI bus LOCKED, which makes
        # every eInk refresh fail with a misleading "Refresh too soon"
        # (displayio can't acquire the bus). Unlock it; rebuild if stuck.
        try:
            spi.unlock()
            print("SPI unlocked after failed SD probe")
        except (RuntimeError, ValueError, OSError) as exc2:
            print("SPI unlock failed (%s); rebuilding bus" % exc2)
            try:
                spi.deinit()
            except (OSError, ValueError, RuntimeError):
                pass
            spi = board.SPI()
        if spi.try_lock():
            spi.unlock()
            print("SPI bus verified free")
        else:
            print("WARNING: SPI bus still locked - display will not refresh")
else:
    print("no SD slot on this rig (QT Py BFF); RAM-only buffering")

# Runtime overrides live on writable storage (SD preferred; CPSAVES or the
# flash root on no-MSC boards like the C6) -- never remounted USB flash.
for _root in ("/sd", "/saves", "/"):
    _ov = _load_json(_root.rstrip("/") + "/config.json")
    if _ov:
        _deep_merge(config, _ov)
        break

# ---------------------------------------------------------------------------
# WiFi (settings.toml may have auto-connected us already)
# ---------------------------------------------------------------------------
ip = None
if wifi.radio.connected:
    ip = str(wifi.radio.ipv4_address)
else:
    ssid = os.getenv("CIRCUITPY_WIFI_SSID") or os.getenv("WIFI_SSID")
    pw = os.getenv("CIRCUITPY_WIFI_PASSWORD") or os.getenv("WIFI_PASSWORD")
    if ssid:
        ip = net_wifi.connect(ssid, pw or "", config.get("timezone_offset_h", 0))

MAC = envproto.mac_str(wifi.radio.mac_address)
print("collector MAC (nodes self-discover it over ESP-NOW):", MAC)

# hub time service: synced by NTP (net_wifi.connect) or by a browser via
# POST /api/time / BLE "time <epoch>"; pushed to nodes in every cfg reply
TIME_SYNCED = time.localtime()[0] >= 2025
print("clock:", "synced" if TIME_SYNCED else "UNSYNCED (waiting for NTP/browser)")

# Radio subsystems were started in the EARLY block (BLE -> ESP-NOW -> AP,
# the only ordering that coexists on the C6); wire the wrappers here.
hub = net_espnow.EspNowHub(existing=_espnow_obj)
print("bring-up: ESP-NOW wrapper (enabled=%s)" % hub.enabled)
_mem("after espnow")
captive = net_captive.CaptivePortal(
    ssid=AP_SSID,
    password=AP_PASSWORD,
    enabled=config.get("ap_enabled", True),
    already_active=ap_started,
)
print("bring-up: captive DNS done (AP active=%s)" % captive.ap_active)
_mem("after AP")

# Radio first on purpose: starting the AP after displayio is up
# hard-faults the CP core on ESP32-C6 (10.3.0-a4). All radio
# bring-up therefore happens before the display/sensors.

# ---------------------------------------------------------------------------
# Sensor, battery, stores
# ---------------------------------------------------------------------------
i2c = None
local_sensor = None
try:
    # prefer the STEMMA QT connector where it's a separate bus (QT Py)
    i2c = (board.STEMMA_I2C() if hasattr(board, "STEMMA_I2C")
           else board.I2C())
    local_sensor = sensors_local.LocalSensor(i2c)
    print("SEN66:", local_sensor.product, local_sensor.serial)
except (OSError, ValueError, RuntimeError) as exc:
    print("Local sensor init failed:", exc)

batt_mon = battery.BatteryMonitor(
    i2c,
    unplugged_v=config.get("host_vcc_unplugged_v", 4.35),
)
print("battery source:", batt_mon.source)
_mem("after sensor+batt")

# only offer /sd as a root when the card actually mounted -- a stale /sd
# DIRECTORY on the flash filesystem would otherwise masquerade as the card
store = datastore.DataStore(
    roots=(("/sd",) if sd_mounted else ()) + ("/saves", "/"),
    flush_interval_s=config.get("sd_flush_interval_s", 600),
    flush_max_pending=config.get("sd_flush_max_pending", 24),
    min_free_bytes=config.get("flash_min_free_kb", 50) * 1024,
)
print("storage:", store.mode, store.root)
_mem("after storage")
ring = datastore.SampleRing(
    capacity=config.get("ring_capacity", 120))  # 2.4KB default; C6 is tight

def _record_interval():
    """Record cadence; stretched on flash to limit wear + fill rate."""
    base = config.get("record_interval_s", 60)
    if store.on_flash:
        return base * config.get("flash_record_multiplier", 5)
    return base

_display_dirty = [False]


def _on_alert_event(event):
    store.log_event(event)  # also forces an SD flush
    _display_dirty[0] = True  # show abnormal states promptly
    print("ALERT: %(src)s %(metric)s -> %(state)s (was %(prev)s, held %(held_s)ss)"
          % event)


tracker = alerts.AlertTracker(config.get("thresholds", {}), _on_alert_event)


# ---------------------------------------------------------------------------
# Shared API handlers (HTTP + BLE)
# ---------------------------------------------------------------------------
node_macs = {}      # src name -> mac bytes (for cfg replies)
pending_cal = {}    # src -> {"step": 1, "ts": epoch} / {"armed": target}
cal_results = {}    # src -> {"ok":, "corr":, "ts":}

CAL_STEP1_MSG = (
    "STEP 1 armed. Take the sensor OUTSIDE (or to fresh air, ~%dppm) and "
    "leave it measuring for at least 3 minutes. THEN run step 2. "
    "Calibrating indoors will mis-calibrate the sensor."
)


def _zone(src):
    return config.get("zones", {}).get(src, src)


def _node_batt_warnings():
    warn_v = config.get("node_batt_warn_v", 3.5)
    crit_v = config.get("node_batt_crit_v", 3.3)
    out = []
    for src, entry in store.latest.items():
        if src == "local":
            continue
        vb = entry.get("vb")
        if vb is not None and vb < warn_v:
            out.append((_zone(src), vb, vb < crit_v))
    return out


def h_latest():
    now = int(time.time())
    sources = {}
    for src, entry in store.latest.items():
        states = {}
        for key in entry.get("m", {}):
            st = tracker.state_of(src, key)
            if st:
                states[key] = st
        sources[src] = {
            "zone": _zone(src),
            "m": entry.get("m", {}),
            "vb": entry.get("vb"),
            "ts": entry.get("ts"),
            "age": alerts.fmt_duration(max(0, now - entry.get("ts", now))),
            "type": entry.get("type"),
            "rssi": entry.get("rssi"),
            "states": states,
        }
    abnormal = []
    for a in tracker.active_abnormal(now):
        abnormal.append({
            "src": _zone(a["src"]), "metric": a["metric"],
            "state": a["state"], "for": alerts.fmt_duration(a["for_s"]),
            "for_s": a["for_s"],
        })
    return {"ts": now, "mac": MAC, "sources": sources, "abnormal": abnormal}


def h_battery():
    nodes = []
    for name, vb, crit in _node_batt_warnings():
        nodes.append({"src": name, "v": vb, "warn": True, "crit": crit})
    return {"host": batt_mon.status(), "nodes": nodes}


def h_events():
    recent = []
    ev_path = (store.root or "/sd").rstrip("/") + "/events.csv"
    try:
        with open(ev_path) as f:
            try:
                f.seek(max(0, os.stat(ev_path)[6] - 2048))
            except OSError:
                pass
            recent = f.read().split("\n")[-25:]
    except OSError:
        pass
    return {
        "active": h_latest()["abnormal"],
        "recent": [l for l in recent if l],
    }


def h_config_get():
    return config


def h_config_set(body):
    if not isinstance(body, dict):
        return {"err": "expected object"}
    _deep_merge(config, body)
    tracker.thresholds = config.get("thresholds", {})
    store.flush_interval_s = config.get("sd_flush_interval_s", 600)
    store.flush_max_pending = config.get("sd_flush_max_pending", 24)
    batt_mon.unplugged_v = config.get("host_vcc_unplugged_v", 4.35)
    saved = False
    if store.root is not None:
        try:
            with open(store.root.rstrip("/") + "/config.json", "w") as f:
                json.dump(config, f)
            os.sync()
            saved = True
        except OSError as exc:
            print("config save failed:", exc)
    _display_dirty[0] = True
    return {"ok": True, "saved_to_sd": saved, "config": config}


def h_calibrate(src, step):
    target = config.get("co2_cal_target_ppm", 420)
    if step == 1:
        pending_cal[src] = {"step": 1, "ts": int(time.time())}
        return {"ok": True, "src": src, "step": 1, "msg": CAL_STEP1_MSG % target}
    if step == 2:
        armed = pending_cal.get(src)
        if not armed or armed.get("step") != 1:
            return {"err": "run step 1 first (and follow its instructions)"}
        if src == "local":
            if local_sensor is None:
                return {"err": "local sensor not available"}
            try:
                corr = local_sensor.force_recalibration(target)
            except (OSError, RuntimeError) as exc:
                return {"err": "recalibration failed: %s" % exc}
            del pending_cal[src]
            cal_results[src] = {"ok": True, "corr": corr, "ts": int(time.time())}
            return {"ok": True, "src": src, "correction_ppm": corr}
        # remote node: arm; delivered in the cfg reply at its next check-in
        pending_cal[src] = {"armed": target, "ts": int(time.time())}
        return {"ok": True, "src": src, "step": 2,
                "msg": "armed - node will recalibrate at its next check-in "
                       "(within its sleep interval); result appears in "
                       "/api/events and cal results"}
    return {"err": "step must be 1 or 2"}


def h_ingest(body):
    """WiFi fallback transport: nodes POST the same envproto JSON here."""
    obj = envproto.decode(body if isinstance(body, (bytes, str)) else b"")
    if obj is None:
        return {"err": "bad packet"}
    _handle_node_packet(None, obj, None)
    reply = _cfg_reply_for(obj.get("n", "?"))
    return {"ok": True, "cfg": json.loads(reply)}


def h_list_days():
    return store.list_days()


def h_time_set(epoch):
    """Set the hub clock (browser time via web page / BLE). Pending
    records buffered with a wrong clock are retro-adjusted."""
    global TIME_SYNCED
    try:
        epoch = int(epoch)
    except (TypeError, ValueError):
        return {"err": "epoch (seconds) required"}
    if epoch < envproto.PLAUSIBLE_EPOCH:
        return {"err": "implausible epoch"}
    delta = epoch - int(time.time())
    rtc.RTC().datetime = time.localtime(epoch)
    adjusted = 0
    if abs(delta) > 5:
        adjusted = store.adjust_pending(delta)
    TIME_SYNCED = True
    print("clock set by client: %+ds (%d pending adjusted)" % (delta, adjusted))
    return {"ok": True, "delta_s": delta, "adjusted": adjusted,
            "now": int(time.time())}


def h_history_lines(day):
    """Generator of file chunks for BLE streaming, or None if missing."""
    if store.data_dir() is None:
        return None
    path = "%s/%s.csv" % (store.data_dir(), day)

    def _gen():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(512)
                if not chunk:
                    return
                yield chunk

    try:
        os.stat(path)
    except OSError:
        return None
    return _gen()


handlers = {
    "latest": h_latest,
    "battery": h_battery,
    "events": h_events,
    "config_get": h_config_get,
    "config_set": h_config_set,
    "calibrate": h_calibrate,
    "ingest": h_ingest,
    "list_days": h_list_days,
    "history_lines": h_history_lines,
    "data_dir": lambda: store.data_dir(),
    "time_set": h_time_set,
}

# ---------------------------------------------------------------------------
# Node packet handling
# ---------------------------------------------------------------------------

def _cfg_reply_for(src):
    interval = config.get("node_intervals", {}).get(
        src, config.get("node_default_interval_s", 120)
    )
    metrics = config.get("node_metrics", {}).get(src)
    cal = None
    armed = pending_cal.get(src)
    if armed and "armed" in armed:
        cal = armed["armed"]
    return envproto.make_config_packet(
        interval, metrics=metrics, asc=False, cal_target=cal,
        epoch=int(time.time()) if TIME_SYNCED else None,
    )


def _handle_node_packet(mac, obj, rssi):
    kind = obj.get("k")
    src = obj.get("n", "node-%s" % (envproto.mac_str(mac)[-5:] if mac else "?"))
    if mac is not None:
        node_macs[src] = mac
    if kind == "dsc":
        # discovery ping: the cfg reply (sent by the caller) is the answer --
        # the node learns our MAC + channel from it. Just log the sighting.
        print("discovery from %s (%s)" % (src, envproto.mac_str(mac) if mac else "?"))
    elif kind == "dat":
        m = obj.get("m", {})
        vb = obj.get("vb")
        # honour the node's reading timestamp (stashed retransmissions);
        # ignore implausible values from unsynced node clocks
        at = obj.get("at")
        if not (at and at > envproto.PLAUSIBLE_EPOCH):
            at = None
        store.update_latest(src, m, batt_v=vb, sensor_type=obj.get("t"),
                            rssi=rssi, ts=at)
        sample = dict(m)
        if vb is not None:
            sample["vb"] = vb
        ring.add(src, sample, flags=0, ts=at)
        worst = tracker.update(src, m)
        flags = datastore.FLAG_ABNORMAL if worst else 0
        # nodes already report at record cadence -> every packet is a record
        store.record(src, sample, flags=flags, ts=at)
    elif kind == "cal":
        ok = bool(obj.get("ok"))
        cal_results[src] = {"ok": ok, "corr": obj.get("corr"),
                            "ts": int(time.time())}
        if ok and src in pending_cal:
            del pending_cal[src]
        store.log_event({
            "ts": int(time.time()), "src": src, "metric": "co2",
            "state": "cal_ok" if ok else "cal_fail", "prev": "",
            "value": obj.get("corr"), "held_s": 0,
        })


# ---------------------------------------------------------------------------
# Portals
# ---------------------------------------------------------------------------
portal = net_wifi.WebPortal(handlers, portal_host=captive.ap_ip
                            if captive.ap_active else None,
                            port=config.get("http_port", 80))
for _attempt in (1, 2):
    try:
        portal.start(ap_active=captive.ap_active)
        break
    except (MemoryError, OSError, RuntimeError) as exc:
        # keep booting: data collection + display matter more than HTTP
        print("HTTP portal start failed (try %d): %s" % (_attempt, exc))
        gc.collect()
        time.sleep(2)
_mem("after http portal")
# BLE radio/uart were created in the EARLY BLE START block (top of file);
# here we just wire the command portal around them. Late BLE creation
# alongside the softAP hard-faults the C6 core (bugs_issues_and_todos.md).
if config.get("ble_enabled", True) and _ble_radio is not None:
    import net_ble
    ble = net_ble.BleUartPortal(handlers, radio=_ble_radio, uart=_ble_uart,
                                adv=_ble_adv)
else:
    if config.get("ble_enabled", True):
        print("BLE unavailable (early init failed)")
    else:
        print("BLE disabled by config")

    class _NoBle:
        ok = False
        connected = False

        def poll(self):
            pass
    ble = _NoBle()
_mem("after BLE")

# ---------------------------------------------------------------------------
# Trend tracking: keep per-source averaged snapshots; compare now vs the
# oldest snapshot inside trend_window_s.
# ---------------------------------------------------------------------------
_trend_hist = {}  # src -> list of (ts, avg_dict)
_trends = {}      # src -> {metric: -1|0|1}

_TREND_MIN_DELTA = {"co2": 30, "pm25": 2, "tc": 0.4, "rh": 2, "voc": 15,
                    "nox": 10, "pm1": 2, "pm4": 2, "pm10": 3}


def _update_trends(src, avgs, now):
    window = config.get("trend_window_s", 600)
    hist = _trend_hist.setdefault(src, [])
    hist.append((now, avgs))
    while hist and now - hist[0][0] > window:
        hist.pop(0)
    if len(hist) < 2:
        return 0
    old = hist[0][1]
    tr = {}
    flags = 0
    for key, val in avgs.items():
        prev = old.get(key)
        if prev is None or val is None:
            continue
        delta = val - prev
        if abs(delta) >= _TREND_MIN_DELTA.get(key, 1):
            tr[key] = 1 if delta > 0 else -1
            # improving/declining is only meaningful when out of spec:
            # for upper-bound metrics falling == improving
            if tracker.state_of(src, key) != alerts.OK:
                if key in ("co2", "pm1", "pm25", "pm4", "pm10", "voc", "nox"):
                    flags |= (datastore.FLAG_IMPROVING if delta < 0
                              else datastore.FLAG_DECLINING)
        else:
            tr[key] = 0
    _trends[src] = tr
    return flags


# ---------------------------------------------------------------------------
# Display refresh. Quad-color eInk enforces ~180s minimum between
# refreshes (EPaperDisplay seconds_per_frame default) and raises
# "Refresh too soon" -- and time_to_refresh does NOT reliably report it
# on this build, so we keep our own clock.
# ---------------------------------------------------------------------------
# panel minimum between refreshes: the quad takes ~20s per refresh and
# display_hw sets seconds_per_frame to match (the core default of 180s
# was just EPaperDisplay's conservatism); small margin on top here
_MIN_REFRESH_S = config.get("display_min_refresh_s", 25)
# the "Loading Data" boot screen (display_hw) used the first refresh
# slot; the dashboard lands once the panel's minimum interval has passed
_last_refresh_ok = time.monotonic()
_next_refresh_try = 0.0


def _status_line():
    bits = []
    bits.append("W:%s" % (ip or "off"))
    if captive.ap_active:
        bits.append("AP:%s" % AP_SSID)
    bits.append({"sd": "SD:ok", "flash": "ST:flash", "ram": "ST:RAM!"}[store.mode])
    if ble.ok:
        bits.append("B:%s" % ("con" if ble.connected else "adv"))
    bits.append("E:%d" % hub.rx_count)
    if not store.latest or len(store.latest) <= 1:
        bits.append(MAC)
    return " ".join(bits)


def refresh_display(now_epoch):
    """Update the persistent dashboard in place + refresh. True on success."""
    global _dashboard
    if display is None:
        return False
    # C6/CP10.3-a4 bug: the wifi stack corrupts the SPI lock flag, leaving
    # the bus "locked" with no owner; refresh() then fails "Refresh too
    # soon" forever. Only the display and the (idle/absent) SD share this
    # bus, so clearing the stale lock is safe.
    try:
        spi.unlock()
    except (RuntimeError, ValueError, OSError):
        pass  # not locked - normal
    gc.collect()
    try:
        if _dashboard is None:
            # panel shows 384x180 of the 384x184 buffer: clamp the 184-axis
            _dashboard = display_ui.Dashboard(
                180 if display.width == 184 else display.width,
                180 if display.height == 184 else display.height,
                palette_mode,
            )
        _dashboard.update(
            latest=store.latest,
            tracker=tracker,
            zones=config.get("zones", {}),
            host_batt=batt_mon.status(),
            node_batt_warnings=_node_batt_warnings(),
            trends=_trends,
            status_line=_status_line(),
            now=now_epoch,
            storage_mode=store.mode,
        )
        # NEVER set root_group = None (re-shows the console splash, whose
        # supervisor auto-refresh starves user refreshes)
        if display.root_group is not _dashboard.root:
            display.root_group = _dashboard.root
        display.refresh()
        _display_dirty[0] = False
        gc.collect()
        return True
    except (RuntimeError, MemoryError) as exc:
        print("display refresh failed: %s (mem %d)" % (exc, gc.mem_free()))
        gc.collect()
        return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
print("collector running; portal:", "http://%s/" % ip if ip else "no wifi")

_last_sample = 0.0
_last_record = 0.0
_last_gc = 0.0
_boot_epoch = time.time()

_err_streak = 0

while True:
    now_m = time.monotonic()
    now_e = int(time.time())
    try:
        # 1. remote nodes over ESP-NOW (reply immediately -- they nap fast)
        for mac, obj, rssi in hub.poll():
            try:
                _handle_node_packet(mac, obj, rssi)
                if obj.get("k") in ("dat", "dsc"):
                    hub.send(mac, _cfg_reply_for(obj.get("n", "?")))
            except Exception as exc:  # one bad packet must not kill the loop
                print("node packet error:", type(exc).__name__, exc)

        # 2. local sensor sampling into the RAM ring
        if local_sensor and now_m - _last_sample >= config.get(
                "sample_interval_s", 15):
            _last_sample = now_m
            m = local_sensor.read()
            if m:
                hb = batt_mon.status()
                sample = dict(m)
                if hb.get("v") is not None:
                    sample["vb"] = hb["v"]
                ring.add("local", sample)
                store.update_latest("local", m, batt_v=hb.get("v"),
                                    sensor_type="sen66")
                tracker.update("local", m)
                if hb.get("crit"):
                    store.flush()  # about to brown out? save everything now

        # 3. averaged record at the user cadence (stretched on flash storage)
        if now_m - _last_record >= _record_interval():
            _last_record = now_m
            avgs = ring.averages("local", _record_interval() * 2)
            if avgs:
                flags = _update_trends("local", avgs, now_e)
                if tracker.worst_for("local"):
                    flags |= datastore.FLAG_ABNORMAL
                store.record("local", avgs, flags=flags)

        # 4. display: the FIRST refresh waits until the system is genuinely
        # ready -- boot settle window elapsed (sensor warmed up, nodes had a
        # chance to check in, alerts collated) AND data on hand. After that,
        # refreshes follow the user schedule; alerts pull one forward, the
        # panel's ~180s hardware minimum is always respected, and a failed
        # attempt backs off 30s instead of spinning.
        _since_ok = now_m - _last_refresh_ok
        _settled = now_m >= config.get("boot_display_delay_s", 60)
        if (store.latest and _settled
                and (_since_ok >= max(config.get("display_interval_s", 120),
                                      _MIN_REFRESH_S)
                     or (_display_dirty[0] and _since_ok >= _MIN_REFRESH_S))
                and now_m >= _next_refresh_try):
            if refresh_display(now_e):
                _last_refresh_ok = now_m
                print("dashboard refreshed (mem %d)" % gc.mem_free())
            else:
                _next_refresh_try = now_m + 30

        # 5. portals + housekeeping
        portal.poll()
        ble.poll()
        captive.poll()
        store.maybe_flush()

        # we're tight on RAM (no PSRAM): sweep regularly so captive-probe /
        # HTTP bursts can't fragment the heap out from under the next
        # screen build or DHCP lease. Also watch the AP: on the C6 other
        # radio activity has been seen to silently kill it.
        if now_m - _last_gc >= 10:
            _last_gc = now_m
            gc.collect()
            if captive.ap_active and not wifi.radio.ap_active:
                print("WARNING: softAP dropped (radio interference bug)")
                captive.ap_active = False

        _err_streak = 0
    except MemoryError:
        # recover heap and keep the buffered data alive
        gc.collect()
        print("loop MemoryError; collected (mem %d)" % gc.mem_free())
    except Exception as exc:
        # never lose data to a crash: log, and if errors persist, flush
        # everything to storage and take a clean reset
        _err_streak += 1
        print("loop error %d/20: %s: %s" % (_err_streak,
                                            type(exc).__name__, exc))
        if _err_streak >= 20:
            print("persistent errors: flushing data, then resetting")
            try:
                store.flush()
            except Exception:
                pass
            time.sleep(1)
            microcontroller.reset()
        time.sleep(0.5)

    time.sleep(0.05)
