# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
net_captive - self-hosted access point + captive-portal DNS.

The collector always answers on its own AP (configurable) so the portal and
data are reachable with no infrastructure: connect to the AP and any DNS
lookup resolves to the hub, which pops the portal on phones/laptops via the
OS captive-portal probes (handled as HTTP routes in net_wifi.py).

STA (home WiFi) and AP run concurrently -- the single radio forces the AP
onto the STA channel when both are up, which is fine: ESP-NOW nodes
channel-hunt to find us anyway.

The DNS responder is a minimal non-blocking UDP answerer: every A query
gets the AP's IPv4. Poll it from the main loop.
"""

import wifi

try:
    import socketpool
except ImportError:
    socketpool = None

AP_IP = "192.168.4.1"  # CircuitPython softAP default


class CaptivePortal:
    def __init__(self, ssid="ENVHUB", password="", enabled=True):
        self.enabled = enabled
        self.ap_active = False
        self.dns_queries = 0
        self._sock = None
        self._buf = bytearray(256)
        if not enabled:
            return
        try:
            if password and len(password) >= 8:
                wifi.radio.start_ap(ssid=ssid, password=password)
            else:
                if password:
                    print("AP password <8 chars; starting OPEN network")
                wifi.radio.start_ap(ssid=ssid)
            self.ap_active = True
            print("AP up: %s @ %s" % (ssid, wifi.radio.ipv4_address_ap))
        except (RuntimeError, ValueError, OSError, NotImplementedError) as exc:
            print("AP start failed:", exc)
            return
        if socketpool is None:
            return
        try:
            pool = socketpool.SocketPool(wifi.radio)
            self._sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
            self._sock.setblocking(False)
            self._sock.bind(("0.0.0.0", 53))
            print("captive DNS listening on :53")
        except OSError as exc:
            print("captive DNS failed:", exc)
            self._sock = None

    @property
    def ap_ip(self):
        try:
            return str(wifi.radio.ipv4_address_ap or AP_IP)
        except AttributeError:
            return AP_IP

    def _answer(self, query, qlen):
        """Build a DNS response resolving any A query to the AP IP."""
        if qlen < 12:
            return None
        # walk the question name to find its end
        i = 12
        while i < qlen and query[i] != 0:
            i += query[i] + 1
        i += 5  # null + QTYPE(2) + QCLASS(2)
        if i > qlen:
            return None
        ip = bytes(int(x) for x in self.ap_ip.split("."))
        return (
            bytes(query[0:2])            # transaction id
            + b"\x81\x80"                # standard response, no error
            + b"\x00\x01\x00\x01\x00\x00\x00\x00"  # 1 question, 1 answer
            + bytes(query[12:i])         # original question
            + b"\xc0\x0c"                # answer name -> pointer to question
            + b"\x00\x01\x00\x01"        # type A, class IN
            + b"\x00\x00\x00\x3c"        # TTL 60s
            + b"\x00\x04" + ip           # rdlength 4 + address
        )

    def poll(self):
        if self._sock is None:
            return
        for _ in range(4):  # drain a few queries per loop, never block
            try:
                n, addr = self._sock.recvfrom_into(self._buf)
            except OSError:
                return  # EAGAIN - nothing waiting
            if not n:
                return
            resp = self._answer(self._buf, n)
            if resp:
                self.dns_queries += 1
                try:
                    self._sock.sendto(resp, addr)
                except OSError:
                    pass
