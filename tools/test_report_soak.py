import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

from report_soak import report


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.start = datetime(2026, 10, 22, tzinfo=timezone.utc)

    def at(self, second):
        return (self.start + timedelta(seconds=second)).isoformat()

    def write(self, name, data):
        (self.root/name).write_text(json.dumps(data))

    def lines(self, name, rows):
        (self.root/name).write_text("".join(json.dumps(r)+"\n" for r in rows))

    def radio(self):
        rows = [dict(cycle=i+1, elapsed_s=t, seconds=5.5, wifi=4, ble=20,
                     gc_allocated=2000, gc_free_estimate=70000, utc=self.at(t))
                for i, t in enumerate(range(6, 28800, 30))]
        state = dict(status="passed", started_utc=self.at(0), finished_utc=self.at(28800),
                     duration_s=28800, elapsed_s=28800, cycles=len(rows), failures=[],
                     revision="abc123", identity={"version":"CircuitPython abc123"})
        self.write("status.json", state)
        self.lines("cycles.jsonl", rows)
        return state, rows

    def test_full_radio_evidence(self):
        self.radio()
        result = report(self.root)
        self.assertEqual(result["evidence_verdict"], "consistent")
        self.assertEqual(result["metrics"]["gc_allocated"]["delta"], 0)
        self.assertEqual(len(result["sha256"]), 2)

    def test_early_pass_rejected(self):
        state, _ = self.radio()
        state.update(elapsed_s=1000, finished_utc=self.at(1000))
        self.write("status.json", state)
        self.assertEqual(report(self.root)["evidence_verdict"], "inconsistent")

    def test_count_drift_rejected(self):
        state, _ = self.radio()
        state["cycles"] += 1
        self.write("status.json", state)
        self.assertIn("cycles count differs between status and logs", report(self.root)["issues"])

    def test_corrupted_terminal_log_rejected(self):
        self.radio()
        with (self.root/"cycles.jsonl").open("a") as f:
            f.write('{"cycle":')
        with self.assertRaises(ValueError):
            report(self.root)

    def test_live_append_never_passes(self):
        state, _ = self.radio()
        state["status"] = "running"
        state.pop("finished_utc")
        self.write("status.json", state)
        with (self.root/"cycles.jsonl").open("a") as f:
            f.write('{"cycle":')
        self.assertEqual(report(self.root)["evidence_verdict"], "provisional")

    def test_recorded_failure_preserved(self):
        state, _ = self.radio()
        state.update(status="failed", failures=["Timeout"])
        self.write("status.json", state)
        self.assertEqual(report(self.root)["evidence_verdict"], "inconsistent")

    def test_missing_radio_span_rejected(self):
        state, rows = self.radio()
        rows = rows[20:]
        for i, row in enumerate(rows, 1):
            row["cycle"] = i
        state["cycles"] = len(rows)
        self.write("status.json", state)
        self.lines("cycles.jsonl", rows)
        self.assertIn("scan evidence gap exceeds maximum recorder bound", report(self.root)["issues"])

    def test_three_empty_scans_rejected(self):
        _, rows = self.radio()
        for row in rows[5:8]:
            row["ble"] = 0
        self.lines("cycles.jsonl", rows)
        self.assertIn("three consecutive empty radio scans", report(self.root)["issues"])

    def https(self):
        rows = [dict(cycle=i+1, elapsed_s=t+1, seconds=1, utc=self.at(t),
                     status="passed", tls_version="TLSv1.2",
                     responses=[dict(path=path, status=200, bytes=24, sha256="a"*64)
                                for path in ("/api/latest", "/api/history", "/api/cert")])
                for i, t in enumerate(range(0, 28800, 120))]
        state = dict(status="passed", started_utc=self.at(0), finished_utc=self.at(28800),
                     duration_s=28800, elapsed_s=28800, interval_s=120, cycles=len(rows),
                     errors=0, failures=[], normal_ca_trust=True, hostname_checking=True,
                     host="device.example", leaf_sha256="b"*64)
        self.write("status.json", state)
        self.lines("cycles.jsonl", rows)
        return state, rows

    def test_full_https_and_live_is_provisional(self):
        state, _ = self.https()
        result = report(self.root)
        self.assertEqual(result["evidence_verdict"], "consistent")
        self.assertEqual(result["mode"], "trusted_https")
        state.update(status="running")
        state.pop("finished_utc")
        self.write("status.json", state)
        self.assertEqual(report(self.root)["evidence_verdict"], "provisional")

    def test_https_hidden_failure_or_missing_route_rejected(self):
        for mutation in (lambda r: r.update(status="failed"),
                         lambda r: r["responses"].pop(),
                         lambda r: r["responses"][0].update(status=500)):
            with self.subTest(mutation=mutation):
                _, rows = self.https()
                mutation(rows[10])
                self.lines("cycles.jsonl", rows)
                self.assertEqual(report(self.root)["evidence_verdict"], "inconsistent")

    def test_https_short_sparse_or_untrusted_rejected(self):
        for mutation in (lambda s: s.update(elapsed_s=1000, finished_utc=self.at(1000)),
                         lambda s: s.update(normal_ca_trust=False),
                         lambda s: s.update(hostname_checking=False)):
            with self.subTest(mutation=mutation):
                state, _ = self.https()
                mutation(state)
                self.write("status.json", state)
                self.assertEqual(report(self.root)["evidence_verdict"], "inconsistent")
        state, rows = self.https()
        rows = rows[3:]
        for index, row in enumerate(rows, 1): row["cycle"] = index
        state["cycles"] = len(rows)
        self.write("status.json", state)
        self.lines("cycles.jsonl", rows)
        self.assertIn("HTTPS evidence gap exceeds recorder bound", report(self.root)["issues"])

    def test_https_false_timestamps_rejected(self):
        _, rows = self.https()
        rows[5]["utc"] = self.at(0)
        self.lines("cycles.jsonl", rows)
        self.assertIn("HTTPS timestamp differs from elapsed evidence", report(self.root)["issues"])

    def test_full_application_and_restart_detection(self):
        self.write("manifest.json", {"boards":[{"name":"node"}], "ble_name":"test", "sensor":"sim"})
        messages = [self.at(0) + " collector running; portal: test\n"]
        for second in range(100, 28800, 200):
            for text in ("delivered: hub confirmed", "deep sleep now", "wake: ResetReason.DEEP_SLEEP_ALARM"):
                messages.append(self.at(second)+" "+text+"\n")
        (self.root/"node.log").write_text("".join(messages))
        http = [dict(utc=self.at(t), data={}) for t in range(1, 28800, 30)]
        ble = [dict(utc=self.at(t), kind="ble_ok", data={"mem":{"free":3900000}}) for t in range(1, 28800, 120)]
        self.lines("http.jsonl", http)
        self.lines("ble.jsonl", ble)
        self.write("status.json", dict(status="passed", started_utc=self.at(0), finished_utc=self.at(28800),
                   elapsed_s=28800, duration_s=28800, failures=[], confirmations=144, sleep_requests=144,
                   true_sleep_wakes=144, collector_starts=1, serial_errors=0, http_ok=len(http),
                   http_errors=0, ble_ok=len(ble), ble_errors=0))
        self.assertEqual(report(self.root)["evidence_verdict"], "consistent")
        with (self.root/"node.log").open("a") as f:
            f.write(self.at(28000)+" collector running; portal: test\n")
        self.assertEqual(report(self.root)["evidence_verdict"], "inconsistent")


if __name__ == "__main__":
    unittest.main()
