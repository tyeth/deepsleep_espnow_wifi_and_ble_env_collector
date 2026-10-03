# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
extrtc - an optional battery-backed RTC on I2C, for the hub and the node.

Both boards keep time in CircuitPython's `rtc.RTC()`, which is the SoC's
own counter: it survives a soft reload and (on ESP32) a deep sleep, and it
does not survive a power cut. Without a coin cell somewhere, a hub that
loses power logs at 2000-01-01 until a browser or NTP sets it (and then has
to relabel everything it wrote in between), and a node stashes readings the
hub cannot place. This module is that coin cell.

What it does, in one call: find the chip, and reconcile it with the system
clock in whichever direction has the better time (`sync()`).

Supported (I2C address -> driver):
  0x51  PCF85063A  built-in driver below -- no Adafruit CP library exists
  0x51  PCF8563    adafruit_pcf8563
  0x68  DS3231     adafruit_ds3231
  0x68  PCF8523    adafruit_pcf8523
  0x68  DS1307     adafruit_ds1307 -- name it; see _CANDIDATES

Only PCF85063A works with nothing installed; the rest need their library
via circup, and are here because "any RTC the user already owns" was the
point. Adding another is one row in _CANDIDATES, as long as its driver
exposes the Adafruit RTC interface (`.datetime`, ideally `.lost_power`).

**Several chips share each address**, which is a hardware fact and not
something this module can fix. Auto-detection builds each candidate for a
responding address and takes the first that is *keeping a time we would
believe* -- not merely one whose registers parse, because one chip's
registers read through another's map produce well-formed dates more often
than is comfortable (a PCF8563 with an alarm set reads, through the
PCF85063A map, as a flawless 2089). A chip that holds no such time but
raises its own lost-power flag is taken as a fallback: that is the
brand-new-coin-cell case, and the one case where refusing it would be
permanent, since a sync is what would have set it.

Even so, DS3231 and DS1307 are *indistinguishable* -- identical registers
at identical addresses -- so a DS1307 in auto mode is claimed as a DS3231
and its halted-oscillator flag is never read. Name the chip in config
(`"rtc": "ds1307"`) and none of the guessing runs.

Interface, for callers:
    r = extrtc.attach(i2c)          # or attach(i2c, "pcf85063a")
    r.chip, r.address
    r.datetime                      # time.struct_time, get and set
    r.lost_power                    # True / False / None (chip cannot say)
    extrtc.sync(r)                  # boot: the chip is the better clock
    extrtc.sync(r, "system")        # after NTP / a browser / a hub reply
"""

import time

# Same line the rest of the project draws between "a real time" and "a
# board that has just booted with no clock" (envproto, datastore, webapp).
PLAUSIBLE_EPOCH = 1700000000  # 2023-11
# ...and an upper one, which exists for detection rather than for sanity.
# A chip read through the wrong register map can land on a well-formed
# date: a PCF8563 with an alarm set reads, through the PCF85063A map, as a
# perfectly valid 2089. Nothing we would ever believe is decades away.
MAX_YEAR = 2050

# How far the system clock and the chip may disagree before a sync writes.
# A second or two is the read/write round trip and the chip's own 1 s
# resolution, not drift worth an I2C write on a battery node.
SYNC_SLOP_S = 3


def _bcd2bin(value):
    """BCD byte -> int, or -1 if it is not BCD at all.

    The -1 matters: every caller feeds this into _epoch_of, whose range
    checks then reject it. A nibble above 9 means we are reading some
    other chip's register (or an alarm register's enable bit), and the
    old silent (0x1F -> 25) answer was how a wrong map produced a
    plausible-looking time.
    """
    if (value & 0x0F) > 9 or (value >> 4) > 9:
        return -1
    return (value & 0x0F) + 10 * (value >> 4)


def _bin2bcd(value):
    return (value // 10) << 4 | (value % 10)


def _epoch_of(st):
    """struct_time -> epoch seconds, or None if it is not a real date.

    The range checks are also the chip test: registers read through the
    wrong map normally fail one of them, which is how auto-detection tells
    two chips at one address apart.
    """
    try:
        if not 2000 <= st[0] <= MAX_YEAR:
            return None
        if not 1 <= st[1] <= 12 or not 1 <= st[2] <= 31:
            return None
        if not 0 <= st[3] <= 23:
            return None
        if not 0 <= st[4] <= 59 or not 0 <= st[5] <= 59:
            return None
        return time.mktime(time.struct_time(
            (st[0], st[1], st[2], st[3], st[4], st[5], -1, -1, -1)))
    except (ValueError, OverflowError, OSError):
        return None


class PCF85063A:
    """Minimal NXP PCF85063A / PCF85063TP. Address 0x51.

    Registers: Control_1 at 0x00, then the time from 0x04 (sec, min, hour,
    day, weekday, month, year) in BCD, with seconds bit 7 = OS -- the
    oscillator stopped, so the contents are not a time anyone set.

    Note the offset. The otherwise-similar PCF8563 puts seconds at 0x02,
    which on this chip is the offset-trim register, so pointing either
    driver at the other chip reads plausible-looking nonsense. That is
    what the validation in attach() is for.
    """

    ADDR = 0x51
    _CTRL1 = 0x00
    _SECONDS = 0x04

    def __init__(self, i2c, address=ADDR):
        # Deliberately does NOT touch the chip. Auto-detection builds one
        # of these for every candidate at 0x51, and 0x51 is also where a
        # 24Cxx EEPROM or an FRAM sits: a constructor that "normalised"
        # register 0 would be rewriting a byte of somebody's memory before
        # anything had established what the device even is. Normalising
        # happens in the setter, by which point we are writing anyway.
        self.i2c = i2c
        self.address = address

    def _read(self, reg, length):
        buf = bytearray(length)
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto_then_readfrom(self.address, bytes((reg,)), buf)
        finally:
            self.i2c.unlock()
        return buf

    def _write(self, reg, data):
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.address, bytes((reg,)) + bytes(data))
        finally:
            self.i2c.unlock()

    @property
    def lost_power(self):
        return bool(self._read(self._SECONDS, 1)[0] & 0x80)

    def snapshot(self):
        """(lost_power, struct_time) from ONE bus transaction.

        Reads Control_1 through to the year in a single burst -- 11 bytes
        instead of two round trips -- because Control_1 is needed to read
        the hours at all (bit 1 selects 12-hour mode) and because the
        status poll behind /api/latest runs this on every page refresh.
        """
        b = self._read(self._CTRL1, 11)
        ctrl1, t = b[0], b[4:]
        if ctrl1 & 0x02:                  # 12-hour mode
            h12 = _bcd2bin(t[2] & 0x1F)
            hour = -1 if h12 < 0 else (h12 % 12) + (12 if t[2] & 0x20 else 0)
        else:
            hour = _bcd2bin(t[2] & 0x3F)
        return bool(t[0] & 0x80), time.struct_time((
            _bcd2bin(t[6]) + 2000 if _bcd2bin(t[6]) >= 0 else -1,   # year
            _bcd2bin(t[5] & 0x1F),        # month
            _bcd2bin(t[3] & 0x3F),        # day
            hour,
            _bcd2bin(t[1] & 0x7F),        # minute
            _bcd2bin(t[0] & 0x7F),        # second; bit 7 is OS, not time
            -1, -1, -1,                   # weekday/yearday/isdst: derived
        ))

    @property
    def datetime(self):
        return self.snapshot()[1]

    @datetime.setter
    def datetime(self, st):
        # The datasheet wants the clock stopped while the time registers
        # are written, or an internal tick lands mid-write and the chip
        # ends up holding a time that was never on either clock. Clearing
        # STOP afterwards also resets the prescaler, so the new second
        # starts here rather than up to one second late.
        #
        # This is also where 12-hour mode gets switched off (bit 1): we
        # are writing the hours in 24-hour form in the next breath, so the
        # two changes belong together. CAP_SEL (bit 0) is left alone -- it
        # describes the crystal fitted to the board, not a preference.
        ctrl1 = self._read(self._CTRL1, 1)[0] & 0xFD      # 24-hour
        self._write(self._CTRL1, bytes((ctrl1 | 0x20,)))  # STOP
        try:
            weekday = st[6]
            if weekday is None or weekday < 0:
                weekday = 0
            self._write(self._SECONDS, bytes((
                _bin2bcd(st[5]) & 0x7F,   # second; bit 7 = 0 clears OS
                _bin2bcd(st[4]),
                _bin2bcd(st[3]),
                _bin2bcd(st[2]),
                # The chip numbers weekdays from Sunday and struct_time
                # from Monday. Nothing here reads the field back (the day
                # of the week is derived from the date), so it is stored
                # as-is rather than converted; that only matters the day
                # someone wires up a weekday alarm.
                weekday % 7,
                _bin2bcd(st[1]),
                _bin2bcd(st[0] % 100),
            )))
        finally:
            self._write(self._CTRL1, bytes((ctrl1 & 0xDF,)))


def _lib(module, cls):
    """Late-import factory for a driver that may not be installed.

    Deliberately late: on the C6 an import costs RAM we are counting, and
    four RTC libraries for the one chip actually on the bus is exactly the
    kind of import the hub cannot afford.
    """
    def build(i2c, address):
        mod = __import__(module)
        for part in module.split(".")[1:]:
            mod = getattr(mod, part)
        return getattr(mod, cls)(i2c)
    return build


# (name, address, factory, "this chip's time is not to be trusted" attr).
# Order is the auto-detect preference within an address: the built-in
# driver first, so the chip we support with no dependencies wins when two
# readings look equally sane.
#
# The last field is not always called lost_power. DS1307 has no such flag
# at all -- what it can say is that its oscillator is halted (CH=1, which
# is its power-on state), and a halted DS1307 sits at a frozen but
# entirely plausible time. Reading `disable_oscillator` instead is what
# stops a hub adopting that frozen time at every power cut.
_CANDIDATES = (
    ("pcf85063a", 0x51, lambda i2c, addr: PCF85063A(i2c, addr), "lost_power"),
    ("pcf8563", 0x51, _lib("adafruit_pcf8563.pcf8563", "PCF8563"),
     "lost_power"),
    ("ds3231", 0x68, _lib("adafruit_ds3231", "DS3231"), "lost_power"),
    ("pcf8523", 0x68, _lib("adafruit_pcf8523.pcf8523", "PCF8523"),
     "lost_power"),
    ("ds1307", 0x68, _lib("adafruit_ds1307", "DS1307"), "disable_oscillator"),
)

CHIPS = tuple(c[0] for c in _CANDIDATES)


class ExternalRTC:
    """One attached chip, wrapped so callers never care which it is."""

    def __init__(self, chip, address, dev, lost_attr="lost_power"):
        self.chip = chip
        self.address = address
        self.dev = dev
        self.lost_attr = lost_attr

    @property
    def datetime(self):
        return self.dev.datetime

    @datetime.setter
    def datetime(self, st):
        self.dev.datetime = st

    @property
    def lost_power(self):
        """True, False, or None when the chip has no such flag.

        None is not False. A chip that cannot say anything leaves the
        caller with the plausibility of the time itself as the only
        evidence, and treating that silence as "power was fine" is how a
        dead cell gets believed.
        """
        try:
            return bool(getattr(self.dev, self.lost_attr))
        except (AttributeError, OSError):
            return None

    def snapshot(self, quiet=False):
        """(lost_power, epoch) in as few bus transactions as the chip allows.

        `quiet` is for the status poll, which runs on every page refresh:
        a chip that has fallen off the bus would otherwise print a line
        per poll, and drown the console it is trying to warn.
        """
        try:
            snap = getattr(self.dev, "snapshot", None)
            if snap is not None and self.lost_attr == "lost_power":
                lost, st = snap()
                return lost, (None if lost else _epoch_of(st))
            lost = self.lost_power
            if lost:
                return lost, None
            return lost, _epoch_of(self.datetime)
        except Exception as exc:
            # Broad on purpose. This runs inside the status poll behind
            # every page refresh and inside boot, and the drivers are
            # third-party: a chip that has fallen off the bus is a line on
            # the console, never a status request that fails or a hub that
            # will not start.
            if not quiet:
                print("extrtc: read failed: %s: %s" % (type(exc).__name__, exc))
            return None, None

    def read_epoch(self, quiet=False):
        """Epoch seconds from the chip, or None if it has nothing usable.

        None covers all three ways that happens: the chip says it lost
        power, the read failed, or the registers do not describe a date.
        """
        return self.snapshot(quiet)[1]

    def write_epoch(self, epoch):
        """Put epoch seconds on the chip. True if it took."""
        try:
            self.datetime = time.localtime(int(epoch))
            return True
        except (OSError, ValueError, RuntimeError, OverflowError) as exc:
            print("extrtc: write failed:", exc)
            return False


def attach(i2c, want="auto", quiet=False):
    """Find an RTC on the bus. Returns an ExternalRTC, or None.

    `want` is the config value: "auto" to detect, "off"/"none" to skip the
    bus entirely, or a chip name from CHIPS to build that one and nothing
    else. Naming it is the reliable option -- see the module docstring on
    why one address is not one chip.
    """
    if i2c is None:
        return None
    # JSON has booleans and people use them: "rtc": false is an obvious
    # way to write "off", and true an obvious way to write "on". Neither
    # has a .lower(), and `want or "auto"` quietly turned false into auto.
    if want is None or want is True:
        want = "auto"
    elif want is False:
        want = "off"
    else:
        want = str(want).lower()
    if want in ("off", "none", "no", "false", "disabled"):
        return None

    if want != "auto":
        for name, addr, build, lost_attr in _CANDIDATES:
            if name != want:
                continue
            try:
                dev = build(i2c, addr)
            except (ImportError, OSError, ValueError, RuntimeError) as exc:
                print("extrtc: %s named in config but not usable: %s"
                      % (name, exc))
                return None
            # Built as asked, and deliberately NOT validated: the user says
            # this chip is there, so a reading that looks wrong means a
            # flat cell or a clock nobody has set yet -- which sync() fixes
            # by writing to it. Rejecting it here would leave a brand-new
            # RTC permanently unused, which is the one case that matters.
            print("extrtc: %s at 0x%02X (from config)" % (name, addr))
            return ExternalRTC(name, addr, dev, lost_attr)
        print("extrtc: unknown chip %r in config; expected one of %s"
              % (want, ", ".join(CHIPS)))
        return None

    while not i2c.try_lock():
        pass
    try:
        found = i2c.scan()
    finally:
        i2c.unlock()

    running = None         # (ExternalRTC, epoch) -- a chip keeping time now
    virgin = None          # ExternalRTC that says it has never been set
    for name, addr, build, lost_attr in _CANDIDATES:
        if addr not in found:
            continue
        try:
            dev = build(i2c, addr)
            cand = ExternalRTC(name, addr, dev, lost_attr)
            lost, epoch = cand.snapshot(quiet=True)
        except ImportError:
            continue       # driver not installed: not this chip, no news
        except (OSError, ValueError, RuntimeError) as exc:
            if not quiet:
                print("extrtc: %s at 0x%02X did not answer: %s"
                      % (name, addr, exc))
            continue
        if epoch is not None and epoch >= PLAUSIBLE_EPOCH:
            # Identified: only a chip that is keeping a time we would
            # actually believe counts. A merely well-formed date is not
            # evidence of anything -- it is exactly what one chip's
            # registers look like through another's map.
            running = (cand, epoch)
            break
        if lost and virgin is None:
            # No usable date, but the chip raises its own lost-power flag
            # -- which is the brand-new-coin-cell case, and the one case
            # where rejecting it would be permanent, because a sync is the
            # thing that would have set it. Held as a fallback, so a chip
            # that is actually running always wins.
            virgin = cand

    if running is None:
        if virgin is not None:
            print("extrtc: %s at 0x%02X has never been set; it will be "
                  "written at the first clock sync"
                  % (virgin.chip, virgin.address))
            return virgin
        if not quiet:
            if any(addr in found for _, addr, _, _ in _CANDIDATES):
                print("extrtc: something is at an RTC address but no driver "
                      "read a time from it; name the chip in config")
            else:
                print("extrtc: none found")
        return None
    r, epoch = running
    print("extrtc: %s at 0x%02X reads %04d-%02d-%02d %02d:%02d:%02d"
          % ((r.chip, r.address) + tuple(time.localtime(epoch)[:6])))
    return r


def sync(r, trust="chip"):
    """Reconcile the chip and `rtc.RTC()`. Returns a short description.

    `trust` says which clock is the better one, and the caller is the only
    thing that can know:

      * `"system"` -- something authoritative has just set the system
        clock: NTP, a browser POSTing /api/time, or a hub `cfg` reply
        reaching a node. Write it through to the chip. This is the only
        way a chip ever gets set in the first place.

      * `"chip"` (the default, and what boot uses) -- nothing has told us
        the time this run, so the chip is the better keeper of it and the
        system clock follows. This is not symmetry for its own sake. The
        ESP32's own clock runs from RTC_SLOW_CLK, which on a devkit is an
        internal RC oscillator good for percent-level accuracy -- minutes
        a day. Any of the chips here is orders of magnitude better. A node
        that is out of hub range syncs on every wake, and under the naive
        "whoever is plausible wins, system first" rule it would spend the
        week writing its own drift onto the coin cell and end up with two
        equally wrong clocks.

    Either way a chip with no usable time is written from a system clock
    that has one -- that is how a new RTC gets adopted -- and neither
    clock is ever set from a time we would not believe (PLAUSIBLE_EPOCH,
    plus the chip's own lost-power flag).

    Callers hold the returned string for the console rather than acting on
    it; the point of routing every path through here is that there is one
    place where the two clocks meet.
    """
    if r is None:
        return "no rtc"
    import rtc

    sys_epoch = int(time.time())
    sys_ok = sys_epoch >= PLAUSIBLE_EPOCH
    chip_epoch = r.read_epoch()
    chip_ok = chip_epoch is not None and chip_epoch >= PLAUSIBLE_EPOCH

    if trust == "system":
        if not sys_ok:
            return "no time to give the rtc yet"
        if chip_ok and abs(chip_epoch - sys_epoch) <= SYNC_SLOP_S:
            return "agree (%+ds)" % (chip_epoch - sys_epoch)
        if not r.write_epoch(sys_epoch):
            return "rtc write failed"
        if chip_ok:
            return "rtc set from system clock (%+ds)" % (
                sys_epoch - chip_epoch)
        return "rtc set from system clock (it had none)"

    if chip_ok:
        delta = chip_epoch - sys_epoch
        if abs(delta) <= SYNC_SLOP_S:
            return "agree (%+ds)" % delta
        rtc.RTC().datetime = time.localtime(chip_epoch)
        return "system clock set from %s (%+ds)" % (r.chip, delta)
    if sys_ok:
        if r.write_epoch(sys_epoch):
            return "rtc set from system clock (it had none)"
        return "rtc write failed"
    return "rtc has no time yet"


def status(r):
    """The clock situation, shaped for an API/status payload."""
    now = int(time.time())
    out = {"synced": now >= PLAUSIBLE_EPOCH, "now": now}
    if r is None:
        out["rtc"] = None
        return out
    out["rtc"] = r.chip
    out["addr"] = r.address
    lost, epoch = r.snapshot(quiet=True)
    if lost is not None:
        out["lost_power"] = lost
    if epoch is not None:
        out["rtc_now"] = epoch
        out["drift_s"] = epoch - now
    return out
