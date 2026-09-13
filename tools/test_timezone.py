# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""Host-side checks for the timezone rules (no hardware, no CircuitPython).

    python tools/test_timezone.py

The one invariant worth defending: **the device clock holds UTC**, and the
timezone offset is a separate, presentation-only quantity. It used to not
be. NTP put local time on the clock (`adafruit_ntp(tz_offset=...)`) while a
browser syncing the same hub put UTC on it, so the same hub told two
different stories about when a reading happened depending on which source
got there first -- and once an RTC is fitted, whichever one wrote last is
the one that survives the power cut.

What is checked here is the arithmetic that replaced it: which offset a
config resolves to and why (`calref.offset_s`), and that turning UTC into
"04:00 local" and back is exact for every offset a real zone uses --
including the ones that are not whole hours, which is where a tidy-looking
`int(hours)` quietly loses Nepal.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
import calref  # noqa: E402

FAILURES = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILURES.append(name)


# Offsets that exist in the world, in minutes east of UTC. The fractional
# ones are the point: a zone is not always a whole number of hours.
REAL_ZONES = (
    ("UTC", 0), ("London BST", 60), ("Berlin CEST", 120),
    ("Newfoundland", -3 * 60 - 30), ("Caracas", -4 * 60),
    ("India", 5 * 60 + 30), ("Nepal", 5 * 60 + 45),
    ("Adelaide", 9 * 60 + 30), ("Chatham", 12 * 60 + 45),
    ("Kiritimati", 14 * 60), ("Baker Island", -12 * 60),
)

WHEN = 1789305045          # 2026-09-13 09:10:45 UTC


def main():
    print("offset_s: precedence")
    check("nothing set means UTC", calref.offset_s({}) == (0, "utc"))
    check("a browser's offset is used when nothing overrides it",
          calref.offset_s({"tz_offset_min_learned": 60}) == (3600, "browser"))
    check("an explicit override wins over the browser",
          calref.offset_s({"timezone_offset_h": -5,
                           "tz_offset_min_learned": 60}) == (-18000, "config"))
    check("an override of 0 still wins (it is a choice, not an absence)",
          calref.offset_s({"timezone_offset_h": 0,
                           "tz_offset_min_learned": 330}) == (0, "config"))
    check("a learned 0 is reported as the browser's, not as 'no idea'",
          calref.offset_s({"tz_offset_min_learned": 0}) == (0, "browser"))

    print("offset_s: values that are not offsets")
    # offset_s runs on the display refresh, the status poll and the clock
    # sync. None of these may raise: a junk value in a config file must
    # cost the eInk its clock line, not the hub.
    JUNK = (
        ("a word", "BST"),
        ("a boolean, which Python would otherwise read as +1", True),
        ("infinity, which raises OverflowError rather than ValueError",
         float("inf")),
        ("infinity spelled as a string", "inf"),
        ("NaN", float("nan")),
        ("a number far too large to be a zone", 1e300),
        ("a list", [5]),
    )
    for name, bad in JUNK:
        check("override: %s falls through to the browser" % name,
              calref.offset_s({"timezone_offset_h": bad,
                               "tz_offset_min_learned": 60})
              == (3600, "browser"))
    for name, bad in JUNK:
        check("learned: %s falls through to UTC" % name,
              calref.offset_s({"tz_offset_min_learned": bad}) == (0, "utc"))
    # Out of range is scale-dependent: the override is hours and the
    # learned value minutes, so 99 is nonsense as one and +1:39 as the
    # other. The units are exactly what a shared check would get wrong.
    check("an override of +99 HOURS is refused",
          calref.offset_s({"timezone_offset_h": 99}) == (0, "utc"))
    check("a learned +99 MINUTES is a real zone and is kept",
          calref.offset_s({"tz_offset_min_learned": 99}) == (99 * 60,
                                                             "browser"))
    check("a learned value in milliseconds is refused",
          calref.offset_s({"tz_offset_min_learned": 3600000}) == (0, "utc"))
    check("a string zero is still a real override",
          calref.offset_s({"timezone_offset_h": "0"}) == (0, "config"))
    check("an absent override is not junk, just absent",
          calref.offset_s({"timezone_offset_h": None,
                           "tz_offset_min_learned": 60}) == (3600, "browser"))

    print("learn_tz: what the caller writes to flash for")
    cfg = {}
    check("a first offer is learned and is a change",
          calref.learn_tz(cfg, 60) == (60, True)
          and cfg["tz_offset_min_learned"] == 60)
    check("the same offer again is NOT a change (no flash write)",
          calref.learn_tz(cfg, 60) == (60, False))
    check("a different offer is a change",
          calref.learn_tz(cfg, 120) == (120, True)
          and cfg["tz_offset_min_learned"] == 120)
    check("a client that says nothing changes nothing",
          calref.learn_tz(cfg, None) == (None, False)
          and cfg["tz_offset_min_learned"] == 120)
    check("an out-of-range offer is refused, and does not clobber",
          calref.learn_tz(cfg, 3600000) == (None, False)
          and cfg["tz_offset_min_learned"] == 120)
    check("junk off the network is refused, not raised",
          calref.learn_tz(cfg, float("inf")) == (None, False))
    check("a BLE console's string is fine",
          calref.learn_tz({}, "-330") == (-330, True))
    check("learning 0 is a real change from never having learned",
          calref.learn_tz({}, 0) == (0, True))

    print("offset_s: zones that are not whole hours")
    for name, mins in REAL_ZONES:
        got, _ = calref.offset_s({"tz_offset_min_learned": mins})
        check("%s survives as %+d min" % (name, mins), got == mins * 60)
    check("India as a fractional override, not rounded to 5",
          calref.offset_s({"timezone_offset_h": 5.5})[0] == 5 * 3600 + 1800)
    check("Nepal as a fractional override",
          calref.offset_s({"timezone_offset_h": 5.75})[0] == 5 * 3600 + 2700)

    print("tz_minutes_ok: what may arrive over the network")
    check("UTC is fine", calref.tz_minutes_ok(0))
    check("Kiritimati (+14:00) is the eastern edge", calref.tz_minutes_ok(840))
    check("Baker Island (-12:00) is the western edge",
          calref.tz_minutes_ok(-720))
    check("a minute past the eastern edge is not",
          not calref.tz_minutes_ok(841))
    check("a minute past the western edge is not",
          not calref.tz_minutes_ok(-721))
    check("milliseconds mistaken for minutes are not",
          not calref.tz_minutes_ok(3600000))

    print("next_local_time: UTC in, UTC out")
    # The contract, for any offset and any starting moment:
    #   * the answer, seen in local time, is exactly hour:minute;
    #   * it is in the future (the +60 guard stops "now" being chosen);
    #   * it is within a day, i.e. it is the NEXT one, not a later one.
    for name, mins in REAL_ZONES:
        hours = mins / 60.0
        off = mins * 60
        worst = None
        for step in range(0, 86400, 997):       # a prime: lands everywhere
            now = WHEN - (WHEN % 86400) + step
            at = calref.next_local_time(now, hours, hour=4)
            local_secs = (at + off) % 86400
            if not (local_secs == 4 * 3600
                    and now + 60 < at <= now + 86400 + 60):
                worst = (step, at, local_secs)
                break
        check("%s: every 04:00 local is a real 04:00 local" % name,
              worst is None)

    print("next_local_time: the boundary the +60 guard exists for")
    four_am = WHEN - (WHEN % 86400) + 4 * 3600
    check("a moment before 04:00 picks today's",
          calref.next_local_time(four_am - 120, 0, hour=4) == four_am)
    check("a moment after 04:00 picks tomorrow's",
          calref.next_local_time(four_am + 1, 0, hour=4) == four_am + 86400)
    check("04:00 exactly picks tomorrow's, not a window of zero length",
          calref.next_local_time(four_am, 0, hour=4) == four_am + 86400)

    print("next_local_time: the offset does not leak into the answer")
    # The bug this guards: scheduling from a clock that was ALREADY local
    # (the old NTP path) double-applied the offset, putting the window
    # hours away from 04:00. Same UTC moment, different zones, and the
    # answers must differ by exactly the difference in offsets.
    a = calref.next_local_time(WHEN, 0, hour=4)
    b = calref.next_local_time(WHEN, 5.5, hour=4)
    check("UTC and India differ by exactly 5.5 h of scheduling",
          (a - b) % 86400 == (5 * 3600 + 1800) % 86400)

    print("collector and node copies are identical")
    here = os.path.dirname(__file__)
    for name in ("calref.py", "net_ble.py", "envproto.py", "battery.py",
                 "extrtc.py"):
        with open(os.path.join(here, "..", "collector", name), "rb") as f:
            a = f.read()
        with open(os.path.join(here, "..", "node", name), "rb") as f:
            b = f.read()
        check("collector/%s == node/%s" % (name, name), a == b)

    print()
    if FAILURES:
        print("%d FAILED:" % len(FAILURES))
        for name in FAILURES:
            print("  -", name)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
