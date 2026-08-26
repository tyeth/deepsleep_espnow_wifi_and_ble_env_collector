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


def install(chain, key, root="/certs"):
    """Install a PEM chain (leaf+intermediate) + key delivered by the web app / BLE.
    Validated (parseable, not expired when the clock is synced), written atomically."""
    try:
        if "BEGIN CERTIFICATE" not in chain or "PRIVATE KEY" not in key:
            return False
        try:
            os.mkdir(root)
        except OSError:
            pass
        with open(root + "/" + CERT + ".new", "w") as f:
            f.write(chain)
        with open(root + "/" + KEY + ".new", "w") as f:
            f.write(key)
        exp = not_after(root + "/" + CERT + ".new")
        if exp is None or (time.time() > 1700000000 and exp < time.time()):
            return False
        os.rename(root + "/" + CERT + ".new", root + "/" + CERT)
        os.rename(root + "/" + KEY + ".new", root + "/" + KEY)
        print("certstore: installed new certificate")
        return True
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
