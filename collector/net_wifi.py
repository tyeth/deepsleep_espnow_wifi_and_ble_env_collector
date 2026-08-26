# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
net_wifi - WiFi bring-up, NTP time sync, and the HTTP portal/REST API.

Routes (all JSON unless noted):
  GET  /                    the analyzer app from /sd/www or /www if deployed,
                            else a tiny landing page linking to the hosted app
  GET  /api/latest          latest values for every source + alert states
  GET  /api/battery         host + node battery concerns
  GET  /api/events          active out-of-spec + tail of events.csv
  GET  /api/history         ?day=YYYY-MM-DD -> that day's CSV from SD
  GET  /api/config          effective config
  POST /api/config          JSON body merged into config, saved to /sd/config.json
  GET  /api/calibrate       pending/scheduled calibrations + last results
  POST /api/calibrate       {"src","step":1|2,"when":"4am"|"now"|epoch,
                             "duration_s","target_ppm","dry",
                             "mode":"frc"|"asc"} reference cal
  POST /api/ingest          node data over WiFi (fallback transport for nodes)
  POST /api/time            {"epoch": ...} browser clock sync

The command handlers themselves live in code.py (shared with BLE); this
module wires HTTP to them with a deliberately small non-blocking server on
socketpool: adafruit_httpserver cost ~46 KB of heap on the C6, which is the
difference between the wifi driver having TX buffers or not. Phones open
several connections per page (some speculative, never used), so every
connection is progressed a little on each poll() and nothing ever blocks the
main loop.
"""

import json
import time

import wifi

try:
    import socketpool
    _HAVE_HTTP = True
except ImportError:
    _HAVE_HTTP = False

# Hosted analyzer (HTTPS, web-BLE). Browsers block plain-http API calls from
# it, so on the AP the app is served from /www when present; this is the
# fallback landing page.
APP_URL = "https://tyeth.github.io/espnow_wifi_and_ble_env_collector/"

# HTTPS on the AP: a public Let's Encrypt certificate for a hostname that resolves
# to 192.168.4.1 (the captive DNS answers every name with the AP address). With it
# the hub-served app is a secure context (built-in AI, web-BLE, service worker)
# and no mixed-content problem exists. Files live on flash so they can be renewed
# (cert lasts ~90 days; sidecar cert_meta.json holds not_after for the check).
import certstore

TLS_HOST = certstore.HOST

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

_TYPES = {
    "html": "text/html", "js": "text/javascript", "css": "text/css",
    "json": "application/json", "svg": "image/svg+xml", "csv": "text/csv",
    "png": "image/png", "txt": "text/plain",
}
_MAX_BODY = 8192   # POST /api/cert carries a PEM chain + key (~5.5 KB)
_IDLE_S = 8          # drop a plain connection that goes quiet this long
_TLS_IDLE_NOREQ_S = 10    # TLS session with no request yet: the handshake itself spans ~2-3 s of polls on the C6
_TLS_KEEPALIVE_S = 15     # TLS session that has served a request: keep for follow-ups (one handshake)
_POLL_BUDGET_MS = 150  # max time spent in one poll()
_MAX_CONNS = 6
_TLS_MIN_FREE = 20 * 1024   # total free IDF heap needed before starting a TLS session
_TLS_WRAP_GIVEUP_S = 4      # how long to keep retrying wrap_socket on MemoryError
_EAGAIN = 11
HTTP_DEBUG = True  # print one line per request (path, bytes, ms) -- bring-up aid


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
    vendor files fit there) or /www on flash; fall back to the landing page
    when neither exists."""
    import os
    for root in ("/sd/www", "/www"):
        try:
            os.stat(root + "/index.html")
            return root
        except OSError:
            pass
    return None


def _idf_free():
    try:
        import espidf
        return espidf.heap_caps_get_free_size()
    except ImportError:
        return 1 << 30


def _static(path):
    """Static app files: the SD card copy wins (big vendor bundles, manual updates),
    then user flash. Returns the first existing path, else the flash path (-> 404)."""
    import os
    for root in ("/sd/www", "/www"):
        try:
            os.stat(root + path)
            return root + path
        except OSError:
            continue
    return "/www" + path


def _json(obj):
    return 200, "application/json", json.dumps(obj).encode()


def _parse_json(body):
    try:
        return json.loads(body)
    except ValueError:
        return None


class _Conn:
    """One client connection progressed incrementally by WebPortal.poll()."""
    __slots__ = ("sock", "req", "out", "file", "t", "done", "t0", "path", "sent", "tls", "keep")

    def __init__(self, sock):
        self.sock = sock
        self.req = b""      # request bytes received so far
        self.out = None     # pending response bytes (memoryview) or None
        self.file = None    # open file being streamed after `out`
        self.t = time.monotonic()
        self.t0 = self.t
        self.path = None
        self.sent = 0
        self.tls = False
        self.keep = False   # HTTP keep-alive: serve further requests on this TLS connection
        self.done = False


class WebPortal:
    """HTTP server wrapper. handlers: dict of callables shared with BLE."""

    def __init__(self, handlers, portal_host=None, port=80):
        self.handlers = handlers
        self.server = None
        self.ok = False
        self.portal_host = portal_host  # AP IP for captive redirects
        self.port = port
        self.app_root = None
        self.tls = None
        self.tls_ctx = None
        self.tls_expiry = None
        self._buf = bytearray(1024)
        self._fbuf = bytearray(4096)  # file streaming chunk
        self._conns = []
        self._tls_pending = []   # accepted :443 sockets awaiting wrap_socket

    # -- routing ------------------------------------------------------------

    def _route(self, method, path, query, body):
        h = self.handlers
        if path == "/" or path == "/index.html" or path == "/sw.js":
            if self.app_root:
                return ("file", _static("/index.html" if path != "/sw.js" else "/sw.js"))
            if path == "/sw.js":
                return 200, "text/javascript", b"// no app deployed"
            return 200, "text/html", (
                b"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                b"<title>ENVHUB</title><h1>ENVHUB</h1><p>Data API: <a href=/api/latest>/api/latest</a></p>"
                b"<p>Analyzer app: <a href='" + APP_URL.encode() + b"'>" + APP_URL.encode() + b"</a></p>")
        if path in _CAPTIVE_PROBES:
            return 302, self._portal_url(), b""
        if method == "GET":
            if path == "/api/latest":
                return _json(h["latest"]())
            if path == "/api/battery":
                return _json(h["battery"]())
            if path == "/api/events":
                return _json(h["events"]())
            if path == "/api/config":
                return _json(h["config_get"]())
            if path == "/api/calibrate":
                return _json(h["cal_status"]())
            if path == "/api/cert":
                return _json(self.cert_status())
            if path == "/api/history":
                day = query.get("day")
                days = h["list_days"]()
                if not day:
                    return _json({"days": days})
                if day not in days:
                    return _json({"err": "no such day", "days": days})
                return ("file", "%s/%s.csv" % (h["data_dir"](), day))
            if self.app_root and "/.." not in path:
                return ("file", _static(path))
        elif method == "POST":
            if path == "/api/ingest":
                return _json(h["ingest"](body))
            data = _parse_json(body)
            if data is None:
                return _json({"err": "bad json"})
            if path == "/api/config":
                return _json(h["config_set"](data))
            if path == "/api/cert":
                return _json(self.install_cert(data.get("cert", ""), data.get("key", "")))
            if path == "/api/time":
                return _json(h["time_set"](data.get("epoch")))
            if path == "/api/calibrate":
                try:
                    step = int(data.get("step", 1))
                except (TypeError, ValueError):
                    return _json({"err": "bad step"})
                return _json(h["calibrate"](data.get("src", "local"), step, data))
        return 404, "text/plain", b"not found"

    def _portal_url(self):
        # Captive-portal probes land on the plain-http page: first paint + data in
        # <1 s. HTTPS (needed for the built-in AI / web-BLE) is one click away in the
        # page header -- an RSA-2048 handshake costs the C6 ~1.3 s of CPU each, so it
        # must not sit on the critical path for every phone that joins.
        return "http://%s%s/" % (self.portal_host or "192.168.4.1",
                                 "" if self.port == 80 else ":%d" % self.port)

    def secure_url(self):
        return ("https://%s/" % TLS_HOST) if self.tls else None

    def _start_tls(self, pool):
        """Listen on :443 with the flash-resident certificate. Returns the wrapped listener or None."""
        found = certstore.resolve()   # /sd/certs first, then /certs on flash
        if not found:
            print("HTTPS: no certificate in /sd/certs or /certs, http only")
            return None
        cert_path, key_path = found
        import gc
        import ssl
        tls = None
        for attempt in (1, 2):
            # mbedTLS/PSA key import wants a sizeable contiguous block: collect first,
            # and retry once -- the failure mode is a bare GENERIC_ERROR when starved
            gc.collect()
            try:
                ctx = ssl.SSLContext()
                # SSLContext() attaches the CA bundle, which as a *server* makes mbedTLS demand
                # a client certificate; clearing the CA store gives VERIFY_NONE.
                ctx.load_verify_locations(cadata="")
                ctx.load_cert_chain(cert_path, key_path)
                raw = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
                raw.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
                raw.bind(("0.0.0.0", 443))
                raw.listen(2)
                raw.setblocking(False)
                # Do NOT wrap the listener: a wrapped listener keeps a full mbedTLS context
                # (record buffers) resident and starved the wifi driver (DHCP ACKs failed).
                # Each accepted socket is wrapped on demand instead; the handshake then runs
                # incrementally inside the non-blocking state machine (first recv).
                self.tls_ctx = ctx
                tls = raw
                break
            except (OSError, ValueError, MemoryError, RuntimeError) as exc:
                try:
                    import espidf
                    heap = "idf_free=%d largest=%d" % (espidf.heap_caps_get_free_size(),
                                                       espidf.heap_caps_get_largest_free_block())
                except ImportError:
                    heap = ""
                print("HTTPS start failed (try %d): %s %s" % (attempt, exc, heap))
                try:
                    raw.close()
                except Exception:
                    pass
                time.sleep(0.5)
        if tls is None:
            return None
        self.tls_expiry = certstore.not_after(cert_path)
        print("HTTPS portal on port 443 as %s (cert from %s)" % (TLS_HOST, cert_path))
        self.check_cert()
        return tls

    def cert_status(self):
        found = certstore.resolve()
        return {"host": TLS_HOST, "https": bool(self.tls), "secure_url": self.secure_url(),
                "source": found[0] if found else None,
                "days_left": certstore.days_left(found[0]) if found else None}

    def install_cert(self, cert, key):
        """Write a new chain + key to flash (/certs), validated, atomic. Takes effect on next boot."""
        ok = certstore.install(cert, key)
        if not ok:
            return {"err": "certificate rejected (not a valid, unexpired PEM chain + key)"}
        st = self.cert_status()
        st["note"] = "installed to /certs; restart the hub to use it"
        return st

    def check_cert(self):
        """Warn when the clock is synced and the certificate is (nearly) expired.
        Returns days left, or None when unknown."""
        if not self.tls_expiry:
            return None
        now = time.time()
        if now < 1700000000:  # clock not synced yet (no RTC battery)
            return None
        days = (self.tls_expiry - now) / 86400
        if days < 0:
            print("HTTPS: certificate EXPIRED %.0f days ago -- renew /certs (%s)" % (-days, TLS_HOST))
        elif days < 14:
            print("HTTPS: certificate expires in %.0f days -- renew /certs soon" % days)
        return days

    # -- server -------------------------------------------------------------

    def start(self, ap_active=False):
        if not _HAVE_HTTP or not (wifi.radio.connected or ap_active):
            return False
        self.app_root = _find_app_root()
        pool = socketpool.SocketPool(wifi.radio)
        try:
            s = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
            s.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
            # 0.0.0.0 serves both the STA (home WiFi) and AP interfaces
            s.bind(("0.0.0.0", self.port))
            s.listen(4)
            s.setblocking(False)
            print("HTTP portal on port", self.port)
        except OSError as exc:
            print("HTTP server start failed:", exc)
            return False
        self.server = s
        self.tls = self._start_tls(pool)
        self.ok = True
        return True

    def poll(self):
        if not self.server:
            return
        # accept everything pending (non-blocking)
        while len(self._conns) < _MAX_CONNS:
            try:
                sock, _addr = self.server.accept()
            except OSError:
                break
            sock.setblocking(False)
            self._conns.append(_Conn(sock))
        # https: accept() performs the TLS handshake (blocking, ~1 s); the served
        # connection then joins the same non-blocking state machine
        # Only start a TLS session when there is IDF headroom for its ~16 KB of
        # buffers (allocated as several small pieces) and no other session is open; otherwise leave the connection in the
        # listen backlog -- the browser waits and retries instead of seeing a reset.
        # Strictly one TLS session at a time: a handshake blocks the loop ~1.3 s (RSA)
        # and would stall any transfer already in flight on another session.
        # (Delaying accepts -- spacing handshakes or waiting for http to go idle -- made
        # Chrome abandon connections before their handshake finished; accept promptly.)
        if self.tls and not any(c.tls for c in self._conns) and not self._tls_pending                 and _idf_free() > _TLS_MIN_FREE:
            try:
                sock, _addr = self.tls.accept()
                self._tls_pending.append((sock, time.monotonic()))
            except OSError:
                pass  # nothing pending
        # Wrap parked TLS sockets: wrap_socket needs a few KB of contiguous Python heap
        # and can fail transiently -- retry over a few polls rather than closing the
        # connection (a close shows up in the browser as "connection reset").
        if self._tls_pending and not any(c.tls for c in self._conns):
            sock, t0 = self._tls_pending[0]
            import gc
            gc.collect()
            try:
                tls_sock = self.tls_ctx.wrap_socket(sock, server_side=True)
                tls_sock.setblocking(False)
                c = _Conn(tls_sock)
                c.tls = True
                self._conns.append(c)
                self._tls_pending.pop(0)
            except MemoryError:
                if time.monotonic() - t0 > _TLS_WRAP_GIVEUP_S:
                    print("HTTPS: no heap for a TLS session after %.0fs, dropping" % _TLS_WRAP_GIVEUP_S)
                    sock.close()
                    self._tls_pending.pop(0)
            except OSError as exc:
                print("HTTPS: cannot start TLS session:", exc)
                sock.close()
                self._tls_pending.pop(0)
        if not self._conns:
            return
        deadline = time.monotonic() + _POLL_BUDGET_MS / 1000
        now = time.monotonic()
        for c in self._conns:
            try:
                self._step(c, deadline)
            except OSError as exc:
                if exc.errno != _EAGAIN:
                    c.done = True
                    if exc.errno not in (104, 128, 32):  # reset / not connected / pipe: normal client hang-ups
                        print("HTTP conn error:", exc)
            except Exception as exc:  # a handler bug must not kill the server
                print("HTTP handler error:", type(exc).__name__, exc)
                c.done = True
            if not c.done:
                limit = _IDLE_S
                if c.tls:
                    limit = _TLS_KEEPALIVE_S if c.keep else _TLS_IDLE_NOREQ_S
                if now - c.t > limit:
                    c.done = True
            if time.monotonic() > deadline:
                break
        # close finished connections
        keep = []
        for c in self._conns:
            if c.done:
                if c.file:
                    c.file.close()
                c.sock.close()
                if HTTP_DEBUG:
                    print("%s %s %d B %d ms%s" % ("HTTPS" if c.tls else "HTTP", c.path, c.sent, int((time.monotonic() - c.t0) * 1000),
                                                    "" if c.out is None else " (incomplete)"))
            else:
                keep.append(c)
        self._conns = keep

    def _step(self, c, deadline):
        buf = self._buf
        if c.out is None:
            # ---- receive phase (non-blocking; EAGAIN propagates = nothing yet)
            n = c.sock.recv_into(buf)
            if n == 0:
                c.done = True  # peer closed without a request
                return
            c.t = time.monotonic()
            c.req += bytes(buf[:n])
            if b"\r\n\r\n" not in c.req:
                if len(c.req) > _MAX_BODY:
                    c.done = True
                return
            header, _, body = c.req.partition(b"\r\n\r\n")
            length = 0
            conn_hdr = b""
            for ln in header.split(b"\r\n")[1:]:
                low = ln[:15].lower()
                if low == b"content-length:":
                    length = int(ln[15:].strip())
                elif low[:11] == b"connection:":
                    conn_hdr = ln[11:].strip().lower()
            if len(body) < min(length, _MAX_BODY):
                return  # body still arriving
            try:
                method, target, _ver = header.split(b"\r\n")[0].decode().split(" ", 2)
            except ValueError:
                c.out = memoryview(self._head(400, "text/plain", 11) + b"bad request")
                return
            path, _, qs = target.partition("?")
            query = {}
            for kv in qs.split("&"):
                if kv:
                    k, _, v = kv.partition("=")
                    query[k] = v
            resp = self._route(method, path, query, body)
            c.req = b""
            c.path = path
            # keep TLS connections open for the follow-up requests (html -> icon -> api)
            # so they reuse one ~1.3 s RSA handshake; plain http stays one-shot
            c.keep = c.tls and conn_hdr != b"close"
            ka = c.keep
            if resp[0] == "file":
                import os
                try:
                    size = os.stat(resp[1])[6]
                    c.file = open(resp[1], "rb")
                    ext = resp[1].rsplit(".", 1)[-1]
                    c.out = memoryview(self._head(200, _TYPES.get(ext, "application/octet-stream"), size, keep=ka))
                except OSError:
                    c.out = memoryview(self._head(404, "text/plain", 9, keep=ka) + b"not found")
            elif resp[0] == 302:  # resp[1] carries the Location
                c.out = memoryview(self._head(302, "text/html", 0, b"Location: %s\r\n" % resp[1].encode(), keep=ka))
            else:
                c.out = memoryview(self._head(resp[0], resp[1], len(resp[2]), keep=ka) + resp[2])
        # ---- send phase: push as much as the socket takes within the budget
        while time.monotonic() < deadline:
            if len(c.out) == 0:
                if c.file is None:
                    self._finish(c)
                    return
                fb = self._fbuf
                n = c.file.readinto(fb)
                if not n:
                    c.file.close()
                    c.file = None
                    self._finish(c)
                    return
                c.out = memoryview(bytes(fb[:n]))
            try:
                sent = c.sock.send(c.out)  # raises EAGAIN when the TX window is full
            except OSError as exc:
                if exc.errno != _EAGAIN:
                    raise
                # window full: the peer ACKs within milliseconds -- wait a little inside
                # this poll's budget instead of giving up the slot until the next poll
                time.sleep(0.005)
                continue
            if not sent:
                return
            c.t = time.monotonic()
            c.sent += sent
            c.out = c.out[sent:]

    def _finish(self, c):
        """Response fully sent: close, or (keep-alive) log it and await the next request."""
        c.out = None
        if c.keep:
            if HTTP_DEBUG:
                print("%s %s %d B %d ms (keep-alive)" % ("HTTPS" if c.tls else "HTTP", c.path, c.sent,
                                                          int((time.monotonic() - c.t0) * 1000)))
            c.path = None
            c.sent = 0
            c.t0 = c.t = time.monotonic()
        else:
            c.done = True

    @staticmethod
    def _head(status, ctype, length, extra=b"", keep=False):
        reason = {200: "OK", 302: "Found", 400: "Bad Request", 404: "Not Found"}.get(status, "OK")
        return (b"HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                b"Access-Control-Allow-Origin: *\r\nConnection: %s\r\n%s\r\n"
                % (status, reason, ctype, length, b"keep-alive" if keep else b"close", extra))
