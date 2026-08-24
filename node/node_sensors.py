# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
node_sensors - auto-detect and read whichever env/CO2 sensor a node carries.

Supported (I2C address -> driver):
  0x62  SCD4x  (adafruit_scd4x)
  0x61  SCD30  (adafruit_scd30)
  0x69  SEN5x  (minimal built-in driver -- no Adafruit CP driver exists)
  0x6B  SEN6x  (adafruit_sen6x)

Every driver is wrapped in a common interface:
  .kind                 "scd4x" | "scd30" | "sen5x" | "sen6x"
  .begin()              start measuring (called after wake)
  .read(timeout_s)      envproto metric dict or None
  .stop()               stop measuring before deep sleep (power saving)
  .set_asc(enabled)     automatic self calibration on/off (project: OFF)
  .force_recal(ppm)     forced CO2 recalibration -> correction or None

CO2 sensors need only ~5-10s awake; PM sensors (SEN5x/SEN6x) need their fan
spun up: pass pm_warmup_s from node_config for a usable PM reading.
"""

import struct
import time


def _crc8(data):
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


class MinimalSEN5x:
    """Just enough SEN54/SEN55 to read one measurement. Address 0x69."""

    ADDR = 0x69

    def __init__(self, i2c):
        self.i2c = i2c

    def _cmd(self, cmd, delay=0.02):
        buf = struct.pack(">H", cmd)
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.ADDR, buf)
        finally:
            self.i2c.unlock()
        time.sleep(delay)

    def _read_words(self, cmd, n_words, delay=0.02):
        self._cmd(cmd, delay)
        raw = bytearray(n_words * 3)
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.readfrom_into(self.ADDR, raw)
        finally:
            self.i2c.unlock()
        words = []
        for i in range(n_words):
            chunk = raw[i * 3 : i * 3 + 3]
            if _crc8(chunk[:2]) != chunk[2]:
                raise OSError("SEN5x CRC error")
            words.append((chunk[0] << 8) | chunk[1])
        return words

    def _write_word(self, cmd, value):
        payload = struct.pack(">H", value)
        buf = struct.pack(">H", cmd) + payload + bytes([_crc8(payload)])
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.ADDR, buf)
        finally:
            self.i2c.unlock()
        time.sleep(0.02)

    def start(self):
        self._cmd(0x0021, 0.05)

    def stop(self):
        self._cmd(0x0104, 0.2)

    def data_ready(self):
        return bool(self._read_words(0x0202, 1)[0] & 0x07FF)

    def read_values(self):
        w = self._read_words(0x03C4, 8, 0.02)

        def s16(v):
            return v - 0x10000 if v & 0x8000 else v

        def val(raw, div, signed=False):
            if raw == (0x7FFF if signed else 0xFFFF):
                return None
            return (s16(raw) if signed else raw) / div

        return {
            "pm1": val(w[0], 10),
            "pm25": val(w[1], 10),
            "pm4": val(w[2], 10),
            "pm10": val(w[3], 10),
            "rh": val(w[4], 100, True),
            "tc": val(w[5], 200, True),
            "voc": val(w[6], 10, True),
            "nox": val(w[7], 10, True),
        }


class _Base:
    kind = "?"

    def begin(self):
        pass

    def stop(self):
        pass

    def set_asc(self, enabled):
        pass

    def force_recal(self, ppm):
        return None


class Scd4x(_Base):
    kind = "scd4x"

    def __init__(self, i2c):
        import adafruit_scd4x
        self.s = adafruit_scd4x.SCD4X(i2c)

    def set_asc(self, enabled):
        # SCD4x settings commands need idle mode: pause, set, resume
        self.s.stop_periodic_measurement()
        try:
            self.s.self_calibration_enabled = enabled
        finally:
            self.s.start_periodic_measurement()

    def begin(self):
        self.s.start_periodic_measurement()

    def read(self, timeout_s=15):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.s.data_ready:
                return {
                    "co2": self.s.CO2,
                    "tc": self.s.temperature,
                    "rh": self.s.relative_humidity,
                }
            time.sleep(0.5)
        return None

    def stop(self):
        self.s.stop_periodic_measurement()

    def force_recal(self, ppm):
        # datasheet: >3 min of measurement in target air must precede FRC,
        # and periodic measurement must be stopped for the FRC command
        self.s.stop_periodic_measurement()
        self.s.force_calibration(ppm)
        return None  # driver does not expose the correction value


class Scd30(_Base):
    kind = "scd30"

    def __init__(self, i2c):
        import adafruit_scd30
        self.s = adafruit_scd30.SCD30(i2c)

    def set_asc(self, enabled):
        self.s.self_calibration_enabled = enabled

    def read(self, timeout_s=25):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.s.data_available:
                return {
                    "co2": self.s.CO2,
                    "tc": self.s.temperature,
                    "rh": self.s.relative_humidity,
                }
            time.sleep(0.5)
        return None

    def force_recal(self, ppm):
        self.s.forced_recalibration_reference = ppm
        return None


class Sen6x(_Base):
    kind = "sen6x"

    def __init__(self, i2c):
        import adafruit_sen6x
        self.s = adafruit_sen6x.SEN66(i2c)

    def set_asc(self, enabled):
        try:
            # driver refuses this while measuring: pause, set, resume
            self.s.stop_measurement()
            try:
                self.s.co2_automatic_self_calibration = enabled
            finally:
                self.s.start_measurement()
        except (OSError, AttributeError):
            pass

    def begin(self):
        self.s.start_measurement()

    def read(self, timeout_s=30):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.s.data_ready:
                d = self.s.all_measurements()
                return {
                    "tc": d.get("temperature"),
                    "rh": d.get("humidity"),
                    "co2": d.get("co2"),
                    "pm1": d.get("pm1_0"),
                    "pm25": d.get("pm2_5"),
                    "pm4": d.get("pm4_0"),
                    "pm10": d.get("pm10"),
                    "voc": d.get("voc_index"),
                    "nox": d.get("nox_index"),
                }
            time.sleep(0.5)
        return None

    def stop(self):
        self.s.stop_measurement()

    def force_recal(self, ppm):
        return self.s.force_co2_recalibration(ppm)


class Sen5x(_Base):
    """Prefers the good-enough-technology CircuitPython SEN5x library
    (circup bundle-add good-enough-technology/circuitpython_goodenough_bundle
     && circup install sensirion_i2c_sen5x); falls back to the minimal
    built-in driver when it isn't installed."""

    kind = "sen5x"

    def __init__(self, i2c):
        self._dev = None
        try:
            from sensirion_i2c_driver import I2cConnection, I2cTransceiver
            from sensirion_i2c_sen5x import Sen5xI2cDevice
            self._dev = Sen5xI2cDevice(
                I2cConnection(I2cTransceiver(i2c, 0x69))
            )
        except (ImportError, OSError, RuntimeError) as exc:
            print("sensirion sen5x lib unavailable (%s); using minimal driver"
                  % exc)
            self.s = MinimalSEN5x(i2c)

    @staticmethod
    def _phys(v):
        # response types carry .physical (float, NaN when unavailable)
        val = getattr(v, "physical", None)
        return None if val is None or val != val else val

    def begin(self):
        if self._dev:
            self._dev.start_measurement()
        else:
            self.s.start()

    def read(self, timeout_s=30):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if self._dev:
                    if self._dev.read_data_ready():
                        v = self._dev.read_measured_values()
                        return {
                            "pm1": self._phys(v.mass_concentration_1p0),
                            "pm25": self._phys(v.mass_concentration_2p5),
                            "pm4": self._phys(v.mass_concentration_4p0),
                            "pm10": self._phys(v.mass_concentration_10p0),
                            "rh": self._phys(v.ambient_humidity),
                            "tc": self._phys(v.ambient_temperature),
                            "voc": self._phys(v.voc_index),
                            "nox": self._phys(v.nox_index),
                        }
                elif self.s.data_ready():
                    return self.s.read_values()
            except OSError:
                pass
            time.sleep(0.5)
        return None

    def stop(self):
        if self._dev:
            self._dev.stop_measurement()
        else:
            self.s.stop()


def detect(i2c):
    """Scan the bus and return a wrapped driver, or None."""
    while not i2c.try_lock():
        pass
    try:
        found = i2c.scan()
    finally:
        i2c.unlock()
    print("I2C:", [hex(a) for a in found])
    try:
        if 0x62 in found:
            return Scd4x(i2c)
        if 0x61 in found:
            return Scd30(i2c)
        if 0x6B in found:
            return Sen6x(i2c)
        if 0x69 in found:
            return Sen5x(i2c)
    except (ImportError, OSError, RuntimeError) as exc:
        print("sensor init failed:", exc)
    return None
