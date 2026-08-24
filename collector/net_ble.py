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
  cal               -> calibration status (pending / scheduled / results)
  cal <src> 1       -> arm + setup/power/timing guidance
  cal <src> 2 [4am|now|<epoch>] [dur_s] [dry] [asc]
                    -> schedule the reference window (default next 04:00);
                       'asc' = overnight automatic-self-calibration mode
  days              -> list of stored days on SD

Requires CircuitPython with _bleio (ESP32-S3/C6 -- use the latest alpha for
the BLE fixes; not available on ESP32-S2, where this module degrades to a
no-op).
"""

import json
import time

# C6/CP10.3-a4 _bleio: the outgoing notification queue holds ~5 packets
# (5 x 20B at the default ATT MTU) and UARTService.write neither blocks
# nor raises on overflow -- excess notifications are SILENTLY DROPPED
# (measured: every burst reply truncates at exactly 100 bytes).
# Preferred fix: a _bleio.PacketBuffer on the TX characteristic, whose
# write() provides real flow control. Fallback: pace one notification
# per write with a gap so the queue drains (still loses the odd packet).
_TX_CHUNK = 20
_TX_DELAY = 0.05   # 20ms still lost the odd packet on long replies

try:
    from adafruit_ble import BLERadio
    from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
    from adafruit_ble.services.nordic import UARTService
    _HAVE_BLE = True
except ImportError:
    _HAVE_BLE = False


class BleUartPortal:
    def __init__(self, handlers, name="ENVHUB", enabled=True,
                 radio=None, uart=None, adv=None, use_pktbuf=False):
        """radio/uart/adv: pre-built objects from the early radio block --
        on the C6, BLE must be created AND advertising before the softAP
        starts (any other ordering fails; see bugs_issues_and_todos.md).
        When adv is given, advertising is assumed already running."""
        self.handlers = handlers
        self.ok = False
        self.connected = False
        self._rxbuf = b""
        self._pb = None
        if not enabled:
            print("BLE disabled by config")
            return
        if not _HAVE_BLE and radio is None:
            print("BLE not available on this board/build")
            return
        try:
            self.radio = radio or BLERadio()
            self.uart = uart or UARTService()
            if adv is not None:
                self.adv = adv  # early block already started advertising
            else:
                self.radio.name = name
                self.adv = ProvideServicesAdvertisement(self.uart)
                self.adv.complete_name = name
                self.radio.start_advertising(self.adv)
            self.ok = True
            # PacketBuffer TX gives true flow control (no dropped
            # notifications) BUT on C6/CP10.3-a4 its write() blocks FOREVER
            # if the client disconnects mid-reply, wedging the main loop
            # (bugs item 9) -- so it's opt-in ("ble_tx_pktbuf": true) until
            # the core aborts blocked writes on disconnect.
            self._pb = self._make_packet_buffer() if use_pktbuf else None
            print("BLE portal ready (advertising as %s, tx=%s)"
                  % (name, "pktbuf" if self._pb else "paced"))
        except Exception as exc:
            print("BLE init failed:", type(exc).__name__, exc)

    def _make_packet_buffer(self):
        """Server-side StreamOut binds to the raw _bleio.Characteristic;
        wrapping it in a PacketBuffer gives writes real flow control
        (multi-packet queue) instead of the drop-on-overflow UART path."""
        ch = None
        try:
            import _bleio
            ch = getattr(self.uart, "_server_tx", None)
            # server-side StreamOut binds as a BoundWriteStream wrapper
            ch = getattr(ch, "bound_characteristic", ch)
            if ch is None:
                print("PacketBuffer TX: no _server_tx on UARTService")
                return None
            return _bleio.PacketBuffer(ch, buffer_size=8)
        except Exception as exc:
            print("PacketBuffer TX unavailable (%s: %s; ch=%s); pacing"
                  % (type(exc).__name__, exc, type(ch).__name__))
            return None

    def _write_paced(self, data):
        if self._pb is not None:
            try:
                try:
                    size = self._pb.outgoing_packet_length
                except (AttributeError, ValueError):
                    size = _TX_CHUNK
                size = max(1, min(size, 512))
                for i in range(0, len(data), size):
                    chunk = data[i : i + size]
                    for _ in range(20):  # flow control: wait for queue room
                        if not self.radio.connected:
                            return  # client gone: abort (it will resend)
                        if self._pb.write(chunk):
                            break
                        time.sleep(0.01)
                    else:
                        return  # client not draining: give up on this reply
                return
            except Exception as exc:
                print("pktbuf write failed (%s); falling back to pacing" % exc)
                self._pb = None
        for i in range(0, len(data), _TX_CHUNK):
            self.uart.write(data[i : i + _TX_CHUNK])
            time.sleep(_TX_DELAY)

    def _send(self, obj):
        self._write_paced((json.dumps(obj) + "\n").encode())

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
                    self._write_paced(("#BEGIN %s\n" % day).encode())
                    for chunk in chunks:
                        self._write_paced(chunk)
                    self._write_paced(b"#END\n")
            elif cmd == "set" and len(parts) > 1:
                body = json.loads(line.strip()[4:])
                self._send(h["config_set"](body))
            elif cmd == "cal":
                words = line.strip().split()
                if len(words) == 1:
                    self._send(h["cal_status"]())
                else:
                    src = words[1]
                    step = int(words[2]) if len(words) > 2 else 1
                    opts = {}
                    for w in words[3:]:
                        wl = w.lower()
                        if wl == "dry":
                            opts["dry"] = True
                        elif wl == "asc":
                            opts["mode"] = "asc"
                        elif wl in ("now", "4am", "next") or (
                                wl.isdigit() and len(wl) >= 9):
                            opts["when"] = wl
                        elif wl.isdigit():
                            opts["duration_s"] = int(wl)
                    self._send(h["calibrate"](src, step, opts))
            elif cmd == "time" and len(parts) > 1:
                self._send(h["time_set"](parts[1]))
            elif cmd == "mem":
                import gc
                gc.collect()
                self._send({"free": gc.mem_free()})
            else:
                self._send({"err": "unknown cmd",
                            "cmds": ["latest", "battery", "events", "config",
                                     "days", "hist <day>", "set <json>",
                                     "cal", "cal <src> 1",
                                     "cal <src> 2 [4am|now] [dur_s] [dry|asc]",
                                     "time <epoch>", "mem"]})
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
                    print("BLE client disconnected")
                # re-advertise whenever idle: C6 _bleio drops advertising on
                # disconnect and a one-shot restart can be missed/fail
                if not self.radio.advertising:
                    try:
                        self.radio.start_advertising(self.adv)
                        print("BLE re-advertising")
                    except Exception as exc:
                        print("BLE re-advertise failed:", exc)
                return
            if not self.connected:
                print("BLE client connected")
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
