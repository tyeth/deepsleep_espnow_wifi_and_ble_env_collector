# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
sensors_local - the collector's own Sensirion SEN66/SEN6x on I2C.

Automatic self calibration (ASC) is forced OFF at startup per project policy;
forced CO2 recalibration is only performed via the explicit two-step user
workflow (see code.py / the API).
"""

import adafruit_sen6x


class LocalSensor:
    def __init__(self, i2c):
        self.sensor = adafruit_sen6x.SEN66(i2c)
        self.product = self.sensor.product_name
        self.serial = self.sensor.serial_number
        try:
            # Project policy: no automatic self calibration on any sensor.
            self.sensor.co2_automatic_self_calibration = False
        except (OSError, AttributeError) as exc:
            print("could not disable ASC:", exc)
        self.sensor.start_measurement()
        self.read_errors = 0

    def read(self):
        """Return an envproto-keyed metric dict, or None if not ready/failed."""
        try:
            if not self.sensor.data_ready:
                return None
            self.sensor.check_sensor_errors()
            d = self.sensor.all_measurements()
        except (OSError, RuntimeError) as exc:
            self.read_errors += 1
            print("SEN66 read failed:", exc)
            return None
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

    def force_recalibration(self, target_ppm):
        """Run forced CO2 recalibration. Returns the correction (ppm) or None.

        Caller is responsible for the user workflow: the sensor must have been
        in fresh air (~target ppm) and measuring for at least 3 minutes first.
        """
        correction = self.sensor.force_co2_recalibration(target_ppm)
        return correction
