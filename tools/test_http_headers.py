#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host-side checks for the hub's static-file responses (no hardware).

    python tools/test_http_headers.py

The AP has no internet, so every browser that forgets the page pulls the
whole ~1.1 MB Plotly bundle from flash again. These checks cover the three
things that make that survivable -- an ETag so a reload costs a 304, Range
support so an interrupted transfer resumes, and cache headers that mark the
vendor bundles immutable while live data stays uncacheable.

`net_wifi` is CircuitPython code, so `wifi`, `socketpool`, `ssl` and
`certstore` are stubbed to import it here; only header construction is
exercised, not the socket loop.
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.join(HERE, "..", "collector")

for name in ("wifi", "socketpool", "ssl", "certstore", "adafruit_ntp"):
    mod = types.ModuleType(name)
    if name == "wifi":
        mod.radio = types.SimpleNamespace(connected=False, ipv4_address=None)
    if name == "certstore":
        mod.HOST = "test.invalid"
        mod.load = lambda *a, **k: None
        mod.paths = lambda *a, **k: (None, None)
    sys.modules.setdefault(name, mod)

sys.path.insert(0, COLLECTOR)
import net_wifi  # noqa: E402

FAILURES = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILURES.append(name)


class FakeConn:
    def __init__(self):
        self.file = None
        self.left = None


def head_for(portal, path, **kw):
    c = FakeConn()
    raw = portal._file_head(c, path, kw.pop("ka", True), **kw)
    if c.file:
        c.file.close()
    text = raw.decode("utf-8", "replace")
    status = int(text.split(" ", 2)[1])
    headers = {}
    for line in text.split("\r\n")[1:]:
        if ": " in line:
            k, _, v = line.partition(": ")
            headers[k.lower()] = v
    return status, headers, c


def main():
    portal = net_wifi.WebPortal.__new__(net_wifi.WebPortal)  # no sockets

    # forward slashes and a real "vendor" directory: the immutable rule
    # keys off "/vendor/" in the path, exactly as it does on the board
    tmp = HERE.replace("\\", "/") + "/_httptest/vendor"
    os.makedirs(tmp, exist_ok=True)
    big = tmp + "/plotly.min.js"
    with open(big, "wb") as f:
        f.write(b"x" * 5000)

    print("a normal GET of a vendor bundle")
    status, h, c = head_for(portal, big)
    etag = h.get("etag")
    check("200", status == 200)
    check("has an ETag", bool(etag))
    check("full length", h.get("content-length") == "5000")
    check("streams the whole file", c.left == 5000)
    check("advertises byte ranges", h.get("accept-ranges") == "bytes")
    check("vendor bundles are immutable",
          "immutable" in h.get("cache-control", ""))
    check("javascript content type",
          h.get("content-type") == "text/javascript")

    print("the browser comes back with that ETag")
    status, h, c = head_for(portal, big, inm=etag.encode())
    check("304 Not Modified", status == 304)
    check("no body", h.get("content-length") == "0")
    check("nothing to stream", c.file is None)

    print("a stale ETag still gets the file")
    status, h, c = head_for(portal, big, inm=b'"deadbeef-1"')
    check("200", status == 200)
    check("full length", c.left == 5000)

    print("resuming an interrupted transfer")
    status, h, c = head_for(portal, big, rng=b"bytes=1000-")
    check("206 Partial Content", status == 206)
    check("sends only the remainder", c.left == 4000)
    check("content-range names the whole file",
          h.get("content-range") == "bytes 1000-4999/5000")
    status, h, c = head_for(portal, big, rng=b"bytes=0-99")
    check("a bounded range is honoured", c.left == 100 and status == 206)
    status, h, c = head_for(portal, big, rng=b"bytes=-100")
    check("a suffix range is honoured", c.left == 100 and status == 206)

    print("a nonsense range is rejected, not guessed at")
    status, h, c = head_for(portal, big, rng=b"bytes=9000-9999")
    check("416", status == 416)
    check("says how big the file is",
          h.get("content-range") == "bytes */5000")

    print("a gzip twin is preferred when the browser accepts it")
    with open(big + ".gz", "wb") as f:
        f.write(b"z" * 1700)
    status, h, c = head_for(portal, big, gz_ok=True)
    check("serves the .gz", h.get("content-encoding") == "gzip")
    check("its own length", h.get("content-length") == "1700")
    check("still javascript", h.get("content-type") == "text/javascript")
    check("varies on Accept-Encoding",
          h.get("vary") == "Accept-Encoding")
    gz_etag = h.get("etag")
    status, h, _ = head_for(portal, big, gz_ok=False)
    check("a client without gzip gets the plain file",
          h.get("content-encoding") is None
          and h.get("content-length") == "5000")
    check("the two have different ETags", gz_etag != h.get("etag"))
    os.remove(big + ".gz")

    print("a file outside vendor/ revalidates instead of being immutable")
    plain = HERE.replace("\\", "/") + "/_httptest/index.html"
    with open(plain, "wb") as f:
        f.write(b"<!doctype html>")
    status, h, _ = head_for(portal, plain)
    check("max-age but not immutable",
          "max-age" in h.get("cache-control", "")
          and "immutable" not in h.get("cache-control", ""))

    print("a missing file")
    status, h, c = head_for(portal, tmp + "/nope.js")
    check("404", status == 404)

    print("keep-alive is honoured")
    status, h, _ = head_for(portal, big, ka=True)
    check("Connection: keep-alive", h.get("connection") == "keep-alive")
    status, h, _ = head_for(portal, big, ka=False)
    check("Connection: close when asked", h.get("connection") == "close")

    for f in (big, plain):
        os.remove(f)
    os.rmdir(tmp)
    os.rmdir(HERE.replace("\\", "/") + "/_httptest")

    print()
    if FAILURES:
        print("%d FAILED: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
