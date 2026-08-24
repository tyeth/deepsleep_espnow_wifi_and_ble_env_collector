# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
net_espnow - collector-side ESP-NOW receiver + config push-back.

Nodes unicast 'dat' packets at us (they channel-hunt until our MAC ACKs, so
no channel coordination is needed here -- we just sit on whatever channel
WiFi negotiated, or the radio default when WiFi is down).

Every received 'dat' gets an immediate unicast 'cfg' reply carrying that
node's interval, enabled metrics, ASC-off policy, and -- only when armed by
the user -- a forced CO2 recalibration target. The node listens briefly
after sending, then deep-sleeps.
"""

import espnow

import envproto


class EspNowHub:
    def __init__(self, existing=None):
        """existing: an ESPNow object created in the early radio block --
        on the C6, creating ESP-NOW while a user softAP is active kills
        the AP (and can wedge USB), so it must come up before the AP."""
        self.enabled = False
        self.rx_count = 0
        self.last_error = None
        self._e = None
        self._peers = {}  # mac bytes -> espnow.Peer
        try:
            self._e = existing if existing is not None else espnow.ESPNow()
            self.enabled = True
        except (RuntimeError, ValueError, OSError) as exc:
            self.last_error = str(exc)
            print("ESP-NOW init failed:", exc)

    def poll(self):
        """Drain the receive buffer. Returns list of (mac_bytes, dict, rssi)."""
        out = []
        if not self.enabled:
            return out
        while self._e:
            try:
                if not len(self._e):
                    break
                pkt = self._e.read()
            except (RuntimeError, OSError) as exc:
                self.last_error = str(exc)
                break
            if pkt is None:
                break
            obj = envproto.decode(pkt.msg)
            if obj is not None:
                self.rx_count += 1
                out.append((bytes(pkt.mac), obj, pkt.rssi))
        return out

    def _peer(self, mac):
        peer = self._peers.get(mac)
        if peer is None:
            peer = espnow.Peer(mac=mac)
            self._e.peers.append(peer)
            self._peers[mac] = peer
        return peer

    def send(self, mac, payload) -> bool:
        """Unicast payload bytes to a node. True if the MAC-layer ACKed."""
        if not self.enabled:
            return False
        try:
            self._e.send(payload, self._peer(mac))
            return True
        except (RuntimeError, OSError, ValueError) as exc:
            self.last_error = str(exc)
            return False
