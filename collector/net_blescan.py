# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
net_blescan - receive node readings broadcast as BLE advertisements.

The hub-side half of node/net_bleadv.py (layout: envadv.py). Raw `_bleio`
scanning with the advertisement prefix as the controller/host filter, so
only our manufacturer-data packets reach Python.

`_bleio`'s ScanResults is a blocking iterator: `for e in results` waits for
the next entry or the scan timeout. A main loop that also serves HTTP and
the BLE UART cannot sit in it, so poll() runs a SHORT timed scan
(`scan_s`, default 1 s) at most every `every_s` seconds and returns what it
caught. A node advertises at ~100-150 ms for its whole window (20 s by
default), so a 1 s scan every 5 s cannot miss a window.

Untested here (no hardware in this session): scanning while the hub is
itself advertising the UART service. Zephyr's host allows the combination
and most controllers do; if start_scan raises while advertising, poll()
reports it once and keeps trying, and the failure signature to look for on
the REPL is "BLE scan failed: ... EBUSY/-16" or "-EINVAL".
"""

import time

import envadv


class AdvReceiver:
    def __init__(self, scan_s=1.0, every_s=5.0, min_rssi=-100):
        self.ok = False
        self.scan_s = scan_s
        self.every_s = every_s
        self.min_rssi = min_rssi
        self.last_seq = {}       # address bytes -> last seq accepted
        self.names = {}          # address bytes -> src name
        self.rx_count = 0
        self.dup_count = 0
        self.last_error = None
        self._next = 0.0
        self._warned = False
        try:
            import _bleio
            self.adapter = _bleio.adapter
            self.adapter.enabled = True
            self.ok = True
        except Exception as exc:
            print("BLE scan receiver unavailable: %s: %s"
                  % (type(exc).__name__, exc))

    @staticmethod
    def src_for(addr):
        """Stable node id from the advertiser address: the node's name does
        not fit the 31-byte PDU next to the reading, so the hub's `zones`
        config maps this id to a display name."""
        b = bytes(addr)
        return "ble-%02X%02X" % (b[-2], b[-1])

    def poll(self):
        """Yield (src, packet_dict, rssi, raw_adv_bytes) for each NEW
        reading. Blocks for scan_s at most once per every_s."""
        if not self.ok:
            return
        now = time.monotonic()
        if now < self._next:
            return
        self._next = now + self.every_s
        try:
            results = self.adapter.start_scan(
                envadv.PREFIX, buffer_size=512, timeout=self.scan_s,
                interval=0.1, window=0.1, minimum_rssi=self.min_rssi,
                active=False)
            for e in results:
                raw = bytes(e.advertisement_bytes)
                got = envadv.unpack(raw)
                if got is None:
                    continue
                seq, m, vb, kind = got
                addr = bytes(e.address.address_bytes)
                if self.last_seq.get(addr) == seq:
                    self.dup_count += 1
                    continue
                self.last_seq[addr] = seq
                self.rx_count += 1
                src = self.src_for(addr)
                yield src, envadv.to_packet(src, seq, m, vb, kind), e.rssi, raw
        except Exception as exc:
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            if not self._warned:
                self._warned = True
                print("BLE scan failed: %s" % self.last_error)
        finally:
            try:
                self.adapter.stop_scan()
            except Exception:
                pass
