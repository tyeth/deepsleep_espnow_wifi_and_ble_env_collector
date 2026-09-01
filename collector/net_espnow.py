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

Upstream behaviour this wrapper defends against (adafruit/circuitpython):
  #9816  read() raises ValueError "Invalid buffer" once the receive ring
         buffer loses sync with the WiFi task, and every later read raises
         the same: the object is dead until deinit + a new ESPNow.
  #7903  a peer whose channel differs from the radio's raises on send; the
         hub only ever replies on its own channel (Peer channel 0), so this
         is the node's problem, not ours.
  #9380  broadcast needs the peer passed explicitly to send(); the hub
         never broadcasts.
  Peer table: IDF holds at most 20 peers (ESP_ERR_ESPNOW_FULL 0x3068 past
         that), so replies keep a bounded, least-recently-used set.
  Issue 6 in bugs_issues_and_todos.md: creating espnow.ESPNow() while a
         user softAP is up kills the AP on the C6, so no rebuild happens in
         AP mode -- a dead receiver asks code.py for a clean reset instead.
"""

import time

import espnow

import envproto

# IDF's table holds 20 peers in total. Stay well under it so a reply to a
# new node never fails just because 20 others reported earlier.
PEER_MAX = 16


class EspNowHub:
    def __init__(self, existing=None, ap_active=False):
        """existing: an ESPNow object created in the early radio block --
        on the C6, creating ESP-NOW while a user softAP is active kills
        the AP (and can wedge USB), so it must come up before the AP.

        ap_active: a user softAP is up, so this object must never be
        rebuilt (same reason); recovery is a reset instead."""
        self.enabled = False
        self.ap_active = bool(ap_active)
        self.needs_reset = False   # receiver dead and no safe rebuild: code.py
                                   # flushes the store and resets the board
        self.rx_count = 0
        self.bad_count = 0
        self.conf_count = 0   # confirmations handed to the radio (async ACK)
        self.dup_count = 0
        self.last_error = None
        self._e = None
        self._peers = {}      # mac bytes -> espnow.Peer
        self._peer_order = []  # mac bytes, least recently used first
        if existing is None and self.ap_active:
            # the early init failed and the AP is up: a new ESPNow now would
            # take the AP down with it (issue 6). Run without nodes.
            self.last_error = "not started: softAP already up"
            print("ESP-NOW left off: a softAP is up (issue 6)")
            return
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
            except ValueError as exc:
                # #9816: the ring buffer is out of sync and stays that way.
                # Anything still queued is lost either way; rebuild when
                # that is safe, otherwise ask for a reset.
                self.last_error = str(exc)
                print("ESP-NOW receive buffer corrupt (%s)" % exc)
                self._recover_receiver()
                break
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

    def _recover_receiver(self):
        """The receive path is dead. Rebuild if no softAP is up; else stop
        polling and flag a reset (the only recovery that keeps the AP)."""
        if not self.ap_active and self._reinit():
            return
        self.enabled = False
        self.needs_reset = True
        print("ESP-NOW receiver dead (%s): requesting a reset"
              % ("no safe rebuild with the AP up" if self.ap_active
                 else "rebuild failed"))

    def _peer(self, mac):
        peer = self._peers.get(mac)
        if peer is not None:
            # most recently used goes to the back
            self._peer_order.remove(mac)
            self._peer_order.append(mac)
            return peer
        while len(self._peer_order) >= PEER_MAX:
            if not self._evict_peer(self._peer_order[0]):
                break   # IDF kept it; try the add anyway rather than spin
        try:
            peer = espnow.Peer(mac=mac)
            self._e.peers.append(peer)
        except (RuntimeError, OSError, ValueError) as exc:
            print("ESP-NOW peer add %s failed: %s: %s"
                  % (envproto.mac_str(mac), type(exc).__name__, exc))
            return None
        self._peers[mac] = peer
        self._peer_order.append(mac)
        return peer

    def _evict_peer(self, mac):
        """Drop a peer from IDF's table and our books. False if IDF refused,
        in which case the books keep it too, so they never disagree."""
        peer = self._peers.get(mac)
        if peer is not None:
            try:
                self._e.peers.remove(peer)
            except (RuntimeError, OSError, ValueError) as exc:
                print("ESP-NOW peer remove %s failed: %s"
                      % (envproto.mac_str(mac), exc))
                return False
        self._peers.pop(mac, None)
        if mac in self._peer_order:
            self._peer_order.remove(mac)
        return True

    def _reinit(self):
        """Tear down and rebuild the espnow object (per-error recovery:
        the C6 send path gets stuck in ESP_ERR_ESPNOW_NO_MEM 0x3067 with
        BLE resident; a deinit/re-setup clears the driver state). Refused
        while a user softAP is up (issue 6: a new ESPNow kills the AP and
        can wedge USB) -- BLE mode qualifies."""
        if self.ap_active:
            print("ESP-NOW not rebuilt: a softAP is up (issue 6)")
            return False
        try:
            self._e.deinit()
        except (RuntimeError, OSError, ValueError, AttributeError):
            pass
        self._peers = {}
        self._peer_order = []
        try:
            self._e = espnow.ESPNow()
            self.enabled = True
            print("ESP-NOW reinitialised")
            return True
        except (RuntimeError, OSError, ValueError) as exc:
            self.last_error = str(exc)
            print("ESP-NOW reinit failed:", exc)
            self.enabled = False
            return False

    def send(self, mac, payload) -> bool:
        """Unicast payload bytes to a node. True if the driver took it."""
        if not self.enabled:
            return False
        # C6 + resident BLE: sends fail ESP_ERR_ESPNOW_NO_MEM (0x3067, IDF
        # internal heap). Retry briefly, then deinit + re-setup and retry.
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
                        print("ESP-NOW send to %s failed: %s: %s"
                              % (envproto.mac_str(mac),
                                 type(exc).__name__, exc))
                        return False
                else:
                    print("ESP-NOW send to %s failed even after reinit: "
                          "%s: %s" % (envproto.mac_str(mac),
                                      type(exc).__name__, exc))
        return False
