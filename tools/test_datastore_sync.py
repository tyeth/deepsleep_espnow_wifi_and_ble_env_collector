#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host-side checks for history sync: RAM-buffered rows and clock relabels.

    python tools/test_datastore_sync.py

Two ways the hub used to hand a browser an empty -- or unusable -- history:

* **Storage is read-only.** A computer holding CIRCUITPY (or a missing SD
  card) means every reading queues in RAM. `list_days()` only listed files,
  and `/api/history?day=` only served files, so the readings were there and
  invisible. They are now listed and served.
* **The clock was set afterwards.** A hub with no RTC battery boots at
  2000-01-01. Those readings went into a 2000-01-01 day file that no later
  clock sync ever corrected. They now go to `data/unsynced.csv` and are
  rewritten into their real day files when the clock arrives.

`datastore` is plain CircuitPython-compatible Python; `net_wifi` needs the
usual board modules stubbed, exactly as tools/test_http_headers.py does.
"""

import os
import shutil
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.join(HERE, "..", "collector")
TMP = os.path.join(HERE, "_dstest").replace("\\", "/")

for name in ("wifi", "socketpool", "ssl", "certstore", "adafruit_ntp"):
    mod = types.ModuleType(name)
    if name == "wifi":
        mod.radio = types.SimpleNamespace(connected=False, ipv4_address=None)
    if name == "certstore":
        mod.HOST = "test.invalid"
        mod.load = lambda *a, **k: None
        mod.paths = lambda *a, **k: (None, None)
    sys.modules.setdefault(name, mod)

sys.path.insert(0, COLLECTOR)
import datastore  # noqa: E402
import net_wifi  # noqa: E402

FAILURES = []

# a plausible clock (2026-09-11 12:00 UTC-ish) and the boot clock a board
# with no RTC battery actually reports
SYNCED_TS = 1789041600
BOOT_TS = 946684800          # 2000-01-01
OFFSET = SYNCED_TS - BOOT_TS


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILURES.append(name)


def new_store(**kw):
    """A store rooted in a clean temp dir, flushing only when told to."""
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    opts = {"roots": (TMP,), "flush_interval_s": 10 ** 6,
            "flush_max_pending": 10 ** 6}
    opts.update(kw)
    return datastore.DataStore(**opts)


def go_read_only(store):
    """Pretend a computer has taken the drive: nothing is writable now."""
    store._writable = lambda root: False
    store.root = store._pick_root()


def go_writable(store):
    """...and has given it back."""
    del store._writable
    store.root = store._pick_root()
    store.read_only = False


def day_file(day):
    return "%s/data/%s.csv" % (TMP, day)


def read(path):
    with open(path) as f:
        return f.read()


def rows_of(text):
    return [l for l in text.strip().split("\n")
            if l and not l.startswith("ts,") and not l.startswith("boot,")]


def unsynced_file(suffix=""):
    return "%s/data/unsynced.csv%s" % (TMP, suffix)


def all_day_rows():
    """(ts, src, flags) of every row in every real day file, in file order."""
    out = []
    for name in sorted(os.listdir(TMP + "/data")):
        if name.endswith(".csv") and name[:4].isdigit():
            for line in rows_of(read("%s/data/%s" % (TMP, name))):
                parts = line.split(",")
                out.append((int(parts[0]), parts[1], int(parts[-1])))
    return out


def reboot(**kw):
    """A new store on the SAME storage: what a power cut leaves behind."""
    opts = {"roots": (TMP,), "flush_interval_s": 10 ** 6,
            "flush_max_pending": 10 ** 6}
    opts.update(kw)
    return datastore.DataStore(**opts)


# The hub's clock, as datastore sees it: None is the host's (synced) clock,
# an epoch pins it -- BOOT_TS is a board that came up with no clock at all.
# Records get explicit timestamps anyway; this decides what a fresh store
# does at boot (relabel earlier boots, or wait) and where "now" is.
HUB_NOW = [None]


class _HubClock:
    def time(self):
        return HUB_NOW[0] if HUB_NOW[0] is not None else _real_time.time()

    def monotonic(self):
        return _real_time.monotonic()

    def localtime(self, *a):
        return _real_time.localtime(*a)


import time as _real_time  # noqa: E402
datastore.time = _HubClock()


def hub_clock(epoch):
    HUB_NOW[0] = epoch


# microcontroller.nvm as datastore finds it: absent on the host unless a
# test installs this stand-in (datastore imports it lazily, per call)
def nvm_install():
    mod = types.ModuleType("microcontroller")
    mod.nvm = bytearray(16)
    sys.modules["microcontroller"] = mod
    return mod.nvm


def nvm_remove():
    sys.modules.pop("microcontroller", None)


def nvm_id(nvm):
    return (nvm[2] | (nvm[3] << 8)) if nvm[1] == 0xB7 else 0


class FakeConn:
    def __init__(self):
        self.file = None
        self.left = None
        self.tail = None


def main():
    m = {"tc": 21.5, "rh": 48.0, "co2": 700}

    print("storage is read-only: the readings are in RAM, and reachable")
    store = new_store()
    go_read_only(store)
    day = store._day_of(SYNCED_TS)
    store.record("local", m, ts=SYNCED_TS)
    store.record("local", m, ts=SYNCED_TS + 60)
    check("nothing reached storage", store.flush() is False)
    # nothing has ever been written here, so there is not even a readable
    # data dir to fall back to: the store has no root at all
    check("the store knows it cannot write",
          store.root is None or store.read_only)
    check("the day is still listed", store.list_days() == [day])
    csv = store.pending_csv(day).decode()
    check("its rows are served from RAM", len(rows_of(csv)) == 2)
    check("with a header, since no file exists yet", csv.startswith("ts,src,"))
    check("and the right timestamps",
          rows_of(csv)[0].startswith("%d,local," % SYNCED_TS))
    check("another day has nothing pending",
          store.pending_csv("2000-01-02") == b"")

    print("the drive comes back: the queue lands in the day file")
    go_writable(store)
    check("flush succeeds", store.flush() is True)
    check("both readings were written", len(rows_of(read(day_file(day)))) == 2)
    check("nothing is left in RAM", store.pending_count() == 0)
    check("and nothing is served twice", store.pending_csv(day) == b"")

    print("a hub with no clock keeps its readings apart from the day files")
    store = new_store()
    store.record("local", m, ts=BOOT_TS)
    store.record("local", m, ts=BOOT_TS + 120)
    check("they are not advertised as a day", store.list_days() == [])
    check("nor served as one", store.pending_csv("2000-01-01") == b"")
    store.flush()
    check("they are on storage, in unsynced.csv",
          len(rows_of(read("%s/data/unsynced.csv" % TMP))) == 2)
    check("no 2000-01-01 day file was created",
          not os.path.exists(day_file("2000-01-01")))
    check("and list_days stays empty", store.list_days() == [])

    print("the browser sets the clock: stored records are relabelled")
    moved = store.relabel_unsynced(OFFSET)
    day = store._day_of(BOOT_TS + OFFSET)
    check("both records moved", moved == 2)
    check("the holding file is gone",
          not os.path.exists("%s/data/unsynced.csv" % TMP))
    body = read(day_file(day))
    check("they are in the real day file", len(rows_of(body)) == 2)
    check("with a header", body.startswith("ts,src,"))
    check("and shifted timestamps",
          rows_of(body)[0].startswith("%d,local," % (BOOT_TS + OFFSET)))
    check("the day is listed now", store.list_days() == [day])

    print("a clock sync while the drive is held is paid off later")
    store = new_store()
    store.record("local", m, ts=BOOT_TS)
    store.flush()
    go_read_only(store)
    check("the rewrite cannot run yet", store.relabel_unsynced(OFFSET) == 0)
    check("it is remembered", store._relabel_offset == OFFSET)
    go_writable(store)
    store.record("local", m, ts=SYNCED_TS + 300)
    store.flush()
    check("the flush relabelled the stored record",
          len(rows_of(read(day_file(store._day_of(BOOT_TS + OFFSET))))) >= 1)
    check("the debt is cleared", store._relabel_offset == 0)
    check("unsynced.csv is gone",
          not os.path.exists("%s/data/unsynced.csv" % TMP))

    print("a relabel interrupted before it planned anything is put back")
    store = new_store()
    store.record("local", m, ts=BOOT_TS)
    store.flush()
    os.rename(unsynced_file(), unsynced_file(".moving"))
    hub_clock(BOOT_TS)               # the next boot has no clock either
    store = reboot()
    check("the file is back", os.path.exists(unsynced_file()))
    check("and nothing else is left", not os.path.exists(unsynced_file(".moving")))
    hub_clock(None)
    check("and it waits for the sync that places it",
          store.relabel_unsynced(0, boot_real=SYNCED_TS) == 1)
    check("as an earlier boot's, flagged estimated",
          all_day_rows()[0][2] & datastore.FLAG_ESTIMATED)

    print("a day that is half on storage and half in RAM")
    store = new_store()
    store.record("local", m, ts=SYNCED_TS)
    store.flush()
    go_read_only(store)
    store.record("local", m, ts=SYNCED_TS + 60)
    day = store._day_of(SYNCED_TS)
    tail = store.pending_csv(day)
    check("only the queued row is in the tail", len(rows_of(tail.decode())) == 1)
    check("and it brings no second header", not tail.startswith(b"ts,"))

    print("the history API sends the file and the queued rows as one CSV")
    portal = net_wifi.WebPortal.__new__(net_wifi.WebPortal)
    portal.handlers = {
        "list_days": store.list_days,
        "pending_csv": store.pending_csv,
        "data_dir": store.data_dir,
    }
    resp = portal._route("GET", "/api/history", {}, b"")
    check("the day list is JSON", resp[0] == 200 and day.encode() in resp[2])
    resp = portal._route("GET", "/api/history", {"day": day}, b"")
    check("a day with queued rows is a file+tail response",
          resp[0] == "filetail" and resp[2] == tail)
    c = FakeConn()
    head = portal._file_tail_head(c, resp[1], resp[2], True).decode()
    size = os.path.getsize(day_file(day))
    check("200", head.split(" ", 2)[1] == "200")
    check("length covers file and tail",
          ("Content-Length: %d" % (size + len(tail))) in head)
    check("csv content type", "Content-Type: text/csv" in head)
    check("never cached", "Cache-Control: no-store" in head)
    check("the file is streamed first", c.left == size)
    check("the queued rows follow it", c.tail == tail)
    served = c.file.read(c.left) + c.tail
    c.file.close()
    check("the client sees both readings", len(rows_of(served.decode())) == 2)
    check("in time order",
          served.decode().index("%d,local" % SYNCED_TS)
          < served.decode().index("%d,local" % (SYNCED_TS + 60)))

    print("a day with nothing on storage at all")
    store = new_store()
    go_read_only(store)
    store.record("local", m, ts=SYNCED_TS)
    day = store._day_of(SYNCED_TS)
    tail = store.pending_csv(day)
    portal.handlers = {
        "list_days": store.list_days,
        "pending_csv": store.pending_csv,
        "data_dir": store.data_dir,
    }
    resp = portal._route("GET", "/api/history", {"day": day}, b"")
    check("still served", resp[0] == "filetail")
    c = FakeConn()
    head = portal._file_tail_head(c, resp[1], resp[2], True).decode()
    check("no file to stream", c.file is None)
    check("length is just the queued rows",
          ("Content-Length: %d" % len(tail)) in head)
    check("which carry the header", c.tail.startswith(b"ts,src,"))

    print("a day with nothing queued is served the same way: never cached")
    store = new_store()
    store.record("local", m, ts=SYNCED_TS)
    store.flush()
    day = store._day_of(SYNCED_TS)
    portal.handlers = {
        "list_days": store.list_days,
        "pending_csv": store.pending_csv,
        "data_dir": store.data_dir,
    }
    resp = portal._route("GET", "/api/history", {"day": day}, b"")
    check("file+tail head, empty tail", resp[0] == "filetail" and resp[2] == b"")
    c = FakeConn()
    head = portal._file_tail_head(c, resp[1], resp[2], True).decode()
    check("length is the file", ("Content-Length: %d" % os.path.getsize(day_file(day))) in head)
    check("and it is not cacheable -- today grows, a sync rewrites days",
          "no-store" in head and "max-age" not in head)
    c.file.close()

    print("an unknown day is still an error, not an empty CSV")
    resp = portal._route("GET", "/api/history", {"day": "2019-01-01"}, b"")
    check("404-ish JSON", resp[0] == 200 and b"no such day" in resp[2])

    # ------------------------------------------------------------------
    # Several boots without a clock, then one sync. Every power cut sends
    # the clock back to 2000-01-01, so the boots' rows share one timestamp
    # range; the boot id kept in NVM (and in the file) is what keeps them
    # apart, and the sync must place all of them without a collision --
    # the analyzer drops rows that share ts+src.
    # ------------------------------------------------------------------
    print("three boots without a clock are told apart by their boot id")
    nvm = nvm_install()
    hub_clock(BOOT_TS)
    store = new_store()
    # boot 1 ran ~20 min; one of its readings was out of spec
    store.record("local", m, ts=BOOT_TS + 600, flags=datastore.FLAG_ABNORMAL)
    store.record("local", m, ts=BOOT_TS + 1200)
    store.flush()
    check("boot 1 took id 1", store.boot_id == 1 and nvm_id(nvm) == 1)
    check("nothing is advertised as a day yet", store.list_days() == [])
    # boot 2: a power cut, the clock starts over, two sources this time
    store = reboot()
    check("a fresh boot has no id until it writes", store.boot_id == 0)
    store.record("local", m, ts=BOOT_TS + 600)
    store.record("node1", m, ts=BOOT_TS + 600)
    store.flush()
    check("boot 2 took id 2", store.boot_id == 2 and nvm_id(nvm) == 2)
    text = read(unsynced_file())
    check("the holding file has its own header",
          text.startswith("boot,ts,src,"))
    check("and each row names its boot",
          "1,%d,local," % (BOOT_TS + 600) in text
          and "2,%d,local," % (BOOT_TS + 600) in text)
    # boot 3: another power cut; runs 1900 s, then a browser sets the clock
    store = reboot()
    for k in (600, 1200, 1800):
        store.record("local", m, ts=BOOT_TS + k)
    store.flush()
    check("boot 3 took id 3", store.boot_id == 3)

    print("the sync places all three boots: exact, ordered, no collisions")
    delta = SYNCED_TS - (BOOT_TS + 1900)     # what the clock had to move
    boot_real = SYNCED_TS - 1900             # when this boot really began
    hub_clock(SYNCED_TS)
    moved = store.relabel_unsynced(delta, boot_real=boot_real)
    check("every stored row moved", moved == 7)
    check("the holding file and its scaffolding are gone",
          not any(os.path.exists(unsynced_file(s))
                  for s in ("", ".moving", ".plan")))
    check("the boot counter is back to 0",
          nvm_id(nvm) == 0 and store.boot_id == 0)
    rows = all_day_rows()
    check("nothing was dropped", len(rows) == 7)
    check("no two rows share ts+src",
          len(set((ts, src) for ts, src, _ in rows)) == 7)
    exact = sorted(ts for ts, _, fl in rows
                   if not fl & datastore.FLAG_ESTIMATED)
    check("this boot's rows carry the measured correction, unflagged",
          exact == [BOOT_TS + k + delta for k in (600, 1200, 1800)])
    est = sorted((ts, src, fl) for ts, src, fl in rows
                 if fl & datastore.FLAG_ESTIMATED)
    check("the earlier boots' rows are flagged estimated", len(est) == 4)
    check("boot 2 ended just before this boot began",
          [(ts, src) for ts, src, _ in est if ts == boot_real - 60]
          == [(boot_real - 60, "local"), (boot_real - 60, "node1")])
    # boot 2's row was 600 s into its run, so it powered on 660 s before
    # this boot did; boot 1 ends a minute before that, its 600 s spacing kept
    check("boot 1 ended before boot 2 powered on, its own spacing intact",
          [ts for ts, _, _ in est if ts < boot_real - 60]
          == [boot_real - 720 - 600, boot_real - 720])
    check("and its abnormal flag survived alongside the new bit",
          est[0][2] == datastore.FLAG_ABNORMAL | datastore.FLAG_ESTIMATED)
    check("the sync reports how far back the history changed",
          store.last_relabel == (7, boot_real - 1320))
    check("the days are listed now", len(store.list_days()) >= 1)

    print("a soft reset keeps the RTC running: that boot's rows stay exact")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 600)
    store.flush()
    # `reset` over the API at boot-clock +2000: the clock does not restart
    store = reboot()
    store.record("local", m, ts=BOOT_TS + 2600)
    store.flush()
    delta = SYNCED_TS - (BOOT_TS + 2700)     # synced 700 s into this boot
    boot_real = SYNCED_TS - 700
    hub_clock(SYNCED_TS)
    check("both rows moved", store.relabel_unsynced(delta, boot_real=boot_real) == 2)
    rows = sorted(all_day_rows())
    check("the earlier boot shares the clock and the exact offset",
          rows[0][0] == BOOT_TS + 600 + delta)
    check("but is still marked as placed by inference",
          rows[0][2] & datastore.FLAG_ESTIMATED)
    check("this boot's row is exact", rows[1] == (BOOT_TS + 2600 + delta, "local", 0))

    print("NTP at boot places what earlier boots left, with no offset at all")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 60)
    store.record("local", m, ts=BOOT_TS + 120)
    store.flush()
    hub_clock(SYNCED_TS)                    # this boot came up with a clock
    store = reboot()
    check("the holding file was emptied at boot", not os.path.exists(unsynced_file()))
    rows = all_day_rows()
    check("both rows are in day files", len(rows) == 2)
    check("flagged estimated, spacing intact",
          all(fl & datastore.FLAG_ESTIMATED for _, _, fl in rows)
          and rows[1][0] - rows[0][0] == 60)
    check("and the store says so", store.last_relabel[0] == 2
          and store.last_relabel[1] == rows[0][0])
    check("the counter is back to 0 for the next unsynced boot",
          nvm_id(nvm) == 0)

    print("a wiped NVM does not reuse an id the file still holds")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    check("boot 1", store.boot_id == 1)
    nvm[:] = bytes(len(nvm))                # a firmware reflash took NVM
    store = reboot()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    check("the file said 1, so this is boot 2", store.boot_id == 2)
    print("...and a board with no NVM runs on the file alone")
    nvm_remove()
    store = reboot()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    check("boot 3", store.boot_id == 3)
    delta = SYNCED_TS - (BOOT_TS + 100)
    hub_clock(SYNCED_TS)
    check("all three boots placed",
          store.relabel_unsynced(delta, boot_real=SYNCED_TS - 100) == 3)
    rows = all_day_rows()
    check("three distinct rows of one source",
          len(set(ts for ts, _, _ in rows)) == 3)
    check("in boot order", [ts for ts, _, _ in rows] == sorted(ts for ts, _, _ in rows))
    nvm = nvm_install()

    print("a relabel cut by a power cut finishes with the plan it committed")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 60)
    store.record("local", m, ts=BOOT_TS + 120)
    store.flush()
    store = reboot()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    delta = SYNCED_TS - (BOOT_TS + 100)
    boot_real = SYNCED_TS - 100
    # what a completed relabel would produce...
    import copy
    snapshot = copy.deepcopy(read(unsynced_file()))
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    expect = sorted(all_day_rows())
    # ...now the same file again, and the power goes after one row moved
    shutil.rmtree(TMP + "/data")
    os.makedirs(TMP + "/data")
    with open(unsynced_file(".moving"), "w") as f:
        f.write(snapshot)
    store.boot_id = 2        # the plan was boot 2's, made before it finished
    plan = store._plan_relabel(unsynced_file(".moving"), delta, boot_real)
    with open(unsynced_file(".plan"), "w") as f:
        for boot in plan:
            f.write("%d,%d,%d\n" % (boot, plan[boot][0], plan[boot][1]))
    first_ts, first_src, first_fl = expect[0]
    with open(day_file(store._day_of(first_ts)), "w") as f:
        f.write(datastore.CSV_HEADER)
        f.write("%d,%s,21.5,48.0,700,,,,,,,,%d\n" % (first_ts, first_src, first_fl))
    hub_clock(BOOT_TS)                       # the next boot: no clock again
    store = reboot()
    check("the scaffolding is cleaned up",
          not any(os.path.exists(unsynced_file(s)) for s in ("", ".moving", ".plan")))
    rows = all_day_rows()
    check("every row is present", set(rows) == set(expect))
    check("the row moved twice is identical, so the analyzer folds it",
          len(rows) == len(expect) + 1)
    check("the counter is back to 0", nvm_id(nvm) == 0)

    print("a put-back that finds a newer holding file appends to it")
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    os.rename(unsynced_file(), unsynced_file(".moving"))
    # this boot could not put it back (storage was the host's at the time)
    # and has since written a holding file of its own
    orig = datastore.DataStore._recover_unsynced
    datastore.DataStore._recover_unsynced = lambda self: None
    store = reboot()
    datastore.DataStore._recover_unsynced = orig
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    check("two files exist for a moment",
          os.path.exists(unsynced_file()) and os.path.exists(unsynced_file(".moving")))
    store = reboot()
    text = read(unsynced_file())
    check("one file again", not os.path.exists(unsynced_file(".moving")))
    check("with one header", text.count("boot,ts,") == 1)
    check("and both boots' rows", len(rows_of(text)) == 2
          and "1,%d,local" % (BOOT_TS + 60) in text
          and "2,%d,local" % (BOOT_TS + 60) in text)
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    check("and the next id clears both", store.boot_id == 3)

    print("a synced boot on read-only storage pays the relabel off later")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    hub_clock(SYNCED_TS)
    orig = datastore.DataStore._writable
    datastore.DataStore._writable = lambda self, root: False
    store = reboot()
    datastore.DataStore._writable = orig
    check("nothing could be written at boot", store.read_only)
    check("so the relabel is owed", store._relabel_due)
    check("and the file is untouched", os.path.exists(unsynced_file()))
    store.root = store._pick_root()
    store.read_only = False
    check("the first flush that can write pays it", store.flush() is True)
    check("the file is gone", not os.path.exists(unsynced_file()))
    check("and the row is in a day file", len(all_day_rows()) == 1)
    check("nothing is owed any more", not store._relabel_due)
    print("...even when a browser nudged the already-real clock meanwhile")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    hub_clock(SYNCED_TS)
    datastore.DataStore._writable = lambda self, root: False
    store = reboot()
    datastore.DataStore._writable = orig
    store.relabel_unsynced(600)             # a phone 10 min ahead of NTP
    check("the nudge is owed on top", store._relabel_offset == 600)
    store.root = store._pick_root()
    store.read_only = False
    store.flush()
    rows = all_day_rows()
    check("the earlier boot's row was placed, not kept",
          not os.path.exists(unsynced_file()) and len(rows) == 1)
    check("before this boot began, flagged",
          rows[0][0] < SYNCED_TS and rows[0][2] & datastore.FLAG_ESTIMATED)

    print("this boot's own rows are never guessed at")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    check("a relabel with no correction keeps them",
          store.relabel_unsynced(0, boot_real=SYNCED_TS) == 0)
    check("in the holding file, boot id intact",
          "1,%d,local" % (BOOT_TS + 60) in read(unsynced_file()))
    check("the counter is kept too", store.boot_id == 1 and nvm_id(nvm) == 1)
    hub_clock(SYNCED_TS)
    check("and the real sync places them",
          store.relabel_unsynced(SYNCED_TS - (BOOT_TS + 100),
                                 boot_real=SYNCED_TS - 100) == 1)

    print("a one-row boot that died a second before the next one is not a chain")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 600)
    store.flush()
    store = reboot()
    store.record("local", m, ts=BOOT_TS + 601)   # jitter: one second later
    store.flush()
    delta = SYNCED_TS - (BOOT_TS + 700)
    hub_clock(SYNCED_TS)
    check("both placed", store.relabel_unsynced(delta) == 2)
    rows = sorted(all_day_rows())
    check("the earlier boot ends a minute before this one powered on",
          rows[0][0] == BOOT_TS + delta - 60 and rows[0][2] & datastore.FLAG_ESTIMATED)
    check("this boot's row is exact", rows[1] == (BOOT_TS + 601 + delta, "local", 0))

    print("a row torn by a power cut cannot fuse with the next boot's rows")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 600)
    store.record("local", m, ts=BOOT_TS + 660)
    store.flush()
    text = read(unsynced_file())
    with open(unsynced_file(), "w") as f:
        f.write(text[:-12])                    # the power went mid-row
    store = reboot()
    store.record("local", m, ts=BOOT_TS + 600)
    store.flush()
    lines = read(unsynced_file()).split("\n")
    check("the append mended the line first",
          any(l.startswith("2,%d,local" % (BOOT_TS + 600)) for l in lines))
    check("a stub is not a row, whichever end was torn",
          datastore._parse_unsynced("1,9466") is None
          and datastore._parse_unsynced("1,946685460,local,21.5,48.0,") is None
          and datastore._parse_unsynced(
              "1,946685460,local,21.5,48.0,700,,,,,,,,0") is not None)
    delta = SYNCED_TS - (BOOT_TS + 700)
    hub_clock(SYNCED_TS)
    check("the intact rows are placed, the stub dropped",
          store.relabel_unsynced(delta) == 2)
    check("nothing was kept back", not os.path.exists(unsynced_file()))
    check("and the counter is free again", nvm_id(nvm) == 0)

    print("finishing an old relabel mid-sync does not cost this boot its id")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    # a synced boot planned boot 1's relabel and lost power before the end
    os.rename(unsynced_file(), unsynced_file(".moving"))
    store.boot_id = 0
    plan = store._plan_relabel(unsynced_file(".moving"), 0, boot_real=SYNCED_TS - 9000)
    with open(unsynced_file(".plan"), "w") as f:
        for boot in plan:
            f.write("%d,%d,%d\n" % (boot, plan[boot][0], plan[boot][1]))
    # this boot came up read-only, so it could not finish it, and has
    # since logged rows of its own
    orig = datastore.DataStore._recover_unsynced
    datastore.DataStore._recover_unsynced = lambda self: None
    store = reboot()
    datastore.DataStore._recover_unsynced = orig
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    check("this is boot 2", store.boot_id == 2)
    delta = SYNCED_TS - (BOOT_TS + 100)
    hub_clock(SYNCED_TS)
    check("the sync moves this boot's row", store.relabel_unsynced(delta) == 1)
    rows = sorted(all_day_rows())
    check("boot 1 was finished with its old plan, estimated",
          len(rows) == 2 and rows[0][2] & datastore.FLAG_ESTIMATED)
    check("this boot's row is exact, not guessed at as an earlier boot",
          rows[1] == (BOOT_TS + 60 + delta, "local", 0))
    check("and only now is the counter free", nvm_id(nvm) == 0)

    print("a sync with no storage at all keeps the correction for later")
    hub_clock(BOOT_TS)
    store = new_store()
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    store = reboot(roots=(TMP + "/gone",))    # the card was pulled
    check("no root", store.root is None)
    hub_clock(SYNCED_TS)
    check("nothing to move yet", store.relabel_unsynced(12345) == 0)
    check("but the correction is owed, not dropped",
          store._relabel_due and store._relabel_offset == 12345)

    print("rows from before the boot column existed count as an earlier boot")
    hub_clock(BOOT_TS)
    nvm[:] = bytes(len(nvm))     # (the pulled card above still holds boot 1)
    store = new_store()
    os.makedirs(TMP + "/data", exist_ok=True)
    with open(unsynced_file(), "w") as f:
        f.write(datastore.CSV_HEADER)
        f.write("%d,local,21.5,48.0,700,,,,,,,,0\n" % (BOOT_TS + 60))
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    check("a legacy row does not steal id 0 from us", store.boot_id == 1)
    hub_clock(SYNCED_TS)
    check("both rows placed", store.relabel_unsynced(
        SYNCED_TS - (BOOT_TS + 100), boot_real=SYNCED_TS - 100) == 2)
    rows = sorted(all_day_rows())
    check("the legacy row before this boot's, flagged",
          rows[0][2] & datastore.FLAG_ESTIMATED and rows[1][2] == 0)

    hub_clock(None)
    nvm_remove()
    shutil.rmtree(TMP, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILED: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
