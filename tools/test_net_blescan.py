# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""Exercise advertisement reception against the keyword-only _bleio API.

python tools/test_net_blescan.py [path/to/baseline/net_blescan.py]
"""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else ROOT / "collector/net_blescan.py"
sys.path.insert(0, str(ROOT / "collector"))
import envadv


class Adapter:
    enabled = False

    def __init__(self):
        self.calls = []
        self.stops = 0
        self.entries = []

    # Match shared-bindings/_bleio/Adapter.c: all parameters are KW_ONLY.
    def start_scan(self, *, prefixes, buffer_size, timeout, interval, window,
                   minimum_rssi, active):
        self.calls.append(dict(prefixes=prefixes, buffer_size=buffer_size,
                               timeout=timeout, active=active))
        if isinstance(self.entries, Exception):
            raise self.entries
        return iter(self.entries)

    def stop_scan(self):
        self.stops += 1


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("tested_scanner", SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.adapter = Adapter()
        self.clock = SimpleNamespace(monotonic=lambda: 10.0)
        self.module.time = self.clock
        with patch.dict(sys.modules, {"_bleio": SimpleNamespace(adapter=self.adapter)}):
            self.receiver = self.module.AdvReceiver()

    def entry(self, seq):
        return SimpleNamespace(advertisement_bytes=envadv.adv_bytes(
            0x1234, seq, {"co2": 612}, 3.87, "sim"), rssi=-54)

    def test_keyword_contract_decodes_and_deduplicates(self):
        self.adapter.entries = [self.entry(7), self.entry(7), self.entry(8)]
        readings = list(self.receiver.poll())
        self.assertEqual(len(readings), 2)
        self.assertEqual([row[0] for row in readings], [envadv.src_for(0x1234)] * 2)
        self.assertEqual([row[2] for row in readings], [-54, -54])
        self.assertEqual(self.receiver.rx_count, 2)
        self.assertEqual(self.receiver.dup_count, 1)
        self.assertIsNone(self.receiver.last_error)
        self.assertEqual(self.adapter.calls[0]["prefixes"], envadv.PREFIX)
        self.assertFalse(self.adapter.calls[0]["active"])
        self.assertEqual(self.adapter.stops, 1)

    def test_scan_throttle_and_cleanup_on_consumer_close(self):
        self.adapter.entries = [self.entry(1), self.entry(2)]
        stream = self.receiver.poll()
        self.assertEqual(next(stream)[0], envadv.src_for(0x1234))
        stream.close()
        self.assertEqual(self.adapter.stops, 1)
        self.assertEqual(list(self.receiver.poll()), [])
        self.assertEqual(len(self.adapter.calls), 1)
        self.clock.monotonic = lambda: 16.0
        self.assertEqual(len(list(self.receiver.poll())), 1)
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertEqual(self.adapter.stops, 2)

    def test_scan_error_is_reported_and_stopped(self):
        self.adapter.entries = OSError("controller busy")
        self.assertEqual(list(self.receiver.poll()), [])
        self.assertIn("OSError", self.receiver.last_error)
        self.assertIn("controller busy", self.receiver.last_error)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.adapter.stops, 1)


if __name__ == "__main__":
    unittest.main()
