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
        self.bad_count = 0
        self.ack_count = 0
        self.dup_count = 0
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
        """Drain the receive buffer.

        Returns list of (mac_bytes, dict, rssi, crc) -- crc is the CRC-16 of
        the bytes as received, which goes straight back in the confirmation
        so the node can prove its packet arrived intact.
        """
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
            raw = bytes(pkt.msg)
            obj = envproto.decode(raw)
            if obj is not None:
                self.rx_count += 1
                out.append((bytes(pkt.mac), obj, pkt.rssi, envproto.crc16(raw)))
            else:
                # undecodable: nothing to confirm (no id), but say so loudly --
                # a corrupted frame is exactly what the CRC scheme is for
                self.bad_count += 1
                print("ESP-NOW: undecodable packet from %s (%d bytes)"
                      % (envproto.mac_str(bytes(pkt.mac)), len(raw)))
        return out

    def _peer(self, mac):
        peer = self._peers.get(mac)
        if peer is None:
            try:
                peer = espnow.Peer(mac=mac)
                self._e.peers.append(peer)
            except (RuntimeError, OSError, ValueError) as exc:
                print("ESP-NOW peer add %s failed: %s: %s"
                      % (envproto.mac_str(mac), type(exc).__name__, exc))
                return None
            self._peers[mac] = peer
        return peer

    def _reinit(self):
        """Tear down and rebuild the espnow object (per-error recovery:
        the C6 send path gets stuck in ESP_ERR_ESPNOW_NO_MEM 0x3067 with
        BLE resident; a deinit/re-setup clears the driver state). Only
        safe when no user softAP is up (issue 6) -- BLE mode qualifies."""
        try:
            self._e.deinit()
        except (RuntimeError, OSError, ValueError, AttributeError):
            pass
        self._peers = {}
        try:
            self._e = espnow.ESPNow()
            print("ESP-NOW reinitialised after send errors")
            return True
        except (RuntimeError, OSError, ValueError) as exc:
            self.last_error = str(exc)
            print("ESP-NOW reinit failed:", exc)
            self.enabled = False
            return False

    def send(self, mac, payload) -> bool:
        """Unicast payload bytes to a node. True if the MAC-layer ACKed."""
        if not self.enabled:
            return False
        # C6 + resident BLE: sends fail ESP_ERR_ESPNOW_NO_MEM (0x3067, IDF
        # internal heap). Retry briefly, then deinit + re-setup and retry.
        import time
        for attempt in range(4):
            peer = self._peer(mac)
            if peer is None:
                if attempt < 3 and self._reinit():
                    continue
                return False
            try:
                self._e.send(payload, peer)
                return True
            except (RuntimeError, OSError, ValueError) as exc:
                self.last_error = str(exc)
                if attempt < 2:
                    time.sleep(0.1)
                elif attempt == 2:
                    if not self._reinit():
                        return False
                else:
                    print("ESP-NOW send to %s failed even after reinit: "
                          "%s: %s" % (envproto.mac_str(mac),
                                      type(exc).__name__, exc))
        return False
