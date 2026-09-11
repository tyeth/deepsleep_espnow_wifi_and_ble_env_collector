# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""Host-side checks for pushing a certificate over BLE (issue #25).

    python tools/test_cert_ble.py

A ~5.5 KB certificate cannot cross the Nordic UART link in one command:
Web Bluetooth refuses a writeValue over 512 bytes, the hub's receive buffer
is 512, and the hub has ~40 KB of heap. It goes as a run of short `cert`
commands instead. This checks the hub end of that -- certstore.Installer
writing pieces straight to disk, and net_ble's parsing of the commands --
and then feeds it the chunks the web app's chunker actually produces, so
the two halves are tested against each other rather than each against its
own idea of the format.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "collector"))

import certstore  # noqa: E402
import net_ble  # noqa: E402

FAILURES = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILURES.append(name)


# A PEM-shaped pair of a realistic size. The bytes are not a real
# certificate -- Installer.finish() parses the DER, which only the hardware
# test can supply -- so the checks here stop at "what arrived is what was
# sent" and the command handling around it.
def sample_pair():
    body = "\n".join("A" * 64 for _ in range(30))
    cert = ("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n" % body) * 2
    key = ("-----BEGIN PRIVATE KEY-----\n%s\n-----END PRIVATE KEY-----\n"
           % "\n".join("B" * 64 for _ in range(25)))
    return cert, key


class FakePortal(net_ble.BleUartPortal):
    """_dispatch and the receive buffer, without a radio under them."""

    def __init__(self, handlers):
        net_ble.BleUartPortal.__init__(self, handlers, enabled=False)
        self.handlers = handlers
        self.sent = []

    def _write_paced(self, data):
        self.sent.append(data)

    def feed(self, chunk):
        """Bytes off the wire, exactly as poll() hands them over."""
        self._rxbuf += chunk
        while b"\n" in self._rxbuf:
            line, self._rxbuf = self._rxbuf.split(b"\n", 1)
            if self._rxdrop:
                self._rxdrop = False
                continue
            self._dispatch(line.decode())
        if len(self._rxbuf) > net_ble._RX_LINE_MAX:
            self._rxbuf = b""
            if not self._rxdrop:
                self._rxdrop = True
                self._send({"err": "line too long (max %d bytes)"
                                   % net_ble._RX_LINE_MAX,
                            "cmds": self._commands()})

    def replies(self):
        out = [json.loads(b.decode()) for b in self.sent]
        self.sent = []
        return out


_REAL_INSTALLER = certstore.Installer


def hub_handler(root):
    """certstore.receive(), pointed at a temp directory instead of /certs."""
    certstore.Installer = lambda _root="/certs": _REAL_INSTALLER(root)
    certstore._rx[0] = None
    return certstore.receive, certstore._rx


JS_CHUNKER = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const m = html.match(/\/\* --- cert helpers:[\s\S]*?\n([\s\S]*?)\/\* --- end cert helpers --- \*\//);
if (!m) { console.error("cert helper block not found in index.html"); process.exit(2); }
const certChunks = new Function("fetch", "AbortSignal", m[1] + "\nreturn certChunks;")(
  null, { timeout: () => undefined });
const { text, max } = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
process.stdout.write(JSON.stringify(certChunks(text, max)));
"""


def js_chunks(text, max_bytes):
    """The web app's own chunker, so both ends are tested against one format."""
    tmp = tempfile.mkdtemp()
    try:
        script = os.path.join(tmp, "chunk.cjs")
        arg = os.path.join(tmp, "arg.json")
        with open(script, "w") as f:
            f.write(JS_CHUNKER)
        with open(arg, "w") as f:
            json.dump({"text": text, "max": max_bytes}, f)
        out = subprocess.run(
            ["node", script, os.path.join(ROOT, "webapp", "index.html"), arg],
            capture_output=True, cwd=ROOT)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.decode()[-500:].strip())
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(tmp)


def main():
    cert, key = sample_pair()

    print("certstore.Installer writes pieces straight through")
    root = tempfile.mkdtemp()
    try:
        rx = certstore.Installer(root)
        for i in range(0, len(cert), 400):
            rx.write("cert", cert[i:i + 400])
        for i in range(0, len(key), 400):
            rx.write("key", key[i:i + 400])
        rx._close()
        with open(os.path.join(root, certstore.CERT + ".new")) as f:
            check("the chain is reassembled byte-for-byte", f.read() == cert)
        with open(os.path.join(root, certstore.KEY + ".new")) as f:
            check("the key is reassembled byte-for-byte", f.read() == key)
        check("bytes written are counted for the client's progress",
              rx.n == len(cert) + len(key))
        check("finish() refuses a chain that is not a certificate",
              certstore.Installer(root).finish() is False)
        # The .new files from the run above are still on disk. A second
        # upload that sends nothing must not be able to install them over a
        # working certificate and report success.
        check("finish() refuses an upload that sent nothing",
              certstore.Installer(root).finish() is False)
        half = certstore.Installer(root)
        half.write("cert", cert)
        check("finish() refuses an upload missing the key",
              half.finish() is False)
        # ...and abort() takes the leftovers with it
        rx2 = certstore.Installer(root)
        rx2.write("key", key)
        rx2.abort()
        check("abort() removes the part-received files",
              not os.path.exists(os.path.join(root, certstore.KEY + ".new")))
    finally:
        shutil.rmtree(root)

    print("net_ble routes the cert commands")
    root = tempfile.mkdtemp()
    try:
        h_cert, state = hub_handler(root)
        p = FakePortal({"cert": h_cert})
        p.feed(b"cert c AAA\n")
        check("a chunk before `cert begin` is refused",
              p.replies()[0].get("err", "").startswith("send `cert begin`"))
        p.feed(b"cert begin\n")
        r = p.replies()[0]
        check("`cert begin` tells the client its chunk budget",
              r.get("ok") and r.get("max") == net_ble.CERT_CHUNK_MAX)
        p.feed(b"cert c -----BEGIN CERTIFICATE-----|AAAA|\n")
        check("a chunk is acknowledged with the byte count",
              p.replies()[0]["n"] == len("-----BEGIN CERTIFICATE-----\nAAAA\n"))
        p.feed(b"cert wat\n")
        check("an unknown step is named in the error",
              "wat" in p.replies()[0]["err"])

        print("a device without the handler says so")
        bare = FakePortal({"latest": lambda: {}})
        bare.feed(b"cert begin\n")
        check("a node answers `not supported on this device`",
              bare.replies()[0]["err"] == "not supported on this device")

        print("an over-long line is reported, not dropped in silence")
        # what the old web app did: one `cert {json}` command, ~6 KB, whose
        # newline is still 5 KB away when the buffer fills
        p2 = FakePortal({"cert": h_cert})
        p2.feed(b'cert {"cert": "' + b"x" * 600)
        check("the hub says the line was too long",
              "line too long" in p2.replies()[0]["err"])
        check("and drops it rather than growing the buffer", p2._rxbuf == b"")
        # the rest of that 5 KB command keeps arriving: it must not produce a
        # reply per overflow, or the client reads a stale error as the answer
        # to whatever it sends next
        for _ in range(8):
            p2.feed(b"y" * 600)
        check("one complaint per over-long line, not one per overflow",
              p2.replies() == [])
        p2.feed(b'"}\ncert begin\n')
        after = p2.replies()
        check("and the next command is answered normally",
              len(after) == 1 and after[0].get("ok") is True)

        print("a disconnect mid-upload drops the part-received file")
        p3 = FakePortal({"cert": h_cert})
        p3.feed(b"cert begin\n")
        p3.feed(b"cert c AAA|\n")
        p3.replies()
        check("the receiver is open before the disconnect", state[0] is not None)
        p3.handlers["cert"]("abort", "")
        check("the receiver is gone after it", state[0] is None)
    finally:
        shutil.rmtree(root)

    print("the web app's chunks and the hub's parser agree")
    root = tempfile.mkdtemp()
    try:
        try:
            chunks_c = js_chunks(cert, net_ble.CERT_CHUNK_MAX)
            chunks_k = js_chunks(key, net_ble.CERT_CHUNK_MAX)
        except (OSError, RuntimeError) as exc:
            print("  SKIP  node unavailable (%s)" % exc)
        else:
            h_cert, state = hub_handler(root)
            p = FakePortal({"cert": h_cert})
            p.feed(b"cert begin\n")
            p.replies()
            longest = 0
            for which, chunks in (("c", chunks_c), ("k", chunks_k)):
                for c in chunks:
                    line = ("cert %s %s\n" % (which, c)).encode()
                    longest = max(longest, len(line))
                    p.feed(line)
            check("every command fits the receive buffer (longest %d)" % longest,
                  longest <= net_ble._RX_LINE_MAX)
            check("...and fits a single 400-byte writeValue", longest <= 400)
            errs = [r for r in p.replies() if "err" in r]
            check("no chunk was refused", not errs)
            p.feed(b"cert end\n")
            # these stub bytes are PEM-shaped but are not a parseable
            # certificate, so `end` must refuse them -- and leave the hub's
            # working certificate alone, which is why the rename is last
            end = p.replies()[0]
            check("a certificate that will not parse is refused",
                  "rejected" in end.get("err", ""))
            check("and the refused upload never became the live certificate",
                  not os.path.exists(os.path.join(root, certstore.CERT)))
            with open(os.path.join(root, certstore.CERT + ".new")) as f:
                check("the chain arrives exactly as the web app sent it",
                      f.read() == cert)
            with open(os.path.join(root, certstore.KEY + ".new")) as f:
                check("the key arrives exactly as the web app sent it",
                      f.read() == key)
    finally:
        shutil.rmtree(root)

    print()
    if FAILURES:
        print("%d check(s) failed:" % len(FAILURES))
        for f in FAILURES:
            print("  -", f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
