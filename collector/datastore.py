# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
datastore - RAM-efficient sample buffering with batched SD writes.

Design goals (no PSRAM, minimise flash/SD wear, minimise dataloss):
  * High-rate samples land in a preallocated struct-packed ring buffer in RAM
    (used for averaging + trend arrows, never written anywhere).
  * Records (averaged, at the user's record interval) queue as CSV lines in a
    small pending list and are appended to the SD card in batches -- one
    open/write/close + sync per flush, every sd_flush_interval_s or when
    sd_flush_max_pending lines are queued.
  * Alert transitions force an immediate flush (the events are exactly what
    the user wants to survive a power pull) and are ALSO written to a
    separate append-only /sd/events.csv.

SD layout:
  /sd/data/YYYY-MM-DD.csv   one file per day, all sources
      ts,src,tc,rh,co2,pm1,pm25,pm4,pm10,voc,nox,vb,flags
  /sd/data/unsynced.csv     records logged before the clock was ever set,
      boot,ts,src,...,flags each tagged with the id of the boot that logged
                            it; relabel_unsynced() queues their move into
                            their real day files the moment a clock
                            arrives, and relabel_step() -- called by the
                            main loop -- does it a slice at a time
                            (.moving/.plan beside it: a rewrite in flight,
                            the .plan also carrying its progress)
  /sd/events.csv            ts,src,metric,state,prev,value,held_s
  /sd/config.json           runtime config overrides (written by the API)

Records queued in RAM are part of the history too: list_days() and
pending_csv() expose them, so a browser syncing from a hub whose storage
is read-only (a computer holding CIRCUITPY) still gets every reading.
"""

import os
import struct
import time

# Ring record: ts(I) src(B) flags(B) tc*100(h) rh*100(H) co2(H)
#              pm25*10(H) voc(H) nox(H) vb_mv(H)
_REC_FMT = "<IBBhHHHHHH"
_REC_SIZE = struct.calcsize(_REC_FMT)  # 20 bytes

FLAG_IMPROVING = 0x01
FLAG_DECLINING = 0x02
FLAG_ABNORMAL = 0x04
# The timestamp was inferred, not measured: the row was logged by an earlier
# boot that never got a clock, and a later clock sync placed it by ordering
# alone (see _plan_relabel). Real to the minute at best; never before the
# reading was actually taken, never later than the boot that followed it.
FLAG_ESTIMATED = 0x08

_NOVAL = 0xFFFF  # sentinel for "no reading" in unsigned ring fields

CSV_HEADER = "ts,src,tc,rh,co2,pm1,pm25,pm4,pm10,voc,nox,vb,flags\n"
EVENTS_HEADER = "ts,src,metric,state,prev,value,held_s\n"

# A hub with no RTC battery boots at 2000-01-01 and stays there until NTP or
# a browser sets the clock. Readings taken in that window are real; their
# timestamps are not, so they are kept apart from the day files rather than
# written as a 2000-01-01 "day" that no one can use and nothing will fix.
PLAUSIBLE_EPOCH = 1700000000   # 2023-11; same line as envproto's
BOOT_EPOCH = 946684800         # 2000-01-01: where an unsynced clock starts
UNSYNCED_DAY = "unsynced"
_MOVING_SUFFIX = ".moving"     # a relabel in progress (see _start_relabel)
_PLAN_SUFFIX = ".plan"         # the offsets that relabel committed to
_TMP_SUFFIX = "~"              # a .plan being written (renamed when whole)

# Every unsynced boot starts at 2000-01-01 again, so the rows of boot 1, boot
# 2 and boot 3 all sit in the same timestamp range of one unsynced.csv. A
# clock sync can only measure the CURRENT boot's offset; shifting the others
# by it would land them on top of this boot's rows -- and the analyzer keys
# rows on ts+src, so colliding rows are silently dropped. Each row therefore
# carries the id of the boot that logged it, as its own leading column (this
# file never reaches a browser as-is; the day-file schema above is unchanged).
# The id lives in NVM so it survives the power cut that ends each boot.
#
# The hub's NVM map -- nothing else may use these bytes:
#   nvm[0]     who owns the USB drive: 0xF0 mcu / 0xF1 pc  (boot.py, h_storage)
#   nvm[1]     0xB7 when nvm[2:4] holds a boot id
#   nvm[2:4]   little-endian id of the last boot that wrote to unsynced.csv;
#              back to 0 once a relabel has emptied the file
_NVM_MAGIC_AT = 1
_NVM_ID_AT = 2
_NVM_MAGIC = 0xB7
_BOOT_ID_MAX = 0xFFFF
_UNSYNCED_HEADER = "boot," + CSV_HEADER
_TAIL_COMMAS = CSV_HEADER.count(",") - 1    # commas after ts in a whole row
# A relabel that has to guess where an earlier boot ended stacks it this far
# before the boot that followed. The true gap was a power cut of unknown
# length, so this is the LATEST those readings can have been taken; a real
# gap shorter than this would need two boots within a minute.
_BOOT_GAP_S = 60
# The relabel is a job the main loop steps through (DataStore.relabel_step)
# rather than one blocking pass: first a read of the file to plan every
# boot's offset, then the move itself, each resumed from a byte offset.
_PHASE_PLAN = 0
_PHASE_MOVE = 1
# How often a moving job records its offset in the .plan. Every step would
# double the flash writes a step costs; never would make a power cut redo
# the whole file (harmless -- the rows come out identical and the analyzer
# folds them -- but a day of rows twice is a lot of flash). 16 KB is ~300
# rows redone at worst.
_CHECKPOINT_BYTES = 16 * 1024
# A job whose storage went read-only under it (a host took the drive) asks
# again this often. The probe is a file write, so not every loop pass.
_REPROBE_MS = 10000


def _now_ms():
    """Milliseconds of monotonic time as an int. time.monotonic() is a
    float that loses its milliseconds after a few hours of uptime on the
    32-bit ports, and a step budget of a few tens of ms would be measured
    against noise; monotonic_ns() is exact where the port has it."""
    try:
        return time.monotonic_ns() // 1000000
    except AttributeError:
        return int(time.monotonic() * 1000)


def _decode_row(line):
    """_parse_unsynced for a raw line read back from storage as bytes.
    Bytes that do not decode are a torn row too: a power cut mid-write
    leaves flash reading 0xFF, which is not UTF-8."""
    try:
        return _parse_unsynced(line.decode().strip())
    except UnicodeError:
        return None


def _note_boot(rec, first, last):
    """Widen a boot's first/last timestamps by one parsed row; 1 if it
    was a row, 0 for a header or a torn line -- so a caller can count."""
    if rec is None:
        return 0
    boot, ts = rec[0], rec[1]
    if boot not in first or ts < first[boot]:
        first[boot] = ts
    if boot not in last or ts > last[boot]:
        last[boot] = ts
    return 1


class _RelabelJob:
    """One rewrite of unsynced.csv, in progress. Nothing here is an open
    file: a step opens what it needs and closes it before it returns
    (DataStore.relabel_step), so the job can wait out a host holding the
    drive without ever being what holds the block device."""

    def __init__(self, moving, plan_path, size, offset_s=0, boot_real=None):
        self.moving = moving
        self.plan_path = plan_path
        self.size = size            # bytes in .moving: the total of each phase
        self.offset_s = offset_s
        self.boot_real = boot_real
        self.phase = _PHASE_PLAN
        self.pos = 0                # the next unread byte of .moving
        self.first = {}             # plan pass: boot -> earliest ts seen
        self.last = {}              #            boot -> latest ts seen
        self.rows = 0               # rows the plan pass counted: the total
        self.plan = None
        self.moved = self.kept = self.torn = 0
        self.earliest = None        # earliest real ts placed so far
        self.checkpoint = 0         # pos the .plan last recorded
        self.started_ms = _now_ms()
        self.work_ms = 0            # time spent inside steps
        self.steps = 0
        self.waiting = False        # storage went read-only under us
        self.probed_ms = 0          # when it was last asked again
        self.retry_ms = 0           # a step failed: not before this
        # the earliest ts a job this one was chained behind placed, so the
        # completion report spans both (a browser re-reads that far back)
        self.earliest_floor = None


def _nvm():
    """The board's NVM, or None when there is none (or too little) to use."""
    try:
        import microcontroller
        nvm = microcontroller.nvm
    except (ImportError, AttributeError):
        return None
    if nvm is None or len(nvm) < _NVM_ID_AT + 2:
        return None
    return nvm


def _nvm_boot_id():
    nvm = _nvm()
    if nvm is None or nvm[_NVM_MAGIC_AT] != _NVM_MAGIC:
        return 0
    return nvm[_NVM_ID_AT] | (nvm[_NVM_ID_AT + 1] << 8)


def _nvm_set_boot_id(n):
    nvm = _nvm()
    if nvm is None:
        return False
    try:
        nvm[_NVM_MAGIC_AT:_NVM_ID_AT + 2] = bytes(
            [_NVM_MAGIC, n & 0xFF, (n >> 8) & 0xFF])
        return True
    except (ValueError, OSError, RuntimeError) as exc:
        print("datastore: could not record boot id in NVM:", exc)
        return False


def _parse_unsynced(line):
    """(boot, ts, tail) for one row of unsynced.csv; None for a header.

    Rows written before the boot column existed start with the timestamp
    itself, which is far larger than any boot id; they count as boot 0,
    "some earlier boot", and are placed like any other earlier boot.
    """
    first, _, rest = line.partition(",")
    try:
        head = int(first)
    except ValueError:
        return None
    if head > _BOOT_ID_MAX:
        boot, ts, tail = 0, head, rest
    else:
        stamp, _, tail = rest.partition(",")
        try:
            boot, ts = head, int(stamp)
        except ValueError:
            return None
    # a clock never reads earlier than its origin, and record() always
    # writes src + ten metrics + flags: anything else is the stub of a row
    # torn by a power cut, which must neither steer a relabel nor reach a
    # day file as a short row
    if ts < BOOT_EPOCH or tail.rstrip("\r\n").count(",") != _TAIL_COMMAS:
        return None
    return boot, ts, tail


def _or_flags(tail, bits):
    """`tail` (src,...,flags) with `bits` set in its flags column."""
    head, _, flags = tail.rpartition(",")
    try:
        return "%s,%d" % (head, int(flags) | bits)
    except ValueError:
        return tail


def _enc(val, scale=1):
    if val is None:
        return _NOVAL
    v = int(val * scale)
    return v if 0 <= v < _NOVAL else _NOVAL


def _dec(raw, scale=1):
    return None if raw == _NOVAL else raw / scale


class SampleRing:
    """Fixed-size struct ring of recent samples for one or more sources."""

    def __init__(self, capacity=360):
        self.capacity = capacity
        self._buf = bytearray(capacity * _REC_SIZE)
        self._head = 0   # next write slot
        self._count = 0
        self._src_ids = {}   # name -> small int
        self._src_names = []

    def src_id(self, name):
        sid = self._src_ids.get(name)
        if sid is None:
            sid = len(self._src_names)
            if sid > 255:
                raise ValueError("too many sources")
            self._src_ids[name] = sid
            self._src_names.append(name)
        return sid

    def add(self, src, m, flags=0, ts=None):
        """Append one sample. m is a metric dict (envproto keys, vb allowed)."""
        ts = int(ts if ts is not None else time.time())
        tc = m.get("tc")
        struct.pack_into(
            _REC_FMT, self._buf, self._head * _REC_SIZE,
            ts, self.src_id(src), flags & 0xFF,
            int(tc * 100) if tc is not None else -0x8000,
            _enc(m.get("rh"), 100),
            _enc(m.get("co2")),
            _enc(m.get("pm25"), 10),
            _enc(m.get("voc")),
            _enc(m.get("nox")),
            _enc(m.get("vb"), 1000),
        )
        self._head = (self._head + 1) % self.capacity
        if self._count < self.capacity:
            self._count += 1

    def _iter_recent(self, max_age_s, src=None, now=None):
        now = now if now is not None else time.time()
        sid = self._src_ids.get(src) if src else None
        for i in range(self._count):
            idx = (self._head - 1 - i) % self.capacity
            rec = struct.unpack_from(_REC_FMT, self._buf, idx * _REC_SIZE)
            if now - rec[0] > max_age_s:
                break  # ring is time-ordered; older beyond this
            if sid is not None and rec[1] != sid:
                continue
            yield rec

    def averages(self, src, window_s, now=None):
        """Mean of each metric for src over the last window_s seconds."""
        sums = {}
        counts = {}
        for rec in self._iter_recent(window_s, src, now):
            vals = {
                "tc": None if rec[3] == -0x8000 else rec[3] / 100,
                "rh": _dec(rec[4], 100),
                "co2": _dec(rec[5]),
                "pm25": _dec(rec[6], 10),
                "voc": _dec(rec[7]),
                "nox": _dec(rec[8]),
                "vb": _dec(rec[9], 1000),
            }
            for k, v in vals.items():
                if v is not None:
                    sums[k] = sums.get(k, 0.0) + v
                    counts[k] = counts.get(k, 0) + 1
        return {k: sums[k] / counts[k] for k in sums}


def take_filesystem(tries=1, delay=0.1):
    """Take CIRCUITPY from the host so the board can write it.

    `unsafe_disable_usb_drive()` is all it takes: the CircuitPython docs are
    explicit that afterwards "CIRCUITPY becomes read/write, and can be
    written from user code or the REPL... easier than arranging for a
    remount() in boot.py". Calling remount() as well is what fails with
    "Cannot remount path when visible via USB".

    The call delays ~2.5 s on purpose, so the host sees the drive report
    not-ready and unmounts it. Make sure the host has finished writing
    first -- this is the equivalent of yanking the drive out.
    """
    import storage
    try:
        storage.unsafe_disable_usb_drive()
        return True
    except Exception as exc:
        print("storage: could not take the filesystem: %s: %s"
              % (type(exc).__name__, exc))
        return False


def give_filesystem_back():
    """Hand CIRCUITPY back: the drive's logical unit becomes ready again and
    the host re-mounts it on its next poll (every second or two). It returns
    to read-only for our code by itself, so there is nothing else to undo."""
    import storage
    storage.enable_usb_drive()
    return True


class DataStore:
    """Latest-value cache + batched writer + event log.

    Storage target picks the first WRITABLE root of `roots`:
      /sd      the SD card (preferred, plenty of space)
      /saves   the CPSAVES partition, when the build has one
      /        CIRCUITPY flash itself -- writable to code on boards with no
               USB mass storage (e.g. ESP32-C6); on MSC boards this probe
               fails while USB is connected, which is what we want.
    On a flash root, `min_free_bytes` (default 50KB) is preserved: the
    oldest day file is rotated out first, then pending data is dropped
    (bounded) rather than filling the filesystem. Callers should also
    lengthen the record interval on flash (see `on_flash`).
    """

    # How much of a relabel one relabel_step() does: whichever of these
    # runs out first. The main loop also drives the display, ESP-NOW and
    # the HTTP/BLE portals between steps, and a poll of those is a few ms,
    # so a step is kept to a few tens of ms; the row cap is the backstop
    # for a clock too coarse to see the budget.
    step_ms = 25
    step_rows = 200

    def __init__(self, roots=("/sd", "/saves", "/"), flush_interval_s=600,
                 flush_max_pending=24, min_free_bytes=50 * 1024,
                 allow_usb_release=False, ram_lines=200, ram_events=100):
        self.roots = roots
        self.allow_usb_release = allow_usb_release
        self._usb_released = False
        # While storage is unwritable -- a computer holding the drive, a
        # missing card -- readings queue here and are written in full the
        # moment it comes back (flush() re-probes every time, and
        # autoreload is off so a host edit cannot restart us and lose
        # them). Only past these caps does anything get dropped.
        self.ram_lines = ram_lines
        self.ram_events = ram_events
        self._warned_full = False
        self.flush_interval_s = flush_interval_s
        self.flush_max_pending = flush_max_pending
        self.min_free_bytes = min_free_bytes
        self.latest = {}       # src -> {"ts":, "m": {...}, "vb":, "type":, "rssi":}
        self._pending = []     # CSV lines waiting for storage
        self._pending_events = []
        self._last_flush = time.monotonic()
        self.read_only = False   # set by _pick_root
        self.root = self._pick_root()
        self.write_errors = 0
        self.dropped_lines = 0
        # the id this boot's pre-clock rows are filed under in unsynced.csv:
        # 0 until the first flush that writes one, so a boot that gets a
        # clock in time (or never gets to write) burns no id
        self.boot_id = 0
        # a clock sync that landed while storage was read-only: the rewrite
        # it owes the day files happens on the next flush that can write,
        # with this much accumulated correction for this boot's own rows
        self._relabel_due = False
        self._relabel_offset = 0
        # (rows moved, earliest real ts placed) by the last relabel, so a
        # client can be told how far back its copy of the history changed
        self.last_relabel = (0, None)
        # the relabel in progress (a _RelabelJob the main loop steps), the
        # summary of the last one to finish, and rows moved since boot
        self._job = None
        self._last_job = None
        self.relabel_moved_total = 0
        self._recover_unsynced()
        if time.time() >= PLAUSIBLE_EPOCH:
            # the clock was set before we existed (NTP at bring-up, an RTC
            # battery), so whatever earlier boots logged without one can be
            # placed now; none of it is this boot's, hence no offset. Queued,
            # not done: boot is also when the display and the radios are
            # being brought up, and the job steps alongside them.
            self.relabel_unsynced(0)

    @property
    def sd_ok(self):
        return self.root == "/sd"

    @property
    def on_flash(self):
        return self.root is not None and self.root != "/sd"

    @property
    def mode(self):
        if self.read_only:
            return "%s (read-only)" % ("sd" if self.sd_ok else "flash")
        return "sd" if self.sd_ok else ("flash" if self.root else "ram")

    def data_dir(self):
        return None if self.root is None else (
            self.root.rstrip("/") + "/data")

    def day_path(self, day):
        d = self.data_dir()
        return None if d is None else "%s/%s.csv" % (d, day)

    def _day_of(self, ts):
        """The day file a timestamp belongs in -- UNSYNCED_DAY while the
        clock is still the one the board booted with."""
        if ts < PLAUSIBLE_EPOCH:
            return UNSYNCED_DAY
        t = time.localtime(ts)
        return "%04d-%02d-%02d" % (t[0], t[1], t[2])

    def _day_size(self, day):
        """Bytes already on storage for a day (0 = nothing, or no storage)."""
        path = self.day_path(day)
        if path is None:
            return 0
        try:
            return os.stat(path)[6]
        except OSError:
            return 0

    def _writable(self, root):
        probe = root.rstrip("/") + "/.dsprobe"
        try:
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            return True
        except OSError:
            return False

    def _pick_root(self, may_release=True):
        """The first writable root, else one that at least holds data.

        A hub whose storage has gone read-only -- USB mass storage mounted
        on a computer, a write-protected or full card -- can still SERVE the
        history it already has. Buffering new readings in RAM and refusing
        to list the days on the card at the same time is the worst of both.

        `may_release=False` for a probe that must only look: a relabel job
        re-probing every few seconds must never be what takes the drive
        back from a computer the user has just handed it to.
        """
        readable = None
        for root in self.roots:
            try:
                os.listdir(root)
            except OSError:
                continue
            if self._writable(root):
                self.read_only = False
                return root
            if readable is None:
                try:
                    os.listdir(root.rstrip("/") + "/data")
                    readable = root      # has history, just cannot be written
                except OSError:
                    pass
        if readable is not None and self.allow_usb_release \
                and may_release and not self._usb_released:
            # Nothing writable because a computer has CIRCUITPY mounted:
            # take the drive back and try again. disable_usb_drive() is
            # boot.py-only, so this is the "unsafe" runtime variant -- named
            # that because a host writing at this instant loses the write,
            # which is why it happens once and only as a last resort.
            self._usb_released = True
            if take_filesystem():
                print("storage: USB drive released so the hub can write")
                return self._pick_root()
            print("storage: could not take the filesystem from the host")
        was_ro = self.read_only
        self.read_only = readable is not None
        if readable and not was_ro:
            # once, not on every flush: this is re-probed constantly so that
            # storage coming back is picked up without a restart
            print("storage: %s is read-only (USB drive mounted?); serving "
                  "existing days, buffering new data in RAM" % readable)
        return readable

    def _free_bytes(self):
        try:
            st = os.statvfs(self.root)
            return st[3] * st[1]  # f_bavail * f_frsize
        except (OSError, AttributeError):
            return None

    def _rotate_oldest(self):
        """Delete the oldest day file to reclaim flash space. True if one went."""
        days = self.stored_days()   # only files can be rotated out
        if len(days) <= 1:  # never delete the day we're writing
            return False
        try:
            os.remove("%s/%s.csv" % (self.data_dir(), days[0]))
            print("storage: rotated out", days[0])
            return True
        except OSError:
            return False

    def _ensure_space(self, need):
        if not self.on_flash:
            return True
        for _ in range(8):
            free = self._free_bytes()
            if free is None or free - need >= self.min_free_bytes:
                return True
            if not self._rotate_oldest():
                return False
        return False

    # ---------------- latest values ----------------

    def update_latest(self, src, metrics, batt_v=None, sensor_type=None,
                      rssi=None, ts=None):
        entry = self.latest.setdefault(src, {})
        entry["ts"] = int(ts if ts is not None else time.time())
        entry["m"] = metrics
        if batt_v is not None:
            entry["vb"] = batt_v
        if sensor_type:
            entry["type"] = sensor_type
        if rssi is not None:
            entry["rssi"] = rssi
        return entry

    # ---------------- record + event queueing ----------------

    def record(self, src, m, flags=0, ts=None):
        """Queue one averaged record. Timestamp kept separate from the CSV
        tail so pending records can be retro-adjusted when the clock syncs
        (see adjust_pending)."""
        ts = int(ts if ts is not None else time.time())

        def f(key, fmt="%.2f"):
            v = m.get(key)
            return "" if v is None else (fmt % v if isinstance(v, float) else str(v))

        tail = "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%d" % (
            src, f("tc", "%.1f"), f("rh", "%.1f"), f("co2", "%.0f"),
            f("pm1", "%.1f"), f("pm25", "%.1f"), f("pm4", "%.1f"),
            f("pm10", "%.1f"), f("voc", "%.0f"), f("nox", "%.0f"),
            f("vb", "%.3f"), flags,
        )
        self._pending.append([ts, tail])
        if len(self._pending) >= self.flush_max_pending:
            self.flush()

    def adjust_pending(self, offset_s):
        """Shift every not-yet-written record by offset_s -- called when
        the clock is synced after data was buffered with a wrong clock."""
        if not offset_s:
            return 0
        for rec in self._pending:
            rec[0] += offset_s
        print("datastore: adjusted %d pending records by %+ds"
              % (len(self._pending), offset_s))
        return len(self._pending)

    # ---------------- records still in RAM ----------------

    def pending_days(self):
        """Days that have records queued in RAM but not yet on storage.

        Records logged before the clock was set are deliberately left out:
        they have no real day yet, and relabel_unsynced() gives them one
        the instant a clock arrives.
        """
        days = []
        for ts, _ in self._pending:
            day = self._day_of(ts)
            if day != UNSYNCED_DAY and day not in days:
                days.append(day)
        return days

    def pending_csv(self, day):
        """The queued rows for one day as CSV bytes, b"" when there are none.

        The history API appends this to whatever is on storage, so a hub
        that cannot write -- a computer holding CIRCUITPY, a missing card --
        still hands a browser the readings buffered in RAM. The header comes
        with it when nothing for that day has reached storage yet.
        """
        rows = [rec for rec in self._pending if self._day_of(rec[0]) == day]
        if not rows:
            return b""
        # built into one bytearray rather than joined: at the RAM cap this
        # is ~12 KB, and the hub has no PSRAM to hold two copies of it
        out = bytearray()
        if not self._day_size(day):
            out += CSV_HEADER.encode()
        for ts, tail in rows:
            out += ("%d,%s\n" % (ts, tail)).encode()
        return out

    def unsynced_pending(self):
        """How many queued records still carry a pre-clock timestamp."""
        n = 0
        for ts, _ in self._pending:
            if ts < PLAUSIBLE_EPOCH:
                n += 1
        return n

    def unsynced_stored(self):
        """Bytes of pre-clock records sitting on storage awaiting a clock.

        Non-zero on a hub that has never been told the time -- including
        the rows of EARLIER boots that ended without one: they wait in the
        same file, each under its boot id, for the sync that places them
        (a relabel caught by a power cut counts too: its .moving file).
        """
        path = self.day_path(UNSYNCED_DAY)
        if path is None:
            return 0
        return self._size(path) + self._size(path + _MOVING_SUFFIX)

    # ---------------- clock sync ----------------

    def _size(self, path):
        try:
            return os.stat(path)[6]
        except OSError:
            return 0

    def _exists(self, path):
        try:
            os.stat(path)
            return True
        except OSError:
            return False

    def _claim_boot_id(self):
        """The id this boot's pre-clock rows are filed under, taken on first
        use.

        One more than the last id in NVM -- or in the file, whichever is
        higher: the file outlives an NVM wiped by a firmware reflash, and
        on a board with no NVM it is the only record there is. The wrap at
        65535 is academic; that many boots without one clock sync would
        have filled the flash long before.
        """
        if self.boot_id:
            return self.boot_id
        last = _nvm_boot_id()
        path = self.day_path(UNSYNCED_DAY)
        for p in (path, path + _MOVING_SUFFIX):
            try:
                with open(p) as f:
                    for line in f:
                        rec = _parse_unsynced(line)
                        if rec is not None and rec[0] > last:
                            last = rec[0]
            except OSError:
                pass
        self.boot_id = last + 1 if last < _BOOT_ID_MAX else 1
        _nvm_set_boot_id(self.boot_id)
        print("datastore: logging without a clock as boot %d" % self.boot_id)
        return self.boot_id

    def relabel_unsynced(self, offset_s, boot_real=None):
        """Queue the move of already-stored pre-clock records onto the real
        timeline. Returns the bytes queued (0: nothing to do, or deferred).

        The companion to adjust_pending(): that fixes what is still in RAM,
        this rewrites what reached /data/unsynced.csv into the day files
        those readings actually belong in. `offset_s` is the correction the
        clock just received -- exact for the rows THIS boot wrote. Rows
        from earlier boots are placed by inference (_plan_boots), which is
        why a hub that came up with a clock passes 0 and still empties the
        file.

        Nothing is moved here. The file is claimed (renamed aside) and the
        work becomes a job that relabel_step() does a slice of per main-
        loop pass: a hub that logged for days without a clock has hundreds
        of KB to move, and one blocking pass was seconds in which it served
        no HTTP connection, no BLE command and read no ESP-NOW packet -- the
        request that set the clock got its reply only at the end.
        relabel_status() is how a client watches it.

        Storage that cannot be written right now defers the whole thing to
        the next flush that can; so does a job already running (the live
        file is claimed the moment that one finishes, _finish_relabel). A
        second correction that lands while a job is still planning is
        folded into its plan -- nothing is committed yet; one that lands
        while it is moving cannot be: those rows go where the first
        correction put them, and the second (a browser disagreeing with
        another by more than 5 s about the time) is owed to the live file
        only. The old one-shot had no such window; a nudge is an accuracy
        loss of that many seconds on that boot's rows, never a lost row.
        """
        if self.root is not None and not self.unsynced_stored():
            return 0          # nothing was ever logged without a clock
        job = self._job
        if job is not None and job.phase == _PHASE_PLAN and not job.waiting:
            job.offset_s += offset_s
            print("datastore: relabel still planning; %+ds folded into it"
                  % offset_s)
            return job.size
        if self.root is None or self.read_only or job is not None:
            # (with no root at all we cannot even see whether the card that
            # comes back holds such a file, so the correction is kept)
            self._relabel_offset += offset_s
            self._relabel_due = True
            print("datastore: relabel deferred (%+ds owed); %s"
                  % (self._relabel_offset,
                     "one is already running" if self._job is not None
                     else "storage is not writable"))
            return 0
        return max(0, self._start_relabel(offset_s, boot_real))

    def relabel_pending(self):
        """True while a relabel job exists -- running, or waiting for the
        storage a host took mid-way."""
        return self._job is not None

    def _recover_unsynced(self):
        """Adopt, or put back, a relabel that a power cut interrupted.

        The rewrite renames the file aside and commits its offsets to a
        .plan before it writes a row. Interrupted after that, the plan is
        picked up as this boot's job, from the last progress line the plan
        recorded (or the top, for a plan written before there were any):
        the rows it had already moved come out identical -- same ts, same
        src -- and the analyzer folds them. Interrupted before the plan
        existed, nothing has moved, and the file goes back to wait for a
        sync -- appended, when a boot in between has already started a
        fresh one.
        """
        if self.root is None or self.read_only or self._job is not None:
            # (read-only: looked at again by the next relabel that can
            # start -- a clock sync, or a flush paying one off -- and
            # failing those, by the next boot; nothing is at risk meanwhile)
            return
        path = self.day_path(UNSYNCED_DAY)
        moving = path + _MOVING_SUFFIX
        plan_path = path + _PLAN_SUFFIX
        if not self._exists(moving):
            for p in (plan_path, plan_path + _TMP_SUFFIX):
                try:
                    os.remove(p)       # its file is done; this is litter
                except OSError:
                    pass
            return
        plan, meta = self._read_plan(plan_path)
        if plan:
            job = _RelabelJob(moving, plan_path, self._size(moving))
            job.phase = _PHASE_MOVE
            job.plan = plan
            job.rows = meta.get("rows")      # None: a plan from before
            job.pos = job.checkpoint = meta.get("pos", 0)
            job.moved = meta.get("moved", 0)
            job.kept = meta.get("kept", 0)
            job.torn = meta.get("torn", 0)
            job.earliest = meta.get("earliest") or None
            self._job = job
            print("datastore: resuming an interrupted clock relabel from "
                  "byte %d of %d" % (job.pos, job.size))
            return
        try:
            if not self._exists(path):
                os.rename(moving, path)
            else:
                with open(moving) as src:
                    with open(path, "a") as dst:
                        for line in src:
                            if _parse_unsynced(line) is None:
                                continue     # the header is there already
                            if not line.endswith("\n"):
                                line += "\n"  # torn by the same power cut
                            dst.write(line)
                os.remove(moving)
            try:
                os.remove(plan_path)     # a header-only plan: nothing placed
            except OSError:
                pass
            print("datastore: recovered an interrupted clock relabel")
        except OSError as exc:
            print("datastore: could not recover %s: %s" % (moving, exc))

    def _read_plan(self, plan_path):
        """({boot: (offset_s, flag bits)}, progress) from a .plan.

        The plan proper is one `boot,offset,flags` line per boot. Around it
        the job keeps its own bookkeeping, which _plan_step and _checkpoint
        write and an interrupted job resumes from: a `#rows,bytes` head
        (the totals, so a resumed job can still report how far along it
        is) and `@pos,moved,kept,torn,earliest` progress lines, of which
        the last complete one wins. Anything torn -- no newline, or too few
        fields -- is ignored: a torn progress line falls back to the one
        before it and redoes a little work, never skips any.
        """
        plan = {}
        meta = {}
        try:
            with open(plan_path) as f:
                for line in f:
                    if not line.endswith("\n"):
                        continue          # torn: the power went mid-line
                    parts = line.strip().split(",")
                    try:
                        if line.startswith("#"):
                            meta["rows"] = int(parts[0][1:])
                        elif line.startswith("@"):
                            if len(parts) < 5:
                                continue
                            meta["pos"] = int(parts[0][1:])
                            meta["moved"] = int(parts[1])
                            meta["kept"] = int(parts[2])
                            meta["torn"] = int(parts[3])
                            meta["earliest"] = int(parts[4])
                        else:
                            plan[int(parts[0])] = (int(parts[1]), int(parts[2]))
                    except (IndexError, ValueError):
                        continue     # a torn line: the plan never completed
        except OSError:
            pass
        return plan, meta

    def _plan_relabel(self, moving, offset_s, boot_real=None):
        """The plan for a whole file in one pass: what the hub does a step
        at a time (_plan_step), for the host tests to pin the arithmetic."""
        first = {}
        last = {}
        with open(moving, "rb") as f:
            for line in f:
                _note_boot(_decode_row(line), first, last)
        return self._plan_boots(first, last, offset_s, boot_real)

    def _plan_boots(self, first, last, offset_s, boot_real=None):
        """Decide what every boot in the file is shifted by, from each
        boot's first and last timestamp: {boot: (offset_s, flag bits)}. A
        boot left out stays in the file.

        This boot's rows take `offset_s`, the correction the clock just
        received, and that is exact. Nothing measured the offset of an
        earlier boot -- it went with the power. What IS known is the order:
        each boot ended before the next began, and this one began at the
        moment its clock read BOOT_EPOCH, which is `offset_s` ago in real
        time. So, walking back from there, every earlier boot is placed
        with its last row _BOOT_GAP_S before the boot that followed it
        powered on -- which, once that boot's offset is chosen, is exactly
        BOOT_EPOCH + offset -- its own spacing and order intact. Rows
        placed this way cannot collide -- not with each other, not with
        this boot's, not with what is queued in RAM (all of which is after
        that moment) -- and carry FLAG_ESTIMATED.

        One refinement: the ESP32's RTC runs on through a soft reset (a
        watchdog, `reset` over the API, the error-streak restart), so a
        boot whose rows all end a clear gap before the following boot's
        first row shared its clock, keeps its offset, and is as exact as
        it. A genuine chain has a reboot plus a record interval between
        the two; a one-row boot that lost power a second before the next
        boot's first reading has not, and the gap keeps it apart. The test
        is on the file's own timestamps, so it needs nothing from the port.

        A firmware build date as a floor was considered and dropped: the
        placement is already the LATEST the rows can have been taken (the
        gap it assumes is the shortest a power cycle allows), so a floor
        could only ever clip rows that are already after it.

        `boot_real` -- real time now less time.monotonic() -- is only the
        anchor when there is no correction to go by (this boot came up
        synced, so none of the file is its own); monotonic() may count
        from power-on rather than this boot on some ports, and any error
        there only back-dates the estimates, never collides them. It is a
        parameter so the host tests can pin it.
        """
        anchor = BOOT_EPOCH + offset_s if offset_s else 0
        if anchor < PLAUSIBLE_EPOCH:
            # no correction, or one too small to have come from the boot
            # clock (a browser nudging an already-real clock): uptime it is
            if boot_real is None:
                boot_real = int(time.time() - time.monotonic())
            anchor = boot_real
        plan = {}
        # 0 is "no id yet" for us but "some earlier boot" in the file
        cur = self.boot_id or None
        prev_off = prev_first = None
        if cur in first and offset_s:
            plan[cur] = (offset_s, 0)
            prev_off, prev_first = offset_s, first[cur]
        # ...and this boot's rows with no correction to place them by are
        # left out: they wait for the sync that brings one, never guessed
        for boot in sorted(first, reverse=True):
            if boot == cur:
                continue
            if prev_first is not None and \
                    last[boot] + _BOOT_GAP_S <= prev_first:
                off = prev_off        # same clock, still ticking
            else:
                off = anchor - _BOOT_GAP_S - last[boot]
            plan[boot] = (off, FLAG_ESTIMATED)
            # when this boot powered on (for a shared clock: when the chain
            # it belongs to did, which is earlier still, so just as safe)
            anchor = BOOT_EPOCH + off
            prev_off, prev_first = off, first[boot]
        return plan

    def _start_relabel(self, offset_s, boot_real=None):
        """Claim unsynced.csv as a relabel job. Returns the bytes claimed,
        0 when there is nothing to move, -1 when it could not even start
        (the caller keeps its offset).

        Renamed aside first, so a crash part-way leaves work to finish
        rather than a file being appended to while it is read -- and so
        the rows this boot logs from here on (all real-time ones, after a
        sync) can never end up in the file the job is reading.
        """
        # never plan over an unfinished one -- but adopting it must not
        # cost us our own id: this boot's rows may be in the live file, and
        # the counter only resets once nothing is left anywhere
        boot_id = self.boot_id
        self._recover_unsynced()
        self.boot_id = boot_id
        if self._job is not None:
            # an interrupted relabel was adopted: it goes first, and the
            # live file is claimed with this correction when it is done
            self._relabel_offset += offset_s
            self._relabel_due = True
            return self._job.size
        path = self.day_path(UNSYNCED_DAY)
        moving = path + _MOVING_SUFFIX
        if not self._exists(path):
            return 0
        size = self._size(path)
        try:
            os.rename(path, moving)
        except OSError as exc:
            print("datastore: relabel could not claim the file:", exc)
            return -1
        self._job = _RelabelJob(moving, path + _PLAN_SUFFIX, size,
                                offset_s, boot_real)
        print("datastore: relabel queued: %d bytes of stored records to "
              "plan and move" % size)
        return size

    def relabel_step(self, budget_ms=None, max_rows=None):
        """One slice of the relabel job, for the main loop: a no-op with
        nothing pending (returns None), else True.

        A step is bounded twice over: by `budget_ms` of wall time -- the
        clock is checked after every row -- and by `max_rows`, so a budget
        the port's clock cannot resolve still ends the step (the defaults
        are the class's step_ms / step_rows). It opens the files it needs
        and closes every one before it returns: nothing this class holds
        between passes can keep CircuitPython from handing the filesystem
        to a host (h_storage in code.py) or remounting it, and the job
        simply waits, resuming from its byte offset, if storage has gone
        read-only under it -- re-probing every _REPROBE_MS, since a drive
        the host ejected by itself comes back with no call to tell us.

        The plan pass is stepped too: parsing every row of the file in
        Python is the slower half of the old one-shot on the C6, not the
        writes, so a synchronous plan would have kept the very stall this
        replaces.
        """
        job = self._job
        if job is None:
            return None
        t0 = _now_ms()
        if job.retry_ms and t0 < job.retry_ms:
            return True        # a step failed a moment ago: not every pass
        job.retry_ms = 0
        if self.root is None or self.read_only:
            if job.probed_ms and t0 - job.probed_ms < _REPROBE_MS:
                return True
            job.probed_ms = t0
            self.root = self._pick_root(may_release=False)
            if self.root is None or self.read_only:
                if not job.waiting:
                    print("datastore: relabel paused at byte %d of %d; "
                          "storage is not writable" % (job.pos, job.size))
                job.waiting = True
                return True
        job.waiting = False
        job.probed_ms = 0
        budget = self.step_ms if budget_ms is None else budget_ms
        rows = self.step_rows if max_rows is None else max_rows
        done = False
        try:
            if job.phase == _PHASE_PLAN:
                self._plan_step(job, t0, budget, rows)
            else:
                done = self._move_step(job, t0, budget, rows)
        except OSError as exc:
            # whatever was moved is in the day files; the job's offset is
            # at the last row it knows landed, and the .plan makes the
            # retry produce the same rows -- so wait for storage to return
            print("datastore: relabel step failed at byte %d: %s"
                  % (job.pos, exc))
            self.write_errors += 1
            self.root = self._pick_root(may_release=False)
            job.probed_ms = job.retry_ms = t0 + _REPROBE_MS
        job.steps += 1
        job.work_ms += _now_ms() - t0
        if done:
            self._finish_relabel(job)
        return True

    def _plan_step(self, job, t0, budget_ms, max_rows):
        """Read on from the job's offset, noting each boot's first and last
        timestamp; at the end of the file, commit the plan and turn the
        job into a move."""
        n = 0
        with open(job.moving, "rb") as f:
            f.seek(job.pos)
            while True:
                line = f.readline()
                if not line:
                    break
                job.pos += len(line)
                job.rows += _note_boot(_decode_row(line), job.first, job.last)
                n += 1
                if n >= max_rows or _now_ms() - t0 >= budget_ms:
                    return
        # the whole file has been read: the offsets are committed before a
        # row moves, so finishing after a power cut lands the same rows
        job.plan = self._plan_boots(job.first, job.last, job.offset_s,
                                    job.boot_real)
        # written whole or not at all: a .plan the power cut short would
        # be adopted at the next boot with the boots it never got to
        # missing -- kept back rather than placed -- so it is renamed into
        # place only once every line is on the medium
        tmp = job.plan_path + _TMP_SUFFIX
        with open(tmp, "w") as f:
            f.write("#%d,%d\n" % (job.rows, job.size))
            for boot in job.plan:
                f.write("%d,%d,%d\n" % (boot, job.plan[boot][0],
                                        job.plan[boot][1]))
        try:
            os.sync()
        except (OSError, AttributeError):
            pass
        os.rename(tmp, job.plan_path)
        job.first = job.last = None
        job.phase = _PHASE_MOVE
        job.pos = 0

    def _move_step(self, job, t0, budget_ms, max_rows):
        """Write rows from the job's offset where the plan puts their boot;
        rows of a boot the plan leaves out go back to a fresh unsynced.csv,
        boot id intact, for a later sync. True at the end of the file.

        The offset advances only when the step's writes have actually
        landed -- it is committed after the output file closes, since a
        write goes to a buffer and it is the close that can still fail on
        a full card. A step that raises therefore leaves the job where it
        started and redoes those rows, which come out identical and fold;
        advancing first would have skipped whatever the failed flush
        never wrote. A step never has more than one output file open:
        rows are in time order within a boot, so the day changes rarely
        and each day file is opened once per step, not once per line.

        A day file is mended before it is appended to, as _append does:
        the power going mid-row leaves a torn tail with no newline, and
        the redo of that very row after the checkpoint would otherwise
        fuse with it into one nonsense line -- the one row the checkpoint
        promised would come out identical and fold.
        """
        plan = job.plan
        out = None
        out_day = None
        n = 0
        done = False
        # this step's work, committed to the job only once the output
        # file has closed without complaint (see the docstring)
        pos = job.pos
        moved = kept = torn = 0
        earliest = None
        try:
            with open(job.moving, "rb") as f:
                f.seek(job.pos)
                while True:
                    line = f.readline()
                    if not line:
                        done = True
                        break
                    rec = _decode_row(line)
                    if rec is None:
                        s = line.strip()
                        if s and not s.startswith(b"boot,") \
                                and not s.startswith(b"ts,"):
                            torn += 1         # a power cut's half-written row
                    else:
                        boot, ts, tail = rec
                        p = plan.get(boot)
                        if p is not None and ts + p[0] >= PLAUSIBLE_EPOCH:
                            ts += p[0]
                            if p[1]:
                                tail = _or_flags(tail, p[1])
                            day = self._day_of(ts)
                            row = "%d,%s\n" % (ts, tail)
                        else:
                            day = UNSYNCED_DAY   # no usable offset: keep, not guess
                            row = "%d,%d,%s\n" % (boot, ts, tail)
                        if day != out_day:
                            if out is not None:
                                out.close()
                                out = None
                            size = self._day_size(day)
                            mend = size and self._torn_tail(self.day_path(day), size)
                            out = open(self.day_path(day), "a")
                            if mend:
                                out.write("\n")
                            if not size:
                                out.write(_UNSYNCED_HEADER if day == UNSYNCED_DAY
                                          else CSV_HEADER)
                            out_day = day
                        out.write(row)
                        if day == UNSYNCED_DAY:
                            kept += 1
                        else:
                            moved += 1
                            if earliest is None or ts < earliest:
                                earliest = ts
                    pos += len(line)
                    n += 1
                    if n >= max_rows or _now_ms() - t0 >= budget_ms:
                        break
        finally:
            if out is not None:
                out.close()      # raises here -> nothing below commits
        job.pos = pos
        job.moved += moved
        job.kept += kept
        job.torn += torn
        if earliest is not None and (job.earliest is None
                                     or earliest < job.earliest):
            job.earliest = earliest
        if not done and job.pos - job.checkpoint >= _CHECKPOINT_BYTES:
            self._checkpoint(job)
        return done

    def _checkpoint(self, job):
        """Record the job's offset in its .plan, so a power cut costs at
        most _CHECKPOINT_BYTES of redone (and folded) rows rather than the
        whole file. The rows it vouches for are synced to the medium first:
        a checkpoint that outlived its rows would skip them."""
        try:
            os.sync()
        except (OSError, AttributeError):
            pass
        with open(job.plan_path, "a") as f:
            f.write("@%d,%d,%d,%d,%d\n" % (job.pos, job.moved, job.kept,
                                           job.torn, job.earliest or 0))
        job.checkpoint = job.pos

    def _finish_relabel(self, job):
        """Clean up after the last row: remove the .moving and .plan and
        -- if the file is now empty -- hand the boot counter back to 0, so
        the next boot without a clock is boot 1 again and the ids never
        grow. Then start the job that was queued behind this one, if any.
        """
        path = self.day_path(UNSYNCED_DAY)
        for p in (job.moving, job.plan_path):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.sync()
        except (OSError, AttributeError):
            pass
        if not job.kept and not self._exists(path):
            # nothing left anywhere -- not even a live file this boot has
            # started meanwhile -- so the ids can start over
            self.boot_id = 0
            _nvm_set_boot_id(0)
        elapsed = _now_ms() - job.started_ms
        handled = job.moved + job.kept + job.torn
        now = int(time.time())
        earliest = job.earliest
        if job.earliest_floor and (earliest is None
                                   or job.earliest_floor < earliest):
            earliest = job.earliest_floor   # the job this one followed
        self.last_relabel = (job.moved, earliest)
        self.relabel_moved_total += job.moved
        # what a bench run reads back through the API: wall time from the
        # sync to the last row, the time actually spent inside steps (the
        # rest was the loop's other work), and the rate over that
        self._last_job = {
            "rows": job.moved, "kept": job.kept, "torn": job.torn,
            "span_s": (now - earliest) if earliest else 0,
            "elapsed_ms": elapsed, "work_ms": job.work_ms,
            "steps": job.steps,
            "rows_per_s": (handled * 1000 // job.work_ms) if job.work_ms
            else handled,
            "at": now,
        }
        self._job = None
        print("datastore: relabelled %d stored record(s) in %d ms (%d ms of "
              "work over %d steps, %d rows/s)%s%s"
              % (job.moved, elapsed, job.work_ms, job.steps,
                 self._last_job["rows_per_s"],
                 (", %d kept for a later sync" % job.kept) if job.kept else "",
                 (", %d torn row(s) dropped" % job.torn) if job.torn else ""))
        if self._relabel_due and self.root is not None and not self.read_only:
            # a sync arrived while this ran, or this was an adopted job and
            # the live file waited behind it: claim that now, same offset
            offset, self._relabel_offset = self._relabel_offset, 0
            self._relabel_due = False
            if self._start_relabel(offset) < 0:
                self._relabel_offset, self._relabel_due = offset, True
            elif self._job is not None:
                # one completion report for the pair: a client that only
                # sees the second finish must still re-read as far back as
                # the first reached
                self._job.earliest_floor = earliest

    def relabel_status(self):
        """The relabel job as a client sees it (GET /api/storage, BLE
        `storage`, and the reply to a clock sync): what state it is in,
        how far it has got in bytes and rows, and -- under `last` -- what
        the most recent completed one moved and how long it took. `pct`
        is the one number a bar needs: the plan pass is the first quarter
        (a read of the file), the move the rest.
        """
        job = self._job
        st = {"state": "idle", "pct": 0, "bytes_done": 0, "bytes_total": 0,
              "rows_done": 0, "rows_total": None, "kept": 0,
              "elapsed_ms": 0, "last": self._last_job}
        if job is None:
            if self._relabel_due:
                st["state"] = "deferred"
                st["bytes_total"] = self.unsynced_stored()
            return st
        if job.waiting:
            st["state"] = "waiting"
        elif job.phase == _PHASE_PLAN:
            st["state"] = "planning"
        else:
            st["state"] = "moving"
        frac = (job.pos * 100 // job.size) if job.size else 100
        st["pct"] = frac // 4 if job.phase == _PHASE_PLAN else 25 + frac * 3 // 4
        st["bytes_done"] = job.pos
        st["bytes_total"] = job.size
        st["rows_done"] = job.moved + job.kept
        st["rows_total"] = job.rows if job.phase == _PHASE_MOVE else None
        st["kept"] = job.kept
        st["elapsed_ms"] = _now_ms() - job.started_ms
        return st

    def log_event(self, event):
        """Queue an alert transition; forces a flush so it survives power loss."""
        self._pending_events.append(
            "%d,%s,%s,%s,%s,%s,%d\n" % (
                event["ts"], event["src"], event["metric"], event["state"],
                event["prev"],
                "" if event.get("value") is None else event["value"],
                event.get("held_s", 0),
            )
        )
        self.flush()

    def maybe_flush(self):
        if (self._pending or self._pending_events or self._relabel_due) and (
            time.monotonic() - self._last_flush >= self.flush_interval_s
        ):
            self.flush()

    # ---------------- storage I/O ----------------

    def _ensure_dir(self, path):
        try:
            os.mkdir(path)
        except OSError:
            pass  # exists

    def _torn_tail(self, path, size):
        """True if the file's last byte is not a newline: a power cut
        mid-write left a torn last row, and anything appended as-is would
        fuse with it into one line with a nonsense timestamp."""
        with open(path, "rb") as f:
            f.seek(size - 1)
            return f.read(1) != b"\n"

    def _append(self, path, header, lines):
        need_header = True
        mend = False
        try:
            size = os.stat(path)[6]
            need_header = size == 0
            if size:
                mend = self._torn_tail(path, size)
        except OSError:
            pass  # missing -> header needed
        with open(path, "a") as f:
            if mend:
                f.write("\n")
            if need_header:
                f.write(header)
            for line in lines:
                f.write(line)

    def _drop_bounded(self):
        """Bound the RAM queue. Nothing is dropped until it is genuinely
        full: everything queued is written as soon as storage returns."""
        over = (len(self._pending) > self.ram_lines
                or len(self._pending_events) > self.ram_events)
        if over and not self._warned_full:
            self._warned_full = True
            print("storage: RAM buffer full (%d readings, %d events); "
                  "dropping the oldest from here on"
                  % (len(self._pending), len(self._pending_events)))
        # drop oldest records first, events last -- they are the rarer and
        # more valuable ones
        while len(self._pending) > self.ram_lines:
            self._pending.pop(0)
            self.dropped_lines += 1
        while len(self._pending_events) > self.ram_events:
            self._pending_events.pop(0)
            self.dropped_lines += 1

    def flush(self):
        """Write everything pending in one burst. Safe to call anytime."""
        self._last_flush = time.monotonic()
        if not (self._pending or self._pending_events
                or self._relabel_due):
            return True
        if self.root is None or self.read_only:
            # re-probe: an SD card may have been inserted, or the USB drive
            # ejected, making storage writable after all
            self.root = self._pick_root()
        if self.root is None or self.read_only:
            self._drop_bounded()
            return False
        need = sum(len(l) for _, l in self._pending) + sum(
            len(l) for l in self._pending_events) + 1024
        if not self._ensure_space(need):
            print("storage full (keeping %dB free); dropping oldest pending"
                  % self.min_free_bytes)
            self._drop_bounded()
            return False
        if self._relabel_due and self._job is None:
            # a clock sync arrived while this was read-only: claim that
            # file before appending, so the new rows can never land in the
            # one the job reads (a job already running claims it when it
            # finishes, _finish_relabel)
            self._ensure_dir(self.data_dir())
            offset, self._relabel_offset = self._relabel_offset, 0
            self._relabel_due = False
            if self._start_relabel(offset) < 0:
                # it could not start: the correction is still owed, and
                # this boot's rows would otherwise be guessed at later
                self._relabel_offset, self._relabel_due = offset, True
        try:
            if self._pending:
                self._ensure_dir(self.data_dir())
                # group by day so a flush spanning midnight lands correctly;
                # anything logged before the clock was set goes to its own
                # file, under this boot's id, until relabel_unsynced() can
                # place it
                by_day = {}
                for ts, tail in self._pending:
                    day = self._day_of(ts)
                    if day == UNSYNCED_DAY:
                        line = "%d,%d,%s\n" % (self._claim_boot_id(), ts, tail)
                    else:
                        line = "%d,%s\n" % (ts, tail)
                    by_day.setdefault(day, []).append(line)
                for day, lines in by_day.items():
                    self._append(
                        "%s/%s.csv" % (self.data_dir(), day),
                        _UNSYNCED_HEADER if day == UNSYNCED_DAY else CSV_HEADER,
                        lines)
                self._pending = []
                del by_day
            if self._pending_events:
                self._append(
                    self.root.rstrip("/") + "/events.csv", EVENTS_HEADER,
                    self._pending_events,
                )
                self._pending_events = []
            try:
                os.sync()
            except (OSError, AttributeError):
                pass
            return True
        except OSError as exc:
            print("storage write failed:", exc)
            self.write_errors += 1
            self.root = self._pick_root()  # re-probe (SD yanked?)
            return False

    def stored_days(self):
        """Day files actually on storage (never the unsynced holding file)."""
        if self.root is None:
            return []
        try:
            return sorted(
                f[:-4] for f in os.listdir(self.data_dir())
                if f.endswith(".csv") and f[:-4] != UNSYNCED_DAY
            )
        except OSError:
            return []

    def list_days(self):
        """Every day a client can ask for -- on storage OR queued in RAM.

        Leaving the RAM-only days out is what made a read-only hub look
        like it had no history at all: the readings were there, just not
        in a file yet, and the browser was never told to ask for them.
        """
        days = self.stored_days()
        for day in self.pending_days():
            if day not in days:
                days.append(day)
        days.sort()
        return days

    def pending_count(self):
        return len(self._pending) + len(self._pending_events)
