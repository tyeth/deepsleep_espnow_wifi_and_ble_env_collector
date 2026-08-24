#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
ble_smoke.py - BLE smoke test for the ENVHUB collector, via bleak.

Runs on the controller PC/Pi (best on Linux/BlueZ; works on Windows).
Scans for the ENVHUB Nordic-UART advertisement, connects, runs the basic
command matrix, and prints the JSON replies.

    pip install bleak
    python tools/ble_smoke.py            # scan + command matrix
    python tools/ble_smoke.py latest     # single command
    python tools/ble_smoke.py "time now" # sync the hub clock
"""

import asyncio
import json
import sys
import time

from bleak import BleakClient, BleakScanner

UART_SVC = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # write to device
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # notify from device

NAME = "ENVHUB"
DEFAULT_CMDS = ["mem", "latest", "battery", "config", "days", "events"]


async def find_hub(timeout=12):
    print("scanning for %s ..." % NAME)
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name or "").startswith(NAME)
        or UART_SVC in (ad.service_uuids or []),
        timeout=timeout,
    )
    if dev is None:
        raise SystemExit("no %s advertisement found (is BLE mode on?)" % NAME)
    print("found %s [%s]" % (dev.name, dev.address))
    return dev


async def run(cmds):
    dev = await find_hub()
    lines: asyncio.Queue = asyncio.Queue()
    buf = bytearray()

    def on_notify(_, data):
        buf.extend(data)
        while b"\n" in buf:
            line, _, rest = bytes(buf).partition(b"\n")
            buf[:] = rest
            lines.put_nowait(line.decode("utf-8", "replace"))

    client = None
    for attempt in range(1, 4):   # WinRT service discovery often needs a retry
        try:
            client = BleakClient(dev, timeout=30)
            await client.connect()
            break
        except Exception as exc:
            print("connect attempt %d failed: %s" % (attempt, exc))
            try:
                await client.disconnect()
            except Exception:
                pass
            client = None
            await asyncio.sleep(4)
    if client is None:
        raise SystemExit("could not connect after retries")
    try:
        await client.start_notify(UART_TX, on_notify)
        for cmd in cmds:
            if cmd == "time now":
                cmd = "time %d" % int(time.time())
            print("\n>> %s" % cmd)
            await client.write_gatt_char(UART_RX, (cmd + "\n").encode(),
                                         response=False)
            if cmd.startswith("hist "):
                # streamed CSV between #BEGIN/#END
                n = 0
                while True:
                    line = await asyncio.wait_for(lines.get(), 20)
                    if line.startswith("#END"):
                        print("<< %d CSV lines streamed" % n)
                        break
                    if not line.startswith("#BEGIN"):
                        n += 1
                continue
            line = await asyncio.wait_for(lines.get(), 15)
            try:
                print("<<", json.dumps(json.loads(line), indent=1)[:800])
            except ValueError:
                print("<<", line[:200])
        await client.stop_notify(UART_TX)
    finally:
        await client.disconnect()
    print("\nBLE smoke test complete")


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1:] or DEFAULT_CMDS))
