#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
hil_bench.py - drive the two-devkit bench (C6 hub + S3 node) from the host
they are plugged into (the Pi: `pi@rpi-hil003b`).

Each devkit exposes TWO ports: the chip's native USB (CircuitPython console
and REPL) and a UART bridge (ESP-ROM + IDF debug log, which is where a hard
fault or a wifi/nimble log line shows up). `ports` tells you which is which.

    python3 tools/hil_bench.py ports
    python3 tools/hil_bench.py console /dev/ttyACM1 30
    python3 tools/hil_bench.py keys /dev/ttyACM1 halt|resume|reset
    python3 tools/hil_bench.py confirm            # delivery-confirmation run
    python3 tools/hil_bench.py outage             # hub stops servicing RX

Scenarios print the lines that matter and end with PASS/FAIL, so a run can
be judged without reading the whole console.

Serial rules learned on this bench, applied throughout:
  * DTR must be asserted or CircuitPython writes nothing to its USB console.
  * RTS must NOT move: it resets the C6 USB-Serial/JTAG (rst:0x15).
  * Opening a UART-bridge port resets the board (auto-reset circuit); the
    native USB port re-enumerates when that happens.
"""

import argparse
import re
import sys
import time

import serial
from serial.tools import list_ports

CONSOLE_HINTS = (("USB JTAG", "esp32c6/s3 native USB"),
                 ("DevKitC", "native USB (CircuitPython CDC)"))
UART_HINTS = (("CP2102", "UART bridge"), ("CH34", "UART bridge"),
              ("Single Serial", "UART bridge"))


def open_port(port, timeout=0.2):
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 115200, timeout
    s.dtr = True     # CircuitPython only writes to a console it thinks is open
    s.rts = False    # moving RTS resets the C6 USB-Serial/JTAG
    s.open()
    time.sleep(0.3)
    return s


def cmd_ports(_args):
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        role = "?"
        for hint, what in CONSOLE_HINTS + UART_HINTS:
            if hint.lower() in (p.description or "").lower() or \
               hint.lower() in (p.hwid or "").lower():
                role = what
                break
        print("%-14s %-46s %s" % (p.device, (p.description or "")[:46], role))
    return 0


def capture(port, seconds, out=None, quiet_filter=True):
    """Read a console for N seconds; returns the text (also echoed)."""
    s = open_port(port)
    end = time.time() + seconds
    buf = b""
    try:
        while time.time() < end:
            chunk = s.read(4096)
            if chunk:
                buf += chunk
    finally:
        s.close()
    text = buf.decode("utf-8", "replace")
    text = re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)", "", text)  # title codes
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    if quiet_filter:
        text = "\n".join(l for l in text.splitlines()
                         if not re.match(r"^[WIE] \(\d+\)|^dhcps:|^wifi:", l))
    if out:
        with open(out, "w") as f:
            f.write(text)
    return text


def cmd_console(args):
    print(capture(args.port, args.seconds))
    return 0


def cmd_keys(args):
    s = open_port(args.port, timeout=1)
    try:
        if args.what == "halt":
            s.write(b"\x03\x03")        # stop code.py, stay at the REPL
        elif args.what == "resume":
            s.write(b"\x04")            # Ctrl-D: run code.py again
        else:                           # reset: interrupt, then reload
            s.write(b"\x03\x03")
            time.sleep(1.5)
            s.write(b"\x04")
        time.sleep(1.0)
    finally:
        s.close()
    print("%s -> %s" % (args.what, args.port))
    return 0


def _report(name, checks, log_lines):
    print("\n--- %s" % name)
    for line in log_lines:
        print("   ", line)
    ok = True
    print()
    for label, passed in checks:
        print("  %s  %s" % ("PASS" if passed else "FAIL", label))
        ok = ok and passed
    print("\n%s: %s" % (name, "PASS" if ok else "FAIL"))
    return 0 if ok else 1


def _interesting(text, pattern):
    return [l.strip() for l in text.splitlines() if re.search(pattern, l)]


NODE_PAT = (r"delivered:|bench: resending|stashed reading|retransmitted|"
            r"did not confirm|no MAC ack|read: |wake:")
HUB_PAT = r"sq=|duplicate |could not be sent|failed"


def cmd_confirm(args):
    """Happy path: a reading is confirmed, and identical retries are not
    stored twice. Needs "test_resend" >= 1 in the node's config."""
    cmd_keys(argparse.Namespace(port=args.node, what="reset"))
    node = capture(args.node, args.seconds)
    hub = capture(args.hub, 1)
    lines = _interesting(node, NODE_PAT) + _interesting(hub, HUB_PAT)
    return _report("confirm", [
        ("node saw a confirmation", "delivered: hub confirmed" in node),
        ("node did not have to stash", "stashed reading" not in node),
    ], lines)


def cmd_outage(args):
    """The case the confirmation exists for: the hub's code stops while its
    radio stays up, so the node still gets MAC-layer ACKs and nothing else.
    The reading must be stashed, then retransmitted once the hub is back."""
    cmd_keys(argparse.Namespace(port=args.hub, what="halt"))
    print("hub halted; watching the node for %ds" % args.seconds)
    out = capture(args.node, args.seconds)
    cmd_keys(argparse.Namespace(port=args.hub, what="resume"))
    print("hub resumed; watching for the retransmission")
    back = capture(args.node, args.seconds + 60)
    lines = _interesting(out, NODE_PAT) + ["--- hub back ---"] + \
        _interesting(back, NODE_PAT)
    return _report("outage", [
        ("node refused to count the report as delivered",
         "did not confirm" in out or "no MAC ack" in out),
        ("reading went to the stash", "stashed reading" in out),
        ("stash was retransmitted after the hub returned",
         "retransmitted" in back),
    ], lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default="/dev/ttyACM1", help="C6 console port")
    ap.add_argument("--node", default="/dev/ttyACM2", help="S3 console port")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports").set_defaults(func=cmd_ports)
    c = sub.add_parser("console")
    c.add_argument("port")
    c.add_argument("seconds", type=float, nargs="?", default=20)
    c.set_defaults(func=cmd_console)
    k = sub.add_parser("keys")
    k.add_argument("port")
    k.add_argument("what", choices=("halt", "resume", "reset"))
    k.set_defaults(func=cmd_keys)
    for name, fn in (("confirm", cmd_confirm), ("outage", cmd_outage)):
        s = sub.add_parser(name)
        s.add_argument("--seconds", type=float, default=100)
        s.set_defaults(func=fn)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
