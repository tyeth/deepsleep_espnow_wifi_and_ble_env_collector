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
  /sd/events.csv            ts,src,metric,state,prev,value,held_s
  /sd/config.json           runtime config overrides (written by the API)
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

_NOVAL = 0xFFFF  # sentinel for "no reading" in unsigned ring fields

CSV_HEADER = "ts,src,tc,rh,co2,pm1,pm25,pm4,pm10,voc,nox,vb,flags\n"
EVENTS_HEADER = "ts,src,metric,state,prev,value,held_s\n"


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

    def _writable(self, root):
        probe = root.rstrip("/") + "/.dsprobe"
        try:
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            return True
        except OSError:
            return False

    def _pick_root(self):
        """The first writable root, else one that at least holds data.

        A hub whose storage has gone read-only -- USB mass storage mounted
        on a computer, a write-protected or full card -- can still SERVE the
        history it already has. Buffering new readings in RAM and refusing
        to list the days on the card at the same time is the worst of both.
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
                and not self._usb_released:
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
        days = self.list_days()
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
        if (self._pending or self._pending_events) and (
            time.monotonic() - self._last_flush >= self.flush_interval_s
        ):
            self.flush()

    # ---------------- storage I/O ----------------

    def _ensure_dir(self, path):
        try:
            os.mkdir(path)
        except OSError:
            pass  # exists

    def _append(self, path, header, lines):
        need_header = True
        try:
            need_header = os.stat(path)[6] == 0
        except OSError:
            pass  # missing -> header needed
        with open(path, "a") as f:
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
        if not (self._pending or self._pending_events):
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
        try:
            if self._pending:
                self._ensure_dir(self.data_dir())
                # group by day so a flush spanning midnight lands correctly
                by_day = {}
                for ts, tail in self._pending:
                    t = time.localtime(ts)
                    day = "%04d-%02d-%02d" % (t[0], t[1], t[2])
                    by_day.setdefault(day, []).append("%d,%s\n" % (ts, tail))
                for day, lines in by_day.items():
                    self._append(
                        "%s/%s.csv" % (self.data_dir(), day), CSV_HEADER, lines
                    )
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

    def list_days(self):
        if self.root is None:
            return []
        try:
            return sorted(
                f[:-4] for f in os.listdir(self.data_dir())
                if f.endswith(".csv")
            )
        except OSError:
            return []

    def pending_count(self):
        return len(self._pending) + len(self._pending_events)
