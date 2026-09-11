# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
certstore - TLS certificate files for the hub's HTTPS portal.

Lookup order: /sd/certs (manual override / big SD card) then /certs on flash.
Renewal writes to flash only (the SD copy is the user's business).
The certificate is a public Let's Encrypt cert for a hostname that resolves to
192.168.4.1; it lasts ~90 days, so expiry is read from the PEM itself and,
when the hub has internet (STA WiFi) and a synced clock, fresh files are
downloaded from RENEW_URL_BASE/ssl.combined + ssl.key.
"""

import binascii
import os
import time

HOST = "192dot168dot4dot1.gundryconsultancy.com"
RENEW_URL_BASE = "https://www.gundryconsultancy.com/"
SEARCH = ("/sd/certs", "/certs")
CERT = "fullchain.pem"
KEY = "key.pem"
RENEW_BEFORE_DAYS = 14


def resolve():
    """Return (cert_path, key_path) of the first complete cert set, or None."""
    for root in SEARCH:
        try:
            os.stat(root + "/" + CERT)
            os.stat(root + "/" + KEY)
            return root + "/" + CERT, root + "/" + KEY
        except OSError:
            continue
    return None


# --- expiry straight from the leaf certificate --------------------------------

def _der_len(b, i):
    """ASN.1 length at b[i]; returns (length, index_of_content)."""
    n = b[i]
    if n < 0x80:
        return n, i + 1
    k = n & 0x7F
    v = 0
    for j in range(k):
        v = (v << 8) | b[i + 1 + j]
    return v, i + 1 + k


def _skip(b, i):
    """Index just past the TLV at b[i]."""
    n, c = _der_len(b, i + 1)
    return c + n


def _time_to_epoch(s):
    """UTCTime YYMMDDhhmmssZ or GeneralizedTime YYYYMMDDhhmmssZ -> epoch."""
    if len(s) == 13:
        yy = int(s[0:2])
        year = 1900 + yy if yy >= 50 else 2000 + yy
        s = "%04d" % year + s[2:]
    t = (int(s[0:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]), int(s[10:12]), int(s[12:14]), 0, 0, -1)
    return time.mktime(t)


def not_after(cert_path):
    """Epoch of the leaf certificate's notAfter, or None if unreadable."""
    try:
        with open(cert_path, "r") as f:
            pem = f.read()
        b64 = pem.split("-----BEGIN CERTIFICATE-----", 1)[1].split("-----END CERTIFICATE-----", 1)[0]
        der = binascii.a2b_base64("".join(b64.split()))
        # Certificate SEQ { tbsCertificate SEQ { [0] version?, serial, sigAlg, issuer, validity SEQ {notBefore, notAfter} ...
        i = _der_len(der, 1)[1]          # into Certificate
        i = _der_len(der, i + 1)[1]      # into tbsCertificate
        if der[i] == 0xA0:               # explicit version
            i = _skip(der, i)
        i = _skip(der, i)                # serialNumber
        i = _skip(der, i)                # signature algorithm
        i = _skip(der, i)                # issuer
        i = _der_len(der, i + 1)[1]      # into validity
        i = _skip(der, i)                # notBefore
        n, c = _der_len(der, i + 1)      # notAfter (0x17 UTCTime / 0x18 GeneralizedTime)
        return _time_to_epoch(der[c:c + n].decode())
    except (OSError, ValueError, IndexError) as exc:
        print("certstore: cannot read expiry:", exc)
        return None


def days_left(cert_path):
    """Days until expiry, or None when the clock is unsynced / cert unreadable."""
    exp = not_after(cert_path)
    now = time.time()
    if exp is None or now < 1700000000:
        return None
    return (exp - now) / 86400


# --- renewal ------------------------------------------------------------------

def _https_get(pool, url, sink):
    """Minimal HTTPS GET streaming the body into sink(bytes). Returns HTTP status."""
    import ssl
    host = url.split("://", 1)[1].split("/", 1)[0]
    path = "/" + url.split("://", 1)[1].split("/", 1)[1]
    ctx = ssl.create_default_context()
    sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect((host, 443))
    tls = ctx.wrap_socket(sock, server_hostname=host)
    tls.send(("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % (path, host)).encode())
    buf = bytearray(1024)
    head = b""
    status = 0
    body_started = False
    while True:
        n = tls.recv_into(buf)
        if not n:
            break
        chunk = bytes(buf[:n])
        if not body_started:
            head += chunk
            if b"\r\n\r\n" in head:
                hdr, _, rest = head.partition(b"\r\n\r\n")
                status = int(hdr.split(b" ", 2)[1])
                body_started = True
                if rest:
                    sink(rest)
        else:
            sink(chunk)
    tls.close()
    return status


def renew(pool, root="/certs"):
    """Download ssl.combined + ssl.key to `root` (flash). Keeps leaf+intermediate only.
    Returns True on success. Never raises."""
    try:
        try:
            os.mkdir(root)
        except OSError:
            pass
        parts = []
        st = _https_get(pool, RENEW_URL_BASE + "ssl.combined", parts.append)
        if st != 200:
            print("certstore: ssl.combined HTTP", st)
            return False
        combined = b"".join(parts).decode()
        certs = combined.split("-----END CERTIFICATE-----")
        chain = "".join(c + "-----END CERTIFICATE-----\n" for c in certs[:2] if "BEGIN CERTIFICATE" in c)
        parts = []
        st = _https_get(pool, RENEW_URL_BASE + "ssl.key", parts.append)
        if st != 200:
            print("certstore: ssl.key HTTP", st)
            return False
        key = b"".join(parts)
        if "BEGIN CERTIFICATE" not in chain or b"PRIVATE KEY" not in key:
            print("certstore: downloaded files look wrong")
            return False
        with open(root + "/" + CERT + ".new", "w") as f:
            f.write(chain)
        with open(root + "/" + KEY + ".new", "wb") as f:
            f.write(key)
        exp = not_after(root + "/" + CERT + ".new")
        if not exp or exp < time.time():
            print("certstore: downloaded cert not valid, keeping old")
            return False
        os.rename(root + "/" + CERT + ".new", root + "/" + CERT)
        os.rename(root + "/" + KEY + ".new", root + "/" + KEY)
        print("certstore: renewed, expires in %.0f days" % ((exp - time.time()) / 86400))
        return True
    except Exception as exc:  # renewal is best effort, never fatal
        print("certstore: renew failed:", type(exc).__name__, exc)
        return False


class Installer:
    """Receive a chain + key in pieces, writing each piece straight to the
    `.new` files rather than joining it in RAM.

    HTTP can hand `install()` both strings at once -- the request body is
    already buffered by then. BLE cannot: a Nordic-UART line is at most a few
    hundred bytes, so a ~5.5 KB certificate arrives as ~15 of them, and the
    hub has ~40 KB of heap free. Holding the chain, the key, the JSON they
    came in and the copies made along the way is what the C6 has least of.

    Pieces are written in the order they arrive; `finish()` applies the same
    validation and atomic rename as `install()`.
    """

    def __init__(self, root="/certs"):
        self.root = root
        self.n = 0                  # bytes written, for the client's progress
        self._files = {}

    def _open(self, which):
        f = self._files.get(which)
        if f is None:
            try:
                os.mkdir(self.root)
            except OSError:
                pass
            f = open("%s/%s.new" % (self.root,
                                    CERT if which == "cert" else KEY), "w")
            self._files[which] = f
        return f

    def write(self, which, text):
        """Append to the chain ('cert') or the key ('key'). Returns bytes so far."""
        if which not in ("cert", "key"):
            raise ValueError("expected cert or key, got %r" % (which,))
        self._open(which).write(text)
        self.n += len(text)
        return self.n

    def _close(self):
        for f in self._files.values():
            try:
                f.close()
            except OSError:
                pass
        self._files = {}

    def finish(self):
        """Validate what arrived and put it in place. True when installed."""
        self._close()
        try:
            exp = not_after(self.root + "/" + CERT + ".new")
            if exp is None or (time.time() > 1700000000 and exp < time.time()):
                return False
            with open(self.root + "/" + KEY + ".new") as f:
                if "PRIVATE KEY" not in f.read():
                    return False
            os.rename(self.root + "/" + CERT + ".new", self.root + "/" + CERT)
            os.rename(self.root + "/" + KEY + ".new", self.root + "/" + KEY)
            print("certstore: installed new certificate (%d bytes)" % self.n)
            return True
        except Exception as exc:
            print("certstore: install failed:", type(exc).__name__, exc)
            return False

    def abort(self):
        """Give up on a part-received certificate. The `.new` files are left
        where they are: nothing reads them, and the next upload overwrites."""
        self._close()


_rx = [None]


def status():
    """What certificate the hub has, in the shape the web app's cert row reads."""
    found = resolve()
    return {"host": HOST,
            "source": found[0] if found else None,
            "days_left": days_left(found[0]) if found else None}


def receive(op, payload=""):
    """One step of a certificate upload arriving over BLE.

    net_ble's `cert` command splits a ~5.5 KB certificate into short lines and
    calls this for each: 'begin', then 'c'/'k' pieces of the chain and the key,
    then 'end'. `payload` is PEM text whose newlines travel as '|' -- the
    command stream is newline-delimited, and '|' appears in neither base64 nor
    a PEM header, so nothing has to be escaped or re-encoded.

    Returns the JSON the portal sends back, errors included: a half-delivered
    certificate is a normal outcome here (the phone walked away), not an
    exception worth unwinding the main loop for.
    """
    rx = _rx[0]
    if op == "status":
        return status()
    if op == "begin":
        if rx is not None:
            rx.abort()
        _rx[0] = Installer()
        return {"ok": True}
    if op == "abort":
        if rx is not None:
            rx.abort()
            _rx[0] = None
        return {"ok": True}
    if rx is None:
        return {"err": "send `cert begin` first"}
    if op in ("c", "k"):
        try:
            return {"n": rx.write("cert" if op == "c" else "key",
                                  payload.replace("|", "\n"))}
        except OSError as exc:
            rx.abort()
            _rx[0] = None
            # much the most likely cause: a PC holds the CIRCUITPY drive, so
            # the filesystem is read-only to us (see code.py's h_storage)
            return {"err": "cannot write /certs (%s); take the filesystem "
                           "back from the PC first" % exc}
    if op == "end":
        ok = rx.finish()
        _rx[0] = None
        if not ok:
            return {"err": "certificate rejected (not a valid, unexpired "
                           "PEM chain + key)"}
        st = status()
        st["note"] = "installed to /certs; restart the hub to use it"
        return st
    return {"err": "unknown cert step %r" % (op,)}


def install(chain, key, root="/certs"):
    """Install a PEM chain (leaf+intermediate) + key delivered by the web app / BLE.
    Validated (parseable, not expired when the clock is synced), written atomically."""
    try:
        if "BEGIN CERTIFICATE" not in chain or "PRIVATE KEY" not in key:
            return False
        rx = Installer(root)
        rx.write("cert", chain)
        rx.write("key", key)
        return rx.finish()
    except Exception as exc:
        print("certstore: install failed:", type(exc).__name__, exc)
        return False


def maybe_renew(pool):
    """Renew when no cert set exists or the current one expires within RENEW_BEFORE_DAYS
    (requires a synced clock). Returns True if a renewal happened."""
    found = resolve()
    if found:
        d = days_left(found[0])
        if d is None or d > RENEW_BEFORE_DAYS:
            return False
        print("certstore: %.0f days left, renewing" % d)
    return renew(pool)
