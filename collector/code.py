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
# BLE name carries the MAC suffix so several hubs on one site stay distinct
# (clients match on the ENVHUB prefix + Nordic UART service).
BLE_NAME = (os.getenv("ENVHUB_BLE_NAME")
            or _ecfg.get("ble_name")
            or "ENVHUB-" + envproto.short_mac(wifi.radio.mac_address)[-4:])
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
        _ble_radio.name = BLE_NAME
        _ble_uart = UARTService()
        _ble_adv = ProvideServicesAdvertisement(_ble_uart)
        _ble_adv.complete_name = BLE_NAME
        _ble_radio.start_advertising(_ble_adv)
        print("early BLE advertising as", BLE_NAME)
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
        # CP 10.3-a4 does NOT auto-start the softAP DHCP server: without
        # this, phones associate and immediately drop (no lease)
        try:
            wifi.radio.start_dhcp_ap()
        except (AttributeError, RuntimeError) as exc:
            print("start_dhcp_ap:", exc)
        ap_started = True
        print("early AP up: %s @ %s" % (AP_SSID, wifi.radio.ipv4_address_ap))
    except Exception as exc:
        print("early AP failed:", exc)

# HTTP serving only makes sense with an AP or STA WiFi: in BLE-only mode
# skip the whole adafruit_httpserver/socket stack -- its import + server
# cost tens of KB that the resident BLE stack has already spoken for, and
# at ~15KB free the C6 can't even complete an incoming GATT connection
# (three client stacks all timed out until this was reclaimed).
HTTP_WANTED = (_ecfg.get("ap_enabled", True)
               or bool(os.getenv("CIRCUITPY_WIFI_SSID")
                       or os.getenv("WIFI_SSID")))
del _ecfg

import alerts
import battery
import calref
import datastore
import display_hw
import display_ui
import net_espnow
import sensors_local
if HTTP_WANTED:
    import net_captive
    import net_wifi
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


def _make_spi():
    # Feathers/QT Py expose board.SPI(); bare devkits (bring-up bench) don't,
    # so fall back to busio on free GPIOs (C6: SCK=IO6 MOSI=IO7 MISO=IO2).
    if hasattr(board, "SPI"):
        return board.SPI()
    import busio
    return busio.SPI(board.IO6, board.IO7, board.IO2)


spi = _make_spi()

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
            spi = _make_spi()
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
elif HTTP_WANTED:
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
if HTTP_WANTED:
    captive = net_captive.CaptivePortal(
        ssid=AP_SSID,
        password=AP_PASSWORD,
        enabled=config.get("ap_enabled", True),
        already_active=ap_started,
    )
    print("bring-up: captive DNS done (AP active=%s)" % captive.ap_active)
else:
    class _NoCaptive:
        ap_active = False
        ap_ip = None

        def poll(self):
            pass
    captive = _NoCaptive()
    print("bring-up: HTTP/captive stack skipped (BLE-only mode)")
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
    if hasattr(board, "STEMMA_I2C"):
        i2c = board.STEMMA_I2C()
    elif hasattr(board, "I2C"):
        i2c = board.I2C()
    else:  # bare devkit: SDA=IO19 SCL=IO20
        import busio
        i2c = busio.I2C(board.IO20, board.IO19)
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
    # mesh delivery health: every node packet we received, confirmed back,
    # re-confirmed as a duplicate, or could not decode at all
    mesh = {"rx": hub.rx_count, "ack": hub.ack_count, "dup": hub.dup_count,
            "bad": hub.bad_count}
    if hub.last_error:
        mesh["err"] = hub.last_error
    return {"ts": now, "mac": MAC, "sources": sources, "abnormal": abnormal,
            "mesh": mesh}


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


# reference calibration state (ASC is OFF everywhere: this is the sensor's
# only correction, so it is a scheduled, stability-gated, two-step affair)
_local_cal = None   # {"target","at","dur","dry","samples","started"}


def _cal_defaults():
    return (config.get("co2_cal_target_ppm", 420),
            config.get("cal_window_s", 3600),
            config.get("cal_now_window_s", 180),
            config.get("cal_min_batt_v", 3.7),
            config.get("cal_asc_window_s", 48 * 3600))


def h_cal_status():
    """Pending/armed/scheduled calibrations + last results, per source."""
    now = int(time.time())
    out = {"pending": {}, "results": cal_results, "local": None}
    for src, p in pending_cal.items():
        d = dict(p)
        if d.get("at"):
            d["starts_in_s"] = d["at"] - now
        out["pending"][src] = d
    if _local_cal:
        lc = {k: _local_cal[k] for k in ("target", "at", "dur", "dry")}
        lc["samples"] = len(_local_cal["samples"])
        lc["running"] = _local_cal["started"] is not None
        if lc["running"]:
            lc["remaining_s"] = max(0, _local_cal["started"]
                                    + _local_cal["dur"] - now)
        else:
            lc["starts_in_s"] = _local_cal["at"] - now
        out["local"] = lc
    return out


def h_calibrate(src, step, opts=None):
    """Two-step CO2 reference calibration.

    step 1: arm + return the setup / power / timing guidance.
    step 2: schedule the measurement window. opts: when='4am' (default:
      next 04:00 local, cal_window_s long) | 'now' (cal_now_window_s) |
      epoch; duration_s override; target_ppm override; dry=true never
      writes the FRC (rehearsal). Nodes get it in their next cfg reply and
      wake for it; the hub's own SEN66 runs it from the main loop.
    """
    global _local_cal
    opts = opts or {}
    target, win_s, now_s, min_v, asc_s = _cal_defaults()
    try:
        target = int(opts.get("target_ppm") or target)
    except (TypeError, ValueError):
        return {"err": "bad target_ppm"}
    if step == 1:
        pending_cal[src] = {"step": 1, "ts": int(time.time())}
        return {"ok": True, "src": src, "step": 1, "target_ppm": target,
                "msg": calref.STEP1_GUIDANCE % {
                    "src": src, "min_v": min_v, "target": target,
                    "dur_min": win_s // 60, "now_min": now_s // 60}
                + " " + calref.ASC_GUIDANCE % {"asc_h": asc_s // 3600,
                                               "target": target}}
    if step != 2:
        return {"err": "step must be 1 or 2"}
    armed = pending_cal.get(src)
    if not armed or armed.get("step") != 1:
        return {"err": "run step 1 first (and follow its instructions)"}
    asc = str(opts.get("mode", "frc")).lower() == "asc"
    when = str(opts.get("when", "now" if asc else "4am")).lower()
    dry = bool(opts.get("dry")) and not asc
    now = int(time.time())
    if when == "now":
        at, dur = 0, (asc_s if asc else now_s)
    else:
        if not TIME_SYNCED:
            return {"err": "hub clock not synced: sync it (browser / BLE "
                           "'time') to schedule, or use when='now'"}
        if when in ("4am", "next", ""):
            at = calref.next_local_time(now, config.get("timezone_offset_h", 0),
                                        hour=config.get("cal_hour_local", 4))
        else:
            try:
                at = int(when)
            except ValueError:
                return {"err": "when must be '4am', 'now' or an epoch"}
            if at < now:
                return {"err": "that time is in the past"}
        dur = asc_s if asc else win_s
    try:
        dur = int(opts.get("duration_s") or dur)
    except (TypeError, ValueError):
        return {"err": "bad duration_s"}
    dur = max(120, min(dur, 72 * 3600 if asc else 12 * 3600))
    plan = {"armed": target, "at": at, "dur": dur, "dry": dry, "asc": asc,
            "ts": now}
    if src == "local":
        if local_sensor is None:
            return {"err": "local sensor not available"}
        _local_cal = {"target": target, "at": at, "dur": dur, "dry": dry,
                      "asc": asc, "samples": [], "started": None}
        del pending_cal[src]
        where = "hub"
    else:
        pending_cal[src] = plan   # delivered in the node's next cfg reply
        where = "node (delivered at its next check-in; it wakes for the window)"
    _display_dirty[0] = True
    return {"ok": True, "src": src, "step": 2, "target_ppm": target,
            "starts_at": at or now, "starts_in_s": max(0, at - now),
            "duration_s": dur, "dry_run": dry, "mode": "asc" if asc else "frc",
            "msg": "%s calibration %s: %s, %s window of %d min%s. Keep the "
                   "sensor in fresh air and powered for the whole window; "
                   "result appears in events / cal status." % (
                       "ASC" if asc else ("DRY-RUN" if dry else "Reference"),
                       "scheduled on the " + where,
                       ("starting now" if not at else
                        "starting in %dh%02dm" % ((at - now) // 3600,
                                                  ((at - now) % 3600) // 60)),
                       "automatic-self-calibration ON" if asc else "measurement",
                       dur // 60,
                       (", then ASC OFF again (before/after readings reported)"
                        if asc else ("" if dry else
                        ", then stability check and forced recalibration to "
                        "%d ppm" % target)))}


def _local_cal_tick(now, co2):
    """Drive the hub's own reference-calibration window from the main
    loop: collect co2 samples through the window, gate on stability,
    then write (or dry-run) the FRC and log the result."""
    global _local_cal
    lc = _local_cal
    if lc is None:
        return
    if lc["started"] is None:
        if now < lc["at"]:
            return
        lc["started"] = now
        lc["samples"] = []
        print("CAL: hub %s window started (%d min%s)"
              % ("ASC" if lc.get("asc") else "reference", lc["dur"] // 60,
                 ", dry run" if lc["dry"] else ""))
        lc["asc_on"] = False
        if lc.get("asc"):
            try:
                local_sensor.set_asc(True)
                lc["asc_on"] = True
            except (OSError, RuntimeError, AttributeError) as exc:
                print("CAL: could not enable ASC:", exc)
                lc["asc_err"] = str(exc)
    if co2 is not None:
        lc["samples"].append((now, co2))
    if now - lc["started"] < lc["dur"]:
        return
    if lc.get("asc"):
        # ASC mode: the sensor adjusted itself (or not); report the shift
        try:
            local_sensor.set_asc(False)
        except (OSError, RuntimeError, AttributeError) as exc:
            print("CAL: could not disable ASC again:", exc)
        head = [v for _, v in lc["samples"][:30]]
        tail = [v for _, v in lc["samples"][-30:]]
        ref0 = calref._median(head) if head else None
        ref = calref._median(tail) if tail else None
        ok = ref is not None and lc.get("asc_on", False)
        why = "" if ok else ("ASC not enabled: %s" % lc.get("asc_err", "")
                             if not lc.get("asc_on") else "no samples")
        res = {"ok": ok, "mode": "asc", "ref_start": ref0, "ref": ref,
               "shift": (ref - ref0) if ok and ref0 is not None else None,
               "why": why, "ts": now}
        cal_results["local"] = res
        store.log_event({"ts": now, "src": "local", "metric": "co2",
                         "state": "cal_asc" if ok else "cal_fail",
                         "prev": "start %s" % ref0, "value": ref,
                         "held_s": lc["dur"]})
        print("CAL: hub ASC result", res)
        _local_cal = None
        _display_dirty[0] = True
        return
    ok, ref, spread, why = calref.evaluate(
        lc["samples"], lc["target"], config.get("cal_max_spread_ppm", 60))
    corr = None
    if ok and not lc["dry"]:
        try:
            corr = local_sensor.force_recalibration(lc["target"])
        except (OSError, RuntimeError) as exc:
            ok, why = False, "FRC failed: %s" % exc
    res = {"ok": ok, "corr": corr, "ref": ref, "spread": spread,
           "why": why, "dry": lc["dry"], "ts": now}
    cal_results["local"] = res
    store.log_event({"ts": now, "src": "local", "metric": "co2",
                     "state": ("cal_dry" if lc["dry"] else "cal_ok") if ok
                     else "cal_fail", "prev": why or "",
                     "value": ref, "held_s": lc["dur"]})
    print("CAL: hub result", res)
    _local_cal = None
    _display_dirty[0] = True


def h_ingest(body):
    """WiFi fallback transport: nodes POST the same envproto JSON here.

    The response carries the same confirmation as the ESP-NOW path (message
    id + CRC-16 of the bytes we received, inside the cfg push), so a node
    gets identical delivery proof whichever transport it fell back to.
    """
    raw = body if isinstance(body, bytes) else (body or "").encode()
    obj = envproto.decode(raw)
    if obj is None:
        return {"err": "bad packet"}
    fresh, reply = confirm_node_packet(None, obj, envproto.crc16(raw))
    if fresh:
        _handle_node_packet(None, obj, None)
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
    "cal_status": h_cal_status,
    "ingest": h_ingest,
    "list_days": h_list_days,
    "history_lines": h_history_lines,
    "data_dir": lambda: store.data_dir(),
    "time_set": h_time_set,
}

# ---------------------------------------------------------------------------
# Node packet handling
# ---------------------------------------------------------------------------

def _cfg_reply_for(src, ack_id=None, ack_crc=None):
    interval = config.get("node_intervals", {}).get(
        src, config.get("node_default_interval_s", 120)
    )
    metrics = config.get("node_metrics", {}).get(src)
    cal = cal_at = cal_dur = None
    cal_dry = False
    armed = pending_cal.get(src)
    if armed and "armed" in armed:
        cal = armed["armed"]
        cal_at = armed.get("at") or None
        cal_dur = armed.get("dur")
        cal_dry = armed.get("dry", False)
        cal_asc = armed.get("asc", False)
    else:
        cal_asc = False
    return envproto.make_config_packet(
        interval, metrics=metrics, asc=False, cal_target=cal,
        epoch=int(time.time()) if TIME_SYNCED else None,
        cal_at=cal_at, cal_dur=cal_dur, cal_dry=cal_dry, cal_asc=cal_asc,
        ack_id=ack_id, ack_crc=ack_crc,
    )


# Last packet confirmed per node: (kind, msg id, crc). A node whose
# confirmation went missing resends the identical packet -- we must confirm
# it again, but must NOT store the reading (or log the calibration) twice.
_last_rx = {}
# ...and the last few reading timestamps per node. A node that never got our
# confirmation keeps the reading in its stash and re-sends it on a later wake
# with a NEW message id, so the id check alone cannot catch that one; the
# reading time can (nodes sample far slower than 1 Hz).
_recent_at = {}
_RECENT_AT_KEEP = 8


def confirm_node_packet(mac, obj, crc):
    """Confirm a node packet FIRST, then let the caller do the slow work.

    The node is awake for a short listen window and naps straight after, so
    the reply goes out before SD writes / display work. The reply carries
    the message id and the CRC-16 of the bytes we received ("dat"/"dsc" get
    it inside the 'cfg' push, everything else gets a bare 'ack'), which is
    what lets the node distinguish "the radio ACKed" from "the hub has it".

    Returns (fresh, reply_bytes): fresh is True when the packet is new and
    should be processed; reply_bytes is the confirmation (already sent when
    mac is not None -- the HTTP fallback returns it in the response body).
    """
    kind = obj.get("k")
    src = obj.get("n", "node-%s" % (envproto.mac_str(mac)[-5:] if mac else "?"))
    msg_id = obj.get("sq", 0)
    if kind in ("dat", "dsc"):
        reply = _cfg_reply_for(src, ack_id=msg_id, ack_crc=crc)
    else:
        reply = envproto.make_ack_packet(msg_id, crc)
    if mac is not None:
        if hub.send(mac, reply):
            hub.ack_count += 1
        else:
            print("confirm to %s (%s sq=%s) failed to send"
                  % (src, kind, msg_id))
    fresh = _last_rx.get(src) != (kind, msg_id, crc)
    _last_rx[src] = (kind, msg_id, crc)
    if fresh and kind == "dat":
        at = obj.get("at")
        if at and at > envproto.PLAUSIBLE_EPOCH:
            seen = _recent_at.setdefault(src, [])
            if at in seen:
                fresh = False
            else:
                seen.append(at)
                if len(seen) > _RECENT_AT_KEEP:
                    del seen[0]
    if not fresh:
        hub.dup_count += 1
        print("duplicate %s sq=%s from %s: re-confirmed, not stored"
              % (kind, msg_id, src))
    return fresh, reply


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
        was = pending_cal.get(src) or {}
        cal_results[src] = {"ok": ok, "corr": obj.get("corr"),
                            "ref": obj.get("ref"), "ref_start": obj.get("ref0"),
                            "why": obj.get("why"),
                            "mode": "asc" if was.get("asc") else "frc",
                            "dry": was.get("dry", False), "ts": int(time.time())}
        if src in pending_cal:
            del pending_cal[src]   # node has run it (or refused): disarm
        store.log_event({
            "ts": int(time.time()), "src": src, "metric": "co2",
            "state": ("cal_asc" if was.get("asc") else
                      "cal_dry" if was.get("dry") else "cal_ok") if ok
            else "cal_fail", "prev": obj.get("why") or "",
            "value": obj.get("ref"), "held_s": 0,
        })
        print("CAL: %s result ok=%s ref=%s corr=%s %s"
              % (src, ok, obj.get("ref"), obj.get("corr"), obj.get("why") or ""))


# ---------------------------------------------------------------------------
# Portals
# ---------------------------------------------------------------------------
if HTTP_WANTED:
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
else:
    class _NoPortal:
        def poll(self):
            pass
    portal = _NoPortal()
_mem("after http portal")
# BLE radio/uart were created in the EARLY BLE START block (top of file);
# here we just wire the command portal around them. Late BLE creation
# alongside the softAP hard-faults the C6 core (bugs_issues_and_todos.md).
if config.get("ble_enabled", True) and _ble_radio is not None:
    import net_ble
    ble = net_ble.BleUartPortal(handlers, name=BLE_NAME, radio=_ble_radio, uart=_ble_uart,
                                adv=_ble_adv,
                                use_pktbuf=config.get("ble_tx_pktbuf", False))
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
    if _local_cal is not None:
        bits.append("CAL:%s" % ("run" if _local_cal["started"] else "wait"))
    elif any("armed" in p for p in pending_cal.values()):
        bits.append("CAL:node")
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
        # 1. remote nodes over ESP-NOW. Confirm first (id + CRC of what we
        #    received, carried by the cfg push), then do the slow work --
        #    the node's listen window is short and it naps straight after.
        for mac, obj, rssi, crc in hub.poll():
            try:
                if confirm_node_packet(mac, obj, crc)[0]:
                    _handle_node_packet(mac, obj, rssi)
            except Exception as exc:  # one bad packet must not kill the loop
                print("node packet error:", type(exc).__name__, exc)

        # 2. local sensor sampling into the RAM ring
        if local_sensor and now_m - _last_sample >= config.get(
                "sample_interval_s", 15):
            _last_sample = now_m
            m = local_sensor.read()
            if _local_cal is not None:
                _local_cal_tick(now_e, m.get("co2") if m else None)
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

    # idle slice: keep the (non-blocking) HTTP portal responsive between passes
    for _ in range(4):
        portal.poll()
        time.sleep(0.05)
