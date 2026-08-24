#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
gen_sample_data.py - generate a realistic multi-day sample dataset into
webapp/sample/ for demoing the analyzer (load with https://.../?demo=1).

Scenario ("my dehumidifier stopped over the last couple of days"):
  * day -2: everything normal (local SEN66 + a 'bedroom' SCD4x node)
  * day -1: 4h data gap in the early hours (power blip), then the
    dehumidifier fails ~10:00 - humidity and CO2 climb
  * today:  fully out of spec and still climbing (ongoing episode);
    bedroom node battery also sagging below 3.5V

Data matches the collector CSV schema exactly:
  ts,src,tc,rh,co2,pm1,pm25,pm4,pm10,voc,nox,vb,flags
"""

import json
import math
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "webapp", "sample"))
HEADER = "ts,src,tc,rh,co2,pm1,pm25,pm4,pm10,voc,nox,vb,flags\n"
STEP = 120  # one record every 2 min


def day_start(days_ago):
    now = time.time()
    t = time.gmtime(now - days_ago * 86400)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, 0)))


def f(v, nd=1):
    return "" if v is None else ("%.*f" % (nd, v))


def rows_for(ts0, ts1, fail_from=None):
    """Yield (ts, local_row, bedroom_row). fail_from: epoch when dehum died."""
    out = []
    for ts in range(ts0, ts1, STEP):
        h = (ts - ts0) / 3600.0
        # local room (SEN66): gentle daily rhythm
        tc = 20.5 + 1.8 * math.sin(h / 24 * 2 * math.pi * 2)
        rh = 46 + 4 * math.sin(h / 6)
        co2 = 580 + 140 * math.sin(h / 4) + 60 * math.sin(h)
        pm25 = 4 + 1.2 * math.sin(h / 3)
        voc = 95 + 10 * math.sin(h / 5)
        if fail_from and ts >= fail_from:
            fh = (ts - fail_from) / 3600.0  # hours since failure
            rh = min(88, rh + fh * 1.9)
            co2 = min(2600, co2 + fh * 75)
            tc += fh * 0.06
            voc += fh * 3
        local = (tc, rh, co2, pm25, voc)
        # bedroom node (SCD4x): follows the house with a lag, battery sags
        age_days = (ts - day_start(2)) / 86400.0
        vb = 3.92 - age_days * 0.22
        btc = tc - 1.2
        brh = rh + 3
        bco2 = co2 * 0.85 + 80
        bedroom = (btc, brh, bco2, vb)
        out.append((ts, local, bedroom))
    return out


def write_day(day_ts0, ts_end, fail_from, path):
    lines = [HEADER]
    for ts, (tc, rh, co2, pm25, voc), (btc, brh, bco2, vb) in rows_for(
            day_ts0, ts_end, fail_from):
        lines.append("%d,local,%s,%s,%s,,%s,,,%s,1,,0\n" % (
            ts, f(tc), f(rh), f(co2, 0), f(pm25), f(voc, 0)))
        if ts % 300 < STEP:  # node reports every ~5 min
            lines.append("%d,bedroom,%s,%s,%s,,,,,,,%s,0\n" % (
                ts, f(btc), f(brh), f(bco2, 0), f(vb, 3)))
    with open(path, "w", newline="") as fh:
        fh.writelines(lines)


def main():
    os.makedirs(OUT, exist_ok=True)
    now = int(time.time())
    d2, d1, d0 = day_start(2), day_start(1), day_start(0)
    fail_from = d1 + 10 * 3600  # dehumidifier dies day-1 10:00
    days = []
    for ts0, ts1, gap in (
        (d2, d1, None),
        (d1, d0, (d1 + 3 * 3600, d1 + 7 * 3600)),  # 4h power blip
        (d0, min(now, d0 + 86400), None),
    ):
        t = time.gmtime(ts0 + 3600)
        day = "%04d-%02d-%02d" % (t.tm_year, t.tm_mon, t.tm_mday)
        path = os.path.join(OUT, day + ".csv")
        if gap:
            write_day(ts0, gap[0], fail_from, path)
            tmp = path + ".part"
            write_day(gap[1], ts1, fail_from, tmp)
            with open(path, "a", newline="") as out_fh, open(tmp) as in_fh:
                in_fh.readline()  # skip header
                out_fh.write(in_fh.read())
            os.remove(tmp)
        else:
            write_day(ts0, ts1, fail_from, path)
        days.append(day)
        print("wrote", path)
    with open(os.path.join(OUT, "days.json"), "w") as fh:
        json.dump(days, fh)
    print("wrote days.json:", days)


if __name__ == "__main__":
    main()
