# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
net_blescan - receive node readings broadcast as BLE advertisements.

The hub-side half of node/net_bleadv.py (layout: envadv.py). Raw `_bleio`
scanning with the advertisement prefix as the controller/host filter, so
only our manufacturer-data packets reach Python.

`_bleio`'s ScanResults is a blocking iterator: `for e in results` waits for
the next entry or the end of the scan. A main loop that also serves HTTP
and the BLE UART cannot sit in it, so poll() runs a SHORT timed scan
(`scan_s`, default 1 s) at most every `every_s` seconds and returns what it
caught. A node advertises at ~100-150 ms for its whole window (20 s by
default), so a 1 s scan every 5 s cannot miss a window.

**The scan's `timeout=` is not trusted.** Measured on a Pico 2 W: Zephyr's
legacy-scan path (`start_le_scan_legacy()`, the only one there, since the
CYW43439 has no extended advertising and the port forces
CONFIG_BT_EXT_ADV=n) never reads the timeout, so on zephyr-cp firmware
without tyeth/circuitpython#20 a `timeout=1` scan simply never ends -- a
`timeout=3` scan was still yielding reports at 57 s -- and the hub's first
poll() would have been its last. So poll() also keeps its own deadline and
stops the scan itself once it passes. That covers the usual case, where
reports keep arriving; on the unfixed firmware in a radio-silent room the
iterator can still block between reports, which only #20 cures.
TODO(fw-11): drop this note once the rebased firmware is the minimum.

Untested on hardware: scanning while the hub is itself advertising the
UART service. Zephyr's host allows the combination and most controllers
do; if start_scan raises while advertising, poll() reports it once and
keeps trying, and the failure signature to look for on the REPL is
"BLE scan failed: ... EBUSY/-16" or "-EINVAL".
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
        self.rx_count = 0
        self.dup_count = 0
        self.overruns = 0        # scans we had to stop ourselves (see top)
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
        config maps this id to a display name.

        `address_bytes` is least-significant byte FIRST (CircuitPython
        stores it reversed from how addresses are printed), so the two
        bytes that differ between boards are [1] and [0] -- the last two
        of the printed address. [-2:] would be the vendor (OUI) end, the
        same on every CYW43439, and every Pico node would share one id."""
        b = bytes(addr)
        return "ble-%02X%02X" % (b[1], b[0])

    def poll(self):
        """Yield (src, packet_dict, rssi, raw_adv_bytes) for each NEW
        reading. Scans for scan_s at most once per every_s."""
        if not self.ok:
            return
        now = time.monotonic()
        if now < self._next:
            return
        self._next = now + self.every_s
        # a little slack over scan_s: the firmware's own timeout, where it
        # works, should be what ends the scan; ours is the backstop
        deadline = now + self.scan_s + 0.5
        try:
            results = self.adapter.start_scan(
                envadv.PREFIX, buffer_size=512, timeout=self.scan_s,
                interval=0.1, window=0.1, minimum_rssi=self.min_rssi,
                active=False)
            for e in results:
                if time.monotonic() > deadline:
                    # the firmware ignored timeout= (see the top of file)
                    self.overruns += 1
                    if self.overruns == 1:
                        print("BLE scan: timeout= not honoured by this "
                              "firmware; stopping scans ourselves")
                    break
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
