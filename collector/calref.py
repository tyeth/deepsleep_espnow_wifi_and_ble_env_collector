# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
calref - shared reference-calibration logic (identical copy in collector/
and node/).

Project policy: automatic self calibration is OFF on every sensor, so the
ONLY correction a CO2 sensor ever gets is the user-run reference
calibration. That makes the reference itself the whole story: the sensor
must sit in genuinely fresh air for a stability window before the forced
recalibration (FRC) is written. Urban outdoor CO2 is closest to the
global background (~420 ppm) between 04:00 and 05:00 local, when traffic
and heating are at their minimum -- hence the scheduled window.

evaluate() is the gate both the hub (SEN66) and nodes run on the window's
samples before touching the sensor.
"""

STEP1_GUIDANCE = (
    "CO2 reference calibration for %(src)s -- STEP 1 of 2 armed, nothing "
    "changed yet. "
    "SETUP: automatic self-calibration is OFF on every sensor (project "
    "policy), so this manual reference is the ONLY correction the sensor "
    "gets -- do it properly. Put the sensor OUTSIDE (shaded, sheltered from "
    "wind and rain) or right at a wide-open window, away from people, "
    "vents, plants and traffic, and keep it still for the whole window. "
    "POWER: the sensor stays awake measuring for the full window -- a node "
    "needs USB power or a well-charged battery (>= %(min_v).2f V; a 60 min "
    "window costs roughly 5-8%% of a 500 mAh cell) and the hub must stay "
    "powered. "
    "TIMING: outdoor CO2 is nearest the ~%(target)d ppm background between "
    "04:00 and 05:00 local in urban areas, so step 2 defaults to the NEXT "
    "04:00 with a %(dur_min)d-minute window (when='4am'). Use when='now' "
    "(%(now_min)d min) only if you are genuinely outdoors in fresh air. "
    "Calibrating indoors WILL mis-calibrate the sensor. "
    "Optional: dry=true runs the window and the stability check but never "
    "writes the calibration -- a safe rehearsal."
)

ASC_GUIDANCE = (
    "ALTERNATIVE (mode='asc'): let the sensor's own automatic "
    "self-calibration do the job. Step 2 with mode='asc' switches ASC ON, "
    "leaves it on for %(asc_h)d h (default; SCD4x needs ~44 h of continuous "
    "operation for its first ASC adjustment, SCD30 about a week) and then "
    "switches it OFF again so the no-ASC policy still holds afterwards. "
    "WARNING -- read before choosing this: ASC assumes the LOWEST CO2 the "
    "sensor sees during that period IS fresh air (~%(target)d ppm). If it "
    "never sees real fresh air it will calibrate itself WRONG, so keep the "
    "room well ventilated for the whole %(asc_h)d h -- window wide open at "
    "least overnight (6-8 h) every night of the period, ideally the sensor "
    "on the sill. The sensor measures continuously the whole time: a node "
    "stays awake for %(asc_h)d h (light-sleeping between reads) -- that is "
    "USB power only, never battery. The before/after readings are reported "
    "so you can see whether it moved; a shorter window (duration_s) is "
    "allowed but may simply not trigger an adjustment."
)

# stability window considered at the end of the measurement (seconds)
STABLE_TAIL_S = 15 * 60
MIN_SAMPLES = 6


def _median(vals):
    vals = sorted(vals)
    n = len(vals)
    if not n:
        return None
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def evaluate(samples, target_ppm, max_spread_ppm=60, tail_s=STABLE_TAIL_S):
    """samples: list of (epoch_or_monotonic_s, co2_ppm). Returns
    (ok, ref_ppm, spread_ppm, reason). ok=True means the sensor sat in
    stable, plausibly-fresh air and the FRC may be written."""
    pts = [(t, v) for t, v in samples if v is not None and v > 0]
    if len(pts) < MIN_SAMPLES:
        return False, None, None, "too few samples (%d)" % len(pts)
    t_end = pts[-1][0]
    tail = [v for t, v in pts if t_end - t <= tail_s] or [v for _, v in pts]
    ref = _median(tail)
    spread = max(tail) - min(tail)
    if spread > max_spread_ppm:
        return False, ref, spread, "unstable (%d ppm spread)" % spread
    # Deliberately loose: a drifted sensor reading real outdoor air HIGH is
    # exactly what FRC exists to fix, and by reading alone that is
    # indistinguishable from stale indoor air. This only catches gross
    # misuse (closed room, ~900+); the 04:00 schedule + the step-1 guide
    # carry the real protection, and 'ref' is reported so the user can
    # judge (bench dry run indoors: 568 ppm passed -- would have been a
    # ~150 ppm mis-calibration if written).
    if ref > target_ppm + 250:
        return False, ref, spread, "not fresh air (%d ppm)" % ref
    if ref < target_ppm - 200:
        return False, ref, spread, "implausibly low (%d ppm)" % ref
    return True, ref, spread, ""


def next_local_time(now_epoch, tz_offset_h, hour=4, minute=0):
    """Epoch of the next hour:minute in local time (tz offset in hours).

    `now_epoch` is UTC, and so is the answer -- the offset goes in and
    comes back out again. Device clocks in this project hold UTC and
    nothing else; see offset_s() for where the offset comes from.
    """
    off = int(tz_offset_h * 3600)
    local = now_epoch + off
    day_start = local - (local % 86400)
    target = day_start + hour * 3600 + minute * 60
    if target <= local + 60:
        target += 86400
    return target - off


def offset_s(config):
    """(seconds east of UTC, where that came from) for a config dict.

    The clock is UTC. This is the separate, presentation-only quantity
    that turns it into something a person reads: the hub's eInk clock
    line, and scheduling a calibration for 04:00 local. It never moves a
    stored timestamp.

    Precedence, and the reason for it:

    * `timezone_offset_h` -- an explicit override, in hours and allowed to
      be fractional (India +5.5, Nepal +5.75, Chatham +12.75). **Absent by
      default**: config.json ships it under an `_`-prefixed name, which is
      how you write a commented-out field in a format with no comments.
      Rename the key to switch it on.
    * else `tz_offset_min_learned` -- whatever the last browser to sync
      the clock said its own offset was, remembered across reboots. A
      phone standing in front of the hub knows the local time better than
      a config file written months ago in another country, and it knows
      whether summer time is in force, which nothing else here does.
    * else UTC. That is what an NTP-only hub with no browser and no
      override gets: a clock that is right, and an eInk that says UTC.

    Returns seconds rather than hours so callers cannot lose Nepal to
    integer division. Never raises: it is called from the display
    refresh, from the status poll and from the clock-sync handler, and a
    junk value in a config file must not take any of those down.
    """
    over = _minutes(config.get("timezone_offset_h"), 60, "timezone_offset_h")
    if over is not None:
        return over * 60, "config"
    learned = _minutes(config.get("tz_offset_min_learned"), 1,
                       "tz_offset_min_learned")
    if learned is not None:
        return learned * 60, "browser"
    return 0, "utc"


# Widest real-world zones are UTC-12 (Baker Island) to UTC+14 (Kiritimati).
# Anything outside that -- from a config file or off the network -- is a
# bug, a joke, or milliseconds in the wrong field.
TZ_MIN_MINUTES = -12 * 60
TZ_MAX_MINUTES = 14 * 60


def tz_minutes_ok(mins):
    return TZ_MIN_MINUTES <= mins <= TZ_MAX_MINUTES


def _minutes(raw, scale, what):
    """raw * scale as whole minutes, or None if it is not a usable offset.

    One funnel for every way a number can arrive and not be one. JSON
    brings all of them: `true` (which is 1 to Python, and never a
    timezone), `1e999` (which is `inf`, and raises OverflowError rather
    than ValueError on the way to int), a string, a list, NaN. And a
    value that is a fine number but not a zone anyone lives in.
    """
    if raw is None or isinstance(raw, bool):
        if isinstance(raw, bool):
            print("config: %s is a boolean, not an offset:" % what, raw)
        return None
    try:
        mins = int(float(raw) * scale)
    except (TypeError, ValueError, OverflowError):
        print("config: %s is not a number:" % what, raw)
        return None
    if not tz_minutes_ok(mins):
        print("config: %s is outside UTC-12..UTC+14:" % what, raw)
        return None
    return mins


def learn_tz(config, raw):
    """Take a client's claimed UTC offset. Returns (minutes, changed).

    `raw` is minutes east of UTC as the browser reports it
    (`-new Date().getTimezoneOffset()`), or None when the client did not
    say -- an older page, or `time <epoch>` typed at a BLE console.

    `changed` is what decides whether the caller writes config.json. A
    clock sync happens on every page connect and a flash write per
    connect is wear for nothing; the offset itself changes twice a year.
    Storing it in `config` rather than returning it keeps one source of
    truth for offset_s(), which is the only thing that reads it.
    """
    mins = _minutes(raw, 1, "tz_offset_min")
    if mins is None:
        return None, False
    if mins == config.get("tz_offset_min_learned"):
        return mins, False
    config["tz_offset_min_learned"] = mins
    return mins, True
