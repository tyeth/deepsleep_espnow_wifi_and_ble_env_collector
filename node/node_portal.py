# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
node_portal - first-boot / on-demand WiFi config portal for sensor nodes.

Nodes have no display, so configuration is files-and-WiFi (per spec). When
a node boots unconfigured (or with the BOOT button held), it raises an
open AP named SENSOR{mac-hex} with a captive portal serving one settings
form. Saving writes /node_config.json (with "configured": true) and
reboots into the normal deep-sleep cycle. Times out after timeout_s and
continues with current settings, so a node never hangs forever.

Everything else is self-configuring: the collector is found by ESP-NOW
broadcast discovery (no MAC to type in), and the collector pushes
interval/metrics/calibration on every check-in.
"""

import json
import time

import microcontroller
import wifi

try:
    import socketpool
    from adafruit_httpserver import GET, POST, Redirect, Request, Response, Server
    _HAVE_HTTP = True
except ImportError:
    _HAVE_HTTP = False

_FORM = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>%(ssid)s setup</title>
<style>body{font-family:system-ui;margin:1.2em;max-width:26em}
label{display:block;margin:.7em 0 .15em;font-weight:600}
input{width:100%%;padding:.45em;box-sizing:border-box}
button{margin-top:1em;padding:.6em 1.4em;font-size:1em}
small{color:#666}</style>
<h2>%(ssid)s</h2>
<p><small>Sensor node setup. The collector is discovered automatically
over ESP-NOW; only name it and (optionally) tune the rest.</small></p>
<form method=post action=/save>
<label>Zone / node name</label>
<input name=name value="%(name)s">
<label>Report interval (seconds)</label>
<input name=interval_s type=number min=10 value="%(interval_s)d">
<label>PM sensor fan warm-up (seconds)</label>
<input name=pm_warmup_s type=number min=0 value="%(pm_warmup_s)d">
<label>Metrics (comma-separated, blank = all)</label>
<input name=metrics value="%(metrics)s">
<label><input name=led type=checkbox %(led)s style="width:auto"> LED blink
 on report</label>
<button>Save &amp; reboot</button>
</form>"""

_PROBES = ("/generate_204", "/gen_204", "/hotspot-detect.html",
           "/library/test/success.html", "/connecttest.txt", "/ncsi.txt",
           "/redirect", "/canonical.html", "/success.txt")


class _Dns:
    """Answer every A query with our AP IP (captive portal)."""

    def __init__(self, pool, ip):
        self.ip = bytes(int(x) for x in ip.split("."))
        self.sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.sock.bind(("0.0.0.0", 53))
        self.buf = bytearray(256)

    def poll(self):
        for _ in range(4):
            try:
                n, addr = self.sock.recvfrom_into(self.buf)
            except OSError:
                return
            if n < 12:
                continue
            q = self.buf
            i = 12
            while i < n and q[i]:
                i += q[i] + 1
            i += 5
            if i > n:
                continue
            resp = (bytes(q[0:2]) + b"\x81\x80"
                    + b"\x00\x01\x00\x01\x00\x00\x00\x00"
                    + bytes(q[12:i]) + b"\xc0\x0c\x00\x01\x00\x01"
                    + b"\x00\x00\x00\x3c\x00\x04" + self.ip)
            try:
                self.sock.sendto(resp, addr)
            except OSError:
                pass


def run(config, ssid, save_path="/node_config.json", timeout_s=180):
    """Serve the setup portal. Reboots on save; returns after timeout."""
    if not _HAVE_HTTP:
        print("portal: adafruit_httpserver missing; skipping")
        return
    try:
        wifi.radio.start_ap(ssid=ssid)  # open network
    except (RuntimeError, ValueError, OSError, NotImplementedError) as exc:
        print("portal: AP failed:", exc)
        return
    ip = str(wifi.radio.ipv4_address_ap or "192.168.4.1")
    print("portal: connect to AP '%s' then browse http://%s/ (%ds timeout)"
          % (ssid, ip, timeout_s))
    pool = socketpool.SocketPool(wifi.radio)
    try:
        dns = _Dns(pool, ip)
    except OSError:
        dns = None
    server = Server(pool, debug=False)

    def form(request):
        return Response(request, _FORM % {
            "ssid": ssid,
            "name": config.get("name") or "",
            "interval_s": config.get("interval_s", 120),
            "pm_warmup_s": config.get("pm_warmup_s", 20),
            "metrics": ",".join(config.get("metrics") or []),
            "led": "checked" if config.get("led") else "",
        }, content_type="text/html")

    server.route("/", GET)(form)
    for p in _PROBES:
        server.route(p, GET)(
            lambda request, _u="http://%s/" % ip: Redirect(request, _u))

    @server.route("/save", POST)
    def save(request: Request):
        d = request.form_data
        config["name"] = (d.get("name") or "").strip() or config.get("name")
        try:
            config["interval_s"] = max(10, int(d.get("interval_s", 120)))
            config["pm_warmup_s"] = max(0, int(d.get("pm_warmup_s", 20)))
        except ValueError:
            pass
        metrics = [m.strip() for m in (d.get("metrics") or "").split(",")
                   if m.strip()]
        config["metrics"] = metrics or None
        config["led"] = "led" in d
        config["configured"] = True
        # CIRCUITPY is read-only to code while USB MSC is connected
        # (S2/S3): fall back to the CPSAVES partition, which stays
        # writable and is loaded with priority by code.py.
        saved = None
        for path in (save_path, "/saves/node_config.json"):
            try:
                with open(path, "w") as f:
                    json.dump(config, f)
                saved = path
                break
            except OSError as exc:
                print("portal: save to %s failed: %s" % (path, exc))
        return Response(
            request,
            ("saved to %s - rebooting into measurement mode" % saved)
            if saved else
            "could not write config (USB holds CIRCUITPY and no CPSAVES "
            "partition) - settings apply until power loss; eject/unplug "
            "USB or use a board with CPSAVES",
            content_type="text/plain")

    try:
        server.start("0.0.0.0", port=80)
    except OSError as exc:
        print("portal: http failed:", exc)
        return
    end = time.monotonic() + timeout_s
    saved_at = None
    while time.monotonic() < end:
        try:
            server.poll()
        except OSError:
            pass
        if dns:
            dns.poll()
        if config.get("configured") and saved_at is None:
            saved_at = time.monotonic()  # let the response flush, then reboot
            print("portal: config saved")
        if saved_at and time.monotonic() - saved_at > 2:
            print("portal: rebooting")
            microcontroller.reset()
        time.sleep(0.02)
    print("portal: timeout - continuing with current settings")
    try:
        wifi.radio.stop_ap()
    except (RuntimeError, OSError, AttributeError):
        pass
