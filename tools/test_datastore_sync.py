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

The rewrite is a job the hub's main loop steps through (`relabel_step`),
not one blocking pass; `drain()` below plays the main loop, a few rows a
step, so every relabel here is exercised chunked. The last groups pin what
chunking must not change: the final state, resumption after a power cut
mid-move, progress that only goes forwards, and a pause while storage is
read-only.

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
    """(ts, src, flags) of every row in every real day file, in file order.
    A torn line (a power cut's fragment) is not a row, as the analyzer
    also sees it."""
    out = []
    for name in sorted(os.listdir(TMP + "/data")):
        if name.endswith(".csv") and name[:4].isdigit():
            for line in rows_of(read("%s/data/%s" % (TMP, name))):
                parts = line.split(",")
                if len(parts) != datastore.CSV_HEADER.count(",") + 1:
                    continue
                out.append((int(parts[0]), parts[1], int(parts[-1])))
    return out


def reboot(**kw):
    """A new store on the SAME storage: what a power cut leaves behind."""
    opts = {"roots": (TMP,), "flush_interval_s": 10 ** 6,
            "flush_max_pending": 10 ** 6}
    opts.update(kw)
    return datastore.DataStore(**opts)


def drain(store, max_rows=3, **kw):
    """Play the main loop: step a queued relabel until nothing is pending,
    and return the rows moved meanwhile (a job and any queued behind it).
    A few rows a step by default, so the chunking is what gets tested; the
    hub's own wall-clock budget is far too generous for a host to hit."""
    before = store.relabel_moved_total
    steps = 0
    while store.relabel_pending():
        store.relabel_step(max_rows=max_rows, **kw)
        steps += 1
        if steps > 100000:
            raise AssertionError("relabel never finished")
    return store.relabel_moved_total - before


def relabel_all(store, offset_s, boot_real=None, **kw):
    """A clock sync and the main loop passes that follow it: rows moved."""
    store.relabel_unsynced(offset_s, boot_real=boot_real)
    return drain(store, **kw)


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

    def monotonic_ns(self):
        return _real_time.monotonic_ns()

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
    queued = store.relabel_unsynced(OFFSET)
    check("the sync queues the work and says how much",
          queued == os.path.getsize(unsynced_file(".moving"))
          and store.relabel_pending())
    check("nothing has moved yet", all_day_rows() == [])
    moved = drain(store)
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
    check("the flush queued the relabel it owed", store.relabel_pending()
          and store.relabel_status()["state"] == "planning")
    drain(store)
    check("and the loop relabelled the stored record",
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
          relabel_all(store, 0, boot_real=SYNCED_TS) == 1)
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
    moved = relabel_all(store, delta, boot_real=boot_real)
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
    check("both rows moved", relabel_all(store, delta, boot_real=boot_real) == 2)
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
    # queued, not done: boot is also when the radios and the display come
    # up, and a synchronous pass here was the same stall as in the sync
    check("the relabel is queued at boot, not run", store.relabel_pending()
          and os.path.exists(unsynced_file(".moving")) and all_day_rows() == [])
    st = store.relabel_status()
    check("and a client can see it from the first pass",
          st["state"] == "planning" and st["pct"] == 0
          and st["bytes_total"] == os.path.getsize(unsynced_file(".moving")))
    check("the loop empties the holding file",
          drain(store) == 2 and not os.path.exists(unsynced_file()))
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
          relabel_all(store, delta, boot_real=SYNCED_TS - 100) == 3)
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
    relabel_all(store, delta, boot_real=boot_real)
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
    check("the plan is adopted as this boot's job, from the top",
          store.relabel_pending() and store.relabel_status()["state"] == "moving"
          and store.relabel_status()["bytes_done"] == 0)
    drain(store)
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
    check("the first flush that can write queues it", store.flush() is True
          and store.relabel_pending())
    check("and the loop pays it", drain(store) == 1)
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
    drain(store)
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
          relabel_all(store, 0, boot_real=SYNCED_TS) == 0)
    check("in the holding file, boot id intact",
          "1,%d,local" % (BOOT_TS + 60) in read(unsynced_file()))
    check("the counter is kept too", store.boot_id == 1 and nvm_id(nvm) == 1)
    check("and the job says so", store.relabel_status()["last"]["kept"] == 1)
    hub_clock(SYNCED_TS)
    check("and the real sync places them",
          relabel_all(store, SYNCED_TS - (BOOT_TS + 100),
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
    check("both placed", relabel_all(store, delta) == 2)
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
          relabel_all(store, delta) == 2 and store.relabel_status()["last"]["torn"] == 1)
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
    store.relabel_unsynced(delta)
    check("the old plan is adopted first, this boot's file queued behind it",
          store.relabel_status()["state"] == "moving" and store._relabel_due
          and os.path.exists(unsynced_file()))
    check("the loop finishes both: boot 1's row, then this boot's",
          drain(store) == 2 and not store._relabel_due)
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
    check("both rows placed", relabel_all(
        store, SYNCED_TS - (BOOT_TS + 100), boot_real=SYNCED_TS - 100) == 2)
    rows = sorted(all_day_rows())
    check("the legacy row before this boot's, flagged",
          rows[0][2] & datastore.FLAG_ESTIMATED and rows[1][2] == 0)

    # ------------------------------------------------------------------
    # The job itself. A hub that logged for days without a clock has
    # hundreds of KB to move; done in one pass inside the request that set
    # the clock, that was seconds of serving nothing. Stepped from the
    # main loop, the outcome must be the same as the one pass was, a
    # power cut mid-way must cost redone rows and nothing else, and a
    # client must be able to watch it.
    # ------------------------------------------------------------------
    print("stepped a row at a time, the relabel lands exactly where one pass did")

    def three_boots():
        """Three unsynced boots, two sources, ~30 rows; returns the file."""
        hub_clock(BOOT_TS)
        nvm[:] = bytes(len(nvm))
        s = new_store()
        for k in range(8):
            s.record("local", m, ts=BOOT_TS + 300 + 60 * k)
            s.record("node1", m, ts=BOOT_TS + 300 + 60 * k, flags=k & 1)
        s.flush()
        s = reboot()
        for k in range(6):
            s.record("local", m, ts=BOOT_TS + 100 + 120 * k)
        s.flush()
        s = reboot()
        for k in range(8):
            s.record("local", m, ts=BOOT_TS + 400 + 60 * k)
        s.flush()
        return s, read(unsynced_file())

    def restore(snapshot, boot_id):
        """The same file again, in a store that is boot `boot_id`."""
        shutil.rmtree(TMP + "/data")
        os.makedirs(TMP + "/data")
        with open(unsynced_file(), "w") as f:
            f.write(snapshot)
        hub_clock(BOOT_TS)
        s = reboot()
        s.boot_id = boot_id
        return s

    store, snapshot = three_boots()
    check("the file holds 30 rows of three boots", len(rows_of(snapshot)) == 30
          and store.boot_id == 3)
    delta = SYNCED_TS - (BOOT_TS + 900)
    boot_real = SYNCED_TS - 900
    hub_clock(SYNCED_TS)
    # a plan step and a move step with no bound to speak of: the old one pass
    moved = relabel_all(store, delta, boot_real=boot_real, max_rows=10 ** 6)
    check("one pass moves them all", moved == 30 and store.relabel_status()["last"]["steps"] == 2)
    expect_rows = sorted(all_day_rows())
    expect_files = {n: read("%s/data/%s" % (TMP, n)) for n in sorted(os.listdir(TMP + "/data"))}
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    # (the file's size on disk, not the text's: this host may write CRLF)
    size = store.relabel_status()["bytes_total"]
    seen = []                      # what a client polling every pass sees
    while store.relabel_pending():
        seen.append(store.relabel_status())
        store.relabel_step(max_rows=1)
    check("a row a step moves them all", sorted(all_day_rows()) == expect_rows)
    check("into byte-identical day files",
          {n: read("%s/data/%s" % (TMP, n)) for n in sorted(os.listdir(TMP + "/data"))}
          == expect_files)
    check("it took one step per line, per phase", 60 < len(seen) < 70)
    check("and the counter is back to 0", store.boot_id == 0 and nvm_id(nvm) == 0)

    print("its progress only goes forwards, and ends at the total")
    plan_steps = [s for s in seen if s["state"] == "planning"]
    move_steps = [s for s in seen if s["state"] == "moving"]
    check("the plan pass comes first, then the move",
          seen[:len(plan_steps)] == plan_steps and plan_steps and move_steps
          and len(plan_steps) + len(move_steps) == len(seen))
    # (the step that finds the end of the file reports the same byte count
    # as the one before it: a phase ends when a read comes back empty)
    check("bytes read climb through the file in each phase, from the top",
          plan_steps[0]["bytes_done"] == 0 and move_steps[0]["bytes_done"] == 0
          and all(a["bytes_done"] <= b["bytes_done"] for a, b in zip(plan_steps, plan_steps[1:]))
          and all(a["bytes_done"] <= b["bytes_done"] for a, b in zip(move_steps, move_steps[1:]))
          and plan_steps[-1]["bytes_done"] == move_steps[-1]["bytes_done"] == size
          and all(s["bytes_total"] == size for s in seen))
    check("the one number a bar needs never falls",
          all(a["pct"] <= b["pct"] for a, b in zip(seen, seen[1:]))
          and seen[0]["pct"] == 0 and plan_steps[-1]["pct"] == 25
          and move_steps[0]["pct"] == 25 and move_steps[-1]["pct"] == 100)
    check("rows are counted once the plan knows the total",
          all(s["rows_total"] is None for s in plan_steps)
          and all(s["rows_total"] == 30 for s in move_steps)
          and all(a["rows_done"] <= b["rows_done"] for a, b in zip(move_steps, move_steps[1:]))
          and move_steps[-1]["rows_done"] == 30)
    last = store.relabel_status()
    check("done, the status is idle with a timeable summary",
          last["state"] == "idle" and last["last"]["rows"] == 30
          and last["last"]["steps"] == len(seen)
          and last["last"]["elapsed_ms"] >= last["last"]["work_ms"] >= 0
          and last["last"]["rows_per_s"] > 0 and last["last"]["at"] == SYNCED_TS
          and last["last"]["span_s"] == SYNCED_TS - expect_rows[0][0])
    check("a step with nothing pending is a no-op",
          store.relabel_step() is None and store.relabel_status() == last)

    print("a power cut mid-move resumes from the last checkpoint, not the top")
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    saved_cp = datastore._CHECKPOINT_BYTES
    datastore._CHECKPOINT_BYTES = 200         # every ~4 rows, for the test
    store.relabel_unsynced(delta, boot_real=boot_real)
    while store.relabel_status()["state"] != "moving":
        store.relabel_step(max_rows=5)
    for _ in range(5):                        # 25 rows: a few checkpoints in
        store.relabel_step(max_rows=5)
    store.relabel_step(max_rows=2)            # ...and two rows past the last
    plan_text = read(unsynced_file(".plan"))
    cp_lines = [l for l in plan_text.split("\n") if l.startswith("@")]
    check("the plan records progress as it goes",
          plan_text.startswith("#30,%d\n" % size) and len(cp_lines) >= 3)
    cp_pos = int(cp_lines[-1][1:].split(",")[0])
    before = store.relabel_status()
    check("...behind the job itself, by design",
          0 < cp_pos <= before["bytes_done"] < size)
    hub_clock(BOOT_TS)                        # the power went; no clock again
    store = reboot()
    st = store.relabel_status()
    check("the next boot resumes at the checkpoint",
          st["state"] == "moving" and st["bytes_done"] == cp_pos
          and st["rows_total"] == 30 and st["rows_done"] < before["rows_done"])
    redone = before["rows_done"] - st["rows_done"]
    drain(store)
    rows = all_day_rows()
    check("every row is present", set(rows) == set(expect_rows))
    check("only the rows past the checkpoint were redone, and fold",
          len(rows) == len(expect_rows) + redone and 0 < redone <= 5)
    check("the scaffolding is gone and the counter free",
          not any(os.path.exists(unsynced_file(s)) for s in ("", ".moving", ".plan"))
          and nvm_id(nvm) == 0)
    datastore._CHECKPOINT_BYTES = saved_cp

    print("a torn checkpoint line is ignored, not obeyed")
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    while store.relabel_status()["state"] != "moving":
        store.relabel_step(max_rows=5)
    store.relabel_step(max_rows=8)
    with open(unsynced_file(".moving"), "rb") as f:
        boundary = len(f.readline()) + len(f.readline()) + len(f.readline())
    with open(unsynced_file(".plan"), "a") as f:
        f.write("@%d,2,0,0,%d\n" % (boundary, expect_rows[0][0]))  # a real one
        f.write("@9")                                               # ...and the cut
    hub_clock(BOOT_TS)
    store = reboot()
    check("the complete line before it is what resumes",
          store.relabel_status()["bytes_done"] == boundary)
    drain(store)
    check("and nothing is missing", set(all_day_rows()) == set(expect_rows))

    print("a power cut during the plan pass puts the file back untouched")
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    store.relabel_step(max_rows=7)
    check("mid-plan: claimed, nothing committed",
          os.path.exists(unsynced_file(".moving")) and not os.path.exists(unsynced_file(".plan")))
    hub_clock(BOOT_TS)
    store = reboot()
    check("the file is back as it was", read(unsynced_file()) == snapshot
          and not store.relabel_pending())
    store.boot_id = 3            # (a soft reset: still boot 3's rows to place)
    hub_clock(SYNCED_TS)
    check("and the next sync places every row", relabel_all(
        store, delta, boot_real=boot_real) == 30
          and sorted(all_day_rows()) == expect_rows)

    print("storage going read-only mid-job pauses it, and it picks up again")
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    while store.relabel_status()["state"] != "moving":
        store.relabel_step(max_rows=5)
    store.relabel_step(max_rows=4)
    go_read_only(store)
    at = store.relabel_status()["bytes_done"]
    store.relabel_step(max_rows=4)
    st = store.relabel_status()
    check("a step with the drive gone does nothing but say so",
          st["state"] == "waiting" and st["bytes_done"] == at and store.relabel_pending())
    for _ in range(3):
        store.relabel_step(max_rows=4)
    check("and keeps saying so", store.relabel_status()["bytes_done"] == at)
    check("nothing was written meanwhile",
          len(all_day_rows()) == st["rows_done"] - st["kept"])
    go_writable(store)
    check("the drive back, the job moves on from where it paused",
          store.relabel_step(max_rows=4) and store.relabel_status()["state"] == "moving"
          and store.relabel_status()["bytes_done"] > at)
    drain(store)
    check("and every row is present exactly once",
          sorted(all_day_rows()) == expect_rows)

    print("a step whose rows never reach the card is redone, not skipped")
    # writes go to a buffer, so it is the CLOSE that fails on a card that
    # has filled or been pulled -- and a job that had already counted those
    # rows as done would step straight over them
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    while store.relabel_status()["state"] != "moving":
        store.relabel_step(max_rows=5)
    at = store.relabel_status()["bytes_done"]
    real_open = open

    class _LosesItsWrites:
        def __init__(self, f):
            self._f = f

        def write(self, s):
            return None                       # buffered, and never written

        def close(self):
            self._f.close()
            raise OSError(28, "No space left on device")

    def flaky_open(path, mode="r", *a, **kw):
        f = real_open(path, mode, *a, **kw)
        return _LosesItsWrites(f) if ("a" in mode and path.endswith(".csv")) else f

    datastore.open = flaky_open
    try:
        store.relabel_step(max_rows=4)
    finally:
        del datastore.open
    st = store.relabel_status()
    check("the job did not move past the rows it lost", st["bytes_done"] == at)
    check("and counted none of them: the tally still matches the files",
          len(all_day_rows()) == st["rows_done"] - st["kept"])
    # the 10 s back-off after a failed step is wall-clock: the bench cares,
    # this test does not
    store._job.retry_ms = store._job.probed_ms = 0
    drain(store)
    check("the retry writes them, and every row is present exactly once",
          sorted(all_day_rows()) == expect_rows)

    print("a second sync while the job is still planning is folded into the plan")
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    first = store.relabel_unsynced(delta, boot_real=boot_real)
    check("the sync's own reply already knew the size",
          first == size == store.relabel_status()["bytes_total"])
    store.relabel_step(max_rows=5)
    check("nothing is committed yet, so the nudge joins the correction",
          store.relabel_unsynced(60) == size and not store._relabel_due
          and store._job.offset_s == delta + 60)
    drain(store)
    exact = sorted(ts for ts, _, fl in all_day_rows() if not fl & datastore.FLAG_ESTIMATED)
    check("this boot's rows carry both",
          exact == [BOOT_TS + 400 + 60 * k + delta + 60 for k in range(8)])

    print("...one that lands while it is moving waits its turn, and finds nothing left")
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    while store.relabel_status()["state"] != "moving":
        store.relabel_step(max_rows=5)
    check("the second is deferred behind the first",
          store.relabel_unsynced(60) == 0 and store._relabel_due
          and store._relabel_offset == 60)
    check("the loop finishes the first and clears the debt",
          drain(store) == 30 and not store._relabel_due
          and store.relabel_status()["state"] == "idle")

    print("a day file torn by the power cut is mended before the redo lands")
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    while store.relabel_status()["state"] != "moving":
        store.relabel_step(max_rows=5)
    store.relabel_step(max_rows=3)
    day = store._day_of(expect_rows[0][0])
    with open(day_file(day), "a") as f:
        f.write("%d,local,21." % (expect_rows[3][0]))      # the row the cut tore
    drain(store)
    lines = rows_of(read(day_file(day)))
    check("no line fused with the fragment",
          all(l.count(",") == datastore.CSV_HEADER.count(",") or l.endswith("21.")
              for l in lines))
    check("every row is present", set(all_day_rows()) >= set(expect_rows))

    print("a job paused by a drive the host ejected by itself notices, in time")
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    store.relabel_step(max_rows=5)
    go_read_only(store)
    store.relabel_step(max_rows=5)
    check("paused", store.relabel_status()["state"] == "waiting")
    del store._writable                        # the drive is back; nobody told us
    store.relabel_step(max_rows=5)
    check("not re-probed on every pass", store.relabel_status()["state"] == "waiting")
    saved_rp = datastore._REPROBE_MS
    datastore._REPROBE_MS = 0
    store.relabel_step(max_rows=5)
    check("the next probe finds it and the job moves on",
          store.relabel_status()["state"] == "planning" and not store.read_only)
    datastore._REPROBE_MS = saved_rp
    check("to the end", drain(store) == 30)

    print("...and its probe never takes the drive back from a computer")
    store = restore(snapshot, 3)
    store.allow_usb_release = True
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    store.relabel_step(max_rows=5)
    # h_storage("pc") hands the drive over: read-only from now, no re-probe
    store._writable = lambda root: False
    store.read_only = True
    taken = []
    saved_take = datastore.take_filesystem
    datastore.take_filesystem = lambda *a, **k: taken.append(1) or True
    datastore._REPROBE_MS = 0
    for _ in range(3):
        store.relabel_step(max_rows=5)
    datastore._REPROBE_MS = saved_rp
    check("the job waits; only a flush may release the drive",
          not taken and store.relabel_status()["state"] == "waiting")
    store._pick_root()                         # what a flush's re-probe does
    check("(a flush's probe still would)", len(taken) == 1)
    datastore.take_filesystem = saved_take
    store._usb_released = False
    go_writable(store)
    drain(store)

    print("a job chained behind an adopted one reports the span of both")
    store = restore(snapshot, 3)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(delta, boot_real=boot_real)
    while store.relabel_status()["state"] != "moving":
        store.relabel_step(max_rows=5)
    store.relabel_step(max_rows=5)
    # the power goes; this boot comes up read-only (a PC has the drive),
    # logs a row of its own, then a sync arrives once the drive is back
    hub_clock(BOOT_TS)
    orig = datastore.DataStore._recover_unsynced
    datastore.DataStore._recover_unsynced = lambda self: None
    store = reboot()
    datastore.DataStore._recover_unsynced = orig
    store.record("local", m, ts=BOOT_TS + 60)
    store.flush()
    check("this boot is 4", store.boot_id == 4)
    hub_clock(SYNCED_TS)
    store.relabel_unsynced(SYNCED_TS - (BOOT_TS + 100))
    check("the old plan goes first", store.relabel_status()["state"] == "moving"
          and store._relabel_due)
    drain(store)
    last = store.relabel_status()["last"]
    check("the second job's report reaches back to the first's earliest row",
          last["rows"] == 1 and last["span_s"] == SYNCED_TS - expect_rows[0][0]
          and store.last_relabel == (1, expect_rows[0][0]))

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
