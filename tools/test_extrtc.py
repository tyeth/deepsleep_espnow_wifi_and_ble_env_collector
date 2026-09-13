# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""Host-side checks for extrtc (no hardware, no CircuitPython).

    python tools/test_extrtc.py

The parts worth testing off the bench are the ones that are pure logic and
easy to get quietly wrong:

  * the PCF85063A register map -- BCD both ways, the OS flag in bit 7 of
    the seconds register, the STOP-bit dance around a write, and the fact
    that seconds live at 0x04 and not at 0x02;
  * auto-detection across two chips that share address 0x51, which is the
    whole reason the register map above has to be exactly right;
  * sync(), which decides which of two clocks is believed. Its four cases
    are the difference between a hub that recovers its own time at boot
    and one that overwrites a good RTC with 2000-01-01.

The fake bus below answers the way the real chips do, including PCF8563's
different layout -- a detector that cannot tell them apart passes nothing
here.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))

FAILURES = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILURES.append(name)


# --------------------------------------------------------------------------
# A stand-in for CircuitPython's `rtc`, which extrtc.sync() imports. The
# system clock is faked too (see _now below) so a test can put the board at
# 2000-01-01 without touching the machine running it.
# --------------------------------------------------------------------------
class _FakeRTCModule:
    class RTC:
        set_to = None

        @property
        def datetime(self):
            return time.localtime(_now[0])

        @datetime.setter
        def datetime(self, st):
            _FakeRTCModule.RTC.set_to = time.mktime(st)
            _now[0] = _FakeRTCModule.RTC.set_to


_now = [0]
sys.modules["rtc"] = _FakeRTCModule

import extrtc  # noqa: E402

_real_time = time.time
time.time = lambda: _now[0]
extrtc.time = time


def _bcd(n):
    return (n // 10) << 4 | (n % 10)


class FakeBus:
    """Just enough busio.I2C for the drivers under test."""

    def __init__(self, devices):
        self.devices = devices          # {address: register list}
        self.locked = False
        self.writes = 0
        self.log = []                   # [(addr, bytes)] in order

    def try_lock(self):
        assert not self.locked, "bus lock not released"
        self.locked = True
        return True

    def unlock(self):
        self.locked = False

    def scan(self):
        return sorted(self.devices)

    def writeto(self, addr, buf):
        assert self.locked, "write without the bus lock"
        if addr not in self.devices:
            raise OSError("no device at 0x%02X" % addr)
        regs = self.devices[addr]
        reg = buf[0]
        self.writes += 1
        self.log.append((addr, bytes(buf)))
        for i, b in enumerate(buf[1:]):
            regs[(reg + i) % len(regs)] = b

    def writeto_then_readfrom(self, addr, out, buf):
        assert self.locked, "read without the bus lock"
        if addr not in self.devices:
            raise OSError("no device at 0x%02X" % addr)
        regs = self.devices[addr]
        reg = out[0]
        for i in range(len(buf)):
            buf[i] = regs[(reg + i) % len(regs)]


def pcf85063a_regs(st=None, os_flag=False, hours12=False):
    """A PCF85063A register file: Control_1 at 0x00, time from 0x04.

    `st=None` is the power-on state from the datasheet -- OS set, and
    Days/Months at 0x01 rather than 0x00, which matters: it means a
    never-set chip reads as a perfectly well-formed 2000-01-01 and cannot
    be rejected on the shape of its registers alone.
    """
    regs = [0] * 17
    if st is None:
        regs[0x04] = 0x80 if os_flag else 0x00
        regs[0x07] = _bcd(1)            # power-on Days is 1
        regs[0x09] = _bcd(1)            # power-on Months is 1
        return regs
    regs[0x04] = _bcd(st[5]) | (0x80 if os_flag else 0)
    regs[0x05] = _bcd(st[4])
    if hours12:
        regs[0x00] |= 0x02              # Control_1 bit 1: 12-hour mode
        hour = st[3] % 12 or 12
        regs[0x06] = _bcd(hour) | (0x20 if st[3] >= 12 else 0)
    else:
        regs[0x06] = _bcd(st[3])
    regs[0x07] = _bcd(st[2])
    regs[0x08] = st[6] % 7 if st[6] >= 0 else 0
    regs[0x09] = _bcd(st[1])
    regs[0x0A] = _bcd(st[0] % 100)
    return regs


def pcf8563_regs(st, alarm=True):
    """A PCF8563 register file: time from 0x02. Same address, other map.

    `alarm=True` is the realistic default, not an edge case: the alarm
    registers at 0x09-0x0C are undefined at power-on and read 0x80|BCD
    once anything has set an alarm. Through the PCF85063A map those two
    land on *months* and *years* -- which is how a PCF8563 came to be
    identified as a PCF85063A reading a flawless 2089.
    """
    regs = [0] * 16
    regs[0x02] = _bcd(st[5])
    regs[0x03] = _bcd(st[4])
    regs[0x04] = _bcd(st[3])
    regs[0x05] = _bcd(st[2])
    regs[0x06] = st[6] % 7 if st[6] >= 0 else 0
    regs[0x07] = _bcd(st[1])
    regs[0x08] = _bcd(st[0] % 100)
    if alarm:
        regs[0x09] = 0x80 | _bcd(5)     # minute alarm, enabled
        regs[0x0A] = 0x80 | _bcd(9)     # hour alarm, enabled
    return regs


def install_fake_lib(name, cls_name, reg_map, lost_attr="lost_power"):
    """Register a stand-in Adafruit driver so _lib() has something to find.

    The real libraries are not installed on a host, so without this the
    0x68 candidates, the dotted-import walk in _lib() and the per-chip
    lost-power attribute are all untested.
    """
    class Dev:
        def __init__(self, i2c):
            self.i2c = i2c

        def _regs(self):
            return self.i2c.devices[0x68]

        @property
        def datetime(self):
            r = self._regs()
            return time.struct_time((
                _unbcd(r[reg_map + 6]) + 2000, _unbcd(r[reg_map + 5] & 0x1F),
                _unbcd(r[reg_map + 4] & 0x3F), _unbcd(r[reg_map + 2] & 0x3F),
                _unbcd(r[reg_map + 1] & 0x7F), _unbcd(r[reg_map] & 0x7F),
                -1, -1, -1))

        @datetime.setter
        def datetime(self, st):
            r = self._regs()
            for off, val in ((0, _bcd(st[5])), (1, _bcd(st[4])),
                             (2, _bcd(st[3])), (4, _bcd(st[2])),
                             (5, _bcd(st[1])), (6, _bcd(st[0] % 100))):
                r[reg_map + off] = val
            setattr(mod_cls, lost_attr, False)

    mod = type(sys)(name)
    setattr(Dev, lost_attr, False)
    mod_cls = Dev
    setattr(mod, cls_name, Dev)
    sys.modules[name] = mod
    return Dev


def _unbcd(v):
    return (v & 0x0F) + 10 * (v >> 4)


WHEN = 1789305045          # 2026-09-13 09:10:45 UTC
UNSET = 946684800          # 2000-01-01, a board with no clock at all


def main():
    print("PCF85063A register map")
    st = time.localtime(WHEN)
    bus = FakeBus({0x51: pcf85063a_regs(st)})
    dev = extrtc.PCF85063A(bus)
    check("reads back the time it was given",
          extrtc._epoch_of(dev.datetime) == WHEN)
    check("clear OS means power was not lost", dev.lost_power is False)
    check("building the driver writes NOTHING (0x51 may be an EEPROM)",
          bus.writes == 0)

    later = WHEN + 4000
    bus.log = []
    dev.datetime = time.localtime(later)
    check("a write round-trips", extrtc._epoch_of(dev.datetime) == later)
    ctrl_writes = [b for a, b in bus.log if b[0] == 0x00]
    time_writes = [i for i, (a, b) in enumerate(bus.log) if b[0] == 0x04]
    check("STOP is SET before the time registers are touched",
          len(ctrl_writes) >= 1 and ctrl_writes[0][1] & 0x20 != 0
          and time_writes and bus.log.index((0x51, ctrl_writes[0])) <
          time_writes[0])
    check("STOP is cleared again afterwards",
          bus.devices[0x51][0x00] & 0x20 == 0)
    check("24-hour mode is selected by the write",
          bus.devices[0x51][0x00] & 0x02 == 0)

    print("PCF85063A left in 12-hour mode by somebody else")
    for hour in (0, 1, 11, 12, 13, 23):
        parts = [2026, 6, 15, hour, 34, 56, -1, -1, -1]
        want = time.struct_time(tuple(parts))
        bus = FakeBus({0x51: pcf85063a_regs(want, hours12=True)})
        got = extrtc.PCF85063A(bus).datetime
        check("12-hour %02d:00 reads back as %02d" % (hour, hour),
              got[3] == hour)

    print("PCF85063A that lost power")
    bus = FakeBus({0x51: pcf85063a_regs(st, os_flag=True)})
    dev = extrtc.PCF85063A(bus)
    r = extrtc.ExternalRTC("pcf85063a", 0x51, dev)
    check("OS set is reported as lost power", r.lost_power is True)
    check("and its time is refused even though it parses",
          r.read_epoch() is None)
    check("writing clears OS",
          r.write_epoch(WHEN) and r.lost_power is False)
    check("and then the time is trusted", r.read_epoch() == WHEN)

    print("every field: BCD tens must survive (the 10-vs-16 bug)")
    # Built as a struct_time, not from an epoch: the chip holds whatever
    # the system clock reads, with no timezone anywhere in the story, and
    # going via the host's localtime() would only test the host's TZ.
    for field, idx, values in (
        ("hour", 3, (0, 9, 10, 13, 19, 20, 23)),
        ("minute", 4, (0, 9, 10, 30, 59)),
        ("second", 5, (0, 9, 10, 45, 59)),
        ("day", 2, (1, 9, 10, 28, 31)),
        ("month", 1, (1, 9, 10, 12)),
        ("year", 0, (2000, 2009, 2010, 2026, 2099)),
    ):
        for value in values:
            parts = [2026, 6, 15, 12, 34, 56, -1, -1, -1]
            parts[idx] = value
            want = time.struct_time(tuple(parts))
            bus = FakeBus({0x51: pcf85063a_regs(want)})
            got = extrtc.PCF85063A(bus).datetime
            check("%s=%d reads back as %d" % (field, value, value),
                  got[idx] == value)

    print("bad BCD is not a time")
    # 0x1F used to decode as 25 and sail through the range checks. A
    # nibble above 9 means we are reading some other chip's register.
    check("a nibble above 9 is rejected", extrtc._bcd2bin(0x1F) == -1)
    check("an alarm register's enable bit is rejected",
          extrtc._bcd2bin(0x8F) == -1)
    check("real BCD still decodes", extrtc._bcd2bin(0x59) == 59)
    check("a date decades away is not believed", extrtc._epoch_of(
        time.struct_time((2089, 5, 9, 6, 13, 14, -1, -1, -1))) is None)

    print("auto-detect at a shared address")
    bus = FakeBus({0x51: pcf85063a_regs(st)})
    r = extrtc.attach(bus)
    check("finds the PCF85063A", r is not None and r.chip == "pcf85063a")
    check("and its time", r.read_epoch() == WHEN)

    # The regression that started this: a PCF8563 with an alarm set reads,
    # through the PCF85063A map, as a flawless 2089 -- so it was claimed,
    # and the next sync() wrote seven bytes over its time registers.
    bus = FakeBus({0x51: pcf8563_regs(st, alarm=True)})
    before = list(bus.devices[0x51])
    r = extrtc.attach(bus)
    check("does NOT claim an alarmed PCF8563 is a PCF85063A",
          r is None or r.chip != "pcf85063a")
    check("and does not write to it while deciding",
          bus.devices[0x51] == before)
    bus = FakeBus({0x51: pcf8563_regs(st, alarm=False)})
    r = extrtc.attach(bus)
    check("nor a freshly-reset one",
          r is None or r.chip != "pcf85063a")

    print("auto-detect on a chip nobody has ever set")
    # The case that would otherwise be permanent: registers hold no date,
    # so the "is this the right register map" test cannot pass, and a
    # rejected chip never gets written -- because writing it is what a
    # clock sync does to a chip that IS attached.
    bus = FakeBus({0x51: pcf85063a_regs(None, os_flag=True)})
    r = extrtc.attach(bus)
    check("a virgin PCF85063A is still attached",
          r is not None and r.chip == "pcf85063a")
    check("...reporting it has no time", r is not None
          and r.read_epoch() is None and r.lost_power is True)
    _now[0] = WHEN
    extrtc.sync(r)
    check("...so the first sync sets it", r.read_epoch() == WHEN)

    print("auto-detect with nothing to find")
    check("empty bus", extrtc.attach(FakeBus({})) is None)
    check("a sensor at a non-RTC address",
          extrtc.attach(FakeBus({0x62: [0] * 8})) is None)
    check("no bus at all (node in sim mode)", extrtc.attach(None) is None)

    print("config names the chip")
    # Power-on state: OS set, Days/Months 0x01 -- i.e. a well-formed
    # 2000-01-01 that only the OS flag says not to believe.
    bus = FakeBus({0x51: pcf85063a_regs(None, os_flag=True)})
    r = extrtc.attach(bus, "pcf85063a")
    check("a named, never-set chip is still attached", r is not None)
    check("...so sync() can be the thing that sets it",
          r is not None and r.read_epoch() is None)
    check("'off' skips the bus", extrtc.attach(bus, "off") is None)
    check("an unknown name is refused, not guessed",
          extrtc.attach(bus, "ds1234") is None)
    # JSON has booleans and people type them into config files.
    check("'rtc': false means off", extrtc.attach(bus, False) is None)
    check("'rtc': true means auto", extrtc.attach(
        FakeBus({0x51: pcf85063a_regs(time.localtime(WHEN))}), True)
        is not None)
    check("'rtc': null means auto", extrtc.attach(
        FakeBus({0x51: pcf85063a_regs(time.localtime(WHEN))}), None)
        is not None)

    print("a library-backed chip at 0x68")
    install_fake_lib("adafruit_ds3231", "DS3231", 0x00)
    ds1307 = install_fake_lib("adafruit_ds1307", "DS1307", 0x00,
                              lost_attr="disable_oscillator")
    regs = [0] * 16
    for off, val in ((0, _bcd(st[5])), (1, _bcd(st[4])), (2, _bcd(st[3])),
                     (4, _bcd(st[2])), (5, _bcd(st[1])),
                     (6, _bcd(st[0] % 100))):
        regs[off] = val
    bus = FakeBus({0x68: regs})
    r = extrtc.attach(bus)
    check("_lib() imports and builds it", r is not None and r.chip == "ds3231")
    check("and reads its time", r is not None and r.read_epoch() == WHEN)
    # A DS1307 with its oscillator halted sits at a frozen but entirely
    # plausible time; only the driver's own flag says not to believe it.
    ds1307.disable_oscillator = True
    r = extrtc.attach(bus, "ds1307")
    check("a halted DS1307 is not believed",
          r is not None and r.read_epoch() is None)
    check("...via the right attribute for that chip, not lost_power",
          r.lost_attr == "disable_oscillator")
    ds1307.disable_oscillator = False

    print("sync(trust='chip'): the chip is the better clock at boot")
    _now[0] = UNSET
    bus = FakeBus({0x51: pcf85063a_regs(time.localtime(WHEN))})
    r = extrtc.attach(bus)
    _now[0] = UNSET                      # attach() must not have moved it
    msg = extrtc.sync(r)
    check("system clock is set from the chip", _now[0] == WHEN)
    check("and says so: %r" % msg, "system clock set from" in msg)

    # The one the review caught: across a week of deep sleeps the ESP32's
    # clock drifts minutes (internal RC on RTC_SLOW_CLK) and the coin cell
    # does not. A node out of hub range syncs every wake; the naive
    # "system clock wins if plausible" rule spent that week writing the
    # drift onto the chip and ended with two equally wrong clocks.
    _now[0] = WHEN + 240                 # a wake's worth of ESP32 drift
    bus = FakeBus({0x51: pcf85063a_regs(time.localtime(WHEN))})
    r = extrtc.attach(bus)
    _now[0] = WHEN + 240
    before = bus.writes
    msg = extrtc.sync(r)
    check("a drifting system clock is corrected FROM the chip",
          _now[0] == WHEN)
    check("and the chip is not written", bus.writes == before)

    print("sync(trust='system'): NTP / a browser / a hub reply")
    _now[0] = WHEN
    bus = FakeBus({0x51: pcf85063a_regs(None, os_flag=True)})
    r = extrtc.attach(bus, "pcf85063a")
    msg = extrtc.sync(r, "system")
    check("the chip is written", r.read_epoch() == WHEN)
    check("and says so: %r" % msg, "rtc set from system clock" in msg)

    _now[0] = WHEN
    bus = FakeBus({0x51: pcf85063a_regs(time.localtime(WHEN - 90))})
    r = extrtc.attach(bus)
    _now[0] = WHEN
    extrtc.sync(r, "system")
    check("a drifted chip is corrected, not the system clock",
          r.read_epoch() == WHEN and _now[0] == WHEN)

    _now[0] = UNSET
    bus = FakeBus({0x51: pcf85063a_regs(time.localtime(WHEN))})
    r = extrtc.attach(bus)
    _now[0] = UNSET
    before = bus.writes
    msg = extrtc.sync(r, "system")
    check("an unset system clock never overwrites a good chip",
          bus.writes == before and r.read_epoch() == WHEN)
    check("and says so: %r" % msg, "no time to give" in msg)

    print("sync: both good and in step")
    _now[0] = WHEN
    bus = FakeBus({0x51: pcf85063a_regs(time.localtime(WHEN))})
    r = extrtc.attach(bus)
    before = bus.writes
    for trust in ("chip", "system"):
        msg = extrtc.sync(r, trust)
        check("trust=%s writes nothing" % trust, bus.writes == before)
        check("...and says so: %r" % msg, msg.startswith("agree"))

    print("sync: a second inside the slop is not worth a write")
    _now[0] = WHEN
    bus = FakeBus({0x51: pcf85063a_regs(time.localtime(WHEN - 1))})
    r = extrtc.attach(bus)
    _now[0] = WHEN
    before = bus.writes
    extrtc.sync(r, "system")
    check("no write", bus.writes == before)
    extrtc.sync(r)
    check("and the system clock is not nudged either", _now[0] == WHEN)

    print("sync: neither clock knows anything")
    _now[0] = UNSET
    bus = FakeBus({0x51: pcf85063a_regs(None, os_flag=True)})
    r = extrtc.attach(bus, "pcf85063a")
    msg = extrtc.sync(r)
    check("the system clock is left alone", _now[0] == UNSET)
    check("and says so: %r" % msg, "no time yet" in msg)
    check("no rtc at all is not an error", extrtc.sync(None) == "no rtc")

    print("status payload")
    _now[0] = WHEN
    bus = FakeBus({0x51: pcf85063a_regs(time.localtime(WHEN))})
    st_none = extrtc.status(None)
    check("no rtc still reports the clock",
          st_none["rtc"] is None and st_none["synced"] is True)
    s = extrtc.status(extrtc.attach(bus))
    check("names the chip", s["rtc"] == "pcf85063a" and s["addr"] == 0x51)
    check("reports drift", s["drift_s"] == 0)
    _now[0] = UNSET
    check("unsynced is reported as such",
          extrtc.status(None)["synced"] is False)

    print("collector and node copies are identical")
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "..", "collector", "extrtc.py"), "rb") as f:
        a = f.read()
    with open(os.path.join(here, "..", "node", "extrtc.py"), "rb") as f:
        b = f.read()
    check("collector/extrtc.py == node/extrtc.py", a == b)

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
