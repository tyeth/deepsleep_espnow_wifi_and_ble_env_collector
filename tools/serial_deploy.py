#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
serial_deploy.py - copy files onto a CircuitPython board over the serial
REPL. Needed for boards with no USB mass storage (ESP32-C6 Feather!).

Usage:
  python tools/serial_deploy.py COM4 collector/*.py collector/config.json
  python tools/serial_deploy.py COM4 --dest /www webapp/index.html
  python tools/serial_deploy.py COM4 --ls          # list board files

Uses raw REPL (Ctrl-A), which CircuitPython supports (it's how Thonny
talks to boards). Files are sent base64-encoded in 512-byte chunks.

STATUS: written 2026-08-24, not yet exercised against the C6 (board was
awaiting a physical reset out of download mode). Test before trusting.
"""

import argparse
import base64
import os
import sys
import time

import serial  # pyserial

CHUNK = 3072        # bytes per raw-REPL write (see put_file)
RAW_ON = b"\x01"    # Ctrl-A
RAW_OFF = b"\x02"   # Ctrl-B
INTERRUPT = b"\x03"
EOT = b"\x04"


class Repl:
    def __init__(self, port, baud=115200):
        # Open without asserting RTS: on the ESP32-C6's USB-Serial/JTAG port the default
        # DTR+RTS toggle at open resets the chip (rst:0x15). DTR alone is needed so
        # CircuitPython treats the console as connected.
        self.s = serial.Serial()
        self.s.port, self.s.baudrate, self.s.timeout = port, baud, 2
        self.s.dtr = True
        self.s.rts = False
        self.s.open()
        time.sleep(0.3)
        self.s.reset_input_buffer()

    def _read_until(self, token, timeout=10):
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
            chunk = self.s.read(256)
            if chunk:
                buf += chunk
                if token in buf:
                    return buf
        raise TimeoutError("waiting for %r, got %r" % (token, buf[-200:]))

    def enter_raw(self):
        self.s.write(INTERRUPT + INTERRUPT)
        # Wait for the normal prompt: with wifi/BLE up, teardown after Ctrl-C can take
        # well over a second and a Ctrl-A sent too early is silently dropped.
        last = None
        for _ in range(10):
            time.sleep(0.5)
            self.s.reset_input_buffer()
            self.s.write(RAW_ON)
            try:
                self._read_until(b"raw REPL", timeout=1.5)
                return
            except TimeoutError as exc:
                last = exc
        raise last

    def exit_raw(self):
        self.s.write(RAW_OFF)

    def exec(self, code, timeout=20):
        """Run code in raw mode; returns stdout, raises on traceback."""
        self.s.write(code.encode() + EOT)
        out = self._read_until(EOT + EOT, timeout=timeout)
        # raw repl frames: "OK<stdout>\x04<stderr>\x04>"
        body = out.split(b"OK", 1)[-1]
        stdout, _, rest = body.partition(EOT)
        stderr = rest.split(EOT)[0]
        if stderr.strip():
            raise RuntimeError(stderr.decode("utf-8", "replace"))
        return stdout.decode("utf-8", "replace")

    def close(self):
        self.s.close()


def put_file(repl, local_path, remote_path):
    size = os.path.getsize(local_path)
    print("-> %s (%d bytes) -> %s" % (local_path, size, remote_path))
    remote_dir = remote_path.rsplit("/", 1)[0]
    if remote_dir and remote_dir != "":
        repl.exec(
            "import os\n"
            "p=''\n"
            "for part in %r.split('/'):\n"
            "    if not part: continue\n"
            "    p += '/' + part\n"
            "    try: os.mkdir(p)\n"
            "    except OSError: pass\n" % remote_dir
        )
    repl.exec("import binascii\nf=open(%r,'wb')" % remote_path)
    with open(local_path, "rb") as f:
        sent = 0
        while True:
            # each chunk is one raw-REPL round trip, so the chunk size sets
            # the throughput: 512B managed ~300B/s on the C6's USB-Serial/
            # JTAG (a 48KB code.py took ~3 minutes), 3KB is ~4x that and
            # still well inside the REPL's input handling
            chunk = f.read(CHUNK)
            if not chunk:
                break
            b64 = base64.b64encode(chunk).decode()
            repl.exec("f.write(binascii.a2b_base64('%s'))" % b64)
            sent += len(chunk)
            print("   %d/%d\r" % (sent, size), end="")
    repl.exec("f.close()")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--dest", default="/", help="remote directory (default /)")
    ap.add_argument("--ls", action="store_true", help="list files and exit")
    ap.add_argument("--reset", action="store_true",
                    help="soft-reboot (ctrl-D) after deploy")
    args = ap.parse_args()

    repl = Repl(args.port)
    repl.enter_raw()
    try:
        if args.ls:
            print(repl.exec(
                "import os\n"
                "def walk(p):\n"
                "    for f in os.listdir(p):\n"
                "        fp=(p+'/'+f).replace('//','/')\n"
                "        st=os.stat(fp)\n"
                "        print(fp, st[6])\n"
                "        if st[0] & 0x4000: walk(fp)\n"
                "walk('/')"
            ))
            return
        for path in args.files:
            name = os.path.basename(path.rstrip("/\\"))
            remote = (args.dest.rstrip("/") + "/" + name).replace("//", "/")
            if os.path.isdir(path):
                # push a whole tree (lib/adafruit_ble, www/, certs/ ...)
                for root, _dirs, files in os.walk(path):
                    rel = os.path.relpath(root, path).replace("\\", "/")
                    target = remote if rel == "." else remote + "/" + rel
                    for fname in sorted(files):
                        put_file(repl, os.path.join(root, fname),
                                 target + "/" + fname)
            else:
                put_file(repl, path, remote)
    finally:
        repl.exit_raw()
        if args.reset:
            repl.s.write(EOT)
        repl.close()
    print("done")


if __name__ == "__main__":
    main()
