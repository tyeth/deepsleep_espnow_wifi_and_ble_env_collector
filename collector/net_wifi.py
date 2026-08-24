# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
net_wifi - WiFi bring-up, NTP time sync, and the HTTP portal/REST API.

Routes (all JSON unless noted):
  GET  /                    tiny dashboard page (HTML, fetches the API)
  GET  /api/latest          latest values for every source + alert states
  GET  /api/battery         host + node battery concerns
  GET  /api/events          active out-of-spec + tail of events.csv
  GET  /api/history         ?day=YYYY-MM-DD -> that day's CSV from SD
  GET  /api/config          effective config
  POST /api/config          JSON body merged into config, saved to /sd/config.json
  POST /api/calibrate       {"src": "local"|node, "step": 1|2} two-step FRC
  POST /api/ingest          node data over WiFi (fallback transport for nodes)

The command handlers themselves live in code.py (shared with BLE); this
module just wires HTTP to them.
"""

import json

import wifi

try:
    import socketpool
    from adafruit_httpserver import (
        GET,
        POST,
        FileResponse,
        JSONResponse,
        Redirect,
        Request,
        Response,
        Server,
    )
    _HAVE_HTTP = True
except ImportError:
    _HAVE_HTTP = False

# OS captive-portal connectivity probes: answering these with a redirect to
# the portal makes phones/laptops pop the page when they join our AP.
_CAPTIVE_PROBES = (
    "/generate_204",              # Android
    "/gen_204",                   # Android
    "/hotspot-detect.html",       # Apple
    "/library/test/success.html", # Apple
    "/connecttest.txt",           # Windows
    "/ncsi.txt",                  # Windows
    "/redirect",                  # Windows
    "/canonical.html",            # Firefox
    "/success.txt",               # Firefox
)

_PAGE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Env Hub</title>
<style>body{font-family:system-ui;margin:1em;background:#fafafa}
h1{font-size:1.2em}table{border-collapse:collapse;width:100%}
td,th{padding:.3em .5em;border-bottom:1px solid #ddd;text-align:left}
.warn{background:#ffe680}.bad{background:#ff9a8a}
.banner{padding:.5em;border-radius:6px;margin:.5em 0;font-weight:600}
.banner.warn{background:#ffe680}.banner.bad{background:#ff9a8a}
small{color:#666}</style>
<h1>Env Hub</h1><div id=b></div><div id=t>loading...</div>
<p><small>auto-refresh 30s &middot; <a href=/api/latest>latest</a> &middot;
<a href=/api/events>events</a> &middot; <a href=/api/battery>battery</a> &middot;
<a href=/api/config>config</a></small></p>
<script>
async function load(){
 try{
  const d=await (await fetch('/api/latest')).json();
  const bt=await (await fetch('/api/battery')).json();
  let bh='';
  if(bt.host&&bt.host.unplugged)bh+=`<div class="banner ${bt.host.crit?'bad':'warn'}">Hub on battery ${bt.host.v??''}V</div>`;
  for(const n of bt.nodes||[])bh+=`<div class="banner ${n.crit?'bad':'warn'}">${n.src} battery low ${n.v}V</div>`;
  for(const a of d.abnormal||[])bh+=`<div class="banner ${a.state}">${a.src} ${a.metric} ${a.state} for ${a.for}</div>`;
  document.getElementById('b').innerHTML=bh;
  let h='<table><tr><th>zone</th><th>CO2</th><th>PM2.5</th><th>T</th><th>RH</th><th>VOC</th><th>NOx</th><th>batt</th><th>age</th></tr>';
  for(const[s,e]of Object.entries(d.sources)){
   const m=e.m||{},st=e.states||{};
   const c=k=>st[k]==2?' class=bad':st[k]==1?' class=warn':'';
   const f=(k,d=1)=>m[k]==null?'--':(+m[k]).toFixed(d);
   h+=`<tr><td>${e.zone||s}</td><td${c('co2')}>${f('co2',0)}</td><td${c('pm25')}>${f('pm25')}</td><td${c('tc')}>${f('tc')}</td><td${c('rh')}>${f('rh')}</td><td${c('voc')}>${f('voc',0)}</td><td${c('nox')}>${f('nox',0)}</td><td>${e.vb??'--'}</td><td>${e.age??''}</td></tr>`;
  }
  document.getElementById('t').innerHTML=h+'</table>';
 }catch(e){document.getElementById('t').textContent='fetch failed: '+e;}
}
load();setInterval(load,30000);
</script>"""


def connect(ssid, password, tz_offset_h=0):
    """Connect WiFi + best-effort NTP sync. Returns ip string or None."""
    try:
        wifi.radio.connect(ssid, password, timeout=15)
    except (ConnectionError, ValueError, OSError) as exc:
        print("WiFi connect failed:", exc)
        return None
    ip = str(wifi.radio.ipv4_address)
    print("WiFi up:", ip, "channel", wifi.radio.ap_info.channel
          if wifi.radio.ap_info else "?")
    try:
        import rtc
        import adafruit_ntp
        pool = socketpool.SocketPool(wifi.radio)
        ntp = adafruit_ntp.NTP(pool, tz_offset=tz_offset_h, cache_seconds=3600)
        rtc.RTC().datetime = ntp.datetime
        print("NTP synced")
    except Exception as exc:  # NTP failure must never kill startup
        print("NTP failed:", exc)
    return ip


def _find_app_root():
    """The full analysis web app is deployed to /sd/www (preferred, big
    vendor files fit there) or /www on flash; fall back to the tiny
    embedded dashboard when neither exists."""
    import os
    for root in ("/sd/www", "/www"):
        try:
            os.stat(root + "/index.html")
            return root
        except OSError:
            pass
    return None


class WebPortal:
    """HTTP server wrapper. handlers: dict of callables shared with BLE."""

    def __init__(self, handlers, portal_host=None):
        self.handlers = handlers
        self.server = None
        self.ok = False
        self.portal_host = portal_host  # AP IP for captive redirects
        self.app_root = None

    def start(self, ap_active=False):
        if not _HAVE_HTTP or not (wifi.radio.connected or ap_active):
            return False
        pool = socketpool.SocketPool(wifi.radio)
        server = Server(pool, debug=False)
        h = self.handlers
        self.app_root = _find_app_root()
        app_root = self.app_root
        portal_url = "http://%s/" % (self.portal_host or "192.168.4.1")

        @server.route("/", GET)
        def index(request: Request):
            if app_root:
                return FileResponse(request, "index.html", root_path=app_root)
            return Response(request, _PAGE, content_type="text/html")

        @server.route("/sw.js", GET)
        def sw(request: Request):
            if app_root:
                return FileResponse(request, "sw.js", root_path=app_root)
            return Response(request, "// no app deployed",
                            content_type="text/javascript")

        @server.route("/mini", GET)
        def mini(request: Request):
            return Response(request, _PAGE, content_type="text/html")

        def captive(request: Request):
            return Redirect(request, portal_url)

        for probe in _CAPTIVE_PROBES:
            server.route(probe, GET)(captive)

        @server.route("/api/latest", GET)
        def latest(request: Request):
            return JSONResponse(request, h["latest"]())

        @server.route("/api/battery", GET)
        def batt(request: Request):
            return JSONResponse(request, h["battery"]())

        @server.route("/api/events", GET)
        def events(request: Request):
            return JSONResponse(request, h["events"]())

        @server.route("/api/config", GET)
        def config_get(request: Request):
            return JSONResponse(request, h["config_get"]())

        @server.route("/api/config", POST)
        def config_post(request: Request):
            try:
                body = json.loads(request.body)
            except ValueError:
                return JSONResponse(request, {"err": "bad json"})
            return JSONResponse(request, h["config_set"](body))

        @server.route("/api/calibrate", POST)
        def calibrate(request: Request):
            try:
                body = json.loads(request.body)
            except ValueError:
                return JSONResponse(request, {"err": "bad json"})
            return JSONResponse(
                request,
                h["calibrate"](body.get("src", "local"), int(body.get("step", 1))),
            )

        @server.route("/api/ingest", POST)
        def ingest(request: Request):
            return JSONResponse(request, h["ingest"](request.body))

        @server.route("/api/history", GET)
        def history(request: Request):
            day = request.query_params.get("day")
            days = h["list_days"]()
            if not day:
                return JSONResponse(request, {"days": days})
            if day not in days:
                return JSONResponse(request, {"err": "no such day", "days": days})
            return FileResponse(request, "%s.csv" % day,
                                root_path=h["data_dir"](),
                                content_type="text/csv")

        try:
            # 0.0.0.0 serves both the STA (home WiFi) and AP interfaces
            server.start("0.0.0.0", port=80)
        except OSError as exc:
            print("HTTP server start failed:", exc)
            return False
        self.server = server
        self.ok = True
        return True

    def poll(self):
        if self.server:
            try:
                self.server.poll()
            except OSError as exc:
                print("HTTP poll error:", exc)
