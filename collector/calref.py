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
    """Epoch of the next hour:minute in local time (tz offset in hours)."""
    off = int(tz_offset_h * 3600)
    local = now_epoch + off
    day_start = local - (local % 86400)
    target = day_start + hour * 3600 + minute * 60
    if target <= local + 60:
        target += 86400
    return target - off
