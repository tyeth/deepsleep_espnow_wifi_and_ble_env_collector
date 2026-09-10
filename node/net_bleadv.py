# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
net_bleadv - broadcast a reading as a BLE advertisement (node side).

Raw `_bleio`, no adafruit_ble: on a Pico W the adafruit_ble import chain
alone (~30 KB of heap on a 32-bit build) is most of the board. The hub's
matching receiver is collector/net_blescan.py; the byte layout is envadv.py.

The advertisement is non-connectable and has no scan response, so the
controller sends ADV_NONCONN_IND at the port's fixed fast interval
(~100-150 ms; zephyr-cp ignores the `interval` argument) for as long as
`start()` is in effect. Legacy PDUs only: this controller has no extended
advertising and the port builds with CONFIG_BT_EXT_ADV=n.
"""


class Beacon:
    def __init__(self):
        self.ok = False
        self.active = False
        try:
            import _bleio
            try:
                # CircuitPython's own BLE workflow advertises CIRCUITPYxxxx
                # from the same adapter; with one legacy advertising set the
                # port stops it when user code starts advertising, but
                # switching the workflow off keeps it from coming back.
                import supervisor
                supervisor.runtime.ble_workflow = False
            except (ImportError, AttributeError):
                pass
            self.adapter = _bleio.adapter
            self.adapter.enabled = True
            self.ok = True
        except Exception as exc:
            print("BLE beacon unavailable: %s: %s" % (type(exc).__name__, exc))

    def start(self, data):
        """Start (or replace) the advertisement. Returns True when on air."""
        if not self.ok:
            return False
        try:
            if self.adapter.advertising:
                self.adapter.stop_advertising()
            self.adapter.start_advertising(data, connectable=False,
                                           interval=0.5)
            self.active = True
        except Exception as exc:
            print("BLE beacon start failed: %s: %s" % (type(exc).__name__, exc))
            self.active = False
        return self.active

    def stop(self):
        if not self.ok:
            return
        try:
            if self.adapter.advertising:
                self.adapter.stop_advertising()
        except Exception as exc:
            print("BLE beacon stop failed: %s" % exc)
        self.active = False
