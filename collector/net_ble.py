# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
net_ble - BLE access via Nordic UART, for web-BLE clients.

Works with any web Bluetooth UART console (e.g. Adafruit's web bluetooth
dashboard / bluefruit web terminal). Line-oriented text commands in, JSON
lines out. Commands map to the same shared handlers as the HTTP API:

  latest            -> latest values + alert states
  battery           -> battery concerns
  events            -> active out-of-spec + recent events
  config            -> effective config
  set <json>        -> merge JSON into config
  cal <src> <1|2>   -> two-step forced CO2 recalibration
  days              -> list of stored days on SD

Requires CircuitPython with _bleio (ESP32-S3/C6 -- use the latest alpha for
the BLE fixes; not available on ESP32-S2, where this module degrades to a
no-op).
"""

import json

try:
    from adafruit_ble import BLERadio
    from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
    from adafruit_ble.services.nordic import UARTService
    _HAVE_BLE = True
except ImportError:
    _HAVE_BLE = False


class BleUartPortal:
    def __init__(self, handlers, name="ENVHUB", enabled=True):
        self.handlers = handlers
        self.ok = False
        self.connected = False
        self._rxbuf = b""
        if not enabled:
            print("BLE disabled by config")
            return
        if not _HAVE_BLE:
            print("BLE not available on this board/build")
            return
        try:
            self.radio = BLERadio()
            self.radio.name = name
            self.uart = UARTService()
            self.adv = ProvideServicesAdvertisement(self.uart)
            self.adv.complete_name = name
            self.radio.start_advertising(self.adv)
            self.ok = True
            print("BLE advertising as", name)
        except Exception as exc:
            print("BLE init failed:", exc)

    def _send(self, obj):
        data = (json.dumps(obj) + "\n").encode()
        # UARTService.write chunks internally, but stay defensive on size
        for i in range(0, len(data), 128):
            self.uart.write(data[i : i + 128])

    def _dispatch(self, line):
        h = self.handlers
        parts = line.strip().split(None, 2)
        if not parts:
            return
        cmd = parts[0].lower()
        try:
            if cmd == "latest":
                self._send(h["latest"]())
            elif cmd == "battery":
                self._send(h["battery"]())
            elif cmd == "events":
                self._send(h["events"]())
            elif cmd == "config":
                self._send(h["config_get"]())
            elif cmd == "days":
                self._send({"days": h["list_days"]()})
            elif cmd == "hist" and len(parts) > 1:
                # stream a day's CSV: "#BEGIN <day>" ... raw CSV ... "#END"
                day = parts[1]
                chunks = h["history_lines"](day)
                if chunks is None:
                    self._send({"err": "no such day", "days": h["list_days"]()})
                else:
                    self.uart.write(("#BEGIN %s\n" % day).encode())
                    for chunk in chunks:
                        for i in range(0, len(chunk), 128):
                            self.uart.write(chunk[i : i + 128])
                    self.uart.write(b"#END\n")
            elif cmd == "set" and len(parts) > 1:
                body = json.loads(line.strip()[4:])
                self._send(h["config_set"](body))
            elif cmd == "cal":
                src = parts[1] if len(parts) > 1 else "local"
                step = int(parts[2]) if len(parts) > 2 else 1
                self._send(h["calibrate"](src, step))
            else:
                self._send({"err": "unknown cmd",
                            "cmds": ["latest", "battery", "events", "config",
                                     "days", "hist <day>", "set <json>",
                                     "cal <src> <1|2>"]})
        except Exception as exc:
            self._send({"err": str(exc)})

    def poll(self):
        if not self.ok:
            return
        try:
            if not self.radio.connected:
                if self.connected:
                    self.connected = False
                    self._rxbuf = b""
                    self.radio.start_advertising(self.adv)
                return
            self.connected = True
            n = self.uart.in_waiting
            if n:
                self._rxbuf += self.uart.read(n) or b""
                while b"\n" in self._rxbuf:
                    line, self._rxbuf = self._rxbuf.split(b"\n", 1)
                    self._dispatch(line.decode())
                if len(self._rxbuf) > 512:
                    self._rxbuf = b""  # garbage guard
        except Exception as exc:
            print("BLE poll error:", exc)
