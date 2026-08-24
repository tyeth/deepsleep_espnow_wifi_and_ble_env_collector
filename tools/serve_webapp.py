#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
serve_webapp.py - serve webapp/ over HTTPS with a self-signed certificate,
so browser features gated on secure contexts (service worker, web-BLE,
Chrome built-in AI / Prompt API) all work during local development.

Usage:
  python tools/serve_webapp.py                 # https://localhost:8443
  python tools/serve_webapp.py --port 9443
  python tools/serve_webapp.py --trust         # add cert to the Windows
                                               # user trust store (certutil;
                                               # shows a confirmation popup)

The certificate (SANs: localhost, 127.0.0.1, ::1, and this machine's LAN
IPs) is generated once into tools/.localcert/ and reused. Generation uses
the 'cryptography' package when available, else the openssl CLI (bundled
with Git for Windows).

Note: Chrome's built-in AI needs more than a secure context - Chrome 131+
(or Canary/Dev with chrome://flags/#prompt-api-for-gemini-nano and
#optimization-guide-on-device-model set), the "Optimization Guide On
Device Model" component downloaded (chrome://components), and enough
disk/RAM. chrome://on-device-internals shows the model state.
"""

import argparse
import datetime
import http.server
import ipaddress
import os
import socket
import ssl
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CERT_DIR = os.path.join(HERE, ".localcert")
CERT = os.path.join(CERT_DIR, "localhost.pem")
KEY = os.path.join(CERT_DIR, "localhost-key.pem")
WEBROOT = os.path.normpath(os.path.join(HERE, "..", "webapp"))


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addr = info[4][0]
            if ":" not in addr and not addr.startswith("127."):
                ips.add(addr)
    except OSError:
        pass
    # UDP trick finds the default-route interface even if hostname lookup fails
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def gen_cert_cryptography(ips):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    sans = [x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.IPAddress(ipaddress.ip_address("::1"))]
    for ip in ips:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                       critical=True)
        .sign(key, hashes.SHA256())
    )
    with open(KEY, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
    with open(CERT, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def gen_cert_openssl(ips):
    sans = ["DNS:localhost", "IP:127.0.0.1", "IP:::1"] + [
        "IP:%s" % ip for ip in ips]
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", KEY, "-out", CERT, "-days", "825",
         "-subj", "/CN=localhost",
         "-addext", "subjectAltName=" + ",".join(sans)],
        check=True)


def ensure_cert():
    if os.path.exists(CERT) and os.path.exists(KEY):
        return
    os.makedirs(CERT_DIR, exist_ok=True)
    ips = lan_ips()
    print("generating self-signed cert for localhost + %s" % ", ".join(ips))
    try:
        gen_cert_cryptography(ips)
        print("(via python 'cryptography')")
    except ImportError:
        gen_cert_openssl(ips)
        print("(via openssl CLI)")


def trust_cert():
    """Windows: add to the current user's Root store (confirmation popup)."""
    if sys.platform != "win32":
        print("--trust is Windows-only; on other OSes trust %s manually" % CERT)
        return
    print("adding cert to the CurrentUser Root store - CONFIRM THE POPUP...")
    subprocess.run(["certutil", "-user", "-addstore", "Root", CERT],
                   check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--root", default=WEBROOT)
    ap.add_argument("--trust", action="store_true",
                    help="install the cert into the Windows user trust store")
    args = ap.parse_args()

    ensure_cert()
    if args.trust:
        trust_cert()

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=args.root, **kw)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")  # dev: no staleness
            super().end_headers()

    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print("serving %s at:" % args.root)
    print("  https://localhost:%d/" % args.port)
    for ip in lan_ips():
        print("  https://%s:%d/  (phones: accept the cert warning)" % (ip, args.port))
    print("Ctrl+C to stop. If Chrome warns, 'Advanced > Proceed' once, or")
    print("re-run with --trust to add it to the Windows user trust store.")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
