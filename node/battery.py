# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
battery - host supply monitoring for the collector.

Detects "unplugged" per the project spec: the Feather's BAT rail sits at
~4.4-5V (through the charger) while USB/DC power is present, and <=4.2V once
running from the LiPo alone -- so a reading below host_vcc_unplugged_v
(default 4.35V) means we are on battery. supervisor.runtime.usb_connected is
used as a second signal (it only covers USB data connections, not a plain
5V supply, so the voltage check stays primary).

Measurement source auto-detect, in order:
  1. MAX17048 fuel gauge on I2C (newer Feather ESP32-S3/C6 revisions)
  2. LC709203F fuel gauge on I2C (older S2/S3 revisions)
  3. board.VOLTAGE_MONITOR / board.BATTERY analog pin (divided by 2)
"""

import time

try:
    import supervisor
except ImportError:
    supervisor = None


class BatteryMonitor:
    def __init__(self, i2c, unplugged_v=4.35, crit_v=3.4):
        self.unplugged_v = unplugged_v
        self.crit_v = crit_v
        self._gauge = None
        self._adc = None
        self.source = "none"
        self._last = (0, None)  # (monotonic, volts) cache
        if i2c is not None:
            try:
                import adafruit_max1704x
                self._gauge = adafruit_max1704x.MAX17048(i2c)
                self.source = "max17048"
            except (ImportError, ValueError, OSError, RuntimeError):
                try:
                    import adafruit_lc709203f
                    self._gauge = adafruit_lc709203f.LC709203F(i2c)
                    self.source = "lc709203f"
                except (ImportError, ValueError, OSError, RuntimeError):
                    self._gauge = None
        if self._gauge is None:
            try:
                import analogio
                import board
                pin = getattr(board, "VOLTAGE_MONITOR", None) or getattr(
                    board, "BATTERY", None
                )
                if pin is not None:
                    self._adc = analogio.AnalogIn(pin)
                    self.source = "adc"
            except (ImportError, ValueError):
                pass

    def voltage(self):
        """Battery-rail voltage, cached for 5s. None if unmeasurable."""
        now = time.monotonic()
        if now - self._last[0] < 5:
            return self._last[1]
        volts = None
        try:
            if self._gauge is not None:
                volts = self._gauge.cell_voltage
            elif self._adc is not None:
                # 100k/100k divider on Feathers -> x2
                volts = self._adc.value / 65535 * self._adc.reference_voltage * 2
        except OSError:
            pass
        self._last = (now, volts)
        return volts

    def status(self):
        """{"v": volts|None, "usb": bool|None, "unplugged": bool, "crit": bool}"""
        volts = self.voltage()
        usb = supervisor.runtime.usb_connected if supervisor else None
        unplugged = False
        crit = False
        if volts is not None:
            unplugged = volts < self.unplugged_v
            crit = unplugged and volts < self.crit_v
        elif usb is not None:
            unplugged = not usb
        return {
            "v": None if volts is None else round(volts, 3),
            "usb": usb,
            "unplugged": unplugged,
            "crit": crit,
            "source": self.source,
        }
